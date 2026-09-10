# Claim Decoder — handoff

Read this first. It encodes things that took a long time to discover and are
not obvious from the code.

Last substantially revised 31 Aug 2026, after a week of corpus repair. The
sections marked **NEW** did not exist before that and contain the findings
most likely to be re-discovered the hard way.

**If you read only one section, read "OPEN: text lost in column assembly".
It is the one defect still in the corpus that nothing in the pipeline can
see.**

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
| Data | BigQuery, 972 clauses + embeddings | dataset `claims` |
| Models | Gemini via Vertex AI | `gemini-3.6-flash` |
| Repo | private | `github.com/gupta19esha/claim-decoder` |

GCP project `project-37e668b0-6b36-4e1f-a02`, region `asia-south1`. Free trial
credits, expiring 16 Nov 2026.

Verified end to end on 31 Aug 2026: a pasted HDFC rejection returns
`well_supported` at 0.95 confidence citing Excl01 on page 30 with its 36-month
waiting period, and correctly reasons that 14 months of coverage is short of it.

### Corpus

972 clauses across five insurers and six policies.

| Policy | Clauses |
|---|---|
| ICICI Lombard Elevate | 227 |
| Niva Bupa ReAssure | 167 |
| HDFC Ergo Optima Secure | 165 |
| Niva Bupa ReAssure 3.0 | 153 |
| Tata AIG Medicare Select | 135 |
| Star Health Arogya Sanjeevani | 125 |

Plus 146 IRDAI non-payable items in `irdai_non_payable_items`. IRDAI-mandated
and identical across insurers, so one canonical copy serves all. Do not
re-extract them per policy: four of six documents parse those lists wrongly.

BigQuery tables: `claims.clauses`, `claims.clauses_embedded` (768 dims,
`text-embedding-004` via connection `vertex_conn`), `claims.embedder`,
`claims.irdai_non_payable_items`.

Backups, oldest first: `clauses_backup_20260831` (the original 953),
`clauses_embedded_backup_20260831`, `clauses_backup_v15_20260831`,
`clauses_backup_v16_20260831` (the 965 that preceded the furniture fixes).

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

**4. A bare page number spliced into a clause.** HDFC's Excl01 read "to the
extent of Sum 30 Insured increase", the printed folio dropped between two
words of a defined term. It went out inside a drafted appeal letter to a
grievance officer before anyone noticed. 24 clauses across HDFC and ICICI.

*Cause:* a line containing only a number matches no pattern in
`FURNITURE_PATTERNS`, and `learn_furniture` cannot learn it because the value
differs on every page. It was the one piece of page furniture with no
detector at all.
*Fix:* `learn_page_number_offset` learns the relationship between the printed
folio and the PDF index **per document**, then `is_page_number_line` strips
matching lines. The offset must be learned, not assumed: front matter means
the printed number rarely equals the PDF index. HDFC and ICICI came out at
offset 0; the other four documents have no bare-number folios at all and the
function correctly returns None, stripping nothing.

**5. A masthead sliced by the gutter, mid-column.** Star's
"MPANY LIMITED | POLICY WORDINGS" sat between items 05 and 06 of the
specified-disease list, and a page stamp "10 / 25" sat inside the 30-day
waiting period clause. 4 clauses.

*Cause:* two separate blind spots. `is_furniture` compared by common
**prefix**, which cannot see a fragment truncated at its start — "mpany
limited policy wordings" shares no first character with the learned "ompany
limited policy wordings". And fuzzy matching only ran at column edges,
because v9 applied it everywhere and ate seven real rows from a benefits
table; these fragments land mid-column.
*Fix:* containment matching at `CONTAINMENT_MIN = 25` characters, plus fuzzy
matching everywhere with the overlap requirement raised from 22 to 44
off-edge.

**Containment is one-directional, and the direction is load-bearing.** The
first version tested `key in known or known in key` and deleted real content:
ICICI's definition `"Company" means ICICI Lombard General Insurance Company
Limited.` and rows from Tata's benefit notes. A clause may legitimately
*contain* the insurer's name; a furniture fragment is contained *in* the
furniture. Only `key in known` is safe. If you ever loosen this, re-run the
newly-removed-lines check across all six documents before trusting it.

**6. Pages sent to the model that produce nothing.** Between 19% and 41% of
sent pages produce no clause. Scattered pages are normal; a long contiguous run
is a section that vanished. HDFC's plan charts are 19 consecutive pages of it.
*Cause:* `extract_text()` linearises tables and destroys row/column
association, so values arrive before their labels and the extraction prompt
correctly tells the model to return nothing rather than guess.
*Detection:* `silent_page_run` in `preload_check`. Measured longest runs were
star 4, tata 5, icici 6, niva 9, niva30 17, hdfc 19, so the default ceiling of
8 sits above incidental gaps and below every genuine section loss.

---

## OPEN: text lost in column assembly — the one defect nothing can see

**Status: unfixed, in the corpus now, and there is no gate for it.**

HDFC's Excl01 sub-clause iii reads

    "as defined under the period for the same would be reduced"

Every other insurer's copy of the same IRDAI-mandated clause reads

    "as defined under the applicable norms on portability stipulated by
     IRDAI, then waiting period for the same would be reduced"

Eighty-seven characters gone, and what remains still parses as a sentence, so
nothing looks wrong.

**Where it is lost.** Not in chunking, not in furniture stripping, not in the
model. `read_pdf` already returns page 31 with the words missing, and the
string "portability" appears nowhere on page 30 in either the column-cropped
or the uncropped extraction. It is gone at the pdfplumber text layer, before
any of our machinery runs. The furniture fixes of 31 Aug removed 24 page-
number splices and 4 masthead fragments and moved this count by zero, which
is the proof that it is a different defect: `page_text` crops two columns at
a learned gutter, and when the crop misplaces or drops a span, the two halves
are joined into a sentence that reads cleanly.

**Why nothing catches it.** Every gate we have detects something ADDED — a
page number, a masthead, an address, a truncation. An omission leaves nothing
behind. There is no shape to match, no residue, no length anomaly big enough
to trip a threshold. `verify_verbatim` passes, because the shortened text
really is what the extracted page says.

**The only detector we have, and its exact limit.** `excl_diff.py` works by
redundancy: Excl01 to Excl18 are IRDAI-mandated and near-identical across
insurers, so a span two or more insurers carry and one lacks is an omission.
That covers **eighteen clause codes and nothing else**. For every
insurer-specific clause — coverages, optional covers, conditions, definitions,
sub-limits, the great majority of the corpus — **we have no way of knowing
whether words are missing.** Assume some are.

Current reading, 31 Aug 2026: 24 omissions across Excl01 (8), Excl02 (12),
Excl16 (3), Excl18 (1). Fourteen of the Excl02 ones are the specified-disease
enumeration, which genuinely varies between insurers, so treat those as
suspect rather than certain. The high-confidence ones carry four or five
witnesses.

Two notes for whoever picks this up. `excl_diff.py` diffs every copy against
every other rather than against a chosen reference, and it has to: with the
longest copy as reference, ICICI's 3908-character Excl01 buried everything in
noise, and with the medoid as reference HDFC — the defective copy — was
itself the medoid for Excl01 and a reference is never diffed against itself.
Both designs silently reported the defect as absent.

The work, if it is ever worth doing, is in `page_text`: compare the
column-cropped assembly against the uncropped `extract_text()` per page and
flag pages where the crop loses tokens. That would generalise beyond the
eighteen codes. It is bounded and it is not a demo blocker.

---

## NEW — the mandatory gate

**`python preload_check.py <file>.jsonl` sits between extraction and BigQuery.
Run it, or do not load.** Exit 0 means safe. With `--load` the bq load runs
only on a clean pass, so the check and the load are the same command and
cannot be skipped by forgetting.

Checks: `truncated`, `starts_mid_sentence`, `continues_previous`,
`embedded_contact_details`, `masthead_fragment`, `page_number_splice`,
`empty`, plus manifest-derived `chunk_failed`, `boundary_unrecovered`,
`verbatim_rejection_rate` and `silent_page_run`.
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
- `masthead_fragment` scores a pipe, a page stamp with spaces around the
  slash, and a company-name tail including the truncated "MPANY LIMITED".
  A caps-run rule was tried and thrown away: ten hits, none real. Policy text
  is full of legitimate acronym runs, and CIN is cervical intraepithelial
  neoplasia at least as often as a corporate identity number.
- `page_number_splice` requires the number to sit between two words neither of
  which makes a number ordinary, to match the clause's own page or a
  neighbour, and the clause to carry fewer than three bare numbers — three or
  more means an enumerated list, not a splice.
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

## NEW — the v17 build, and how to repeat it

31 Aug 2026. Corpus went 965 → 972 clauses.

**Only three policies were re-extracted: HDFC, ICICI and Star.** Niva, Niva
3.0 and Tata were not, and this was deliberate rather than lazy. Neither
furniture fix changes their page text — verified at page level before
spending anything, which is free — so re-running them would have cost credits
to reproduce what we already had while swapping a known-good file for a
differently-sampled one. **Extraction is not deterministic. Never re-extract
a policy you have no reason to re-extract.**

That non-determinism is the main hazard in this process. Star's first re-run
lost pages 3 and 22 outright — 19 clauses, none of them absorbed elsewhere,
including a `limit` clause carrying room sub-limits. A second run recovered
page 22. Page 3 survives stripping with 2761 characters and sits in a kept
chunk, so nothing was broken; the model simply did not return it on either
run.

**`build_v17.py` is the assembler and the pattern to copy.** For each
re-extracted policy it takes the new run, finds what the new run dropped that
the old one had, and carries those clauses forward — **but only if they pass
the gates**. That last condition is what stopped the four
masthead-contaminated Star clauses returning through the side door: the
`masthead_fragment` gate refused them by name. Two HDFC clauses were refused
the same way, on `page_number_splice` and `truncated`.

Per policy: HDFC 164 → 165, ICICI 223 → 227, Star 123 → 125 (110 extracted,
15 recovered). Zero failed chunks, verbatim rejection 0.3 to 0.7 percent.

**Sweep, before and after** (`sweep_contamination.py`, free, no model calls):

| shape | before | after |
|---|---|---|
| page-number splice | 24 | **0** |
| masthead fragment | 4 | **0** |
| other stray numbers | 9 | 9 |

The nine survivors are legitimate and were judged individually: "RAI stage 3",
"3 occasions", "30 mm of Hg", "2/3 years". Omissions were 24 before and 24
after, for the reason set out in the column-assembly section above.

Backups from this build: `clauses_backup_v16_20260831`, and the earlier
`clauses_backup_20260831` and `clauses_backup_v15_20260831`.

---

## NEW — the mobile layout, and the one rule that holds it

7 Sep 2026. The narrow viewport had never been checked on any screen. It
overflowed horizontally, and the cause was a single missing wrapping rule
rather than anything structural — no grid, no fixed width, no absolute
positioning was at fault, and the layout needed no reworking.

**Every overflow came from text we did not write.** Policy wordings carry
runs no default rule will break. Measured against the real corpus at 320px,
four clauses push the exhibit past its measure:

| clause | over |
|---|---|
| niva_reassure_30 6.2.4 p41 | +235px |
| tata_medicare_select B7 p16 | +87px |
| niva_reassure 8.8 p33 | +48px |
| icici_elevate 34.1.9 p78 | +16px |

6.2.4 carries
`https://transactions.nivabupa.com/cashlessclaims/pages/intimation-claim.aspx`,
76 characters with no break opportunity the renderer will take, and it
overflows at **414px too** — this was never only a small-phone problem.

The worse surface is the pasted-letter preview on the waiting screen, because
its content is whatever the insurer wrote. A claim reference of the shape
`CLM/HDFC/2026/0098871/PREAUTH/REV02` is enough, so the rejection route broke
for a large share of real users regardless of policy.

*Fix:* `.wrap-verbatim` in `theme.css`, applied to the four surfaces that
render text the app did not author — the clause text, the clause title, the
pasted-letter preview and the drafted letter — plus the bill's line
descriptions and IRDAI item names. It sets `overflow-wrap: break-word` and
`min-width: 0`.

**The alternatives are all wrong here, and the reason matters.**
`word-break: break-all` breaks every word rather than only the ones that do
not fit, and a quoted clause stops reading as a document. `hyphens: auto`
inserts a hyphen character into text that is quoted verbatim and will be read
against the printed page — we do not add characters to it. `overflow-x:
hidden` clips the far end of a clause, which is the one thing this product
must never do. `break-word` inserts nothing and moves nothing.

**`npm run verify:mobile` is the gate** for width. It walks every screen at
320, 375 and 414, requires the document to be no wider than the viewport, and
names the elements responsible when it is not. It answers only the question
"does it fit"; `npm run verify:policy-step` is the companion that drives a
form and asks whether it works. See "the form that produced the worst answer
by default" below for why both are needed. The API is stubbed from
`verify_mobile_fixtures.mjs`, so it needs no backend and no credentials and
reaches the finding screens deterministically. It exits non-zero, so it can
gate a deploy. `ENGINE=webkit` runs it under Safari's engine and `ORIGIN=`
points it at the deployed site. Verified passing on both engines, at all three
widths, against the live site.

There is a companion check worth knowing about: rendering all 972 clause texts
through the real exhibit styling and measuring each one. That is how the four
clauses above were named rather than guessed at. Character counts do not
answer this — only the renderer knows where it will agree to break a URL.

---

## NEW — the form that produced the worst answer by default

9 Sep 2026. On a narrow viewport the insurer step showed two collapsed rows
stacked together between the insurer cards and the submit button: "None of
these is my insurer" and "Add dates and amount for a sharper answer". Both
read as footnotes. Nobody opens a footnote.

**The dates were inside the second one, and the dates decide the verdict.**
`ADJUDICATOR_PROMPT` is handed the claim details and told to judge only
against the clauses shown and to return `insufficient_information` rather
than guess. A waiting period is arithmetic on two dates. With neither
supplied there is nothing to do the arithmetic on, so the default path
through the form — fill nothing, press the button — returned "not enough to
judge" on the commonest kind of rejection there is.

That is worth stating plainly: **the form was shaped so that the majority
route through it produced the worst answer the product can give.** It was a
design failure, not a user error, and no gate we had could see it. Nothing
overflowed. Nothing was slow. Every screen passed `verify:mobile`.

*Fix, in `PolicyStep`:*
- Both dates are in the main flow, in a `border-t-[3px] border-ink` block —
  the weight this system gives to something carrying the argument. Not
  collapsible.
- One line saying why: a waiting period is counted in months from the day the
  policy started, so the two dates decide whether one had run out by
  admission.
- Treatment and amount stay collapsed, relabelled "Add the treatment and the
  amount claimed". They colour how the answer is written; they do not decide
  it, and the note inside says so.
- Empty dates warn once and then go ahead. `missing` is derived rather than
  stored, so the warning self-clears the moment the dates are filled and a
  stale one can never sit under a complete form.
- "None of these is my insurer" is plain text below the submit button. As a
  collapsed row between the cards and the control it read as a third thing to
  weigh up before pressing anything, when it is an exit for the few people we
  cannot help.

**The warning goes below the button, and that is deliberate.** Anything
inserted above the control shifts it out from under a thumb already resting
there. The label changes in place instead — "Check the rejection" becomes
"Check it anyway" — so the second press is a decision rather than a mis-tap.
`verify_policy_step.mjs` measures the button's position in **document**
coordinates either side of the press and requires it not to move. Do not use
`boundingBox()` for this: it is viewport-relative, and Playwright scrolls an
element into view before clicking it, so two readings either side of a click
disagree by the scroll distance. That produced a false failure the first time
this ran.

**`npm run verify:policy-step` is the second gate, and it drives the form.**
27 checks at 375px: the date fields are reachable without opening anything
and are not inside a `<details>`, treatment and amount still are, the escape
hatch is plain text below the control, an empty submit warns without leaving
the step, a second press proceeds, a filled form needs one press and shows no
warning, a half-filled one names only the date actually missing, and both
dates arrive in the POST body. That last check is the one that matters most:
it is the only thing asserting the dates reach the adjudicator at all.

Both gates pass under chromium and webkit, at 320/375/414, against the dev
server, the production build and the deployed site.

**The lesson generalises.** `verify:mobile` asks whether the layout fits.
That is not the same question as whether the form works, and a form can be
perfectly laid out and still be shaped so nobody fills the field that decides
the answer. When a field is load-bearing, gate the behaviour, not the width.

---

## NEW — the page moving under the reader, and the three causes

9 Sep 2026. Mobile felt loose: the layout moved when things were tapped. Not
overflow — 8897703 had fixed that, and every width still passed. Three
separate defects, none of which a width gate can see.

**1. Both textareas were 14px, and mobile Safari zooms below 16px.** The
letter field and the bill field were `text-[0.875rem]`. Safari zooms the
viewport whenever a focused input computes under 16px **and does not zoom
back out**, so the reader taps a textarea to paste a letter and is left on a
page wider than the screen for the rest of the session. This is not a layout
shift, no shift observer reports it, and it is the one that most reads as
"the whole screen moved".

*Fix:* `text-base sm:text-[0.875rem]` on both. 16px on phones, the designed
14px mono from 640px up where no browser does this. **Do not tidy the two
sizes into one.** The alternative — `maximum-scale=1` in the viewport meta —
would also stop the zoom, by disabling pinch zoom for everyone. That is an
accessibility failure and this product is read by people who are unwell.

**2. Scroll position was carried across every screen change, and this was the
serious one.** Each step of the decoder is a whole screen, and React swapping
the content does not reset the scroll offset. Measured: pressing "Check the
rejection" from the foot of the policy step landed the reader **1709px into
the finding, in the middle of the second clause exhibit**, having never seen
"The rejection looks weak" — the headline the screen exists to deliver. The
bill had the same defect: press the button at the foot of a long pasted bill
and the total you were just told about is above the top of the screen.

*Fix:* `window.scrollTo(0, 0)` on `[step]` in `Rejection` and on `[result]`
in `Bill`. Instant, never smooth — an animated scroll is motion nobody asked
for and it fights a reader who starts scrolling before it finishes.

**3. Nothing else.** Worth recording, because it was where the time was
expected to go. No focus style occupied space (the one ring is an `outline`,
which does not reflow, and `focus:border-ink` changes colour rather than
width). No animation changed height — `motion.jsx` is transform-only and that
rule held. Every in-place interaction now measures **0.0000**.

### `npm run verify:mobile-shift`

Walks 21 interactions across all four screens, and for each one clears a
`layout-shift` PerformanceObserver, screenshots, interacts, screenshots
again, and reports the score with the nodes that moved and the scroll delta.
Writes `mobile-shots/index.html`, a contact sheet pairing every before and
after against its score, so a shift can be **seen** rather than only scored.
`mobile-shots/` is gitignored.

Four things about how it measures, each of which was wrong in the first
version and cost a false reading:

- **`hadRecentInput` is recorded but never filtered on.** Standard CLS
  discards shifts within 500ms of a tap. Those are exactly what this hunts.
- **The tap target is scrolled into view before the *first* screenshot.**
  Playwright scrolls an element into view as part of clicking it and a real
  thumb does not, so leaving it inside the measured window charges the
  interaction for a scroll the reader had already made — and the two
  screenshots then show different parts of the page for a reason that has
  nothing to do with the shift.
- **A screen change is judged on where it lands, not on CLS.** The content is
  meant to be entirely different, so a score across it measures nothing.
  Those steps assert `scrollY === 0` instead. `policy-submit` scored 0.1187
  before the fix, which understated a defect that put the reader 1709px off
  target; the scroll assertion states it exactly.
- **A disclosure is meant to move what is below it.** Those carry a wide
  budget and are read for *which* nodes moved.

`layout-shift` is a Chromium API, so the shift half runs there; the font-size
half is computed style and runs on either engine. Verified on chromium at 320
and 375, on webkit at 375, against the dev server, the production build and
the deployed site.

**Read the three gates as three questions.** `verify:mobile` asks does it
fit. `verify:policy-step` asks does the form work. `verify:mobile-shift` asks
does it hold still. All three passed while each of the others was failing, at
some point in the last two days, which is the argument for having all three.

---

## NEW — what the optional fields actually do, and eight rejection types

9 Sep 2026. Only HDFC pre-existing disease had ever been run end to end.
`run_matrix.py` runs nine cases against the deployed API in the exact body
shape the form builds, sequentially, and merges into `matrix_results.json`.
Everything below is measured, not assumed.

### The dates decide the verdict. Treatment and amount do not.

Identical rejection text, identical policy, only the claim fields varying:

| | fields | verdict | confidence |
|---|---|---|---|
| a | all four, start 2020-01-15, admission 2026-06-10 (77 months) | `weakly_supported` | 0.95 |
| b | all four, start 2025-01-01, admission 2026-06-10 (17 months) | `well_supported` | 0.95 / 0.85 |
| c | dates only, same 17 months | `well_supported` | 0.95 / 0.90 |
| d | treatment and amount only, no dates | `insufficient_information` | 0.95 |
| e | nothing | `insufficient_information` | 0.90 / 0.95 |

**a and b differ, so the dates reach the model and the arithmetic is real.**
Both cite the same clause — Excl01, HDFC page 30, `waiting_period_days` 1080
— and reason to opposite conclusions: "over six years of continuous coverage"
against "only 17 months of coverage had passed". `letter_type` flips with it,
`appeal` on a, `substantiate` on b. This was the check that outranked
everything else and it passes.

**c is identical to b, so treatment and amount contribute nothing to the
verdict.** They colour the explanation — b names the angioplasty where c says
"hospital admission" — and nothing more. The accordion copy already says
exactly this ("These sharpen how the answer is written. They do not decide it
— the dates above are what a waiting period turns on"), and this is the
evidence that the copy is true rather than merely plausible.

**d does not invent a timeline.** Given a treatment and an amount and no
dates it returns `insufficient_information` and names the gap: "the claim
details provided do not include the policy start date, the hospital admission
date, or any medical records confirming when the cardiac condition was first
diagnosed". `what_would_change_it` names the same three. e behaves the same
way from nothing at all.

**Verdicts are stable; confidence is not.** Every case was run twice. All five
verdicts and all five `letter_type` values reproduced exactly. Confidence
moved on three of five (b 0.95→0.85, c 0.95→0.90, e 0.90→0.95). **Do not build
anything that branches on a confidence threshold.** It is a display value with
roughly ±0.1 of run-to-run noise, and the verdict is the stable signal.

**A known display oddity, unfixed.** `insufficient_information` at 0.95 renders
as "Confidence in this reading: 95%" directly under "Not enough to judge". It
is confidence in the reading, not in a verdict, and the two lines read as
contradicting each other. Worth rewording when that screen is next touched.

### The other rejection types

| | case | verdict | confidence | clause |
|---|---|---|---|---|
| f | sub-limit, Star, cataract Rs 95,000 | `well_supported` | 0.95 | Star p9 + p22 "Cataract Treatment", `monetary_cap` 40000, `percent_cap` 25.0 |
| g | documentation, Star | `partially_supported` | 0.85 | Star p15 "Documents to be submitted", p14 "Claim Settlement" |
| h | specified disease, Niva, hernia | `well_supported` | 0.95 | Niva p22 Excl02, `waiting_period_days` 720 |
| i | HDFC letter filed against Star | `partially_supported` | 0.85 | Star p10 "Excl 01" — **Star's, not HDFC's** |

f is the first evidence that `monetary_cap` and `percent_cap` reach a user
correctly: "capped at 25% of the sum insured or Rs. 40,000 per eye", against a
Rs 95,000 bill. h does the 24-month arithmetic against the dates and gets
16.5 months.

**g was expected to return `insufficient_information` and did not, and the
expectation was wrong.** Star's wording does address documentation: clause E
on page 15 requires a "Discharge summary including complete medical history",
and page 14 makes compliance a "Condition Precedent to Admission of
Liability". The clauses are real and on point, so this is not a clause forced
to fit. The adjudicator then reasoned that "an illegible or missing document
is a curable administrative defect rather than a permanent policy exclusion"
and offered an appeal letter with a concrete next step. That is a better
answer than `insufficient_information`, which would have been true and
useless. **Before treating a non-`insufficient_information` verdict as a
forced fit, read the retrieved clause text.**

### Cross-insurer contamination: structurally impossible, and now proved

`retrieve()` puts `WHERE policy_id = @policy_id` before the ORDER BY, so the
ranking never sees another insurer's clauses. Case i confirms it end to end —
the HDFC letter filed against Star returned Star's own Excl01 on page 10 and
nothing of HDFC's. The filter can only leak if a `policy_id` maps to more than
one insurer, so that was checked directly:

```
policy_id                 distinct_insurers
hdfc_optima_secure        1    HDFC Ergo
icici_elevate             1    ICICI Lombard
niva_reassure             1    Niva Bupa
niva_reassure_30          1    Niva Bupa
star_arogya_sanjeevani    1    Star Health
tata_medicare_select      1    Tata AIG
```

One insurer per policy across all 972 rows, so all 15 retrieved clauses were
necessarily Star's, not only the two shown. **Re-run that query before
trusting any corpus reload.** It is the whole proof.

**But i exposes a real gap.** The letter says "your claim under policy Optima
Secure" and the reader had selected Star. The system answered against Star
without ever noticing the letter names a different insurer, and produced a
confident, well-reasoned answer about a policy the letter is not about. Not
contamination — the right policy was searched, the one the reader chose — but
nothing anywhere says "this letter appears to be from a different insurer".
That is the confirmation step the auto-detection idea in Direction already
calls for, and it is needed whether or not auto-detection is ever built.

### The bill auditor's letter

`npm run verify:bill-letter` drives the real site against the real API, and
had never been pressed before today. It captures `/api/bill/audit` by
intercepting the route and passing the real response through, then reads the
rendered letter and requires every finding's IRDAI name to appear **inside
quotes, verbatim**, the billed description to appear verbatim, the amounts to
match, both section totals to be arithmetic on their own lines, and — the
check that matters — **every quoted string in the letter to trace back to an
item the API returned**, so nothing can be quoted that the corpus does not
hold.

27 checks pass. Set `BILL_TEXT` to change the bill: the three-item bill in the
brief is all List I and never reaches section B, so the ten-line sample is
what exercises `subsume_room` and `subsume_procedure`. Both sections verified,
Rs 3,320 + Rs 3,800 = Rs 7,120.

`page.on("response")` does not reliably retain a body long enough to read it
and returned null every time; `context.route` with `route.fetch()` is the way
to capture a real response without stubbing it.

---

## NEW — the insurer-mismatch notice, and two corrections

9 Sep 2026, following the test matrix above.

**The landing said 965 clauses.** The corpus has been 972 since the v17 build
of 31 Aug. The figure is hardcoded in `Landing.jsx`; the policy step reads
`clause_count` from the API and was always right. If the corpus moves again,
that constant is the one place that does not follow.

**Confidence is withheld on `insufficient_information`.** The adjudicator
scores every verdict, and on that one the score means "I am confident there is
not enough here to judge" — measured at 0.95 on a case with no dates at all.
Printed as "Confidence in this reading: 95%" under "Not enough to judge" it
read as self-contradiction. The `VERDICT` table now carries `scored`, false
only there, defaulted true so a new verdict is scored unless it says
otherwise. The clause count ("15 clauses from your policy were read") survives
on its own: it is a fact about what was searched, true on every verdict, and
not a claim about the answer.

### The mismatch notice

Case i produced a confident, well-reasoned finding about Star from a letter
that says "your claim under policy Optima Secure". Retrieval was right —
`policy_id` filtering makes contamination impossible — but nothing said the
letter names a different insurer. Now a notice sits **above** the verdict,
because it changes what the verdict means, and it warns without blocking: the
finding, the exhibit and the letter are all still delivered.

`src/insurerMatch.js`, deterministic and no model call. **Both directions of
error are costly** — a miss leaves someone reading a confident answer about
the wrong document, a false positive tells an anxious reader their correct
choice is wrong — and the unit test caught two failures before deploy:

- **Longest name first, and a match is consumed.** "ReAssure" is a substring
  of "ReAssure 3.0".
- **A single-word policy name must be capitalised to count.** Two of the six
  are ordinary English words, "Elevate" and "ReAssure", and "undertaken to
  elevate the patient's quality of life" is a sentence a real letter might
  contain. Multi-word names match without regard to case.
- **A precedence ladder, most specific first:** own policy named → quiet; a
  different policy named → warn; own insurer named → quiet; a different
  insurer named → warn. The insurer alone cannot discriminate, because two
  policies share one — treating "Niva Bupa" in a ReAssure 3.0 letter as
  reassurance silenced a real mismatch.

**One recorded ambiguity, deliberate and tested as such.** A portability
letter that names the previous policy in full and the current one only by
insurer does warn, because step 2 sits above step 3. The reader can resolve
that and we cannot, and the copy says they can ignore it if the letter simply
refers to a previous insurer.

**Ink, not ochre.** The theme allows ochre once per screen and
`what_would_change_it` already has it; two would dilute both. The notice is
first on the page and does not need colour to be read. `verify_finding.mjs`
asserts the ochre count stays at one.

### Two more gates

`npm run verify:insurer-match` — 15 checks, no browser, no API, no model.
`npm run verify:finding` — 15 checks in a browser with a stubbed API, covering
both verdict paths and the notice's position, presence and absence.

Seven gates now. Run them all before a deploy:
`verify:mobile`, `verify:policy-step`, `verify:mobile-shift`,
`verify:insurer-match`, `verify:finding`, `verify:bill-letter`, and
`run_matrix.py` when the backend or a prompt changes.

**A testing note worth keeping.** `.folio` sets `text-transform: uppercase`,
and `innerText` returns rendered text — so an assertion on "Check this first"
fails against "CHECK THIS FIRST" while the element is on screen. Match
case-insensitively on any text inside a `.folio`. Playwright's own `text=`
engine is already case-insensitive, which is why one assertion passed and
another failed on the same element.

---

## NEW — the type scale everywhere, and depth in the neutrals

9 Sep 2026, after the result screen proved the scale.

### The scale, on all five screens

Landing, paste, policy, waiting and the bill now use the role-named tokens
from `30a3912`. Two structural changes came with it:

**The bill's number is the moment.** It used to be buried mid-sentence in a
headline — "₹3,170 on this bill should not have been charged to your claim" —
so the thing the reader came for was a fragment of a paragraph. Split: the
amount alone at verdict scale, the sentence beneath at lead. Big and quiet;
no celebration, because someone reading it is unwell or caring for someone
who is.

**The landing's three figures came down** from 5xl/6xl to screen scale. They
were the second-loudest thing on the page and argued with the claim above
them. One moment per screen, and on the landing it is the claim.

### Why the page read flat, measured

| | before | after |
|---|---|---|
| surface span, card → deepest | **5.9 L\*** | **13.9 L\*** |
| paper → sunk (what the exhibit relies on) | **2.4 L\*** | **4.4 L\*** |
| ink-verbatim → ink-2 (two tokens, one job) | 4.9 L\* apart | 13.3 apart |

2.4 L\* is at the edge of perceptibility for a large flat field. The exhibit's
"sheet laid on a desk" was working on almost nothing.

**Deepening the surfaces spends the text-contrast budget, and that is the
thing to understand before touching these values.** The obvious move for
recession — a paler grey — measured 4.28:1 on paper and 3.83:1 on sunk,
under the AA floor. So `ink-soft` got slightly *darker*, not lighter, and
text recession comes from the ground stepping down beneath it plus size and
weight. `ink-soft` cannot go lighter while asides sit on `paper-sunk`.

`paper-deep` (L\* 86.1) is the exhibit band. `ink-soft` measures 3.20:1 there
and cannot be used, so that band's label steps up to `ink-2` — the budget
being spent, made concrete.

### No second hue, and why

The question was asked and the answer was no. The measured cause of flatness
was a 5.9 L\* surface span; adding hue to a depth problem gives a coloured
flat page. The system already carried four hues (contest, upheld, insurer,
ochre) — it was never a one-colour system, it was one dominant plus three
restricted, and a fifth is where it starts reading as a dashboard.

Decisive: **`contest-deep` and `contest-tint` were defined and never used.**
The one saturated colour had a three-rung ramp with only the middle rung in
service. `contest-deep` is now the landing hero — the front door is the
deepest green and the verdict band sits a step above it. Depth within the one
colour rather than a new meaning to learn.

### `npm run verify:palette` — and it caught the bug it was built for

Deepening the surfaces nearly shipped two invisible defects:

- `rule-soft` was L\* 91.7 against a new `paper-sunk` of L\* 92.8. A hairline
  **lighter than the surface it is drawn on** — it would simply disappear.
- `ochre-tint` was 1.02:1 against the new paper: a callout ground
  indistinguishable from the page behind it.

Neither is visible in a diff, neither breaks a layout, neither shows up in an
overflow or stability gate. They are arithmetic, so they are checkable. 40
checks, no browser:

1. every rule clears 1.2:1 on every ground it is drawn on
2. the neutral ramp keeps its depth — adjacent surfaces ≥2.0 L\* apart, span
   ≥10
3. every declared text-on-ground pair clears AA at 4.5:1
4. every callout ground is ≥1.08:1 against the page

**The rule and text pairs are declared, not inferred.** The first version
checked every rule against every surface and failed instantly on `rule-soft`
against `paper-deep` — correct arithmetic about a combination the design does
not use and cannot satisfy, since a soft hairline and the deepest paper stock
are 1.01:1 apart at any honest value. A stylesheet cannot tell you what sits
on what. Writing the pair down is the moment someone has to think about it.

It also failed `rule` on `paper-deep` at 1.1996:1 — genuinely under, not a
rounding artefact — so `rule` went from `#cdc5b0` to `#c9c0a9`.

**Eight gates now.** `verify:palette` is the cheapest of them: no browser, no
API, no model, runs in under a second. Run it after any colour change.
---

## NEW — the adjudicator was resolving silences, and the fix has a known cost

10 Sep 2026.

**The defect.** An HDFC pre-existing disease rejection, policy start 15 Jan
2020, admission 10 Jun 2026 — 77 months of cover, well past the 36-month
waiting period. The adjudicator returned `well_supported` at 0.95 reasoning
"Because the pre-existing diabetes was not declared and accepted when the
policy was issued, expenses for its treatment remain excluded."

**Nothing in the input said the condition was undeclared.** Excl01 has a
second condition — coverage after 36 months requires the disease to have been
declared at application and accepted — and with the waiting period satisfied,
that condition was the only thing left that could sustain the rejection. The
model resolved the silence in the insurer's favour and stated it as settled.

The system half-knew: `what_would_change_it` asked for proof the condition
was declared, and the insurer's own weak spot named the six years of cover.
It recognised the fact was unestablished while the verdict treated it as
established.

The same input had returned `weakly_supported` earlier the same day. **That
instability was a symptom of the same gap** — with the fact unknown, the
verdict is free to swing on whichever reading the model lands on.

*Cause:* the prompts constrained **clauses** ("Judge only against the clauses
shown. Never assume a provision that is not here") and said nothing about
**facts**. The model could not invent a clause but was free to invent a fact
about the claimant.

*Fix:* a rule in `ADJUDICATOR_PROMPT` and `ADVOCATE_PROMPT` that a fact not
stated in the rejection letter or the claim details is UNKNOWN — not false,
not true — and that a silence is never resolved in either party's favour.
Where a clause turns on such a fact the verdict is
`insufficient_information` and the explanation names the missing fact. An
advocate may argue a fact is unproven but must never assert it as
established.

**Result on the reported case: three runs, three times
`insufficient_information`** (0.95, 0.90, 0.90), each naming the missing
fact. The instability is gone.

### Materiality — TRIED TWICE, REVERTED. Read this before trying again.

10 Sep 2026. The unknown-fact rule above fixed the reported case and left two
neighbours wrong: the cataract sub-limit abstained over a Sum Insured that
cannot change the answer, and the specified-disease case abstained over
exceptions nobody had raised. Two attempts to fix that, both reverted.

**Attempt 1 — a materiality rule plus an `unknown_facts` array returned first
in the JSON.** Partly worked. The Sum Insured came out "not material" 3 of 3
with the arithmetic spelled out — *"the cap per eye can never exceed Rs 40,000
regardless of the Sum Insured"*. But better enumeration without a burden
principle is paralysis: the specified-disease case went to
`insufficient_information` 3 of 3, flagging accident and portability
exceptions nobody had claimed.

**Attempt 2 — a burden rule, then a `role` / `raised_by` decision table.** The
prose rule suppressed exceptions indiscriminately. The structured version
asked the model to attribute each unknown before judging it. Neither landed,
and the second one showed why.

**THE FINDING THAT SETTLES IT: `raised_by` was filled in wrongly.** In the
case where nobody mentions portability, two of three runs recorded it as
*"raised by the claimant"*. In the case where the letter says in terms that
the insured contends the hernia followed a road accident, two of three runs
recorded the accident as *"raised by nobody"* and decided the case on that
basis.

That is not a rule-wording problem. It is the model misreading who said what
in a four-line letter. **No refinement of the rule reaches it**, because every
version of the rule depends on that attribution being right. A structured
field does not make a judgement reliable; it only gives an unreliable
judgement a tidier place to be wrong.

**Measured across states, three runs each**, on the two cases that matter:

| state | h — dates settle it, want well_supported | f — cap settles it, want well_supported | j — genuinely undecidable |
|---|---|---|---|
| `4a43f54` unknown-fact rule (**live**) | **2 / 3** | 1 / 3 | 3 / 3 |
| `b45450f` + materiality + unknown_facts | 0 / 3 | 2 / 3 | 3 / 3 |
| attempt 2, burden rule | 1 / 3 | 0 / 3 | 3 / 3 |
| attempt 2, role + raised_by | 1 / 3 | not run | 3 / 3 |

Reverted to `4a43f54`. It is the best available on `h`, and a wrong "cannot
decide" on a case the dates plainly settle is worse than a cautious one on a
sub-limit. **`j` is 3 of 3 in every variant, so the original defect — the
adjudicator resolving a silence in the insurer's favour — stays fixed
whatever else is done here.**

**What is still wrong, and what would actually be needed.** `f` abstains 2 of
3 over a Sum Insured that cannot change the answer, and `h` abstains 1 of 3
over an exception nobody raised. Both are the same root cause: judging
materiality requires holding the clause logic, the stated facts and who
asserted them simultaneously, and the model does that inconsistently at this
prompt length. If it is picked up again, the thing to try is **not** another
rule. Either:

- decide materiality deterministically in Python for the shapes that recur —
  a cap with "whichever is lower" against a bill is arithmetic, not judgement;
  or
- run the attribution as its own small call with only the letter and the
  question "which of these exceptions does this letter mention?", so the
  reading step is not competing with the reasoning step.

### The process fix, which is the durable part

**Deploy to a no-traffic revision and run every case against it before
promoting.**

```
gcloud run deploy claim-decoder-api --source backend --region asia-south1 \
  --max-instances 1 --no-traffic --tag candidate
CLAIM_API=https://candidate---claim-decoder-api-a5vy5uonga-el.a.run.app \
  python run_matrix.py h x3
gcloud run services update-traffic claim-decoder-api \
  --region asia-south1 --to-latest      # only once it passes
```

`run_matrix.py` takes `CLAIM_API` for exactly this. Both regressions on 10 Sep
went live because each change was shipped and its neighbours checked
afterwards.

**And three runs, never one.** The claim in an earlier revision of this file
that `h` was well_supported "3 of 3" at `4a43f54` was wrong: it rested on a
single run, and the real figure is 2 of 3. Adjudication is not deterministic,
a verdict that moves between runs of identical input is telling you the input
does not determine it, and a single run is not evidence of anything.
`python run_matrix.py <case> x3` is the minimum.

Case `k` in `run_matrix.py` is the control worth keeping: it is `h` with the
accident exception actually raised in the letter. A rule that suppresses
unraised exceptions must still flag `k`. Any future attempt should be judged
on `h` and `k` together — passing one alone proves nothing.
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
- **The landing clause count is hardcoded.** `Landing.jsx` FIGURES carries
  972; the policy step reads the live `clause_count`. A corpus change has to
  update that constant by hand.
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
- **A letter is now always offered, but it is not always an appeal.**
  `letter_type` is `appeal` on a contestable verdict and `substantiate` when
  the rejection holds, where the letter asks the insurer to evidence the
  specific point their own advocate named as weakest. It is explicitly told
  not to argue the rejection is wrong and not to ask for payment, so it can
  never read as a hopeless appeal.

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
