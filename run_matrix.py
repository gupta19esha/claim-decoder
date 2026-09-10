"""
The optional-field matrix and the untested rejection types.

Hits the deployed API exactly as the frontend does: POST /api/cases with the
same body shape the form builds, then poll GET /api/cases/{id}. Dates are sent
as YYYY-MM-DD because that is what <input type="date"> produces, and sending
anything else would test a path no user can reach.

Sequential, never parallel: the case store is an in-process dict behind
--max-instances 1, and six concurrent runs share one Vertex quota.

  python run_matrix.py            # everything
  python run_matrix.py a b i      # named cases only
  python run_matrix.py j x3       # the same case three times, for stability

Extraction is not deterministic and neither is adjudication. A verdict that
moves between runs of identical input is telling you the input does not
determine it — which is a finding, not noise.

Writes matrix_results.json with the full result of every run.
"""

import json
import sys
import time
import urllib.error
import urllib.request

API = "https://claim-decoder-api-793807740598.asia-south1.run.app"

# One rejection text, reused verbatim across a-e and i, so that any difference
# between those runs is attributable to the claim fields and nothing else.
HDFC_PED = (
    "We regret to inform you that your claim under policy Optima Secure has "
    "been repudiated. The insured was admitted for treatment of a condition "
    "which is pre-existing in nature. As per Exclusion Excl01 of the policy "
    "wording, treatment of a pre-existing disease and its direct "
    "complications is excluded until the expiry of 36 months of continuous "
    "coverage after the date of inception of the first policy with us. The "
    "claim is therefore not payable."
)

# The case that exposed the adjudicator resolving a silence in the insurer's
# favour. The dates clear the 36-month waiting period outright (77 months of
# cover), so the only thing left that could sustain the rejection is Excl01's
# other condition — that the disease was declared at application and accepted.
# NOTHING IN THIS INPUT SAYS WHETHER IT WAS. That is the silence.
HDFC_PED_DIABETES = (
    "We regret to inform you that your claim under policy Optima Secure has "
    "been repudiated. The insured was admitted for treatment of complications "
    "arising from diabetes mellitus, which is a pre-existing condition. As "
    "per Exclusion Excl01 of the policy wording, treatment of a pre-existing "
    "disease and its direct complications is excluded. The claim is therefore "
    "not payable."
)

STAR_SUBLIMIT = (
    "Your claim for cataract surgery has been partially settled. As per "
    "policy terms the amount payable for cataract is subject to a sub-limit. "
    "The balance amount is not payable and stands deducted."
)

STAR_DOCS = (
    "Claim rejected. Documents submitted were incomplete and the discharge "
    "summary was not legible."
)

NIVA_SPECIFIED = (
    "The claim is denied as the treatment falls within the specified disease "
    "waiting period of 24 months from policy commencement."
)

HDFC = ("hdfc_ergo", "hdfc_optima_secure")
STAR = ("star_health", "star_arogya_sanjeevani")
NIVA = ("niva_bupa", "niva_reassure")

# treatment, amount, policy_start_date, admission_date
FULL_PAST = ("Angioplasty", 285000, "2020-01-15", "2026-06-10")
FULL_INSIDE = ("Angioplasty", 285000, "2025-01-01", "2026-06-10")

CASES = {
    # ---- part one: what each optional field contributes ----
    "a": ("all four, 6 years of cover (past the 36-month window)",
          HDFC, HDFC_PED, FULL_PAST),
    "b": ("all four, 17 months of cover (inside the window)",
          HDFC, HDFC_PED, FULL_INSIDE),
    # c uses b's dates so that c-vs-b isolates treatment and amount, and
    # b-vs-d isolates the dates. Stated in the report; it is not arbitrary.
    "c": ("dates only, 17 months (no treatment, no amount)",
          HDFC, HDFC_PED, (None, None, "2025-01-01", "2026-06-10")),
    "d": ("treatment and amount only, no dates",
          HDFC, HDFC_PED, ("Angioplasty", 285000, None, None)),
    "e": ("nothing filled",
          HDFC, HDFC_PED, (None, None, None, None)),

    # ---- part two: rejection types never tested ----
    "f": ("sub-limit, Star Arogya Sanjeevani, cataract",
          STAR, STAR_SUBLIMIT,
          ("Cataract surgery", 95000, "2023-04-01", "2026-05-20")),
    "g": ("documentation, Star Arogya Sanjeevani (not addressed by wording)",
          STAR, STAR_DOCS,
          (None, None, "2023-04-01", "2026-05-20")),
    "h": ("specified disease waiting period, Niva ReAssure, hernia",
          NIVA, NIVA_SPECIFIED,
          ("Hernia repair", 78000, "2025-03-01", "2026-07-20")),
    # The HDFC letter, deliberately filed against Star. Every retrieved clause
    # must be Star's. A single HDFC clause here is the worst failure this
    # system could have.
    "i": ("WRONG INSURER: HDFC letter filed against Star Arogya Sanjeevani",
          STAR, HDFC_PED, FULL_INSIDE),

    # The unstated-fact case. Should be insufficient_information naming the
    # missing fact, and should be stable across runs — with the fact unknown,
    # a verdict either way is free to swing.
    "j": ("UNSTATED FACT: PED diabetes, 77 months of cover, declaration silent",
          HDFC, HDFC_PED_DIABETES, (None, None, "2020-01-15", "2026-06-10")),
}

ORDER = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]


def post(path, body):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(API + path, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def run(key):
    label, (insurer_id, policy_id), text, (treat, amt, start, adm) = CASES[key]
    body = {
        "rejection_text": text,
        "insurer_id": insurer_id,
        "policy_id": policy_id,
        "claim": {
            "treatment": treat,
            "amount": amt,
            "policy_start_date": start,
            "admission_date": adm,
        },
    }
    print(f"\n[{key}] {label}")
    print(f"     policy={policy_id}  claim={json.dumps(body['claim'])}")

    t0 = time.time()
    created = post("/api/cases", body)
    case_id = created["case_id"]

    deadline = time.time() + 180
    while time.time() < deadline:
        res = get(f"/api/cases/{case_id}")
        if res.get("status") == "complete":
            break
        if res.get("status") == "failed":
            print(f"     FAILED: {res.get('explanation')}")
            return {"key": key, "label": label, "sent": body, "result": res}
        time.sleep(2)
    else:
        print("     TIMED OUT")
        return {"key": key, "label": label, "sent": body, "result": None}

    took = time.time() - t0
    clauses = res.get("deciding_clauses") or []
    print(f"     verdict={res.get('verdict')}  confidence={res.get('confidence')}"
          f"  type={res.get('rejection_type')}  considered={res.get('considered_count')}"
          f"  letter={res.get('letter_type')}  ({took:.0f}s)")
    for c in clauses:
        print(f"     clause: {c.get('insurer')} p{c.get('source_page')} "
              f"{c.get('exclusion_code')} | {(c.get('clause_title') or '')[:70]}")
        print(f"             wait={c.get('waiting_period_days')} "
              f"cap={c.get('monetary_cap')} pct={c.get('percent_cap')}")
    for u in res.get("unknown_facts") or []:
        mark = "MATERIAL" if u.get("material") else "not material"
        print(f"     unknown [{mark}]: {u.get('fact')}")
        print(f"               why: {(u.get('why') or '')[:190]}")
    print(f"     why: {(res.get('explanation') or '')[:400]}")
    return {"key": key, "label": label, "sent": body, "result": res,
            "seconds": round(took)}


def main():
    args = sys.argv[1:]
    repeat = 1
    for a in args:
        if a.startswith("x") and a[1:].isdigit():
            repeat = int(a[1:])
    keys = [k for k in args if k in CASES] or ORDER
    if repeat > 1:
        keys = [k for k in keys for _ in range(repeat)]
    out = []
    seen = {}
    for k in keys:
        seen[k] = seen.get(k, 0) + 1
        tag = k if seen[k] == 1 else f"{k}#{seen[k]}"
        try:
            r = run(k)
            r["key"] = tag
            out.append(r)
        except urllib.error.HTTPError as e:
            print(f"     HTTP {e.code}: {e.read().decode('utf-8')[:300]}")
            out.append({"key": k, "error": f"HTTP {e.code}"})
        except Exception as e:  # noqa: BLE001
            print(f"     ERROR {type(e).__name__}: {e}")
            out.append({"key": k, "error": f"{type(e).__name__}: {e}"})

    # Merge rather than overwrite: runs are expensive and are done in
    # batches, and a later batch must not discard an earlier one.
    try:
        with open("matrix_results.json", encoding="utf-8") as fh:
            prior = {r["key"]: r for r in json.load(fh)}
    except (OSError, ValueError):
        prior = {}
    for r in out:
        prior[r["key"]] = r
    order = ORDER + sorted(k for k in prior if k not in ORDER)
    merged = [prior[k] for k in order if k in prior]
    with open("matrix_results.json", "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)
    print("\nwrote matrix_results.json")


if __name__ == "__main__":
    main()
