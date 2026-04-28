#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

python -m pip install --upgrade pip >/dev/null
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

mkdir -p outputs

base_outputs="outputs/veribet_full_outputs.yaml"
base_report="outputs/veribet_full_report.json"
retry_outputs="outputs/veribet_retry_outputs.yaml"
merged_outputs="outputs/veribet_full_outputs_merged.yaml"
merged_report="outputs/veribet_full_report_merged.json"
retry_attempts=3

python3 scripts/veribet_runner.py \
  --pack packs/veribet_regression_pack_v1.yaml \
  --bundle prompts/veribet_prompt_bundle_v412_candidate.yaml \
  --model "$OPENAI_MODEL" \
  --base-url "$OPENAI_BASE_URL" \
  --outputs "$base_outputs" \
  --report "$base_report"

retry_case_ids="$(
python3 - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("outputs/veribet_full_report.json").read_text(encoding="utf-8"))
case_ids = []
for case in report.get("cases", []):
    if not case.get("passed"):
        case_ids.append(case["id"])
print(" ".join(case_ids))
PY
)"

if [ -z "$retry_case_ids" ]; then
  echo "No failed cases. Full report is already clean."
  exit 0
fi

current_retry_ids="$retry_case_ids"
attempt=1
cp "$base_outputs" "$merged_outputs"

while [ -n "$current_retry_ids" ] && [ "$attempt" -le "$retry_attempts" ]; do
  echo "Retry attempt $attempt/$retry_attempts for: $current_retry_ids"

  runner_args=()
  for case_id in $current_retry_ids; do
    runner_args+=(--case-id "$case_id")
  done

  python3 scripts/veribet_runner.py \
    --pack packs/veribet_regression_pack_v1.yaml \
    --bundle prompts/veribet_prompt_bundle_v412_candidate.yaml \
    --model "$OPENAI_MODEL" \
    --base-url "$OPENAI_BASE_URL" \
    "${runner_args[@]}" \
    --outputs "$retry_outputs"

  python3 - <<'PY'
import yaml
from pathlib import Path

base_path = Path("outputs/veribet_full_outputs_merged.yaml")
retry_path = Path("outputs/veribet_retry_outputs.yaml")
merged_path = Path("outputs/veribet_full_outputs_merged.yaml")

base = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
retry = yaml.safe_load(retry_path.read_text(encoding="utf-8")) or {}

retry_map = {item.get("id"): item for item in retry.get("cases", [])}
merged_cases = []
seen = set()

for item in base.get("cases", []):
    case_id = item.get("id")
    if case_id in retry_map:
        merged_cases.append(retry_map[case_id])
        seen.add(case_id)
    else:
        merged_cases.append(item)
        seen.add(case_id)

for case_id, item in retry_map.items():
    if case_id not in seen:
        merged_cases.append(item)

base["cases"] = merged_cases
merged_path.write_text(yaml.safe_dump(base, allow_unicode=True, sort_keys=False), encoding="utf-8")
print(merged_path)
PY

  python3 scripts/veribet_eval.py \
    --pack packs/veribet_regression_pack_v1.yaml \
    --outputs "$merged_outputs" \
    --report "$merged_report" >/dev/null

  current_retry_ids="$(
  python3 - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("outputs/veribet_full_report_merged.json").read_text(encoding="utf-8"))
case_ids = []
for case in report.get("cases", []):
    if not case.get("passed"):
        case_ids.append(case["id"])
print(" ".join(case_ids))
PY
  )"

  attempt=$((attempt + 1))
done

python3 scripts/veribet_eval.py \
  --pack packs/veribet_regression_pack_v1.yaml \
  --outputs "$merged_outputs" \
  --report "$merged_report"

echo "Merged outputs: $merged_outputs"
echo "Merged report: $merged_report"
