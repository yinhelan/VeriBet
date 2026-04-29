#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
source .venv/bin/activate

if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

HOST="${VERIBET_API_HOST:-127.0.0.1}"
PORT="${VERIBET_API_PORT:-8012}"

python3 scripts/veribet_api.py --host "$HOST" --port "$PORT"
