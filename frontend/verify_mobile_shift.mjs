// Narrow-viewport stability gate: does the page move under the reader.
//
// WHY THIS IS SEPARATE FROM verify_mobile.mjs
//
// That gate asks "does it fit". This one asks "does it hold still". They are
// different failures with different causes, and a screen can pass the first
// while being unusable on the second: nothing overflows, every width is
// correct, and the layout still jumps every time a thumb lands on it.
//
// Four things move a mobile page, and all four are checked here:
//
//   1. Mobile Safari zooms the viewport when a focused input has a computed
//      font-size below 16px. It is not a layout shift and no shift observer
//      will report it — the page is simply scaled up and left there. This is
//      the one that reads as "the whole screen moved".
//   2. Focus styles that occupy space. An outline does not, a border-width
//      change does.
//   3. Animated elements that change height rather than transform.
//   4. Reflow when a section expands or the step changes, including scroll
//      position carried across a screen change so the reader lands mid-page.
//
// HOW IT MEASURES
//
// A PerformanceObserver for "layout-shift" is installed before any script
// runs, and the buffer is cleared immediately before each interaction, so the
// score reported against an interaction was caused by that interaction.
// hadRecentInput is recorded but NOT used to filter: shifts within 500ms of a
// tap are exactly what this is hunting, and the standard CLS metric discards
// them. The nodes responsible are named, with the rectangle they moved from
// and to.
//
// Every interaction is screenshotted before and after and written to a
// contact sheet, so a shift can be seen rather than only scored.
//
//   npm run dev                       # in another terminal
//   npm run verify:mobile-shift       # writes mobile-shots/index.html
//
// layout-shift is a Chromium API, so the shift half runs there. The font-size
// half is engine-independent and runs wherever it is pointed.
//
// Exits non-zero on any failure, so it can gate a deploy.

import { chromium, webkit } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { POLICIES, CASE_RESULT, APPEAL, BILL } from "./verify_mobile_fixtures.mjs";

const ORIGIN = process.env.ORIGIN || "http://localhost:5173";
const API = "https://claim-decoder-api-793807740598.asia-south1.run.app";
const WIDTH = Number(process.env.WIDTH) || 375;
const ENGINE = process.env.ENGINE || "chromium";
const OUT = process.env.SHOTS || "mobile-shots";

// A single interaction may legitimately move the page — opening a disclosure
// is meant to. What it may not do is move content the reader was already
// looking at. 0.05 is half of the "needs improvement" CLS threshold and well
// above the rounding noise of a repaint.
const BUDGET = Number(process.env.BUDGET) || 0.05;

// Mobile Safari's zoom trigger. Not a preference.
const MIN_INPUT_FONT_PX = 16;

const LETTER =
  "We regret to inform you that your claim has been repudiated under Excl01, " +
  "the pre-existing disease waiting period. Claim reference " +
  "CLM/HDFC/2026/0098871/PREAUTH/REV02.";

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

// Installed before any page script. Collects every layout shift with the
// nodes that moved, so a failure names the element rather than a number.
const OBSERVER = () => {
  window.__shifts = [];
  const describe = (node) => {
    if (!node || node.nodeType !== 1) return { tag: "?", cls: "", text: "" };
    return {
      tag: node.tagName.toLowerCase(),
      cls: (node.getAttribute("class") || "").trim().slice(0, 90),
      text: (node.textContent || "").trim().replace(/\s+/g, " ").slice(0, 60),
    };
  };
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        window.__shifts.push({
          value: e.value,
          hadRecentInput: e.hadRecentInput,
          sources: (e.sources || []).slice(0, 4).map((s) => ({
            ...describe(s.node),
            from: s.previousRect
              ? [Math.round(s.previousRect.x), Math.round(s.previousRect.y)]
              : null,
            to: s.currentRect
              ? [Math.round(s.currentRect.x), Math.round(s.currentRect.y)]
              : null,
          })),
        });
      }
    }).observe({ type: "layout-shift", buffered: true });
  } catch {
    window.__shiftsUnsupported = true;
  }
};

let failures = 0;
let checks = 0;
const sheet = [];

function ok(name, condition, detail = "") {
  checks++;
  if (condition) console.log(`  ok    ${name}`);
  else {
    failures++;
    console.log(`  FAIL  ${name}${detail ? `\n          ${detail}` : ""}`);
  }
}

let shot = 0;

/*
  One interaction, measured. Screenshots either side, the shift score it
  caused, the nodes that moved, and what happened to the scroll position and
  the document height.
*/
async function step(page, name, action, opts = {}) {
  const budget = opts.budget ?? BUDGET;
  const n = String(++shot).padStart(2, "0");
  const before = `${n}-${name}-before.png`;
  const after = `${n}-${name}-after.png`;

  /*
    Scroll whatever is about to be tapped into view BEFORE the first
    screenshot. Playwright scrolls an element into view as part of clicking
    it, and a real thumb does not: leaving that inside the measured window
    charges the interaction for a scroll the reader had already made, and the
    two screenshots then show different parts of the page for a reason that
    has nothing to do with the shift being hunted.
  */
  if (opts.at) {
    await opts.at.scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(200);
  }

  await page.evaluate(() => {
    window.__shifts = [];
  });
  const pre = await page.evaluate(() => ({
    scrollY: Math.round(window.scrollY),
    docHeight: Math.round(document.documentElement.scrollHeight),
  }));
  await page.screenshot({ path: `${OUT}/${before}` });

  await action(page);
  await page.waitForTimeout(opts.settle ?? 700);

  const post = await page.evaluate(() => ({
    scrollY: Math.round(window.scrollY),
    docHeight: Math.round(document.documentElement.scrollHeight),
    shifts: window.__shifts,
    unsupported: !!window.__shiftsUnsupported,
  }));
  await page.screenshot({ path: `${OUT}/${after}` });

  const score = post.shifts.reduce((t, s) => t + s.value, 0);
  const worst = post.shifts
    .flatMap((s) => s.sources.map((src) => ({ ...src, value: s.value })))
    .sort((a, b) => b.value - a.value)
    .slice(0, 4);

  sheet.push({
    name,
    before,
    after,
    screenChange: !!opts.screenChange,
    score,
    worst,
    scrollY: [pre.scrollY, post.scrollY],
    docHeight: [pre.docHeight, post.docHeight],
    budget,
  });

  const detail =
    `score=${score.toFixed(4)} budget=${budget}` +
    `\n          scrollY ${pre.scrollY} -> ${post.scrollY}, docHeight ${pre.docHeight} -> ${post.docHeight}` +
    worst
      .map(
        (w) =>
          `\n          moved ${JSON.stringify(w.from)} -> ${JSON.stringify(w.to)}  <${w.tag}> "${w.text}"\n            class="${w.cls}"`
      )
      .join("");

  if (post.unsupported) {
    console.log(`  --    ${name}: layout-shift unsupported on this engine`);
    return;
  }
  /*
    A screen change is not a layout shift worth scoring. The content is meant
    to be entirely different, so a CLS number across it measures nothing. What
    matters is where the reader is put: the browser keeps the scroll offset
    when one screen replaces another, so a reader who pressed a button at the
    foot of a long form lands that far into a screen they have never seen,
    past the headline it exists to deliver.
  */
  if (opts.screenChange) {
    ok(`${name} starts the new screen at the top`, post.scrollY === 0, detail);
    return;
  }
  ok(`${name} does not move the page`, score <= budget, detail);
}

/* --------------------------------------------- the font-size audit */

// Every control the reader can focus, and the size the browser computes for
// it. Below 16px, mobile Safari zooms the viewport and does not zoom back.
const AUDIT_FONTS = () =>
  [...document.querySelectorAll("input, textarea, select")]
    .filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 || r.height > 0 || el.type === "file";
    })
    .map((el) => ({
      id: el.id || null,
      tag: el.tagName.toLowerCase(),
      type: el.type || null,
      px: parseFloat(getComputedStyle(el).fontSize),
      hidden: el.hidden || el.type === "file",
    }));

async function auditFonts(page, where) {
  const fields = await page.evaluate(AUDIT_FONTS);
  for (const f of fields) {
    if (f.hidden) continue;
    const id = f.id ? `#${f.id}` : `<${f.tag}${f.type ? ` type=${f.type}` : ""}>`;
    ok(
      `${where}: ${id} is at least ${MIN_INPUT_FONT_PX}px (${f.px}px)`,
      f.px >= MIN_INPUT_FONT_PX,
      `mobile Safari zooms the viewport on focus below ${MIN_INPUT_FONT_PX}px`
    );
  }
  return fields;
}

/* -------------------------------------------------------- the walk */

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
await context.addInitScript(OBSERVER);
const page = await context.newPage();
mkdirSync(OUT, { recursive: true });

console.log(`engine=${ENGINE}  origin=${ORIGIN}  viewport=${WIDTH}px  budget=${BUDGET}\n`);

/* ---- landing: scrolling past the reveal animations ---- */

console.log("landing");
await page.goto(`${ORIGIN}/`, { waitUntil: "networkidle" });
await page.waitForTimeout(600);
await step(page, "landing-scroll-half", async (p) => {
  await p.evaluate(() => window.scrollTo(0, document.body.scrollHeight * 0.4));
});
await step(page, "landing-scroll-end", async (p) => {
  await p.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
});

/* ---- rejection: the whole form, tap by tap ---- */

console.log("\nrejection, the letter");
await page.goto(`${ORIGIN}/rejection`, { waitUntil: "networkidle" });
await page.waitForSelector("#letter");
await page.waitForTimeout(400);
await auditFonts(page, "letter step");

await step(
  page,
  "letter-focus",
  async (p) => {
    await p.locator("#letter").focus();
  },
  { at: page.locator("#letter") }
);
await step(page, "letter-type", async (p) => {
  await p.fill("#letter", LETTER);
});
await step(
  page,
  "letter-continue",
  async (p) => {
    await p.getByRole("button", { name: "Continue" }).click();
    await p.waitForSelector("text=Which policy is this?");
  },
  { at: page.getByRole("button", { name: "Continue" }), screenChange: true }
);

console.log("\nrejection, the policy");
await auditFonts(page, "policy step");

await step(
  page,
  "policy-choose-insurer",
  async (p) => {
    await p.locator("button[aria-pressed]").first().click();
  },
  { at: page.locator("button[aria-pressed]").first() }
);
await step(
  page,
  "policy-focus-start-date",
  async (p) => {
    await p.locator("#start").focus();
  },
  { at: page.locator("#start") }
);
await step(page, "policy-fill-dates", async (p) => {
  await p.fill("#start", "2025-01-15");
  await p.fill("#admission", "2026-03-04");
});
// A disclosure is meant to move what is below it. What it may not do is move
// what is above it, so this one is measured with a wider budget and read for
// which nodes moved rather than for the number alone.
await step(
  page,
  "policy-open-details",
  async (p) => {
    await p.locator("main details summary").first().click();
  },
  { at: page.locator("main details summary").first(), budget: 0.6 }
);
await step(
  page,
  "policy-focus-treatment",
  async (p) => {
    await p.locator("#treatment").focus();
  },
  { at: page.locator("#treatment") }
);
await step(
  page,
  "policy-submit",
  async (p) => {
    await p.getByRole("button", { name: "Check the rejection" }).click();
    await p.waitForSelector("text=Reading your policy", { timeout: 15000 });
  },
  {
    at: page.getByRole("button", { name: "Check the rejection" }),
    screenChange: true,
  }
);

console.log("\nrejection, the wait and the finding");
await step(
  page,
  "waiting-to-finding",
  async (p) => {
    await p.waitForSelector("text=The rejection looks weak", { timeout: 25000 });
  },
  { screenChange: true }
);
await step(page, "finding-scroll", async (p) => {
  await p.evaluate(() => window.scrollTo(0, document.body.scrollHeight * 0.5));
});
await step(
  page,
  "finding-draft-appeal",
  async (p) => {
    await p.getByRole("button", { name: "Draft the appeal" }).click();
    await p.waitForSelector("text=Draft appeal", { timeout: 20000 });
  },
  { at: page.getByRole("button", { name: "Draft the appeal" }), budget: 0.6 }
);
// A label swap inside a button resizes it and moves its siblings. Small, and
// exactly the kind of thing that reads as the page being loose.
await step(
  page,
  "finding-copy-letter",
  async (p) => {
    await p.getByRole("button", { name: "Copy letter" }).click();
  },
  { at: page.getByRole("button", { name: "Copy letter" }) }
);

/* ---- bill ---- */

console.log("\nthe bill");
await page.goto(`${ORIGIN}/bill`, { waitUntil: "networkidle" });
await page.waitForSelector("#bill");
await page.waitForTimeout(400);
await auditFonts(page, "bill step");

await step(
  page,
  "bill-focus",
  async (p) => {
    await p.locator("#bill").focus();
  },
  { at: page.locator("#bill") }
);
await step(
  page,
  "bill-example",
  async (p) => {
    await p.getByRole("button", { name: "Use an example bill" }).click();
  },
  { at: page.getByRole("button", { name: "Use an example bill" }) }
);
await step(
  page,
  "bill-check",
  async (p) => {
    await p.getByRole("button", { name: "Check the bill" }).click();
    await p.waitForSelector("text=should not have been", { timeout: 20000 });
  },
  {
    at: page.getByRole("button", { name: "Check the bill" }),
    screenChange: true,
  }
);
await step(
  page,
  "bill-expand-not-flagged",
  async (p) => {
    await p.locator("details summary").first().click();
  },
  { at: page.locator("details summary").first(), budget: 0.6 }
);
await step(
  page,
  "bill-draft-letter",
  async (p) => {
    await p.getByRole("button", { name: "Draft the letter" }).click();
    await p.waitForSelector("text=Draft letter", { timeout: 20000 });
  },
  { at: page.getByRole("button", { name: "Draft the letter" }), budget: 0.6 }
);
await step(
  page,
  "bill-copy-letter",
  async (p) => {
    await p.getByRole("button", { name: "Copy letter" }).click();
  },
  { at: page.getByRole("button", { name: "Copy letter" }) }
);

/* ------------------------------------------------- the contact sheet */

const rows = sheet
  .map(
    (s) => `
  <section class="${s.score > s.budget ? "bad" : "good"}">
    <h2>${s.name} <span class="score">${s.score.toFixed(4)}</span>
      <span class="meta">${s.screenChange ? "screen change &mdash; must land at the top" : "budget " + s.budget} &middot; scrollY ${s.scrollY[0]}&rarr;${s.scrollY[1]} &middot; height ${s.docHeight[0]}&rarr;${s.docHeight[1]}</span>
    </h2>
    ${
      s.worst.length
        ? `<ul class="moved">${s.worst
            .map(
              (w) =>
                `<li><code>&lt;${w.tag}&gt;</code> ${JSON.stringify(w.from)} &rarr; ${JSON.stringify(w.to)} <em>${w.text.replace(/</g, "&lt;")}</em></li>`
            )
            .join("")}</ul>`
        : ""
    }
    <div class="pair">
      <figure><img src="${s.before}"><figcaption>before</figcaption></figure>
      <figure><img src="${s.after}"><figcaption>after</figcaption></figure>
    </div>
  </section>`
  )
  .join("");

writeFileSync(
  `${OUT}/index.html`,
  `<!doctype html><meta charset="utf-8"><title>Mobile stability — ${WIDTH}px</title>
<style>
  body { font: 14px/1.5 system-ui, sans-serif; margin: 0; padding: 24px; background: #faf9f6; color: #10203a; }
  h1 { font-size: 20px; }
  section { border-top: 3px solid #10203a; background: #fff; padding: 16px; margin: 24px 0; }
  section.bad { border-top-color: #7d2b2b; }
  h2 { font-size: 15px; margin: 0 0 8px; }
  .score { font: 600 15px ui-monospace, monospace; margin-left: 8px; }
  .bad .score { color: #7d2b2b; }
  .good .score { color: #1f4436; }
  .meta { display: block; font-weight: 400; color: #5d6d87; font-size: 12px; margin-top: 2px; }
  .moved { margin: 8px 0; padding-left: 18px; color: #5d6d87; font-size: 12px; }
  .moved em { color: #10203a; font-style: normal; }
  .pair { display: flex; gap: 16px; align-items: flex-start; }
  figure { margin: 0; }
  img { width: ${WIDTH}px; max-width: 46vw; border: 1px solid #dcd7cc; display: block; }
  figcaption { font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: #5d6d87; padding-top: 4px; }
</style>
<h1>Mobile stability at ${WIDTH}px &mdash; ${sheet.filter((s) => !s.screenChange && s.score > s.budget).length} of ${sheet.length} interactions over budget</h1>
${rows}`
);

await context.close();
await browser.close();

console.log("\n  interaction                       shift   scrollY        height");
for (const r of sheet) {
  const over = !r.screenChange && r.score > r.budget;
  console.log(
    "  " +
      (r.name + " ".repeat(33)).slice(0, 33) +
      r.score.toFixed(4) +
      "  " +
      (r.scrollY[0] + "->" + r.scrollY[1]).padEnd(13) +
      " " +
      r.docHeight[0] + "->" + r.docHeight[1] +
      (over ? "   OVER BUDGET" : "") +
      (r.screenChange ? "   (screen change)" : "")
  );
}

console.log(`\ncontact sheet: ${OUT}/index.html`);
console.log(
  `${failures === 0 ? `PASS — ${checks} checks` : `FAIL — ${failures} of ${checks} checks failed`}`
);
process.exit(failures === 0 ? 0 : 1);
