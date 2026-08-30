"""
Diff two extraction runs of the same policy.

Clauses have no stable identity across runs: the model may split or merge
them, and clause_id is null on a fifth of the corpus. So records are matched
on (source_page, normalised clause_title) and, failing that, on the opening
of the clause text. What is reported is what actually matters after a
pipeline change: how many clauses appeared, vanished, or had their text
altered, and whether any of them got longer because something that was
cutting them off has been removed.

    python compare_extractions.py before.jsonl after.jsonl
    python compare_extractions.py before.jsonl after.jsonl --probe "Pre-existing Disease"
"""

import argparse
import json
import re


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def body(rec):
    return re.sub(r"\s+", " ", (rec.get("clause_text") or "")).strip()


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def index(recs):
    by_key, by_open = {}, {}
    for r in recs:
        by_key.setdefault((r.get("source_page"), norm(r.get("clause_title"))),
                          []).append(r)
        by_open.setdefault(norm(body(r))[:70], []).append(r)
    return by_key, by_open


def match(recs_a, recs_b):
    """-> (pairs, only_a, only_b)"""
    _, b_open = index(recs_b)
    b_key, _ = index(recs_b)
    used, pairs, only_a = set(), [], []

    for r in recs_a:
        key = (r.get("source_page"), norm(r.get("clause_title")))
        cand = [c for c in b_key.get(key, []) if id(c) not in used]
        if not cand:
            cand = [c for c in b_open.get(norm(body(r))[:70], [])
                    if id(c) not in used]
        if cand:
            used.add(id(cand[0]))
            pairs.append((r, cand[0]))
        else:
            only_a.append(r)

    only_b = [r for r in recs_b if id(r) not in used]
    return pairs, only_a, only_b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--probe", action="append", default=[],
                    help="Clause title to print in full from both runs.")
    ap.add_argument("--pages", action="append", default=[],
                    help="Page or range, e.g. 18-19, printed in full from "
                         "both runs. Use when the thing you want to inspect "
                         "is a stretch of the document rather than a clause "
                         "you can name.")
    ap.add_argument("--show", type=int, default=8)
    args = ap.parse_args()

    a, b = load(args.before), load(args.after)
    pairs, only_a, only_b = match(a, b)

    same = [p for p in pairs if body(p[0]) == body(p[1])]
    changed = [p for p in pairs if body(p[0]) != body(p[1])]
    grew = [p for p in changed if len(body(p[1])) > len(body(p[0]))]
    shrank = [p for p in changed if len(body(p[1])) < len(body(p[0]))]

    print(f"before : {len(a)} clauses  ({args.before})")
    print(f"after  : {len(b)} clauses  ({args.after})")
    print()
    print(f"  matched            {len(pairs)}")
    print(f"    text identical   {len(same)}")
    print(f"    text changed     {len(changed)}")
    print(f"      longer         {len(grew)}")
    print(f"      shorter        {len(shrank)}")
    print(f"  only in before     {len(only_a)}")
    print(f"  only in after      {len(only_b)}")

    delta = sum(len(body(y)) - len(body(x)) for x, y in changed)
    print(f"\n  net characters of clause text: {delta:+d}")

    if changed:
        print("\n--- biggest text changes")
        for x, y in sorted(changed,
                           key=lambda p: -abs(len(body(p[1])) - len(body(p[0]))
                                              ))[:args.show]:
            d = len(body(y)) - len(body(x))
            print(f"  p{x.get('source_page'):<4}{d:+6d}  "
                  f"{str(x.get('clause_title'))[:48]}")

    for label, group in (("only in before", only_a), ("only in after", only_b)):
        if group:
            print(f"\n--- {label}")
            for r in group[:args.show]:
                print(f"  p{r.get('source_page'):<4}"
                      f"{str(r.get('clause_title'))[:52]}")
            if len(group) > args.show:
                print(f"  ... {len(group) - args.show} more")

    def show(label_text, pick):
        print("\n" + "=" * 76)
        print(f"PROBE: {label_text}")
        print("=" * 76)
        for label, recs in (("BEFORE", a), ("AFTER", b)):
            hit = [r for r in recs if pick(r)]
            chars = sum(len(body(r)) for r in hit)
            print(f"\n-- {label}: {len(hit)} clause(s), {chars} chars")
            for r in hit:
                print(f"   p{r.get('source_page')} "
                      f"[{r.get('clause_type')}] "
                      f"{str(r.get('clause_title'))[:54]!r} "
                      f"len={len(body(r))} wpd={r.get('waiting_period_days')} "
                      f"cap={r.get('monetary_cap')} pct={r.get('percent_cap')}")
                print(f"      {body(r)[:900]}")

    for probe in args.probe:
        show(probe, lambda r, p=probe: norm(p) in norm(r.get("clause_title")))

    for spec in args.pages:
        lo, _, hi = spec.partition("-")
        lo, hi = int(lo), int(hi or lo)
        show(f"pages {lo}-{hi}",
             lambda r, lo=lo, hi=hi: isinstance(r.get("source_page"), int)
             and lo <= r["source_page"] <= hi)


if __name__ == "__main__":
    main()
