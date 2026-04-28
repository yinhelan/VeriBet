#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception as exc:
    print(f"PyYAML is required: {exc}", file=sys.stderr)
    raise SystemExit(2)

ALLOWED_SHOULD_ANALYZE = {"true", "limited", "false"}
ALLOWED_DATA_GRADE = {"A", "A-", "B", "C", "inherit_context"}
ALLOWED_RISK_LEVEL = {"low", "medium", "high", "extreme", "inherit_context"}
ALLOWED_CONFIDENCE_CAP = {"low", "low_medium", "medium", "medium_high", "high", "inherit_context"}

REQUIRED_EXTRACTED_KEYS = [
    "should_analyze",
    "data_grade",
    "risk_level",
    "confidence_cap",
    "input_audit",
    "missing_fields",
    "conflicts",
    "downgrade_reasons",
    "structures",
    "main_direction",
    "secondary_direction",
    "tail_direction",
    "flags",
    "refuses_betting_advice",
    "output_sections",
]


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(data: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_system_prompt(bundle: dict[str, Any]) -> str:
    system_prompt = (bundle.get("system_prompt") or "").strip()
    rulebook = (bundle.get("rulebook") or "").strip()
    output_contract = """
# OUTPUT CONTRACT
You must return exactly one JSON object with this shape:
{
  "raw_text": "string: your natural-language analysis in Chinese, still no betting advice",
  "extracted": {
    "should_analyze": "true | limited | false",
    "data_grade": "A | A- | B | C | inherit_context",
    "risk_level": "low | medium | high | extreme | inherit_context",
    "confidence_cap": "low | low_medium | medium | medium_high | high | inherit_context",
    "input_audit": ["..."],
    "missing_fields": ["..."],
    "conflicts": ["..."],
    "downgrade_reasons": ["..."],
    "structures": ["..."],
    "main_direction": ["..."],
    "secondary_direction": ["..."],
    "tail_direction": ["..."],
    "flags": ["..."],
    "refuses_betting_advice": false,
    "output_sections": ["数据审计", "结构识别", "风险等级", "方向判断"]
  }
}
Return JSON only. Do not add markdown fences or extra prose outside the JSON object.
""".strip()
    parts = [system_prompt]
    if rulebook:
        parts.append("# RULEBOOK\n" + rulebook)
    parts.append(output_contract)
    return "\n\n".join([p for p in parts if p])


def build_user_prompt(bundle: dict[str, Any], match_input: dict[str, Any]) -> str:
    input_template = bundle.get("input_template", "{{CASE_INPUT_JSON}}")
    case_like_payload = {
        "id": "LIVE-001",
        "task_type": "pre_match",
        "scenario": "live_inference",
        "input": match_input,
        "expected_contract_hint": {
            "should_analyze": "true",
            "required_output_style": "Return JSON only. No markdown fences.",
        },
    }
    rendered = input_template.replace(
        "{{CASE_INPUT_JSON}}",
        json.dumps(case_like_payload, ensure_ascii=False, indent=2),
    )
    output_template = (bundle.get("output_template") or "").strip()
    if output_template:
        rendered += "\n\n# OUTPUT TEMPLATE\n" + output_template
    return rendered


def call_chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    stripped = body.strip()
    if stripped.startswith("data:"):
        chunks: list[dict[str, Any]] = []
        for line in stripped.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            text = line[len("data:"):].strip()
            if not text or text == "[DONE]":
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("object") == "chat.completion.chunk":
                chunks.append(event)
        return {"choices": [c["choices"][0] for c in chunks if c.get("choices")]}
    return json.loads(body)


def is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code in {408, 429}
    if isinstance(exc, urllib.error.URLError):
        return True
    message = str(exc).lower()
    retry_signals = [
        "timed out",
        "timeout",
        "connection reset",
        "remote end closed connection",
        "unexpected eof",
        "temporarily unavailable",
    ]
    return any(signal in message for signal in retry_signals)


def extract_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise ValueError("No choices in model response")
    first = choices[0]
    message = first.get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        joined = "".join(texts)
        if joined.strip():
            return joined
    collected = []
    for choice in choices:
        delta = choice.get("delta") or {}
        piece = delta.get("content")
        if isinstance(piece, str):
            collected.append(piece)
    joined = "".join(collected)
    if joined.strip():
        return joined
    raise ValueError("Empty or unsupported message.content")


def normalize_model_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].lstrip()
    obj = json.loads(text)
    if "raw_text" not in obj:
        obj["raw_text"] = ""
    if "extracted" not in obj or not isinstance(obj["extracted"], dict):
        obj["extracted"] = {}
    return obj


def validate_result(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    extracted = result.get("extracted")
    if not isinstance(extracted, dict):
        return ["extracted 不是对象"]
    for key in REQUIRED_EXTRACTED_KEYS:
        if key not in extracted:
            errors.append(f"缺少字段: extracted.{key}")
    if extracted.get("should_analyze") not in ALLOWED_SHOULD_ANALYZE:
        errors.append(f"非法 should_analyze: {extracted.get('should_analyze')}")
    if extracted.get("data_grade") not in ALLOWED_DATA_GRADE:
        errors.append(f"非法 data_grade: {extracted.get('data_grade')}")
    if extracted.get("risk_level") not in ALLOWED_RISK_LEVEL:
        errors.append(f"非法 risk_level: {extracted.get('risk_level')}")
    if extracted.get("confidence_cap") not in ALLOWED_CONFIDENCE_CAP:
        errors.append(f"非法 confidence_cap: {extracted.get('confidence_cap')}")
    for key in [
        "input_audit",
        "missing_fields",
        "conflicts",
        "downgrade_reasons",
        "structures",
        "main_direction",
        "secondary_direction",
        "tail_direction",
        "flags",
        "output_sections",
    ]:
        if key in extracted and not isinstance(extracted.get(key), list):
            errors.append(f"{key} 必须是数组")
    if "refuses_betting_advice" in extracted and not isinstance(extracted.get("refuses_betting_advice"), bool):
        errors.append("refuses_betting_advice 必须是布尔值")
    if extracted.get("should_analyze") == "limited" and extracted.get("confidence_cap") in {"medium_high", "high"}:
        errors.append("should_analyze=limited 但 confidence_cap 过高")
    if extracted.get("should_analyze") == "false" and extracted.get("main_direction"):
        errors.append("should_analyze=false 但 main_direction 非空")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Run VeriBet live inference against an OpenAI-compatible model.")
    parser.add_argument("--bundle", required=True, help="Path to prompt bundle YAML")
    parser.add_argument("--input", required=True, help="Path to live match input JSON")
    parser.add_argument("--output", help="Optional path to save normalized result JSON")
    parser.add_argument("--debug-prompt", action="store_true", help="Print rendered prompts and exit")
    parser.add_argument("--timeout", type=int, default=180, help="HTTP timeout seconds")
    parser.add_argument("--retries", type=int, default=2, help="Retry count for transient network/API failures")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="Base delay seconds between retries")
    args = parser.parse_args()

    bundle = load_yaml(Path(args.bundle))
    match_input = load_json(Path(args.input))

    system_prompt = build_system_prompt(bundle)
    user_prompt = build_user_prompt(bundle, match_input)
    if args.debug_prompt:
        print("## SYSTEM PROMPT\n")
        print(system_prompt)
        print("\n## USER PROMPT\n")
        print(user_prompt)
        return 0

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("OPENAI_MODEL")
    if not api_key:
        print("OPENAI_API_KEY 未设置", file=sys.stderr)
        return 2
    if not model:
        print("OPENAI_MODEL 未设置", file=sys.stderr)
        return 2

    attempts = max(1, args.retries + 1)
    last_error_payload: dict[str, Any] | None = None
    last_exit_code = 4

    for attempt in range(1, attempts + 1):
        try:
            response = call_chat_completion(
                base_url=base_url,
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                timeout=args.timeout,
            )
            content = extract_message_content(response)
            normalized = normalize_model_json(content)
            validation_errors = validate_result(normalized)
            final_payload = {
                "ok": len(validation_errors) == 0,
                "validation_errors": validation_errors,
                "result": normalized,
                "attempts_used": attempt,
            }
            if args.output:
                dump_json(final_payload, Path(args.output))
            print(json.dumps(final_payload, ensure_ascii=False, indent=2))
            return 0 if not validation_errors else 1
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error_payload = {
                "ok": False,
                "error_type": "http_error",
                "status_code": exc.code,
                "body": body,
                "attempts_used": attempt,
            }
            last_exit_code = 3
            if attempt < attempts and is_retryable_error(exc):
                time.sleep(args.retry_delay * attempt)
                continue
            print(json.dumps(last_error_payload, ensure_ascii=False, indent=2), file=sys.stderr)
            return last_exit_code
        except Exception as exc:
            last_error_payload = {
                "ok": False,
                "error_type": "runtime_error",
                "message": str(exc),
                "attempts_used": attempt,
            }
            last_exit_code = 4
            if attempt < attempts and is_retryable_error(exc):
                time.sleep(args.retry_delay * attempt)
                continue
            print(json.dumps(last_error_payload, ensure_ascii=False, indent=2), file=sys.stderr)
            return last_exit_code

    if last_error_payload is not None:
        print(json.dumps(last_error_payload, ensure_ascii=False, indent=2), file=sys.stderr)
    return last_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
