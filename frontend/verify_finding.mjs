// The finding screen's two notices, driven in a browser.
//
//   1. The confidence figure is withheld on insufficient_information.
//      The adjudicator scores that verdict like any other — measured at 0.95
//      on a case with no dates at all — and "Confidence in this reading: 95%"
//      printed under "Not enough to judge" reads as a contradiction.
//
//   2. The insurer-mismatch notice appears above the verdict when the pasted
//      letter names a policy other than the one selected, and stays away when
//      it does not. The matching rules themselves are unit tested in
//      verify_insurer_match.mjs; this checks that the result reaches the
//      screen, in the right place, without blocking anything.
//
// The API is stubbed so both verdicts are reachable without model spend.
//
//   npm run verify:finding
//
// Exits non-zero on any failure.

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { POLICIES, CASE_RESULT, APPEAL } from "./verify_mobile_fixtures.mjs";

const ORIGIN = process.env.ORIGIN || "http://localhost:5173";
const API = "https://claim-decoder-api-793807740598.asia-south1.run.app";
const OUT = process.env.SHOTS || "mobile-shots";

const HDFC_LETTER =
  "We regret to inform you that your claim under policy Optima Secure has " +
  "been repudiated. As per Exclusion Excl01 of the policy wording, treatment " +
  "of a pre-existing disease is excluded until the expiry of 36 months of " +
  "continuous coverage.";

const NEUTRAL_LETTER =
  "We regret to inform you that your claim has been repudiated under the " +
  "pre-existing disease waiting period of 36 months.";

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

const json = (body) => ({
  status: 200,
  contentType: "application/json",
  headers: { "Access-Control-Allow-Origin": "*" },
  body: JSON.stringify(body),
});

/*
  Reaches the finding with a chosen verdict and a chosen letter. The insurer
  is picked by name rather than by position, because which policy is selected
  is the whole point of the mismatch check.
*/
async function toFinding(context, { verdict, letter, insurer }) {
  const result = { ...CASE_RESULT, verdict, confidence: 0.95 };
  await context.route(`${API}/**`, (route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (method === "OPTIONS")
      return route.fulfill({
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    if (url.includes("/api/policies")) return route.fulfill(json(POLICIES));
    if (url.includes("/appeal")) return route.fulfill(json(APPEAL));
    if (url.includes("/api/cases") && method === "POST")
      return route.fulfill(json({ case_id: "case_probe", status: "processing" }));
    if (url.includes("/api/cases/")) return route.fulfill(json(result));
    return route.fulfill(json({}));
  });

  const page = await context.newPage();
  await page.goto(`${ORIGIN}/rejection`, { waitUntil: "networkidle" });
  await page.waitForSelector("#letter");
  await page.fill("#letter", letter);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.waitForSelector("text=Which policy is this?");
  await page
    .locator("button[aria-pressed]")
    .filter({ hasText: insurer })
    .first()
    .click();
  await page.fill("#start", "2025-01-01");
  await page.fill("#admission", "2026-06-10");
  await page.getByRole("button", { name: "Check the rejection" }).click();
  await page.waitForSelector("h1", { timeout: 20000 });
  await page.waitForTimeout(900);
  return page;
}

const browser = await chromium.launch();
mkdirSync(OUT, { recursive: true });
console.log(`origin=${ORIGIN}\n`);

/* ---------------------------------- 1. confidence on a scored verdict ---- */

console.log("a scored verdict keeps its confidence");
{
  const context = await browser.newContext({
    viewport: { width: 375, height: 900 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  const page = await toFinding(context, {
    verdict: "weakly_supported",
    letter: NEUTRAL_LETTER,
    insurer: "HDFC Ergo",
  });
  const body = await page.locator("main").innerText();
  ok("the verdict rendered", body.includes("The rejection looks weak"));
  ok("confidence is shown", /Confidence in this reading:\s*95%/.test(body), body.slice(0, 200));
  ok("the clause count is shown", /clauses from your policy were read/.test(body));
  ok("no mismatch notice on a letter that names nobody", !/check this first/i.test(body));
  await page.screenshot({ path: `${OUT}/finding-scored.png`, fullPage: true });
  await context.close();
}

/* ------------------------- 2. no confidence on insufficient_information -- */

console.log("\ninsufficient_information withholds it");
{
  const context = await browser.newContext({
    viewport: { width: 375, height: 900 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  const page = await toFinding(context, {
    verdict: "insufficient_information",
    letter: NEUTRAL_LETTER,
    insurer: "HDFC Ergo",
  });
  const body = await page.locator("main").innerText();
  ok("the verdict rendered", body.includes("Not enough to judge"));
  ok(
    "no confidence figure anywhere on the screen",
    !/Confidence in this reading/.test(body),
    body.slice(0, 400)
  );
  ok(
    "the clause count survives on its own",
    /clauses from your policy were read/.test(body),
    "it is a fact about what was searched and is true on every verdict"
  );
  await page.screenshot({ path: `${OUT}/finding-insufficient.png`, fullPage: true });
  await context.close();
}

/* ------------------------------------------- 3. the mismatch notice ------ */

console.log("\nthe insurer-mismatch notice");
{
  const context = await browser.newContext({
    viewport: { width: 375, height: 900 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  const page = await toFinding(context, {
    verdict: "weakly_supported",
    letter: HDFC_LETTER,
    insurer: "Star Health",
  });
  const body = await page.locator("main").innerText();

  // Case-insensitive: .folio sets text-transform: uppercase, and innerText
  // returns the rendered text, so the label comes back as "CHECK THIS FIRST".
  ok("it appears", /check this first/i.test(body));
  ok(
    "it names the policy the letter mentions",
    body.includes("HDFC Ergo Optima Secure"),
    body.slice(0, 500)
  );
  ok(
    "it names the policy that was chosen",
    body.includes("Star Health Arogya Sanjeevani")
  );

  // Above the verdict, in document order, because it changes what the verdict
  // means. Compared in document coordinates, not viewport ones.
  const noticeTop = await page
    .locator("text=Check this first")
    .evaluate((n) => n.getBoundingClientRect().top + window.scrollY);
  const verdictTop = await page
    .getByRole("heading", { level: 1 })
    .evaluate((n) => n.getBoundingClientRect().top + window.scrollY);
  ok(
    "it sits above the verdict headline",
    noticeTop < verdictTop,
    `notice at ${Math.round(noticeTop)}, verdict at ${Math.round(verdictTop)}`
  );

  // It warns; it does not block. The finding and the letter are still there.
  ok("the verdict is still delivered", body.includes("The rejection looks weak"));
  ok("the clause exhibit is still shown", (await page.locator("figure.exhibit").count()) > 0);
  ok(
    "the letter is still offered",
    (await page.getByRole("button", { name: /Draft the/ }).count()) > 0
  );

  // The theme allows ochre once per screen and what_would_change_it has it.
  const ochre = await page.locator(".bg-ochre-tint").count();
  ok("ochre is still used at most once on this screen", ochre <= 1, `found ${ochre}`);

  await page.screenshot({ path: `${OUT}/finding-mismatch.png`, fullPage: true });
  await context.close();
}

await browser.close();
console.log(
  `\n${failures === 0 ? `PASS — ${checks} checks` : `FAIL — ${failures} of ${checks} checks failed`}`
);
process.exit(failures === 0 ? 0 : 1);
