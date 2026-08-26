# Extraction pre-flight, 23 August

Picking up at section 11 of the handoff, steps 1 to 6.

---

## 1. The PDFs in this project cannot be parsed here

Checked all seven files by magic bytes.

| File | What actually arrived |
|---|---|
| Policy_Arogya_Sanjeevani...pdf | ZIP of 53 page JPEGs |
| PolicyWordings_myOptimaSecure...pdf | ZIP of 139 page JPEGs |
| ReAssure30_Policy_Wordings.pdf | ZIP of 125 page JPEGs |
| ReAssurePolicyWording.pdf | ZIP of 91 page JPEGs |
| medicare_select_policy_wording...pdf | ZIP of 99 page JPEGs |
| newcompletehealthinsurancebrochure.pdf | ZIP of 51 page JPEGs |
| elevate.pdf | Plain extracted text, 265 KB |

This is the project file store rasterising them on upload, not a problem with
your originals. pdfplumber gets no PDF bytes, so no extraction can run here.

**Good news on the scan question.** I pulled page 6 of the Star Arogya
Sanjeevani image out and looked at it. It is a crisp digital render, perfectly
square, vector-sharp type. Not a scan. Same for Optima Secure and Niva Bupa.
Your originals almost certainly have selectable text, so no OCR and nothing to
discard. elevate.pdf arriving as text confirms ICICI Elevate is text-based.

Confirm locally in one line before uploading anything:

```bash
for f in *.pdf; do echo -n "$f "; python -c "
import pdfplumber,sys
p=pdfplumber.open(sys.argv[1])
n=len(p.pages); c=sum(len(pg.extract_text() or '') for pg in p.pages[:10])
print(n,'pages', c//10,'chars/page', 'SCAN, DISCARD' if c//10 < 200 else 'ok')
" "$f"; done
```

Under 200 chars a page means a scan. Discard it.

Also confirmed from the page image: Star Arogya Sanjeevani is genuinely two
column, body text only, with a full width header band and footer band. So the
column handling matters and the furniture stripping has real work to do.

---

## 2. Six bugs in extract_policy.py, fixed in v2

Found by reading, not by running, so the first three are the ones to watch
when you do run it.

**Wrong page numbers on every clause.** v1 stamps `chunk["start_page"]` onto
every clause in the chunk. Chunks run to 6000 characters, which is three to
five pages. So "see page 12" in an appeal letter points at the wrong page,
roughly half the time. The whole product rests on the user being able to check
the citation. v2 marks pages inline as `[[page N]]`, asks the model to return
the page, validates it against the markers present, and strips the markers
before the verbatim check.

**Annexure tables lose half their items.** v1 takes `cells[-1]` as the item
name. Annexure A is laid out as two side by side item tables, so a row is
`[1, Baby food, 35, Gloves]`. Taking the last cell keeps Gloves and drops
Baby food. You would have got roughly 34 of the 68 List I items and never
noticed, because 34 items still looks like a plausible list. v2 walks the row
in pairs and takes every serial-then-name pair.

**Section detection returns the wrong section.** v1 loops SECTION_MARKERS in
list order and returns the first pattern that matches anywhere in the first
400 characters. So a page whose body mentions "conditions" before its heading
"SPECIFIC EXCLUSIONS" gets labelled a condition, because DEFINITIONS and
COVERAGE sit earlier in the list. v2 takes the earliest heading by position in
the text and scans 1200 characters.

**Column split assumed to be dead centre.** v1 hardcodes 0.5. Insurers vary,
and a split 15pt off eats the first character of every line in one column.
v2 finds the gutter by scanning the middle band of the page for the widest
vertical channel with no word boxes in it, and reports the ratio it found per
document. Tested on a synthetic two column page: detected 0.498, columns read
in correct order. `--gutter` still lets you force it.

**The verbatim check does almost nothing.** v1's fallback probes
`candidate[:85% of length]`, which is nearly the whole clause, so it only ever
passes what an exact match would have passed anyway. Meanwhile real verbatim
text fails on hyphenation across line breaks and curly quotes. v2 normalises
unicode punctuation, repairs line-break hyphenation, then falls back to a
longest contiguous run. Tested:

| Input | v2 verdict |
|---|---|
| Exact copy | accept |
| Exact copy with hyphenation and line breaks | accept |
| Curly quotes and en dashes | accept |
| Close paraphrase | reject, longest run 38 of 170 chars |

**Model.** Moved to `gemini-2.5-flash`. Better at long-context verbatim copying
than 2.0, same order of cost, still a Google model so the competition rule
holds.

One thing v2 cannot fix. The verbatim check compares against the chunk text,
not the PDF. If the columns read scrambled, garbage passes the check happily.
That is what the dry run is for. Added a prompt rule telling the model to
return `[]` if the text reads scrambled, as a second line of defence.

---

## 3. New dry run mode

Runs the whole pipeline except the model call. Free. Do this first on every
document.

```bash
python extract_policy_v2.py Policy_Arogya_Sanjeevani.pdf \
  --insurer "Star Health" \
  --policy-name "Arogya Sanjeevani" \
  --policy-id star_arogya_sanjeevani \
  --dry-run
```

Prints pages, layout mode per page, detected gutter ratio, chunk count by
section, a warning listing any near-empty pages, and the Annexure item counts
by category. Dumps every chunk to `dryrun_chunks.txt`.

What to check in the dump, in order:

1. Sentences run in order. If they jump mid sentence, rerun with
   `--gutter 0.48` or `0.52`.
2. Section labels look right. Exclusions chunks contain exclusions.
3. Annexure counts. Star should be near 68 / 37 / 23 / 18 for
   not_payable / subsume_room / subsume_procedure / subsume_treatment. Well
   short of that means the table parser needs adjusting for that document.

Only after that is clean, run with `--limit 3` and read three records by eye.

---

## 4. A bug in bigquery_setup.md section 4

```sql
JOIN `claims.clauses` c ON c.clause_text = e.content_source
```

`content` is `CONCAT(clause_title, '. ', clause_text)`, so `content_source`
never equals `clause_text` and this join returns zero rows. It will look like
the embedding step silently produced nothing.

`ML.GENERATE_EMBEDDING` already passes the input columns through, so drop the
join:

```sql
CREATE OR REPLACE TABLE `claims.clauses_embedded` AS
SELECT
  * EXCEPT (content, ml_generate_embedding_result,
            ml_generate_embedding_statistics, ml_generate_embedding_status),
  ml_generate_embedding_result AS embedding
FROM ML.GENERATE_EMBEDDING(
  MODEL `claims.embedder`,
  (
    SELECT *, CONCAT(IFNULL(clause_title, ''), '. ', clause_text) AS content
    FROM `claims.clauses`
  ),
  STRUCT(TRUE AS flatten_json_output)
);
```

Second issue with the same join. Arogya Sanjeevani is IRDAI standardised, so
Excl 01 through Excl 18 are word for word identical across every insurer.
Joining on `clause_text` would have fanned each standard exclusion out across
all insurers in the corpus. Dropping the join removes that too.

Worth adding a check after loading:

```sql
SELECT clause_text, COUNT(DISTINCT insurer) AS insurers, COUNT(*) AS rows
FROM `claims.clauses`
GROUP BY clause_text
HAVING COUNT(*) > 1
ORDER BY rows DESC
LIMIT 20;
```

Standard exclusions appearing once per insurer is correct and expected. The
same clause appearing twice for one insurer is a chunk overlap bug.

---

## 5. What to do next, in order

1. Run the selectable text check above on your local originals
2. `pip install pdfplumber google-genai`
3. Dry run on Star Arogya Sanjeevani. Read `dryrun_chunks.txt`
4. Dry run on the other five. Note any that need a different `--gutter`
5. Set `GEMINI_API_KEY`, run Star with `--limit 3`, read three records against
   the PDF
6. Full run on Star, then the rest
7. Upload the PDFs to Cloud Storage. This can happen any time, it is not
   blocking, and nothing in the pipeline reads from the bucket yet
8. BigQuery load with the corrected embedding SQL

On the corpus. Six documents is already above the cut-to-five floor in section
12. Do not download more until Star is loaded and retrieval returns sensible
clauses. Getting one policy end to end is worth more than six half-parsed ones.

On timing. Aug 28 checkpoint is five days out. Aug 22 and 23 on the submitted
timeline were the API contract freeze and the stubbed Cloud Run deploy, and
neither has started. Those unblock nothing else and can be done in parallel
with extraction. If extraction eats more than two days, deploy the stub first
and come back, because a live URL with a stub beats a perfect corpus with
nothing deployed.
