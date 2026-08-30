#!/usr/bin/env bash
# Re-extract only the three policies the furniture fixes change.
#
# Niva, Niva 3.0 and Tata are untouched by both fixes: neither has a bare
# page-number line surviving, and neither carries a gutter-truncated
# masthead. Re-running them would spend credits to reproduce what we already
# have, and would swap a known-good file for a differently-sampled one.
set -u
cd "$(dirname "$0")"

PROJECT=project-37e668b0-6b36-4e1f-a02
SUFFIX=v17
mkdir -p logs

run () {
  pdf="$1"; ins="$2"; name="$3"; pid="$4"
  out="${pid}_${SUFFIX}.jsonl"
  log="logs/${pid}_${SUFFIX}.log"
  echo "=== ${pid}: extracting"
  python extract_policy_v13.py "$pdf" \
    --insurer "$ins" --policy-name "$name" --policy-id "$pid" \
    --out "$out" --items-out "${pid}_items_${SUFFIX}.jsonl" \
    --vertex --project "$PROJECT" --location global --rpm 0 > "$log" 2>&1
  ex=$?
  written=$(grep -oE "^Wrote [0-9]+ clauses" "$log" | grep -oE "[0-9]+" | head -1)
  echo "=== ${pid}: exit ${ex}, ${written:-0} clauses"
  grep -E "chunk boundaries|Dropped [0-9]+ of|INCOMPLETE" "$log" | head -3
}

run "PolicyWordings_myOptimaSecure-76673175551.pdf" \
    "HDFC Ergo" "Optima Secure" "hdfc_optima_secure"
run "elevate.pdf" \
    "ICICI Lombard" "Elevate" "icici_elevate"
run "Policy_Arogya_Sanjeevani_Insurance_Policy_V_12_84d133b97f.pdf" \
    "Star Health" "Arogya Sanjeevani" "star_arogya_sanjeevani"

echo "THREE DONE"
