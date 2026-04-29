#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from veribet_live import (
    build_system_prompt,
    build_user_prompt,
    call_chat_completion,
    extract_message_content,
    is_retryable_error,
    load_yaml,
    normalize_model_json,
    validate_result,
)
from veribet_postmortem import (
    infer_winner_from_score,
    matches_direction,
    normalize_result_label,
)
from veribet_rule_proposer import make_candidate

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = ROOT_DIR / "prompts" / "veribet_prompt_bundle_v412_candidate.yaml"
DEFAULT_ENV = ROOT_DIR / ".env"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_repo_path(value: str, *, create_parent: bool = False) -> Path:
    raw = Path(value)
    path = raw if raw.is_absolute() else (ROOT_DIR / raw)
    path = path.resolve()
    try:
        path.relative_to(ROOT_DIR)
    except ValueError as exc:
        raise ValueError(f"path must stay inside repo root: {value}") from exc
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def analyze_match(
    *,
    match_input: dict[str, Any],
    bundle_path: Path = DEFAULT_BUNDLE,
    timeout: int = 180,
    retries: int = 2,
    retry_delay: float = 1.5,
) -> dict[str, Any]:
    bundle = load_yaml(bundle_path)
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("OPENAI_MODEL")

    if not api_key:
        raise ValueError("OPENAI_API_KEY 未设置")
    if not model:
        raise ValueError("OPENAI_MODEL 未设置")

    system_prompt = build_system_prompt(bundle)
    user_prompt = build_user_prompt(bundle, match_input)
    max_attempts = max(retries, 0) + 1

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = call_chat_completion(
                base_url=base_url,
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                timeout=timeout,
            )
            content = extract_message_content(response)
            normalized = normalize_model_json(content)
            validation_errors = validate_result(normalized)
            return {
                "ok": len(validation_errors) == 0,
                "validation_errors": validation_errors,
                "result": normalized,
                "attempts_used": attempt,
                "model": model,
                "base_url": base_url,
                "bundle": str(bundle_path),
            }
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not is_retryable_error(exc):
                break
            time.sleep(retry_delay)

    assert last_exc is not None
    raise last_exc


def discover_input_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.glob("*.json") if p.is_file())


def analyze_batch(
    *,
    named_inputs: list[tuple[str, dict[str, Any]]],
    bundle_path: Path = DEFAULT_BUNDLE,
    timeout: int = 180,
    retries: int = 2,
    retry_delay: float = 1.5,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    failed = 0

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    for input_name, match_input in named_inputs:
        item: dict[str, Any] = {
            "input_name": input_name,
        }
        try:
            result = analyze_match(
                match_input=match_input,
                bundle_path=bundle_path,
                timeout=timeout,
                retries=retries,
                retry_delay=retry_delay,
            )
            item.update({
                "ok": result.get("ok", False),
                "validation_errors": result.get("validation_errors", []),
                "attempts_used": result.get("attempts_used", 1),
                "result": result.get("result"),
            })
            if output_dir is not None:
                output_path = output_dir / f"{Path(input_name).stem}.result.json"
                dump_json(output_path, result)
                item["saved_output"] = str(output_path)
            if not item["ok"]:
                failed += 1
        except Exception as exc:
            failed += 1
            item.update({
                "ok": False,
                "error": str(exc),
            })
        results.append(item)

    return {
        "ok": failed == 0,
        "total_inputs": len(named_inputs),
        "failed_inputs": failed,
        "results": results,
        "bundle": str(bundle_path),
    }


def build_review(
    *,
    match_input: dict[str, Any],
    match_input_file: str,
    live_result: dict[str, Any],
    result_file: str,
    ft_score: str,
    ht_score: str = "",
    result_label: str = "",
    tags: list[str] | None = None,
    judgement: str = "",
    rule_delta: str = "",
    analyst: str = "",
    source: str = "api_review",
) -> dict[str, Any]:
    extracted = ((live_result.get("result") or {}).get("extracted") or {})
    match_id = Path(match_input_file).stem if match_input_file else f"api_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    winner = normalize_result_label(result_label) if result_label else infer_winner_from_score(ft_score)

    main_direction = extracted.get("main_direction") or []
    secondary_direction = extracted.get("secondary_direction") or []
    tail_direction = extracted.get("tail_direction") or []

    return {
        "match_id": match_id,
        "match_input_file": match_input_file,
        "result_file": result_file,
        "actual_result": {
            "ft_score": ft_score,
            "ht_score": ht_score or "",
        },
        "result_label": {
            "winner": winner,
            "hit_main_direction": matches_direction(winner, main_direction),
            "hit_secondary_direction": matches_direction(winner, secondary_direction),
            "hit_tail_direction": matches_direction(winner, tail_direction),
        },
        "veribet_summary": {
            "should_analyze": extracted.get("should_analyze"),
            "data_grade": extracted.get("data_grade"),
            "risk_level": extracted.get("risk_level"),
            "confidence_cap": extracted.get("confidence_cap"),
            "structures": extracted.get("structures") or [],
            "main_direction": main_direction,
            "secondary_direction": secondary_direction,
            "tail_direction": tail_direction,
            "flags": extracted.get("flags") or [],
            "raw_text": (live_result.get("result") or {}).get("raw_text", ""),
        },
        "postmortem_tags": tags or [],
        "human_judgement": judgement,
        "suggested_rule_delta": rule_delta,
        "notes": {
            "analyst": analyst,
            "source": source,
        },
    }


def run_json_script(script_name: str, args: list[str]) -> dict[str, Any]:
    py = ROOT_DIR / ".venv" / "bin" / "python"
    script_path = ROOT_DIR / "scripts" / script_name
    proc = subprocess.run(
        [str(py), str(script_path), *args],
        cwd=ROOT_DIR,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"{script_name} exited with code {proc.returncode}"
        raise RuntimeError(detail)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{script_name} did not return valid JSON") from exc


class VeriBetAPIHandler(BaseHTTPRequestHandler):
    server_version = "VeriBetAPI/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._send_json(HTTPStatus.OK, {
                "ok": True,
                "service": "veribet-api",
                "model": os.getenv("OPENAI_MODEL", ""),
                "base_url": os.getenv("OPENAI_BASE_URL", ""),
                "bundle": str(DEFAULT_BUNDLE),
            })
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = self._read_json_body()
            if parsed.path == "/api/live/analyze":
                self.handle_live_analyze(body)
                return
            if parsed.path == "/api/live/batch":
                self.handle_live_batch(body)
                return
            if parsed.path == "/api/reviews/postmortem":
                self.handle_postmortem(body)
                return
            if parsed.path == "/api/patches/propose":
                self.handle_propose(body)
                return
            if parsed.path == "/api/patches/test":
                self.handle_patch_test(body)
                return
            if parsed.path == "/api/patches/apply":
                self.handle_patch_apply(body)
                return
            if parsed.path == "/api/ingest-and-review":
                self.handle_ingest_and_review(body)
                return
            if parsed.path == "/api/ingest-review-and-test":
                self.handle_ingest_review_and_test(body)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "bad_request", "message": str(exc)})
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "internal_error", "message": str(exc)})

    def handle_live_analyze(self, body: dict[str, Any]) -> None:
        match_input = body.get("input")
        if not isinstance(match_input, dict):
            raise ValueError("input must be an object")
        bundle_path = resolve_repo_path(body.get("bundle_path", str(DEFAULT_BUNDLE.relative_to(ROOT_DIR))))
        result = analyze_match(
            match_input=match_input,
            bundle_path=bundle_path,
            timeout=int(body.get("timeout", 180)),
            retries=int(body.get("retries", 2)),
            retry_delay=float(body.get("retry_delay", 1.5)),
        )
        output_path = body.get("output_path")
        if output_path:
            out = resolve_repo_path(output_path, create_parent=True)
            dump_json(out, result)
            result["saved_output"] = str(out)
        self._send_json(HTTPStatus.OK, result)

    def handle_live_batch(self, body: dict[str, Any]) -> None:
        bundle_path = resolve_repo_path(body.get("bundle_path", str(DEFAULT_BUNDLE.relative_to(ROOT_DIR))))
        timeout = int(body.get("timeout", 180))
        retries = int(body.get("retries", 2))
        retry_delay = float(body.get("retry_delay", 1.5))
        output_dir_value = body.get("output_dir")
        output_dir = resolve_repo_path(output_dir_value, create_parent=True) if output_dir_value else None

        named_inputs: list[tuple[str, dict[str, Any]]] = []
        inputs_path = body.get("inputs_path")
        inputs = body.get("inputs")

        if inputs_path:
            input_root = resolve_repo_path(inputs_path)
            for path in discover_input_paths(input_root):
                named_inputs.append((path.name, load_json(path)))
        elif isinstance(inputs, list):
            for index, item in enumerate(inputs, start=1):
                if not isinstance(item, dict):
                    raise ValueError("each item in inputs must be an object")
                input_name = item.get("name") or item.get("id") or f"batch_{index:03d}"
                match_input = item.get("input")
                if not isinstance(match_input, dict):
                    raise ValueError("each batch item must include input object")
                named_inputs.append((str(input_name), match_input))
        else:
            raise ValueError("inputs_path or inputs is required")

        if not named_inputs:
            raise ValueError("no input JSON files found")

        result = analyze_batch(
            named_inputs=named_inputs,
            bundle_path=bundle_path,
            timeout=timeout,
            retries=retries,
            retry_delay=retry_delay,
            output_dir=output_dir,
        )
        self._send_json(HTTPStatus.OK, result)

    def handle_postmortem(self, body: dict[str, Any]) -> None:
        if isinstance(body.get("input"), dict):
            match_input = body["input"]
            input_file = body.get("match_input_file", "")
        else:
            input_path = body.get("input_path")
            if not input_path:
                raise ValueError("input or input_path is required")
            path = resolve_repo_path(input_path)
            match_input = load_json(path)
            input_file = str(path)

        if isinstance(body.get("result"), dict):
            live_result = body["result"]
            result_file = body.get("result_file", "")
        else:
            result_path = body.get("result_path")
            if not result_path:
                raise ValueError("result or result_path is required")
            path = resolve_repo_path(result_path)
            live_result = load_json(path)
            result_file = str(path)

        ft_score = body.get("ft_score")
        if not ft_score:
            raise ValueError("ft_score is required")

        review = build_review(
            match_input=match_input,
            match_input_file=input_file,
            live_result=live_result,
            result_file=result_file,
            ft_score=ft_score,
            ht_score=body.get("ht_score", ""),
            result_label=body.get("result_label", ""),
            tags=body.get("tags") or [],
            judgement=body.get("judgement", ""),
            rule_delta=body.get("rule_delta", ""),
            analyst=body.get("analyst", ""),
            source=body.get("source", "api_review"),
        )
        output_path = body.get("output_path")
        if output_path:
            out = resolve_repo_path(output_path, create_parent=True)
            dump_json(out, review)
            review["saved_output"] = str(out)
        self._send_json(HTTPStatus.OK, {"ok": True, "review": review})

    def handle_propose(self, body: dict[str, Any]) -> None:
        if isinstance(body.get("review"), dict):
            review = body["review"]
        else:
            review_path = body.get("review_path")
            if not review_path:
                raise ValueError("review or review_path is required")
            review = load_json(resolve_repo_path(review_path))
        candidate = make_candidate(review)
        output_path = body.get("output_path")
        if output_path:
            out = resolve_repo_path(output_path, create_parent=True)
            dump_json(out, candidate)
            candidate["saved_output"] = str(out)
        self._send_json(HTTPStatus.OK, {"ok": True, "candidate": candidate})

    def handle_patch_test(self, body: dict[str, Any]) -> None:
        patch_paths = body.get("patch_paths") or body.get("patches") or []
        if isinstance(patch_paths, str):
            patch_paths = [patch_paths]
        if not isinstance(patch_paths, list) or not patch_paths:
            raise ValueError("patch_paths must be a non-empty list")
        output_dir = body.get("output_dir", f"patch_test_runs/api_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        args: list[str] = []
        bundle_path = body.get("bundle_path")
        pack_path = body.get("pack_path")
        retries = body.get("retries")
        if bundle_path:
            args.extend(["--bundle", str(resolve_repo_path(bundle_path).relative_to(ROOT_DIR))])
        if pack_path:
            args.extend(["--pack", str(resolve_repo_path(pack_path).relative_to(ROOT_DIR))])
        for item in patch_paths:
            args.extend(["--patch", str(resolve_repo_path(item).relative_to(ROOT_DIR))])
        args.extend(["--output-dir", str(resolve_repo_path(output_dir, create_parent=True).relative_to(ROOT_DIR))])
        if retries is not None:
            args.extend(["--retries", str(int(retries))])
        result = run_json_script("veribet_patch_test.py", args)
        self._send_json(HTTPStatus.OK, result)

    def handle_patch_apply(self, body: dict[str, Any]) -> None:
        summary_path = body.get("summary_path")
        if not summary_path:
            raise ValueError("summary_path is required")
        args = ["--summary", str(resolve_repo_path(summary_path).relative_to(ROOT_DIR))]
        bundle_path = body.get("bundle_path")
        if bundle_path:
            args.extend(["--bundle", str(resolve_repo_path(bundle_path).relative_to(ROOT_DIR))])
        if body.get("force"):
            args.append("--force")
        result = run_json_script("veribet_patch_apply.py", args)
        self._send_json(HTTPStatus.OK, result)

    def handle_ingest_and_review(self, body: dict[str, Any]) -> None:
        if isinstance(body.get("input"), dict):
            match_input = body["input"]
            input_file = body.get("match_input_file", "")
        else:
            input_path = body.get("input_path")
            if not input_path:
                raise ValueError("input or input_path is required")
            path = resolve_repo_path(input_path)
            match_input = load_json(path)
            input_file = str(path)

        bundle_path = resolve_repo_path(body.get("bundle_path", str(DEFAULT_BUNDLE.relative_to(ROOT_DIR))))
        timeout = int(body.get("timeout", 180))
        retries = int(body.get("retries", 2))
        retry_delay = float(body.get("retry_delay", 1.5))

        if isinstance(body.get("result"), dict):
            live_result = body["result"]
            result_file = body.get("result_file", "")
        elif body.get("result_path"):
            path = resolve_repo_path(body["result_path"])
            live_result = load_json(path)
            result_file = str(path)
        else:
            live_result = analyze_match(
                match_input=match_input,
                bundle_path=bundle_path,
                timeout=timeout,
                retries=retries,
                retry_delay=retry_delay,
            )
            result_output_path = body.get("result_output_path")
            if result_output_path:
                out = resolve_repo_path(result_output_path, create_parent=True)
                dump_json(out, live_result)
                result_file = str(out)
                live_result["saved_output"] = str(out)
            else:
                result_file = ""

        ft_score = body.get("ft_score")
        if not ft_score:
            raise ValueError("ft_score is required")

        review = build_review(
            match_input=match_input,
            match_input_file=input_file,
            live_result=live_result,
            result_file=result_file,
            ft_score=ft_score,
            ht_score=body.get("ht_score", ""),
            result_label=body.get("result_label", ""),
            tags=body.get("tags") or [],
            judgement=body.get("judgement", ""),
            rule_delta=body.get("rule_delta", ""),
            analyst=body.get("analyst", ""),
            source=body.get("source", "api_ingest_review"),
        )

        review_output_path = body.get("review_output_path")
        if review_output_path:
            out = resolve_repo_path(review_output_path, create_parent=True)
            dump_json(out, review)
            review["saved_output"] = str(out)

        candidate = make_candidate(review)
        patch_output_path = body.get("patch_output_path")
        if patch_output_path:
            out = resolve_repo_path(patch_output_path, create_parent=True)
            dump_json(out, candidate)
            candidate["saved_output"] = str(out)

        self._send_json(HTTPStatus.OK, {
            "ok": True,
            "live_result": live_result,
            "review": review,
            "candidate": candidate,
        })

    def handle_ingest_review_and_test(self, body: dict[str, Any]) -> None:
        if isinstance(body.get("input"), dict):
            match_input = body["input"]
            input_file = body.get("match_input_file", "")
        else:
            input_path = body.get("input_path")
            if not input_path:
                raise ValueError("input or input_path is required")
            path = resolve_repo_path(input_path)
            match_input = load_json(path)
            input_file = str(path)

        bundle_path = resolve_repo_path(body.get("bundle_path", str(DEFAULT_BUNDLE.relative_to(ROOT_DIR))))
        timeout = int(body.get("timeout", 180))
        retries = int(body.get("retries", 2))
        retry_delay = float(body.get("retry_delay", 1.5))

        if isinstance(body.get("result"), dict):
            live_result = body["result"]
            result_file = body.get("result_file", "")
        elif body.get("result_path"):
            path = resolve_repo_path(body["result_path"])
            live_result = load_json(path)
            result_file = str(path)
        else:
            live_result = analyze_match(
                match_input=match_input,
                bundle_path=bundle_path,
                timeout=timeout,
                retries=retries,
                retry_delay=retry_delay,
            )
            result_output_path = body.get("result_output_path")
            if result_output_path:
                out = resolve_repo_path(result_output_path, create_parent=True)
                dump_json(out, live_result)
                result_file = str(out)
                live_result["saved_output"] = str(out)
            else:
                result_file = ""

        ft_score = body.get("ft_score")
        if not ft_score:
            raise ValueError("ft_score is required")

        review = build_review(
            match_input=match_input,
            match_input_file=input_file,
            live_result=live_result,
            result_file=result_file,
            ft_score=ft_score,
            ht_score=body.get("ht_score", ""),
            result_label=body.get("result_label", ""),
            tags=body.get("tags") or [],
            judgement=body.get("judgement", ""),
            rule_delta=body.get("rule_delta", ""),
            analyst=body.get("analyst", ""),
            source=body.get("source", "api_ingest_review_test"),
        )

        review_output_path = body.get("review_output_path")
        if review_output_path:
            out = resolve_repo_path(review_output_path, create_parent=True)
            dump_json(out, review)
            review["saved_output"] = str(out)

        candidate = make_candidate(review)
        patch_output_path = body.get("patch_output_path")
        if patch_output_path:
            out = resolve_repo_path(patch_output_path, create_parent=True)
            dump_json(out, candidate)
            candidate["saved_output"] = str(out)
            patch_ref = str(out.relative_to(ROOT_DIR))
        else:
            temp_patch_dir = resolve_repo_path(
                body.get("temp_patch_dir", f"patches/api_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"),
                create_parent=True,
            )
            out = temp_patch_dir / f"{review.get('match_id', 'candidate')}.candidate.json"
            dump_json(out, candidate)
            candidate["saved_output"] = str(out)
            patch_ref = str(out.relative_to(ROOT_DIR))

        patch_test_output_dir = body.get(
            "patch_test_output_dir",
            f"patch_test_runs/api_{review.get('match_id', 'candidate')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        )
        patch_test_args: list[str] = [
            "--bundle", str(bundle_path.relative_to(ROOT_DIR)),
        ]
        if body.get("pack_path"):
            patch_test_args.extend(["--pack", str(resolve_repo_path(body["pack_path"]).relative_to(ROOT_DIR))])
        patch_test_args.extend([
            "--patch", patch_ref,
            "--output-dir", str(resolve_repo_path(patch_test_output_dir, create_parent=True).relative_to(ROOT_DIR)),
            "--retries", str(int(body.get("patch_test_retries", 1))),
        ])
        patch_test_result = run_json_script("veribet_patch_test.py", patch_test_args)

        self._send_json(HTTPStatus.OK, {
            "ok": True,
            "live_result": live_result,
            "review": review,
            "candidate": candidate,
            "patch_test": patch_test_result,
        })


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local HTTP API for VeriBet automation.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8012, help="Bind port")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV), help="Optional .env path")
    args = parser.parse_args()

    load_env_file(resolve_repo_path(args.env_file) if args.env_file else DEFAULT_ENV)
    httpd = ThreadingHTTPServer((args.host, args.port), VeriBetAPIHandler)
    print(json.dumps({
        "ok": True,
        "service": "veribet-api",
        "listen": f"http://{args.host}:{args.port}",
        "bundle": str(DEFAULT_BUNDLE),
    }, ensure_ascii=False, indent=2))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
