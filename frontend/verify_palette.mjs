// The palette, checked as a system. No browser, no API, no model.
//
// WHY THIS EXISTS
//
// Deepening the surfaces nearly shipped a bug that nothing would have caught.
// rule-soft was #ebe7de at L*91.7 and the new paper-sunk was L*92.8, so a
// hairline would have been LIGHTER than the surface it was drawn on and
// simply disappeared. ochre-tint had the same defect against the new paper:
// 1.02:1, a callout ground indistinguishable from the page.
//
// Neither is visible in a diff, neither breaks a layout, and neither shows up
// in an overflow or stability gate. They are arithmetic, so they are
// checkable.
//
// WHAT IT HOLDS TO
//
//   1. Every rule clears MIN_RULE on every ground it is drawn on. Declared
//      pairs, like the text pairs below: the first version checked every rule
//      against every surface and failed immediately on rule-soft against
//      paper-deep, which is correct arithmetic about a combination the design
//      does not use and cannot satisfy — a soft hairline and the deepest
//      paper stock are 1.01:1 apart and no honest value fixes that. The
//      declaration is the design decision, written down.
//   2. The neutral ramp keeps its depth — adjacent surfaces at least MIN_STEP
//      apart in L*, so "paper" and "sunk" can never drift back together.
//   3. Every declared text-on-surface pair clears AA for normal text. The
//      pairs are declared rather than inferred, because a stylesheet cannot
//      tell you what sits on what — and declaring them forces the thought
//      when a new combination is introduced.
//   4. Every callout ground is distinguishable from the page it sits on.
//
//   npm run verify:palette
//
// Exits non-zero on any failure.

import { readFileSync } from "node:fs";

const CSS = readFileSync("src/theme.css", "utf-8");

/* ------------------------------------------------------------- colour maths */

const srgb = (c) => {
  c /= 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
const lum = (hex) => {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
};
const Lstar = (hex) => {
  const Y = lum(hex);
  return Y > 0.008856 ? 116 * Y ** (1 / 3) - 16 : 903.3 * Y;
};
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
};

/* --------------------------------------------------------------- the tokens */

const palette = {};
for (const m of CSS.matchAll(/--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
  palette[m[1]] = m[2].toLowerCase();
}

// Grounds anything can be drawn on.
const SURFACES = [
  "card",
  "paper",
  "paper-sunk",
  "paper-chip",
  "paper-deep",
  "ochre-tint",
  "upheld-tint",
  "contest-tint",
];

// The neutral ramp, lightest first. Depth is asserted along this order.
const RAMP = ["card", "paper", "paper-sunk", "paper-chip", "paper-deep"];

/*
  Which hairline is drawn on which ground. A border sits at a boundary, so it
  is judged against both sides: the exhibit's side border is drawn on card and
  seen against the band behind it.
*/
const RULE_ON = [
  ["rule", "card"], ["rule", "paper"], ["rule", "paper-sunk"],
  ["rule", "paper-chip"], ["rule", "paper-deep"],
  ["rule-soft", "card"], ["rule-soft", "paper"], ["rule-soft", "paper-sunk"],
];

/*
  Text on ground, as the design actually uses it. Declared, not inferred: a
  stylesheet cannot tell you what sits on what, and writing the pair down is
  the moment someone has to think about whether it is readable.
*/
const TEXT_ON = [
  ["ink", "card"], ["ink", "paper"], ["ink", "paper-sunk"], ["ink", "paper-chip"],
  ["ink", "ochre-tint"], ["ink", "upheld-tint"],
  ["ink", "paper-deep"],
  ["ink-2", "card"], ["ink-2", "paper"], ["ink-2", "paper-sunk"], ["ink-2", "paper-chip"],
  // paper-deep is the exhibit band. ink-soft measures 3.20:1 there and cannot
  // be used, so its label steps up to ink-2 — the surface deepening spending
  // the contrast budget, made concrete.
  ["ink-2", "paper-deep"],
  ["ink-soft", "card"], ["ink-soft", "paper"], ["ink-soft", "paper-sunk"],
  ["ink-verbatim", "card"], ["ink-verbatim", "paper"],
  ["ochre", "ochre-tint"], ["ochre", "paper"],
  ["insurer", "card"], ["insurer", "paper"],
  // The paper-coloured type that sits on the two saturated grounds.
  ["paper", "contest"], ["paper", "contest-deep"],
];

const MIN_RULE = 1.2; // a hairline must be visible on its ground
const MIN_STEP = 2.0; // L*, so two surfaces never read as one field
const MIN_TEXT = 4.5; // WCAG AA, normal text
const MIN_GROUND = 1.08; // a callout must not vanish into the page

let failures = 0;
let checks = 0;
const ok = (name, cond, detail = "") => {
  checks++;
  if (cond) console.log(`  ok    ${name}`);
  else {
    failures++;
    console.log(`  FAIL  ${name}${detail ? `\n          ${detail}` : ""}`);
  }
};

/* ------------------------------------------------------------- the report */

console.log("SURFACES");
for (const s of SURFACES) {
  if (!palette[s]) continue;
  console.log(`  ${s.padEnd(14)} ${palette[s]}  L*${Lstar(palette[s]).toFixed(1).padStart(6)}`);
}
console.log("\nINK");
for (const t of ["ink", "ink-verbatim", "ink-2", "ink-soft"]) {
  if (!palette[t]) continue;
  console.log(
    `  ${t.padEnd(14)} ${palette[t]}  L*${Lstar(palette[t]).toFixed(1).padStart(6)}` +
      `   on paper ${ratio(palette[t], palette.paper).toFixed(2)}:1`
  );
}
console.log("");

/* ------------------------------------------------- 1. rules against grounds */

console.log("every rule is visible on the grounds it is drawn on");
for (const [r, g] of RULE_ON) {
  if (!palette[r] || !palette[g]) {
    ok(`${r} on ${g}: both defined`, false);
    continue;
  }
  const v = ratio(palette[r], palette[g]);
  ok(
    `${r} on ${g} is ${v.toFixed(2)}:1`,
    v >= MIN_RULE,
    `needs ${MIN_RULE}:1 — a hairline lighter than its ground disappears`
  );
}

/* ------------------------------------------------------ 2. the ramp's depth */

console.log("\nthe neutral ramp keeps its depth");
for (let i = 0; i < RAMP.length - 1; i++) {
  const [a, b] = [RAMP[i], RAMP[i + 1]];
  if (!palette[a] || !palette[b]) {
    ok(`${a} -> ${b} both defined`, false);
    continue;
  }
  const step = Lstar(palette[a]) - Lstar(palette[b]);
  ok(
    `${a} -> ${b} steps down ${step.toFixed(1)} L*`,
    step >= MIN_STEP,
    `needs ${MIN_STEP} L* — below that two surfaces read as one field`
  );
}
const span = Lstar(palette[RAMP[0]]) - Lstar(palette[RAMP[RAMP.length - 1]]);
ok(`the ramp spans ${span.toFixed(1)} L*`, span >= 10, "was 5.9 and read as one field");

/* --------------------------------------------------------- 3. text on ground */

console.log("\ntext clears AA on every ground it is used on");
for (const [t, s] of TEXT_ON) {
  if (!palette[t] || !palette[s]) {
    ok(`${t} on ${s}: both defined`, false);
    continue;
  }
  const v = ratio(palette[t], palette[s]);
  ok(`${t} on ${s} is ${v.toFixed(2)}:1`, v >= MIN_TEXT, `needs ${MIN_TEXT}:1`);
}

/* ------------------------------------------------------ 4. callouts show up */

console.log("\na callout ground is distinguishable from the page");
for (const s of ["ochre-tint", "upheld-tint", "contest-tint", "paper-sunk"]) {
  if (!palette[s]) continue;
  const v = ratio(palette[s], palette.paper);
  ok(
    `${s} vs paper is ${v.toFixed(2)}:1`,
    v >= MIN_GROUND,
    `needs ${MIN_GROUND}:1 — below that the block vanishes into the page`
  );
}

console.log(
  `\n${failures === 0 ? `PASS — ${checks} checks` : `FAIL — ${failures} of ${checks} checks failed`}`
);
process.exit(failures === 0 ? 0 : 1);
