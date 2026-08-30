#!/usr/bin/env bash
# Re-extract each policy as an independent run.
#
# Per policy rather than one batch: a failure costs one policy, not six, and
# any single policy can be re-run on its own without redoing the rest. Each
# gets its own log so a failure is diagnosable without scrolling past five
# healthy runs.
#
# Sequential, not parallel. Six concurrent runs share one Vertex quota and a
# 429 storm costs more time than the concurrency saves.
#
# Each successful extraction is immediately put through preload_check.py.
# Nothing is loaded to BigQuery here — that stays a separate, deliberate step.
set -u
cd "$(dirname "$0")"

PROJECT=project-37e668b0-6b36-4e1f-a02
SUFFIX=v15
mkdir -p logs
RESULTS=()

run () {   # pdf, insurer, policy-name, policy-id
  pdf="$1"; ins="$2"; name="$3"; pid="$4"
  out="${pid}_${SUFFIX}.jsonl"
  log="logs/${pid}.log"

  echo "=== ${pid}: extracting -> ${out}  (log: ${log})"
  python extract_policy_v13.py "$pdf" \
    --insurer "$ins" --policy-name "$name" --policy-id "$pid" \
    --out "$out" --items-out "${pid}_items_${SUFFIX}.jsonl" \
    --vertex --project "$PROJECT" --location global --rpm 0 \
    > "$log" 2>&1
  ex=$?

  if [ "$ex" -ne 0 ]; then
    echo "=== ${pid}: EXTRACTION FAILED, exit ${ex}"
    grep -E "INCOMPLETE|CHUNK FAILED" "$log" | head -5
    RESULTS+=("${pid}: extract FAILED(${ex}), check skipped")
    return
  fi

  written=$(grep -oE "^Wrote [0-9]+ clauses" "$log" | grep -oE "[0-9]+" | head -1)
  echo "=== ${pid}: extracted ${written:-?} clauses, running preload_check"
  python preload_check.py "$out" >> "$log" 2>&1
  cx=$?
  if [ "$cx" -eq 0 ]; then
    echo "=== ${pid}: PASSED preload_check"
    RESULTS+=("${pid}: ${written:-?} clauses, check PASSED")
  else
    echo "=== ${pid}: REFUSED by preload_check"
    grep -E "^  [a-z_]+  x[0-9]+" "$log" | tail -8
    RESULTS+=("${pid}: ${written:-?} clauses, check REFUSED")
  fi
}

run "Policy_Arogya_Sanjeevani_Insurance_Policy_V_12_84d133b97f.pdf" \
    "Star Health" "Arogya Sanjeevani" "star_arogya_sanjeevani"
run "PolicyWordings_myOptimaSecure-76673175551.pdf" \
    "HDFC Ergo" "Optima Secure" "hdfc_optima_secure"
run "elevate.pdf" \
    "ICICI Lombard" "Elevate" "icici_elevate"
run "ReAssure-Policy-Wording.pdf" \
    "Niva Bupa" "ReAssure" "niva_reassure"
run "ReAssure30_Policy_Wordings.pdf" \
    "Niva Bupa" "ReAssure 3.0" "niva_reassure_30"
run "medicare_select_policy_wording_0faeeb61c5.pdf" \
    "Tata AIG" "Medicare Select" "tata_medicare_select"

echo
echo "=================== SUMMARY ==================="
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo "ALL SIX ATTEMPTED"
