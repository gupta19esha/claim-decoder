"""
Page-level impact of raising the furniture length ceiling.

Runs the extractor's page assembly twice, once with the old caps (100 in
learn_furniture, 90 in is_furniture) and once with the new one, and reports
exactly which lines the change removes. Free: no model calls.

The point is to decide re-extraction scope. A document whose page text does
not change does not need re-extracting.
"""

import os
import sys

import pdfplumber

import extract_policy_v13 as ex
from extract_policy_v13 import (page_text, _furniture_key, _edge_keys,
                                strip_furniture)

DOCS = [
    ("star_arogya_sanjeevani",
     "Policy_Arogya_Sanjeevani_Insurance_Policy_V_12_84d133b97f.pdf"),
    ("hdfc_optima_secure", "PolicyWordings_myOptimaSecure-76673175551.pdf"),
    ("icici_elevate", "elevate.pdf"),
    ("niva_reassure", "ReAssure-Policy-Wording.pdf"),
    ("niva_reassure_30", "ReAssure30_Policy_Wordings.pdf"),
    ("tata_medicare_select", "medicare_select_policy_wording_0faeeb61c5.pdf"),
]


def learn(raw_pages, cap, threshold=0.5):
    counts = {}
    n = len(raw_pages)
    for _, text in raw_pages:
        for line in {_furniture_key(l) for l in text.split("\n") if l.strip()}:
            if line:
                counts[line] = counts.get(line, 0) + 1
    return {k for k, c in counts.items()
            if c >= max(2, n * threshold) and len(k) <= cap}


def fuzzy(line, furniture, cap, min_overlap=22):
    key = _furniture_key(line)
    if not key:
        return False
    if key in furniture:
        return True
    if len(key) > cap:
        return False
    for known in furniture:
        if len(key) > len(known) + 32:
            continue
        overlap = os.path.commonprefix([key, known])
        if (len(overlap) >= min_overlap
                and len(overlap) >= 0.6 * min(len(key), len(known))):
            return True
    return False


def strip(raw, edges, furniture, cap):
    out = []
    for (i, text), edge in zip(raw, edges):
        kept = []
        for l in text.split("\n"):
            k = _furniture_key(l)
            if k and k in furniture:
                continue
            if k and k in edge and fuzzy(l, furniture, cap):
                continue
            kept.append(l)
        out.append((i, strip_furniture("\n".join(kept))))
    return out


def main():
    print(f"new ceiling: FURNITURE_MAX_LEN = {ex.FURNITURE_MAX_LEN}\n")
    print(f"{'policy':24s}{'pages':>6s}{'lines cut old':>15s}"
          f"{'lines cut new':>15s}{'extra':>8s}{'chars removed':>15s}")
    print("-" * 84)
    details = []
    for policy, path in DOCS:
        raw, edges = [], []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text, _, _, segs = page_text(page, None)
                raw.append((i, text))
                edges.append(_edge_keys(segs))

        old_pages = strip(raw, edges, learn(raw, 100), 90)
        new_pages = strip(raw, edges, learn(raw, ex.FURNITURE_MAX_LEN),
                          ex.FURNITURE_MAX_LEN)

        raw_lines = sum(len([l for l in t.split("\n")]) for _, t in raw)
        old_lines = sum(len(t.split("\n")) for _, t in old_pages)
        new_lines = sum(len(t.split("\n")) for _, t in new_pages)
        old_chars = sum(len(t) for _, t in old_pages)
        new_chars = sum(len(t) for _, t in new_pages)

        print(f"{policy:24s}{len(raw):6d}{raw_lines - old_lines:15d}"
              f"{raw_lines - new_lines:15d}{old_lines - new_lines:8d}"
              f"{old_chars - new_chars:15d}")

        if old_lines != new_lines:
            gone = set()
            for (_, o), (_, n) in zip(old_pages, new_pages):
                gone |= set(o.split("\n")) - set(n.split("\n"))
            details.append((policy, gone))

    print("\n" + "=" * 84)
    print("LINES THE FIX NOW REMOVES  (must all be furniture)")
    print("=" * 84)
    for policy, gone in details:
        print(f"\n-- {policy}: {len(gone)} distinct lines")
        for g in sorted(gone, key=len, reverse=True)[:6]:
            print(f"   len={len(g):4d} {g.strip()[:88]!r}")


if __name__ == "__main__":
    main()
