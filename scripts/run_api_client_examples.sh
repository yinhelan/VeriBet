#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== health =="
scripts/veribet_api_client.sh health

echo
echo "== jobs =="
scripts/veribet_api_client.sh jobs
