"""
Second pass over numbers only.

Fills waiting_period_days, monetary_cap and percent_cap where the first
extraction left them null but the text plainly carries the figure, and
corrects values that disagree with the text.

The model never sees or produces clause_text here. It reads one clause and
returns numbers plus, for each number, the exact substring it read it from.
That evidence span is the whole point: without it a number is an assertion,
with it the number is a claim about the source that can be falsified. Every
answer is then checked three ways before it is written:

  1. the evidence span appears verbatim in clause_text
  2. the number is derivable from the span ALONE, not from anywhere in the
     clause. The audit searches the whole clause and so accepts any figure
     present somewhere; that is too weak to write on.
  3. the conversion is the mandated one, months * 30. A 1095 where 1080 is
     expected is rejected rather than quietly accepted, because a fortnight
     of drift is a fortnight of drift in every date a tracker shows.

Anything that fails stays null. A value that already agrees with the text is
never overwritten.

Scope is deliberately narrow: clause_type in exclusion, waiting_period, limit
and coverage. 35 further clauses in condition and definition have parseable
durations, and every one sampled is a grace period, policy year, portability
window or critical-illness survival period. The deterministic parser cannot
tell those from a waiting period, so widening the scope would write wrong
values into the field a date tracker would compute from.

    python numeric_pass.py --dry-run
    python numeric_pass.py --out clauses_v16_all.jsonl
"""

import argparse
import json
import os
import re
import sys
import time

from audit_numeric_fields import (find_durations, find_money, find_percents,
                                  has_wait_context, as_number)
from extract_policy_v13 import normalise, REQUEST_TIMEOUT_MS

MODEL = "gemini-3.6-flash"
TARGET_TYPES = {"exclusion", "waiting_period", "limit", "coverage"}

# Conversions the extraction prompt mandates. months*365/12 and months*30.44
# are what a model reaches for when it converts properly instead of following
# the instruction, and they are rejected so the corpus stays internally
# consistent.
ALLOWED_CONVENTIONS = {"days", "months*30", "years*365", "years*360"}

PROMPT = """You are reading one clause from an Indian health insurance policy and extracting ONLY numbers from it.

Return JSON only:

{{
  "waiting_period_days": integer or null,
  "waiting_period_evidence": "the exact substring you read it from, copied character for character, or null",
  "monetary_cap": integer or null,
  "monetary_cap_evidence": "exact substring, or null",
  "percent_cap": number or null,
  "percent_cap_evidence": "exact substring, or null",
  "ambiguous": true or false
}}

Rules:
1. Every evidence string must be copied EXACTLY from the clause below. Never paraphrase it, never tidy it, never write a number in words that the clause writes in digits or the reverse. If you cannot copy it exactly, return null for that field.
2. Convert months to days by multiplying by 30. 36 months is 1080. 24 months is 720. Days stay as they are. Years multiply by 365.
3. waiting_period_days is only for a period the claimant must wait before cover begins. A grace period for paying premium, a notice period, the length of a policy year, and a survival period after a critical illness are NOT waiting periods. Return null for those.
4. monetary_cap is a rupee figure that limits what will be paid. Not a sum insured, not a premium, not an example.
5. percent_cap is a single percentage that limits what will be paid. If the clause lists several percentages for different conditions, such as a table of disability percentages by body part, that is not a single cap: set "ambiguous": true and return null.
6. Never infer a number that is not written. "not more than the Base Sum Insured" is not 100 percent. If the figure is not printed, return null.

Clause title: {title}

Clause:
---
{text}
---"""


def client():
    from google import genai
    from google.genai import types
    return genai.Client(
        vertexai=True,
        project=os.environ.get("GCP_PROJECT_ID",
                               "project-37e668b0-6b36-4e1f-a02"),
        location="global",
        http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS)), types


def ask(cli, types, prompt, retries=4):
    last = None
    for attempt in range(retries):
        try:
            raw = cli.models.generate_content(
                model=MODEL, contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json")).text.strip()
            raw = re.sub(r"^```(?:json)?|```$", "", raw,
                         flags=re.MULTILINE).strip()
            return json.loads(raw)
        except Exception as exc:
            last = exc
            text = str(exc)
            offline = any(s in text for s in (
                "NameResolutionError", "getaddrinfo", "Max retries",
                "Server disconnected"))
            time.sleep(20 if offline else 2 ** attempt)
    print(f"    call failed: {last}", file=sys.stderr)
    return None


# ------------------------------------------------------------------ gating

def check_span(value, evidence, clause_text, kind):
    """Returns (ok, reason). All three conditions must hold."""
    if value is None:
        return False, "null"
    if not evidence:
        return False, "no evidence span"
    if normalise(evidence) not in normalise(clause_text):
        return False, "evidence not verbatim in clause_text"

    v = as_number(value)
    if v is None:
        return False, "value not numeric"

    if kind == "waiting_period_days":
        cands = find_durations(evidence)
        if not has_wait_context(clause_text):
            return False, "clause has no waiting-period wording"
        for days, convention, _ in cands:
            if abs(days - v) <= 1 and convention in ALLOWED_CONVENTIONS:
                return True, convention
        offered = sorted({d for d, c, _ in cands if c in ALLOWED_CONVENTIONS})
        return False, f"not derivable from span (span offers {offered})"

    if kind == "monetary_cap":
        for amount, _ in find_money(evidence):
            if abs(amount - v) <= 1:
                return True, "rupees"
        return False, (f"not derivable from span "
                       f"(span offers {sorted({a for a, _ in find_money(evidence)})})")

    for pct, _ in find_percents(evidence):
        if abs(pct - v) <= 0.01:
            return True, "percent"
    return False, (f"not derivable from span "
                   f"(span offers {sorted({p for p, _ in find_percents(evidence)})})")


# ------------------------------------------------------------- candidates

def needs(rec, field):
    """Is this field worth asking about? Null with something parseable, or
    populated with something the text does not support."""
    text = rec.get("clause_text") or ""
    value = rec.get(field)
    if field == "waiting_period_days":
        cands = find_durations(text)
        if value is None:
            return bool(cands) and has_wait_context(text)
        return not any(abs(d - as_number(value)) <= 1 for d, _, _ in cands)
    if field == "monetary_cap":
        cands = [a for a, _ in find_money(text)]
        if value is None:
            return bool(cands)
        return not any(abs(a - as_number(value)) <= 1 for a in cands)
    cands = [p for p, _ in find_percents(text)]
    if value is None:
        return bool(cands)
    return not any(abs(p - as_number(value)) <= 0.01 for p in cands)


FIELDS = ("waiting_period_days", "monetary_cap", "percent_cap")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="clauses_v15_all.jsonl")
    ap.add_argument("--out", default="clauses_v16_all.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    recs = [json.loads(l) for l in open(args.corpus, encoding="utf-8")
            if l.strip()]
    candidates = [r for r in recs
                  if str(r.get("clause_type")) in TARGET_TYPES
                  and any(needs(r, f) for f in FIELDS)]

    print(f"{len(recs)} clauses, {len(candidates)} candidates in "
          f"{sorted(TARGET_TYPES)}")
    for r in candidates:
        want = [f for f in FIELDS if needs(r, f)]
        print(f"  {r['policy_id'][:20]:20s} p{str(r.get('source_page')):>4s} "
              f"{str(r.get('clause_title'))[:38]:38s} {want}")
    if args.dry_run:
        return 0

    cli, types = client()
    filled = corrected = rejected = 0
    log = []

    for i, rec in enumerate(candidates, start=1):
        title = rec.get("clause_title") or "Untitled"
        print(f"[{i}/{len(candidates)}] {rec['policy_id']} p"
              f"{rec.get('source_page')} {title[:44]}")
        got = ask(cli, types, PROMPT.format(title=title,
                                            text=rec["clause_text"]))
        if got is None:
            continue

        for field in FIELDS:
            if not needs(rec, field):
                continue
            value = got.get(field)
            evidence = got.get(field + "_evidence")
            ok, why = check_span(value, evidence, rec["clause_text"], field)
            before = rec.get(field)
            if ok:
                rec[field] = int(value) if field != "percent_cap" else float(value)
                if before is None:
                    filled += 1
                else:
                    corrected += 1
                print(f"    {field}: {before!r} -> {rec[field]!r}  ({why})")
                log.append((rec["policy_id"], rec.get("source_page"), field,
                            before, rec[field], why, evidence))
            else:
                # An existing value only reaches this loop if the parser
                # could not derive it from the clause. If the second pass
                # cannot substantiate it either, it is a figure with no basis
                # in the source and must not survive: a wrong number shown to
                # a claimant is worse than no number.
                if before is not None:
                    rec[field] = None
                    corrected += 1
                    reason = ("model reports the clause is ambiguous"
                              if got.get("ambiguous")
                              else f"unsubstantiated ({why})")
                    print(f"    {field}: {before!r} -> None  ({reason})")
                    log.append((rec["policy_id"], rec.get("source_page"),
                                field, before, None, reason, evidence))
                elif value is not None:
                    rejected += 1
                    print(f"    {field}: REJECTED {value!r} -- {why}")

    with open(args.out, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nfilled {filled}, corrected {corrected}, rejected {rejected}")
    print(f"wrote {args.out}")
    with open("numeric_pass_log.json", "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
