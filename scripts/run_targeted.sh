#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

source .venv/bin/activate

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

mkdir -p outputs

python3 scripts/veribet_runner.py \
  --pack packs/veribet_regression_pack_v1.yaml \
  --bundle prompts/veribet_prompt_bundle_v412_candidate.yaml \
  --model "$OPENAI_MODEL" \
  --base-url "$OPENAI_BASE_URL" \
  --case-id VB-007 \
  --case-id VB-013 \
  --outputs outputs/veribet_targeted_outputs.yaml \
  --report outputs/veribet_targeted_report.json
