"""
Claim Decoder API.

Pipeline for a case:

  1. Gemini parses the pasted rejection letter into structured fields
  2. The reason is embedded and matched against clauses in BigQuery, filtered
     to the insurer and policy first
  3. Three agents argue over the retrieved clauses: one for the insurer, one
     for the claimant, one adjudicating
  4. Every clause the adjudicator relies on is taken from what was retrieved,
     never from what a model wrote

Step 4 is the one that matters. Agents receive clause text, they never produce
it. A paraphrase in an appeal letter cites language the policy does not
contain, which makes the product worse than useless.
"""

import json
import os
import re
import sys
import traceback
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Claim Decoder API", version="0.2.0")

PROJECT = os.environ.get("GCP_PROJECT_ID", "project-37e668b0-6b36-4e1f-a02")
DATASET = os.environ.get("BQ_DATASET", "claims")
LOCATION = os.environ.get("VERTEX_LOCATION", "global")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
TOP_K = int(os.environ.get("TOP_K", "15"))

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

_pool = ThreadPoolExecutor(max_workers=4)


# ------------------------------------------------------------- error shape

def fail(status: int, code: str, message: str):
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message}})


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    mapping = {400: "invalid_input", 401: "unauthorised", 404: "not_found",
               429: "rate_limited", 500: "analysis_failed"}
    return fail(exc.status_code, mapping.get(exc.status_code, "analysis_failed"),
                exc.detail if isinstance(exc.detail, str) else "Request failed.")


# ------------------------------------------------------------------- auth

REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "false").lower() == "true"
DEBUG_ERRORS = os.environ.get("DEBUG_ERRORS", "false").lower() == "true"


async def current_user(authorization: Optional[str] = Header(None)) -> str:
    """User id comes from the verified token, never from a request body."""
    if not REQUIRE_AUTH:
        return "demo-user"
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in required.")
    try:
        import firebase_admin
        from firebase_admin import auth as fb_auth, credentials
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.ApplicationDefault(),
                                          {"projectId": PROJECT})
        return fb_auth.verify_id_token(authorization.split(" ", 1)[1])["uid"]
    except Exception:
        raise HTTPException(401, "Sign in required.")


# ---------------------------------------------------------------- clients

_bq = None
_genai = None


def bq():
    global _bq
    if _bq is None:
        from google.cloud import bigquery
        _bq = bigquery.Client(project=PROJECT)
    return _bq


def genai_client():
    """Vertex rather than the AI Studio key, so usage draws on Cloud credits."""
    global _genai
    if _genai is None:
        from google import genai
        _genai = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
    return _genai


def ask(prompt: str, as_json: bool = True, retries: int = 2):
    from google.genai import types
    last = None
    for attempt in range(retries + 1):
        try:
            cfg = types.GenerateContentConfig(
                response_mime_type="application/json" if as_json else "text/plain"
            )
            raw = genai_client().models.generate_content(
                model=MODEL, contents=prompt, config=cfg).text.strip()
            if not as_json:
                return raw
            raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
            return json.loads(raw)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"Model call failed: {last}")


# ------------------------------------------------------ verbatim guardrail

def normalise(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[\u2018\u2019\u02bc]", "'", s)
    s = re.sub(r"[\u201c\u201d]", '"', s)
    s = re.sub(r"[\u2010-\u2015]", "-", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(?<=\w)\s*-\s*(?=\w)", "", s)
    return s.strip().lower()


def is_verbatim(quote: str, corpus_texts: list) -> bool:
    """A quote survives only if it appears in a clause we actually retrieved."""
    q = normalise(quote)
    if len(q) < 25:
        return True
    return any(q in normalise(t) for t in corpus_texts)


# -------------------------------------------------------------- retrieval

PARSE_PROMPT = """Read this health insurance claim rejection and return JSON only.

{{
  "reason_summary": "one plain sentence describing why the insurer says it was rejected, in the insurer's own framing",
  "search_query": "a short phrase describing the policy provision being invoked, suitable for searching policy wording. No insurer names, no claim numbers.",
  "cited_clause_refs": ["any clause numbers or exclusion codes the letter quotes, e.g. 'Excl 01', '4.2'. Empty if none."],
  "treatment": "the treatment or condition, or null",
  "rejection_type": "one of: pre_existing, waiting_period, exclusion, non_payable_item, sublimit, documentation, other"
}}

Rejection text:
---
{text}
---"""


def retrieve(policy_id: str, query: str, k: int = TOP_K) -> list:
    """
    Vector search, filtered to the policy before ranking.

    Filtering first is not an optimisation. Searching the whole corpus returns
    plausible clauses from the wrong insurer, which is the single most
    damaging thing this product could do.
    """
    from google.cloud import bigquery
    sql = f"""
    WITH q AS (
      SELECT ml_generate_embedding_result AS qv
      FROM ML.GENERATE_EMBEDDING(
        MODEL `{PROJECT}.{DATASET}.embedder`,
        (SELECT @query AS content),
        STRUCT(TRUE AS flatten_json_output, 'RETRIEVAL_QUERY' AS task_type))
    )
    SELECT clause_id, clause_title, clause_text, clause_type, exclusion_code,
           source_page, insurer, policy_name, waiting_period_days,
           monetary_cap, percent_cap, cap_basis,
           ML.DISTANCE(embedding, (SELECT qv FROM q), 'COSINE') AS dist
    FROM `{PROJECT}.{DATASET}.clauses_embedded`
    WHERE policy_id = @policy_id
    ORDER BY dist
    LIMIT @k
    """
    job = bq().query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("query", "STRING", query),
            bigquery.ScalarQueryParameter("policy_id", "STRING", policy_id),
            bigquery.ScalarQueryParameter("k", "INT64", k),
        ]))
    return [dict(r) for r in job.result()]


# ----------------------------------------------------------------- agents

def clause_block(clauses: list) -> str:
    out = []
    for i, c in enumerate(clauses, start=1):
        meta = []
        if c.get("exclusion_code"):
            meta.append(c["exclusion_code"])
        if c.get("waiting_period_days"):
            meta.append(f"waiting period {c['waiting_period_days']} days")
        if c.get("monetary_cap"):
            meta.append(f"cap Rs {c['monetary_cap']}")
        if c.get("percent_cap"):
            meta.append(f"{c['percent_cap']} percent")
        tail = ", " + ", ".join(meta) if meta else ""
        out.append(
            f"[{i}] {c.get('clause_title') or 'Untitled'} "
            f"(page {c.get('source_page')}{tail})\n{c['clause_text']}"
        )
    return "\n\n".join(out)


ADVOCATE_PROMPT = """You are arguing on behalf of {side} in a health insurance claim dispute in India.

Build the strongest honest case {side} could make, using only the clauses below. Do not invent clauses. Do not rely on anything not shown here.

Return JSON only:
{{
  "position": "two or three sentences making the argument in plain English",
  "relies_on": [clause numbers from the list you actually rely on, as integers],
  "weakest_point": "the strongest objection the other side would raise"
}}

What the insurer said:
{reason}

Claim details:
{claim}

Clauses from the policy:
{clauses}"""


ADJUDICATOR_PROMPT = """You are adjudicating a health insurance claim dispute in India. You are neutral. You are not the claimant's advocate.

Decide whether the insurer's rejection is supported by the policy wording shown below.

Return JSON only:
{{
  "verdict": "well_supported | partially_supported | weakly_supported | insufficient_information",
  "confidence": a number between 0 and 1,
  "deciding_clause_numbers": [the clause numbers that actually decide this, as integers, usually one or two],
  "explanation": "three or four sentences explaining the decision in plain English a policyholder would understand. Name the specific condition that decides it, such as a date or a number of months.",
  "what_would_change_it": "the single fact that would flip this decision, phrased as something the claimant can go and check"
}}

Rules:
- If the clauses do not actually address the stated reason, return insufficient_information rather than guessing.
- A clause that merely defines a term is not a deciding clause. The clause that imposes the exclusion, waiting period or limit is.
- Judge only against the clauses shown. Never assume a provision that is not here.

What the insurer said:
{reason}

Claim details:
{claim}

The insurer's advocate argued:
{insurer_case}

The claimant's advocate argued:
{claimant_case}

Clauses from the policy:
{clauses}"""


def analyse(case: dict):
    """Runs in a background thread. Writes the result back onto the case."""
    try:
        body = case["input"]
        claim_desc = json.dumps(body["claim"], default=str)

        print("stage: parsing rejection", file=sys.stderr, flush=True)
        parsed = ask(PARSE_PROMPT.format(text=body["rejection_text"]))
        query = (parsed.get("search_query") or parsed.get("reason_summary")
                 or body["rejection_text"][:300])

        print(f"stage: retrieving for {body['policy_id']}", file=sys.stderr, flush=True)
        clauses = retrieve(body["policy_id"], query)
        if not clauses:
            case["result"].update({
                "status": "complete",
                "verdict": "insufficient_information",
                "confidence": 0.0,
                "deciding_clauses": [],
                "explanation": ("No clauses were found for this policy. The "
                                "policy wording may not be in the corpus yet."),
                "arguments": {"insurer_position": "", "claimant_position": ""},
                "appeal_available": False,
            })
            return

        block = clause_block(clauses)
        reason = parsed.get("reason_summary", "")

        print(f"stage: {len(clauses)} clauses, running agents", file=sys.stderr, flush=True)
        insurer = ask(ADVOCATE_PROMPT.format(
            side="the insurer", reason=reason, claim=claim_desc, clauses=block))
        claimant = ask(ADVOCATE_PROMPT.format(
            side="the claimant", reason=reason, claim=claim_desc, clauses=block))

        print("stage: adjudicating", file=sys.stderr, flush=True)
        ruling = ask(ADJUDICATOR_PROMPT.format(
            reason=reason, claim=claim_desc,
            insurer_case=json.dumps(insurer), claimant_case=json.dumps(claimant),
            clauses=block))

        # The adjudicator picks clause numbers, so the text shown to the user
        # is the text we retrieved. Nothing a model wrote reaches the user as
        # a quotation.
        picked = []
        for n in ruling.get("deciding_clause_numbers") or []:
            if isinstance(n, int) and 1 <= n <= len(clauses):
                picked.append(clauses[n - 1])
        if not picked:
            picked = clauses[:1]

        case["result"].update({
            "status": "complete",
            "verdict": ruling.get("verdict", "insufficient_information"),
            "confidence": float(ruling.get("confidence", 0.5)),
            "deciding_clauses": [
                {
                    "clause_id": c.get("clause_id"),
                    "clause_title": c.get("clause_title"),
                    "clause_text": c["clause_text"],
                    "insurer": c.get("insurer"),
                    "source_page": c.get("source_page"),
                    "exclusion_code": c.get("exclusion_code"),
                    "waiting_period_days": c.get("waiting_period_days"),
                    "monetary_cap": c.get("monetary_cap"),
                    "percent_cap": c.get("percent_cap"),
                }
                for c in picked
            ],
            "explanation": ruling.get("explanation", ""),
            "what_would_change_it": ruling.get("what_would_change_it"),
            "arguments": {
                "insurer_position": insurer.get("position", ""),
                "claimant_position": claimant.get("position", ""),
                "insurer_weak_point": insurer.get("weakest_point"),
                "claimant_weak_point": claimant.get("weakest_point"),
            },
            "rejection_type": parsed.get("rejection_type"),
            "considered_count": len(clauses),
            "appeal_available": ruling.get("verdict") != "well_supported",
        })
        case["_corpus"] = [c["clause_text"] for c in clauses]
        case["_clauses"] = picked
    except Exception as exc:
        # The analysis runs in a worker thread, so an exception here never
        # reaches Cloud Run's log unless it is printed. Without this the logs
        # show a clean run and a failed case, which is unfalsifiable.
        detail = traceback.format_exc()
        print("ANALYSIS FAILED\n" + detail, file=sys.stderr, flush=True)
        case["result"].update({
            "status": "failed",
            "explanation": "The analysis could not be completed.",
        })
        # Surfaced through the API only when DEBUG_ERRORS is on, so a real
        # user never sees a stack trace but a developer can see it in one
        # request instead of hunting through logs.
        if DEBUG_ERRORS:
            case["result"]["debug_error"] = f"{type(exc).__name__}: {exc}"
        case["error"] = str(exc)


# ---------------------------------------------------------------- schemas

class Claim(BaseModel):
    amount: Optional[float] = None
    treatment: Optional[str] = None
    admission_date: Optional[str] = None
    discharge_date: Optional[str] = None
    policy_start_date: Optional[str] = None


class CaseCreate(BaseModel):
    rejection_text: str = Field(min_length=10)
    insurer_id: str
    policy_id: str
    claim: Claim = Claim()


# NOTE: an in-process dict only works while max-instances is 1. A POST and a
# GET can otherwise land on different Cloud Run instances and the poll will
# 404. Firestore replaces this.
CASES: dict = {}


# -------------------------------------------------------------- endpoints

@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL,
            "time": datetime.now(timezone.utc).isoformat()}


@app.get("/debug/checks")
async def debug_checks():
    """Tests each dependency separately so a failure points at one thing."""
    out = {}
    try:
        rows = list(bq().query(
            f"SELECT COUNT(*) AS n FROM `{PROJECT}.{DATASET}.clauses_embedded`"
        ).result())
        out["bigquery"] = {"ok": True, "rows": rows[0]["n"]}
    except Exception as exc:
        out["bigquery"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        r = ask("Return JSON only: {\"ok\": true}")
        out["gemini"] = {"ok": True, "reply": r}
    except Exception as exc:
        out["gemini"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        hits = retrieve("star_arogya_sanjeevani", "pre existing disease", 3)
        out["retrieval"] = {"ok": True, "titles": [h.get("clause_title") for h in hits]}
    except Exception as exc:
        out["retrieval"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    return out


@app.post("/api/cases", status_code=202)
async def create_case(body: CaseCreate, background: BackgroundTasks,
                      uid: str = Depends(current_user)):
    case_id = str(uuid.uuid4())
    CASES[case_id] = {
        "uid": uid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": body.model_dump(),
        "result": {"case_id": case_id, "status": "processing"},
    }
    background.add_task(_pool.submit, analyse, CASES[case_id])
    return {"case_id": case_id, "status": "processing"}


@app.get("/api/cases/{case_id}")
async def get_case(case_id: str, uid: str = Depends(current_user)):
    case = CASES.get(case_id)
    if not case or case["uid"] != uid:
        raise HTTPException(404, "Case not found.")
    return case["result"]


@app.get("/api/cases")
async def list_cases(uid: str = Depends(current_user)):
    return {"cases": [
        {"case_id": cid, "status": c["result"]["status"],
         "verdict": c["result"].get("verdict"),
         "insurer_id": c["input"]["insurer_id"], "created_at": c["created_at"]}
        for cid, c in CASES.items() if c["uid"] == uid
    ]}


APPEAL_PROMPT = """Write a formal appeal letter to an Indian health insurer's grievance officer.

Rules:
- Quote the policy clause exactly as given below. Never rephrase a quotation.
- Plain, firm, unemotional. No threats, no legal citations you cannot support.
- Under 300 words.
- End with "Yours faithfully," and nothing after it.
- Do not invent facts about the claimant that are not given.

Return plain text only, no JSON, no markdown.

Why the claim was rejected:
{reason}

The finding:
{explanation}

The clause this turns on, quote it exactly:
{clause}

Claim details:
{claim}"""


@app.post("/api/cases/{case_id}/appeal")
async def create_appeal(case_id: str, uid: str = Depends(current_user)):
    case = CASES.get(case_id)
    if not case or case["uid"] != uid:
        raise HTTPException(404, "Case not found.")
    if case["result"].get("status") != "complete":
        raise HTTPException(400, "The analysis is not finished yet.")

    clauses = case.get("_clauses") or []
    if not clauses:
        raise HTTPException(400, "No clause available to appeal against.")

    letter = ask(APPEAL_PROMPT.format(
        reason=case["input"]["rejection_text"][:1200],
        explanation=case["result"].get("explanation", ""),
        clause=clauses[0]["clause_text"],
        claim=json.dumps(case["input"]["claim"], default=str),
    ), as_json=False)

    # Any policy language the letter quotes must exist in the corpus. A letter
    # citing wording the policy does not contain is worse than no letter.
    quotes = re.findall(r'"([^"]{25,})"', letter)
    corpus = case.get("_corpus") or []
    unverified = [q for q in quotes if not is_verbatim(q, corpus)]
    if unverified:
        letter = ("The draft quoted wording that could not be matched to the "
                  "policy, so it has been withheld. Quote this clause "
                  "yourself:\n\n\"" + clauses[0]["clause_text"] + "\"")

    return {"letter_text": letter, "quotes_verified": not unverified}


@app.get("/api/policies")
async def list_policies():
    sql = f"""
    SELECT insurer, policy_id, ANY_VALUE(policy_name) AS policy_name,
           COUNT(*) AS clause_count
    FROM `{PROJECT}.{DATASET}.clauses`
    GROUP BY insurer, policy_id
    ORDER BY insurer, policy_name
    """
    rows = [dict(r) for r in bq().query(sql).result()]
    grouped: dict = {}
    for r in rows:
        key = re.sub(r"[^a-z0-9]+", "_", r["insurer"].lower()).strip("_")
        grouped.setdefault(key, {"insurer_id": key, "insurer": r["insurer"],
                                 "policies": []})
        grouped[key]["policies"].append({
            "policy_id": r["policy_id"],
            "policy_name": r["policy_name"],
            "clause_count": r["clause_count"],
        })
    return {"insurers": list(grouped.values())}
