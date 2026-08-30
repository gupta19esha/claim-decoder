"""
Short-field verbatim audit.

verify_verbatim in the extraction script guards clause_text. Nothing guards
the short fields, and two of them reach the user's screen: clause_title is the
heading on the exhibit card, exclusion_code is printed in the metadata strip
(frontend/src/App.jsx). If the model rewrites those, the product is showing
invented text under a banner that says "Quoted word for word".

This checks each short field against the page it came from, using the same
PDF pipeline the extractor used so the comparison is like for like.

Verdicts:
  verbatim    the stored value is printed on that page
  normalised  matches once case, spacing and punctuation are folded away
  altered     a value of the same shape is printed, but not this one
  absent      nothing comparable on the page

Usage:
    python audit_short_fields.py
"""

import json
import re
import sys
from collections import Counter, defaultdict

from extract_policy_v13 import read_pdf, normalise

CORPUS = [
    ("star_arogya_sanjeevani", "star_clauses.jsonl",
     "Policy_Arogya_Sanjeevani_Insurance_Policy_V_12_84d133b97f.pdf"),
    ("hdfc_optima_secure", "hdfc_optima_clauses.jsonl",
     "PolicyWordings_myOptimaSecure-76673175551.pdf"),
    ("icici_elevate", "icici_elevate_clauses.jsonl", "elevate.pdf"),
    ("niva_reassure", "niva_reassure_clauses.jsonl",
     "ReAssure-Policy-Wording.pdf"),
    ("niva_reassure_30", "niva_reassure30_clauses.jsonl",
     "ReAssure30_Policy_Wordings.pdf"),
    ("tata_medicare_select", "tata_medicare_clauses.jsonl",
     "medicare_select_policy_wording_0faeeb61c5.pdf"),
]

CODE_RE = re.compile(r"E[xX][ce][lI1]\s*\.?\s*-?\s*\d{1,2}")


def soft(s):
    """Fold the differences nobody would call a rewrite."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def check_against_page(value, page_text, shape_re=None):
    if not value:
        return None
    if value in page_text:
        return "verbatim"
    if soft(value) and soft(value) in soft(page_text):
        return "normalised"
    if shape_re:
        printed = shape_re.findall(page_text)
        if printed:
            digits = re.sub(r"[^0-9]", "", value)
            if any(re.sub(r"[^0-9]", "", p) == digits for p in printed):
                return "altered"
    return "absent"


def check_in_text(value, clause_text):
    """For fields that should sit inside the clause body, like cap_basis."""
    if not value:
        return None
    if value in clause_text:
        return "verbatim"
    if soft(value) and soft(value) in soft(clause_text):
        return "normalised"
    return "absent"


def main():
    # Widen a page lookup by one either side. resolve_page can legitimately
    # land a clause on the page it starts on while the heading sits at the
    # foot of the page before.
    tallies = defaultdict(Counter)
    examples = defaultdict(list)

    for policy_id, jsonl, pdf in CORPUS:
        print(f"reading {pdf} ...", flush=True)
        pages, _, _ = read_pdf(pdf)
        page_text = {p: t for p, t in pages}

        def window(pg):
            return "\n".join(page_text.get(p, "")
                             for p in (pg - 1, pg, pg + 1) if p in page_text)

        recs = [json.loads(l) for l in open(jsonl, encoding="utf-8") if l.strip()]
        for r in recs:
            pg = r.get("source_page")
            if not isinstance(pg, int):
                continue
            win = window(pg)

            for field, shape in (("exclusion_code", CODE_RE),
                                 ("clause_id", None),
                                 ("clause_title", None)):
                v = check_against_page(r.get(field), win, shape)
                if v:
                    tallies[field][v] += 1
                    if v in ("altered", "absent"):
                        examples[field].append((policy_id, pg, r.get(field),
                                                r.get("clause_title")))

            v = check_in_text(r.get("cap_basis"), r.get("clause_text") or "")
            if v:
                tallies["cap_basis"][v] += 1
                if v == "absent":
                    examples["cap_basis"].append((policy_id, pg,
                                                  r.get("cap_basis"),
                                                  r.get("clause_title")))

    print("\n" + "=" * 78)
    print("SHORT FIELD VERBATIM STATUS")
    print("=" * 78)
    for field in ("exclusion_code", "clause_id", "clause_title", "cap_basis"):
        t = tallies[field]
        total = sum(t.values())
        if not total:
            continue
        print(f"\n{field}  ({total} populated)")
        for k in ("verbatim", "normalised", "altered", "absent"):
            if t[k]:
                print(f"    {k:12s} {t[k]:4d}  {t[k] / total:5.1%}")

    print("\n" + "=" * 78)
    print("EXAMPLES")
    print("=" * 78)
    for field in ("exclusion_code", "cap_basis", "clause_title"):
        items = examples[field][:12]
        if not items:
            continue
        print(f"\n--- {field} ({len(examples[field])} flagged)")
        for policy, pg, val, title in items:
            print(f"  {policy[:20]:20s} p{pg:<4} {str(val)[:44]:44s} "
                  f"| {str(title)[:28]}")


if __name__ == "__main__":
    main()
