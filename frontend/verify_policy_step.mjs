// The insurer step, checked by driving it rather than by looking at it.
//
// WHY THIS EXISTS
//
// The dates decide the verdict. The adjudicator is handed the claim details
// and told to judge only against what it can see, and to return
// insufficient_information rather than guess — so a waiting-period rejection
// with no dates has nothing to resolve against. When both date fields sat
// inside a collapsed "Add dates and amount for a sharper answer" row, the
// default path through the form (fill nothing, press the button) produced the
// worst answer the product can give.
//
// A width check cannot see that. Nothing overflowed; the form was simply
// shaped so that nobody would fill it. So this gate asserts the shape of the
// step and the behaviour of its button, at 375px, with a real browser.
//
// What it holds to:
//   1. both date fields are reachable without opening anything
//   2. neither date field is inside a <details>
//   3. treatment and amount stay inside one
//   4. "None of these is my insurer" is plain text, below the submit button
//   5. pressing with dates empty warns and does NOT leave the step
//   6. pressing a second time goes ahead anyway — the warning is not a wall
//   7. with both dates filled, one press is enough and no warning appears
//   8. the warning names only the date actually missing
//   9. the warning self-clears when the dates are filled after it appeared
//  10. the warned state does not overflow the viewport
//
//   npm run dev                       # in another terminal
//   npm run verify:policy-step        # or: ORIGIN=... node verify_policy_step.mjs
//
// Exits non-zero on any failure, so it can gate a deploy.

import { chromium, webkit } from "playwright";
import { POLICIES, CASE_RESULT, APPEAL, BILL } from "./verify_mobile_fixtures.mjs";

const ORIGIN = process.env.ORIGIN || "http://localhost:5173";
const API = "https://claim-decoder-api-793807740598.asia-south1.run.app";
const WIDTH = Number(process.env.WIDTH) || 375;
const ENGINE = process.env.ENGINE || "chromium";

const LETTER =
  "We regret to inform you that your claim has been repudiated under Excl01, " +
  "the pre-existing disease waiting period.";

const json = (body) => ({
  status: 200,
  contentType: "application/json",
  headers: { "Access-Control-Allow-Origin": "*" },
  body: JSON.stringify(body),
});

async function mock(context) {
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
    if (url.includes("/api/bill/audit")) return route.fulfill(json(BILL));
    if (url.includes("/api/cases") && method === "POST")
      return route.fulfill(json({ case_id: "case_probe", status: "processing" }));
    if (url.includes("/api/cases/")) return route.fulfill(json(CASE_RESULT));
    return route.fulfill(json({}));
  });
}

let failures = 0;
let checks = 0;

function ok(name, condition, detail = "") {
  checks++;
  if (condition) {
    console.log(`  ok    ${name}`);
  } else {
    failures++;
    console.log(`  FAIL  ${name}${detail ? `\n          ${detail}` : ""}`);
  }
}

// Reaches the insurer step with the letter pasted. Every case starts here.
async function toPolicyStep(page) {
  await page.goto(`${ORIGIN}/rejection`, { waitUntil: "networkidle" });
  await page.waitForSelector("#letter");
  await page.fill("#letter", LETTER);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.waitForSelector("text=Which policy is this?");
  // The policy cards are the only aria-pressed buttons on this step.
  await page.locator("button[aria-pressed]").first().click();
}

const onPolicyStep = (page) =>
  page.locator("text=Which policy is this?").isVisible();

/* Document-absolute, not viewport-relative. boundingBox() is measured against
   the viewport, and Playwright scrolls an element into view before clicking
   it, so two boundingBox() readings either side of a click compare positions
   in two different scroll positions and disagree by the scroll distance. */
const absTop = (locator) =>
  locator.evaluate((n) => n.getBoundingClientRect().top + window.scrollY);
const absBottom = (locator) =>
  locator.evaluate((n) => n.getBoundingClientRect().bottom + window.scrollY);

const browser = await (ENGINE === "webkit" ? webkit : chromium).launch();
const context = await browser.newContext({
  viewport: { width: WIDTH, height: 800 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
  userAgent:
    "Mozilla/5.0 (Linux; Android 12; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
});
await mock(context);
const page = await context.newPage();

console.log(`engine=${ENGINE}  origin=${ORIGIN}  viewport=${WIDTH}px\n`);

/* ------------------------------------------------ the shape of the step */

console.log("the dates are in the main flow");
await toPolicyStep(page);

for (const id of ["#start", "#admission"]) {
  const el = page.locator(id);
  ok(`${id} is visible without opening anything`, await el.isVisible());
  const inDetails = await el.evaluate((n) => !!n.closest("details"));
  ok(`${id} is not inside a <details>`, !inDetails);
}

for (const id of ["#treatment", "#amount"]) {
  const inDetails = await page
    .locator(id)
    .evaluate((n) => !!n.closest("details"));
  ok(`${id} stays inside a <details>`, inDetails);
}

const detailsCount = await page.locator("main details").count();
ok(
  "exactly one collapsed row remains on this step",
  detailsCount === 1,
  `found ${detailsCount}`
);

// The reason line has to be present and has to say what the dates are for.
const reason = await page
  .locator("text=A waiting period is counted in months")
  .isVisible();
ok("the reason the dates matter is stated in the flow", reason);

/* ------------------------- "none of these" is plain text, below the control */

console.log("\nthe insurer escape hatch");
const noneHeading = page.getByRole("heading", {
  name: "None of these is my insurer",
});
ok("it is present", await noneHeading.isVisible());
ok(
  "it is not a <summary> and not inside a <details>",
  await noneHeading.evaluate(
    (n) => n.tagName.toLowerCase() !== "summary" && !n.closest("details")
  )
);

const submitBottom = await absBottom(
  page.getByRole("button", { name: "Check the rejection" })
);
const submitTop = await absTop(
  page.getByRole("button", { name: "Check the rejection" })
);
const noneTop = await absTop(noneHeading);
ok(
  "it sits below the submit button",
  noneTop > submitBottom,
  `submit ends at ${Math.round(submitBottom)}, this starts at ${Math.round(noneTop)}`
);

/* --------------------------------- pressing with no dates: warn, not block */

console.log("\nsubmitting with both dates empty");
await page.getByRole("button", { name: "Check the rejection" }).click();
await page.waitForSelector("#dates-warning", { timeout: 5000 }).catch(() => {});

const warning = page.locator("#dates-warning");
ok("a warning appears", await warning.isVisible());
ok(
  "it is announced to assistive tech",
  (await warning.getAttribute("role")) === "alert"
);
ok("it still has not left the step", await onPolicyStep(page));

const warnText = (await warning.innerText()).replace(/\s+/g, " ");
ok(
  "it names both missing dates",
  warnText.includes("the date the policy started") &&
    warnText.includes("the date of admission"),
  warnText
);
ok(
  "it says what the answer will be worth",
  /not enough to judge/i.test(warnText),
  warnText
);

const anyway = page.getByRole("button", { name: "Check it anyway" });
ok("the button relabels in place", await anyway.isVisible());
ok(
  "the button is described by the warning",
  (await anyway.getAttribute("aria-describedby")) === "dates-warning"
);

// The control must not move out from under a thumb that is already there.
const afterTop = await absTop(anyway);
ok(
  "the button did not move when the warning appeared",
  Math.abs(afterTop - submitTop) < 1,
  `was y=${Math.round(submitTop)}, now y=${Math.round(afterTop)} (document coordinates)`
);

// Nothing may overflow in this state either.
const over = await page.evaluate(
  () => document.documentElement.scrollWidth - document.documentElement.clientWidth
);
ok("the warned state does not overflow", over <= 0, `+${over}px`);

console.log("\npressing again goes ahead anyway");
await anyway.click();
await page.waitForSelector("text=Reading your policy", { timeout: 10000 }).catch(() => {});
ok("the second press leaves the step", !(await onPolicyStep(page)));

/* ------------------------------------ one date missing: name only that one */

console.log("\nsubmitting with only the admission date");
await toPolicyStep(page);
await page.fill("#admission", "2026-03-04");
await page.getByRole("button", { name: "Check the rejection" }).click();
await page.waitForSelector("#dates-warning", { timeout: 5000 }).catch(() => {});
const oneText = (await page.locator("#dates-warning").innerText()).replace(
  /\s+/g,
  " "
);
ok(
  "it names the start date only",
  oneText.includes("the date the policy started") &&
    !oneText.includes("the date of admission"),
  oneText
);

console.log("\nfilling the dates clears the warning");
await page.fill("#start", "2025-01-15");
ok(
  "the warning is gone",
  (await page.locator("#dates-warning").count()) === 0
);
ok(
  "the button reads as the plain action again",
  await page.getByRole("button", { name: "Check the rejection" }).isVisible()
);

/* ------------------------------------------- both dates: one press, no warn */

console.log("\nsubmitting with both dates filled");
await toPolicyStep(page);
await page.fill("#start", "2025-01-15");
await page.fill("#admission", "2026-03-04");
await page.getByRole("button", { name: "Check the rejection" }).click();
await page.waitForSelector("text=Reading your policy", { timeout: 10000 }).catch(() => {});
ok("one press is enough", !(await onPolicyStep(page)));
ok(
  "no warning was ever shown",
  (await page.locator("#dates-warning").count()) === 0
);

/* ------------------------------------------- the dates reach the API call */

console.log("\nwhat the API is actually sent");
let posted = null;
await context.route(`${API}/api/cases`, async (route) => {
  if (route.request().method() === "POST") {
    posted = JSON.parse(route.request().postData() || "{}");
    return route.fulfill(json({ case_id: "case_probe", status: "processing" }));
  }
  return route.fallback();
});
await toPolicyStep(page);
await page.fill("#start", "2025-01-15");
await page.fill("#admission", "2026-03-04");
await page.getByRole("button", { name: "Check the rejection" }).click();
await page.waitForSelector("text=Reading your policy", { timeout: 10000 }).catch(() => {});
ok(
  "both dates are in the POST body",
  posted?.claim?.policy_start_date === "2025-01-15" &&
    posted?.claim?.admission_date === "2026-03-04",
  JSON.stringify(posted?.claim)
);

await context.close();
await browser.close();

console.log(
  `\n${failures === 0 ? `PASS — ${checks} checks` : `FAIL — ${failures} of ${checks} checks failed`}`
);
process.exit(failures === 0 ? 0 : 1);
