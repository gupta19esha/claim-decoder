# Claim Decoder — handoff

Read this first. It encodes things that took a long time to discover and are
not obvious from the code.

---

## What this is

A tool that checks whether a health insurance claim rejection is actually
supported by the policy wording, and quotes the clause verbatim with the page
number so the user can verify it themselves.

**The core promise is verbatim.** Clause text shown to a user, or quoted in an
appeal letter, must come from retrieved corpus records. Never from model
output. A paraphrased clause in an appeal letter cites language the policy does
not contain, which is worse than giving no answer. Every change must preserve
this.

---

## Current state, working end to end

| Layer | What | Where |
|---|---|---|
| Frontend | React + Vite, plain CSS | `https://project-37e668b0-6b36-4e1f-a02.web.app` |
| Backend | FastAPI on Cloud Run | `https://claim-decoder-api-793807740598.asia-south1.run.app` |
| Data | BigQuery, 953 clauses + embeddings | dataset `claims` |
| Models | Gemini via Vertex AI | `gemini-3.6-flash` |
| Repo | private | `github.com/gupta19esha/claim-decoder` |

GCP project `project-37e668b0-6b36-4e1f-a02`, name `claim-decoder`, region
`asia-south1`. Free trial credits, about ₹28,694, expiring 16 Nov 2026.

### Corpus

953 clauses across five insurers and six policies, all verbatim verified:

| Policy | Clauses |
|---|---|
| ICICI Lombard Elevate | 222 |
| HDFC Ergo Optima Secure | 166 |
| Niva Bupa ReAssure | 166 |
| Tata AIG Medicare Select | 149 |
| Niva Bupa ReAssure 3.0 | 144 |
| Star Health Arogya Sanjeevani | 106 |

Plus 146 IRDAI non-payable items in `irdai_non_payable_items`. These are
IRDAI-mandated and identical across insurers, so one canonical copy serves all
of them. Do not re-extract them per policy: four of six documents parsed those
lists wrongly, dumping everything into `not_payable`, which would tell a user
an item is never payable when it is actually subsumed into room charges.

BigQuery tables: `claims.clauses`, `claims.clauses_embedded` (768 dims,
`text-embedding-004` via connection `vertex_conn`), `claims.embedder`,
`claims.irdai_non_payable_items`.

---

## Things that cost hours to find out

**Vertex needs `location="global"`.** Not `us-central1`. Newer Gemini models
404 on named regions. This is the single most opaque failure in the stack.

**Gemini 3.6 rejects sampling parameters.** Passing `temperature` is an error,
not a warning.

**AI Studio and Vertex are separate wallets.** Google Cloud trial credits do
not fund AI Studio's prepay balance. Everything must go through Vertex or it
fails with "prepayment credits are depleted" while the console shows ₹28,694
unused.

**PowerShell mangles gcloud env vars.** Commas inside a value are read as
separators. Use the `^|^` delimiter form:
```
--set-env-vars "^|^ALLOWED_ORIGINS=a,b,c|REQUIRE_AUTH=false"
```
Backticks in BigQuery SQL are eaten by PowerShell double quotes. Put SQL in a
`.sql` file and pipe it: `Get-Content x.sql | bq query --use_legacy_sql=false`.

**`--max-instances 1` is load-bearing.** Cases live in an in-process dict, so a
POST and its polling GETs must hit the same instance. More instances means
random 404s. Firestore is the real fix.

**Windows writes cp1252 by default.** Opening output files without
`encoding="utf-8"` crashes on bullet characters in HDFC, Tata and ICICI
policies, after all the model calls have been paid for.

**IAM roles the compute service account needs**
(`793807740598-compute@developer.gserviceaccount.com`):
`bigquery.user`, `bigquery.dataViewer`, `bigquery.connectionUser`,
`aiplatform.user`, `cloudbuild.builds.builder`, `storage.objectViewer`,
`logging.logWriter`.

`bigquery.connectionUser` is the easy one to miss. Without it, table reads work
but `ML.GENERATE_EMBEDDING` fails, so retrieval breaks while everything else
looks healthy.

**`/debug/checks` exists for this.** It tests BigQuery, Gemini and retrieval
separately and names the failing one. It turned an unfalsifiable "analysis
could not be completed" into a one-line diagnosis. Extend it rather than
debugging through logs.

**Background thread exceptions do not reach Cloud Run logs** unless explicitly
printed. `analyse()` prints its traceback to stderr for this reason.

---

## Extraction pipeline

`extract_policy_v13.py`. Thirteen versions because each insurer's PDF breaks
differently. What it handles:

- **Two-column detection by gutter analysis**, scanning only the page body.
  Full-width header bands sit centred and defeat a naive scan.
- **Repeated-line furniture stripping.** Column cropping slices a header banner
  in half, so it arrives as two fragments no regex would anticipate. Lines
  appearing on most pages get dropped, matched on a shared prefix because the
  gutter varies from 0.496 to 0.518 and cuts at a different character each
  page. Fuzzy matching is restricted to column edges: applying it everywhere
  ate seven real rows from a benefits table.
- **Page-accurate `source_page`.** Pages are marked inline and returned per
  clause. Stamping the chunk's first page made roughly half the citations
  wrong.
- **Verbatim check** with unicode normalisation, hyphenation repair and a
  longest-contiguous-run fallback. Rejection rates ran 1 to 6 percent across
  insurers. Above 20 percent means that document needs attention.

Usage:
```
python extract_policy_v13.py "policy.pdf" --insurer "X" --policy-name "Y" \
  --policy-id z --dry-run          # free, check column order first
python extract_policy_v13.py "policy.pdf" --insurer "X" --policy-name "Y" \
  --policy-id z --out z_clauses.jsonl --vertex \
  --project project-37e668b0-6b36-4e1f-a02 --location global --rpm 0
```

Always dry-run first and read `dryrun_chunks.txt`. If sentences jump mid-clause
the columns are scrambled and everything downstream is garbage.

---

## Known gaps

- **Six List I items missing** from Star's Annexure, serials 9, 20, 21, 24, 25,
  54, 58, where a long name wrapped and the serial got stranded. Fails safe:
  those items are not recognised, never wrongly flagged.
- **ICICI Elevate section labels are wrong.** 21 chunks labelled
  `waiting_period`, only 1 `definition`, across 111 pages. Clause text is fine;
  the label is advisory only. Do not filter by `section` for that policy.
- **141 clauses have null `clause_id`, 68 null `clause_title`.** Frontend must
  handle blanks.
- **Retrieval ranking is mediocre.** Cosine distances cluster around 0.43 to
  0.50 and the right clause is often rank 3, not rank 1. This is deliberately
  unfixed: the agent layer picks the governing clause from 15 candidates and
  does it well. Recall matters, rank does not. Do not spend time here.
- **In-memory case store.** Restart loses everything. Firestore is the fix, and
  brings DPDP obligations with it.
- **No auth.** `REQUIRE_AUTH=false`. Firebase verification is written and
  switched off.
- **`DEBUG_ERRORS`** must be off before any demo.

---

## What to build next, in order

1. **Test other rejection types.** Only pre-existing disease on Star has ever
   been tested end to end. Try sub-limits, non-payable items, documentation
   rejections, on each insurer. This is where surprises live.
2. **Automated corpus quality gates.** Expected Excl codes present, Annexure
   counts in range, rejection rate thresholds. Right now a human reads
   `dryrun_chunks.txt` to decide if a document parsed correctly. That human is
   the bottleneck at 200 policies, and this is what makes the thing shippable.
3. **Homepage** — after step 1, because what you learn changes what it says.
4. Firestore, then auth, then more policies.

Do not broaden scope to other insurance products before one rejection type
works reliably across all six policies.

---

## Product notes

**The moat is the corpus and the verbatim guarantee.** The interface is
replicable in an afternoon. Extraction across insurer-specific PDF layouts is
not.

**Handling rejection letters means handling health data.** Diagnoses are
sensitive personal data under India's DPDP Act, with consent, retention and
breach obligations. The current in-memory store is accidentally the most
private possible design. Adding Firestore is a deliberate decision to take on
those duties, not a technical detail.

**Check the IRDAI perimeter before charging.** Quoting a public document and
reasoning about it is closer to journalism than broking. Charging for outcomes,
or producing letters people file unmodified, is worth checking properly. Cheap
now, expensive later.

**Decide who pays.** A person with a freshly rejected claim is stressed and
unlikely to pay upfront. Hospital TPA desks and claim-assistance firms have
budget and volume. This changes what gets built.

---

## Working style

Short, direct messages. One numbered sequence of steps, not a decision tree.
Explicit file paths and full commands, since the environment is PowerShell on
Windows. Confirm what a command does before running it.

---

## Research findings, 28 Aug 2026, n=8, directional only

Eight responses. Too few to conclude from, but the pattern is worth holding.

- **0 of 6** Indian respondents suspected the insurer might be wrong.
  Three assumed the insurer was right, two never considered it, one
  suspected but could not tell.
- **4 of 6** let it go. Reasons cluster on "assumed it would not work",
  "too much effort for the amount", and "was too unwell to deal with it".
- **3 found the relevant clause themselves** and still gave up.
- Only **1 of 8** preferred verbatim clause quoting over a persuasive
  letter. Three preferred the persuasive letter, two saw no difference.
- Amounts were not trivial: one over Rs 5 lakh, three at Rs 1-5 lakh.

**Implication.** The blocker is belief and effort, not comprehension. A tool
that explains the clause well does not address either. The verbatim guarantee
is a quality mechanism that stops the system generating nonsense, not a
feature users are buying.

**Known form bug.** The India branch did not skip the US section, so Indian
respondents were asked about EOBs and Evidence of Coverage. Their India
answers are valid; their US answers are noise. Fix before collecting more.

---

## Direction

A claim rejection happens to someone perhaps once every few years. That is
fatal for retention, and no number of features fixes it. The product cannot
be built only around the rejection moment.

**The asset is structured, verifiable knowledge of what a policy actually
says.** That is useful at four moments, of which the rejection is one.

Build order:

1. **Policy vault.** Upload once, keep a decoded version. Waiting periods as
   dates, caps as rupee figures, family members. This is the account people
   return to, and it is a pure derivation of data already extracted.
2. **Waiting period tracker.** "Your PED exclusion expires 14 March 2027."
   Computable today. Nobody in India does this.
3. **Bill auditor.** Discharge bill against the 146 IRDAI non-payable items
   and the room rent cap. Deductions happen on almost every claim while
   outright rejection is rarer, so this is likely bigger than the rejection
   tool.
4. **Rejection decoder.** The current product, as one screen of a larger one.
5. **Escalation.** Grievance letter, deadline clock, Bima Bharosa route,
   Ombudsman filing. The deadline clock in particular converts inertia into
   action better than argument does.

Two features worth adding to the existing decoder regardless:

- **Lead with a recovery estimate**, not a verdict. "Roughly Rs 1.4 lakh of
  this looks contestable." Largely computable from `monetary_cap`,
  `percent_cap` and `waiting_period_days`.
- **Read the insurer and policy from the rejection letter** instead of asking
  the user to pick. Half the respondents did not have their policy document,
  so the policy picker is a wall.

**The 146 IRDAI non-payable items are in BigQuery and completely unused.**
The bill auditor is the highest-value thing buildable from data that already
exists.

**B2B is worth naming.** Hospital TPA desks handle rejections daily, have
budget, and do this manually today. Same corpus, different interface.
Consumer builds the brand, B2B solves retention and pays for it.
