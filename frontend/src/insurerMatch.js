/*
  Does a pasted rejection letter name a policy other than the one selected?

  Its own module because the matching rules are fiddly enough to deserve a
  test that does not need a browser. verify_insurer_match.mjs imports it
  directly, and both of the rules below exist because that test caught them
  failing.

  Case i of the 9 Sep matrix: an HDFC letter filed against Star returned a
  confident, well-reasoned finding about Star. Retrieval was correct — it
  searched the policy the reader chose, and cross-insurer contamination is
  impossible because retrieve() filters on policy_id before ranking — but
  nothing anywhere said the letter names a different insurer.

  Deterministic, not a model call: the six insurer and policy names are known,
  and a string match is something a reader can check for themselves.

  BOTH DIRECTIONS OF ERROR ARE COSTLY. A miss leaves someone reading a
  confident answer about the wrong document. A false positive tells someone
  their correct choice is wrong, on a screen they are already anxious about.
*/

const escapeRe = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/*
  Which known insurers and policies does this letter name?

  Two rules, each of which was wrong in the first version:

  1. LONGEST NAME FIRST, and a match is consumed. "ReAssure" is a substring of
     "ReAssure 3.0", so without this a ReAssure 3.0 letter also reports plain
     ReAssure and the two cancel out.

  2. A SINGLE-WORD POLICY NAME MUST BE CAPITALISED to count. Two of the six
     are ordinary English words — "Elevate" and "ReAssure" — and "undertaken
     to elevate the patient's quality of life" is a sentence a rejection
     letter might really contain. A product name is a proper noun and appears
     capitalised (or upper-cased) in any letter that means it. Multi-word
     names are distinctive enough to match without regard to case.
*/
export function namesInLetter(letter, policies) {
  // Original case is kept: rule 2 needs it. Only whitespace is normalised.
  let hay = " " + String(letter || "").replace(/\s+/g, " ") + " ";

  const terms = [];
  for (const p of policies) {
    terms.push({ kind: "policy", id: p.policy_id, term: p.policy_name });
    terms.push({ kind: "insurer", id: p.insurer, term: p.insurer });
  }
  terms.sort((a, b) => b.term.length - a.term.length);

  const policyIds = new Set();
  const insurers = new Set();

  for (const { kind, id, term } of terms) {
    const oneWord = !/\s/.test(term);
    const re = new RegExp(
      "(^|[^A-Za-z0-9])(" + escapeRe(term) + ")([^A-Za-z0-9]|$)",
      "gi"
    );

    let hit = false;
    hay = hay.replace(re, (whole, before, matched, after) => {
      // Rule 2: an all-lowercase single-word match is the English word, not
      // the product. Leave it in place so nothing else is disturbed.
      if (oneWord && !/^[A-Z]/.test(matched)) return whole;
      hit = true;
      // Rule 1: blank the match so a shorter name cannot match inside it.
      return before + " ".repeat(matched.length) + after;
    });

    if (hit) {
      if (kind === "policy") policyIds.add(id);
      else insurers.add(id);
    }
  }

  return { policyIds, insurers };
}

/*
  A precedence ladder, most specific evidence first. The policy name is a
  stronger signal than the insurer name, because two of the six policies share
  an insurer and the insurer alone cannot tell them apart — a "ReAssure 3.0"
  letter names "Niva Bupa" too, and treating that as reassurance silenced a
  real mismatch.

    1. the selected policy is named          -> quiet
    2. a different policy is named           -> warn, naming it
    3. the selected insurer is named         -> quiet
    4. a different insurer is named          -> warn, naming it
    5. nothing recognised                    -> quiet

  Step 2 above step 3 means a portability letter that names the previous
  policy in full and the current one only by insurer does warn. That is
  deliberate: it is a genuine ambiguity, the reader is better placed to
  resolve it than we are, and the copy on the screen tells them they can
  ignore it if the letter is simply referring to a previous insurer.
*/
export function insurerMismatch(letter, policy, policies) {
  if (!letter || !policy || !policies?.length) return null;
  const { policyIds, insurers } = namesInLetter(letter, policies);

  if (policyIds.has(policy.policy_id)) return null;

  const others = policies.filter(
    (p) => p.policy_id !== policy.policy_id && policyIds.has(p.policy_id)
  );
  if (others.length) {
    return { named: [...new Set(others.map((p) => `${p.insurer} ${p.policy_name}`))] };
  }

  if (insurers.has(policy.insurer)) return null;

  const otherInsurers = [...insurers].filter((i) => i !== policy.insurer);
  if (otherInsurers.length) return { named: otherInsurers };

  return null;
}
