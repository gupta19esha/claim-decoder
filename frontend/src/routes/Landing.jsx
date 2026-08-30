import { Link } from "react-router-dom";
import Exhibit from "../components/Exhibit.jsx";
import { Settle, DrawnRule } from "../components/motion.jsx";

/*
  The landing page has one job: make someone believe a rejection is worth
  questioning. Our own research, n=8, is that the blocker is belief and
  effort, not comprehension — four of six let it go, and three found the
  relevant clause themselves and still gave up.

  So this is written as a public notice rather than as marketing. Flat blocks,
  large plain statements, and evidence in the form of figures that can be
  checked. It is the only part of the product set in a sans, which is
  deliberate: a notice pasted on the front of a document.

  EVERY NUMBER ON THIS PAGE IS TRUE AND MODEST.

  There is no "70% of claims are wrongly rejected" here, because we do not
  know that. The persuasion is the mechanism, not a statistic: an insurer must
  point to a rule, the rule is written down, and you can read it. The one
  place we could overclaim is coverage, so the six-policy limit is stated in
  the evidence band, above the fold on desktop and before any input on mobile.
*/

// Verbatim, from ICICI Lombard Elevate page 83, as held in the corpus. Shown
// as a sample of what the tool returns. Not paraphrased, not shortened.
const SAMPLE_CLAUSE =
  "Treatment of a Pre-existing Disease and its direct complications, until " +
  "the expiry of 36 months of continuous coverage after the date of " +
  "inception of the first Policy with Us. a. In case of enhancement of the " +
  "Sum Insured, this exclusion shall apply afresh to the extent of Sum " +
  "Insured increased. b. If You are continuously covered without any Break " +
  "in Policy, then the waiting period for the same would be reduced to the " +
  "extent of prior coverage, subject to the IRDAI norms on portability and " +
  "migration. c. Coverage under the Policy after the expiry of 36 months " +
  "for any Pre-existing Disease is subject to the same being declared at " +
  "the time of application and accepted by Us.";

const FIGURES = [
  { n: "965", label: "clauses held", sub: "read from the policy wordings" },
  { n: "6", label: "policies", sub: "five insurers. That is all we hold" },
  { n: "146", label: "IRDAI items", sub: "a hospital may not bill to a claim" },
];

const STEPS = [
  {
    n: "01",
    h: "Paste what they sent you",
    p: "The rejection letter or the SMS. Word for word — the wording is what matters, not a summary.",
  },
  {
    n: "02",
    h: "Tell us which policy",
    p: "After you have pasted, not before. You do not need the policy document, only the insurer's name.",
  },
  {
    n: "03",
    h: "Read the clause yourself",
    p: "You get the exact wording they are relying on, and the page number to find it on. Verify it. That is the point.",
  },
];

export default function Landing() {
  return (
    <div className="min-h-screen bg-paper">
      <header className="border-b border-rule">
        <div className="mx-auto flex max-w-6xl items-baseline justify-between px-5 py-4 sm:px-8">
          <span className="font-doc text-lg font-semibold tracking-tight">
            Claim Decoder
          </span>
          <span className="folio text-ink-soft">India</span>
        </div>
      </header>

      {/* ---------------------------------------------------- the premise */}
      <section className="bg-contest text-paper">
        <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24 lg:py-32">
          {/* Deliberately not animated. This is the first thing a stressed
              person sees, and it must be on the screen the instant the page
              paints — never waiting on a frame loop that a slow phone, a
              background tab or a throttled renderer might not run. Motion
              below the fold is safe because the reader is scrolling, so the
              tab is demonstrably alive. */}
          <p className="folio mb-8 text-paper/70">If your claim was rejected</p>
          <h1 className="max-w-[16ch] font-notice text-[2.5rem] leading-[1.02] font-medium tracking-[-0.03em] text-balance sm:text-6xl lg:text-[5.25rem]">
            A rejection has to point to a rule.
          </h1>
          <p className="mt-8 max-w-[30ch] font-notice text-2xl leading-tight font-normal text-paper/85 sm:mt-10 sm:text-3xl lg:max-w-[34ch] lg:text-4xl">
            The rule is written down, in a document you are entitled to read.
          </p>

          {/* Both routes sit above the fold. Someone who arrives already
              convinced should not have to scroll past an argument to find the
              way in — the persuasion below is for the undecided, not a toll
              gate everyone pays. */}
          <div className="mt-10 flex flex-col gap-3 sm:mt-12 sm:flex-row sm:gap-4">
            <Link
              to="/rejection"
              className="group flex items-baseline justify-between gap-6 border border-paper bg-paper px-6 py-5 text-ink transition-colors hover:bg-white sm:flex-1 sm:px-7"
            >
              <span className="font-doc text-xl leading-tight font-semibold sm:text-2xl">
                My claim was rejected
              </span>
              <span aria-hidden="true" className="font-notice text-xl transition-transform group-hover:translate-x-1">
                &rarr;
              </span>
            </Link>
            <Link
              to="/bill"
              className="group flex items-baseline justify-between gap-6 border border-paper/50 px-6 py-5 text-paper transition-colors hover:border-paper hover:bg-white/5 sm:flex-1 sm:px-7"
            >
              <span className="font-doc text-xl leading-tight font-semibold sm:text-2xl">
                Check my hospital bill
              </span>
              <span aria-hidden="true" className="font-notice text-xl transition-transform group-hover:translate-x-1">
                &rarr;
              </span>
            </Link>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------ the offer */}
      <section className="mx-auto max-w-6xl px-5 py-14 sm:px-8 sm:py-20">
        <div className="lg:grid lg:grid-cols-12 lg:gap-12">
          <Settle className="lg:col-span-5">
            <h2 className="font-doc text-2xl leading-snug font-semibold text-balance sm:text-3xl">
              This shows you the wording, not our opinion of it.
            </h2>
          </Settle>
          <Settle delay={0.06} className="mt-5 lg:col-span-6 lg:col-start-7 lg:mt-0">
            <p className="font-doc text-lg leading-relaxed text-ink-2 sm:text-xl">
              Paste what the insurer sent you. You get back the clause they are
              relying on, quoted exactly, with the page number in your policy
              where you can check it. If the wording does not support what they
              did, you will see that too — and you can take the page to them.
            </p>
          </Settle>
        </div>

      </section>

      {/* --------------------------------------------------- the evidence */}
      <section className="border-y border-rule bg-paper-sunk">
        <div className="mx-auto max-w-6xl px-5 py-12 sm:px-8 sm:py-16">
          <Settle as="h2" className="folio text-ink-soft">
            What we actually hold
          </Settle>
          <dl className="mt-8 grid grid-cols-1 gap-8 sm:grid-cols-3 sm:gap-6">
            {FIGURES.map((f, i) => (
              <Settle key={f.label} delay={i * 0.06}>
                <dt className="font-notice text-5xl leading-none font-medium tracking-tight tabular-nums sm:text-6xl">
                  {f.n}
                </dt>
                <dd className="mt-3">
                  <span className="font-doc text-lg font-semibold">
                    {f.label}
                  </span>
                  <span className="mt-1 block font-doc text-base text-ink-soft">
                    {f.sub}
                  </span>
                </dd>
              </Settle>
            ))}
          </dl>

          {/* Stated before anyone types, not after they fail at submit. */}
          <Settle
            delay={0.2}
            className="mt-10 border-l-[3px] border-ochre bg-ochre-tint px-5 py-4 sm:mt-12"
          >
            <p className="font-doc text-base leading-relaxed text-ink sm:text-lg">
              <strong className="font-semibold">
                Six policies is all we hold today.
              </strong>{" "}
              ICICI Lombard Elevate, HDFC Ergo Optima Secure, Niva Bupa
              ReAssure and ReAssure 3.0, Tata AIG Medicare Select, Star Health
              Arogya Sanjeevani. If yours is not one of those, the rejection
              decoder cannot check it yet. The bill checker works for everyone.
            </p>
          </Settle>
        </div>
      </section>

      {/* ------------------------------------------------------ the steps */}
      <section className="mx-auto max-w-6xl px-5 py-14 sm:px-8 sm:py-20">
        <Settle as="h2" className="folio text-ink-soft">
          How it goes
        </Settle>
        <ol className="mt-8 grid gap-10 sm:gap-8 lg:grid-cols-3 lg:gap-12">
          {STEPS.map((s, i) => (
            <Settle as="li" key={s.n} delay={i * 0.06}>
              <DrawnRule className="mb-5" />
              <span className="folio text-ink-soft tabular-nums">{s.n}</span>
              <h3 className="mt-3 font-doc text-xl leading-snug font-semibold sm:text-2xl">
                {s.h}
              </h3>
              <p className="mt-2 max-w-[42ch] font-doc text-base leading-relaxed text-ink-2">
                {s.p}
              </p>
            </Settle>
          ))}
        </ol>
      </section>

      {/* ------------------------------------------------- the exhibit */}
      <section className="border-t border-rule bg-card">
        <div className="mx-auto max-w-6xl px-5 py-14 sm:px-8 sm:py-20">
          <div className="lg:grid lg:grid-cols-12 lg:gap-12">
            <Settle className="lg:col-span-4">
              <h2 className="font-doc text-2xl leading-snug font-semibold text-balance sm:text-3xl">
                This is what you get back.
              </h2>
              <p className="mt-4 max-w-[38ch] font-doc text-base leading-relaxed text-ink-2 sm:text-lg">
                Not a summary. The clause itself, as printed, with the page it
                sits on. Print it and hand it to a grievance officer — it is
                built to survive a photocopier.
              </p>
              <p className="mt-4 font-doc text-sm text-ink-soft">
                Example below: the pre-existing disease exclusion from ICICI
                Lombard Elevate.
              </p>
            </Settle>

            <Settle delay={0.08} className="mt-8 lg:col-span-7 lg:col-start-6 lg:mt-0">
              <Exhibit
                title="Pre-Existing Diseases"
                page={83}
                source="ICICI Lombard Elevate"
                text={SAMPLE_CLAUSE}
                meta={["Excl01", "1080 day wait"]}
                note="Quoted word for word from the policy wording. In the tool, this is the clause your insurer is relying on."
              />
            </Settle>
          </div>
        </div>
      </section>

      {/* --------------------------------------------------------- close */}
      <section className="border-t border-rule">
        <div className="mx-auto max-w-6xl px-5 py-14 sm:px-8 sm:py-20">
          <Settle
            as="h2"
            className="max-w-[20ch] font-notice text-3xl leading-[1.08] font-medium tracking-[-0.02em] text-balance sm:text-5xl lg:text-6xl"
          >
            Three people we spoke to found the clause themselves, and still let
            it go.
          </Settle>
          <Settle
            as="p"
            delay={0.06}
            className="mt-6 max-w-[52ch] font-doc text-lg leading-relaxed text-ink-2 sm:text-xl"
          >
            Understanding the clause was never the hard part. Believing it was
            worth the effort was. If the wording does not support what they
            did, that is worth ten minutes of your day.
          </Settle>
          <Settle delay={0.12} className="mt-10">
            <Link
              to="/rejection"
              className="inline-block border border-ink bg-ink px-7 py-4 font-doc text-lg font-semibold text-paper transition-colors hover:bg-ink-2"
            >
              Check a rejection
            </Link>
          </Settle>
        </div>
      </section>

      <footer className="border-t border-rule">
        <div className="mx-auto max-w-6xl px-5 py-8 font-doc text-sm leading-relaxed text-ink-soft sm:px-8">
          Clause text is quoted directly from the insurer's published policy
          wording. Item names are quoted from the IRDAI non-payable lists. This
          is not legal advice, and we are not a broker or an insurer.
        </div>
      </footer>
    </div>
  );
}
