"""
Corpus quality gates.

Automated checks that a freshly extracted policy is fit to serve, so a human
does not have to read dryrun_chunks.txt and decide. Each gate returns a list
of failures; a non-empty list means the file should not be loaded.

Two gates so far, both from a real corpus defect. ICICI Elevate's page footer
survived furniture stripping on 103 of 111 pages, was spliced into 22 clauses
and cut 10 of them off mid-sentence, including the definition of Pre-existing
Disease, which lost limb (b) entirely. Nothing caught it: the verbatim check
passed, because the address genuinely was in the assembled page text. That is
the shape of the hole these gates close — verify_verbatim proves a clause came
from the extracted page, not that the extracted page resembles the printed one.

    python quality_gates.py star_clauses.jsonl ...
    python quality_gates.py --verbose *.jsonl

Exit code is 1 if any gate fails, so this can sit in front of a bq load.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict

# --------------------------------------------------------------- gate: text
# ends mid-sentence

# Words that cannot end a complete clause. A clause finishing on one of these
# has been cut, whatever the reason. "...prior to the date of commencement of
# the policy issued by us; or" is the ICICI PED definition losing limb (b).
DANGLING = {
    "a", "an", "and", "any", "are", "as", "at", "be", "because", "been",
    "being", "but", "by", "can", "for", "from", "had", "has", "have", "her",
    "his", "if", "in", "into", "is", "its", "may", "must", "no", "nor", "not",
    "of", "on", "onto", "or", "our", "over", "per", "shall", "such", "than",
    "that", "the", "their", "these", "this", "those", "to", "under", "unless",
    "until", "upon", "was", "were", "when", "where", "which", "while", "who",
    "whom", "whose", "will", "with", "your",
}

TERMINAL = ".!?"

URL_TAIL_RE = re.compile(
    r"(?:https?://|www\.)\S+$|[\w-]+(?:\.[\w-]+)*\.(?:in|com|org|net|gov|co)$",
    re.I)


def gate_truncated(rec):
    text = re.sub(r"\s+", " ", (rec.get("clause_text") or "")).strip()
    if not text:
        return ("empty", "clause_text is empty")

    last = text[-1]
    if last in TERMINAL:
        return None
    # A trailing comma or an unclosed hyphen is a cut, never a style.
    if last in ",-–—":
        return ("truncated", f"ends on {last!r}: ...{text[-60:]}")
    if last.isalpha():
        # A clause may legitimately end on a bare URL, and a domain suffix
        # looks exactly like a dangling preposition: the grievance clauses
        # end "...bimabharosa.irdai.gov.in", whose last word is "in".
        if URL_TAIL_RE.search(text):
            return ("no_terminal_punctuation", f"...{text[-60:]}")
        # Case matters. A capitalised final letter or word is a label or a
        # proper noun, not a dangling function word: the vaccination table
        # ends "13 Hepatitis A", which is complete.
        word = re.findall(r"[A-Za-z]+", text)[-1]
        if word.islower() and word in DANGLING:
            return ("truncated", f"ends on dangling {word!r}: ...{text[-60:]}")
        # A lone lowercase letter is a word cut off, not a word. HDFC's
        # non-disclosure clause ends "...continue with the Policy o", which
        # is "option c" losing everything after the o.
        if word.islower() and len(word) == 1:
            return ("truncated",
                    f"ends on a single letter {word!r}: ...{text[-60:]}")
        # No terminal punctuation but a content word. Common and usually
        # legitimate: headings, table rows, list items. Reported, not failed.
        return ("no_terminal_punctuation", f"...{text[-60:]}")

    if last.isdigit():
        # A trailing number is normal for a table row, but not when the word
        # introducing it is a preposition. HDFC's PED modification clause
        # ends "...from 36 months to 12", losing "months (1 year)" and with
        # it the second of the two options it exists to describe.
        tokens = text.split()
        if len(tokens) >= 2:
            prev = re.sub(r"[^A-Za-z]", "", tokens[-2]).lower()
            if prev in DANGLING:
                return ("truncated",
                        f"ends on {prev!r} + number: ...{text[-60:]}")
        return ("no_terminal_punctuation", f"...{text[-60:]}")
    return None


# ------------------------------------------------- gate: embedded page furniture

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

# A postal address is scored rather than pattern-matched, because no single
# token is decisive. "Road" appears in hospital names, a six-digit number
# appears in sums insured. Two independent signals together do not.
ADDRESS_SIGNALS = (
    ("office", re.compile(r"Registered\s+Office|Corporate\s+Office|"
                          r"Mailing\s+Address", re.I)),
    ("street", re.compile(r"\b(?:Road|Marg|Street|Lane|Nagar|Chowk|"
                          r"Business\s+Park|Industrial\s+Estate)\b")),
    ("unit", re.compile(r"\b(?:\d+(?:st|nd|rd|th)\s+Floor|Tower\s+[A-Z]\b|"
                        r"Plot\s+No|Survey\s+No)")),
    ("pin", re.compile(r"\b[1-9]\d{5}\b")),
)

# Clauses that are legitimately about how to reach the insurer. These really
# do carry an address and an email and must not be flagged.
CONTACT_EXEMPT = re.compile(
    r"grievance|redressal|ombudsman|complaint|\bnotices?\b|"
    r"customer\s+(?:care|service|support)|contact\s+"
    r"(?:us|details)|excluded\s+(?:hospitals?|providers?)|"
    r"how\s+to\s+(?:claim|contact)",
    re.I,
)


def is_contact_clause(rec):
    haystack = " ".join(str(rec.get(f) or "")
                        for f in ("clause_title", "section", "clause_type"))
    if CONTACT_EXEMPT.search(haystack):
        return True
    # Some contact clauses are untitled, so allow the opening of the body to
    # establish it. Only the opening: an address buried on line 40 of an
    # exclusion is exactly what this gate is for.
    return bool(CONTACT_EXEMPT.search((rec.get("clause_text") or "")[:220]))


def gate_contact_details(rec):
    text = rec.get("clause_text") or ""
    if not text:
        return None

    email = EMAIL_RE.search(text)
    hits = [name for name, pat in ADDRESS_SIGNALS if pat.search(text)]
    has_address = len(hits) >= 2

    if not email and not has_address:
        return None
    if is_contact_clause(rec):
        return None

    what = []
    if email:
        what.append(f"email {email.group(0)!r}")
    if has_address:
        what.append("postal address (" + ", ".join(hits) + ")")
    return ("embedded_contact_details", "; ".join(what))


# ----------------------------------------------------- gate: text begins
# mid-sentence, i.e. the clause is the far side of a split

# Leading enumeration, which is not a sentence start: "i.", "a)", "(iv)", "3.".
LIST_MARKER_RE = re.compile(
    r"^\s*(?:[\(\[]?(?:[ivxlcdm]{1,4}|[a-z]|\d{1,2})[.)\]]\s+)+", re.I)

# Enumeration is not always punctuated. Niva 3.0 sets its sub-clauses as
# "a If the Insured Person suffers...", where the label is a bare letter. The
# following capital is what distinguishes it from a fragment beginning with
# an article: "a Hospital shall" would be a cut, "a If" is a list item. The
# rule is narrow on purpose — one clause in 965 needs it.
BARE_LABEL_RE = re.compile(r"^\s*[a-z]\s+(?=[A-Z])")

OPENING_JUNK = " \t\n\"'“”‘’•▪-–—*"


def starts_mid_sentence(text):
    """
    True when the clause opens partway through a sentence.

    Lowercase alone is not the test. 140 clauses in the corpus start
    lowercase and almost all are list items ("i. Room Rent") or the
    scanner reading a capital I as a lowercase L ("lf any claim", "ln case
    of"). Enumeration is stripped first and the L-for-I artifact is
    excused, so what is left is a genuine continuation.
    """
    t = (text or "").lstrip(OPENING_JUNK)
    t = BARE_LABEL_RE.sub("", LIST_MARKER_RE.sub("", t))
    # Hyphens are part of the token. Stopping at one turns "e-Counseling"
    # into a lowercase "e" and flags a heading as a mid-sentence start;
    # taken whole, its capital C means islower() rejects it for us.
    m = re.match(r"([A-Za-z][A-Za-z-]*)", t)
    if not m:
        return False
    word = m.group(1)
    if not word.islower():
        return False
    if word[0] == "l" and len(word) <= 3:      # lf / ln / lt, really If/In/It
        return False
    return True


def gate_starts_mid_sentence(rec):
    text = re.sub(r"\s+", " ", (rec.get("clause_text") or "")).strip()
    if not text:
        return None
    # A definition whose body opens "means ..." is not a fragment. The term
    # being defined is the heading, which is how policy wordings are set:
    # "You, Your, Insured Person" / "means the person whose name appears in
    # the Policy Schedule". Only counts when there is a title to carry it.
    if rec.get("clause_title") and re.match(r"means\b", text):
        return None
    if starts_mid_sentence(text):
        return ("starts_mid_sentence", f"{text[:70]}...")
    return None


def gate_continues_previous(recs):
    """
    Sequence gate: a clause cut in half at a chunk boundary.

    The signature is a pair. The clause before ends on a dangling word, the
    clause after opens mid-sentence, and they sit on the same page or on
    consecutive ones. Neither half looks wrong on its own, which is why
    nothing has caught this.
    """
    findings = []
    for prev, cur in zip(recs, recs[1:]):
        pp, cp = prev.get("source_page"), cur.get("source_page")
        if not (isinstance(pp, int) and isinstance(cp, int)):
            continue
        if not 0 <= cp - pp <= 1:
            continue
        before = gate_truncated(prev)
        if not before or before[0] != "truncated":
            continue
        cur_text = re.sub(r"\s+", " ", (cur.get("clause_text") or "")).strip()
        if not starts_mid_sentence(cur_text):
            continue
        prev_text = re.sub(r"\s+", " ",
                           (prev.get("clause_text") or "")).strip()
        findings.append((
            "continues_previous", cur,
            f"p{pp} ends '...{prev_text[-40:]}' then p{cp} opens "
            f"'{cur_text[:40]}...'"))
    return findings


GATES = (gate_truncated, gate_contact_details, gate_starts_mid_sentence)
SEQUENCE_GATES = (gate_continues_previous,)

# Findings that block a load. no_terminal_punctuation is reported but does not
# fail: 18 percent of the corpus ends without a full stop and almost all of it
# is headings and table rows.
BLOCKING = {"truncated", "empty", "embedded_contact_details",
            "starts_mid_sentence", "continues_previous"}


# ------------------------------------------------------------------- runner

def check(recs):
    findings = []
    for rec in recs:
        for gate in GATES:
            result = gate(rec)
            if result:
                kind, detail = result
                findings.append((kind, rec, detail))
    # Sequence gates need document order, so run them per policy over the
    # records as they were extracted.
    by_policy = defaultdict(list)
    for rec in recs:
        by_policy[rec.get("policy_id")].append(rec)
    for group in by_policy.values():
        for gate in SEQUENCE_GATES:
            findings.extend(gate(group))
    return findings


def load(paths):
    for path in paths:
        for lineno, line in enumerate(open(path, encoding="utf-8"), start=1):
            if line.strip():
                rec = json.loads(line)
                rec.setdefault("policy_id", path)
                rec["_line"] = lineno
                yield rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--verbose", action="store_true",
                    help="Print every finding, not just a sample.")
    ap.add_argument("--show", type=int, default=6)
    args = ap.parse_args()

    recs = list(load(args.files))
    findings = check(recs)

    per_policy = defaultdict(Counter)
    totals = Counter()
    for kind, rec, _ in findings:
        per_policy[rec.get("policy_id")][kind] += 1
        totals[kind] += 1
    counts = Counter(r.get("policy_id") for r in recs)

    kinds = ["truncated", "starts_mid_sentence", "continues_previous",
             "embedded_contact_details", "empty", "no_terminal_punctuation"]
    print(f"{'policy':26s}{'clauses':>9s}" + "".join(f"{k[:17]:>19s}"
                                                     for k in kinds))
    print("-" * (35 + 19 * len(kinds)))
    for policy in sorted(counts):
        row = f"{str(policy)[:26]:26s}{counts[policy]:9d}"
        for k in kinds:
            row += f"{per_policy[policy][k]:>19d}"
        print(row)
    print("-" * (35 + 19 * len(kinds)))
    row = f"{'TOTAL':26s}{len(recs):9d}"
    for k in kinds:
        row += f"{totals[k]:>19d}"
    print(row)

    blocking = [f for f in findings if f[0] in BLOCKING]
    print(f"\nblocking findings: {len(blocking)}")

    shown = defaultdict(int)
    for kind, rec, detail in findings:
        if kind not in BLOCKING:
            continue
        shown[kind] += 1
        if not args.verbose and shown[kind] > args.show:
            continue
        print(f"  [{kind}] {rec.get('policy_id')} p{rec.get('source_page')} "
              f"{str(rec.get('clause_title'))[:40]}")
        print(f"      {detail}")
    if not args.verbose:
        for kind, n in shown.items():
            if n > args.show:
                print(f"  ... {n - args.show} more {kind}")

    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
