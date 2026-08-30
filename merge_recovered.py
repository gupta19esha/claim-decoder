"""
Bring forward clauses the new extraction lost.

The re-extraction is a large net improvement but it is not deterministic:
across the six policies 80 clauses present before were absent after. 61 of
those were absorbed into a longer clause, which is the overlap and dedupe
working as intended. About 14 had no trace at all — the model simply did not
return them this time.

This recovers only that last group, and only the ones that pass the gates. A
naive union of old and new would not do: the contaminated ICICI clauses are
not substrings of their clean replacements, so they would survive the merge
and put the page footer back into the corpus.

    python merge_recovered.py            # report only
    python merge_recovered.py --write     # write <policy>_v15_merged.jsonl
"""

import argparse
import json
import re

from compare_extractions import load, match, body, norm
from extract_policy_v13 import dedupe_records
from quality_gates import GATES, BLOCKING

PAIRS = [
    ("star_arogya_sanjeevani", "star_clauses.jsonl",
     "star_arogya_sanjeevani_v15.jsonl"),
    ("hdfc_optima_secure", "hdfc_optima_clauses.jsonl",
     "hdfc_optima_secure_v15.jsonl"),
    ("icici_elevate", "icici_elevate_clauses.jsonl",
     "icici_elevate_v15.jsonl"),
    ("niva_reassure", "niva_reassure_clauses.jsonl",
     "niva_reassure_v15.jsonl"),
    ("niva_reassure_30", "niva_reassure30_clauses.jsonl",
     "niva_reassure_30_v15.jsonl"),
    ("tata_medicare_select", "tata_medicare_clauses.jsonl",
     "tata_medicare_select_v15.jsonl"),
]


def blocking_findings(rec):
    out = []
    for gate in GATES:
        res = gate(rec)
        if res and res[0] in BLOCKING:
            out.append(res)
    return out


def gone_from(old, new):
    """Old clauses with no trace anywhere in the new extraction."""
    _, only_old, _ = match(old, new)
    haystack = " || ".join(norm(body(r)) for r in new)
    gone = []
    for rec in only_old:
        n = norm(body(rec))
        if not n:
            continue
        if n in haystack:
            continue                       # absorbed into a longer clause
        probe = n[len(n) // 3:len(n) // 3 + 60]
        if probe and probe in haystack:
            continue                       # partially present
        gone.append(rec)
    return gone


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--suffix", default="_merged")
    args = ap.parse_args()

    total_kept = total_rejected = 0
    for policy, old_path, new_path in PAIRS:
        old, new = load(old_path), load(new_path)
        gone = gone_from(old, new)

        kept, rejected = [], []
        for rec in gone:
            problems = blocking_findings(rec)
            (rejected if problems else kept).append((rec, problems))

        print(f"\n=== {policy}")
        print(f"  new extraction: {len(new)} clauses")
        print(f"  lost with no trace: {len(gone)}")
        for rec, _ in kept:
            print(f"    KEEP   p{rec.get('source_page'):<4} "
                  f"len={len(body(rec)):5d} [{rec.get('clause_type')}] "
                  f"{str(rec.get('clause_title'))[:44]}")
        for rec, problems in rejected:
            why = ", ".join(p[0] for p in problems)
            print(f"    DROP   p{rec.get('source_page'):<4} "
                  f"len={len(body(rec)):5d} {str(rec.get('clause_title'))[:36]}"
                  f"  <- {why}")

        merged = new + [r for r, _ in kept]
        merged, dupes = dedupe_records(merged)
        print(f"  merged: {len(new)} + {len(kept)} recovered "
              f"- {len(dupes)} deduped = {len(merged)}")

        total_kept += len(kept)
        total_rejected += len(rejected)

        if args.write:
            stem = re.sub(r"\.jsonl$", "", new_path) + args.suffix
            with open(stem + ".jsonl", "w", encoding="utf-8") as f:
                for r in merged:
                    r.pop("_line", None)
                    r.pop("_source_file", None)
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")

            # The merged file is the extraction run plus clauses carried over
            # from an older one, so it needs its own manifest saying so.
            # Pointing the gate at the unmodified v15 manifest would claim a
            # provenance the file no longer has.
            man = json.load(open(re.sub(r"\.jsonl$", "", new_path)
                                 + ".manifest.json", encoding="utf-8"))
            man["records_written"] = len(merged)
            man["recovered_from"] = old_path
            man["recovered_count"] = len(kept)
            man["recovered_clauses"] = [
                {"source_page": r.get("source_page"),
                 "clause_title": r.get("clause_title"),
                 "chars": len(body(r))} for r, _ in kept]
            man["recovery_refused"] = [
                {"source_page": r.get("source_page"),
                 "clause_title": r.get("clause_title"),
                 "failed": [p[0] for p in problems]}
                for r, problems in rejected]
            with open(stem + ".manifest.json", "w", encoding="utf-8") as f:
                json.dump(man, f, indent=2, ensure_ascii=False)
            print(f"  wrote {stem}.jsonl and {stem}.manifest.json")

    print(f"\nrecovered {total_kept} clauses, "
          f"refused {total_rejected} that failed the gates")


if __name__ == "__main__":
    main()
