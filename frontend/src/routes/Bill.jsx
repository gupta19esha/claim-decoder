import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { auditBill } from "../api";
import Shell from "../components/Shell.jsx";
import { Arrive } from "../components/motion.jsx";

/*
  The hospital bill checker.

  THE FOUR IRDAI LISTS ARE TWO ARGUMENTS, NOT FOUR LABELS.

  The previous build printed the category description and left the reader to
  work out what it meant. But "never payable" and "already inside the room
  charge" are different things to say to a hospital billing desk:

    List I           the hospital should not have billed this at all. Ask for
                     it to be struck off.
    Lists II-IV      you have been charged twice. The item is already inside
                     a charge you have paid — the room charge, the procedure
                     charge, or the cost of treatment. Ask for it to be
                     folded back into that charge.

  So the findings are grouped by argument first and by which charge second,
  never-payable leads, and each group carries the sentence the claimant can
  actually use. That is the teaching: not what the list is called, but what
  it lets you say.

  Item names are quoted from the corpus and never paraphrased, exactly as
  clause text is in the decoder. The quotation is the product.
*/

const rupees = (n) =>
  n === null || n === undefined
    ? null
    : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

/* A figure needs its denominator. Rs 6,670 against a bill of Rs 1,13,770 is
   a different fact from Rs 6,670 against Rs 15,000. */
const pct = (share) =>
  typeof share === "number" ? `${(share * 100).toFixed(1)}%` : "part";

/* The billed line and the IRDAI item often carry the same words. */
const same = (f) =>
  (f.description || "").trim().toUpperCase() ===
  (f.item_name || "").trim().toUpperCase();

const SUBSUME = {
  subsume_room: "the room charge",
  subsume_procedure: "the procedure charge",
  subsume_treatment: "the cost of treatment",
};

const SAMPLE = `ROOM RENT - SINGLE PRIVATE (4 DAYS)   24000.00
SURGEON CHARGES   45000.00
GLOVES   450.00
BABY FOOD   320.00
ATTENDANT CHARGES   2400.00
X-RAY FILM   800.00
AIR CONDITIONER CHARGES   3000.00
TELEPHONE CHARGES   150.00
ICU CHARGES (2 DAYS)   30000.00
MEDICINES AND DRUGS   18500.00`;

export default function Bill() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);

  /*
    The findings replace the paste screen, and the browser keeps the scroll
    offset across the swap — press the button from the foot of a long
    pasted bill and the total you were just told about is above you, off
    the top of the screen. Same defect as the step change in the rejection
    decoder, same instant fix, and it has to run on the reset too.
  */
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [result]);

  async function readFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    try {
      // Read in the browser, not uploaded. Nothing about the bill reaches a
      // server until the reader presses the button, and a bill is health data.
      setText(await file.text());
    } catch {
      setError("That file could not be read. Paste the bill text instead.");
    }
    e.target.value = "";
  }

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await auditBill(text));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const foot =
    "Item names are quoted directly from the IRDAI non-payable lists. This is not legal advice.";

  return (
    <Shell
      steps={["The bill", "What was checked"]}
      current={result ? 1 : 0}
      foot={foot}
    >
      {error && (
        <div
          role="alert"
          className="mb-8 border-l-[3px] border-insurer bg-card px-5 py-4 font-doc text-body"
        >
          <strong className="font-semibold">Something went wrong.</strong>{" "}
          {error}
        </div>
      )}

      {result ? (
        <Findings
          result={result}
          /* The band runs flush to the step rule, which means pulling it up
             over Shell's own top padding — so it must not do that when the
             error banner is above it. */
          flush={!error}
          onReset={() => {
            setResult(null);
            setText("");
          }}
        />
      ) : (
        <Paste
          text={text}
          setText={setText}
          busy={busy}
          run={run}
          fileRef={fileRef}
          readFile={readFile}
        />
      )}
    </Shell>
  );
}

/* ------------------------------------------------------------ the bill */

function Paste({ text, setText, busy, run, fileRef, readFile }) {
  return (
    <div className="lg:grid lg:grid-cols-12 lg:gap-12">
      <div className="lg:col-span-7">
        <h1 className="font-doc text-screen font-semibold text-balance lg:text-screen-lg">
          What did the hospital charge you?
        </h1>
        <p className="mt-4 max-w-[54ch] font-doc text-lead text-ink-2 lg:text-lead-lg">
          Paste the itemised bill, one line per item, with the amount at the
          end of the line. We check every line against the 146 items the IRDAI
          says a hospital may not bill to a claim.
        </p>

        {/* The scope limit, plainly, before the check runs. Stated again with
            the result. A checker that silently skips the largest deduction on
            most bills would be read as having checked it. */}
        <p className="mt-4 max-w-[54ch] font-doc text-body text-ink">
          <strong className="font-semibold">Room rent is not checked.</strong>{" "}
          Your room limit is set in your Policy Schedule, not in the policy
          wording, so there is nothing generic to check it against.
        </p>

        <label htmlFor="bill" className="sr-only">
          The itemised bill
        </label>
        {/* 16px on a phone. Below that mobile Safari zooms the viewport
            on focus and leaves it zoomed. Same rule as the letter textarea
            in Rejection.jsx, same reason; the designed 14px mono returns
            at sm:. */}
        <textarea
          id="bill"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={12}
          placeholder={"GLOVES   450.00\nBABY FOOD   320.00\nATTENDANT CHARGES   2400.00"}
          className="mt-6 w-full border border-rule bg-card px-4 py-4 font-quote text-base leading-relaxed text-ink placeholder:text-ink-soft/60 focus:border-ink sm:text-[0.875rem]"
        />

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button
            onClick={run}
            disabled={text.trim().length < 10 || busy}
            className="border border-ink bg-ink px-7 py-4 font-doc text-lead font-semibold text-paper transition-colors hover:bg-ink-2 disabled:cursor-not-allowed disabled:opacity-35"
          >
            {busy ? "Checking…" : "Check the bill"}
          </button>
          <button
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            className="border border-rule px-6 py-4 font-doc text-body text-ink-2 transition-colors hover:border-ink"
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
          {!text && (
            <button
              onClick={() => setText(SAMPLE)}
              className="font-doc text-aside text-ink-soft underline hover:text-ink"
            >
              Use an example bill
            </button>
          )}
        </div>
      </div>

      <aside className="mt-10 lg:col-span-4 lg:col-start-9 lg:mt-0">
        <h2 className="folio text-ink-soft">What this checks</h2>
        <p className="mt-3 font-doc text-body text-ink-2">
          The IRDAI publishes four lists of items a hospital may not charge to
          your claim. They are the same for every insurer in India, so this
          works whoever you are with, and you do not need your policy.
        </p>
        <p className="mt-3 font-doc text-body text-ink-2">
          It does not check sub-limits, deductibles, or whether the treatment
          itself was covered. If your claim was refused outright, the{" "}
          <Link to="/rejection" className="text-ink underline">
            rejection decoder
          </Link>{" "}
          is the other half of this.
        </p>
        <p className="mt-3 font-doc text-aside text-ink-soft">
          Your bill is sent to be checked and not stored. A file you choose is
          read in this browser, not uploaded.
        </p>
      </aside>
    </div>
  );
}

/* --------------------------------------------------------- the findings */

function Findings({ result, onReset, flush = true }) {
  const findings = result.findings || [];
  const never = findings.filter((f) => f.category === "not_payable");
  const twice = findings.filter((f) => f.category !== "not_payable");

  const sum = (rows) =>
    rows.reduce((t, f) => t + (typeof f.amount === "number" ? f.amount : 0), 0);

  if (findings.length === 0)
    return <NothingFlagged result={result} onReset={onReset} flush={flush} />;

  const byCharge = Object.keys(SUBSUME)
    .map((k) => ({ key: k, rows: twice.filter((f) => f.category === k) }))
    .filter((g) => g.rows.length > 0);

  return (
    <div>
      {/* Calm authority, not celebration. The reader is stressed and possibly
          ill; a number this size deserves a plain statement. */}
      {/*
        THE ONE MOMENT ON THIS SCREEN, AND IT IS THE NUMBER.

        It used to be buried mid-sentence in a headline — "Rs 3,170 on this
        bill should not have been charged to your claim" — so the thing the
        reader came for was a fragment of a paragraph. Split: the amount alone
        at verdict scale, the sentence beneath it at lead.

        Big and quiet. No celebration, no exclamation, nothing that treats a
        hospital bill as a win. Someone reading this is unwell or looking
        after someone who is.
      */}
      <section
        className={
          "-mx-5 bg-contest px-5 py-14 text-paper sm:-mx-8 sm:px-8 sm:py-16 lg:py-24 " +
          (flush ? "-mt-8 sm:-mt-12" : "")
        }
      >
        <p className="folio opacity-60">What was checked</p>
        <p className="mt-6 font-doc text-verdict font-medium tabular-nums lg:mt-8 lg:text-verdict-lg">
          {rupees(result.flagged_total)}
        </p>
        <h1 className="mt-6 max-w-[26ch] font-doc text-lead font-normal text-balance opacity-90 lg:mt-8 lg:text-lead-lg">
          on this bill should not have been charged to your claim.
        </h1>
        <p className="mt-6 max-w-[58ch] font-doc text-body opacity-75">
            {result.lines_flagged} of {result.lines_read} lines matched the
            IRDAI lists.
            {typeof result.bill_total === "number" && result.bill_total > 0 && (
              <>
                {" "}
                That is {pct(result.flagged_share)} of a bill totalling{" "}
                {rupees(result.bill_total)}.
              </>
            )}
          {result.findings_without_amount > 0 &&
            ` ${result.findings_without_amount} matched but had no readable amount, so they are not in this total.`}
        </p>
      </section>

      {never.length > 0 && (
        <Group
          heading="Should never have been charged"
          argument="These are on the IRDAI's list of items no hospital may bill to a claim, whoever your insurer is. Ask the billing desk to strike them off."
          total={sum(never)}
          rows={never}
        />
      )}

      {twice.length > 0 && (
        <section className="mt-12">
          <h2 className="font-doc text-section font-semibold lg:text-section-lg">
            Charged to you twice
          </h2>
          <p className="mt-2 max-w-[62ch] font-doc text-body text-ink-2">
            These are not forbidden in themselves. They are already inside a
            charge you have paid, so billing them again as separate lines
            charges you for the same thing twice. Ask for each to be folded
            back into the charge it belongs to.
          </p>
          <p className="mt-2 font-doc text-aside text-ink-soft">
            {rupees(sum(twice))} across {twice.length} line
            {twice.length === 1 ? "" : "s"}.
          </p>

          {byCharge.map((g) => (
            <Group
              key={g.key}
              nested
              heading={`Already inside ${SUBSUME[g.key]}`}
              argument={`Each line below is part of ${SUBSUME[g.key]} you have already been billed for.`}
              total={sum(g.rows)}
              rows={g.rows}
            />
          ))}
        </section>
      )}

      <NotFlagged rows={result.not_flagged || []} />

      <BillLetter result={result} />

      <ScopeNote reason={result.checks?.room_rent_reason} />

      <div className="no-print mt-10 flex flex-wrap gap-3">
        <button
          onClick={() => window.print()}
          className="border border-ink px-6 py-3 font-doc text-base font-semibold text-ink transition-colors hover:bg-paper-sunk"
        >
          Print this
        </button>
        <button
          onClick={onReset}
          className="border border-rule px-6 py-3 font-doc text-base text-ink-2 transition-colors hover:border-ink"
        >
          Check another bill
        </button>
      </div>
    </div>
  );
}

function Group({ heading, argument, total, rows, nested }) {
  return (
    <section className={nested ? "mt-8" : "mt-12"}>
      <h2
        className={
          nested
            ? "font-doc text-section font-semibold"
            : "font-doc text-section font-semibold lg:text-section-lg"
        }
      >
        {heading}
      </h2>
      <p className="mt-2 max-w-[62ch] font-doc text-body text-ink-2">
        {argument}
      </p>
      <p className="mt-2 font-doc text-aside text-ink-soft">
        {rupees(total)} across {rows.length} line{rows.length === 1 ? "" : "s"}.
      </p>

      <ul className="mt-4 space-y-3">
        {rows.map((f, i) => (
          <Row key={`${f.line_no}-${i}`} f={f} />
        ))}
      </ul>
    </section>
  );
}

/*
  One flagged line. Desktop puts the charge on the left and the authority for
  striking it on the right, because that is the pairing the reader has to
  make — "they billed me this" against "the IRDAI says this". On a phone the
  two stack, charge first.
*/
function Row({ f }) {
  return (
    <li className="border border-rule bg-card md:grid md:grid-cols-12 md:items-start">
      <div className="flex items-baseline justify-between gap-4 px-5 py-4 md:col-span-5 md:border-r md:border-rule-soft">
        <span className="wrap-verbatim font-doc text-body text-ink">
          <span className="folio mr-2 text-ink-soft">L{f.line_no}</span>
          {f.description}
        </span>
        <span className="font-quote text-body whitespace-nowrap text-ink">
          {rupees(f.amount) || "—"}
        </span>
      </div>

      <div className="border-t border-rule-soft px-5 py-4 md:col-span-7 md:border-t-0">
        {/* Showing "GLOVES / IRDAI list GLOVES" reads as a rendering fault,
            not as evidence. When the billed line and the IRDAI wording are
            the same the match is self-evident, so only the difference is
            worth printing. The wording is still verbatim from the corpus
            whenever it is shown — never paraphrased, same rule as clause text
            in the decoder. */}
        {same(f) ? (
          <span className="font-doc text-aside text-ink-soft">
            Matches the IRDAI list exactly.
          </span>
        ) : (
          <>
            <span className="folio text-ink-soft">IRDAI list</span>
            <q className="wrap-verbatim mt-1 block font-quote text-[0.8125rem] leading-relaxed text-ink-verbatim">
              {f.item_name}
            </q>
          </>
        )}
      </div>
    </li>
  );
}

/*
  Nothing flagged. A designed outcome, not an empty container: it says what
  was checked, what was not, and what to do next. "We found nothing" with no
  scope attached would read as "your bill is fine", which is not what it
  means.
*/
function NothingFlagged({ result, onReset, flush = true }) {
  return (
    <div>
      <Arrive>
        <section
          className={
            "-mx-5 bg-paper-sunk px-5 py-14 sm:-mx-8 sm:px-8 sm:py-16 lg:py-20 " +
            (flush ? "-mt-8 sm:-mt-12" : "")
          }
        >
          <p className="folio text-ink-soft">What was checked</p>
          <h1 className="mt-6 max-w-[22ch] font-doc text-screen font-semibold text-balance lg:mt-8 lg:text-screen-lg">
            Nothing on this bill matched the IRDAI lists.
          </h1>
          <p className="mt-6 max-w-[58ch] font-doc text-lead text-ink-2 lg:text-lead-lg">
            All {result.lines_read} lines we could read were checked against
            all {result.checks?.irdai_items || 146} items. None of them is an
            item a hospital is forbidden from charging to your claim.
          </p>
        </section>
      </Arrive>

      <div className="mt-8 lg:grid lg:grid-cols-12 lg:gap-12">
        <div className="lg:col-span-7">
          <h2 className="folio text-ink-soft">What this does not mean</h2>
          <p className="mt-1.5 font-doc text-body text-ink">
            It does not mean the bill is correct. It means none of the lines is
            on the one list that is the same for every insurer in India. A bill
            can still be wrong in ways this cannot see: a room charge above
            your eligible category, a sub-limit on a procedure, a deductible,
            or a charge for treatment your policy does not cover at all.
          </p>
          <p className="mt-4 font-doc text-body text-ink-2">
            If lines were missed, it is usually the format. This reads one item
            per line with the amount at the end. If your bill pasted as a
            single block, try re-pasting it with the line breaks intact.
          </p>
        </div>

        <div className="mt-6 lg:col-span-5 lg:mt-0">
          <div className="border-l-[3px] border-ochre bg-ochre-tint px-5 py-4">
            <p className="folio text-ochre">Worth doing next</p>
            <p className="mt-1.5 font-doc text-body text-ink">
              Ask the hospital for the itemised bill in full if you were given
              a summary. Deductions are usually made line by line, so a summary
              hides exactly what this checks.
            </p>
          </div>
        </div>
      </div>

      <ScopeNote reason={result.checks?.room_rent_reason} />

      <div className="no-print mt-10">
        <button
          onClick={onReset}
          className="border border-ink px-6 py-3 font-doc text-base font-semibold text-ink transition-colors hover:bg-paper-sunk"
        >
          Check another bill
        </button>
      </div>
    </div>
  );
}

/*
  The lines that were not flagged.

  Collapsed, because it is reference rather than argument, but present.
  Showing only what was flagged asks the reader to trust that the rest was
  correctly left alone, and the entire premise of this product is that nobody
  should have to take our word for anything.
*/
function NotFlagged({ rows }) {
  if (rows.length === 0) return null;
  return (
    <details className="mt-10 border border-rule-soft bg-card">
      <summary className="cursor-pointer px-5 py-4 font-doc text-body text-ink-2">
        {rows.length} line{rows.length === 1 ? "" : "s"} checked and not flagged
      </summary>
      <ul className="border-t border-rule-soft">
        {rows.map((l) => (
          <li
            key={l.line_no}
            className="flex items-baseline justify-between gap-4 border-b border-rule-soft px-5 py-3 last:border-b-0"
          >
            <span className="wrap-verbatim font-doc text-body text-ink">
              <span className="folio mr-2 text-ink-soft">L{l.line_no}</span>
              {l.description}
            </span>
            <span className="font-quote text-aside whitespace-nowrap text-ink-soft">
              {rupees(l.amount) || "—"}
            </span>
          </li>
        ))}
      </ul>
      <p className="border-t border-rule-soft px-5 py-3 font-doc text-aside text-ink-soft">
        None of these appears on the IRDAI lists. That does not make each one
        correct, only that it is not an item a hospital is forbidden from
        charging.
      </p>
    </details>
  );
}

/*
  The letter to the billing desk.

  The rejection side produces a letter and this side stopped at a page, which
  left the reader with a finding and no way to act on it. This is the thing
  that actually recovers the money.

  Composed in the browser from the findings with no model involved, for the
  same reason the matching has none: every item name in it is the corpus row,
  and a letter quoting an item the IRDAI list does not contain would be worse
  than no letter.
*/
function billLetterText(result) {
  const f = result.findings || [];
  const never = f.filter((x) => x.category === "not_payable");
  const twice = f.filter((x) => x.category !== "not_payable");
  const money = (n) =>
    typeof n === "number"
      ? `Rs ${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`
      : "amount not stated";
  const sum = (rows) => rows.reduce((t, x) => t + (x.amount || 0), 0);
  const line = (x) =>
    `  Line ${x.line_no}: ${x.description} - ${money(x.amount)}\n` +
    `      IRDAI list: "${x.item_name}"`;

  const parts = [
    "To\nThe Billing Department",
    "",
    "Subject: Request to review items billed against my insurance claim",
    "",
    "Dear Sir/Madam,",
    "",
    "I have checked the itemised bill issued to me against the IRDAI's " +
      "published lists of items that may not be charged to a health " +
      "insurance claim. The lines below appear on those lists. I request " +
      "that the bill be revised accordingly.",
  ];

  if (never.length) {
    parts.push(
      "",
      `A. Items that may not be charged to a claim at all (${money(sum(never))})`,
      "",
      never.map(line).join("\n")
    );
  }
  if (twice.length) {
    parts.push(
      "",
      `B. Items already included in a charge already billed (${money(sum(twice))})`,
      "",
      twice
        .map(
          (x) =>
            `${line(x)}\n      Already included in ${
              SUBSUME[x.category] || "another charge"
            }.`
        )
        .join("\n")
    );
  }

  parts.push(
    "",
    `Total queried: ${money(result.flagged_total)}.`,
    "",
    "Please confirm in writing whether these lines will be removed or " +
      "adjusted, and issue a revised bill. I am happy to discuss any line " +
      "you believe has been listed in error.",
    "",
    "Yours faithfully,"
  );
  return parts.join("\n");
}

function BillLetter({ result }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const text = billLetterText(result);

  async function copy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <section className="mt-12">
      {!open ? (
        <div className="no-print border border-rule bg-card p-5 sm:p-6">
          <h2 className="font-doc text-section font-semibold lg:text-section-lg">
            Take it to the billing desk
          </h2>
          <p className="mt-2 max-w-[62ch] font-doc text-body text-ink-2">
            A letter listing each line above with the IRDAI wording beside it,
            and a total. Deductions are argued line by line, so the list is the
            argument.
          </p>
          <button
            onClick={() => setOpen(true)}
            className="mt-5 border border-ink bg-ink px-7 py-4 font-doc text-lead font-semibold text-paper transition-colors hover:bg-ink-2"
          >
            Draft the letter
          </button>
        </div>
      ) : (
        <Arrive>
          <h2 className="folio text-ink-soft">Draft letter</h2>
          <div className="wrap-verbatim mt-3 border border-rule bg-card px-5 py-6 font-quote text-[0.8125rem] leading-[1.85] whitespace-pre-wrap text-ink-verbatim">
            {text}
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

function ScopeNote({ reason }) {
  return (
    <section className="mt-12 border-t border-rule pt-6">
      <h2 className="folio text-ink-soft">What was not checked</h2>
      <div className="mt-3 lg:grid lg:grid-cols-12 lg:gap-12">
        <p className="font-doc text-body text-ink lg:col-span-7">
          <strong className="font-semibold">Room rent.</strong>{" "}
          {reason ||
            "Room rent limits are set in your Policy Schedule, not in the policy wording, so they cannot be checked from the policy alone."}{" "}
          If you were admitted to a room above your eligible category, the
          insurer may also deduct a proportion of every associated charge — and
          that deduction is often larger than everything on this page.
        </p>
        <p className="mt-3 font-doc text-body text-ink-2 lg:col-span-5 lg:mt-0">
          Also unchecked: sub-limits on specific procedures, your deductible,
          and whether the treatment itself is covered. Your Policy Schedule is
          the document that settles all three.
        </p>
      </div>
    </section>
  );
}
