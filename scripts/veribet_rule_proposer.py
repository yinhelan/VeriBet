#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return s or "candidate"


def make_candidate(review: dict[str, Any]) -> dict[str, Any]:
    match_id = review.get("match_id", "unknown_match")
    tags = set(review.get("postmortem_tags") or [])
    judgement = review.get("human_judgement", "")
    suggested_rule_delta = review.get("suggested_rule_delta", "")
    structures = (review.get("veribet_summary") or {}).get("structures") or []
    match_input_file = review.get("match_input_file", "")

    target_section = "rulebook"
    change_type = "append_rule"
    rationale = {
        "match_id": match_id,
        "postmortem_tags": list(tags),
        "human_judgement": judgement,
        "suggested_rule_delta": suggested_rule_delta,
        "structures": structures,
        "match_input_file": match_input_file,
    }

    content = suggested_rule_delta.strip()
    rule_id = f"review_{slugify(match_id)}"

    lower_path = match_input_file.lower()
    lower_judgement = (judgement + " " + suggested_rule_delta).lower()

    if "主热未封口" in tags or "平局低估" in tags:
        rule_id = "league_home_heat_draw_guard_v1"
        content = (
            "若联赛场景下主胜赔率处于 2.20~2.35 区间，主端为唯一明显负赔付端，"
            "且仅有单快照、缺少 T1→T_last 演变验证，则不得把平局降到尾部；"
            "平局至少保留为 secondary_direction，并在 flags 中显式提示单快照下主热未封口风险。"
        )
    elif "高比分开放战" in tags or ("欧战" in lower_judgement and "开放" in lower_judgement):
        rule_id = "europe_open_game_risk_hint_v1"
        content = (
            "若欧战强强对话中主胜与平局赔付同时承压，且仅有单快照，"
            "则即便方向排序偏向某一端，也必须在 flags 或 raw_text 中补充开放战/高波动提示，"
            "避免把方向正确误写成低波动兑现。"
        )
    elif "单快照偏保守" in tags and ("efl" in lower_path or "championship" in lower_path):
        rule_id = "single_snapshot_league_conservatism_v1"
        content = (
            "联赛单快照样本若缺少 T1→T_last 演变链路，应默认保留主方向之外的核心防守位，"
            "不得因单一终盘承接就删除平局防守。"
        )

    return {
        "rule_id": rule_id,
        "target_section": target_section,
        "change_type": change_type,
        "content": content,
        "rationale": rationale,
        "status": "candidate",
    }


def discover_review_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.glob("*.review.json") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate candidate VeriBet rule patches from review JSON files.")
    parser.add_argument("--reviews", required=True, help="Review JSON file or directory")
    parser.add_argument("--output-dir", required=True, help="Directory to write candidate patch JSON files")
    args = parser.parse_args()

    review_root = Path(args.reviews)
    output_dir = Path(args.output_dir)
    review_paths = discover_review_paths(review_root)
    if not review_paths:
      raise SystemExit("No review JSON files found")

    written: list[str] = []
    for review_path in review_paths:
        review = load_json(review_path)
        candidate = make_candidate(review)
        out_name = f"{review_path.stem}.candidate.json"
        out_path = output_dir / out_name
        dump_json(out_path, candidate)
        written.append(str(out_path))

    print(json.dumps({
        "ok": True,
        "generated": written,
        "count": len(written),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
