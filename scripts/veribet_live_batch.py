#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def discover_inputs(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.glob("*.json") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description="Run VeriBet live inference for one or more input JSON files.")
    parser.add_argument("--bundle", required=True, help="Path to prompt bundle YAML")
    parser.add_argument("--inputs", required=True, help="Input JSON file or directory of JSON files")
    parser.add_argument("--output-dir", required=True, help="Directory to write result JSON files")
    parser.add_argument("--timeout", type=int, default=180, help="HTTP timeout seconds")
    parser.add_argument("--retries", type=int, default=2, help="Retry count per input for transient failures")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="Base delay seconds between retries")
    args = parser.parse_args()

    bundle_path = Path(args.bundle)
    input_root = Path(args.inputs)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = discover_inputs(input_root)
    if not inputs:
        print(json.dumps({"ok": False, "message": "No input JSON files found"}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    py = Path(__file__).with_name("veribet_live.py")
    summary: list[dict[str, object]] = []
    failed = 0

    for input_file in inputs:
        output_file = output_dir / f"{input_file.stem}.result.json"
        cmd = [
            sys.executable,
            str(py),
            "--bundle",
            str(bundle_path),
            "--input",
            str(input_file),
            "--output",
            str(output_file),
            "--timeout",
            str(args.timeout),
            "--retries",
            str(args.retries),
            "--retry-delay",
            str(args.retry_delay),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        item: dict[str, object] = {
            "input": str(input_file),
            "output": str(output_file),
            "exit_code": proc.returncode,
        }
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if stdout:
            try:
                parsed = json.loads(stdout)
                item["ok"] = parsed.get("ok")
                item["validation_errors"] = parsed.get("validation_errors", [])
            except json.JSONDecodeError:
                item["stdout"] = stdout
        if stderr:
            item["stderr"] = stderr
        if proc.returncode != 0:
            failed += 1
        summary.append(item)

    print(json.dumps({
        "ok": failed == 0,
        "total_inputs": len(inputs),
        "failed_inputs": failed,
        "results": summary,
    }, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
