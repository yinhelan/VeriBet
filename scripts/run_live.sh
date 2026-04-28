#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

source .venv/bin/activate

python -m pip install pyyaml certifi >/dev/null

if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

: "${OPENAI_API_KEY:?OPENAI_API_KEY 未设置}"
: "${OPENAI_MODEL:?OPENAI_MODEL 未设置}"
: "${OPENAI_BASE_URL:=https://api.openai.com/v1}"
: "${SSL_CERT_FILE:=$(python -c 'import certifi; print(certifi.where())')}"

export SSL_CERT_FILE

input_path="${1:-inputs/live_match_input.json}"
output_path="${2:-live_result.json}"
retries="${VERIBET_LIVE_RETRIES:-2}"
retry_delay="${VERIBET_LIVE_RETRY_DELAY:-2}"

mkdir -p "$(dirname "$output_path")"

python3 scripts/veribet_live.py \
  --bundle prompts/veribet_prompt_bundle_v412_candidate.yaml \
  --input "$input_path" \
  --output "$output_path" \
  --retries "$retries" \
  --retry-delay "$retry_delay"
