#!/usr/bin/env bash
set -euo pipefail

API_BASE="${VERIBET_API_BASE:-http://127.0.0.1:8012}"

usage() {
  cat <<'EOF'
Usage:
  scripts/veribet_api_client.sh health
  scripts/veribet_api_client.sh jobs [query]
  scripts/veribet_api_client.sh job <job_id>
  scripts/veribet_api_client.sh delete-job <job_id>
  scripts/veribet_api_client.sh cleanup [keep]
  scripts/veribet_api_client.sh batch-dir <inputs_path> [output_dir]
  scripts/veribet_api_client.sh ingest-review-and-test <input_path> <ft_score> [ht_score]

Environment:
  VERIBET_API_BASE  Default: http://127.0.0.1:8012
EOF
}

cmd="${1:-}"
if [[ -z "$cmd" ]]; then
  usage
  exit 1
fi
shift || true

case "$cmd" in
  health)
    curl -s "$API_BASE/healthz"
    ;;

  jobs)
    query="${1:-}"
    if [[ -n "$query" ]]; then
      curl -s "$API_BASE/api/jobs?$query"
    else
      curl -s "$API_BASE/api/jobs"
    fi
    ;;

  job)
    job_id="${1:-}"
    [[ -n "$job_id" ]] || { echo "job_id is required" >&2; exit 1; }
    curl -s "$API_BASE/api/jobs/$job_id"
    ;;

  delete-job)
    job_id="${1:-}"
    [[ -n "$job_id" ]] || { echo "job_id is required" >&2; exit 1; }
    curl -s -X DELETE "$API_BASE/api/jobs/$job_id"
    ;;

  cleanup)
    keep="${1:-20}"
    curl -s -X POST "$API_BASE/api/jobs/cleanup" \
      -H 'Content-Type: application/json' \
      -d "{\"keep\":$keep,\"statuses\":[\"completed\",\"failed\"],\"job_types\":[\"ingest_review_and_test\"]}"
    ;;

  batch-dir)
    inputs_path="${1:-}"
    output_dir="${2:-live_outputs_api_batch}"
    [[ -n "$inputs_path" ]] || { echo "inputs_path is required" >&2; exit 1; }
    curl -s -X POST "$API_BASE/api/live/batch" \
      -H 'Content-Type: application/json' \
      -d "{\"inputs_path\":\"$inputs_path\",\"output_dir\":\"$output_dir\"}"
    ;;

  ingest-review-and-test)
    input_path="${1:-}"
    ft_score="${2:-}"
    ht_score="${3:-}"
    [[ -n "$input_path" ]] || { echo "input_path is required" >&2; exit 1; }
    [[ -n "$ft_score" ]] || { echo "ft_score is required" >&2; exit 1; }
    stem="$(basename "$input_path" .json)"
    payload="{\"input_path\":\"$input_path\",\"ft_score\":\"$ft_score\",\"result_output_path\":\"live_outputs/${stem}.result.json\",\"review_output_path\":\"reviews/${stem}.review.json\",\"patch_output_path\":\"patches/${stem}.candidate.json\",\"patch_test_output_dir\":\"patch_test_runs/${stem}\",\"patch_test_retries\":1}"
    if [[ -n "$ht_score" ]]; then
      payload="{\"input_path\":\"$input_path\",\"ft_score\":\"$ft_score\",\"ht_score\":\"$ht_score\",\"result_output_path\":\"live_outputs/${stem}.result.json\",\"review_output_path\":\"reviews/${stem}.review.json\",\"patch_output_path\":\"patches/${stem}.candidate.json\",\"patch_test_output_dir\":\"patch_test_runs/${stem}\",\"patch_test_retries\":1}"
    fi
    curl -s -X POST "$API_BASE/api/jobs/ingest-review-and-test" \
      -H 'Content-Type: application/json' \
      -d "$payload"
    ;;

  *)
    usage
    exit 1
    ;;
esac
