#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import json
import os
import ssl
import subprocess
import sys
from datetime import datetime
import re
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import certifi
except Exception:
    certifi = None

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT_DIR / ".env.data_sources"
DEFAULT_RETRIES = 2
DEFAULT_RETRY_DELAY = 1.0
TOP_COMPETITION_PRESETS: dict[str, dict[str, str | None]] = {
    "epl": {
        "label": "Premier League",
        "api_sports_league": "39",
        "football_data_competition": "PL",
        "odds_api_sport": "soccer_epl",
    },
    "championship": {
        "label": "Championship",
        "api_sports_league": "40",
        "football_data_competition": "ELC",
        "odds_api_sport": "soccer_efl_champ",
    },
    "bundesliga": {
        "label": "Bundesliga",
        "api_sports_league": "78",
        "football_data_competition": "BL1",
        "odds_api_sport": "soccer_germany_bundesliga",
    },
    "laliga": {
        "label": "La Liga",
        "api_sports_league": "140",
        "football_data_competition": "PD",
        "odds_api_sport": "soccer_spain_la_liga",
    },
    "serie_a": {
        "label": "Serie A",
        "api_sports_league": "135",
        "football_data_competition": "SA",
        "odds_api_sport": "soccer_italy_serie_a",
    },
    "ligue_1": {
        "label": "Ligue 1",
        "api_sports_league": "61",
        "football_data_competition": "FL1",
        "odds_api_sport": "soccer_france_ligue_one",
    },
    "ucl": {
        "label": "UEFA Champions League",
        "api_sports_league": "2",
        "football_data_competition": "CL",
        "odds_api_sport": "soccer_uefa_champs_league",
    },
    "world_cup": {
        "label": "FIFA World Cup",
        "api_sports_league": "1",
        "football_data_competition": "WC",
        "odds_api_sport": "soccer_fifa_world_cup",
    },
    "nations_league": {
        "label": "UEFA Nations League",
        "api_sports_league": "5",
        "football_data_competition": None,
        "odds_api_sport": "soccer_uefa_nations_league",
    },
    "conference_league": {
        "label": "UEFA Europa Conference League",
        "api_sports_league": "848",
        "football_data_competition": None,
        "odds_api_sport": "soccer_uefa_europa_conference_league",
    },
}


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


def resolve_preset(
    preset: str | None,
    sport: str | None,
    api_sports_league: str | None,
    football_data_competition: str | None,
    competition_filter: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    if not preset:
        return sport, api_sports_league, football_data_competition, competition_filter
    if preset not in TOP_COMPETITION_PRESETS:
        raise SystemExit(f"未知 preset: {preset}")
    chosen = TOP_COMPETITION_PRESETS[preset]
    return (
        sport or chosen.get("odds_api_sport"),
        api_sports_league or chosen.get("api_sports_league"),
        football_data_competition or chosen.get("football_data_competition"),
        competition_filter or chosen.get("label"),
    )


def list_top_competitions() -> dict[str, Any]:
    return {
        "ok": True,
        "count": len(TOP_COMPETITION_PRESETS),
        "presets": [
            {
                "preset": key,
                "label": value.get("label"),
                "odds_api_sport": value.get("odds_api_sport"),
                "api_sports_league": value.get("api_sports_league"),
                "football_data_competition": value.get("football_data_competition"),
            }
            for key, value in TOP_COMPETITION_PRESETS.items()
        ],
    }


def parse_presets_arg(raw: str | None) -> list[str]:
    if not raw:
        return list(TOP_COMPETITION_PRESETS.keys())
    presets = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [item for item in presets if item not in TOP_COMPETITION_PRESETS]
    if unknown:
        raise SystemExit(f"未知 preset: {', '.join(unknown)}")
    return presets


def open_url(
    req: urllib.request.Request,
    timeout: int = 30,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
) -> tuple[str, Any]:
    context = None
    if certifi is not None:
      context = ssl.create_default_context(cafile=certifi.where())
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return body, resp.headers
        except (urllib.error.URLError, TimeoutError, http.client.RemoteDisconnected, ConnectionResetError) as exc:
            attempt += 1
            if attempt > retries:
                raise exc
            time.sleep(retry_delay)


def http_get_json(url: str, headers: dict[str, str], timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    body, _headers = open_url(req, timeout=timeout)
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
    body, headers = open_url(req, timeout=30)
    payload = json.loads(body)
    return {
        "data": payload,
        "x-requests-remaining": headers.get("x-requests-remaining"),
        "x-requests-used": headers.get("x-requests-used"),
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


def run_live_batch_for_inputs(
    inputs_dir: str,
    output_dir: str,
    retries: int = 2,
    retry_delay: float = 2.0,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(ROOT_DIR / "scripts" / "veribet_live_batch.py"),
        "--bundle",
        str(ROOT_DIR / "prompts" / "veribet_prompt_bundle_v412_candidate.yaml"),
        "--inputs",
        str(ROOT_DIR / inputs_dir),
        "--output-dir",
        str(ROOT_DIR / output_dir),
        "--retries",
        str(retries),
        "--retry-delay",
        str(retry_delay),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT_DIR))
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    payload: dict[str, Any] = {
        "exit_code": proc.returncode,
        "command": cmd,
    }
    if stdout:
        try:
            payload["result"] = json.loads(stdout)
        except json.JSONDecodeError:
            payload["stdout"] = stdout
    if stderr:
        payload["stderr"] = stderr
    payload["ok"] = proc.returncode == 0
    return payload


def aggregate_day(
    date: str,
    sport: str | None = None,
    preset: str | None = None,
    competition_filter: str | None = None,
    export_dir: str | None = None,
    api_sports_league: str | None = None,
    api_sports_season: str | None = None,
    api_sports_team: str | None = None,
    football_data_competition: str | None = None,
) -> dict[str, Any]:
    sport, api_sports_league, football_data_competition, competition_filter = resolve_preset(
        preset,
        sport,
        api_sports_league,
        football_data_competition,
        competition_filter,
    )
    actual_sport = sport or "soccer_epl"
    fd = football_data_matches(date, date, football_data_competition)
    api = api_sports_fixtures(date, api_sports_league, api_sports_season, api_sports_team)
    odds = odds_api_scores(actual_sport, None)

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
        "sport": actual_sport,
        "preset": preset,
        "competition_filter": competition_filter,
        "export_dir": export_dir,
        "api_sports_league": api_sports_league,
        "api_sports_season": api_sports_season,
        "api_sports_team": api_sports_team,
        "football_data_competition": football_data_competition,
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


def fetch_and_run_live_day(
    date: str,
    sport: str | None = None,
    preset: str | None = None,
    competition_filter: str | None = None,
    export_dir: str | None = None,
    api_sports_league: str | None = None,
    api_sports_season: str | None = None,
    api_sports_team: str | None = None,
    football_data_competition: str | None = None,
    live_output_dir: str | None = None,
    live_retries: int = 2,
    live_retry_delay: float = 2.0,
) -> dict[str, Any]:
    actual_export_dir = export_dir or f"inputs_auto_{date}"
    aggregate = aggregate_day(
        date=date,
        sport=sport,
        preset=preset,
        competition_filter=competition_filter,
        export_dir=actual_export_dir,
        api_sports_league=api_sports_league,
        api_sports_season=api_sports_season,
        api_sports_team=api_sports_team,
        football_data_competition=football_data_competition,
    )
    actual_live_output_dir = live_output_dir or f"live_outputs_auto_{date}"
    if not aggregate.get("veribet_candidates_count"):
        live = {
            "ok": True,
            "skipped": True,
            "reason": "No exported VeriBet candidates for requested filters",
            "exit_code": 0,
        }
    else:
        live = run_live_batch_for_inputs(
            inputs_dir=actual_export_dir,
            output_dir=actual_live_output_dir,
            retries=live_retries,
            retry_delay=live_retry_delay,
        )
    return {
        "ok": aggregate.get("ok") and live.get("ok"),
        "date": date,
        "inputs_dir": actual_export_dir,
        "live_output_dir": actual_live_output_dir,
        "aggregate": aggregate,
        "live": live,
    }


def scan_top_day(
    date: str,
    presets: list[str],
    api_sports_season: str | None = None,
    run_live: bool = False,
    export_base_dir: str | None = None,
    live_output_base_dir: str | None = None,
) -> dict[str, Any]:
    export_root = export_base_dir or f"inputs_auto_{date}"
    live_root = live_output_base_dir or f"live_outputs_auto_{date}"
    results: list[dict[str, Any]] = []
    ok_count = 0
    for preset in presets:
        export_dir = f"{export_root}/{preset}"
        if run_live:
            live_output_dir = f"{live_root}/{preset}"
            item = fetch_and_run_live_day(
                date=date,
                preset=preset,
                api_sports_season=api_sports_season,
                export_dir=export_dir,
                live_output_dir=live_output_dir,
            )
            aggregate = item.get("aggregate") or {}
            live = item.get("live") or {}
            summary = {
                "preset": preset,
                "ok": item.get("ok"),
                "sport": aggregate.get("sport"),
                "merged_count": aggregate.get("merged_count"),
                "veribet_candidates_count": aggregate.get("veribet_candidates_count"),
                "exported_files": len(aggregate.get("exported_files") or []),
                "live_ok": live.get("ok"),
                "live_skipped": live.get("skipped", False),
            }
        else:
            aggregate = aggregate_day(
                date=date,
                preset=preset,
                api_sports_season=api_sports_season,
                export_dir=export_dir,
            )
            item = {
                "ok": aggregate.get("ok"),
                "date": date,
                "inputs_dir": export_dir,
                "aggregate": aggregate,
            }
            summary = {
                "preset": preset,
                "ok": aggregate.get("ok"),
                "sport": aggregate.get("sport"),
                "merged_count": aggregate.get("merged_count"),
                "veribet_candidates_count": aggregate.get("veribet_candidates_count"),
                "exported_files": len(aggregate.get("exported_files") or []),
            }
        if item.get("ok"):
            ok_count += 1
        item["summary"] = summary
        results.append(item)

    return {
        "ok": ok_count == len(results),
        "date": date,
        "run_live": run_live,
        "presets": presets,
        "api_sports_season": api_sports_season,
        "export_base_dir": export_root,
        "live_output_base_dir": live_root if run_live else None,
        "total_presets": len(results),
        "ok_presets": ok_count,
        "results": results,
        "summaries": [item["summary"] for item in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Query configured football data sources for VeriBet.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV), help="Path to .env.data_sources")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Check which data-source keys are configured")
    sub.add_parser("top-competitions", help="List built-in top competition presets")
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
    p_agg.add_argument("--sport")
    p_agg.add_argument("--preset", choices=sorted(TOP_COMPETITION_PRESETS.keys()))
    p_agg.add_argument("--competition", help="Case-insensitive substring filter on competition/league name")
    p_agg.add_argument("--export-dir", help="Write veribet_candidates into this repo-relative directory")
    p_agg.add_argument("--api-sports-league", help="Exact API-SPORTS league id filter")
    p_agg.add_argument("--api-sports-season", help="API-SPORTS season, usually YYYY")
    p_agg.add_argument("--api-sports-team", help="API-SPORTS team id filter")
    p_agg.add_argument("--football-data-competition", help="football-data competition code such as PL, ELC, CL")

    p_fetch_live = sub.add_parser("fetch-live-day", help="Fetch one day, export inputs, and run VeriBet live batch")
    p_fetch_live.add_argument("--date", required=True)
    p_fetch_live.add_argument("--sport")
    p_fetch_live.add_argument("--preset", choices=sorted(TOP_COMPETITION_PRESETS.keys()))
    p_fetch_live.add_argument("--competition", help="Case-insensitive substring filter on competition/league name")
    p_fetch_live.add_argument("--export-dir", help="Repo-relative directory to write input JSON files")
    p_fetch_live.add_argument("--api-sports-league", help="Exact API-SPORTS league id filter")
    p_fetch_live.add_argument("--api-sports-season", help="API-SPORTS season, usually YYYY")
    p_fetch_live.add_argument("--api-sports-team", help="API-SPORTS team id filter")
    p_fetch_live.add_argument("--football-data-competition", help="football-data competition code such as PL, ELC, CL")
    p_fetch_live.add_argument("--live-output-dir", help="Repo-relative directory to write VeriBet live result JSON files")
    p_fetch_live.add_argument("--live-retries", type=int, default=2)
    p_fetch_live.add_argument("--live-retry-delay", type=float, default=2.0)

    p_scan = sub.add_parser("scan-top-day", help="Run aggregate/export or live workflow across top competition presets")
    p_scan.add_argument("--date", required=True)
    p_scan.add_argument("--presets", help="Comma-separated preset names; default is all top presets")
    p_scan.add_argument("--api-sports-season", help="API-SPORTS season, usually YYYY")
    p_scan.add_argument("--run-live", action="store_true", help="Also run VeriBet live batch for each preset")
    p_scan.add_argument("--export-base-dir", help="Base repo-relative directory for exported inputs")
    p_scan.add_argument("--live-output-base-dir", help="Base repo-relative directory for live outputs when --run-live is used")

    args = parser.parse_args()
    load_env_file(Path(args.env_file))

    if args.command == "check":
        result = {"ok": True, "configured": check_sources()}
    elif args.command == "top-competitions":
        result = list_top_competitions()
    elif args.command == "football-data-competitions":
        result = football_data_competitions()
    elif args.command == "football-data-matches":
        result = football_data_matches(args.date_from, args.date_to, args.competition)
    elif args.command == "api-sports-fixtures":
        result = api_sports_fixtures(args.date, args.league, args.season, args.team)
    elif args.command == "odds-api-scores":
        result = odds_api_scores(args.sport, args.days_from)
    elif args.command == "aggregate-day":
        result = aggregate_day(
            args.date,
            args.sport,
            args.preset,
            args.competition,
            args.export_dir,
            args.api_sports_league,
            args.api_sports_season,
            args.api_sports_team,
            args.football_data_competition,
        )
    elif args.command == "fetch-live-day":
        result = fetch_and_run_live_day(
            date=args.date,
            sport=args.sport,
            preset=args.preset,
            competition_filter=args.competition,
            export_dir=args.export_dir,
            api_sports_league=args.api_sports_league,
            api_sports_season=args.api_sports_season,
            api_sports_team=args.api_sports_team,
            football_data_competition=args.football_data_competition,
            live_output_dir=args.live_output_dir,
            live_retries=args.live_retries,
            live_retry_delay=args.live_retry_delay,
        )
    elif args.command == "scan-top-day":
        result = scan_top_day(
            date=args.date,
            presets=parse_presets_arg(args.presets),
            api_sports_season=args.api_sports_season,
            run_live=args.run_live,
            export_base_dir=args.export_base_dir,
            live_output_base_dir=args.live_output_base_dir,
        )
    else:
        raise SystemExit(f"unsupported command: {args.command}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
