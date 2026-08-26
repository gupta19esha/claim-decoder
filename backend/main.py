"""
Claim Decoder API, stubbed.

Every endpoint matches the frozen contract in handoff.md and returns realistic
fake data. Nothing here calls BigQuery or Gemini yet. The point is to get a
live URL with CORS and Firebase token verification working before any real
logic exists, because those are the things that only break once deployed.

Replace the bodies marked STUB one at a time. The shapes never change, so the
frontend never has to.
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Claim Decoder API", version="0.1.0-stub")

# ----------------------------------------------------------------- CORS
# Both Firebase Hosting domains plus local dev. Configured before any
# frontend exists, because "works in Postman, fails in browser" is always
# this and always costs an hour.

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:3000",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ------------------------------------------------------------- error shape

class ErrorBody(BaseModel):
    code: Literal["invalid_input", "not_found", "unauthorised",
                  "analysis_failed", "rate_limited"]
    message: str


def fail(status: int, code: str, message: str):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    mapping = {400: "invalid_input", 401: "unauthorised",
               404: "not_found", 429: "rate_limited", 500: "analysis_failed"}
    return fail(exc.status_code,
                mapping.get(exc.status_code, "analysis_failed"),
                exc.detail if isinstance(exc.detail, str) else "Request failed.")


# ------------------------------------------------------------------- auth

REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "false").lower() == "true"


async def current_user(authorization: Optional[str] = Header(None)) -> str:
    """
    Returns the caller's user id.

    The user id is derived from the verified token, never accepted from a
    request body, otherwise anyone can read anyone else's cases.

    While REQUIRE_AUTH is false this returns a demo user so the frontend can
    be built before Firebase is wired up. Flip the env var to turn real
    verification on, and this is the only function that changes.
    """
    if not REQUIRE_AUTH:
        return "demo-user"

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in required.")

    token = authorization.split(" ", 1)[1]
    try:
        import firebase_admin
        from firebase_admin import auth as fb_auth, credentials
        if not firebase_admin._apps:
            firebase_admin.initialize_app(
                credentials.ApplicationDefault(),
                {"projectId": os.environ["FIREBASE_PROJECT_ID"]},
            )
        decoded = fb_auth.verify_id_token(token)
        return decoded["uid"]
    except Exception:
        raise HTTPException(401, "Sign in required.")


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


# ------------------------------------------------------- in-memory store
# Cloud Run instances are ephemeral and there may be up to three of them, so
# a dict is not a real store. Firestore replaces this. Fine for a stub.

CASES: dict = {}


def stub_result(case_id: str, body: CaseCreate) -> dict:
    """STUB. Replace with retrieval plus the three agents."""
    return {
        "case_id": case_id,
        "status": "complete",
        "verdict": "weakly_supported",
        "confidence": 0.72,
        "deciding_clauses": [
            {
                "clause_id": "1",
                "clause_title": "Pre-Existing Diseases",
                "clause_text": (
                    "Expenses related to the treatment of a pre-existing "
                    "Disease (PED) and its direct complications shall be "
                    "excluded until the expiry of thirty six months of "
                    "continuous coverage after the date of inception of the "
                    "first policy with the insurer."
                ),
                "insurer": "Star Health",
                "source_page": 10,
            }
        ],
        "explanation": (
            "The insurer cited a pre-existing disease exclusion. The policy "
            "applies that exclusion only for the first thirty six months of "
            "continuous coverage. Check the policy inception date against the "
            "date of admission."
        ),
        "arguments": {
            "insurer_position": (
                "The condition was diagnosed before the policy commenced and "
                "falls within the thirty six month exclusion window."
            ),
            "claimant_position": (
                "The exclusion lapses after thirty six months of continuous "
                "coverage. If the policy has run longer than that, the "
                "exclusion no longer applies."
            ),
        },
        "appeal_available": True,
    }


# -------------------------------------------------------------- endpoints

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.post("/api/cases", status_code=202)
async def create_case(body: CaseCreate, uid: str = Depends(current_user)):
    """
    Returns immediately with a case id. The frontend polls the GET endpoint.

    Analysis will take 10 to 30 seconds once real. A synchronous request would
    hit the Cloud Run timeout and look like a crash mid demo, so the polling
    shape is built in from the start even though the stub is instant.
    """
    case_id = str(uuid.uuid4())
    CASES[case_id] = {
        "uid": uid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "insurer_id": body.insurer_id,
        "policy_id": body.policy_id,
        "rejection_text": body.rejection_text,
        "result": stub_result(case_id, body),
    }
    return {"case_id": case_id, "status": "processing"}


@app.get("/api/cases/{case_id}")
async def get_case(case_id: str, uid: str = Depends(current_user)):
    case = CASES.get(case_id)
    if not case or case["uid"] != uid:
        raise HTTPException(404, "Case not found.")
    return case["result"]


@app.get("/api/cases")
async def list_cases(uid: str = Depends(current_user)):
    return {
        "cases": [
            {
                "case_id": cid,
                "status": c["result"]["status"],
                "verdict": c["result"]["verdict"],
                "insurer_id": c["insurer_id"],
                "created_at": c["created_at"],
            }
            for cid, c in CASES.items()
            if c["uid"] == uid
        ]
    }


@app.post("/api/cases/{case_id}/appeal")
async def create_appeal(case_id: str, uid: str = Depends(current_user)):
    """STUB. Replace with Gemini generation over the deciding clauses."""
    case = CASES.get(case_id)
    if not case or case["uid"] != uid:
        raise HTTPException(404, "Case not found.")
    return {
        "letter_text": (
            "To the Grievance Redressal Officer,\n\n"
            "I am writing to appeal the rejection of my claim.\n\n"
            "The rejection cites the pre-existing disease exclusion. That "
            "exclusion applies only until the expiry of thirty six months of "
            "continuous coverage from the inception of the first policy. My "
            "policy has been continuously in force beyond that period, so the "
            "exclusion no longer applies.\n\n"
            "I request that the claim be reconsidered.\n\n"
            "Yours faithfully,"
        )
    }


@app.get("/api/policies")
async def list_policies():
    """
    No auth. The frontend needs this to populate the insurer picker before
    sign in. Replace with a SELECT DISTINCT over claims.clauses.
    """
    return {
        "insurers": [
            {"insurer_id": "star_health", "insurer": "Star Health",
             "policies": [{"policy_id": "star_arogya_sanjeevani",
                           "policy_name": "Arogya Sanjeevani"}]},
            {"insurer_id": "hdfc_ergo", "insurer": "HDFC Ergo",
             "policies": [{"policy_id": "hdfc_optima_secure",
                           "policy_name": "Optima Secure"}]},
            {"insurer_id": "tata_aig", "insurer": "Tata AIG",
             "policies": [{"policy_id": "tata_medicare_select",
                           "policy_name": "Medicare Select"}]},
            {"insurer_id": "icici_lombard", "insurer": "ICICI Lombard",
             "policies": [{"policy_id": "icici_elevate",
                           "policy_name": "Elevate"}]},
            {"insurer_id": "niva_bupa", "insurer": "Niva Bupa",
             "policies": [{"policy_id": "niva_reassure",
                           "policy_name": "ReAssure"},
                          {"policy_id": "niva_reassure_30",
                           "policy_name": "ReAssure 3.0"}]},
        ]
    }
