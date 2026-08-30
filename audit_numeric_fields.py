"""
Numeric field audit.

The verbatim check in extract_policy_v13.py covers clause_text and nothing
else. waiting_period_days, monetary_cap and percent_cap are raw model output,
including the month-to-day arithmetic the extraction prompt asks for. Every
product built on dates or rupee figures reads those three fields.

This re-derives each of them from clause_text by deterministic parsing and
compares against what the model wrote.

WHAT AGREEMENT MEANS HERE

A value "agrees" if the number appears in the clause text under some
defensible reading. It does NOT mean the model picked the right number. A
clause listing several caps, or an exclusion carrying both a 24 month and a
48 month period, will agree on any of them. So the disagreement rate this
reports is a FLOOR on the true error rate, never a ceiling.

Verdicts:

  agree        model value is present in the text
  disagree     text carries numbers of this kind, model's is not among them
  unsupported  model gave a number, text carries no number of this kind
  missed       text carries a number, model gave null
  both_null    nothing to check

unsupported is the serious one: a figure with no basis in the source at all.
disagree is next. missed is a recall gap, invisible rather than wrong, but it
matters for anything that has to enumerate every waiting period in a policy.

Usage:
    python audit_numeric_fields.py *.jsonl
    python audit_numeric_fields.py --findings out.jsonl star_clauses.jsonl
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict

# --------------------------------------------------------------- number words

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000, "lakhs": 100000,
           "lac": 100000, "lacs": 100000, "crore": 10000000,
           "crores": 10000000}

_NUM_WORD = set(_ONES) | set(_TENS) | set(_SCALES) | {"and", "a"}


def words_to_int(tokens):
    """Parse a run of number words. Returns None if the run is not a number."""
    if not tokens or all(t in ("and", "a") for t in tokens):
        return None
    total, current, seen = 0, 0, False
    for t in tokens:
        if t in ("and",):
            continue
        if t == "a":
            current = current or 1
            seen = True
        elif t in _ONES:
            current += _ONES[t]
            seen = True
        elif t in _TENS:
            current += _TENS[t]
            seen = True
        elif t in _SCALES:
            scale = _SCALES[t]
            if scale >= 1000:
                total += (current or 1) * scale
                current = 0
            else:
                current = (current or 1) * scale
            seen = True
        else:
            return None
    return (total + current) if seen else None


def trailing_number_words(prefix, max_tokens=5):
    """Longest run of number words at the end of `prefix`."""
    tokens = re.findall(r"[a-z]+", prefix.lower())
    tokens = tokens[-max_tokens:]
    for start in range(len(tokens)):
        run = tokens[start:]
        if run and all(t in _NUM_WORD for t in run):
            val = words_to_int(run)
            if val is not None:
                return val
    return None


# ----------------------------------------------------------------- durations

_UNIT_RE = re.compile(r"\b(?P<unit>days?|months?|years?)\b", re.IGNORECASE)

# Words that sit between the number and the unit. "sixty continuous months"
# and "thirty-six (36) calendar months" are both ordinary policy phrasing, and
# a scan that insists the number touch the unit finds neither. Missing them
# made the moratorium clause, which every insurer words identically, look like
# a fabricated 1800.
_FILLER_RE = re.compile(
    r"(?:\s+(?:calendar|continuous|consecutive|completed|complete|full|"
    r"further|initial|successive|policy))+\s*$", re.IGNORECASE)

_PAREN_TAIL = re.compile(r"\(\s*(\d{1,4})\s*\)\s*[-‐-―]?\s*$")
# The trailing hyphen is what "30-day initial Waiting Period" needs.
_DIGIT_TAIL = re.compile(r"(\d{1,4})\s*[-‐-―]?\s*$")

# Whether the clause is about waiting periods at all. This is used only to
# decide whether a null is a genuine miss. It is deliberately NOT used to
# filter candidates when judging a value the model did produce: the question
# there is whether the number is derivable from the text, and narrowing the
# candidate set would manufacture disagreements. An earlier version windowed
# this to 160 characters and flagged a correct 720 because the phrase
# "waiting period" fell just outside the window that contained "24 months".
_WAIT_CONTEXT = re.compile(
    r"waiting\s+period|shall\s+not\s+be\s+(?:payable|admissible)|"
    r"not\s+be\s+covered|are\s+excluded|is\s+excluded|excluded\s+(?:until|for)|"
    r"after\s+(?:the\s+)?(?:expiry|completion)|continuous\s+coverage|"
    r"moratorium|survival\s+period|time\s*bound|"
    r"from\s+the\s+(?:date\s+of\s+)?(?:inception|commencement)",
    re.IGNORECASE,
)


def has_wait_context(text):
    return bool(_WAIT_CONTEXT.search(text or ""))


def find_durations(text):
    """Durations in the text, as (days, convention, raw)."""
    out = []
    for m in _UNIT_RE.finditer(text):
        unit = m.group("unit").lower().rstrip("s")
        prefix = _FILLER_RE.sub(" ", text[max(0, m.start() - 70):m.start()])

        pm = _PAREN_TAIL.search(prefix)
        dm = _DIGIT_TAIL.search(prefix)
        if pm:                      # "thirty-six (36) months", digits win
            n = int(pm.group(1))
        elif dm:
            n = int(dm.group(1))
        else:
            n = trailing_number_words(prefix)
        if n is None or n <= 0 or n > 2000:
            continue

        raw = re.sub(r"\s+", " ",
                     text[max(0, m.start() - 24):m.end()].strip())[-32:]
        if unit == "day":
            out.append((n, "days", raw))
        elif unit == "month":
            # The extraction prompt mandates months * 30. The other two are
            # what a model reaches for when it converts properly instead of
            # following the instruction, and the difference is real: 36
            # months is 1080 or 1095 depending on which it used, which is a
            # fortnight of error in any date the vault or tracker shows.
            out.append((n * 30, "months*30", raw))
            out.append((round(n * 365 / 12), "months*365/12", raw))
            out.append((round(n * 30.4375), "months*30.44", raw))
        else:
            out.append((n * 365, "years*365", raw))
            out.append((n * 360, "years*360", raw))
            out.append((n * 366, "years*366", raw))
    return out


# --------------------------------------------------------------------- money

_MONEY_RE = re.compile(
    r"(?:(?:Rs|INR|₹)\.?\s*|Rupees\s+)"
    r"(?P<num>[\d][\d,]*(?:\.\d+)?)"
    r"\s*(?P<scale>lakhs?|lacs?|crores?|thousand)?",
    re.IGNORECASE,
)

_MONEY_WORDS_RE = re.compile(
    r"(?:Rs|INR|₹)\.?\s*|Rupees\s+", re.IGNORECASE)

_BARE_MONEY_RE = re.compile(r"(?P<num>[\d][\d,]*)\s*/-")

# "1 lakh", "5 Lacs" with no Rs in front. Common in benefit tables where the
# currency sits in the column header rather than the cell.
_SCALED_RE = re.compile(
    r"(?P<num>[\d][\d,]*(?:\.\d+)?)\s*(?P<scale>lakhs?|lacs?|crores?)",
    re.IGNORECASE)

_SCALE_MULT = {"lakh": 100000, "lakhs": 100000, "lac": 100000,
               "lacs": 100000, "crore": 10000000, "crores": 10000000,
               "thousand": 1000}


def find_money(text):
    """Rupee figures in the text, as (value, raw)."""
    out = []
    for m in _MONEY_RE.finditer(text):
        try:
            num = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        scale = (m.group("scale") or "").lower()
        val = num * _SCALE_MULT.get(scale, 1)
        if val > 0:
            out.append((int(round(val)), m.group(0).strip()))

    for m in _BARE_MONEY_RE.finditer(text):
        try:
            val = int(m.group("num").replace(",", ""))
        except ValueError:
            continue
        if val > 0:
            out.append((val, m.group(0).strip()))

    for m in _SCALED_RE.finditer(text):
        try:
            num = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        val = num * _SCALE_MULT.get(m.group("scale").lower().rstrip("s"), 1)
        if val > 0:
            out.append((int(round(val)), m.group(0).strip()))

    # "Rupees Five Lakh only" — policy documents write amounts in words at
    # least as often as in digits.
    for m in _MONEY_WORDS_RE.finditer(text):
        tail = text[m.end():m.end() + 60].lower()
        tokens = re.findall(r"[a-z]+", tail)
        run = []
        for t in tokens:
            if t in _NUM_WORD:
                run.append(t)
            else:
                break
        if run:
            val = words_to_int(run)
            if val and val > 0:
                out.append((val, (m.group(0) + " " + " ".join(run)).strip()))
    return out


# ------------------------------------------------------------------- percent

_PCT_RE = re.compile(
    r"(?P<num>\d{1,3}(?:\.\d+)?)\s*(?:%|per\s*cent|percent)", re.IGNORECASE)
_PCT_WORD_RE = re.compile(r"(?:%|per\s*cent|percent)", re.IGNORECASE)


def find_percents(text):
    out = []
    for m in _PCT_RE.finditer(text):
        try:
            out.append((float(m.group("num")), m.group(0).strip()))
        except ValueError:
            continue
    for m in _PCT_WORD_RE.finditer(text):
        val = trailing_number_words(text[max(0, m.start() - 30):m.start()])
        if val is not None and 0 < val <= 100:
            out.append((float(val), text[max(0, m.start() - 20):m.end()].strip()))
    return out


# ------------------------------------------------------------------ compare

def as_number(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.replace(",", "").strip()
        s = re.sub(r"^(?:Rs|INR|₹)\.?\s*", "", s, flags=re.IGNORECASE)
        try:
            return float(s)
        except ValueError:
            return None
    return None


def appears_literally(value, text):
    """
    Is this exact figure printed in the text, however it is grouped?

    Last line of defence before calling something a fabrication. Indian
    documents group as 1,00,000 and Western tooling as 100,000, and a cap can
    appear in a table cell with no currency marker at all. Matching the digit
    string directly catches all of those. Generous by design: whatever
    survives this is a number with no basis in the source.
    """
    if value is None:
        return None
    if isinstance(value, float) and not value.is_integer():
        digits = f"{value:g}"
    else:
        digits = str(int(value))
    if len(digits) < 2:
        return None
    grouped = r"[,\s]?".join(digits)
    m = re.search(r"(?<![\d.])" + grouped + r"(?![\d])", text)
    return re.sub(r"\s+", " ", m.group(0)) if m else None


def judge(model_value, candidates, tolerance=1, text=None):
    """candidates is a list of (value, label, raw) tuples."""
    mv = as_number(model_value)
    has_candidates = bool(candidates)

    if mv is None:
        return ("missed" if has_candidates else "both_null"), None
    if mv == 0:
        return "zero", None
    for cand in candidates:
        if abs(cand[0] - mv) <= tolerance:
            return "agree", cand
    if text is not None:
        literal = appears_literally(mv, text)
        if literal:
            return "agree_literal", (mv, "printed in text", literal)
    return ("disagree" if has_candidates else "unsupported"), None


# --------------------------------------------------------------------- audit

FIELDS = ("waiting_period_days", "monetary_cap", "percent_cap")


def audit_record(rec):
    text = rec.get("clause_text") or ""
    result = {}

    durations = find_durations(text)
    verdict, hit = judge(rec.get("waiting_period_days"), durations)
    # A duration that exists in a clause with no waiting-period wording is not
    # a miss, it is correctly ignored. "Policy Year means a period of twelve
    # months" is a definition, and a null there is right.
    if verdict == "missed" and not has_wait_context(text):
        verdict = "both_null"
    result["waiting_period_days"] = {
        "verdict": verdict,
        "model": rec.get("waiting_period_days"),
        "convention": hit[1] if hit else None,
        "matched_text": hit[2] if hit else None,
        "candidates": sorted({(c[0], c[2]) for c in durations})[:6],
    }

    money = [(v, "rupees", raw) for v, raw in find_money(text)]
    verdict, hit = judge(rec.get("monetary_cap"), money, text=text)
    result["monetary_cap"] = {
        "verdict": verdict,
        "model": rec.get("monetary_cap"),
        "convention": hit[1] if hit else None,
        "matched_text": hit[2] if hit else None,
        "candidates": sorted({(c[0], c[2]) for c in money})[:6],
    }

    pcts = [(v, "percent", raw) for v, raw in find_percents(text)]
    verdict, hit = judge(rec.get("percent_cap"), pcts, tolerance=0.01)
    result["percent_cap"] = {
        "verdict": verdict,
        "model": rec.get("percent_cap"),
        "convention": None,
        "matched_text": hit[2] if hit else None,
        "candidates": sorted({(c[0], c[2]) for c in pcts})[:6],
    }
    return result


def load(paths):
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    print(f"  bad JSON at {path}:{lineno}", file=sys.stderr)
                    continue
                rec["_source_file"] = path
                rec["_lineno"] = lineno
                yield rec


BAD = ("disagree", "unsupported")
VERDICT_ORDER = ("agree", "agree_literal", "disagree", "unsupported",
                 "zero", "missed", "both_null")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--findings", default="numeric_audit_findings.jsonl")
    ap.add_argument("--show", type=int, default=6,
                    help="Examples to print per field per verdict.")
    args = ap.parse_args()

    records = list(load(args.files))
    print(f"{len(records)} clauses from {len(args.files)} files\n")

    tallies = {f: Counter() for f in FIELDS}
    conventions = {f: Counter() for f in FIELDS}
    by_policy = defaultdict(lambda: {f: Counter() for f in FIELDS})
    examples = {f: defaultdict(list) for f in FIELDS}
    findings = []

    for rec in records:
        res = audit_record(rec)
        policy = rec.get("policy_id") or rec.get("_source_file")
        flagged = {}
        for f in FIELDS:
            v = res[f]["verdict"]
            tallies[f][v] += 1
            by_policy[policy][f][v] += 1
            if res[f]["convention"]:
                conventions[f][res[f]["convention"]] += 1
            if v in BAD or v == "missed":
                examples[f][v].append((rec, res[f]))
            if v in BAD:
                flagged[f] = res[f]
        if flagged:
            findings.append({
                "policy_id": rec.get("policy_id"),
                "clause_id": rec.get("clause_id"),
                "clause_title": rec.get("clause_title"),
                "source_page": rec.get("source_page"),
                "source_file": rec["_source_file"],
                "line": rec["_lineno"],
                "fields": flagged,
                "clause_text": (rec.get("clause_text") or "")[:600],
            })

    n = len(records)
    print("=" * 74)
    print("PER FIELD")
    print("=" * 74)
    for f in FIELDS:
        t = tallies[f]
        populated = n - t["both_null"] - t["missed"]
        checked = populated - t["zero"]
        bad = sum(t[k] for k in BAD)
        print(f"\n{f}")
        print(f"  populated by the model   {populated:4d} of {n}")
        for k in VERDICT_ORDER:
            if t[k]:
                print(f"    {k:24s} {t[k]:4d}")
        if checked > 0:
            print(f"  DISAGREEMENT RATE        {bad}/{checked} = "
                  f"{bad / checked:.1%} of populated non-zero values")
        if conventions[f]:
            print(f"  conventions matched      {dict(conventions[f])}")

    print("\n" + "=" * 74)
    print("COVERAGE PER POLICY, clauses carrying a value for each field")
    print("=" * 74)
    print(f"{'policy':26s}{'clauses':>9s}" +
          "".join(f"{f.split('_')[0]:>22s}" for f in FIELDS))
    for policy in sorted(by_policy):
        n_pol = sum(1 for r in records
                    if (r.get("policy_id") or r["_source_file"]) == policy)
        row = f"{str(policy)[:26]:26s}{n_pol:9d}"
        for f in FIELDS:
            t = by_policy[policy][f]
            filled = sum(t.values()) - t["both_null"] - t["missed"]
            row += f"{f'{filled} ({filled / n_pol:.1%})':>22s}"
        print(row)
    row = f"{'TOTAL':26s}{n:9d}"
    for f in FIELDS:
        t = tallies[f]
        filled = n - t["both_null"] - t["missed"]
        row += f"{f'{filled} ({filled / n:.1%})':>22s}"
    print(row)

    print("\n" + "=" * 74)
    print("PER POLICY, share of populated values that disagree")
    print("=" * 74)
    header = f"{'policy':28s}" + "".join(f"{f.split('_')[0]:>14s}" for f in FIELDS)
    print(header)
    for policy in sorted(by_policy):
        row = f"{str(policy)[:28]:28s}"
        for f in FIELDS:
            t = by_policy[policy][f]
            checked = sum(t.values()) - t["both_null"] - t["missed"] - t["zero"]
            bad = sum(t[k] for k in BAD)
            row += f"{(f'{bad}/{checked}' if checked else '-'):>14s}"
        print(row)

    print("\n" + "=" * 74)
    print("EXAMPLES")
    print("=" * 74)
    for f in FIELDS:
        for v in ("unsupported", "disagree", "agree_literal", "missed"):
            items = examples[f][v][:args.show]
            if not items:
                continue
            print(f"\n--- {f} :: {v} ({len(examples[f][v])} total)")
            for rec, det in items:
                title = (rec.get("clause_title") or "untitled")[:44]
                print(f"  [{rec.get('policy_id')}] p{rec.get('source_page')} "
                      f"{title}")
                print(f"      model={det['model']!r}  "
                      f"text offers={det['candidates'][:4]}")

    with open(args.findings, "w", encoding="utf-8") as fh:
        for item in findings:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"\n{len(findings)} clauses flagged on at least one field "
          f"-> {args.findings}")


if __name__ == "__main__":
    main()
