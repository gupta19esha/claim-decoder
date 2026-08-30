import { useEffect, useState, useRef } from "react";
import { Link } from "react-router-dom";
import {
  listPolicies,
  createCase,
  pollCase,
  createAppeal,
  auditBill,
} from "./api";

const VERDICT = {
  well_supported: {
    headline: "The rejection holds up",
    sub: "The policy wording supports what the insurer did.",
    tone: "firm",
  },
  partially_supported: {
    headline: "The rejection partly holds up",
    sub: "Some of it is supported, some of it is not.",
    tone: "mixed",
  },
  weakly_supported: {
    headline: "The rejection looks weak",
    sub: "The policy wording does not clearly support this.",
    tone: "weak",
  },
  insufficient_information: {
    headline: "Not enough to judge",
    sub: "The policy does not clearly address the reason given.",
    tone: "unknown",
  },
};

// Analysis takes 20 to 40 seconds. A spinner for that long reads as broken, so
// the stages are named. They are honest: this is the order the backend works in.
const STAGES = [
  "Reading the rejection letter",
  "Searching the policy wording",
  "Putting the insurer's case",
  "Putting your case",
  "Weighing them against the clauses",
];

const MODES = {
  rejection: {
    label: "Rejection letter",
    blurb:
      "Paste the rejection letter. See the clause the insurer is relying on, " +
      "in the policy's own words, with the page you can check it on.",
    foot:
      "Clause text is quoted directly from the policy wording. This is not " +
      "legal advice.",
  },
  bill: {
    label: "Discharge bill",
    blurb:
      "Paste the itemised bill. See which lines the IRDAI says a hospital " +
      "may not charge you for, quoted from the published list.",
    foot:
      "Item names are quoted directly from the IRDAI non-payable lists. This " +
      "is not legal advice.",
  },
};

/*
  Route shells. These still wear the superseded stylesheet: the landing has
  been rebuilt, and these two screens are next. Each deploy stays usable in
  the meantime, which is the point of going screen by screen.
*/
function Shell({ mode, children }) {
  const m = MODES[mode];
  return (
    <div className="page">
      <header className="masthead">
        <div className="wrap">
          <Link
            to="/"
            style={{ textDecoration: "none", color: "inherit" }}
            aria-label="Claim Decoder home"
          >
            <h1>Claim Decoder</h1>
          </Link>
          <nav className="tabs" aria-label="What to check">
            {Object.entries(MODES).map(([key, cfg]) => (
              <Link
                key={key}
                to={key === "rejection" ? "/rejection" : "/bill"}
                className={`tab${key === mode ? " now" : ""}`}
                aria-current={key === mode ? "page" : undefined}
                style={{ textDecoration: "none", display: "inline-block" }}
              >
                {cfg.label}
              </Link>
            ))}
          </nav>
          <p>{m.blurb}</p>
        </div>
      </header>

      <main className="wrap">{children}</main>

      <footer className="wrap foot">{m.foot}</footer>
    </div>
  );
}

export function BillRoute() {
  return (
    <Shell mode="bill">
      <BillAuditor />
    </Shell>
  );
}

function RejectionDecoder() {
  const [insurers, setInsurers] = useState([]);
  const [insurerId, setInsurerId] = useState("");
  const [policyId, setPolicyId] = useState("");
  const [rejectionText, setRejectionText] = useState("");
  const [treatment, setTreatment] = useState("");
  const [amount, setAmount] = useState("");
  const [policyStart, setPolicyStart] = useState("");
  const [admission, setAdmission] = useState("");

  const [status, setStatus] = useState("idle");
  const [stage, setStage] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    listPolicies()
      .then((d) => setInsurers(d.insurers))
      .catch((e) => setError(e.message));
    return () => clearInterval(timer.current);
  }, []);

  const policies = insurers.find((i) => i.insurer_id === insurerId)?.policies || [];

  async function submit() {
    setError(null);
    setStatus("working");
    setStage(0);
    timer.current = setInterval(
      () => setStage((s) => Math.min(s + 1, STAGES.length - 1)),
      6000
    );
    try {
      const { case_id } = await createCase({
        rejection_text: rejectionText,
        insurer_id: insurerId,
        policy_id: policyId,
        claim: {
          treatment: treatment || null,
          amount: amount ? Number(amount) : null,
          policy_start_date: policyStart || null,
          admission_date: admission || null,
        },
      });
      setResult(await pollCase(case_id));
      setStatus("done");
    } catch (e) {
      setError(e.message);
      setStatus("idle");
    } finally {
      clearInterval(timer.current);
    }
  }

  function startOver() {
    setResult(null);
    setStatus("idle");
    setError(null);
  }

  const canSubmit =
    rejectionText.trim().length >= 10 && insurerId && policyId && status !== "working";

  return (
    <>
        {error && (
          <div className="card notice" role="alert">
            <strong>Something went wrong.</strong> {error}
          </div>
        )}

        {status === "done" ? (
          <Result result={result} onReset={startOver} />
        ) : (
          <>
            <div className="field">
              <label className="label" htmlFor="rejection">
                What the insurer told you
              </label>
              <div className="hint">
                Paste it word for word. Wording matters more than a summary.
              </div>
              <textarea
                className="textarea"
                id="rejection"
                value={rejectionText}
                onChange={(e) => setRejectionText(e.target.value)}
                disabled={status === "working"}
                placeholder="We regret to inform you that your claim has been repudiated…"
              />
            </div>

            <div className="grid-2">
              <div className="field">
                <label className="label" htmlFor="insurer">Insurer</label>
                <select
                  className="select"
                  id="insurer"
                  value={insurerId}
                  disabled={status === "working"}
                  onChange={(e) => {
                    setInsurerId(e.target.value);
                    setPolicyId("");
                  }}
                >
                  <option value="">Select</option>
                  {insurers.map((i) => (
                    <option key={i.insurer_id} value={i.insurer_id}>
                      {i.insurer}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field">
                <label className="label" htmlFor="policy">Policy</label>
                <select
                  className="select"
                  id="policy"
                  value={policyId}
                  onChange={(e) => setPolicyId(e.target.value)}
                  disabled={!insurerId || status === "working"}
                >
                  <option value="">Select</option>
                  {policies.map((p) => (
                    <option key={p.policy_id} value={p.policy_id}>
                      {p.policy_name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <details className="card extras">
              <summary>Add claim details for a sharper answer</summary>
              <div className="grid-2">
                <div className="field">
                  <label className="label" htmlFor="treatment">Treatment</label>
                  <input
                    className="input"
                    id="treatment"
                    value={treatment}
                    onChange={(e) => setTreatment(e.target.value)}
                    placeholder="Angioplasty"
                  />
                </div>
                <div className="field">
                  <label className="label" htmlFor="amount">Amount claimed</label>
                  <input
                    className="input"
                    id="amount"
                    type="number"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    placeholder="285000"
                  />
                </div>
                <div className="field">
                  <label className="label" htmlFor="start">Policy started on</label>
                  <input
                    className="input"
                    id="start"
                    type="date"
                    value={policyStart}
                    onChange={(e) => setPolicyStart(e.target.value)}
                  />
                </div>
                <div className="field">
                  <label className="label" htmlFor="admission">
                    Date of admission
                  </label>
                  <input
                    className="input"
                    id="admission"
                    type="date"
                    value={admission}
                    onChange={(e) => setAdmission(e.target.value)}
                  />
                </div>
              </div>
              <p className="hint">
                Waiting periods turn on dates. Without them the answer has to
                hedge.
              </p>
            </details>

            <div className="actions">
              <button className="btn" onClick={submit} disabled={!canSubmit}>
                {status === "working" ? "Checking…" : "Check the rejection"}
              </button>
            </div>

            {status === "working" && (
              <ol className="stages" aria-live="polite">
                {STAGES.map((s, i) => (
                  <li
                    key={s}
                    className={i < stage ? "done" : i === stage ? "now" : ""}
                  >
                    {s}
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
    </>
  );
}

/* --------------------------------------------------------- bill auditor */

const rupees = (n) =>
  n === null || n === undefined
    ? null
    : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

/* The four IRDAI lists say different things and the difference changes what
   the claimant should say. Only the first is money that should never have
   been charged; the rest is money already inside a charge the bill has. */
const CATEGORY = {
  not_payable: {
    heading: "Should not have been charged at all",
    tone: "firm",
    note: "The IRDAI lists these as never payable under any policy.",
  },
  subsume_room: {
    heading: "Already covered by the room charge",
    tone: "weak",
    note: "Billing these separately charges you twice for the same thing.",
  },
  subsume_procedure: {
    heading: "Already covered by the procedure charge",
    tone: "weak",
    note: "Billing these separately charges you twice for the same thing.",
  },
  subsume_treatment: {
    heading: "Already covered by the cost of treatment",
    tone: "weak",
    note: "Billing these separately charges you twice for the same thing.",
  },
};

function BillAuditor() {
  const [billText, setBillText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);

  async function readFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    try {
      // Read in the browser rather than uploading. Nothing about the bill
      // reaches the server until the user presses the button, and a bill is
      // health data.
      setBillText(await file.text());
    } catch {
      setError("That file could not be read. Paste the bill text instead.");
    }
    e.target.value = "";
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      setResult(await auditBill(billText));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <BillResult
        result={result}
        onReset={() => {
          setResult(null);
          setBillText("");
        }}
      />
    );
  }

  return (
    <>
      {error && (
        <div className="card notice" role="alert">
          <strong>Something went wrong.</strong> {error}
        </div>
      )}

      <div className="field">
        <label className="label" htmlFor="bill">
          The itemised bill
        </label>
        <div className="hint">
          One line per item, with the amount at the end of the line. Copy it
          straight from the bill.
        </div>
        <textarea
          className="textarea"
          id="bill"
          value={billText}
          onChange={(e) => setBillText(e.target.value)}
          disabled={busy}
          placeholder={"ROOM RENT - SINGLE PRIVATE (4 DAYS)   24000.00\nGLOVES   450.00\nBABY FOOD   320.00"}
        />
      </div>

      <div className="actions">
        <button
          className="btn"
          onClick={submit}
          disabled={billText.trim().length < 10 || busy}
        >
          {busy ? "Checking…" : "Check the bill"}
        </button>
        <button
          className="btn ghost"
          onClick={() => fileRef.current?.click()}
          disabled={busy}
        >
          Upload a text file
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.csv,text/plain,text/csv"
          onChange={readFile}
          hidden
        />
      </div>

      <ScopeNotice />
    </>
  );
}

/* Stated before the user runs it and again with the result. A bill auditor
   that silently skips the largest deduction on most bills would be read as
   having checked it. */
function ScopeNotice({ reason }) {
  return (
    <section className="card scope">
      <div className="eyebrow">What this does not check</div>
      <p>
        <strong>Room rent is not checked.</strong>{" "}
        {reason ||
          "Room rent limits are set in your Policy Schedule, not in the policy wording, so they cannot be checked from the policy alone."}
      </p>
      <p className="hint">
        This checks the 146 items the IRDAI says a hospital may not bill to a
        claim. It does not check sub-limits, deductibles, or whether the
        treatment itself was covered.
      </p>
    </section>
  );
}

function BillResult({ result, onReset }) {
  const grouped = result.by_category || [];
  const findings = result.findings || [];

  return (
    <>
      <section className="card verdict firm">
        <div className="eyebrow">Bill check</div>
        <h2>
          {findings.length === 0
            ? "Nothing flagged"
            : `${rupees(result.flagged_total)} should not have been billed to you`}
        </h2>
        <p className="verdict-sub">
          {result.lines_flagged} of {result.lines_read} lines matched the IRDAI
          non-payable lists.
          {result.findings_without_amount > 0 &&
            ` ${result.findings_without_amount} matched but had no readable amount, so they are not in the total.`}
        </p>
      </section>

      {grouped.map((cat) => {
        const meta = CATEGORY[cat.category] || {};
        const rows = findings.filter((f) => f.category === cat.category);
        return (
          <section key={cat.category}>
            <h3 className="section-head">
              {meta.heading || cat.category_description}
            </h3>
            <p className="hint">{meta.note}</p>
            {rows.map((f, i) => (
              <article className="card bill-row" key={`${f.line_no}-${i}`}>
                <div className="bill-line">
                  <span className="bill-desc">{f.description}</span>
                  <span className="bill-amt">
                    {rupees(f.amount) || "no amount read"}
                  </span>
                </div>
                <div className="bill-item">
                  <span className="eyebrow">IRDAI list</span>
                  <q>{f.item_name}</q>
                </div>
                <div className="exhibit-meta">
                  <span>{f.category_description}</span>
                  <span>line {f.line_no}</span>
                </div>
              </article>
            ))}
            <p className="provenance">
              {rows.length} line{rows.length === 1 ? "" : "s"},{" "}
              {rupees(cat.amount)}
              {cat.amount_known ? "" : " from the lines with a readable amount"}
            </p>
          </section>
        );
      })}

      <ScopeNotice reason={result.checks?.room_rent_reason} />

      <div className="actions">
        <button className="btn ghost" onClick={onReset}>
          Check another bill
        </button>
      </div>
    </>
  );
}

/* Policy clauses arrive as one block containing lettered sub-clauses. Left as
   is they are a wall of text. Breaking on the lettering makes them readable
   without altering a character. */
function clauseParts(text) {
  return String(text)
    .split(/(?=(?:^|\s)[A-H]\.\s)/g)
    .map((p) => p.trim())
    .filter(Boolean);
}

function Result({ result, onReset }) {
  const [letter, setLetter] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState(null);

  const v = VERDICT[result.verdict] || VERDICT.insufficient_information;

  async function getAppeal() {
    setBusy(true);
    setErr(null);
    try {
      setLetter(await createAppeal(result.case_id));
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    await navigator.clipboard.writeText(letter.letter_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <>
      <section className={`card verdict ${v.tone}`}>
        <div className="eyebrow">Verdict</div>
        <h2>{v.headline}</h2>
        <p className="verdict-sub">{v.sub}</p>
        <p className="explain">{result.explanation}</p>
        <div className="meter">
          <div className="meter-bar">
            <span style={{ width: `${Math.round(result.confidence * 100)}%` }} />
          </div>
          <span className="meter-label">
            {Math.round(result.confidence * 100)}% confident in this reading
          </span>
        </div>
      </section>

      {result.what_would_change_it && (
        <section className="pivot">
          <div className="eyebrow">Go and check this</div>
          <p>{result.what_would_change_it}</p>
        </section>
      )}

      <h3 className="section-head">The clause this turns on</h3>
      {result.deciding_clauses.map((c, i) => (
        <article className="card exhibit" key={c.clause_id || i}>
          <div className="exhibit-tab">page {c.source_page}</div>
          <h4>{c.clause_title || "Untitled clause"}</h4>
          <div className="exhibit-body">
            {clauseParts(c.clause_text).map((p, j) => (
              <p key={j}>{p}</p>
            ))}
          </div>
          <div className="exhibit-meta">
            {[
              c.insurer,
              c.exclusion_code,
              c.waiting_period_days ? `${c.waiting_period_days} day wait` : null,
              c.monetary_cap
                ? `cap ₹${Number(c.monetary_cap).toLocaleString("en-IN")}`
                : null,
              c.percent_cap ? `${c.percent_cap}%` : null,
            ]
              .filter(Boolean)
              .map((m) => (
                <span key={m}>{m}</span>
              ))}
          </div>
          <div className="exhibit-check">
            Quoted word for word. Open your policy at page {c.source_page} and
            read it yourself.
          </div>
        </article>
      ))}

      <h3 className="section-head">How each side would argue it</h3>
      <div className="args">
        <div className="card arg insurer">
          <h4>The insurer's case</h4>
          <p>{result.arguments.insurer_position}</p>
          {result.arguments.insurer_weak_point && (
            <p className="rebut">
              <span>Weak spot</span> {result.arguments.insurer_weak_point}
            </p>
          )}
        </div>
        <div className="card arg claimant">
          <h4>Your case</h4>
          <p>{result.arguments.claimant_position}</p>
          {result.arguments.claimant_weak_point && (
            <p className="rebut">
              <span>Weak spot</span> {result.arguments.claimant_weak_point}
            </p>
          )}
        </div>
      </div>

      {result.considered_count > 0 && (
        <p className="provenance">
          {result.considered_count} clauses from this policy were read before
          settling on the one above.
        </p>
      )}

      {err && <div className="card notice">{err}</div>}

      {letter && (
        <>
          <h3 className="section-head">Draft appeal</h3>
          {!letter.quotes_verified && (
            <div className="card notice">
              Part of the draft quoted wording that could not be matched to the
              policy, so it was withheld.
            </div>
          )}
          <div className="card letter">{letter.letter_text}</div>
          <div className="actions">
            <button className="btn" onClick={copy}>
              {copied ? "Copied" : "Copy letter"}
            </button>
          </div>
        </>
      )}

      <div className="actions">
        {result.appeal_available && !letter && (
          <button className="btn" onClick={getAppeal} disabled={busy}>
            {busy ? "Drafting…" : "Draft an appeal letter"}
          </button>
        )}
        <button className="btn ghost" onClick={onReset}>
          Check another rejection
        </button>
      </div>
    </>
  );
}
