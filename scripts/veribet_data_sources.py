#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from datetime import datetime
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    import certifi
except Exception:
    certifi = None

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT_DIR / ".env.data_sources"


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
        if key:
            os.environ[key] = value


def http_get_json(url: str, headers: dict[str, str], timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    context = None
    if certifi is not None:
      context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


def football_data_headers() -> dict[str, str]:
    token = os.getenv("FOOTBALL_DATA_TOKEN")
    if not token:
        raise SystemExit("FOOTBALL_DATA_TOKEN 未设置")
    return {"X-Auth-Token": token}


def api_sports_headers() -> dict[str, str]:
    key = os.getenv("APISPORTS_KEY")
    if not key:
        raise SystemExit("APISPORTS_KEY 未设置")
    return {"x-apisports-key": key}


def odds_api_key() -> str:
    key = os.getenv("ODDS_API_KEY")
    if not key:
        raise SystemExit("ODDS_API_KEY 未设置")
    return key


def football_data_competitions() -> dict[str, Any]:
    return http_get_json(
        "https://api.football-data.org/v4/competitions",
        football_data_headers(),
    )


def football_data_matches(date_from: str | None, date_to: str | None, competition: str | None) -> dict[str, Any]:
    base = "https://api.football-data.org/v4/matches"
    if competition:
        base = f"https://api.football-data.org/v4/competitions/{urllib.parse.quote(competition)}/matches"
    query: dict[str, str] = {}
    if date_from:
        query["dateFrom"] = date_from
    if date_to:
        query["dateTo"] = date_to
    url = base
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return http_get_json(url, football_data_headers())


def api_sports_fixtures(date: str | None, league: str | None, season: str | None, team: str | None) -> dict[str, Any]:
    query: dict[str, str] = {}
    if date:
        query["date"] = date
    if league:
        query["league"] = league
    if season:
        query["season"] = season
    if team:
        query["team"] = team
    url = "https://v3.football.api-sports.io/fixtures"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return http_get_json(url, api_sports_headers())


def odds_api_scores(sport: str, days_from: int | None) -> dict[str, Any]:
    key = odds_api_key()
    query: dict[str, str] = {"apiKey": key}
    if days_from is not None:
        query["daysFrom"] = str(days_from)
    url = f"https://api.the-odds-api.com/v4/sports/{urllib.parse.quote(sport)}/scores"
    url += "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    context = None
    if certifi is not None:
      context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=30, context=context) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(body)
        return {
            "data": payload,
            "x-requests-remaining": resp.headers.get("x-requests-remaining"),
            "x-requests-used": resp.headers.get("x-requests-used"),
        }


def check_sources() -> dict[str, Any]:
    return {
        "football_data_token": bool(os.getenv("FOOTBALL_DATA_TOKEN")),
        "api_sports_key": bool(os.getenv("APISPORTS_KEY")),
        "odds_api_key": bool(os.getenv("ODDS_API_KEY")),
        "scrapingbee_api_key": bool(os.getenv("SCRAPINGBEE_API_KEY")),
        "oddsp_api_key": bool(os.getenv("ODDSP_API_KEY")),
        "oddsp_account_id": bool(os.getenv("ODDSP_ACCOUNT_ID")),
    }


def safe_slug(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in text).strip("_")


def normalize_name(text: str) -> str:
    return " ".join((text or "").lower().replace("&", " and ").split())


def extract_date(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text[:10]


def parse_kickoff(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        return dt.isoformat()
    except ValueError:
        return text


def match_key(home: str, away: str, date: str) -> str:
    return f"{normalize_name(home)}__{normalize_name(away)}__{date}"


def competition_text(item: dict[str, Any]) -> str:
    football_data = (item.get("sources") or {}).get("football_data") or {}
    api_sports = (item.get("sources") or {}).get("api_sports") or {}
    odds_api = (item.get("sources") or {}).get("odds_api") or {}
    return str(
        football_data.get("competition")
        or api_sports.get("league")
        or odds_api.get("sport_title")
        or ""
    )


def sanitize_filename(text: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "_", normalize_name(text))
    return compact.strip("_") or "match"


def build_veribet_candidate(item: dict[str, Any]) -> dict[str, Any]:
    football_data = (item.get("sources") or {}).get("football_data") or {}
    api_sports = (item.get("sources") or {}).get("api_sports") or {}
    odds_api = (item.get("sources") or {}).get("odds_api") or {}
    competition = competition_text(item)
    kickoff = football_data.get("kickoff") or api_sports.get("kickoff") or odds_api.get("kickoff")
    notes: dict[str, Any] = {"stage": "pre_match"}
    if football_data.get("matchday") is not None:
        notes["matchday"] = football_data.get("matchday")
    if api_sports.get("round"):
        notes["round"] = api_sports.get("round")
    if odds_api.get("completed") is not None:
        notes["odds_api_completed"] = odds_api.get("completed")

    candidate = {
        "basic_info": {
            "competition": competition,
            "match": f"{item.get('home_team')} vs {item.get('away_team')}",
            "kick_off": parse_kickoff(kickoff),
            "venue": None,
            "weather": None,
        },
        "snapshots": {},
        "notes": notes,
        "source_match_key": item.get("match_key"),
        "source_coverage": sorted((item.get("sources") or {}).keys()),
    }
    return candidate


def export_candidates(candidates: list[dict[str, Any]], export_dir: str) -> list[str]:
    output_dir = ROOT_DIR / export_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for candidate in candidates:
        match_text = ((candidate.get("basic_info") or {}).get("match") or "match").replace(" vs ", "_vs_")
        filename = sanitize_filename(match_text) + ".json"
        target = output_dir / filename
        target.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(str(target.relative_to(ROOT_DIR)))
    return written


def aggregate_day(
    date: str,
    sport: str = "soccer_epl",
    competition_filter: str | None = None,
    export_dir: str | None = None,
) -> dict[str, Any]:
    fd = football_data_matches(date, date, None)
    api = api_sports_fixtures(date, None, None, None)
    odds = odds_api_scores(sport, None)

    aggregate: dict[str, dict[str, Any]] = {}

    for item in fd.get("matches", []):
        home = ((item.get("homeTeam") or {}).get("name") or "").strip()
        away = ((item.get("awayTeam") or {}).get("name") or "").strip()
        kickoff = item.get("utcDate", "")
        item_date = extract_date(kickoff) or date
        if item_date != date:
            continue
        key = match_key(home, away, item_date)
        aggregate.setdefault(key, {
            "match_key": key,
            "date": item_date,
            "home_team": home,
            "away_team": away,
            "sources": {},
        })
        aggregate[key]["sources"]["football_data"] = {
            "competition": (item.get("competition") or {}).get("name"),
            "status": (item.get("status") or ""),
            "kickoff": kickoff,
            "score": item.get("score"),
            "matchday": item.get("matchday"),
        }

    for item in api.get("response", []):
        fixture = item.get("fixture") or {}
        teams = item.get("teams") or {}
        home = ((teams.get("home") or {}).get("name") or "").strip()
        away = ((teams.get("away") or {}).get("name") or "").strip()
        kickoff = fixture.get("date", "")
        item_date = extract_date(kickoff) or date
        if item_date != date:
            continue
        key = match_key(home, away, item_date)
        aggregate.setdefault(key, {
            "match_key": key,
            "date": item_date,
            "home_team": home,
            "away_team": away,
            "sources": {},
        })
        aggregate[key]["sources"]["api_sports"] = {
            "league": ((item.get("league") or {}).get("name")),
            "round": ((item.get("league") or {}).get("round")),
            "status": ((fixture.get("status") or {}).get("short")),
            "kickoff": kickoff,
            "goals": item.get("goals"),
            "score": item.get("score"),
        }

    for item in odds.get("data", []):
        home = (item.get("home_team") or "").strip()
        away = (item.get("away_team") or "").strip()
        kickoff = item.get("commence_time", "")
        item_date = extract_date(kickoff) or date
        if item_date != date:
            continue
        key = match_key(home, away, item_date)
        aggregate.setdefault(key, {
            "match_key": key,
            "date": item_date,
            "home_team": home,
            "away_team": away,
            "sources": {},
        })
        aggregate[key]["sources"]["odds_api"] = {
            "sport_key": item.get("sport_key"),
            "sport_title": item.get("sport_title"),
            "completed": item.get("completed"),
            "kickoff": kickoff,
            "scores": item.get("scores"),
            "last_update": item.get("last_update"),
        }

    merged = sorted(aggregate.values(), key=lambda x: (x.get("date") or "", x.get("home_team") or "", x.get("away_team") or ""))
    if competition_filter:
        wanted = normalize_name(competition_filter)
        merged = [
            item for item in merged
            if wanted in normalize_name(competition_text(item))
        ]
    veribet_candidates = [build_veribet_candidate(item) for item in merged]
    exported_files: list[str] = []
    if export_dir:
        exported_files = export_candidates(veribet_candidates, export_dir)
    return {
        "ok": True,
        "date": date,
        "sport": sport,
        "competition_filter": competition_filter,
        "export_dir": export_dir,
        "notes": [
            "aggregate-day 现在只保留目标日期的比赛。",
            "veribet_candidates 是可直接继续补充快照字段的 VeriBet 输入骨架。",
        ],
        "source_counts": {
            "football_data_matches": len(fd.get("matches", [])),
            "api_sports_fixtures": len(api.get("response", [])),
            "odds_api_scores": len(odds.get("data", [])),
        },
        "merged_count": len(merged),
        "merged": merged,
        "veribet_candidates_count": len(veribet_candidates),
        "veribet_candidates": veribet_candidates,
        "exported_files": exported_files,
        "raw": {
            "football_data": fd,
            "api_sports": {
                "get": api.get("get"),
                "parameters": api.get("parameters"),
                "results": api.get("results"),
                "paging": api.get("paging"),
            },
            "odds_api": {
                "x-requests-remaining": odds.get("x-requests-remaining"),
                "x-requests-used": odds.get("x-requests-used"),
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Query configured football data sources for VeriBet.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV), help="Path to .env.data_sources")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Check which data-source keys are configured")
    sub.add_parser("football-data-competitions", help="List football-data competitions")
    p_matches = sub.add_parser("football-data-matches", help="List football-data matches")
    p_matches.add_argument("--date-from")
    p_matches.add_argument("--date-to")
    p_matches.add_argument("--competition")

    p_fixtures = sub.add_parser("api-sports-fixtures", help="List API-SPORTS fixtures")
    p_fixtures.add_argument("--date")
    p_fixtures.add_argument("--league")
    p_fixtures.add_argument("--season")
    p_fixtures.add_argument("--team")

    p_scores = sub.add_parser("odds-api-scores", help="Fetch The Odds API scores")
    p_scores.add_argument("--sport", default="soccer_epl")
    p_scores.add_argument("--days-from", type=int)

    p_agg = sub.add_parser("aggregate-day", help="Fetch one day from multiple sources and build a merged view")
    p_agg.add_argument("--date", required=True)
    p_agg.add_argument("--sport", default="soccer_epl")
    p_agg.add_argument("--competition", help="Case-insensitive substring filter on competition/league name")
    p_agg.add_argument("--export-dir", help="Write veribet_candidates into this repo-relative directory")

    args = parser.parse_args()
    load_env_file(Path(args.env_file))

    if args.command == "check":
        result = {"ok": True, "configured": check_sources()}
    elif args.command == "football-data-competitions":
        result = football_data_competitions()
    elif args.command == "football-data-matches":
        result = football_data_matches(args.date_from, args.date_to, args.competition)
    elif args.command == "api-sports-fixtures":
        result = api_sports_fixtures(args.date, args.league, args.season, args.team)
    elif args.command == "odds-api-scores":
        result = odds_api_scores(args.sport, args.days_from)
    elif args.command == "aggregate-day":
        result = aggregate_day(args.date, args.sport, args.competition, args.export_dir)
    else:
        raise SystemExit(f"unsupported command: {args.command}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
