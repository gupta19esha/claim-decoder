"""
Policy wording extraction, v2.

Changes from v1, all of them things that would have corrupted the corpus:

1. Page-accurate source_page. v1 stamped every clause in a chunk with the
   chunk's first page. Page citations are the product's credibility, so
   pages are now marked inline and returned per clause.
2. Column detection by gutter analysis rather than a word-crossing count.
   Also auto-detects the gutter position instead of assuming dead centre.
3. --dry-run. Runs the entire pipeline except the model call. Free. Use it
   to check column order before spending anything.
4. Verbatim check hardened: unicode punctuation normalised, line-break
   hyphenation repaired, and a contiguous-run fallback instead of v1's
   85 percent prefix probe which almost never fired.
5. Annexure tables: v1 took cells[-1] as the item name, which silently
   dropped the left half of every two-column item table. Now takes all
   item cells in the row.
6. Section detection scans the whole page and takes the earliest heading
   by position, not the first pattern in list order.

Usage:
    python extract_policy_v2.py input.pdf --insurer "Star Health" \
        --policy-name "Arogya Sanjeevani" --policy-id star_arogya_sanjeevani \
        --dry-run

    python extract_policy_v2.py input.pdf --insurer "Star Health" \
        --policy-name "Arogya Sanjeevani" --policy-id star_arogya_sanjeevani \
        --limit 3 --out clauses.jsonl
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone

import pdfplumber

# Gemini 2.5 Flash is closed to new API keys. The API itself points at
# gemini-3.6-flash as the replacement. 3.6 and later dropped the sampling
# parameters, so temperature must not be sent at all: passing it is an
# error, not a warning. Override with --model if you want to try 3.7.
MODEL = "gemini-3.6-flash"

# Per-request ceiling in milliseconds. A chunk that has not answered in two
# minutes is not going to.
REQUEST_TIMEOUT_MS = 120_000

PAGE_MARK = "[[page {n}]]"
PAGE_MARK_RE = re.compile(r"\[\[page (\d+)\]\]")

# Page furniture. Generic patterns first, insurer specific after.
FURNITURE_PATTERNS = [
    r"^\s*UIN\s*:",
    r"^\s*POLICY\s+WORDINGS?\s*$",
    r"^\s*\d+\s*/\s*\d+\s*$",
    r"^\s*Page\s+\d+\s+of\s+\d+\s*$",
    r"Registered\s+Office",
    r"Corporate\s+Office",
    r"Toll\s*free",
    r"^\s*CIN\s*[:.]",
    r"IRDA[I]?\s+Reg",
    r"^\s*Email\s*:.*Website\s*:",
    r"www\.[a-z]+\.com\s*$",
    r"INSURANCE\s+COMPANY\s+LIMITED",
    r"POL\s*/\s*\w+\s*/\s*V\.",
]

SECTION_MARKERS = [
    (r"\bPREAMBLE\b", "preamble"),
    (r"\bOPERATIVE\s+CLAUSE\b", "operative"),
    (r"\bSTANDARD\s+DEFINITIONS\b", "definition"),
    (r"\bSPECIFIC\s+DEFINITIONS\b", "definition"),
    (r"\bDEFINITIONS\b", "definition"),
    (r"\bCOVERAGE\b", "coverage"),
    (r"\bBENEFITS?\s+COVERED\b", "coverage"),
    (r"\bSTANDARD\s+EXCLUSIONS\b", "exclusion"),
    (r"\bSPECIFIC\s+EXCLUSIONS\b", "exclusion"),
    (r"\bEXCLUSIONS\b", "exclusion"),
    (r"\bWAITING\s+PERIODS?\b", "waiting_period"),
    (r"\bSTANDARD\s+CONDITIONS\b", "condition"),
    (r"\bSPECIFIC\s+CONDITIONS\b", "condition"),
    (r"\bGENERAL\s+CONDITIONS\b", "condition"),
    (r"\bCONDITIONS\b", "condition"),
    (r"\bTABLE\s+OF\s+BENEFITS\b", "benefits_table"),
    (r"\bANNEXURE\s*[-\u2013]?\s*A\b", "annexure"),
    (r"\bLIST\s+OF\s+INSURANCE\s+OMBUDSMAN\b", "ombudsman"),
    (r"\bGRIEVANCE\s+REDRESSAL\b", "ombudsman"),
]

EXTRACTION_PROMPT = """You are extracting structured clause records from an Indian health insurance policy wording document.

Return ONLY a JSON array. No markdown fences, no commentary. If the text contains no extractable clause, return [].

The input text contains page markers of the form [[page 12]]. These mark where a new page begins. They are NOT part of the policy text. Never include a page marker inside clause_text.

Each object in the array must have exactly these keys:

{{
  "clause_id": "the clause number or code exactly as printed, e.g. '5.1', 'Excl 01', '4.3'. Use null if genuinely unnumbered.",
  "clause_title": "the heading as printed, e.g. 'Pre-Existing Diseases', 'Cataract Treatment'",
  "clause_text": "the FULL text of the clause, copied character for character from the input, with page markers removed",
  "clause_type": "one of: exclusion, waiting_period, condition, definition, coverage, limit",
  "applies_to": ["list of treatments, conditions or expense categories this governs, lowercase, e.g. 'cataract', 'maternity', 'joint replacement'. Empty array if general."],
  "waiting_period_days": integer or null,
  "monetary_cap": integer or null,
  "cap_basis": "how the cap is expressed if there is one, e.g. 'per day', 'per eye per policy year', 'percent of sum insured'. Null if no cap.",
  "percent_cap": number or null,
  "conditions_required": ["conditions that must hold for this clause to bite, e.g. 'policy in force less than 36 months'"],
  "exclusion_code": "the IRDAI standard exclusion code if present, e.g. 'Excl 01'. Null otherwise.",
  "source_page": integer, the page number this clause starts on, taken from the nearest preceding page marker
}}

Hard rules:

1. clause_text must be VERBATIM. Never summarise, never rephrase, never clean up. Copy exactly, including awkward wording and spelling. This is the single most important rule. If you cannot copy it exactly, omit the record entirely.
2. Never invent a clause that is not in the input.
3. If a clause lists sub-items (like a list of diseases under a waiting period), keep them inside clause_text rather than splitting into separate records.
4. Convert months to days for waiting_period_days. 36 months becomes 1080. 24 months becomes 720. 30 days stays 30.
5. For monetary_cap, extract the rupee figure as a plain integer. "Rs.5000/-" becomes 5000. If the cap is only a percentage, leave monetary_cap null and fill percent_cap.
6. Where a clause has both a percentage and an absolute cap ("2% of Sum Insured subject to maximum of Rs.5000/- per day"), fill both percent_cap and monetary_cap, and describe the basis in cap_basis.
7. If the text reads as scrambled or sentences do not follow each other, return [] rather than guessing. Scrambled input means the page was parsed wrongly upstream.

The section this text came from is: {section}

Text:
---
{text}
---"""


# ---------------------------------------------------------------- text utils

def strip_furniture(text):
    out = []
    for line in text.split("\n"):
        if any(re.search(p, line, flags=re.IGNORECASE) for p in FURNITURE_PATTERNS):
            continue
        out.append(line)
    return "\n".join(out)


def normalise(s):
    """
    Fold the differences that make a true verbatim copy fail a string match.

    Order matters here and v9 had it wrong. Page markers were removed after
    de-hyphenation, so a word split across a page break, "any pre-" at the
    foot of page 10 and "existing disease" at the head of page 11, kept its
    hyphen and gained a space, while the model correctly wrote
    "pre-existing". That single character difference is what was still
    failing Excl 01 even once the header fragment was stripped. Markers go
    first, then hyphens are healed, then hyphenation is neutralised entirely
    so neither side can differ on it.
    """
    s = unicodedata.normalize("NFKC", s)
    s = PAGE_MARK_RE.sub("\n", s)                    # markers first
    s = s.replace("\u00ad", "")                      # soft hyphen
    s = re.sub(r"[\u2018\u2019\u02bc]", "'", s)      # curly single quotes
    s = re.sub(r"[\u201c\u201d]", '"', s)            # curly double quotes
    s = re.sub(r"[\u2010-\u2015]", "-", s)           # dashes
    s = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", s)   # hyphenation across lines
    s = re.sub(r"\s+", " ", s)
    # A hyphen between word characters carries no meaning for this
    # comparison and is the single most common place the two sides differ.
    s = re.sub(r"(?<=\w)\s*-\s*(?=\w)", "", s)
    return s.strip().lower()


# ------------------------------------------------------------ column handling

def find_gutter(page, band=0.16, margin=0.15):
    """
    Locate the vertical whitespace channel that separates two columns.

    Header and footer bands span the full page width and sit centred, so a
    scan over the whole page height never finds an empty channel. Restrict
    to the body region and ignore any word wider than a third of the page,
    which is always furniture rather than body text.
    """
    words = page.extract_words() or []
    if len(words) < 20:
        return None

    width, height = page.width, page.height
    top, bottom = height * margin, height * (1 - margin)
    max_word_w = width / 3.0

    body = [w for w in words
            if top < (w["top"] + w["bottom"]) / 2 < bottom
            and (w["x1"] - w["x0"]) < max_word_w]
    if len(body) < 15:
        return None

    lo, hi = width * (0.5 - band), width * (0.5 + band)
    bucket = 2.0
    n = max(1, int((hi - lo) / bucket))
    occupied = [False] * n
    for w in body:
        if w["x1"] < lo or w["x0"] > hi:
            continue
        a = max(0, int((w["x0"] - lo) / bucket))
        b = min(n - 1, int((w["x1"] - lo) / bucket))
        for i in range(a, b + 1):
            occupied[i] = True

    best_len, best_start = 0, None
    run_len, run_start = 0, None
    for i, occ in enumerate(occupied + [True]):
        if not occ:
            if run_start is None:
                run_start = i
            run_len += 1
        else:
            if run_len > best_len:
                best_len, best_start = run_len, run_start
            run_len, run_start = 0, None

    if best_start is None or best_len * bucket < 8:
        return None

    # Both sides must carry some real text. A short right column is normal
    # at the end of a section, so this is a floor rather than a ratio.
    centre = lo + (best_start + best_len / 2) * bucket
    left = sum(1 for w in body if w["x1"] <= centre)
    right = sum(1 for w in body if w["x0"] >= centre)
    if min(left, right) < 10:
        return None

    return centre / width


def page_text(page, forced_gutter=None):
    """Return (text, mode, gutter_ratio, segments).

    segments is the text of each column separately. Knowing where a column
    starts and ends is what lets furniture be matched at the edges only.
    """
    whole = page.extract_text() or ""
    ratio = forced_gutter if forced_gutter else find_gutter(page)

    if ratio is None:
        return whole, "single", None, [whole]

    split = page.width * ratio
    left = page.crop((0, 0, split, page.height)).extract_text() or ""
    right = page.crop((split, 0, page.width, page.height)).extract_text() or ""
    combined = (left + "\n" + right).strip()

    if len(combined) < len(whole) * 0.6:
        return whole, "single_fallback", ratio, [whole]
    return combined, "two_column", ratio, [left, right]


# Repetition is the signal for furniture. Length is not.
#
# v13 capped a furniture line at 100 characters. That silently discarded the
# longest footer line in three of the six policy documents: ICICI's
# 115-character address band survived on 103 of 111 pages, was spliced into
# 22 clauses and cut 10 of them off mid-sentence, including the definition of
# Pre-existing Disease. HDFC (106) and Tata (113) had the same hole.
#
# Measured across all six documents: every line repeating on 50 percent or
# more of pages is furniture — company names, registered addresses, UINs,
# product names, page markers. Not one is body text. So the ceiling is not
# what identifies furniture; repetition already does that.
#
# What the ceiling is for is over-deletion. Past some length a "line" is not a
# printed line at all but a mis-assembled block, and deleting it costs more
# than leaving it in. The longest single printed line in any of the six
# documents is 158 characters, so 250 leaves about 58 percent headroom over
# the worst real case while still refusing to delete a whole paragraph.
FURNITURE_MAX_LEN = 250


def learn_furniture(raw_pages, threshold=0.5):
    """
    Find the lines that repeat on most pages and drop them.

    Regex patterns alone cannot catch these. Cropping the columns cuts the
    full width header band in half, so Star's banner arrives as two
    fragments, "STAR HEALTH AND ALLIED INSURANCE CO" at the top of the left
    column and "OMPANY LIMITED | POLICY WORDINGS" in the middle of the page
    where the right column starts. No pattern written in advance would match
    those. Repetition across pages does, and it works for any insurer
    without hand tuning.
    """
    counts = {}
    n = len(raw_pages)
    for _, text in raw_pages:
        for line in set(_furniture_key(l) for l in text.split("\n") if l.strip()):
            if line:
                counts[line] = counts.get(line, 0) + 1
    return {k for k, c in counts.items()
            if c >= max(2, n * threshold) and len(k) <= FURNITURE_MAX_LEN}


def is_furniture(line, furniture, min_overlap=22):
    """
    Match furniture fragments that were cut at slightly different points.

    The gutter sits anywhere from 0.496 to 0.518 of the page width depending
    on the page, so the full width header band is sliced at a different
    character each time. Most pages yield "STAR HEALTH AND ALLIED INSURANCE
    CO", one yields "...COM", another "...CO LTD". Exact key matching
    stripped the common variants and left the odd ones sitting inside clause
    text. On this document that put a header fragment in the middle of
    Excl 01, Pre-Existing Diseases, which then failed the verbatim check and
    was dropped. Losing the most cited exclusion in Indian health insurance
    to a rounding difference in a column split is not acceptable, so match on
    a shared prefix instead of equality.
    """
    key = _furniture_key(line)
    if not key:
        return False
    if key in furniture:
        return True
    if len(key) > FURNITURE_MAX_LEN:
        return False
    for known in furniture:
        # A real clause line that merely starts with the insurer's name must
        # not be mistaken for a header, so the candidate has to be about the
        # same length as the known fragment, not merely start like it.
        if len(key) > len(known) + 32:
            continue
        overlap = os.path.commonprefix([key, known])
        if len(overlap) >= min_overlap and len(overlap) >= 0.6 * min(len(key), len(known)):
            return True
    return False


def _furniture_key(line):
    """Normalise away page numbers so footers with a page count still match."""
    return re.sub(r"[\d\W_]+", " ", line).strip().lower()


def _edge_keys(segments, n=2):
    """Keys of the first and last few lines of each column."""
    keys = set()
    for seg in segments:
        lines = [l for l in seg.split("\n") if l.strip()]
        for l in lines[:n] + lines[-n:]:
            k = _furniture_key(l)
            if k:
                keys.add(k)
    return keys


def read_pdf(path, forced_gutter=None):
    raw = []
    edges = []
    diagnostics = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text, mode, ratio, segments = page_text(page, forced_gutter)
            diagnostics.append({
                "page": i, "mode": mode,
                "gutter": round(ratio, 3) if ratio else None,
                "chars": len(text),
            })
            raw.append((i, text))
            edges.append(_edge_keys(segments))

    furniture = learn_furniture(raw)
    pages = []
    for (i, text), edge in zip(raw, edges):
        # Exact furniture matches are dropped wherever they appear. Fuzzy
        # prefix matches are only allowed at a column's first or last lines,
        # which is the only place a header or footer band can land. v9 applied
        # the fuzzy rule everywhere and ate seven real rows out of the
        # benefits table on pages 22 and 23.
        kept = []
        for l in text.split("\n"):
            k = _furniture_key(l)
            if k and k in furniture:
                continue
            if k and k in edge and is_furniture(l, furniture):
                continue
            kept.append(l)
        pages.append((i, strip_furniture("\n".join(kept))))
    return pages, diagnostics, furniture


# ------------------------------------------------------------------- chunking

def classify_section(text, current):
    """
    Find the first line on the page that is actually a heading.

    v2 searched the first 1200 characters as one blob, so a heading sitting
    below a paragraph was missed and the page kept the previous section.
    That is why a whole run of Star pages came back with no exclusion or
    definition section at all. Headings are short standalone lines, so test
    line by line and require the line to look like a heading rather than a
    sentence that happens to contain the word.
    """
    # Content signals first. Star prints its section headings only in a side
    # navigation strip, which the furniture stripper removes, so whole runs
    # of definition and exclusion pages carried no heading at all and
    # inherited "preamble" from four pages earlier. What a page contains is
    # more reliable than whether it happens to repeat its own heading.
    if len(re.findall(r"\bExcl\s*\d{2}\b", text)) >= 2:
        return "exclusion"
    if len(re.findall(r"(?m)^[A-Z][A-Za-z /\-]{2,40}:\s+\S.*?\bmeans\b", text)) >= 3:
        return "definition"
    if len(re.findall(r"(?i)waiting period of \w+", text)) >= 2:
        return "waiting_period"

    for raw in text.split("\n"):
        line = raw.strip()
        if not line or len(line) > 90:
            continue
        for pattern, label in SECTION_MARKERS:
            m = re.search(pattern, line, flags=re.IGNORECASE)
            if not m:
                continue
            # The heading must dominate the line, not be buried in prose.
            if len(m.group(0)) / len(line) > 0.35 or line.isupper():
                return label
    return current


def build_chunks(pages, max_chars=6000, overlap_chars=1500):
    """
    Group pages into chunks, carrying a tail across every length flush.

    A clause that spans a chunk boundary is invisible on both sides. The
    chunk holding its opening ends mid-sentence, the chunk holding the rest
    begins mid-sentence, and the extractor emits a truncated clause, a
    headless fragment, or nothing. ICICI's definition of Pre-existing Disease
    lost limb (b) exactly this way: limb (a) closed one chunk and limb (b)
    opened the next. Removing the page footer that was also spliced into it
    made the clause end cleanly and did not bring limb (b) back, because the
    two defects are unrelated.

    So a length flush carries the tail of the page it just closed into the
    next chunk. A clause that began anywhere in that tail is then whole in
    the second chunk. 1500 characters is the 95th percentile of clause length
    in the existing corpus, where the median is 321 and p90 is 996, so it
    covers all but the longest 5 percent of clauses while adding at most 1500
    characters to a 6000 character chunk.

    Section flushes do not carry. The carried text would be labelled with the
    section it is leaving, and a clause almost never spans a change of
    section.

    The overlap duplicates text deliberately, so the extractor sees some
    clauses twice. dedupe_records removes the copies afterwards.
    """
    chunks = []
    current_section = "unknown"
    buffer, buffer_pages = [], []

    def flush(section):
        if not buffer:
            return
        chunks.append({
            "section": section,
            "text": "\n".join(buffer).strip(),
            "start_page": buffer_pages[0],
            "end_page": buffer_pages[-1],
        })

    def carry_tail():
        """The trailing overlap_chars of the page just closed."""
        page_no = buffer_pages[-1]
        last = buffer[-1]
        body = last.split("\n", 1)[1] if "\n" in last else last
        if len(body) > overlap_chars:
            body = body[-overlap_chars:]
            # Start on a line boundary. Text opening mid-word cannot match
            # the source, so anything extracted from it would fail the
            # verbatim check and be discarded.
            nl = body.find("\n")
            if 0 <= nl < 200:
                body = body[nl + 1:]
        return [PAGE_MARK.format(n=page_no) + "\n" + body], [page_no]

    for page_no, text in pages:
        if not text.strip():
            continue

        new_section = classify_section(text, current_section)
        section_changed = new_section != current_section
        too_long = sum(len(b) for b in buffer) + len(text) > max_chars

        if (section_changed or too_long) and buffer:
            flush(current_section)
            if too_long and not section_changed and overlap_chars > 0:
                buffer, buffer_pages = carry_tail()
            else:
                buffer, buffer_pages = [], []

        current_section = new_section
        buffer.append(PAGE_MARK.format(n=page_no) + "\n" + text)
        buffer_pages.append(page_no)

    flush(current_section)
    return chunks


def _sentence_start_distance(text):
    """Characters from the end back to the start of the unfinished sentence."""
    for m in reversed(list(re.finditer(r"[.!?]\s", text))):
        return len(text) - m.end()
    return len(text)


def boundary_report(pages, max_chars=6000, overlap_chars=1500):
    """
    How many chunk boundaries fall inside a clause.

    This is the only check that sees the pipeline's worst failure mode. When
    a clause is split across two chunks the extractor does not usually emit
    both halves: it emits one truncated clause, or it drops the far half
    entirely. Nothing downstream catches either outcome. The verbatim check
    passes on a fragment, because the fragment really is in the source. And a
    clause that never reached the corpus leaves nothing to inspect at all.

    Measured across the six original policy documents, 78 of 127 length
    boundaries cut a clause mid-sentence, and only 11 of those 78 left any
    trace in the corpus. HDFC Optima Secure cut a clause at 23 of its 23
    length boundaries.

    Boundaries are counted on unoverlapped chunking, because that is where
    the cut happens. `recoverable` is how many of them the current overlap
    window pulls whole into the following chunk. Section flushes are excluded
    since they are not overlapped and a clause rarely spans a section.
    """
    plain = build_chunks(pages, max_chars, overlap_chars=0)
    bounds = cut = recoverable = 0
    unrecovered = []
    for a, b in zip(plain, plain[1:]):
        if a["section"] != b["section"]:
            continue
        bounds += 1
        body = re.sub(r"[ \t]+", " ", PAGE_MARK_RE.sub("", a["text"])).strip()
        if not body or body[-1] in ".!?":
            continue
        cut += 1
        back = _sentence_start_distance(body)
        if back <= overlap_chars:
            recoverable += 1
        else:
            unrecovered.append((a["end_page"], back, body[-70:]))
    return {"chunks": len(plain), "boundaries": bounds, "cut": cut,
            "recoverable": recoverable, "unrecovered": unrecovered}


def print_boundary_report(rep, overlap_chars):
    """Printed on every run, dry or not. Free, and nobody should extract a
    document without seeing it."""
    share = f" ({rep['cut'] / rep['boundaries']:.0%})" if rep["boundaries"] else ""
    print(f"  chunk boundaries: {rep['boundaries']}, "
          f"cutting a clause mid-sentence: {rep['cut']}{share}")
    if not rep["cut"]:
        return
    print(f"    recovered whole by the {overlap_chars} char overlap: "
          f"{rep['recoverable']}")
    if rep["unrecovered"]:
        print(f"    NOT recovered: {len(rep['unrecovered'])}. These clauses "
              f"will be truncated or lost.")
        for page, back, tail in rep["unrecovered"][:3]:
            print(f"      after page {page}: clause began {back} chars back "
                  f"| ...{tail.strip()[-46:]!r}")
        print(f"    Raise --overlap above {max(b for _, b, _ in rep['unrecovered'])} "
              f"to cover them, or accept the loss.")


def dedupe_records(records):
    """
    Remove the copies the chunk overlap creates. Returns (kept, dropped).

    Records are compared on normalised clause_text. An exact repeat goes, and
    so does a record whose text is wholly contained in another's, because
    that record is a fragment of the longer one. That second rule is what
    cleans up fragments left behind by the old non-overlapping chunking, not
    just the duplicates the new overlap introduces.

    Two guards. Containment only counts within one page of the container, so
    a short clause that happens to be quoted inside a longer one elsewhere in
    the document survives; the overlap only ever duplicates across adjacent
    pages. And the longer record is kept whole rather than merged with the
    shorter one's fields, because merging would let a number extracted from a
    partial clause ride along on the complete one.
    """
    order = {id(r): i for i, r in enumerate(records)}
    longest_first = sorted(
        records, key=lambda r: -len(normalise(r.get("clause_text") or "")))

    kept, dropped = [], []
    for rec in longest_first:
        text = normalise(rec.get("clause_text") or "")
        page = rec.get("source_page")
        if len(text) >= 25 and any(
                text in normalise(k.get("clause_text") or "")
                and isinstance(page, int)
                and isinstance(k.get("source_page"), int)
                and abs(page - k["source_page"]) <= 1
                for k in kept):
            dropped.append(rec)
            continue
        kept.append(rec)

    kept.sort(key=lambda r: order[id(r)])
    return kept, dropped


# ------------------------------------------------------------------- annexure

LIST_LABELS = {
    "LIST IV": ("subsume_treatment", "Must be subsumed into cost of treatment"),
    "LIST III": ("subsume_procedure", "Must be subsumed into procedure charges"),
    "LIST II": ("subsume_room", "Must be subsumed into room charges"),
    "LIST I": ("not_payable", "Never payable under the policy"),
}

LIST_HEAD_RE = re.compile(r"\bLIST\s+(IV|III|II|I)\b")

ITEM_LINE_RE = re.compile(
    r"(?:^|\s)(\d{1,3})[.):]?\s+"
    r"([A-Za-z][^\d\n]{2,70}?)"
    r"(?=\s+\d{1,3}[.):]?\s+[A-Za-z]|\s*$)"
)

HEADER_CELLS = {"ITEM", "ITEMS", "SL NO", "SL.NO", "SI NO", "SI.NO.", "S NO",
                "S.NO.", "SR NO", "SR.NO.", "NO", "PARTICULARS"}


def extract_annexure_lists(pages):
    """
    Parse the non-payable item lists.

    Two changes from v3, both found by running against the real Star
    document, which returned zero items.

    First, v3 gated on the word ANNEXURE appearing on the page. In the Star
    wording that word only ever appears inside prose, as "Annexure-A". The
    list pages themselves are headed "LIST II - Items that are to be
    subsumed into Room Charges" and nothing else, so the gate never opened
    and no page was ever examined. Triggering on the LIST headings instead
    removes the dependency on a word that may not be there.

    Second, v3 re-read the PDF with plain whole-page extraction, throwing
    away the column handling. These lists are two columns of items, so that
    pass read them interleaved. This now consumes the already column-ordered
    page text.
    """
    items = []
    current = None

    for page_no, text in pages:
        # Only stop at the ombudsman directory at the very end. The word
        # also appears in the grievance redressal clause much earlier, and
        # breaking there stops before the lists are ever reached.
        # Stop at the ombudsman directory. Guarding on current means the
        # earlier grievance redressal clause, which also says ombudsman,
        # cannot stop the walk before the lists are reached.
        if current is not None and "OMBUDSMAN" in text.upper():
            break

        lines = [l.rstrip() for l in text.split("\n")]

        # Some items wrap so that the serial sits alone on its own line
        # between the two halves of the item name. Rejoin those first.
        merged = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if (re.fullmatch(r"\s*\d{1,3}\s*", line) and merged
                    and i + 1 < len(lines)):
                serial = line.strip()
                merged[-1] = f"{serial} {merged[-1].strip()} {lines[i + 1].strip()}"
                i += 2
                continue
            merged.append(line)
            i += 1

        # Walk the page in reading order and switch list as headings appear.
        # A single page routinely carries the end of List II, all of List III
        # and the start of List IV, so one label per page is far too coarse.
        for line in merged:
            head = LIST_HEAD_RE.search(line.upper())
            if head:
                current = LIST_LABELS["LIST " + head.group(1)]
                continue
            if current is None:
                continue
            for mm in ITEM_LINE_RE.finditer(line):
                name = mm.group(2).strip(" .:-")
                if len(name) < 3 or name.upper().strip(".") in HEADER_CELLS:
                    continue
                items.append({
                    "item_name": re.sub(r"\s+", " ", name),
                    "category": current[0],
                    "category_description": current[1],
                    "source_page": page_no,
                })

    seen, unique = set(), []
    for it in items:
        key = (it["item_name"].upper(), it["category"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    return unique


# ---------------------------------------------------------------- model calls

_last_calls = []


def throttle(rpm):
    """
    Keep under the free tier ceiling.

    The free tier allows a handful of requests per minute per model. v5
    fired three retries back to back on failure, so a single failing chunk
    burned the whole minute's allowance and guaranteed the next two chunks
    failed too. Pace the calls instead.
    """
    if not rpm:
        return
    now = time.time()
    _last_calls[:] = [t for t in _last_calls if now - t < 60]
    if len(_last_calls) >= rpm:
        wait = 60 - (now - _last_calls[0]) + 1
        if wait > 0:
            print(f"  pacing, waiting {wait:.0f}s for quota")
            time.sleep(wait)
        now = time.time()
        _last_calls[:] = [t for t in _last_calls if now - t < 60]
    _last_calls.append(time.time())


def retry_delay_from(message, default):
    """Google tells us exactly how long to wait. Use it instead of guessing."""
    m = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+(?:\.\d+)?)s", message)
    if m:
        return float(m.group(1)) + 2
    m = re.search(r"retry in (\d+(?:\.\d+)?)s", message)
    if m:
        return float(m.group(1)) + 2
    return default


def call_gemini(client, types, chunk, model=MODEL, retries=5, rpm=4):
    """
    Returns the parsed records, or None if every attempt failed.

    None and [] must stay distinguishable. [] means the model read the chunk
    and found no clause in it, which is a normal outcome for a cover page. A
    failure that returns [] instead is a chunk silently dropped from the
    corpus: the run reports success, the clause count looks plausible, and
    the missing pages leave no trace. A DNS blip during one run cost two
    consecutive waiting_period chunks of Star Health that way.
    """
    prompt = EXTRACTION_PROMPT.format(section=chunk["section"], text=chunk["text"])
    for attempt in range(retries):
        throttle(rpm)
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            raw = response.text.strip()
            raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                parsed = [parsed]
            return parsed
        except json.JSONDecodeError:
            print(f"  bad JSON on attempt {attempt + 1}", file=sys.stderr)
            time.sleep(2 ** attempt)
        except Exception as exc:
            text = str(exc)
            if "RESOURCE_EXHAUSTED" in text or "429" in text:
                if "prepayment credits are depleted" in text:
                    print("  prepaid credits are at zero, falling back to the "
                          "free tier ceiling", file=sys.stderr)
                wait = retry_delay_from(text, 30)
                print(f"  rate limited, waiting {wait:.0f}s "
                      f"(attempt {attempt + 1})", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  error on attempt {attempt + 1}: {text[:200]}",
                      file=sys.stderr)
                # A name-resolution or connection failure is the network
                # being away, not the request being wrong. Backing off for
                # seconds loses the chunk; a transient outage outlasts that.
                offline = any(s in text for s in (
                    "NameResolutionError", "getaddrinfo", "Max retries",
                    "Server disconnected", "Connection aborted",
                    "Temporary failure in name resolution"))
                time.sleep(20 if offline else 2 ** attempt)
    return None


def longest_common_run(a, b):
    """Length of the longest contiguous substring of a that occurs in b.
    Binary search on length, cheap enough at clause size."""
    lo, hi, best = 0, len(a), 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if mid == 0:
            break
        found = any(a[i:i + mid] in b for i in range(0, len(a) - mid + 1))
        if found:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def verify_verbatim(clause, source_text, min_ratio=0.9):
    text = (clause.get("clause_text") or "").strip()
    if not text:
        return False, "empty"

    src = normalise(source_text)
    cand = normalise(text)

    if cand in src:
        return True, "exact"

    run = longest_common_run(cand, src)
    if run >= max(60, int(len(cand) * min_ratio)):
        return True, f"run {run}/{len(cand)}"
    return False, f"run {run}/{len(cand)}"


def resolve_page(clause, chunk):
    """Trust the model's page if it is inside the chunk, else fall back."""
    valid = [int(m) for m in PAGE_MARK_RE.findall(chunk["text"])]
    p = clause.get("source_page")
    if isinstance(p, int) and p in valid:
        return p
    # Locate the clause in the chunk and take the nearest preceding marker.
    probe = normalise(clause.get("clause_text", ""))[:80]
    if probe:
        marks = [(m.start(), int(m.group(1)))
                 for m in PAGE_MARK_RE.finditer(chunk["text"])]
        flat = normalise(chunk["text"])
        idx = flat.find(probe)
        if idx >= 0 and marks:
            frac = idx / max(1, len(flat))
            approx = int(frac * len(chunk["text"]))
            preceding = [pg for pos, pg in marks if pos <= approx]
            if preceding:
                return preceding[-1]
    return chunk["start_page"]


# ----------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--insurer", required=True)
    ap.add_argument("--policy-name", required=True)
    ap.add_argument("--policy-id", required=True)
    ap.add_argument("--out", default="clauses.jsonl")
    ap.add_argument("--items-out", default=None,
                    help="Defaults to <policy-id>_items.jsonl so runs do not "
                         "overwrite each other.")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--gutter", type=float, default=None,
                    help="Force the column split as a fraction of page width.")
    ap.add_argument("--overlap", type=int, default=1500,
                    help="Characters carried from one chunk into the next so "
                         "a clause spanning the boundary is whole in the "
                         "second. Default %(default)s, the 95th percentile of "
                         "clause length. 0 disables it.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse, chunk and dump. No model calls, no cost.")
    ap.add_argument("--dump", default="dryrun_chunks.txt")
    ap.add_argument("--items-only", action="store_true",
                    help="Write only the Annexure item lists. No model calls, "
                         "no cost. Use this to recover items when the clause "
                         "file is already good.")
    ap.add_argument("--vertex", action="store_true",
                    help="Call Gemini through Vertex AI so usage bills the "
                         "Google Cloud project and draws on Cloud credits.")
    ap.add_argument("--project", default=None,
                    help="Google Cloud project id, for --vertex.")
    ap.add_argument("--location", default="global",
                    help="Vertex region. Default %(default)s. Newer Gemini "
                         "models 404 on named regions, so 'global' is the "
                         "only value that reliably works.")
    ap.add_argument("--rpm", type=int, default=4,
                    help="Requests per minute ceiling. Free tier allows 5, "
                         "so 4 is safe. Use 0 to disable pacing if you have "
                         "paid credits.")
    ap.add_argument("--model", default=MODEL,
                    help="Gemini model id. Default %(default)s.")
    args = ap.parse_args()
    if not args.items_out:
        args.items_out = f"{args.policy_id}_items.jsonl"

    print(f"Reading {args.pdf}")
    pages, diags, furniture = read_pdf(args.pdf, args.gutter)
    print(f"  {len(pages)} pages")
    if furniture:
        print(f"  stripped {len(furniture)} repeated furniture lines:")
        for f in sorted(furniture)[:6]:
            print(f"    {f[:64]}")

    modes = {}
    for d in diags:
        modes[d["mode"]] = modes.get(d["mode"], 0) + 1
    print(f"  layout: {modes}")
    gutters = [d["gutter"] for d in diags if d["gutter"]]
    if gutters:
        print(f"  gutter ratio: min {min(gutters)} max {max(gutters)}")

    empty = [d["page"] for d in diags if d["chars"] < 50]
    if empty:
        print(f"  WARNING: {len(empty)} pages with almost no text: {empty[:15]}")
        print("  If most pages look like this the PDF is scanned. Discard it.")

    chunks = build_chunks(pages, overlap_chars=args.overlap)
    skip = {"ombudsman", "unknown"}
    kept = [c for c in chunks if c["section"] not in skip]
    print(f"  {len(chunks)} chunks, {len(kept)} after dropping {skip}")
    counts = {}
    for c in kept:
        counts[c["section"]] = counts.get(c["section"], 0) + 1
    print(f"  sections: {counts}")

    # Unconditional, before the dry-run and items-only branches, so it is
    # impossible to extract a document without seeing this number.
    boundary = boundary_report(pages, overlap_chars=args.overlap)
    print_boundary_report(boundary, args.overlap)

    if args.limit:
        kept = kept[:args.limit]

    if args.items_only:
        items = extract_annexure_lists(pages)
        for it in items:
            it.update({"insurer": args.insurer, "policy_id": args.policy_id})
        with open(args.items_out, "w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        by_cat = {}
        for it in items:
            by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
        print(f"Wrote {len(items)} items to {args.items_out} {by_cat}")
        return

    if args.dry_run:
        with open(args.dump, "w", encoding="utf-8") as f:
            for i, c in enumerate(kept, start=1):
                f.write(f"\n{'=' * 70}\n")
                f.write(f"CHUNK {i}  section={c['section']}  "
                        f"pages {c['start_page']}-{c['end_page']}  "
                        f"{len(c['text'])} chars\n")
                f.write(f"{'=' * 70}\n")
                f.write(c["text"] + "\n")
        print(f"\nDry run. Wrote {len(kept)} chunks to {args.dump}")
        print("Read the first three by eye. Sentences must run in order.")
        print("If they jump mid sentence, rerun with --gutter 0.48 or 0.52.")
        items = extract_annexure_lists(pages)
        by_cat = {}
        for it in items:
            by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
        print(f"Annexure items found: {len(items)} {by_cat}")
        for it in items[:8]:
            print(f"  {it['category']:20s} {it['item_name'][:60]}")
        return

    from google import genai
    from google.genai import types

    if args.vertex:
        # Vertex bills the Google Cloud project, so hackathon Cloud credits
        # apply. The AI Studio prepay wallet is a separate balance and Cloud
        # credits do not flow into it.
        project = args.project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            sys.exit("Pass --project YOUR_GCP_PROJECT_ID when using --vertex.")
        # An explicit timeout is load-bearing. Without one the client blocks
        # indefinitely on a network fault: a DNS outage mid-run left a socket
        # waiting for an answer that was never coming, and the process sat
        # there for three and a half hours. The retry loop in call_gemini
        # cannot help, because control never comes back to it.
        client = genai.Client(
            vertexai=True, project=project, location=args.location,
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))
        print(f"Using Vertex AI, project {project}, region {args.location}, "
              f"timeout {REQUEST_TIMEOUT_MS // 1000}s")
    else:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            sys.exit("Set GEMINI_API_KEY first, or use --vertex.")
        client = genai.Client(api_key=api_key)
    print(f"Using model {args.model}, paced at {args.rpm or 'unlimited'} req/min")
    if args.rpm:
        mins = len(kept) / args.rpm
        print(f"{len(kept)} chunks at this pace takes about {mins:.0f} minutes")

    records, rejected, failed = [], 0, []
    for i, chunk in enumerate(kept, start=1):
        print(f"[{i}/{len(kept)}] {chunk['section']} "
              f"(pages {chunk['start_page']}-{chunk['end_page']})")

        returned = call_gemini(client, types, chunk, args.model, rpm=args.rpm)
        if returned is None:
            failed.append((i, chunk))
            print(f"  CHUNK FAILED, every attempt errored. Pages "
                  f"{chunk['start_page']}-{chunk['end_page']} are not in "
                  f"this output.", file=sys.stderr)
            continue

        for clause in returned:
            ok, why = verify_verbatim(clause, chunk["text"])
            if not ok:
                rejected += 1
                print(f"  rejected, not verbatim ({why}): "
                      f"{clause.get('clause_title', 'untitled')}", file=sys.stderr)
                continue
            clause["source_page"] = resolve_page(clause, chunk)
            clause["clause_text"] = PAGE_MARK_RE.sub("", clause["clause_text"]).strip()
            clause.update({
                "insurer": args.insurer,
                "policy_name": args.policy_name,
                "policy_id": args.policy_id,
                "section": chunk["section"],
            })
            records.append(clause)

    extracted = len(records)
    records, duplicates = dedupe_records(records)
    if duplicates:
        print(f"\nDropped {len(duplicates)} of {extracted} records as copies "
              f"or fragments of a longer clause")
        for d in duplicates[:5]:
            print(f"    p{d.get('source_page')} "
                  f"{str(d.get('clause_title'))[:52]}")

    with open(args.out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(records)} clauses to {args.out}")
    if rejected:
        rate = rejected / max(1, rejected + len(records))
        print(f"Rejected {rejected} for failing the verbatim check "
              f"({rate:.0%}). Above 20 percent means tighten the prompt.")

    print("Extracting Annexure A item lists")
    items = extract_annexure_lists(pages)
    for it in items:
        it.update({"insurer": args.insurer, "policy_id": args.policy_id})
    with open(args.items_out, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    by_cat = {}
    for it in items:
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
    print(f"Wrote {len(items)} non-payable items to {args.items_out} {by_cat}")

    # A manifest of what this run knew and the output cannot show. Failed
    # chunks and boundary damage leave no trace in the .jsonl, so without
    # this the pre-load check has no way to see them.
    manifest_path = re.sub(r"\.jsonl$", "", args.out) + ".manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "policy_id": args.policy_id,
            "insurer": args.insurer,
            "policy_name": args.policy_name,
            "source_pdf": os.path.basename(args.pdf),
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "model": args.model,
            "overlap_chars": args.overlap,
            "pages": len(pages),
            # Pages actually sent to the model. Compared at gate time against
            # the pages that produced clauses: a long run that was sent and
            # came back empty is a whole section lost in silence.
            "pages_sent": sorted({p for c in kept
                                  for p in range(c["start_page"],
                                                 c["end_page"] + 1)}),
            "chunks_total": len(kept),
            "chunks_failed": [
                {"index": i, "section": c["section"],
                 "start_page": c["start_page"], "end_page": c["end_page"]}
                for i, c in failed],
            "verbatim_rejected": rejected,
            "verbatim_rejection_rate": (
                rejected / max(1, rejected + extracted)),
            "records_extracted": extracted,
            "records_deduped": len(duplicates),
            "records_written": len(records),
            "boundary": {
                "boundaries": boundary["boundaries"],
                "cut": boundary["cut"],
                "recoverable": boundary["recoverable"],
                "unrecovered": [
                    {"after_page": p, "chars_back": b, "tail": t.strip()[-70:]}
                    for p, b, t in boundary["unrecovered"]],
            },
        }, f, indent=2, ensure_ascii=False)
    print(f"Wrote run manifest to {manifest_path}")

    if failed:
        print(f"\n{'!' * 70}")
        print(f"INCOMPLETE: {len(failed)} of {len(kept)} chunks failed every "
              f"attempt and contributed nothing.")
        for i, c in failed:
            print(f"    chunk {i}: {c['section']} "
                  f"pages {c['start_page']}-{c['end_page']}")
        print("Those pages are absent from the output. Do not load this file;"
              " re-run the policy.")
        print("!" * 70)
        sys.exit(2)


if __name__ == "__main__":
    main()
