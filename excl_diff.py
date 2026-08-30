"""
Cross-insurer diff of the IRDAI standard exclusions, Excl01 to Excl18.

These clauses are mandated by IRDAI and are near-identical across insurers.
That redundancy is the only detector we have for an OMISSION: text dropped
during extraction leaves nothing behind, so no single-document gate can see
it. HDFC's Excl01 sub-clause iii reads

    "as defined under the period for the same would be reduced"

where every other insurer's copy reads

    "as defined under the applicable norms on portability stipulated by
     IRDAI, then waiting period for the same would be reduced"

Nine words gone, and the clause still reads as a sentence.

Method. For each code the reference is the MEDOID — the copy most similar on
average to all the others — not the longest. The longest is an outlier trap:
ICICI's Excl01 runs 3908 characters against a 750-800 character norm because
it bundles adjacent material, and diffing everything against it buried the
64-character HDFC omission in noise. The medoid is the standard clause by
construction.

Every other copy is then diffed against the reference, and a span the
reference has but a policy lacks is reported only if at least one THIRD
policy also has it. That third witness separates a genuine omission from one
insurer simply wording their clause differently.

    python excl_diff.py                      # current corpus
    python excl_diff.py --corpus other.jsonl
    python excl_diff.py --before a.jsonl --after b.jsonl
"""

import argparse
import difflib
import json
import re
from collections import defaultdict

MIN_SPAN = 30          # characters; shorter differences are wording, not loss
CODE_RE = re.compile(r"ex[ce]l\s*\.?\s*-?\s*(\d{1,2})", re.IGNORECASE)


def norm(text):
    """Fold everything that is not the words themselves."""
    t = re.sub(r"\s+", " ", (text or "")).lower()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def code_of(rec):
    """The IRDAI code number, from the code field or the title."""
    for field in ("exclusion_code", "clause_title"):
        m = CODE_RE.search(str(rec.get(field) or ""))
        if m:
            n = int(m.group(1))
            if 1 <= n <= 18:
                return n
    return None


def collect(path):
    """code -> {policy_id: (text, page)}, keeping the longest copy per policy."""
    out = defaultdict(dict)
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        rec = json.loads(line)
        n = code_of(rec)
        if n is None:
            continue
        text = re.sub(r"\s+", " ", rec.get("clause_text") or "").strip()
        pid = rec["policy_id"]
        if pid not in out[n] or len(text) > len(out[n][pid][0]):
            out[n][pid] = (text, rec.get("source_page"))
    return out


def medoid(holders):
    """
    The copy most like all the others.

    Not the longest: one insurer bundling extra material into a clause makes
    it the longest and the worst possible reference, because every other copy
    then appears to be missing text that was never standard.
    """
    pids = list(holders)
    if len(pids) < 3:
        return max(pids, key=lambda p: len(holders[p][0]))
    best, best_score = pids[0], -1.0
    for p in pids:
        a = norm(holders[p][0])
        score = sum(
            difflib.SequenceMatcher(None, a, norm(holders[q][0]),
                                    autojunk=False).quick_ratio()
            for q in pids if q != p
        ) / (len(pids) - 1)
        if score > best_score:
            best, best_score = p, score
    return best


def missing_spans(reference, candidate):
    """Spans present in reference, absent from candidate."""
    a, b = norm(reference), norm(candidate)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    gaps = []
    for tag, i1, i2, _j1, _j2 in sm.get_opcodes():
        if tag in ("delete", "replace") and (i2 - i1) >= MIN_SPAN:
            gaps.append(a[i1:i2].strip())
    return gaps


def analyse(path, label):
    codes = collect(path)
    print(f"\n{'=' * 78}\n{label}: {path}\n{'=' * 78}")
    print(f"{'code':>6s}{'policies':>10s}{'shortest':>10s}{'longest':>9s}"
          f"{'spread':>8s}   omissions")
    print("-" * 78)

    findings = []
    for n in sorted(codes):
        holders = codes[n]
        lens = {p: len(t) for p, (t, _) in holders.items()}
        if not lens:
            continue
        shortest, longest = min(lens.values()), max(lens.values())
        ref_pid = medoid(holders)
        ref_text = holders[ref_pid][0]

        # No single reference. Each copy is diffed against every other, so a
        # defective copy cannot hide by being chosen as the yardstick — which
        # is exactly what happened to HDFC's Excl01 when the reference was
        # the medoid, and to the same clause when it was the longest.
        omissions = []
        if len(holders) >= 3:
            for pid, (text, page) in holders.items():
                gaps = []
                for qid, (qtext, _) in holders.items():
                    if qid == pid:
                        continue
                    for gap in missing_spans(qtext, text):
                        witnesses = sum(
                            1 for r, (rt, _) in holders.items()
                            if r != pid and gap[:60] in norm(rt))
                        # Two independent witnesses: one other insurer having
                        # the text could be their own drafting, two makes it
                        # the standard wording.
                        if witnesses >= 2:
                            gaps.append((gap, witnesses))
                # Keep the longest of any overlapping spans.
                gaps.sort(key=lambda g: -len(g[0]))
                kept = []
                for gap, w in gaps:
                    if not any(gap[:40] in k for k, _ in kept):
                        kept.append((gap, w))
                omissions.extend((pid, page, g, w) for g, w in kept)

        spread = f"{longest - shortest}"
        print(f"{n:>6d}{len(holders):>10d}{shortest:>10d}{longest:>9d}"
              f"{spread:>8s}   {len(omissions) or ''}")
        findings.extend((n, *o) for o in omissions)

    if not findings:
        print("\nNo omissions found: every copy carries every span that two or "
              "more other insurers share.")
        return findings

    print(f"\n{'=' * 78}\nOMISSIONS — text two or more insurers have and this "
          f"one does not\n{'=' * 78}")
    for n, pid, page, gap, witnesses in findings:
        print(f"\nExcl{n:02d}  {pid}  p{page}   "
              f"{len(gap)} chars, present in {witnesses} other copies")
        print(f"   missing: \"{gap[:180]}\"")
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="clauses_v16_all.jsonl")
    ap.add_argument("--before")
    ap.add_argument("--after")
    args = ap.parse_args()

    if args.before and args.after:
        b = analyse(args.before, "BEFORE")
        a = analyse(args.after, "AFTER")
        print(f"\n{'=' * 78}\nomissions before: {len(b)}   after: {len(a)}")
    else:
        analyse(args.corpus, "CORPUS")


if __name__ == "__main__":
    main()
