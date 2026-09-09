// Narrow-viewport overflow gate.
//
// Every screen is walked at 320, 375 and 414 CSS pixels and the document is
// required to be no wider than the viewport. When it is wider, the elements
// actually responsible are named, rather than every descendant that is merely
// carried along by an overflowing ancestor.
//
// This exists because the mobile layout shipped unverified across four
// screens. The defect it caught was a single unbreakable run of text: policy
// wordings carry URLs like
// "https://transactions.nivabupa.com/cashlessclaims/pages/intimation-claim.aspx"
// and a pasted rejection letter carries claim references, none of which any
// default wrapping rule will break. See .wrap-verbatim in theme.css.
//
// The API is stubbed from verify_mobile_fixtures.mjs, so this needs no
// backend and no credentials, and the finding screens are reachable
// deterministically.
//
//   npm run dev                       # in another terminal
//   npx playwright install chromium   # once
//   npm run verify:mobile             # or: ENGINE=webkit ORIGIN=... node verify_mobile.mjs
//
// Exits non-zero if anything overflows, so it can gate a deploy.

import { chromium, webkit } from "playwright";
import { POLICIES, CASE_RESULT, APPEAL, BILL } from "./verify_mobile_fixtures.mjs";

const ORIGIN = process.env.ORIGIN || "http://localhost:5173";
const API = "https://claim-decoder-api-793807740598.asia-south1.run.app";
const WIDTHS = process.argv.slice(2).map(Number).filter(Boolean);
const SIZES = WIDTHS.length ? WIDTHS : [320, 375, 414];
const SHOTS = process.env.SHOTS || null;

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
    if (method === "OPTIONS") return route.fulfill({ status: 204, headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    }});
    if (url.includes("/api/policies")) return route.fulfill(json(POLICIES));
    if (url.includes("/appeal")) return route.fulfill(json(APPEAL));
    if (url.includes("/api/bill/audit")) return route.fulfill(json(BILL));
    if (url.includes("/api/cases") && method === "POST")
      return route.fulfill(json({ case_id: "case_probe", status: "processing" }));
    if (url.includes("/api/cases/")) return route.fulfill(json(CASE_RESULT));
    return route.fulfill(json({}));
  });
}

// Runs in the page. Returns the overflow origins: elements sticking past the
// right edge whose parent does not, plus elements whose own content is wider
// than their box.
const MEASURE = () => {
  const vw = document.documentElement.clientWidth;
  const out = {
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    clientWidth: vw,
    bodyScrollWidth: document.body.scrollWidth,
    culprits: [],
  };

  const label = (el) => {
    const cls = (el.getAttribute("class") || "").trim().slice(0, 150);
    const txt = (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 70);
    return {
      tag: el.tagName.toLowerCase(),
      cls,
      text: txt,
    };
  };

  const past = new Map();
  for (const el of document.querySelectorAll("*")) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const overRight = r.right - vw;
    const overLeft = -r.left;
    if (overRight > 0.5 || overLeft > 0.5) past.set(el, { overRight, overLeft, r });
  }

  for (const [el, info] of past) {
    // An element is an origin if its parent is inside the viewport: the
    // overflow starts here rather than being inherited.
    const parentOver = el.parentElement && past.has(el.parentElement);
    const selfScroll = el.scrollWidth - el.clientWidth;
    if (!parentOver || selfScroll > 1) {
      out.culprits.push({
        ...label(el),
        right: Math.round(info.r.right),
        left: Math.round(info.r.left),
        width: Math.round(info.r.width),
        overRight: Math.round(info.overRight),
        overLeft: Math.round(info.overLeft),
        selfScroll: Math.round(selfScroll),
        inheritedFromParent: !!parentOver,
      });
    }
  }

  // Scroll containers whose content exceeds their box, even if they sit
  // inside the viewport. These are the ones a hidden overflow would mask.
  out.clipped = [];
  for (const el of document.querySelectorAll("*")) {
    const over = el.scrollWidth - el.clientWidth;
    if (over > 1 && el.clientWidth > 0) {
      out.clipped.push({ ...label(el), over, clientWidth: el.clientWidth });
    }
  }

  out.culprits.sort((a, b) => b.overRight - a.overRight);
  out.clipped.sort((a, b) => b.over - a.over);
  out.clipped = out.clipped.slice(0, 12);
  return out;
};

async function screen(page, name, prepare) {
  await prepare(page);
  await page.waitForTimeout(450);
  const m = await page.evaluate(MEASURE);
  return { name, ...m };
}

const goLanding = async (p) => {
  await p.goto(`${ORIGIN}/`, { waitUntil: "networkidle" });
};

const goRejectionPaste = async (p) => {
  await p.goto(`${ORIGIN}/rejection`, { waitUntil: "networkidle" });
  await p.waitForSelector("#letter");
};

const goRejectionPolicy = async (p) => {
  await goRejectionPaste(p);
  await p.fill("#letter", "We regret to inform you that your claim has been repudiated under Excl01, the pre-existing disease waiting period.");
  await p.getByRole("button", { name: "Continue" }).click();
  await p.waitForSelector("text=Which policy is this?");
};

// The dates now sit in the main flow rather than inside a disclosure, and
// pressing the button without them warns once before going ahead. That is a
// second state of this step with its own layout, so it is measured too.
const goRejectionPolicyWarned = async (p) => {
  await goRejectionPolicy(p);
  await p.locator("button[aria-pressed]").first().click();
  await p.getByRole("button", { name: "Check the rejection" }).click();
  await p.waitForSelector("#dates-warning");
};

const goRejectionFinding = async (p) => {
  await goRejectionPolicy(p);
  // The policy cards are the only aria-pressed buttons on this step.
  await p.locator("button[aria-pressed]").first().click();
  // Filled, so this walks the intended path in one press. The empty-date
  // path is verify_policy_step.mjs, which checks behaviour rather than width.
  await p.fill("#start", "2025-01-15");
  await p.fill("#admission", "2026-03-04");
  await p.getByRole("button", { name: "Check the rejection" }).click();
  await p.waitForSelector("text=The rejection looks weak", { timeout: 20000 });
};

const goRejectionLetter = async (p) => {
  await goRejectionFinding(p);
  await p.getByRole("button", { name: "Draft the appeal" }).click();
  await p.waitForSelector("text=Draft appeal", { timeout: 20000 });
};

const goBillPaste = async (p) => {
  await p.goto(`${ORIGIN}/bill`, { waitUntil: "networkidle" });
  await p.waitForSelector("#bill");
};

const goBillFindings = async (p) => {
  await goBillPaste(p);
  await p.getByRole("button", { name: "Use an example bill" }).click();
  await p.getByRole("button", { name: "Check the bill" }).click();
  await p.waitForSelector("text=should not have been", { timeout: 20000 });
};

const goBillLetter = async (p) => {
  await goBillFindings(p);
  await p.getByRole("button", { name: "Draft the letter" }).click();
  await p.waitForSelector("text=Draft letter", { timeout: 20000 });
};

const SCREENS = [
  ["landing", goLanding],
  ["rejection-paste", goRejectionPaste],
  ["rejection-policy", goRejectionPolicy],
  ["rejection-policy-warned", goRejectionPolicyWarned],
  ["rejection-finding", goRejectionFinding],
  ["rejection-letter", goRejectionLetter],
  ["bill-paste", goBillPaste],
  ["bill-findings", goBillFindings],
  ["bill-letter", goBillLetter],
];

const ENGINE = process.env.ENGINE || "chromium";
const browser = await (ENGINE === "webkit" ? webkit : chromium).launch();
console.log(`engine=${ENGINE}  origin=${ORIGIN}`);
let bad = 0;

for (const width of SIZES) {
  const context = await browser.newContext({
    viewport: { width, height: 800 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    userAgent:
      "Mozilla/5.0 (Linux; Android 12; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
  });
  await mock(context);
  const page = await context.newPage();

  console.log(`\n${"=".repeat(72)}\n  VIEWPORT ${width}px\n${"=".repeat(72)}`);

  for (const [name, prepare] of SCREENS) {
    let r;
    try {
      r = await screen(page, name, prepare);
    } catch (e) {
      console.log(`\n  ${name}: COULD NOT REACH — ${String(e).split("\n")[0]}`);
      continue;
    }
    const over = r.scrollWidth - r.clientWidth;
    const flag = over > 0 ? "OVERFLOW" : "ok";
    if (over > 0) bad++;
    console.log(
      `\n  ${name}: ${flag}  scrollWidth=${r.scrollWidth} clientWidth=${r.clientWidth} (+${over}px)`
    );
    if (over > 0) {
      for (const c of r.culprits.slice(0, 8)) {
        console.log(
          `      +${c.overRight}px  <${c.tag}> w=${c.width} right=${c.right}` +
            (c.selfScroll > 1 ? ` selfScroll=+${c.selfScroll}` : "") +
            `\n            class="${c.cls}"` +
            `\n            text="${c.text}"`
        );
      }
    }
    if (r.clipped.length) {
      console.log(`      -- content wider than its box --`);
      for (const c of r.clipped.slice(0, 5)) {
        console.log(
          `      +${c.over}px  <${c.tag}> box=${c.clientWidth}\n            class="${c.cls}"\n            text="${c.text}"`
        );
      }
    }
    if (SHOTS) {
      await page.screenshot({
        path: `${SHOTS}/${width}-${name}.png`,
        fullPage: true,
      });
    }
  }
  await context.close();
}

await browser.close();
console.log(`\n${bad === 0 ? "PASS — no horizontal overflow anywhere" : `FAIL — ${bad} screen/width combinations overflow`}`);
process.exit(bad === 0 ? 0 : 1);
