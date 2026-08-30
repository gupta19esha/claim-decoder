"""
Assemble the v17 corpus.

Three policies were re-extracted for the furniture fixes. Three were not,
because neither fix changes their page text and re-running them would spend
credits to reproduce what we already have while swapping a known-good file
for a differently-sampled one.

Extraction is not deterministic, so a re-run gains some clauses and loses
others. Anything the new run dropped is carried forward from v16 — but only
if it passes the gates, which is what keeps the four masthead-contaminated
Star clauses from coming back in through the side door.

    python build_v17.py --write
"""

import argparse
import json
import re
import sys

sys.path.insert(0, ".")
from compare_extractions import match, body, norm          # noqa: E402
from extract_policy_v13 import dedupe_records              # noqa: E402
from quality_gates import GATES, BLOCKING                  # noqa: E402

PREVIOUS = "clauses_v16_all.jsonl"
OUT = "clauses_v17_all.jsonl"

REEXTRACTED = {
    "hdfc_optima_secure": "hdfc_optima_secure_v17.jsonl",
    "icici_elevate": "icici_elevate_v17.jsonl",
    # Two runs: the first lost page 22 entirely, the second did not.
    "star_arogya_sanjeevani": "star_arogya_sanjeevani_v17b.jsonl",
}
UNCHANGED = ("niva_reassure", "niva_reassure_30", "tata_medicare_select")


def blocking_findings(rec):
    out = []
    for gate in GATES:
        res = gate(rec)
        if res and res[0] in BLOCKING:
            out.append(res[0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    prev = [json.loads(l) for l in open(PREVIOUS, encoding="utf-8") if l.strip()]
    final = []

    for pid in sorted(REEXTRACTED) + list(UNCHANGED):
        old = [r for r in prev if r["policy_id"] == pid]

        if pid in UNCHANGED:
            final.extend(old)
            print(f"{pid:24s} carried forward unchanged: {len(old)}")
            continue

        new = [json.loads(l) for l in open(REEXTRACTED[pid], encoding="utf-8")
               if l.strip()]
        _, only_old, _ = match(old, new)
        hay = " || ".join(norm(body(r)) for r in new)

        kept, refused = [], []
        for rec in only_old:
            n = norm(body(rec))
            if not n:
                continue
            if n in hay:
                continue                                  # absorbed
            probe = n[len(n) // 3:len(n) // 3 + 60]
            if probe and probe in hay:
                continue                                  # partly present
            bad = blocking_findings(rec)
            (refused if bad else kept).append((rec, bad))

        merged, dupes = dedupe_records(new + [r for r, _ in kept])
        final.extend(merged)

        print(f"{pid:24s} {len(old)} -> {len(new)} re-extracted, "
              f"+{len(kept)} recovered, -{len(dupes)} deduped = {len(merged)}")
        for rec, bad in refused:
            print(f"     REFUSED p{rec.get('source_page')} "
                  f"{str(rec.get('clause_title'))[:38]}  <- {', '.join(bad)}")

    print(f"\ntotal: {len(final)} clauses")
    if args.write:
        with open(OUT, "w", encoding="utf-8") as f:
            for r in final:
                for k in ("_line", "_source_file"):
                    r.pop(k, None)
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
