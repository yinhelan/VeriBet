#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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


def discover_patch_paths(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        p = Path(value)
        if p.is_dir():
            paths.extend(sorted(x for x in p.glob("*.candidate.json") if x.is_file()))
        else:
            paths.append(p)
    return paths


def load_patches(paths: list[Path]) -> list[dict[str, Any]]:
    return [load_json(path) for path in paths]


def apply_patches_to_bundle(bundle: dict[str, Any], patches: list[dict[str, Any]]) -> dict[str, Any]:
    updated = dict(bundle)
    rulebook = (updated.get("rulebook") or "").rstrip()
    additions: list[str] = []
    for patch in patches:
        if patch.get("target_section") != "rulebook":
            continue
        if patch.get("change_type") != "append_rule":
            continue
        rule_id = patch.get("rule_id", "candidate_rule")
        content = (patch.get("content") or "").strip()
        if not content:
            continue
        additions.append(f"- [PATCH:{rule_id}] {content}")
    if additions:
        updated["rulebook"] = rulebook + ("\n\n" if rulebook else "") + "\n".join(additions)
    return updated


def merge_outputs(base_outputs: Path, retry_outputs: Path, merged_outputs: Path) -> None:
    base = load_yaml(base_outputs) or {}
    retry = load_yaml(retry_outputs) or {}
    retry_map = {item.get("id"): item for item in retry.get("cases", [])}
    merged_cases = []
    seen = set()
    for item in base.get("cases", []):
        case_id = item.get("id")
        if case_id in retry_map:
            merged_cases.append(retry_map[case_id])
            seen.add(case_id)
        else:
            merged_cases.append(item)
            seen.add(case_id)
    for case_id, item in retry_map.items():
        if case_id not in seen:
            merged_cases.append(item)
    base["cases"] = merged_cases
    dump_yaml(merged_outputs, base)


def run_veribet(
    *,
    root_dir: Path,
    bundle_path: Path,
    pack_path: Path,
    output_dir: Path,
    retries: int,
) -> dict[str, Any]:
    py = root_dir / ".venv" / "bin" / "python"
    runner = root_dir / "scripts" / "veribet_runner.py"
    evaluator = root_dir / "scripts" / "veribet_eval.py"

    model = os.environ.get("OPENAI_MODEL")
    base_url = os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not model or not base_url or not api_key:
        raise RuntimeError("OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL 必须在环境变量中可用")

    output_dir.mkdir(parents=True, exist_ok=True)
    base_outputs = output_dir / "base_outputs.yaml"
    base_report = output_dir / "base_report.json"
    retry_outputs = output_dir / "retry_outputs.yaml"
    merged_outputs = output_dir / "merged_outputs.yaml"
    merged_report = output_dir / "merged_report.json"

    env = os.environ.copy()

    def run_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=root_dir, env=env, capture_output=True, text=True)

    initial = run_cmd([
        str(py), str(runner),
        "--pack", str(pack_path),
        "--bundle", str(bundle_path),
        "--model", model,
        "--base-url", base_url,
        "--outputs", str(base_outputs),
        "--report", str(base_report),
    ])
    if initial.returncode not in {0, 1}:
        raise RuntimeError(f"Initial run failed: {initial.stderr or initial.stdout}")

    base_report_obj = load_json(base_report)
    failed_ids = [case["id"] for case in base_report_obj.get("cases", []) if not case.get("passed")]
    merged_outputs.write_text(base_outputs.read_text(encoding="utf-8"), encoding="utf-8")

    attempt_logs: list[dict[str, Any]] = []
    attempt = 1
    current_failed_ids = failed_ids[:]
    while current_failed_ids and attempt <= retries:
        args = [
            str(py), str(runner),
            "--pack", str(pack_path),
            "--bundle", str(bundle_path),
            "--model", model,
            "--base-url", base_url,
        ]
        for case_id in current_failed_ids:
            args.extend(["--case-id", case_id])
        args.extend(["--outputs", str(retry_outputs)])
        proc = run_cmd(args)
        if proc.returncode not in {0, 1}:
            attempt_logs.append({
                "attempt": attempt,
                "failed_case_ids": current_failed_ids,
                "returncode": proc.returncode,
                "stderr": proc.stderr,
                "stdout": proc.stdout,
            })
            attempt += 1
            continue

        merge_outputs(merged_outputs, retry_outputs, merged_outputs)
        eval_proc = run_cmd([
            str(py), str(evaluator),
            "--pack", str(pack_path),
            "--outputs", str(merged_outputs),
            "--report", str(merged_report),
        ])
        if eval_proc.returncode not in {0, 1}:
            raise RuntimeError(f"Eval after retry failed: {eval_proc.stderr or eval_proc.stdout}")
        merged_report_obj = load_json(merged_report)
        current_failed_ids = [case["id"] for case in merged_report_obj.get("cases", []) if not case.get("passed")]
        attempt_logs.append({
            "attempt": attempt,
            "failed_case_ids": current_failed_ids,
            "returncode": proc.returncode,
        })
        attempt += 1

    final_eval = run_cmd([
        str(py), str(evaluator),
        "--pack", str(pack_path),
        "--outputs", str(merged_outputs),
        "--report", str(merged_report),
    ])
    if final_eval.returncode not in {0, 1}:
        raise RuntimeError(f"Final eval failed: {final_eval.stderr or final_eval.stdout}")

    return {
        "base_outputs": str(base_outputs),
        "base_report": str(base_report),
        "merged_outputs": str(merged_outputs),
        "merged_report": str(merged_report),
        "initial_report": base_report_obj,
        "final_report": load_json(merged_report),
        "attempt_logs": attempt_logs,
    }


def summarize_delta(baseline: dict[str, Any], patched: dict[str, Any]) -> dict[str, Any]:
    b = baseline["final_report"]
    p = patched["final_report"]
    baseline_cases = {case["id"]: case for case in b.get("cases", [])}
    patched_cases = {case["id"]: case for case in p.get("cases", [])}
    improved = []
    regressed = []
    unchanged = []
    for case_id in sorted(set(baseline_cases) | set(patched_cases)):
        bc = baseline_cases.get(case_id)
        pc = patched_cases.get(case_id)
        if not bc or not pc:
            continue
        if pc["score"] > bc["score"] or (pc["passed"] and not bc["passed"]):
            improved.append(case_id)
        elif pc["score"] < bc["score"] or (bc["passed"] and not pc["passed"]):
            regressed.append(case_id)
        else:
            unchanged.append(case_id)

    decision = "reject"
    if p["total_score"] > b["total_score"] and p["hard_fail_count"] <= b["hard_fail_count"] and not regressed:
        decision = "accept"
    elif p["total_score"] >= b["total_score"] and p["hard_fail_count"] <= b["hard_fail_count"] and improved:
        decision = "review"

    return {
        "baseline_total_score": b["total_score"],
        "patched_total_score": p["total_score"],
        "baseline_pass_count": b["pass_count"],
        "patched_pass_count": p["pass_count"],
        "baseline_hard_fail_count": b["hard_fail_count"],
        "patched_hard_fail_count": p["hard_fail_count"],
        "improved_cases": improved,
        "regressed_cases": regressed,
        "unchanged_cases": unchanged,
        "decision": decision,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Temporarily apply candidate patches and compare baseline vs patched regression results.")
    parser.add_argument("--bundle", default="prompts/veribet_prompt_bundle_v412_candidate.yaml", help="Base bundle YAML")
    parser.add_argument("--pack", default="packs/veribet_regression_pack_v1.yaml", help="Regression pack YAML")
    parser.add_argument("--patch", action="append", default=[], help="Candidate patch JSON file or directory; repeatable")
    parser.add_argument("--output-dir", default="patch_test_runs/latest", help="Directory to store baseline/patched artifacts")
    parser.add_argument("--retries", type=int, default=3, help="Retry attempts for failed cases in each run")
    args = parser.parse_args()

    if not args.patch:
        raise SystemExit("At least one --patch is required")

    root_dir = Path(__file__).resolve().parents[1]
    load_env_file(root_dir / ".env")
    bundle_path = (root_dir / args.bundle).resolve()
    pack_path = (root_dir / args.pack).resolve()
    output_dir = (root_dir / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    patch_paths = discover_patch_paths(args.patch)
    patches = load_patches(patch_paths)
    base_bundle = load_yaml(bundle_path)
    patched_bundle = apply_patches_to_bundle(base_bundle, patches)

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as tmp:
        tmp_bundle_path = Path(tmp.name)
    dump_yaml(tmp_bundle_path, patched_bundle)

    baseline_run = run_veribet(
        root_dir=root_dir,
        bundle_path=bundle_path,
        pack_path=pack_path,
        output_dir=output_dir / "baseline",
        retries=args.retries,
    )
    patched_run = run_veribet(
        root_dir=root_dir,
        bundle_path=tmp_bundle_path,
        pack_path=pack_path,
        output_dir=output_dir / "patched",
        retries=args.retries,
    )
    delta = summarize_delta(baseline_run, patched_run)

    summary = {
        "ok": True,
        "bundle": str(bundle_path),
        "pack": str(pack_path),
        "patches": [str(p) for p in patch_paths],
        "tmp_bundle": str(tmp_bundle_path),
        "baseline": baseline_run,
        "patched": patched_run,
        "delta": delta,
    }
    dump_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
