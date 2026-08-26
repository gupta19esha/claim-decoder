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

import pdfplumber

MODEL = "gemini-2.5-flash"

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
    """Fold the differences that make a true verbatim copy fail a string match."""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00ad", "")                       # soft hyphen
    s = re.sub(r"[\u2018\u2019\u02bc]", "'", s)       # curly single quotes
    s = re.sub(r"[\u201c\u201d]", '"', s)             # curly double quotes
    s = re.sub(r"[\u2010-\u2015]", "-", s)            # dashes
    s = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", s)      # hyphenation across lines
    s = PAGE_MARK_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


# ------------------------------------------------------------ column handling

def find_gutter(page, band=0.12):
    """
    Locate the vertical whitespace channel that separates two columns.

    Scan the middle band of the page for the widest x range containing no
    word boxes. Returns the gutter centre as a fraction of page width, or
    None if the page is single column.
    """
    words = page.extract_words() or []
    if len(words) < 20:
        return None

    width = page.width
    lo, hi = width * (0.5 - band), width * (0.5 + band)

    # Occupancy histogram in 2pt buckets across the candidate band.
    bucket = 2.0
    n = max(1, int((hi - lo) / bucket))
    occupied = [False] * n
    for w in words:
        if w["x1"] < lo or w["x0"] > hi:
            continue
        a = max(0, int((w["x0"] - lo) / bucket))
        b = min(n - 1, int((w["x1"] - lo) / bucket))
        for i in range(a, b + 1):
            occupied[i] = True

    # Widest empty run.
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

    centre = lo + (best_start + best_len / 2) * bucket
    return centre / width


def page_text(page, forced_gutter=None):
    """Return (text, mode, gutter_ratio)."""
    whole = page.extract_text() or ""
    ratio = forced_gutter if forced_gutter else find_gutter(page)

    if ratio is None:
        return whole, "single", None

    split = page.width * ratio
    left = page.crop((0, 0, split, page.height)).extract_text() or ""
    right = page.crop((split, 0, page.width, page.height)).extract_text() or ""
    combined = (left + "\n" + right).strip()

    if len(combined) < len(whole) * 0.6:
        return whole, "single_fallback", ratio
    return combined, "two_column", ratio


def read_pdf(path, forced_gutter=None):
    pages = []
    diagnostics = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text, mode, ratio = page_text(page, forced_gutter)
            diagnostics.append({
                "page": i, "mode": mode,
                "gutter": round(ratio, 3) if ratio else None,
                "chars": len(text),
            })
            pages.append((i, strip_furniture(text)))
    return pages, diagnostics


# ------------------------------------------------------------------- chunking

def classify_section(text, current):
    """Earliest heading by position in the page, not first pattern in list."""
    best_pos, best_label = None, None
    head = text[:1200]
    for pattern, label in SECTION_MARKERS:
        m = re.search(pattern, head, flags=re.IGNORECASE)
        if m and (best_pos is None or m.start() < best_pos):
            best_pos, best_label = m.start(), label
    return best_label or current


def build_chunks(pages, max_chars=6000):
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

    for page_no, text in pages:
        if not text.strip():
            continue

        new_section = classify_section(text, current_section)
        section_changed = new_section != current_section
        too_long = sum(len(b) for b in buffer) + len(text) > max_chars

        if (section_changed or too_long) and buffer:
            flush(current_section)
            buffer, buffer_pages = [], []

        current_section = new_section
        buffer.append(PAGE_MARK.format(n=page_no) + "\n" + text)
        buffer_pages.append(page_no)

    flush(current_section)
    return chunks


# ------------------------------------------------------------------- annexure

LIST_LABELS = {
    "LIST IV": ("subsume_treatment", "Must be subsumed into cost of treatment"),
    "LIST III": ("subsume_procedure", "Must be subsumed into procedure charges"),
    "LIST II": ("subsume_room", "Must be subsumed into room charges"),
    "LIST I": ("not_payable", "Never payable under the policy"),
}

HEADER_CELLS = {"ITEM", "ITEMS", "SL NO", "SL.NO", "SI NO", "SI.NO.", "S NO",
                "S.NO.", "SR NO", "SR.NO.", "NO", "PARTICULARS"}


def extract_annexure_lists(path):
    items = []
    with pdfplumber.open(path) as pdf:
        current = None
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            upper = text.upper()

            if "ANNEXURE" not in upper and current is None:
                continue

            # Take the label that appears latest on the page, since a page
            # ending one list and starting the next belongs to the next.
            best_pos, best_key = -1, None
            for key in LIST_LABELS:
                pos = upper.rfind(key)
                if pos > best_pos:
                    best_pos, best_key = pos, key
            if best_key:
                current = LIST_LABELS[best_key]

            if current is None:
                continue

            for table in page.extract_tables() or []:
                for row in table:
                    cells = [c.strip() for c in row if c and c.strip()]
                    if len(cells) < 2:
                        continue
                    # Two-column item tables look like [1, item, 35, item].
                    # v1 took cells[-1] and lost the left half. Walk pairs.
                    for i, cell in enumerate(cells):
                        if not cell.rstrip(".").isdigit():
                            continue
                        if i + 1 >= len(cells):
                            continue
                        name = cells[i + 1]
                        if name.rstrip(".").isdigit():
                            continue
                        if name.upper().strip(".") in HEADER_CELLS:
                            continue
                        if len(name) < 3:
                            continue
                        items.append({
                            "item_name": re.sub(r"\s+", " ", name),
                            "category": current[0],
                            "category_description": current[1],
                            "source_page": page_no,
                        })

            if "OMBUDSMAN" in upper:
                break

    seen, unique = set(), []
    for it in items:
        key = (it["item_name"].upper(), it["category"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    return unique


# ---------------------------------------------------------------- model calls

def call_gemini(client, types, chunk, retries=3):
    prompt = EXTRACTION_PROMPT.format(section=chunk["section"], text=chunk["text"])
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
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
        except Exception as exc:
            print(f"  error on attempt {attempt + 1}: {exc}", file=sys.stderr)
        time.sleep(2 ** attempt)
    return []


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
    ap.add_argument("--items-out", default="non_payable_items.jsonl")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--gutter", type=float, default=None,
                    help="Force the column split as a fraction of page width.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse, chunk and dump. No model calls, no cost.")
    ap.add_argument("--dump", default="dryrun_chunks.txt")
    args = ap.parse_args()

    print(f"Reading {args.pdf}")
    pages, diags = read_pdf(args.pdf, args.gutter)
    print(f"  {len(pages)} pages")

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

    chunks = build_chunks(pages)
    skip = {"ombudsman", "unknown"}
    kept = [c for c in chunks if c["section"] not in skip]
    print(f"  {len(chunks)} chunks, {len(kept)} after dropping {skip}")
    counts = {}
    for c in kept:
        counts[c["section"]] = counts.get(c["section"], 0) + 1
    print(f"  sections: {counts}")

    if args.limit:
        kept = kept[:args.limit]

    if args.dry_run:
        with open(args.dump, "w") as f:
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
        items = extract_annexure_lists(args.pdf)
        by_cat = {}
        for it in items:
            by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
        print(f"Annexure items found: {len(items)} {by_cat}")
        for it in items[:8]:
            print(f"  {it['category']:20s} {it['item_name'][:60]}")
        return

    from google import genai
    from google.genai import types
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("Set GEMINI_API_KEY first.")
    client = genai.Client(api_key=api_key)

    records, rejected = [], 0
    for i, chunk in enumerate(kept, start=1):
        print(f"[{i}/{len(kept)}] {chunk['section']} "
              f"(pages {chunk['start_page']}-{chunk['end_page']})")

        for clause in call_gemini(client, types, chunk):
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

    with open(args.out, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(records)} clauses to {args.out}")
    if rejected:
        rate = rejected / max(1, rejected + len(records))
        print(f"Rejected {rejected} for failing the verbatim check "
              f"({rate:.0%}). Above 20 percent means tighten the prompt.")

    print("Extracting Annexure A item lists")
    items = extract_annexure_lists(args.pdf)
    for it in items:
        it.update({"insurer": args.insurer, "policy_id": args.policy_id})
    with open(args.items_out, "w") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    by_cat = {}
    for it in items:
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
    print(f"Wrote {len(items)} non-payable items to {args.items_out} {by_cat}")


if __name__ == "__main__":
    main()
