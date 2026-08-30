"""
Chunk-boundary damage across every policy document at once.

The measurement itself lives in extract_policy_v13.boundary_report, which the
extractor prints on every run. This script is only the corpus-wide view: same
function, six documents, one table. Keeping the logic in the extractor means
the number a person sees before extracting and the number reported here
cannot drift apart.

Free. No model calls.

    python measure_chunk_boundaries.py
    python measure_chunk_boundaries.py --overlap 2500
"""

import argparse

from extract_policy_v13 import read_pdf, boundary_report

DOCS = [
    ("star_arogya_sanjeevani",
     "Policy_Arogya_Sanjeevani_Insurance_Policy_V_12_84d133b97f.pdf"),
    ("hdfc_optima_secure", "PolicyWordings_myOptimaSecure-76673175551.pdf"),
    ("icici_elevate", "elevate.pdf"),
    ("niva_reassure", "ReAssure-Policy-Wording.pdf"),
    ("niva_reassure_30", "ReAssure30_Policy_Wordings.pdf"),
    ("tata_medicare_select", "medicare_select_policy_wording_0faeeb61c5.pdf"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--overlap", type=int, default=1500)
    args = ap.parse_args()

    print(f"overlap window = {args.overlap} chars\n")
    print(f"{'policy':24s}{'chunks':>8s}{'bounds':>8s}{'cut':>7s}{'cut %':>7s}"
          f"{'recovered':>11s}{'lost':>6s}")
    print("-" * 71)

    totals = [0, 0, 0, 0, 0]
    deep = []
    for policy, path in DOCS:
        pages, _, _ = read_pdf(path)
        rep = boundary_report(pages, overlap_chars=args.overlap)
        lost = len(rep["unrecovered"])
        pct = f"{rep['cut'] / rep['boundaries']:.0%}" if rep["boundaries"] else "-"
        print(f"{policy:24s}{rep['chunks']:8d}{rep['boundaries']:8d}"
              f"{rep['cut']:7d}{pct:>7s}{rep['recoverable']:11d}{lost:6d}")
        totals = [t + v for t, v in zip(totals, [
            rep["chunks"], rep["boundaries"], rep["cut"],
            rep["recoverable"], lost])]
        deep += [(policy, *u) for u in rep["unrecovered"]]

    print("-" * 71)
    pct = f"{totals[2] / totals[1]:.0%}" if totals[1] else "-"
    print(f"{'TOTAL':24s}{totals[0]:8d}{totals[1]:8d}{totals[2]:7d}"
          f"{pct:>7s}{totals[3]:11d}{totals[4]:6d}")

    if deep:
        print(f"\nclauses beginning further back than {args.overlap} chars "
              f"({len(deep)}):")
        for policy, page, back, tail in deep:
            print(f"  {policy[:22]:22s} after p{page:<4} {back:5d} back  "
                  f"...{tail.strip()[-52:]!r}")


if __name__ == "__main__":
    main()
