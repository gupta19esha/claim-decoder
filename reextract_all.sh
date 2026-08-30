#!/usr/bin/env bash
# Re-extract all six policies with the furniture ceiling and chunk overlap.
# Sequential on purpose: parallel runs share one Vertex quota and a 429
# storm costs more time than it saves.
set -u
cd "$(dirname "$0")"

PROJECT=project-37e668b0-6b36-4e1f-a02
SUFFIX=v15

run () {   # pdf, insurer, policy-name, policy-id
  echo "=================================================================="
  echo "== $4"
  echo "=================================================================="
  python extract_policy_v13.py "$1" \
    --insurer "$2" --policy-name "$3" --policy-id "$4" \
    --out "${4}_${SUFFIX}.jsonl" --items-out "${4}_items_${SUFFIX}.jsonl" \
    --vertex --project "$PROJECT" --location global --rpm 0
  echo "== exit $? for $4"
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

echo "ALL SIX DONE"
