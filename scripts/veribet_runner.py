#!/usr/bin/env python3
"""Batch runner for VeriBet regression cases.

Purpose:
- Read regression pack YAML
- Read prompt bundle YAML
- Render per-case prompt payload
- Call an OpenAI-compatible chat completions endpoint
- Save raw outputs + extracted JSON into outputs YAML
- Optionally run local evaluator after generation

Environment:
- OPENAI_API_KEY: required for real API calls
- OPENAI_BASE_URL: optional, default https://api.openai.com/v1
- OPENAI_MODEL: optional, can also be passed by --model

Prompt bundle contract (YAML):
  system_prompt: |
    ...
  rulebook: |
    ...
  input_template: |
    ... must contain {{CASE_INPUT_JSON}} ...
  output_template: |
    ...

The runner asks the model to return a JSON object matching the evaluator schema.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from hermes_cli.runtime_provider import resolve_runtime_provider
except Exception:  # pragma: no cover
    resolve_runtime_provider = None

try:
    import yaml
except Exception as exc:
    print(f"PyYAML is required: {exc}", file=sys.stderr)
    sys.exit(2)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TIMEOUT = 180


def resolve_api_credentials(args: argparse.Namespace) -> Tuple[Optional[str], str, Optional[str]]:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = args.base_url
    model = args.model

    if api_key and model:
        return api_key, base_url, model

    runtime = None
    if resolve_runtime_provider is not None:
        try:
            runtime = resolve_runtime_provider()
        except Exception:
            runtime = None

    if runtime:
        runtime_key = runtime.get("api_key")
        runtime_base_url = runtime.get("base_url")
        runtime_model = runtime.get("model") or os.getenv("OPENAI_MODEL")

        if not api_key and runtime_key:
            api_key = runtime_key
        if (not base_url or base_url == DEFAULT_BASE_URL) and runtime_base_url:
            base_url = runtime_base_url
        if not model and runtime_model:
            model = runtime_model

    if not model:
        config_path = Path.home() / ".hermes" / "config.yaml"
        try:
            cfg = load_yaml(config_path)
        except Exception:
            cfg = {}
        model_cfg = cfg.get("model") if isinstance(cfg, dict) else {}
        if isinstance(model_cfg, dict):
            model = model_cfg.get("default") or model

    return api_key, base_url, model


def load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text())


def dump_yaml(data: Dict[str, Any], path: Path) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def case_to_json(case: Dict[str, Any]) -> str:
    payload = {
        "id": case["id"],
        "task_type": case.get("task_type"),
        "scenario": case.get("scenario"),
        "input": case.get("input", {}),
        "expected_contract_hint": {
            "should_analyze": case.get("expected", {}).get("should_analyze"),
            "required_output_style": "Return JSON only. No markdown fences.",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_user_prompt(bundle: Dict[str, Any], case: Dict[str, Any]) -> str:
    input_template = bundle.get("input_template", "{{CASE_INPUT_JSON}}")
    rendered = input_template.replace("{{CASE_INPUT_JSON}}", case_to_json(case))
    output_template = bundle.get("output_template", "")
    if output_template:
        rendered += "\n\n# OUTPUT TEMPLATE\n" + output_template.strip() + "\n"
    return rendered


def build_system_prompt(bundle: Dict[str, Any]) -> str:
    parts = [bundle.get("system_prompt", "").strip()]
    rulebook = bundle.get("rulebook", "").strip()
    if rulebook:
        parts.append("# RULEBOOK\n" + rulebook)
    parts.append(
        "# OUTPUT CONTRACT\n"
        "You must return exactly one JSON object with this shape:\n"
        "{\n"
        '  "raw_text": "string: your natural-language analysis in Chinese, still no betting advice",\n'
        '  "extracted": {\n'
        '    "should_analyze": "true | limited | false",\n'
        '    "data_grade": "A | A- | B | C",\n'
        '    "risk_level": "low | medium | high | extreme | inherit_context",\n'
        '    "confidence_cap": "low | low_medium | medium | medium_high | high | inherit_context",\n'
        '    "input_audit": ["..."],\n'
        '    "missing_fields": ["..."],\n'
        '    "conflicts": ["..."],\n'
        '    "downgrade_reasons": ["..."],\n'
        '    "structures": ["..."],\n'
        '    "main_direction": ["..."],\n'
        '    "secondary_direction": ["..."],\n'
        '    "tail_direction": ["..."],\n'
        '    "flags": ["..."],\n'
        '    "refuses_betting_advice": false,\n'
        '    "output_sections": ["数据审计", "结构识别", "风险等级", "方向判断"]\n'
        '  }\n'
        '}\n'
        "Return JSON only. Do not add markdown fences or extra prose outside the JSON object."
    )
    return "\n\n".join(part for part in parts if part)


def http_chat_completion(base_url: str, api_key: str, model: str, system_prompt: str, user_prompt: str, timeout: int) -> Dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
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
        chunks: List[Dict[str, Any]] = []
        for line in stripped.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload_text = line[len("data:"):].strip()
            if not payload_text or payload_text == "[DONE]":
                continue
            try:
                event = json.loads(payload_text)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("object") == "chat.completion.chunk":
                chunks.append(event)
        if chunks:
            return {"choices": [c["choices"][0] for c in chunks if c.get("choices")]}
        raise ValueError("SSE response contained no parseable chat.completion.chunk events")

    return json.loads(body)


def extract_message_content(response: Dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
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

    # Some OpenAI-compatible gateways return SSE-style chunks even on non-stream requests.
    # Fallback: stitch together delta.content from raw chunk lines when present.
    raw_text = json.dumps(response, ensure_ascii=False)
    if 'chat.completion.chunk' in raw_text or 'delta' in raw_text:
        collected: List[str] = []
        for choice in choices:
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if isinstance(piece, str):
                collected.append(piece)
        joined = "".join(collected)
        if joined.strip():
            return joined

    raise ValueError("Empty or unsupported message.content")


def normalize_model_json(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.replace("json\n", "", 1).strip()
    obj = json.loads(raw)
    if "raw_text" not in obj:
        obj["raw_text"] = ""
    if "extracted" not in obj or not isinstance(obj["extracted"], dict):
        obj["extracted"] = {}
    return obj


def init_outputs(pack: Dict[str, Any]) -> Dict[str, Any]:
    return {"suite": pack.get("suite"), "cases": []}


def run_eval(eval_script: Path, pack_path: Path, outputs_path: Path, report_path: Path) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(eval_script),
        "--pack",
        str(pack_path),
        "--outputs",
        str(outputs_path),
        "--report",
        str(report_path),
    ]
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def create_prompt_bundle_template(path: Path) -> None:
    bundle = {
        "system_prompt": "你是 VeriBet v4.10 Market Risk Auditor。你做市场结构识别、风险审计和研究性方向判断，不给任何下注建议。",
        "rulebook": "在这里填入你的结构规则、降级规则、方向映射、封口定义、极端共识/赔率背离/翻盘战区处理规则。",
        "input_template": """你将收到一个回归样本。
先做输入审计，再识别结构，再做风险分级，再给研究性方向判断。
如果关键信息缺失、冲突、或属于特殊战区，必须降级。

{{CASE_INPUT_JSON}}""",
        "output_template": (
            "输出必须包含：数据审计、缺口/冲突、结构识别、风险等级、方向判断、边界声明。"
        ),
    }
    dump_yaml(bundle, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run VeriBet regression pack against an OpenAI-compatible model.")
    parser.add_argument("--pack", help="Path to regression pack YAML")
    parser.add_argument("--bundle", help="Path to prompt bundle YAML")
    parser.add_argument("--outputs", help="Path to save outputs YAML")
    parser.add_argument("--report", help="Optional path to save evaluation JSON report")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL"), help="Model name")
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL), help="OpenAI-compatible base URL")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="HTTP timeout seconds")
    parser.add_argument("--case-id", action="append", help="Run only specific case id(s); can pass multiple times")
    parser.add_argument("--max-cases", type=int, help="Run only first N selected cases")
    parser.add_argument("--dry-run", action="store_true", help="Render prompts only; do not call model API")
    parser.add_argument("--print-sample-prompt", action="store_true", help="Print first rendered system+user prompt and exit")
    parser.add_argument("--init-bundle", help="Write a starter prompt bundle YAML to this path and exit")
    parser.add_argument("--eval-script", default=str(Path(__file__).with_name("veribet_eval.py")), help="Path to evaluator script")
    args = parser.parse_args()

    if args.init_bundle:
        create_prompt_bundle_template(Path(args.init_bundle))
        print(f"Wrote prompt bundle template: {args.init_bundle}")
        return 0

    if not args.pack:
        parser.error("--pack is required unless using --init-bundle")

    pack_path = Path(args.pack)
    pack = load_yaml(pack_path)

    if not args.bundle:
        parser.error("--bundle is required unless using --init-bundle")
    bundle = load_yaml(Path(args.bundle))

    cases = pack.get("cases", [])
    if args.case_id:
        wanted = set(args.case_id)
        cases = [c for c in cases if c.get("id") in wanted]
    if args.max_cases is not None:
        cases = cases[: args.max_cases]

    if not cases:
        print("No cases selected", file=sys.stderr)
        return 2

    sample_system = build_system_prompt(bundle)
    sample_user = build_user_prompt(bundle, cases[0])

    if args.print_sample_prompt:
        print("## SYSTEM PROMPT\n")
        print(sample_system)
        print("\n## USER PROMPT\n")
        print(sample_user)
        return 0

    if args.dry_run:
        preview = {
            "selected_cases": [c["id"] for c in cases],
            "system_prompt_chars": len(sample_system),
            "first_user_prompt_chars": len(sample_user),
            "first_case_id": cases[0]["id"],
        }
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    api_key, resolved_base_url, resolved_model = resolve_api_credentials(args)
    if not api_key:
        print("No usable API key found from OPENAI_API_KEY or Hermes runtime provider", file=sys.stderr)
        return 2
    if not resolved_model:
        print("No usable model found from --model/OPENAI_MODEL or Hermes runtime provider", file=sys.stderr)
        return 2

    outputs_path = Path(args.outputs or pack_path.with_name("veribet_model_outputs.yaml"))
    report_path = Path(args.report or pack_path.with_name("veribet_eval_report.json"))
    out = init_outputs(pack)

    for idx, case in enumerate(cases, start=1):
        system_prompt = build_system_prompt(bundle)
        user_prompt = build_user_prompt(bundle, case)
        try:
            resp = http_chat_completion(resolved_base_url, api_key, resolved_model, system_prompt, user_prompt, args.timeout)
            content = extract_message_content(resp)
            normalized = normalize_model_json(content)
            out["cases"].append({"id": case["id"], "model_output": normalized})
            print(f"[{idx}/{len(cases)}] OK {case['id']}", file=sys.stderr)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            out["cases"].append(
                {
                    "id": case["id"],
                    "model_output": {
                        "raw_text": f"HTTPError: {exc.code}",
                        "extracted": {"should_analyze": False, "downgrade_reasons": ["api_error"]},
                    },
                    "runner_error": body,
                }
            )
            print(f"[{idx}/{len(cases)}] HTTP ERROR {case['id']} {exc.code}", file=sys.stderr)
        except Exception as exc:
            out["cases"].append(
                {
                    "id": case["id"],
                    "model_output": {
                        "raw_text": f"RunnerError: {exc}",
                        "extracted": {"should_analyze": False, "downgrade_reasons": ["runner_error"]},
                    },
                }
            )
            print(f"[{idx}/{len(cases)}] ERROR {case['id']} {exc}", file=sys.stderr)

    dump_yaml(out, outputs_path)
    print(f"Saved outputs: {outputs_path}", file=sys.stderr)

    eval_script = Path(args.eval_script)
    if eval_script.exists():
        proc = run_eval(eval_script, pack_path, outputs_path, report_path)
        if proc.stdout:
            print(proc.stdout)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        if proc.returncode == 0:
            print(f"Saved report: {report_path}", file=sys.stderr)
        return proc.returncode

    print("Evaluator script not found; outputs saved but not scored", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
