#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
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
    with urllib.request.urlopen(req, timeout=30) as resp:
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
    else:
        raise SystemExit(f"unsupported command: {args.command}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
