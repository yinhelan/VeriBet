#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_result_label(value: str) -> str:
    v = value.strip().lower()
    mapping = {
        "主胜": "home",
        "平": "draw",
        "平局": "draw",
        "客胜": "away",
        "主负": "away",
        "home": "home",
        "draw": "draw",
        "away": "away",
    }
    if v not in mapping:
        raise ValueError(f"Unsupported result label: {value}")
    return mapping[v]


def infer_winner_from_score(ft_score: str) -> str:
    left, right = ft_score.split("-")
    home = int(left.strip())
    away = int(right.strip())
    if home > away:
        return "home"
    if home < away:
        return "away"
    return "draw"


def matches_direction(label: str, directions: list[str]) -> bool:
    wanted = {
        "home": {"主胜"},
        "draw": {"平局", "平"},
        "away": {"客胜", "主负"},
    }[label]
    return any(item in wanted for item in directions)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a standardized VeriBet postmortem review JSON.")
    parser.add_argument("--input", required=True, help="Match input JSON path")
    parser.add_argument("--result", required=True, help="Live inference result JSON path")
    parser.add_argument("--output", required=True, help="Review output JSON path")
    parser.add_argument("--ft-score", required=True, help="Full-time score, e.g. 2-2")
    parser.add_argument("--ht-score", help="Half-time score, e.g. 0-0")
    parser.add_argument("--result-label", help="Optional normalized result label: home/draw/away or 主胜/平/客胜")
    parser.add_argument("--tag", action="append", default=[], help="Repeatable postmortem tag")
    parser.add_argument("--judgement", default="", help="Human postmortem judgement text")
    parser.add_argument("--rule-delta", default="", help="Suggested rule delta text")
    parser.add_argument("--analyst", default="", help="Analyst name")
    parser.add_argument("--source", default="manual_review", help="Review source")
    args = parser.parse_args()

    input_path = Path(args.input)
    result_path = Path(args.result)
    output_path = Path(args.output)

    match_input = load_json(input_path)
    live_result = load_json(result_path)
    extracted = ((live_result.get("result") or {}).get("extracted") or {})

    match_id = input_path.stem
    if args.result_label:
        winner = normalize_result_label(args.result_label)
    else:
        winner = infer_winner_from_score(args.ft_score)

    main_direction = extracted.get("main_direction") or []
    secondary_direction = extracted.get("secondary_direction") or []
    tail_direction = extracted.get("tail_direction") or []

    review = {
        "match_id": match_id,
        "match_input_file": str(input_path),
        "result_file": str(result_path),
        "actual_result": {
            "ft_score": args.ft_score,
            "ht_score": args.ht_score or "",
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
        "postmortem_tags": args.tag,
        "human_judgement": args.judgement,
        "suggested_rule_delta": args.rule_delta,
        "notes": {
            "analyst": args.analyst,
            "source": args.source,
        },
    }

    dump_json(output_path, review)
    print(json.dumps(review, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
