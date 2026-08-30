"""
Corpus-wide sweep for page furniture spliced into clause text.

Two shapes, both found by inspection rather than by any gate:

  page number splice   HDFC Excl01 page 30 reads "to the extent of Sum 30
                       Insured increase". A bare page number dropped between
                       two words of a defined term.

  masthead fragment    Star page 11 reads "05. Tympanoplasty MPANY LIMITED |
                       POLICY WORDINGS 06. Hysterectomy". A header sliced by
                       the column gutter, carrying no address or email, so
                       the contact-details gate scores nothing against it.

Both survive verify_verbatim, because the text really is in the assembled
page. Both are being quoted to users under "quoted word for word", and the
HDFC one has already gone out inside a drafted letter to a grievance officer.

Counts first. Fixes later.

    python sweep_contamination.py
"""

import json
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, ".")
from quality_gates import gate_masthead_fragment  # noqa: E402

CORPUS = "clauses_v16_all.jsonl"

# Words that make a following or preceding number ordinary rather than
# stray: amounts, durations, enumerations, references.
NUMERIC_CONTEXT = {
    "rs", "inr", "rupees", "day", "days", "month", "months", "year", "years",
    "hour", "hours", "week", "weeks", "percent", "per", "cent", "lakh",
    "lakhs", "lac", "lacs", "crore", "crores", "age", "aged", "upto", "up",
    "to", "of", "than", "least", "maximum", "minimum", "section", "clause",
    "code", "excl", "exel", "list", "annexure", "point", "points", "times",
    "sum", "insured", "no", "number", "sl", "sr", "item", "aged", "within",
    "after", "before", "period", "plan", "option", "type", "level", "band",
    "and", "or", "the", "a", "an", "is", "are", "was", "were", "shall",
    # Ordinal fragments and counting words. "as on 1 st day" is the scanner
    # splitting "1st", not a splice, and "exceeds 48 consecutive hours" is a
    # duration.
    "consecutive", "st", "nd", "rd", "th", "first", "second", "third",
    "pre", "next", "last", "only", "such", "these", "any", "all", "each",
}

# A number wedged between two alphabetic words.
WEDGED = re.compile(r"(?<![\w/.-])(\d{1,3})(?![\w/.%-])")


def stray_numbers(rec):
    """
    Bare numbers sitting between two words with no numeric context.

    A page number is the common case, so a match on the clause's own
    source_page is reported separately and is close to certain.
    """
    text = re.sub(r"\s+", " ", rec.get("clause_text") or "")
    page = rec.get("source_page")
    out = []

    for m in WEDGED.finditer(text):
        n = int(m.group(1))
        before = text[:m.start()].rstrip()
        after = text[m.end():].lstrip()
        # Must sit between two alphabetic words.
        bw = re.search(r"([A-Za-z]+)\W*$", before)
        aw = re.match(r"([A-Za-z]+)", after)
        if not bw or not aw:
            continue
        b, a = bw.group(1).lower(), aw.group(1).lower()
        if b in NUMERIC_CONTEXT or a in NUMERIC_CONTEXT:
            continue
        # A number that opens a list item, "01. Benign ENT disorders", is
        # enumeration, not a splice. Those are caught by the punctuation
        # after the digits, which WEDGED already excludes, but a bare
        # enumerator with no dot can still slip through.
        if re.match(r"^[A-Z]", aw.group(1)) and b.endswith("."):
            continue
        ctx = text[max(0, m.start() - 55):m.end() + 45]
        out.append({
            "n": n,
            # The marker sits at the page break, so a clause that began on
            # the previous page carries the NEXT page's number. Both
            # neighbours count.
            "is_source_page": isinstance(page, int) and n in (page - 1, page,
                                                              page + 1),
            "context": ctx.strip(),
        })
    return out


def main():
    recs = [json.loads(l) for l in open(CORPUS, encoding="utf-8") if l.strip()]

    page_hits, stray_hits, masthead_hits, listy = [], [], [], []
    for rec in recs:
        # Runs for every clause. The list-density skip below applies only to
        # stray numbers; a masthead fragment can sit inside an enumerated
        # list and Star's does exactly that, between items 05 and 06.
        masthead = gate_masthead_fragment(rec)
        if masthead:
            masthead_hits.append((rec, masthead))

        found = stray_numbers(rec)
        # A clause carrying three or more bare numbers is an enumerated list
        # — HDFC's critical-illness table reads "HIV 19 Medullary Cystic
        # Disease 45 Terminal Illness 20" — and none of them is a splice.
        if len(found) >= 3:
            listy.append((rec, found))
            continue
        for s in found:
            (page_hits if s["is_source_page"] else stray_hits).append((rec, s))

    def per_policy(hits):
        c = Counter()
        for rec, _ in hits:
            c[rec["policy_id"]] += 1
        return c

    pp, sp, mp = (per_policy(page_hits), per_policy(stray_hits),
                  per_policy(masthead_hits))
    policies = sorted({r["policy_id"] for r in recs})

    print(f"{len(recs)} clauses swept\n")
    print(f"{'policy':24s}{'page-number splice':>20s}{'other stray no.':>17s}"
          f"{'masthead frag':>15s}")
    print("-" * 76)
    for p in policies:
        print(f"{p:24s}{pp[p]:>20d}{sp[p]:>17d}{mp[p]:>15d}")
    print("-" * 76)
    print(f"{'TOTAL':24s}{sum(pp.values()):>20d}{sum(sp.values()):>17d}"
          f"{sum(mp.values()):>15d}")
    print(f"\n{len(listy)} clauses skipped as enumerated lists "
          f"(3+ bare numbers, none of them a splice)")

    def show(title, hits, limit=None):
        print("\n" + "=" * 76)
        print(f"{title} ({len(hits)})")
        print("=" * 76)
        for rec, s in hits[:limit] if limit else hits:
            page = rec.get("source_page")
            print(f"\n{rec['policy_id']} p{page} "
                  f"{str(rec.get('clause_title'))[:44]}")
            ctx = s["context"] if isinstance(s, dict) else s[1]
            print(f"   ...{ctx}...")

    show("PAGE-NUMBER SPLICES — the number equals the clause's own page",
         page_hits)
    show("MASTHEAD FRAGMENTS", masthead_hits)
    show("OTHER STRAY NUMBERS — judge each", stray_hits, limit=25)


if __name__ == "__main__":
    main()
