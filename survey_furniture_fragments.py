"""
Survey: page furniture spliced into clause text, carrying no address or email.

The existing gate scores an email address or two postal-address signals. That
catches ICICI's footer, which is an address. It does not catch a masthead
fragment like

    ... 05. Tympanoplasty MPANY LIMITED | POLICY WORDINGS 06. Hysterectomy ...

which is live in the corpus and being quoted to users under "quoted word for
word". Nothing in it is an address, so nothing fired.

The shape that does distinguish it from legitimate prose:

  - a run of consecutive ALL-CAPS words sitting inside mixed-case text
  - a pipe, which mastheads use as a separator and policy prose does not
  - a masthead phrase in caps: COMPANY LIMITED, POLICY WORDINGS, UIN, IRDA

Case is the whole signal. Every policy in the corpus says "Policy means these
Policy wordings, the Policy Schedule..." in ordinary prose, and that must not
be flagged. "POLICY WORDINGS" in caps, mid-sentence, is a printed header.

Run before changing anything. Reports counts, not fixes.
"""

import json
import re
import sys
from collections import Counter, defaultdict

CORPUS = "clauses_v16_all.jsonl"

# Three or more consecutive all-caps words. Two is too common: policy text is
# full of "SUM INSURED" and "ICU CHARGES" used legitimately.
CAPS_RUN = re.compile(r"\b(?:[A-Z][A-Z&]{1,}\b[ ,/-]{1,3}){2,}[A-Z][A-Z&]{1,}\b")

MASTHEAD = re.compile(
    r"\b(?:COMPANY\s+LIMITED|POLICY\s+WORDINGS?|INSURANCE\s+CO\b|"
    r"UIN\s*[:.]|IRDA[I]?\s+REG|\bCIN\b|TOLL\s*FREE|REGISTERED\s+OFFICE)",
)

PIPE = re.compile(r"\|")

# Annexure and benefit-table clauses are legitimately full of capitals. They
# are still checked for the pipe and the masthead phrases, only the bare
# caps-run rule is relaxed.
TABLEISH = re.compile(r"(?:\b\d{2}\.\s){3,}|LIST\s+[IV]+\b", re.I)


def findings_for(rec):
    text = re.sub(r"\s+", " ", rec.get("clause_text") or "").strip()
    if not text:
        return []
    out = []

    if PIPE.search(text):
        m = PIPE.search(text)
        out.append(("pipe", text[max(0, m.start() - 60):m.start() + 40]))

    m = MASTHEAD.search(text)
    if m:
        out.append(("masthead_caps", text[max(0, m.start() - 60):m.end() + 30]))

    # Skip the first 40 characters: a clause may legitimately open on a
    # capitalised heading.
    body = text[40:]
    for m in CAPS_RUN.finditer(body):
        run = m.group(0)
        if len(run) < 12:
            continue
        if TABLEISH.search(text) and not MASTHEAD.search(run):
            continue
        out.append(("caps_run", body[max(0, m.start() - 50):m.end() + 30]))
        break

    return out


def main():
    recs = [json.loads(l) for l in open(CORPUS, encoding="utf-8") if l.strip()]
    per_policy = defaultdict(Counter)
    kinds = Counter()
    hits = []

    for rec in recs:
        found = findings_for(rec)
        if not found:
            continue
        hits.append((rec, found))
        for kind, _ in found:
            per_policy[rec["policy_id"]][kind] += 1
            kinds[kind] += 1

    print(f"{len(recs)} clauses surveyed")
    print(f"{len(hits)} clauses carry at least one furniture signal\n")

    print(f"{'policy':24s}{'pipe':>7s}{'masthead':>10s}{'caps_run':>10s}{'clauses':>9s}")
    print("-" * 60)
    for p in sorted(per_policy):
        c = per_policy[p]
        n = sum(1 for r, _ in hits if r["policy_id"] == p)
        print(f"{p:24s}{c['pipe']:>7d}{c['masthead_caps']:>10d}"
              f"{c['caps_run']:>10d}{n:>9d}")
    print("-" * 60)
    print(f"{'TOTAL':24s}{kinds['pipe']:>7d}{kinds['masthead_caps']:>10d}"
          f"{kinds['caps_run']:>10d}{len(hits):>9d}")

    print("\n" + "=" * 74)
    print("EVERY HIT, so each can be judged real or false")
    print("=" * 74)
    for rec, found in hits:
        print(f"\n{rec['policy_id']} p{rec.get('source_page')} "
              f"{str(rec.get('clause_title'))[:44]}")
        for kind, ctx in found:
            print(f"   [{kind}] ...{ctx.strip()}...")


if __name__ == "__main__":
    sys.exit(main())
