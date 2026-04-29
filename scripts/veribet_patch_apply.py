#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def patch_marker(rule_id: str) -> str:
    return f"[PATCH:{rule_id}]"


def apply_patches_to_bundle(bundle: dict[str, Any], patches: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    updated = dict(bundle)
    rulebook = (updated.get("rulebook") or "").rstrip()
    applied: list[str] = []
    additions: list[str] = []

    for patch in patches:
        if patch.get("target_section") != "rulebook":
            continue
        if patch.get("change_type") != "append_rule":
            continue
        rule_id = patch.get("rule_id", "candidate_rule")
        marker = patch_marker(rule_id)
        if marker in rulebook:
            continue
        content = (patch.get("content") or "").strip()
        if not content:
            continue
        additions.append(f"- {marker} {content}")
        applied.append(rule_id)

    if additions:
        updated["rulebook"] = rulebook + ("\n\n" if rulebook else "") + "\n".join(additions)
    return updated, applied


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply accepted VeriBet candidate patches to the main prompt bundle.")
    parser.add_argument("--summary", required=True, help="patch_test summary.json path")
    parser.add_argument("--bundle", default="prompts/veribet_prompt_bundle_v412_candidate.yaml", help="Target bundle YAML path")
    parser.add_argument("--force", action="store_true", help="Apply even if decision is not accept")
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[1]
    summary_path = (root_dir / args.summary).resolve() if not Path(args.summary).is_absolute() else Path(args.summary)
    bundle_path = (root_dir / args.bundle).resolve() if not Path(args.bundle).is_absolute() else Path(args.bundle)

    summary = load_json(summary_path)
    decision = ((summary.get("delta") or {}).get("decision") or "").lower()
    if decision != "accept" and not args.force:
        raise SystemExit(f"Refusing to apply patch because decision={decision!r}; use --force to override")

    patch_paths = [Path(p) if Path(p).is_absolute() else (root_dir / p).resolve() for p in summary.get("patches", [])]
    patches = [load_json(path) for path in patch_paths]
    bundle = load_yaml(bundle_path)

    updated_bundle, applied_rule_ids = apply_patches_to_bundle(bundle, patches)
    if not applied_rule_ids:
        print(json.dumps({
            "ok": True,
            "message": "No new patches applied",
            "decision": decision,
            "bundle": str(bundle_path),
        }, ensure_ascii=False, indent=2))
        return 0

    backup_path = bundle_path.with_suffix(bundle_path.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    backup_path.write_text(bundle_path.read_text(encoding="utf-8"), encoding="utf-8")
    dump_yaml(bundle_path, updated_bundle)

    print(json.dumps({
        "ok": True,
        "decision": decision,
        "bundle": str(bundle_path),
        "backup": str(backup_path),
        "applied_rule_ids": applied_rule_ids,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
