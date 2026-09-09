// The bill auditor's letter, checked against the corpus it quotes.
//
// The letter is composed in the browser by billLetterText() with no model
// involved, for the same reason the matching has none: every item name in it
// is a corpus row, and a letter quoting an item the IRDAI list does not
// contain would be worse than no letter. Nothing had ever pressed the button.
//
// This drives the REAL API — no fixtures — because the point is to confirm
// that what the letter quotes is what the corpus holds. It records the
// /api/bill/audit response off the wire, then reads the rendered letter and
// requires, for every finding:
//
//   * the IRDAI item name appears in the letter verbatim, inside quotes
//   * the billed description appears verbatim
//   * the amount appears, formatted, and the section total is arithmetic on
//     the findings rather than a restatement of the headline
//   * every quoted string in the letter traces back to a finding, so nothing
//     is quoted that the API did not return
//
//   ORIGIN=https://project-37e668b0-6b36-4e1f-a02.web.app node verify_bill_letter.mjs
//
// Exits non-zero on any failure.

import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const ORIGIN = process.env.ORIGIN || "http://localhost:5173";
const WIDTH = Number(process.env.WIDTH) || 375;

// Three List I items by default, which is the case that was asked for.
// BILL_TEXT points it at another bill: the ten-line sample also carries
// subsume_room and subsume_procedure lines, which exercise section B of the
// letter and cannot be reached from a bill of three List I items.
const BILL =
  process.env.BILL_TEXT ||
  ["GLOVES   450.00", "BABY FOOD   320.00", "ATTENDANT CHARGES   2400.00"].join("\n");

let failures = 0;
let checks = 0;
function ok(name, condition, detail = "") {
  checks++;
  if (condition) console.log(`  ok    ${name}`);
  else {
    failures++;
    console.log(`  FAIL  ${name}${detail ? `\n          ${detail}` : ""}`);
  }
}

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: WIDTH, height: 900 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
});
/*
  The audit response, taken off the wire rather than reconstructed. Captured
  by intercepting the route and passing the real response through untouched —
  page.on("response") does not reliably retain a body long enough to read it,
  and reading it late returned null. Nothing is stubbed: route.fetch() makes
  the real call to the real API and the page renders the real answer.
*/
let audit = null;
await context.route("**/api/bill/audit", async (route) => {
  const real = await route.fetch();
  audit = await real.json().catch(() => null);
  await route.fulfill({ response: real });
});

const page = await context.newPage();

console.log(`origin=${ORIGIN}\n`);
await page.goto(`${ORIGIN}/bill`, { waitUntil: "networkidle" });
await page.waitForSelector("#bill");
await page.fill("#bill", BILL);
await page.getByRole("button", { name: "Check the bill" }).click();
await page.waitForSelector("text=What was checked", { timeout: 30000 });
await page.waitForTimeout(800);

ok("the audit response was captured", !!audit);
if (!audit) {
  await browser.close();
  process.exit(1);
}

const findings = audit.findings || [];
console.log(
  `\n  bill: ${audit.lines_read} lines read, ${audit.lines_flagged} flagged, ` +
    `total flagged ${audit.flagged_total}\n`
);
for (const f of findings) {
  console.log(
    `    L${f.line_no} "${f.description}" ${f.amount}  [${f.category}]\n` +
      `        IRDAI: "${f.item_name}"`
  );
}

ok("at least one line was flagged", findings.length > 0);

await page.getByRole("button", { name: "Draft the letter" }).click();
await page.waitForSelector("text=Draft letter", { timeout: 15000 });
await page.waitForTimeout(400);

// The letter as the reader sees it. innerText, so it is the rendered text and
// not the source.
const letter = await page
  .locator("div.wrap-verbatim.whitespace-pre-wrap")
  .first()
  .innerText();
writeFileSync("bill-letter.txt", letter, "utf-8");
console.log(`\n  ---- the letter as rendered (${letter.length} chars) ----\n`);
console.log(letter.replace(/^/gm, "  | "));
console.log("");

/* ------------------------- every finding is quoted exactly ------------------------- */

for (const f of findings) {
  ok(
    `L${f.line_no}: IRDAI name quoted verbatim — "${f.item_name}"`,
    letter.includes(`"${f.item_name}"`),
    `not found as a quoted string in the letter`
  );
  ok(
    `L${f.line_no}: billed description verbatim — "${f.description}"`,
    letter.includes(f.description),
    `not found in the letter`
  );
  if (typeof f.amount === "number") {
    const money = `Rs ${f.amount.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
    ok(`L${f.line_no}: amount present as ${money}`, letter.includes(money));
  }
}

/* --------------- nothing is quoted that the API did not return --------------- */

const quoted = [...letter.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
const known = new Set(findings.map((f) => f.item_name));
const stray = quoted.filter((q) => !known.has(q));
ok(
  "every quoted string in the letter is an IRDAI item the API returned",
  stray.length === 0,
  stray.length ? `unexpected quotations: ${JSON.stringify(stray)}` : ""
);
ok(
  "every returned item name is quoted at least once",
  [...known].every((k) => quoted.includes(k)),
  `missing: ${JSON.stringify([...known].filter((k) => !quoted.includes(k)))}`
);

/* --------------------------- the totals are arithmetic --------------------------- */

const sum = (rows) => rows.reduce((t, x) => t + (x.amount || 0), 0);
const never = findings.filter((x) => x.category === "not_payable");
const twice = findings.filter((x) => x.category !== "not_payable");
const money = (n) => `Rs ${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

if (never.length)
  ok(
    `section A total is the sum of its own lines (${money(sum(never))})`,
    letter.includes(money(sum(never)))
  );
if (twice.length)
  ok(
    `section B total is the sum of its own lines (${money(sum(twice))})`,
    letter.includes(money(sum(twice)))
  );
ok(
  `the queried total matches flagged_total (${money(audit.flagged_total)})`,
  letter.includes(`Total queried: ${money(audit.flagged_total)}`),
  `letter should carry the API's own flagged_total`
);

/* ------------------- it does not overclaim on the reader's behalf ------------------- */

ok(
  "the letter does not assert the bill is fraudulent or demand a refund amount beyond the queried total",
  !/fraud|illegal|penalt/i.test(letter)
);
ok(
  "the letter asks for written confirmation rather than asserting an outcome",
  /confirm in writing/i.test(letter)
);

await browser.close();
console.log(
  `\nletter written to bill-letter.txt\n` +
    `${failures === 0 ? `PASS — ${checks} checks` : `FAIL — ${failures} of ${checks} checks failed`}`
);
process.exit(failures === 0 ? 0 : 1);
