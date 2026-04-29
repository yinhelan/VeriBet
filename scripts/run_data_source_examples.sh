#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "== configured keys =="
python3 scripts/veribet_data_sources.py check

echo
echo "== football-data competitions =="
python3 scripts/veribet_data_sources.py football-data-competitions
