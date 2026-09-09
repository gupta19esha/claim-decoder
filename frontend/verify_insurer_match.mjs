// The insurer-mismatch matcher, unit tested. No browser, no API, no model.
//
// This decides whether a reader is told "your letter mentions X but you chose
// Y" above a finding. Both directions of error are costly: a miss leaves
// someone reading a confident answer about the wrong document, and a false
// positive tells someone their correct choice is wrong, on a screen they are
// already anxious about.
//
// The traps it is built around, all of which are real:
//   * "ReAssure" is a substring of "ReAssure 3.0"
//   * a letter may legitimately name a previous insurer during portability
//   * "Elevate" is an ordinary English word
//
//   npm run verify:insurer-match
//
// Exits non-zero on any failure.

import { insurerMismatch, namesInLetter } from "./src/insurerMatch.js";
import { POLICIES } from "./verify_mobile_fixtures.mjs";

const policies = POLICIES.insurers.flatMap((i) =>
  (i.policies || []).map((p) => ({ ...p, insurer: i.insurer }))
);
const by = (id) => policies.find((p) => p.policy_id === id);

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

const HDFC_LETTER =
  "We regret to inform you that your claim under policy Optima Secure has " +
  "been repudiated. As per Exclusion Excl01 of the policy wording, treatment " +
  "of a pre-existing disease is excluded until the expiry of 36 months.";

console.log(`${policies.length} policies loaded\n`);

/* ------------------------------------------------- it fires when it should */

console.log("it warns on a real mismatch");

const m1 = insurerMismatch(HDFC_LETTER, by("star_arogya_sanjeevani"), policies);
ok("case i: HDFC letter, Star selected", !!m1);
ok(
  "  and it names HDFC Ergo Optima Secure",
  m1?.named?.includes("HDFC Ergo Optima Secure"),
  JSON.stringify(m1)
);

const m2 = insurerMismatch(
  "Your claim with Niva Bupa under ReAssure 3.0 is denied.",
  by("niva_reassure"),
  policies
);
ok(
  "the substring trap: a ReAssure 3.0 letter against ReAssure warns",
  !!m2 && m2.named.includes("Niva Bupa ReAssure 3.0"),
  JSON.stringify(m2)
);

const m3 = insurerMismatch(
  "This is a communication from Star Health regarding your claim.",
  by("hdfc_optima_secure"),
  policies
);
ok(
  "insurer named without a policy name still warns",
  !!m3 && m3.named.includes("Star Health"),
  JSON.stringify(m3)
);

/* ------------------------------------------------ it stays quiet otherwise */

console.log("\nit stays quiet when it should");

ok(
  "the matching policy is named: no warning",
  insurerMismatch(HDFC_LETTER, by("hdfc_optima_secure"), policies) === null
);
ok(
  "the matching insurer is named without the policy: no warning",
  insurerMismatch(
    "HDFC Ergo has reviewed your claim and repudiated it.",
    by("hdfc_optima_secure"),
    policies
  ) === null
);
ok(
  "portability: both named, the selected one among them, no warning",
  insurerMismatch(
    "Your policy was ported to Star Health Arogya Sanjeevani from HDFC Ergo " +
      "Optima Secure. The claim is denied under the waiting period.",
    by("star_arogya_sanjeevani"),
    policies
  ) === null
);
ok(
  "a letter naming nobody: no warning",
  insurerMismatch(
    "We regret to inform you that your claim has been repudiated under the " +
      "pre-existing disease waiting period of 36 months.",
    by("hdfc_optima_secure"),
    policies
  ) === null
);
ok(
  "the ReAssure 3.0 reader gets no warning from their own letter",
  insurerMismatch(
    "Your claim under ReAssure 3.0 is denied.",
    by("niva_reassure_30"),
    policies
  ) === null
);

/*
  A deliberate decision, recorded so it is not mistaken for a bug. A
  portability letter that names the previous policy in full and the current
  one only by insurer DOES warn: step 2 of the ladder sits above step 3. The
  ambiguity is real, the reader can resolve it and we cannot, and the copy on
  the screen tells them to ignore it if the letter simply refers to a previous
  insurer.
*/
console.log("\nthe recorded ambiguity");
ok(
  "previous policy named in full, current one only by insurer: warns",
  !!insurerMismatch(
    "Your cover was ported from HDFC Ergo Optima Secure. Niva Bupa has " +
      "reviewed the claim and denied it under the waiting period.",
    by("niva_reassure"),
    policies
  )
);

/* ---------------------------------------------- the ordinary-word false positive */

console.log("\nordinary words are not policy names");

ok(
  '"elevate" used as a verb does not warn',
  insurerMismatch(
    "The treatment was undertaken to elevate the patient's quality of life. " +
      "The claim is denied under the waiting period.",
    by("hdfc_optima_secure"),
    policies
  ) !== null === false,
  JSON.stringify(
    insurerMismatch(
      "The treatment was undertaken to elevate the patient's quality of life.",
      by("hdfc_optima_secure"),
      policies
    )
  )
);

ok(
  "a word merely containing a policy name does not match",
  !namesInLetter("elevated enzymes and reassurance were noted", policies)
    .policyIds.size,
  JSON.stringify([
    ...namesInLetter("elevated enzymes and reassurance were noted", policies)
      .policyIds,
  ])
);

/* --------------------------------------------------------------- degenerate */

console.log("\nit does not throw on missing input");
ok("no letter", insurerMismatch("", by("hdfc_optima_secure"), policies) === null);
ok("no policy", insurerMismatch(HDFC_LETTER, null, policies) === null);
ok("no policies", insurerMismatch(HDFC_LETTER, by("hdfc_optima_secure"), []) === null);

console.log(
  `\n${failures === 0 ? `PASS — ${checks} checks` : `FAIL — ${failures} of ${checks} checks failed`}`
);
process.exit(failures === 0 ? 0 : 1);
