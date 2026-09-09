import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { listPolicies, createCase, pollCase, createAppeal } from "../api";
import Shell from "../components/Shell.jsx";
import Exhibit from "../components/Exhibit.jsx";
import { Arrive } from "../components/motion.jsx";
import { insurerMismatch } from "../insurerMatch.js";

/*
  The rejection decoder.

  ORDER OF OPERATIONS IS THE DESIGN.

  The old build asked for the insurer and the policy before it asked for
  anything else, and half our research respondents did not have their policy
  document. That picker was a wall placed in front of a door. Here the letter
  comes first, because the letter is the thing they are holding, and the
  policy question arrives once they are already invested — and it can be
  answered from a letterhead rather than a document.

  Four steps, each a screen rather than a state: paste, policy, the wait, the
  finding. The wait is a screen because it lasts 20 to 40 seconds and a
  spinner for that long reads as broken.
*/

const STEPS = ["The letter", "The policy", "Reading", "The finding"];

/*
  Verdict tone. Contest green is the only saturated colour and it means "you
  may have a case". Upheld is graphite: when the rejection holds, the page
  goes quiet rather than red. The previous build had this inverted.
*/
const VERDICT = {
  weakly_supported: {
    headline: "The rejection looks weak",
    sub: "The policy wording does not clearly support what the insurer did.",
    band: "bg-contest text-paper",
    rule: "border-contest",
    contestable: true,
  },
  partially_supported: {
    headline: "The rejection only partly holds",
    sub: "Some of it is supported by the wording. Some of it is not.",
    band: "bg-contest text-paper",
    rule: "border-contest",
    contestable: true,
  },
  well_supported: {
    headline: "The rejection holds up",
    sub: "The policy wording does support what the insurer did.",
    band: "bg-upheld-tint text-ink",
    rule: "border-upheld",
    contestable: false,
  },
  insufficient_information: {
    headline: "Not enough to judge",
    sub: "The policy wording we hold does not clearly address the reason they gave.",
    band: "bg-paper-sunk text-ink",
    rule: "border-ink-soft",
    contestable: false,
    // See `scored` below.
    scored: false,
  },
};

/*
  `scored` decides whether the confidence figure is shown.

  The adjudicator returns a confidence on every verdict including
  insufficient_information, and there it means "I am confident there is not
  enough here to judge" — measured at 0.95 on a case with no dates at all.
  Printed as "Confidence in this reading: 95%" directly under "Not enough to
  judge" it reads as a contradiction, and a reader who has just been told we
  cannot answer does not need a number attached to it.

  So it is shown only where there is a finding for it to qualify. Every other
  verdict is scored; the default below is true, so a new verdict added to the
  table is scored unless it says otherwise.
*/
for (const v of Object.values(VERDICT)) {
  if (v.scored === undefined) v.scored = true;
}


// Honest: this is the order the backend actually works in.
const STAGES = [
  "Reading the rejection letter",
  "Searching the policy wording",
  "Putting the insurer's case",
  "Putting your case",
  "Weighing them against the clauses",
];

const rupees = (n) =>
  n === null || n === undefined || n === ""
    ? null
    : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

export default function Rejection() {
  const [step, setStep] = useState(0);
  const [letter, setLetter] = useState("");
  const [insurers, setInsurers] = useState([]);
  const [policy, setPolicy] = useState(null);
  const [claim, setClaim] = useState({
    treatment: "",
    amount: "",
    policy_start_date: "",
    admission_date: "",
  });
  const [stage, setStage] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    listPolicies()
      .then((d) => setInsurers(d.insurers || []))
      .catch((e) => setError(e.message));
    return () => clearInterval(timer.current);
  }, []);

  /*
    Each step is a whole screen, and the browser keeps the scroll offset when
    one replaces another. Measured: pressing "Check the rejection" from the
    foot of the policy step landed the reader 1709px into the finding, in the
    middle of the second clause, having never seen the verdict headline that
    the screen exists to deliver. Nothing overflowed and nothing animated —
    the page had simply moved out from under them, which is what "the whole
    screen moves" means.

    Instant, never smooth. A long animated scroll is motion nobody asked for,
    and this is read by someone stressed; it would also fight a reader who
    starts scrolling before it finishes.
  */
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [step]);

  const policies = insurers.flatMap((i) =>
    (i.policies || []).map((p) => ({ ...p, insurer: i.insurer }))
  );

  async function run() {
    setError(null);
    setStep(2);
    setStage(0);
    timer.current = setInterval(
      () => setStage((s) => Math.min(s + 1, STAGES.length - 1)),
      6000
    );
    try {
      const { case_id } = await createCase({
        rejection_text: letter,
        insurer_id: policy.insurer_id || "",
        policy_id: policy.policy_id,
        claim: {
          treatment: claim.treatment || null,
          amount: claim.amount ? Number(claim.amount) : null,
          policy_start_date: claim.policy_start_date || null,
          admission_date: claim.admission_date || null,
        },
      });
      setResult(await pollCase(case_id));
      setStep(3);
    } catch (e) {
      setError(e.message);
      setStep(1);
    } finally {
      clearInterval(timer.current);
    }
  }

  const foot =
    "Clause text is quoted directly from the insurer's published policy wording. This is not legal advice.";

  return (
    <Shell steps={STEPS} current={step} foot={foot}>
      {error && (
        <div
          role="alert"
          className="mb-8 border-l-[3px] border-insurer bg-card px-5 py-4 font-doc text-base"
        >
          <strong className="font-semibold">Something went wrong.</strong>{" "}
          {error}
        </div>
      )}

      {step === 0 && (
        <PasteStep
          letter={letter}
          setLetter={setLetter}
          policies={policies}
          onNext={() => setStep(1)}
        />
      )}
      {step === 1 && (
        <PolicyStep
          letter={letter}
          policies={policies}
          policy={policy}
          setPolicy={setPolicy}
          claim={claim}
          setClaim={setClaim}
          onBack={() => setStep(0)}
          onRun={run}
        />
      )}
      {step === 2 && <WaitingStep letter={letter} policy={policy} stage={stage} />}
      {step === 3 && result && (
        <Finding
          result={result}
          policy={policy}
          letter={letter}
          policies={policies}
        />
      )}
    </Shell>
  );
}

/* ------------------------------------------------------------ step one */

function PasteStep({ letter, setLetter, policies, onNext }) {
  const ready = letter.trim().length >= 10;

  return (
    <div className="lg:grid lg:grid-cols-12 lg:gap-12">
      {/* Desktop uses the width for guidance beside the field rather than
          above it, so the caveats are readable without pushing the textarea
          below the fold. */}
      <div className="lg:col-span-7">
        <h1 className="font-doc text-3xl leading-tight font-semibold text-balance sm:text-4xl">
          What did the insurer tell you?
        </h1>
        <p className="mt-3 max-w-[52ch] font-doc text-lg leading-relaxed text-ink-2">
          Paste the rejection letter, the email, or the SMS. Word for word —
          the wording is what we check against, so a summary will not do.
        </p>

        <label htmlFor="letter" className="sr-only">
          The rejection letter
        </label>
        {/* text-base is 16px, and that number is not a preference. Mobile
            Safari zooms the viewport when a focused field computes below
            16px, and it does not zoom back out — the reader is left on a page
            wider than the screen, having only tapped a textarea. The designed
            14px mono returns at sm:, 640px and up, where no browser does
            this. Do not "tidy" the two sizes into one. */}
        <textarea
          id="letter"
          value={letter}
          onChange={(e) => setLetter(e.target.value)}
          rows={12}
          placeholder="We regret to inform you that your claim has been repudiated…"
          className="mt-6 w-full border border-rule bg-card px-4 py-4 font-quote text-base leading-relaxed text-ink placeholder:text-ink-soft/60 focus:border-ink sm:text-[0.875rem]"
        />

        <div className="mt-5 flex flex-wrap items-center gap-4">
          <button
            onClick={onNext}
            disabled={!ready}
            className="border border-ink bg-ink px-7 py-4 font-doc text-lg font-semibold text-paper transition-colors hover:bg-ink-2 disabled:cursor-not-allowed disabled:opacity-35"
          >
            Continue
          </button>
          {!ready && (
            <span className="font-doc text-base text-ink-soft">
              Paste the letter to continue.
            </span>
          )}
        </div>
      </div>

      {/* The six-policy limit, before they type. Failing at submit after
          someone has pasted a letter is the worst possible moment to tell
          them we cannot help. */}
      <aside className="mt-10 lg:col-span-4 lg:col-start-9 lg:mt-0">
        <div className="border-l-[3px] border-ochre bg-ochre-tint px-5 py-4">
          <p className="folio text-ochre">Before you start</p>
          <p className="mt-2 font-doc text-base leading-relaxed text-ink">
            We hold the full wording for six policies. If yours is not one of
            them we cannot check your rejection yet.
          </p>
          <ul className="mt-3 space-y-1">
            {policies.map((p) => (
              <li key={p.policy_id} className="font-doc text-base text-ink-2">
                {p.insurer} — {p.policy_name}
              </li>
            ))}
            {policies.length === 0 && (
              <li className="font-doc text-base text-ink-soft">Loading…</li>
            )}
          </ul>
          <p className="mt-3 font-doc text-base leading-relaxed text-ink-2">
            Not listed?{" "}
            <Link to="/bill" className="text-ink underline">
              The bill checker
            </Link>{" "}
            works for any insurer.
          </p>
        </div>
      </aside>
    </div>
  );
}

/* ------------------------------------------------------------ step two */

function PolicyStep({
  letter,
  policies,
  policy,
  setPolicy,
  claim,
  setClaim,
  onBack,
  onRun,
}) {
  const set = (k) => (e) => setClaim({ ...claim, [k]: e.target.value });

  /*
    THE DATES ARE NOT BEHIND A DISCLOSURE, AND THAT IS THE WHOLE POINT.

    They used to sit inside "Add dates and amount for a sharper answer",
    stacked against a second collapsed row, between the cards and the button.
    Two grey rows that both read as footnotes, and nobody opens a footnote.

    That was not cosmetic. The adjudicator is handed the claim details and
    told to judge only against what it can see and to return
    insufficient_information rather than guess. A waiting period is arithmetic
    on two dates; with neither supplied there is nothing to do the arithmetic
    on. So the default path through this form — fill nothing, press the
    button — produced the worst answer the product can give, on the commonest
    kind of rejection there is.

    Treatment and amount stay collapsed. They colour how the answer is
    written. They do not decide it.
  */
  const [warned, setWarned] = useState(false);

  const missing = [
    !claim.policy_start_date && "the date the policy started",
    !claim.admission_date && "the date of admission",
  ].filter(Boolean);

  /*
    Warn once, then let them through. Blocking would put a wall back in front
    of the door, and the dates are genuinely optional — someone reading a
    letter in a corridor may not have them. Deriving this rather than storing
    it means the warning self-clears the moment the dates are filled, so a
    stale one can never sit underneath a complete form.
  */
  const held = warned && missing.length > 0;

  function submit() {
    if (missing.length > 0 && !warned) {
      setWarned(true);
      return;
    }
    onRun();
  }

  return (
    <div>
      <h1 className="font-doc text-3xl leading-tight font-semibold text-balance sm:text-4xl">
        Which policy is this?
      </h1>
      <p className="mt-3 max-w-[56ch] font-doc text-lg leading-relaxed text-ink-2">
        You do not need the policy document. The insurer's name is on the
        letter you just pasted — match it below.
      </p>

      {/* Insurer name is the largest thing on each card, because that is what
          someone can match against a letterhead without the policy in hand. */}
      <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {policies.map((p) => {
          const chosen = policy?.policy_id === p.policy_id;
          return (
            <button
              key={p.policy_id}
              onClick={() => setPolicy(p)}
              aria-pressed={chosen}
              className={
                "flex flex-col items-start border p-5 text-left transition-colors " +
                (chosen
                  ? "border-ink bg-ink text-paper"
                  : "border-rule bg-card hover:border-ink")
              }
            >
              <span className="font-doc text-xl leading-tight font-semibold sm:text-2xl">
                {p.insurer}
              </span>
              <span
                className={
                  "mt-1 font-doc text-base " +
                  (chosen ? "text-paper/80" : "text-ink-2")
                }
              >
                {p.policy_name}
              </span>
              <span
                className={
                  "folio mt-4 " + (chosen ? "text-paper/60" : "text-ink-soft")
                }
              >
                {p.clause_count} clauses held
              </span>
            </button>
          );
        })}
      </div>

      {/* The 3px rule is the weight this system gives a block that carries the
          argument, and that is exactly what this is. */}
      <section className="mt-8 border-t-[3px] border-ink bg-card px-5 py-5 sm:px-6 sm:py-6">
        <h2 className="font-doc text-xl leading-tight font-semibold sm:text-2xl">
          When did the policy start, and when were you admitted?
        </h2>
        <p className="mt-2 max-w-[62ch] font-doc text-base leading-relaxed text-ink-2">
          A waiting period is counted in months from the day your policy
          started, so these two dates are what decide whether one had run out
          by the time you were admitted. Without both, the answer has to hedge.
        </p>
        <div className="mt-5 grid gap-5 sm:grid-cols-2">
          <Field label="Policy started on" id="start">
            <input
              id="start"
              type="date"
              value={claim.policy_start_date}
              onChange={set("policy_start_date")}
              className="w-full border border-rule bg-paper px-3 py-3 font-doc text-base"
            />
          </Field>
          <Field label="Date of admission" id="admission">
            <input
              id="admission"
              type="date"
              value={claim.admission_date}
              onChange={set("admission_date")}
              className="w-full border border-rule bg-paper px-3 py-3 font-doc text-base"
            />
          </Field>
        </div>
      </section>

      <details className="mt-4 border border-rule-soft bg-card">
        <summary className="cursor-pointer px-5 py-4 font-doc text-lg text-ink-2">
          Add the treatment and the amount claimed
        </summary>
        <div className="grid gap-5 border-t border-rule-soft px-5 py-5 sm:grid-cols-2">
          <Field label="Treatment" id="treatment">
            <input
              id="treatment"
              value={claim.treatment}
              onChange={set("treatment")}
              placeholder="Angioplasty"
              className="w-full border border-rule bg-paper px-3 py-3 font-doc text-base"
            />
          </Field>
          <Field label="Amount claimed" id="amount">
            <input
              id="amount"
              type="number"
              inputMode="numeric"
              value={claim.amount}
              onChange={set("amount")}
              placeholder="285000"
              className="w-full border border-rule bg-paper px-3 py-3 font-doc text-base"
            />
          </Field>
          <p className="font-doc text-base text-ink-soft sm:col-span-2">
            These sharpen how the answer is written. They do not decide it —
            the dates above are what a waiting period turns on.
          </p>
        </div>
      </details>

      <div className="mt-8 flex flex-wrap items-center gap-4">
        <button
          onClick={submit}
          disabled={!policy}
          aria-describedby={held ? "dates-warning" : undefined}
          className="border border-ink bg-ink px-7 py-4 font-doc text-lg font-semibold text-paper transition-colors hover:bg-ink-2 disabled:cursor-not-allowed disabled:opacity-35"
        >
          {held ? "Check it anyway" : "Check the rejection"}
        </button>
        <button
          onClick={onBack}
          className="font-doc text-lg text-ink-2 underline hover:text-ink"
        >
          Back to the letter
        </button>
        {!policy && (
          <span className="font-doc text-base text-ink-soft">
            Choose your insurer to continue.
          </span>
        )}
      </div>

      {/* Below the button, deliberately. Anything inserted above it shifts the
          control out from under a thumb that is already resting there. The
          label changes in place instead, so the second press is a decision
          rather than a mis-tap. */}
      {held && (
        <div
          id="dates-warning"
          role="alert"
          className="mt-4 max-w-[62ch] border-l-[3px] border-ochre bg-ochre-tint px-5 py-4"
        >
          <p className="folio text-ochre">Without the dates</p>
          <p className="mt-2 font-doc text-base leading-relaxed text-ink">
            You have not given {missing.join(" or ")}. We cannot work out how
            long you had been covered by the time you were admitted, and a
            waiting period turns on exactly that — so the answer will most
            likely come back as not enough to judge.
          </p>
          <p className="mt-2 font-doc text-base leading-relaxed text-ink-2">
            Add them above, or press the button again to go ahead without them.
          </p>
        </div>
      )}

      {/* Plain text, and below the control. As a collapsed row between the
          cards and the button this read as a third thing to weigh up before
          pressing anything, when it is an exit for the few people we cannot
          help. */}
      <section className="mt-10 border-t border-rule-soft pt-5">
        <h2 className="folio text-ink-soft">None of these is my insurer</h2>
        <p className="mt-2 max-w-[62ch] font-doc text-base leading-relaxed text-ink-2">
          Then we cannot check this rejection yet. We hold only the six
          wordings above, and guessing against a policy that is not yours would
          produce a confident answer about the wrong document — which is worse
          than no answer. The{" "}
          <Link to="/bill" className="text-ink underline">
            hospital bill checker
          </Link>{" "}
          does not need your policy: it works against the IRDAI list, which is
          the same for every insurer in India.
        </p>
      </section>
    </div>
  );
}

/* min-w-0: a grid child defaults to min-width:auto, and a date input's
   intrinsic width is set by the widget the browser draws rather than by us.
   Without this it can refuse to shrink and push the two-column track wide. */
function Field({ label, id, children }) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="folio mb-2 block text-ink-soft">
        {label}
      </label>
      {children}
    </div>
  );
}

/* ---------------------------------------------------------- step three */

function WaitingStep({ letter, policy, stage }) {
  return (
    <div className="lg:grid lg:grid-cols-12 lg:gap-12">
      <div className="lg:col-span-5">
        <h1 className="font-doc text-3xl leading-tight font-semibold text-balance sm:text-4xl">
          Reading your policy.
        </h1>
        <p className="mt-3 max-w-[46ch] font-doc text-lg leading-relaxed text-ink-2">
          This takes about half a minute. Three readings are made of the same
          clauses — the insurer's, yours, and a neutral one — and then they are
          weighed against each other.
        </p>

        {/* Named stages rather than a spinner. Half a minute of undifferen-
            tiated waiting reads as broken; these are honest, and they are the
            order the work actually happens in. */}
        <ol className="mt-8 space-y-0">
          {STAGES.map((s, i) => {
            const state = i < stage ? "done" : i === stage ? "now" : "todo";
            return (
              <li
                key={s}
                aria-current={state === "now" ? "step" : undefined}
                className={
                  "flex items-baseline gap-3 border-b border-rule-soft py-3 font-doc text-lg " +
                  (state === "now"
                    ? "text-ink"
                    : state === "done"
                      ? "text-ink-soft"
                      : "text-rule")
                }
              >
                <span aria-hidden="true" className="font-quote text-sm">
                  {state === "done" ? "●" : state === "now" ? "▸" : "○"}
                </span>
                <span>{s}</span>
              </li>
            );
          })}
        </ol>
      </div>

      {/* Their document, on screen, being worked on. The wait should look
          like labour applied to the thing they handed over. */}
      <div className="mt-10 lg:col-span-6 lg:col-start-7 lg:mt-0">
        <div className="border-t-[3px] border-ink bg-card">
          <div className="flex items-baseline justify-between border-b border-rule-soft px-5 py-3">
            <span className="folio text-ink">Your letter</span>
            {policy && (
              <span className="folio text-ink-soft">{policy.insurer}</span>
            )}
          </div>
          <p className="wrap-verbatim max-h-[22rem] overflow-hidden px-5 py-5 font-quote text-[0.8125rem] leading-[1.8] whitespace-pre-wrap text-ink-verbatim">
            {letter.slice(0, 900)}
            {letter.length > 900 ? "…" : ""}
          </p>
        </div>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------- step four */

function Finding({ result, policy, letter, policies = [] }) {
  const v = VERDICT[result.verdict] || VERDICT.insufficient_information;
  const clauses = result.deciding_clauses || [];
  const noClauses = clauses.length === 0;
  const mismatch = insurerMismatch(letter, policy, policies);

  return (
    <div>
      {/*
        Above the verdict, because it changes what the verdict means. It warns
        and never blocks: a letter can legitimately name another insurer, the
        reader may have chosen deliberately, and the finding below is still a
        true statement about the policy they picked.

        Ink rather than ochre. Ochre means "go and check this" and the theme
        allows it once per screen; what_would_change_it already has it, and
        two would dilute both. This sits first on the page and does not need
        colour to be read.
      */}
      {mismatch && (
        <section className="mb-8 border-l-[3px] border-ink bg-paper-sunk px-5 py-4">
          <p className="folio text-ink-soft">Check this first</p>
          <p className="mt-2 max-w-[62ch] font-doc text-lg leading-relaxed text-ink">
            Your letter mentions{" "}
            <strong className="font-semibold">{mismatch.named.join(" and ")}</strong>
            , but you chose{" "}
            <strong className="font-semibold">
              {policy.insurer} {policy.policy_name}
            </strong>
            . Everything below is read from the wording of the policy you
            chose.
          </p>
          <p className="mt-2 max-w-[62ch] font-doc text-base leading-relaxed text-ink-2">
            If that is the wrong policy, the finding is about the wrong
            document — go back and pick again. If it is right, and the letter
            simply refers to a previous insurer, you can ignore this.
          </p>
        </section>
      )}

      <Arrive>
        <section className={"px-5 py-8 sm:px-8 sm:py-10 " + v.band}>
          <p className="folio opacity-70">The finding</p>
          <h1 className="mt-3 max-w-[20ch] font-doc text-3xl leading-tight font-semibold text-balance sm:text-4xl lg:text-5xl">
            {v.headline}
          </h1>
          <p className="mt-3 max-w-[52ch] font-doc text-lg leading-relaxed opacity-90">
            {v.sub}
          </p>
        </section>
      </Arrive>

      {/* Desktop is not a stretched phone. The reasoning and the one thing
          worth checking sit side by side at the top, because they are read
          together and neither needs the full measure. The exhibit then takes
          the whole width on its own, folio in the true margin and text capped
          to a readable measure — it is the evidence, and it gets the boldness
          while everything around it stays quiet. */}
      <div className="mt-8 lg:grid lg:grid-cols-12 lg:gap-12">
        <div className="lg:col-span-7">
          <h2 className="folio text-ink-soft">Why</h2>
          <p className="mt-3 font-doc text-lg leading-relaxed text-ink">
            {result.explanation}
          </p>

          {/* The clause count stands on its own when the score is withheld:
              it is a fact about what was searched, not a claim about the
              answer, and it is true on every verdict. */}
          {((v.scored && typeof result.confidence === "number") ||
            result.considered_count > 0) && (
            <p className="mt-4 font-doc text-base text-ink-soft">
              {v.scored && typeof result.confidence === "number" && (
                <>
                  Confidence in this reading:{" "}
                  <span className="font-quote">
                    {Math.round(result.confidence * 100)}%
                  </span>
                  .{" "}
                </>
              )}
              {result.considered_count > 0 && (
                <>
                  {result.considered_count} clauses from your policy were read
                  before settling on the one below.
                </>
              )}
            </p>
          )}
        </div>

        {result.what_would_change_it && (
          <div className="mt-6 lg:col-span-5 lg:mt-0">
            <div className="border-l-[3px] border-ochre bg-ochre-tint px-5 py-4">
              <p className="folio text-ochre">Go and check this</p>
              <p className="mt-2 font-doc text-lg leading-relaxed text-ink">
                {result.what_would_change_it}
              </p>
            </div>
          </div>
        )}
      </div>

      <div className="mt-10">
        {noClauses ? (
          <NoClause policy={policy} explanation={result.explanation} />
        ) : (
          <>
            <h2 className="folio mb-3 text-ink-soft">
              {clauses.length > 1
                ? "The clauses this turns on"
                : "The clause this turns on"}
            </h2>
            <div className="space-y-8">
              {clauses.map((c, i) => (
                <Exhibit
                  key={c.clause_id || i}
                  title={c.clause_title || "Untitled clause"}
                  page={c.source_page}
                  source={c.insurer}
                  text={c.clause_text}
                  meta={[
                    c.exclusion_code,
                    c.waiting_period_days
                      ? `${c.waiting_period_days} day wait`
                      : null,
                    c.monetary_cap ? `cap ${rupees(c.monetary_cap)}` : null,
                    c.percent_cap ? `${c.percent_cap}%` : null,
                  ].filter(Boolean)}
                />
              ))}
            </div>
          </>
        )}
      </div>

      {result.arguments &&
        (result.arguments.insurer_position ||
          result.arguments.claimant_position) && (
          <section className="no-print mt-12">
            <h2 className="folio text-ink-soft">How each side would argue it</h2>
            <div className="mt-4 grid gap-4 md:grid-cols-2 md:gap-6">
              {/* Oxblood appears here and nowhere else in the product: it
                  marks the insurer's position, so the adversary is visibly
                  the adversary and your own case is set in plain ink. */}
              <Side
                heading="The insurer's case"
                accent="border-insurer"
                body={result.arguments.insurer_position}
                weak={result.arguments.insurer_weak_point}
              />
              <Side
                heading="Your case"
                accent="border-ink"
                body={result.arguments.claimant_position}
                weak={result.arguments.claimant_weak_point}
              />
            </div>
          </section>
        )}

      <Appeal result={result} />
    </div>
  );
}

function Side({ heading, accent, body, weak }) {
  return (
    <article className={"border-t-[3px] bg-card p-5 sm:p-6 " + accent}>
      <h3 className="folio text-ink-soft">{heading}</h3>
      <p className="mt-3 font-doc text-lg leading-relaxed text-ink">{body}</p>
      {weak && (
        <p className="mt-4 border-t border-rule-soft pt-3 font-doc text-base leading-relaxed text-ink-soft">
          <span className="folio mb-1 block text-ink-soft">Weak spot</span>
          {weak}
        </p>
      )}
    </article>
  );
}

/*
  The no-clause case, designed rather than left as an empty container. It
  happens when retrieval finds nothing for the policy, and the honest thing
  is to say what was and was not checked.
*/
function NoClause({ policy, explanation }) {
  return (
    <section className="border-t-[3px] border-ink-soft bg-card px-5 py-6 sm:px-6">
      <h2 className="folio text-ink-soft">No clause to show</h2>
      <p className="mt-3 font-doc text-lg leading-relaxed text-ink">
        {explanation ||
          "We could not find wording in this policy that addresses the reason given."}
      </p>
      <p className="mt-4 font-doc text-base leading-relaxed text-ink-2">
        This is not a finding in your favour, and it is not one against you. It
        means the wording we hold for{" "}
        {policy ? `${policy.insurer} ${policy.policy_name}` : "this policy"}{" "}
        does not clearly cover the reason they gave. Two things are worth
        doing: check you chose the right policy, and ask the insurer in writing
        which clause number they are relying on. They are obliged to tell you.
      </p>
    </section>
  );
}

/*
  The letter.

  There is always one, but it is not always an appeal. When the wording
  supports the insurer, an appeal would be a hopeless one and offering it
  would be dishonest — so the action changes instead of disappearing, and the
  copy says plainly which letter this is and what it does. The reader who has
  just been told the rejection holds up is the one who most needs a next step.
*/
const LETTER = {
  appeal: {
    heading: "Put it to them in writing",
    blurb:
      "A short letter to the grievance officer, quoting the clause exactly " +
      "as printed. You can send it as it is, or use it as a starting point.",
    cta: "Draft the appeal",
    drafting: "Drafting the appeal…",
    label: "Draft appeal",
  },
  substantiate: {
    heading: "Make them prove it",
    blurb:
      "The wording is on their side, so an appeal would not get far — but " +
      "they have asserted something they have not yet evidenced. This letter " +
      "asks them to produce that evidence in writing, and to confirm the " +
      "clause and page they are relying on. It does not ask them to pay.",
    cta: "Draft the letter",
    drafting: "Drafting the letter…",
    label: "Draft letter",
  },
};

function Appeal({ result }) {
  const [letter, setLetter] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState(null);

  if (!result.appeal_available && !letter) return null;

  // Which letter this is, and therefore what it is honestly called.
  const kind = letter?.letter_type || result.letter_type || "appeal";
  const copyFor = LETTER[kind] || LETTER.appeal;

  async function draft() {
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
    <section className="mt-12">
      {err && (
        <div className="mb-4 border-l-[3px] border-insurer bg-card px-5 py-4 font-doc text-base">
          {err}
        </div>
      )}

      {!letter ? (
        <div className="no-print border border-rule bg-card p-5 sm:p-6">
          <h2 className="font-doc text-2xl leading-tight font-semibold">
            {copyFor.heading}
          </h2>
          <p className="mt-2 max-w-[62ch] font-doc text-lg leading-relaxed text-ink-2">
            {copyFor.blurb}
          </p>
          <button
            onClick={draft}
            disabled={busy}
            className="mt-5 border border-ink bg-ink px-7 py-4 font-doc text-lg font-semibold text-paper transition-colors hover:bg-ink-2 disabled:opacity-40"
          >
            {busy ? copyFor.drafting : copyFor.cta}
          </button>
        </div>
      ) : (
        <Arrive>
          <h2 className="folio text-ink-soft">{copyFor.label}</h2>
          {!letter.quotes_verified && (
            <p className="mt-3 border-l-[3px] border-ochre bg-ochre-tint px-5 py-4 font-doc text-base leading-relaxed">
              Part of the draft quoted wording that could not be matched to the
              policy, so it was withheld. What remains is safe to send.
            </p>
          )}
          <div className="wrap-verbatim mt-3 border border-rule bg-card px-5 py-6 font-quote text-[0.8125rem] leading-[1.85] whitespace-pre-wrap text-ink-verbatim">
            {letter.letter_text}
          </div>
          <div className="no-print mt-4 flex flex-wrap gap-3">
            <button
              onClick={copy}
              className="border border-ink px-6 py-3 font-doc text-base font-semibold text-ink transition-colors hover:bg-paper-sunk"
            >
              {copied ? "Copied" : "Copy letter"}
            </button>
            <button
              onClick={() => window.print()}
              className="border border-rule px-6 py-3 font-doc text-base text-ink-2 transition-colors hover:border-ink"
            >
              Print
            </button>
          </div>
        </Arrive>
      )}
    </section>
  );
}
