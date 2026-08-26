import { useEffect, useState } from "react";
import { listPolicies, createCase, pollCase, createAppeal } from "./api";

const VERDICT_COPY = {
  well_supported: ["The rejection holds up", "strong"],
  partially_supported: ["The rejection partly holds up", "weak"],
  weakly_supported: ["The rejection looks weak", "weak"],
  insufficient_information: ["Not enough information to judge", "weak"],
};

export default function App() {
  const [insurers, setInsurers] = useState([]);
  const [insurerId, setInsurerId] = useState("");
  const [policyId, setPolicyId] = useState("");
  const [rejectionText, setRejectionText] = useState("");
  const [treatment, setTreatment] = useState("");
  const [amount, setAmount] = useState("");

  const [status, setStatus] = useState("idle"); // idle | working | done
  const [result, setResult] = useState(null);
  const [letter, setLetter] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listPolicies()
      .then((d) => setInsurers(d.insurers))
      .catch((e) => setError(e.message));
  }, []);

  const policies = insurers.find((i) => i.insurer_id === insurerId)?.policies || [];

  async function submit() {
    setError(null);
    setLetter(null);
    setStatus("working");
    try {
      const { case_id } = await createCase({
        rejection_text: rejectionText,
        insurer_id: insurerId,
        policy_id: policyId,
        claim: {
          treatment: treatment || null,
          amount: amount ? Number(amount) : null,
        },
      });
      setResult(await pollCase(case_id));
      setStatus("done");
    } catch (e) {
      setError(e.message);
      setStatus("idle");
    }
  }

  async function getAppeal() {
    setError(null);
    try {
      const d = await createAppeal(result.case_id);
      setLetter(d.letter_text);
    } catch (e) {
      setError(e.message);
    }
  }

  function startOver() {
    setResult(null);
    setLetter(null);
    setStatus("idle");
  }

  const canSubmit =
    rejectionText.trim().length >= 10 && insurerId && policyId && status !== "working";

  return (
    <div className="wrap">
      <header className="masthead">
        <h1>Claim Decoder</h1>
        <p>
          Paste the rejection letter. Read the clause the insurer is relying on,
          in the policy's own words, with the page it came from.
        </p>
      </header>

      {error && <div className="notice">{error}</div>}

      {status !== "done" ? (
        <>
          <div className="field">
            <label htmlFor="rejection">What the insurer told you</label>
            <textarea
              id="rejection"
              value={rejectionText}
              onChange={(e) => setRejectionText(e.target.value)}
              placeholder="Paste the rejection letter or the reason given, word for word."
            />
          </div>

          <div className="row">
            <div className="field">
              <label htmlFor="insurer">Insurer</label>
              <select
                id="insurer"
                value={insurerId}
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
                disabled={!insurerId}
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

          <div className="row">
            <div className="field">
              <label htmlFor="treatment">Treatment</label>
              <input
                id="treatment"
                value={treatment}
                onChange={(e) => setTreatment(e.target.value)}
                placeholder="Cataract surgery"
              />
            </div>
            <div className="field">
              <label htmlFor="amount">Amount claimed</label>
              <input
                id="amount"
                type="number"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="85000"
              />
            </div>
          </div>

          <div className="actions">
            <button onClick={submit} disabled={!canSubmit}>
              {status === "working" ? "Checking the policy" : "Check the rejection"}
            </button>
            {status === "working" && (
              <span className="working">Reading the clauses. Around 30 seconds.</span>
            )}
          </div>
        </>
      ) : (
        <Result result={result} letter={letter} onAppeal={getAppeal} onReset={startOver} />
      )}
    </div>
  );
}

function Result({ result, letter, onAppeal, onReset }) {
  const [headline, tone] = VERDICT_COPY[result.verdict] || [result.verdict, "weak"];

  return (
    <>
      <div className="verdict">
        <div className="verdict-label">Verdict</div>
        <h2>{headline}</h2>
        <span className={`badge ${tone}`}>{result.verdict.replace(/_/g, " ")}</span>
        <span className="confidence">
          confidence {Math.round(result.confidence * 100)}%
        </span>
        <p style={{ marginBottom: 0, marginTop: 14 }}>{result.explanation}</p>
      </div>

      <div className="section-head">The clause this turns on</div>
      {result.deciding_clauses.map((c, i) => (
        <article className="exhibit" key={c.clause_id || i}>
          <span className="exhibit-page">page {c.source_page}</span>
          <h3 className="exhibit-title">{c.clause_title || "Untitled clause"}</h3>
          <p className="exhibit-text">{c.clause_text}</p>
          <div className="exhibit-source">
            {c.insurer}
            {c.clause_id ? ` · clause ${c.clause_id}` : ""} · quoted word for word
            from the policy wording
          </div>
        </article>
      ))}

      <div className="section-head">Both sides of it</div>
      <div className="args">
        <div className="arg">
          <h4>Insurer's case</h4>
          <p>{result.arguments.insurer_position}</p>
        </div>
        <div className="arg">
          <h4>Your case</h4>
          <p>{result.arguments.claimant_position}</p>
        </div>
      </div>

      {letter && (
        <>
          <div className="section-head">Draft appeal</div>
          <div className="letter">{letter}</div>
        </>
      )}

      <div className="actions">
        {result.appeal_available && !letter && (
          <button onClick={onAppeal}>Draft an appeal</button>
        )}
        <button className="secondary" onClick={onReset}>
          Check another rejection
        </button>
      </div>
    </>
  );
}
