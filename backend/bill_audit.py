"""
Discharge bill auditing against the IRDAI non-payable item lists.

No model is involved anywhere in this file, on purpose. Matching a bill line
to a published list of item names is a lookup, not a judgement, and a lookup
that a person can re-run by hand is worth more here than one that is cleverer.
It also means there is no surface on which an item name could be invented: the
text returned to the user is the row from the corpus, unchanged.

The four IRDAI lists say different things and the difference matters to the
claimant:

  not_payable        never payable under any policy
  subsume_room       already inside the room charge, so billing it again is
                     double-charging
  subsume_procedure  already inside the procedure charge
  subsume_treatment  already inside the cost of treatment

Only the first is money the hospital should never have charged. The other
three are money that should already have been covered by a line the bill
already has, which is a different argument to make and is worded differently
in the output.
"""

import re

# Words that carry no distinguishing power. "CHARGES" appears in dozens of
# item names and in most bill lines; matching on it would flag everything.
STOPWORDS = {
    "CHARGES", "CHARGE", "EXPENSES", "EXPENSE", "COST", "COSTS", "FEE",
    "FEES", "AND", "OR", "THE", "OF", "FOR", "PER", "IN", "ON", "TO", "A",
    "AN", "WITH", "ANY", "ALL", "ITEM", "ITEMS", "MISC", "OTHER", "OTHERS",
    "USED", "DURING", "IF", "NOT", "NO",
    # Size and place modifiers. These are the dangerous ones. Several IRDAI
    # names are truncated or carry a modifier after a slash, so splitting
    # produces fragments like "ROOM" (from "EAU-DE-COLOGNE / ROOM") and
    # "SHORT" (from "KNEE BRACES (LONG/ SHORT/"). Left distinctive, "ROOM"
    # matches the room rent line itself and tells the claimant the hospital
    # should never have charged for their bed.
    "ROOM", "LONG", "SHORT", "SMALL", "LARGE", "MEDIUM", "EXTRA",
}

# An alternative with nothing distinctive falls back to whole-name matching,
# but only if the name is long enough to mean something on its own.
MIN_SUBSTRING_LEN = 8

AMOUNT_RE = re.compile(r"(?:(?:RS|INR|₹)\.?\s*)?(\d[\d,]*(?:\.\d{1,2})?)\s*$",
                       re.IGNORECASE)
TOKEN_RE = re.compile(r"[A-Z]+")


def normalise(text):
    return re.sub(r"\s+", " ", (text or "").upper()).strip()


def tokens(text):
    return [t for t in TOKEN_RE.findall(normalise(text)) if len(t) >= 2]


def distinctive(text):
    """Tokens that actually identify an item."""
    return [t for t in tokens(text) if t not in STOPWORDS and len(t) >= 3]


def _token_present(needle, haystack_tokens):
    """
    Present, allowing for plurals and simple inflection.

    Bills write "EYE PADS" where the list says "EYE PAD", and "GLOVES" where
    it says "GLOVE". Comparing on a common prefix handles both without
    dragging in a stemmer.
    """
    for t in haystack_tokens:
        if t == needle:
            return True
        # Three characters is enough to allow "PAD" to meet "PADS". The
        # length guard keeps it from reaching "CAPSULE" from "CAP".
        if len(needle) >= 3 and (t.startswith(needle) or needle.startswith(t)):
            if abs(len(t) - len(needle)) <= 2:
                return True
    return False


def prepare(items):
    """
    Index the IRDAI rows for matching.

    Item names carry alternatives separated by a slash, as in "ENTRANCE PASS /
    VISITORS PASS". Each alternative is matched independently, otherwise a
    bill that says only "VISITORS PASS" would never match.
    """
    prepared = []
    for item in items:
        name = item.get("item_name") or ""
        alternatives = []
        for part in re.split(r"\s*/\s*", name):
            part = part.strip(" ,.;:-")
            if not part:
                continue
            alternatives.append({
                "text": part,
                "distinctive": distinctive(part),
                "normalised": normalise(part),
            })
        if not alternatives:
            continue
        prepared.append({
            "item_name": name,
            "category": item.get("category"),
            "category_description": item.get("category_description"),
            "alternatives": alternatives,
        })
    return prepared


def parse_bill_lines(text):
    """
    Split a pasted bill into (description, amount) pairs.

    Deliberately forgiving. A hospital bill pasted out of a PDF loses its
    columns, so the only reliable structure is that the amount tends to be
    the last number on the line.
    """
    out = []
    for lineno, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line or len(line) < 3:
            continue
        amount = None
        match = AMOUNT_RE.search(line)
        description = line
        if match:
            try:
                amount = float(match.group(1).replace(",", ""))
            except ValueError:
                amount = None
            description = line[:match.start()].strip(" .:-\t|")
        # Strip a leading serial number: "12. GLOVES" or "12 GLOVES".
        description = re.sub(r"^\d{1,3}[.)]?\s+", "", description).strip()
        if not description or not distinctive(description):
            continue
        out.append({
            "line_no": lineno,
            "raw": line,
            "description": description,
            "amount": amount,
        })
    return out


def match_line(line, prepared):
    """
    Best matching IRDAI item for one bill line, or None.

    A match requires every distinctive token of the item to be present in the
    line. That is a deliberately strict rule: flagging a charge the hospital
    was entitled to make is worse than missing one, because the claimant takes
    it to a grievance officer and loses credibility.
    """
    line_tokens = tokens(line["description"])
    if not line_tokens:
        return None

    best = None
    for item in prepared:
        for alt in item["alternatives"]:
            needed = alt["distinctive"]
            if not needed:
                # Nothing distinctive to match on, so demand the whole name,
                # and only if it is long enough to be meaningful alone.
                if (len(alt["normalised"]) >= MIN_SUBSTRING_LEN
                        and alt["normalised"] in normalise(
                            line["description"])):
                    score = len(alt["normalised"])
                else:
                    continue
            elif all(_token_present(t, line_tokens) for t in needed):
                score = sum(len(t) for t in needed)
            else:
                continue

            if best is None or score > best["score"]:
                best = {
                    "score": score,
                    "item_name": item["item_name"],
                    "matched_alternative": alt["text"],
                    "category": item["category"],
                    "category_description": item["category_description"],
                }
    return best


def audit(bill_text, items):
    """Returns findings, totals and the lines that were read but not flagged."""
    prepared = prepare(items)
    lines = parse_bill_lines(bill_text)

    findings, clean = [], []
    for line in lines:
        hit = match_line(line, prepared)
        if hit:
            findings.append({
                "line_no": line["line_no"],
                "bill_line": line["raw"],
                "description": line["description"],
                "amount": line["amount"],
                # Straight from the corpus row. Never rewritten.
                "item_name": hit["item_name"],
                "matched_alternative": hit["matched_alternative"],
                "category": hit["category"],
                "category_description": hit["category_description"],
            })
        else:
            clean.append(line)

    by_category = {}
    for f in findings:
        slot = by_category.setdefault(
            f["category"], {"category": f["category"],
                            "category_description": f["category_description"],
                            "count": 0, "amount": 0.0, "amount_known": True})
        slot["count"] += 1
        if f["amount"] is None:
            slot["amount_known"] = False
        else:
            slot["amount"] += f["amount"]

    flagged_total = sum(f["amount"] for f in findings
                        if f["amount"] is not None)
    missing_amounts = sum(1 for f in findings if f["amount"] is None)

    return {
        "lines_read": len(lines),
        "lines_flagged": len(findings),
        "lines_not_flagged": len(clean),
        "findings": sorted(findings, key=lambda f: (
            f["category"] != "not_payable", -(f["amount"] or 0))),
        "by_category": sorted(by_category.values(),
                              key=lambda c: -c["amount"]),
        "flagged_total": round(flagged_total, 2),
        "findings_without_amount": missing_amounts,
    }
