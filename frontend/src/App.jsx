import { useEffect, useState, useRef } from "react";
import { listPolicies, createCase, pollCase, createAppeal } from "./api";

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

export default function App() {
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
    <div className="page">
      <header className="masthead">
        <div className="wrap">
          <h1>Claim Decoder</h1>
          <p>
            Paste the rejection letter. See the clause the insurer is relying on,
            in the policy's own words, with the page you can check it on.
          </p>
        </div>
      </header>

      <main className="wrap">
        {error && (
          <div className="notice" role="alert">
            <strong>Something went wrong.</strong> {error}
          </div>
        )}

        {status === "done" ? (
          <Result result={result} onReset={startOver} />
        ) : (
          <>
            <div className="field">
              <label htmlFor="rejection">What the insurer told you</label>
              <div className="hint">
                Paste it word for word. Wording matters more than a summary.
              </div>
              <textarea
                id="rejection"
                value={rejectionText}
                onChange={(e) => setRejectionText(e.target.value)}
                disabled={status === "working"}
                placeholder="We regret to inform you that your claim has been repudiated…"
              />
            </div>

            <div className="grid-2">
              <div className="field">
                <label htmlFor="insurer">Insurer</label>
                <select
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
                <label htmlFor="policy">Policy</label>
                <select
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

            <details className="extras">
              <summary>Add claim details for a sharper answer</summary>
              <div className="grid-2">
                <div className="field">
                  <label htmlFor="treatment">Treatment</label>
                  <input
                    id="treatment"
                    value={treatment}
                    onChange={(e) => setTreatment(e.target.value)}
                    placeholder="Angioplasty"
                  />
                </div>
                <div className="field">
                  <label htmlFor="amount">Amount claimed</label>
                  <input
                    id="amount"
                    type="number"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    placeholder="285000"
                  />
                </div>
                <div className="field">
                  <label htmlFor="start">Policy started on</label>
                  <input
                    id="start"
                    type="date"
                    value={policyStart}
                    onChange={(e) => setPolicyStart(e.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="admission">Date of admission</label>
                  <input
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
              <button onClick={submit} disabled={!canSubmit}>
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
      </main>

      <footer className="wrap foot">
        Clause text is quoted directly from the policy wording. This is not legal
        advice.
      </footer>
    </div>
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
      <section className={`verdict ${v.tone}`}>
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
        <article className="exhibit" key={c.clause_id || i}>
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
        <div className="arg insurer">
          <h4>The insurer's case</h4>
          <p>{result.arguments.insurer_position}</p>
          {result.arguments.insurer_weak_point && (
            <p className="rebut">
              <span>Weak spot</span> {result.arguments.insurer_weak_point}
            </p>
          )}
        </div>
        <div className="arg claimant">
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

      {err && <div className="notice">{err}</div>}

      {letter && (
        <>
          <h3 className="section-head">Draft appeal</h3>
          {!letter.quotes_verified && (
            <div className="notice">
              Part of the draft quoted wording that could not be matched to the
              policy, so it was withheld.
            </div>
          )}
          <div className="letter">{letter.letter_text}</div>
          <div className="actions">
            <button onClick={copy}>{copied ? "Copied" : "Copy letter"}</button>
          </div>
        </>
      )}

      <div className="actions">
        {result.appeal_available && !letter && (
          <button onClick={getAppeal} disabled={busy}>
            {busy ? "Drafting…" : "Draft an appeal letter"}
          </button>
        )}
        <button className="ghost" onClick={onReset}>
          Check another rejection
        </button>
      </div>
    </>
  );
}
