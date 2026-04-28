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

inputs_path="${1:-inputs}"
output_dir="${2:-live_outputs}"
retries="${VERIBET_LIVE_RETRIES:-2}"
retry_delay="${VERIBET_LIVE_RETRY_DELAY:-2}"

python3 scripts/veribet_live_batch.py \
  --bundle prompts/veribet_prompt_bundle_v412_candidate.yaml \
  --inputs "$inputs_path" \
  --output-dir "$output_dir" \
  --retries "$retries" \
  --retry-delay "$retry_delay"
