# Claim Decoder — handoff

Read this first. It encodes things that took a long time to discover and are
not obvious from the code.

Last substantially revised 31 Aug 2026, after a week of corpus repair. The
sections marked **NEW** did not exist before that and contain the findings
most likely to be re-discovered the hard way.

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

**But know exactly how narrow that promise is.** `verify_verbatim` proves a
clause appears in the *extracted page text*. It does not prove the extracted
page text resembles the *printed page*, and it does not prove the clause is
whole. Both of those failed silently for months. See "The silent-loss family".

---

## Current state, working end to end

| Layer | What | Where |
|---|---|---|
| Frontend | React + Vite, plain CSS | `https://project-37e668b0-6b36-4e1f-a02.web.app` |
| Backend | FastAPI on Cloud Run | `https://claim-decoder-api-793807740598.asia-south1.run.app` |
| Data | BigQuery, 965 clauses + embeddings | dataset `claims` |
| Models | Gemini via Vertex AI | `gemini-3.6-flash` |
| Repo | private | `github.com/gupta19esha/claim-decoder` |

GCP project `project-37e668b0-6b36-4e1f-a02`, region `asia-south1`. Free trial
credits, expiring 16 Nov 2026.

Verified end to end on 31 Aug 2026: a pasted HDFC rejection returns
`well_supported` at 0.95 confidence citing Excl01 on page 30 with its 36-month
waiting period, and correctly reasons that 14 months of coverage is short of it.

### Corpus

965 clauses across five insurers and six policies.

| Policy | Clauses |
|---|---|
| ICICI Lombard Elevate | 223 |
| Niva Bupa ReAssure | 167 |
| HDFC Ergo Optima Secure | 164 |
| Niva Bupa ReAssure 3.0 | 153 |
| Tata AIG Medicare Select | 135 |
| Star Health Arogya Sanjeevani | 123 |

Plus 146 IRDAI non-payable items in `irdai_non_payable_items`. IRDAI-mandated
and identical across insurers, so one canonical copy serves all. Do not
re-extract them per policy: four of six documents parse those lists wrongly.

BigQuery tables: `claims.clauses`, `claims.clauses_embedded` (768 dims,
`text-embedding-004` via connection `vertex_conn`), `claims.embedder`,
`claims.irdai_non_payable_items`.

Backups from the 31 Aug rebuild: `clauses_backup_20260831` (the original 953),
`clauses_embedded_backup_20260831`, `clauses_backup_v15_20260831`.

---

## Things that cost hours to find out

**Vertex needs `location="global"`.** Not `us-central1`. Newer Gemini models
404 on named regions. This is the single most opaque failure in the stack. The
`--location` default in `extract_policy_v13.py` is now `global`; it used to be
`us-central1`, which was a trap for anyone who omitted the flag.

**Gemini 3.6 rejects sampling parameters.** Passing `temperature` is an error,
not a warning.

**AI Studio and Vertex are separate wallets.** Google Cloud trial credits do
not fund AI Studio's prepay balance. Everything must go through Vertex.

**PowerShell mangles gcloud env vars.** Commas inside a value are read as
separators. Use the `^|^` delimiter form:
```
--set-env-vars "^|^ALLOWED_ORIGINS=a,b,c|REQUIRE_AUTH=false"
```
Backticks in BigQuery SQL are eaten by PowerShell double quotes. Put SQL in a
`.sql` file and pipe it: `Get-Content x.sql | bq query --use_legacy_sql=false`.

**`--max-instances 1` is load-bearing.** Cases live in an in-process dict, so a
POST and its polling GETs must hit the same instance. Firestore is the real fix.

**Windows writes cp1252 by default.** Opening output files without
`encoding="utf-8"` crashes on bullet characters. Also applies to reading
subprocess output in Python: `subprocess.run(..., encoding="utf-8")` or the
stage glyphs `○ ● ▸` will kill it.

**`bq` is not directly executable from Python on Windows.** It is a wrapper
script, so `subprocess.call(["bq", ...])` raises `FileNotFoundError`. Resolve
with `shutil.which` and pass `shell=True`. This is why `preload_check --load`
failed the first time it was ever used.

**IAM roles the compute service account needs**
(`793807740598-compute@developer.gserviceaccount.com`):
`bigquery.user`, `bigquery.dataViewer`, `bigquery.connectionUser`,
`aiplatform.user`, `cloudbuild.builds.builder`, `storage.objectViewer`,
`logging.logWriter`.

`bigquery.connectionUser` is the easy one to miss. Without it, table reads work
but `ML.GENERATE_EMBEDDING` fails, so retrieval breaks while everything else
looks healthy.

**`/debug/checks` exists for this.** It tests BigQuery, Gemini and retrieval
separately and names the failing one. Extend it rather than debugging logs.

**Background thread exceptions do not reach Cloud Run logs** unless explicitly
printed. `analyse()` prints its traceback to stderr for this reason.

**NEW — loading `claims.clauses` changes nothing a user sees.** `retrieve()`
queries `claims.clauses_embedded`, which is `clauses` plus an embedding
column. Load one without rebuilding the other and the API serves the old
corpus while looking perfectly healthy. `rebuild_embeddings.sql` does the
rebuild and takes about three seconds. Document task_type stays
`RETRIEVAL_DOCUMENT`; the query side in `retrieve()` uses `RETRIEVAL_QUERY`.
They are two halves of one asymmetric scheme and must stay paired.

**NEW — the genai client needs an explicit timeout.** Without one it blocks
forever on a network fault. A DNS outage mid-run left a socket waiting for an
answer that never came and the process sat there for three hours forty minutes
looking like a long job. `REQUEST_TIMEOUT_MS = 120_000` is passed via
`HttpOptions`. No amount of retry logic helps if control never returns to the
retry loop.

---

## NEW — the silent-loss family

Every serious corpus defect found this week has the same shape: **data goes
missing and the pipeline reports success.** The verbatim check passes, the
clause count looks plausible, and nothing is wrong on the surface. Assume any
new failure is one of these until proved otherwise.

**1. Page furniture spliced into clauses.** ICICI's footer address survived
stripping on 103 of 111 pages and was spliced into 22 clauses, cutting 10 of
them off mid-sentence including the definition of Pre-existing Disease. The
verbatim check passed legitimately, because the address really was in the
assembled page text.

*Cause:* `learn_furniture` capped a furniture line at 100 characters. The
footer's normalised key is 115. Every other line of the same footer block
(46–74 chars) was stripped correctly; only the long one survived.
*Fix:* `FURNITURE_MAX_LEN = 250`, used by both `learn_furniture` and
`is_furniture`. Repetition identifies furniture — measured across all six
documents, every line repeating on 50%+ of pages is furniture and none is body
text. The ceiling only guards against over-deletion: past some length a "line"
is a mis-assembled block, and the longest real printed line in any of the six
is 158 characters, so 250 leaves headroom.

**2. Clauses cut in half at chunk boundaries.** **78 of 127 length boundaries
cut a clause mid-sentence (61%). HDFC cut a clause at 23 of its 23.** Only 11
of those 78 left any trace in the corpus — the extractor usually drops the far
half rather than emitting it, so there is nothing to inspect.

*Fix:* `build_chunks(..., overlap_chars=1500)` carries the trailing 1500
characters of the page it just closed into the next chunk, cut at a line
boundary. **1500 is the 95th percentile of clause length** (median 321, p90
996), so it covers all but the longest 5% while adding at most 1500 characters
to a 6000-character chunk. Section flushes do not carry — the text would be
labelled with the section it is leaving.

The overlap duplicates text on purpose; `dedupe_records` removes copies
afterwards, dropping any clause wholly contained in another within one page.
That same rule also cleans up fragments the old chunking left behind. Two
guards: containment only counts within ±1 page, and the longer record is kept
whole rather than field-merged, because merging would let a number extracted
from a partial clause ride along on the complete one.

**3. Chunks that failed every retry returned `[]`.** Indistinguishable from
"this chunk had no clauses". A DNS blip cost two consecutive `waiting_period`
chunks of Star Health while the run reported success.
*Fix:* `call_gemini` returns `None` on exhaustion, never `[]`. Failed chunks
are listed by section and page range and the process exits 2.

**4. Pages sent to the model that produce nothing.** Between 19% and 41% of
sent pages produce no clause. Scattered pages are normal; a long contiguous run
is a section that vanished. HDFC's plan charts are 19 consecutive pages of it.
*Cause:* `extract_text()` linearises tables and destroys row/column
association, so values arrive before their labels and the extraction prompt
correctly tells the model to return nothing rather than guess.
*Detection:* `silent_page_run` in `preload_check`. Measured longest runs were
star 4, tata 5, icici 6, niva 9, niva30 17, hdfc 19, so the default ceiling of
8 sits above incidental gaps and below every genuine section loss.

---

## NEW — the mandatory gate

**`python preload_check.py <file>.jsonl` sits between extraction and BigQuery.
Run it, or do not load.** Exit 0 means safe. With `--load` the bq load runs
only on a clean pass, so the check and the load are the same command and
cannot be skipped by forgetting.

Checks: `truncated`, `starts_mid_sentence`, `continues_previous`,
`embedded_contact_details`, `empty`, plus manifest-derived `chunk_failed`,
`boundary_unrecovered`, `verbatim_rejection_rate` and `silent_page_run`.
`no_terminal_punctuation` is reported but does not block — 18% of the corpus
ends without a full stop and nearly all of it is headings and table rows.

**The run manifest** is written by the extractor next to its output
(`<out>.manifest.json`). It carries what the jsonl cannot show: failed chunks,
boundary damage, pages sent, verbatim rejection rate, dedupe count. A file
without a manifest cannot be vouched for and is blocked by default; use
`--allow-missing-manifest` only for files that predate manifests.

`--accept KIND=N` is a deliberate, recorded override. Findings are still
printed and the acceptance is echoed next to the pass so it cannot be mistaken
for a clean file. `bq load` appends by default — pass `--replace` when swapping
a corpus, or it silently doubles.

Gate calibration details worth keeping:
- Dangling-word detection is case-sensitive. `"...13 Hepatitis A"` is complete;
  `"...endorsements or"` is not.
- A clause ending on a bare URL is fine. Grievance clauses end
  `"...bimabharosa.irdai.gov.in"`, whose last word is "in".
- A definition whose body opens `"means ..."` is not a fragment. The term is
  the heading.
- Enumeration is not always punctuated: `"a If the Insured Person..."` is a
  list item, not a cut.
- The address gate scores two independent signals rather than pattern-matching,
  because "Road" appears in hospital names and six-digit numbers appear in sums
  insured. Contact clauses (grievance, ombudsman, notices) are exempt.

---

## Extraction pipeline

`extract_policy_v13.py`. What it handles:

- **Two-column detection by gutter analysis**, scanning only the page body.
- **Repeated-line furniture stripping**, matched on a shared prefix because the
  gutter varies from 0.496 to 0.518 and cuts at a different character each page.
  Fuzzy matching is restricted to column edges: applying it everywhere ate seven
  real rows from a benefits table.
- **Page-accurate `source_page`.** Stamping the chunk's first page made roughly
  half the citations wrong.
- **Verbatim check** with unicode normalisation, hyphenation repair and a
  longest-contiguous-run fallback. Rejection rates run 0 to 4.4%. Above 20%
  means that document needs attention.
- **Chunk overlap and dedupe** (above).
- **A boundary report printed on every run**, before the `--dry-run` and
  `--items-only` branches, so nobody can extract a document without seeing how
  many boundaries cut a clause.

Usage:
```
python extract_policy_v13.py "policy.pdf" --insurer "X" --policy-name "Y" \
  --policy-id z --dry-run          # free, check column order first
python extract_policy_v13.py "policy.pdf" --insurer "X" --policy-name "Y" \
  --policy-id z --out z_v15.jsonl --vertex \
  --project project-37e668b0-6b36-4e1f-a02 --location global --rpm 0
python preload_check.py z_v15.jsonl        # then, and only then
```

Always dry-run first and read the chunk dump. If sentences jump mid-clause the
columns are scrambled and everything downstream is garbage.

Re-extract **per policy**, not as one batch: a failure costs one policy instead
of six and any policy can be re-run alone. `reextract_per_policy.sh` does this
and runs `preload_check` after each. Sequential, not parallel — six concurrent
runs share one Vertex quota.

---

## NEW — numbers, and why the second pass filled nothing

`waiting_period_days`, `monetary_cap` and `percent_cap` were never covered by
the verbatim check. They are model output, including the month-to-day
arithmetic the prompt asks for.

An audit re-derived all three from `clause_text` by deterministic parsing
(`audit_numeric_fields.py`). **Disagreement rate was 1.1%** — the numbers that
exist are almost all faithful. The problem was that they mostly did not exist:
5.4% of clauses carry a waiting period, 2.7% a rupee cap, 3.7% a percentage.

A targeted second pass (`numeric_pass.py`) ran over 32 candidates with a
numbers-only prompt, gated three ways: the evidence span must appear verbatim
in `clause_text`, the number must be derivable from *that span alone*, and the
conversion must be the mandated months × 30.

**It filled zero fields and corrected four. Zero fills was the correct
answer.** The deterministic parser was saying "there is a rupee figure in this
text"; the model, asked precisely and told never to infer, said "yes, and it is
not a cap" — a sum insured tier, an example, a bonus threshold. A parser can
find a number; only the reading tells you what it is. Do not treat low numeric
coverage as a bug to be fixed by extracting harder.

The four corrections were values with no basis in the source: three
`percent_cap: 100.0` on clauses whose text lists a *table* of percentages by
body part, and one `monetary_cap: 4500` that appears nowhere in the clause.
Inference presented as extraction. **The corpus now has zero numeric
disagreements.**

Scope was deliberately narrow: `exclusion`, `waiting_period`, `limit`,
`coverage`. 35 further clauses in `condition` and `definition` have parseable
durations and every one sampled is a grace period, policy year, portability
window or critical-illness survival period. The deterministic parser cannot
tell those from a waiting period, so widening the scope would write wrong
values into the field a date tracker computes from.

---

## NEW — room rent caps live in the Policy Schedule. This is load-bearing.

**For four of six policies the room rent cap is not in the policy wording at
all. It is in the customer's Policy Schedule.**

| policy | room sentences | with a number | deferring to Schedule |
|---|---|---|---|
| star | 3 | 1 | 0 |
| hdfc | 28 | 3 | 9 |
| icici | 19 | 1 | 6 |
| niva | 4 | 0 | 1 |
| niva30 | 4 | 0 | 1 |
| tata | 14 | 0 | 6 |

Tata: *"Room Rent, Boarding, Nursing Expenses… up to the room category
specified in the Policy Schedule."*
Niva 3.0: *"…higher than the eligible room category as specified in your
Policy Schedule."*

Only Star has a hard cap in the wording (*"up to 2% of the Sum Insured subject
to maximum of Rs.5000"*), because Arogya Sanjeevani is a standardised IRDAI
product with fixed sub-limits. ICICI has one only via an optional cover that
must be purchased.

**HDFC's zero `monetary_cap` is correct, not a defect.** The wording says
*"Room rent limit shall be 'At Actuals' unless otherwise specified in the
Policy Schedule."* Optima Secure has no room cap. Confirmed a second way by
structured table extraction of its plan chart: `Room Rent | At Actuals` across
every plan variant. Do not go looking for a missing number here.

**What this means for the bill auditor.** The room-rent half is not buildable
from a generic policy for four of six products; it needs the customer's
Schedule. The feature splits cleanly:
- *Generic, buildable today:* the 146 IRDAI non-payable items, identical across
  insurers, already in BigQuery, completely unused. That is the larger part of
  most deduction disputes.
- *Needs the customer's Schedule:* room rent, ICU caps, sub-limits, deductibles.

That is a product decision, not a technical one.

**Benefit tables are not worth extracting** for this reason. They can be
recovered — `pdfplumber`'s `extract_tables()` returns HDFC's plan chart intact
where `extract_text()` scrambles it — but the numbers recovered are still
plan-variant dependent and the room cap still lives in the Schedule. Two of the
six have no benefit-table heading in the text at all; two more have headings
`SECTION_MARKERS` does not recognise (`"Annexure C - Plan Chart"`,
`"Annexure I - Product Benefit Table"`). Fixing the classifier alone would
achieve nothing, because the pages are already being sent and come back empty.

---

## Known gaps

- **Six List I items missing** from Star's Annexure, serials 9, 20, 21, 24, 25,
  54, 58, where a long name wrapped and the serial got stranded. Fails safe.
- **ICICI Elevate section labels are wrong.** Clause text is fine; the label is
  advisory only. Do not filter by `section` for that policy.
- **`exclusion_code` is a mention, not an identifier.** ICICI has three rows
  matching Excl01 — the governing exclusion (1080 days), an optional cover that
  reduces it (720), and a 91-character cross-reference (null). Any lookup keyed
  on `exclusion_code` gets three answers. A gate asserting "Excl01 present"
  passes on the strength of the cross-reference.
- **`exclusion_code` has no canonical form.** 42 distinct values for 18 codes:
  `Excl 01`, `Excl01`, `Exel 01`, `Code-Exel 10`. Tata's wording genuinely
  prints "Exel" — the typo is the insurer's — but the model transcribed it
  inconsistently, preserving it 6 times and silently correcting it 9 times.
  Normalise before keying anything on this field.
- **`cap_basis` is paraphrase, not transcription.** Only 24% of it appears
  verbatim in the clause; the prompt asks for a normalised descriptor. It
  reaches nobody today, but becomes load-bearing the moment a bill auditor
  needs to know whether a cap is per-day or per-year.
- **`clause_title` and `exclusion_code` are user-visible and unguarded.** 96.4%
  and 87.7% verbatim respectively.
- **8 accepted gate findings are live in the corpus**: 5 truncations, 3
  mid-sentence starts, accepted via `--accept` and not fixed.
- **Three policies have a silent page run above the ceiling** and are only
  loadable with `--max-silent-run` raised: hdfc 19, niva30 17, niva 9.
- **Retrieval ranking is mediocre.** Cosine distances cluster 0.43 to 0.50.
  Deliberately unfixed: the agent layer picks the governing clause from 15
  candidates and does it well. Recall matters, rank does not.
- **In-memory case store.** Restart loses everything. Firestore is the fix, and
  brings DPDP obligations with it.
- **No auth.** `REQUIRE_AUTH=false`. Firebase verification is written and off.
- **`DEBUG_ERRORS`** must be off before any demo.
- **The appeal-letter verbatim check only inspects quoted spans** of 25+
  characters. An unquoted paraphrase of policy wording passes untouched, and
  the verdict `explanation` and both advocate positions are never checked.

---

## Product notes

**The moat is the corpus and the verbatim guarantee.** The interface is
replicable in an afternoon. Extraction across insurer-specific PDF layouts is
not — and the week of repair above is why.

**Handling rejection letters means handling health data.** Diagnoses are
sensitive personal data under India's DPDP Act. The current in-memory store is
accidentally the most private possible design. Adding Firestore is a deliberate
decision to take on those duties.

**Check the IRDAI perimeter before charging.** Quoting a public document and
reasoning about it is closer to journalism than broking. Charging for outcomes,
or producing letters people file unmodified, is worth checking properly.

**Decide who pays.** A person with a freshly rejected claim is stressed and
unlikely to pay upfront. Hospital TPA desks and claim-assistance firms have
budget and volume.

---

## Working style

Short, direct messages. One numbered sequence of steps, not a decision tree.
Explicit file paths and full commands, since the environment is PowerShell on
Windows. Confirm what a command does before running it.

---

## Research findings, 28 Aug 2026, n=8, directional only

- **0 of 6** Indian respondents suspected the insurer might be wrong.
- **4 of 6** let it go: "assumed it would not work", "too much effort for the
  amount", "was too unwell to deal with it".
- **3 found the relevant clause themselves** and still gave up.
- Only **1 of 8** preferred verbatim clause quoting over a persuasive letter.
- Amounts were not trivial: one over Rs 5 lakh, three at Rs 1-5 lakh.

**Implication.** The blocker is belief and effort, not comprehension. A tool
that explains the clause well does not address either. The verbatim guarantee
is a quality mechanism that stops the system generating nonsense, not a feature
users are buying.

**Known form bug.** The India branch did not skip the US section, so Indian
respondents were asked about EOBs. Their India answers are valid; their US
answers are noise. Fix before collecting more.

---

## Direction

A claim rejection happens to someone perhaps once every few years. That is
fatal for retention. The product cannot be built only around the rejection
moment.

**The asset is structured, verifiable knowledge of what a policy actually
says.** Build order:

1. **Bill auditor, non-payable items only.** The 146 IRDAI items are generic,
   already in BigQuery, and unused. Deductions happen on almost every claim
   while outright rejection is rarer. Needs no persistence, no auth, no
   account. Do not promise room-rent checking without the customer's Schedule.
2. **Policy vault.** Upload once, keep a decoded version. Requires Firestore,
   auth and DPDP duties — the largest infrastructure and legal surface in the
   roadmap.
3. **Waiting period tracker.** "Your PED exclusion expires 14 March 2027."
   Needs both persistence and trustworthy `waiting_period_days`.
4. **Rejection decoder.** The current product, as one screen of a larger one.
5. **Escalation.** Grievance letter, deadline clock, Bima Bharosa route,
   Ombudsman filing. The deadline clock converts inertia into action better
   than argument does. Highest leverage on the research, last in dependencies.

Two features worth adding to the decoder regardless:

- **Lead with a recovery estimate**, not a verdict. But note the numeric
  coverage above: this is computable for far fewer claims than it looks.
- **Read the insurer and policy from the rejection letter.** Half the
  respondents did not have their policy document. Beware: `retrieve()` filters
  by `policy_id` before ranking, and that filter is the only thing preventing
  confidently wrong clauses from the wrong insurer. Auto-detection needs a
  confirmation step and an explicit "this policy is not in the corpus" path.

**B2B is worth naming.** Hospital TPA desks handle rejections daily, have
budget, and do this manually today. Same corpus, different interface.
