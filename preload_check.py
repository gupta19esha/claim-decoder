"""
The check between extraction and BigQuery. Run this, or do not load.

    python preload_check.py icici_elevate_v15.jsonl
    python preload_check.py icici_elevate_v15.jsonl --load

Exit code 0 means the file is safe to load. Anything else means it is not.
With --load, the bq load runs only on a clean pass, so the check cannot be
skipped by forgetting it: the load and the check are the same command.

WHAT IT CHECKS, AND WHY EACH ONE EXISTS

Every gate here is a defect that reached the corpus and was invisible until
someone went looking. None of them were caught by the verbatim check, because
the verbatim check proves a clause came from the extracted page text — not
that the extracted page text resembles the printed page, and not that the
clause is whole.

  truncated            A clause ending on a dangling word. ICICI's definition
                       of Pre-existing Disease ended "...issued by us; or",
                       missing limb (b) entirely.
  starts_mid_sentence  The far side of a split, extracted as its own clause.
  continues_previous   Both halves of a split present as separate records.
  contamination        Page furniture inside clause_text. ICICI's footer
                       survived on 103 of 111 pages and was spliced into 22
                       clauses, cutting 10 of them off.
  empty                clause_text with nothing in it.

  chunks_failed        From the run manifest. A chunk whose every attempt
                       errored contributes nothing, and a DNS blip did
                       exactly that to two waiting_period chunks of Star
                       Health while the run reported success.
  boundary damage      From the run manifest. Clauses cut at a chunk boundary
                       whose opening sits further back than the overlap
                       window, so they are truncated or lost. This is the
                       only defect that is invisible in the .jsonl by
                       construction: when the extractor drops the far half of
                       a split, there is no record to inspect.
  verbatim rejection   Above 20 percent means the document parsed badly.

The manifest is written by extract_policy_v13.py next to its output. A file
without one cannot be vouched for, so that is a failure by default; pass
--allow-missing-manifest for corpus files extracted before manifests existed.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter

from quality_gates import check, BLOCKING

DEFAULT_TABLE = "claims.clauses"
DEFAULT_SCHEMA = "clauses_schema.json"
MAX_REJECTION_RATE = 0.20


def load_records(path):
    recs = []
    for lineno, line in enumerate(open(path, encoding="utf-8"), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{lineno} is not valid JSON: {exc}")
        rec["_line"] = lineno
        recs.append(rec)
    return recs


def manifest_path_for(jsonl_path):
    return re.sub(r"\.jsonl$", "", jsonl_path) + ".manifest.json"


def silent_pages(man, records):
    """
    Pages sent to the model that produced no clause at all.

    A page here and there is normal — a cover page, a page that is all
    heading. A long contiguous run is a section that vanished without any
    error: the chunks were built, the calls succeeded, and nothing came back.
    HDFC's plan charts are 19 consecutive pages of exactly that, because the
    table text arrives column-scrambled and the extraction prompt correctly
    tells the model to return nothing rather than guess. Nothing else in the
    pipeline notices, which is what puts this in the same family as the
    footer contamination and the boundary cuts.

    Measured across the six policies: longest silent runs were star 4,
    tata 5, icici 6, niva 9, niva30 17, hdfc 19. The default ceiling of 8
    sits above the incidental gaps and below every genuine section loss.
    """
    sent = man.get("pages_sent")
    if not sent:
        return None
    have = {r.get("source_page") for r in records}
    missing = sorted(p for p in sent if p not in have)

    runs, run = [], []
    for p in missing:
        if run and p == run[-1] + 1:
            run.append(p)
        else:
            if run:
                runs.append(run)
            run = [p]
    if run:
        runs.append(run)
    runs.sort(key=len, reverse=True)
    return {"sent": len(sent), "missing": missing, "runs": runs}


def check_manifest(man, args):
    """Failures that only the extraction run could have known about."""
    problems = []

    failed = man.get("chunks_failed") or []
    if failed:
        for c in failed:
            problems.append((
                "chunk_failed",
                f"chunk {c.get('index')} ({c.get('section')}, pages "
                f"{c.get('start_page')}-{c.get('end_page')}) errored on every "
                f"attempt. Those pages are absent from this file."))

    b = man.get("boundary") or {}
    unrec = b.get("unrecovered") or []
    if len(unrec) > args.max_unrecovered:
        for u in unrec:
            problems.append((
                "boundary_unrecovered",
                f"a clause after page {u.get('after_page')} begins "
                f"{u.get('chars_back')} chars back, beyond the "
                f"{man.get('overlap_chars')} char overlap, so it is cut. "
                f"Re-extract with --overlap above {u.get('chars_back')}, or "
                f"accept with --max-unrecovered {len(unrec)}."))

    rate = man.get("verbatim_rejection_rate")
    if isinstance(rate, (int, float)) and rate > args.max_rejection_rate:
        problems.append((
            "verbatim_rejection_rate",
            f"{rate:.1%} of extracted clauses failed the verbatim check "
            f"(ceiling {args.max_rejection_rate:.0%}). The document probably "
            f"parsed badly; read the dry-run dump before trusting this."))

    if man.get("records_written") == 0:
        problems.append(("empty_output", "the run wrote no clauses at all"))

    return problems


def check_page_coverage(cov, args):
    """Blocking and warning findings from the silent-page analysis."""
    blocking, warnings = [], []
    if cov is None:
        warnings.append((
            "page_coverage_unknown",
            "the manifest has no pages_sent, so pages that were extracted "
            "but produced nothing cannot be detected"))
        return blocking, warnings

    for run in cov["runs"]:
        if len(run) > args.max_silent_run:
            blocking.append((
                "silent_page_run",
                f"pages {run[0]}-{run[-1]} ({len(run)} consecutive) were sent "
                f"to the model and produced no clause. A section this long "
                f"does not vanish by accident — check whether it is a table. "
                f"Accept with --max-silent-run {len(run)} if it is expected."))
        elif len(run) >= 3:
            warnings.append((
                "silent_pages",
                f"pages {run[0]}-{run[-1]} ({len(run)}) produced no clause"))
    if cov["missing"]:
        warnings.append((
            "page_coverage",
            f"{len(cov['missing'])} of {cov['sent']} pages sent produced no "
            f"clause ({len(cov['missing']) / cov['sent']:.0%})"))
    return blocking, warnings


def main():
    ap = argparse.ArgumentParser(
        description="Gate a clause .jsonl before loading it to BigQuery.")
    ap.add_argument("jsonl")
    ap.add_argument("--manifest", default=None,
                    help="Defaults to the .manifest.json beside the input.")
    ap.add_argument("--allow-missing-manifest", action="store_true",
                    help="Downgrade a missing manifest to a warning. Only for "
                         "files extracted before manifests existed.")
    ap.add_argument("--max-unrecovered", type=int, default=0,
                    help="Boundary-cut clauses beyond the overlap window that "
                         "you are willing to accept. Default %(default)s.")
    ap.add_argument("--max-rejection-rate", type=float,
                    default=MAX_REJECTION_RATE)
    ap.add_argument("--max-silent-run", type=int, default=8,
                    help="Longest run of consecutive pages that may be sent "
                         "to the model and produce nothing. Default "
                         "%(default)s: measured silent runs across the six "
                         "policies were 4, 5, 6, 9, 17 and 19, so this sits "
                         "above the incidental gaps and below every genuine "
                         "lost section.")
    ap.add_argument("--show", type=int, default=5,
                    help="Examples printed per finding type.")
    ap.add_argument("--accept", action="append", default=[], metavar="KIND=N",
                    help="Accept up to N findings of KIND, e.g. "
                         "truncated=2. A deliberate, recorded override: the "
                         "findings are still printed and the acceptance is "
                         "echoed. Anything beyond N still blocks.")
    ap.add_argument("--load", action="store_true",
                    help="Run the bq load, but only if every check passes.")
    ap.add_argument("--table", default=DEFAULT_TABLE)
    ap.add_argument("--schema", default=DEFAULT_SCHEMA)
    ap.add_argument("--replace", action="store_true",
                    help="Replace the table instead of appending. bq load "
                         "appends by default, which would silently double a "
                         "corpus that was meant to be swapped.")
    args = ap.parse_args()

    print(f"pre-load check: {args.jsonl}")
    print("=" * 74)

    records = load_records(args.jsonl)
    if not records:
        print("  FAIL  the file contains no records")
        return 1
    print(f"  {len(records)} clauses, "
          f"{len({r.get('policy_id') for r in records})} policy id(s)")

    blocking, warnings = [], []

    # ---- record-level and sequence gates
    for kind, rec, detail in check(records):
        entry = (kind, f"p{rec.get('source_page')} "
                       f"{str(rec.get('clause_title'))[:40]} | {detail}")
        (blocking if kind in BLOCKING else warnings).append(entry)

    # ---- run manifest
    man_path = args.manifest or manifest_path_for(args.jsonl)
    if os.path.exists(man_path):
        man = json.load(open(man_path, encoding="utf-8"))
        print(f"  manifest: {os.path.basename(man_path)} "
              f"({man.get('pages')} pages, {man.get('chunks_total')} chunks, "
              f"overlap {man.get('overlap_chars')})")
        b = man.get("boundary") or {}
        if b:
            print(f"  boundaries: {b.get('boundaries')}, cut "
                  f"{b.get('cut')}, recovered {b.get('recoverable')}, "
                  f"unrecovered {len(b.get('unrecovered') or [])}")
        if man.get("records_deduped"):
            print(f"  deduped: {man['records_deduped']} copies or fragments "
                  f"removed")
        blocking.extend(check_manifest(man, args))
        cov = silent_pages(man, records)
        if cov:
            print(f"  page coverage: {cov['sent'] - len(cov['missing'])}"
                  f"/{cov['sent']} pages sent produced a clause"
                  + (f", longest silent run {len(cov['runs'][0])}"
                     if cov["runs"] else ""))
        cov_block, cov_warn = check_page_coverage(cov, args)
        blocking.extend(cov_block)
        warnings.extend(cov_warn)
    elif args.allow_missing_manifest:
        warnings.append((
            "no_manifest",
            f"{os.path.basename(man_path)} not found. Failed chunks and "
            f"boundary damage cannot be checked for this file."))
        print("  manifest: MISSING (allowed)")
    else:
        blocking.append((
            "no_manifest",
            f"{os.path.basename(man_path)} not found. Without it there is no "
            f"way to know whether chunks failed or clauses were cut at a "
            f"boundary. Re-extract, or pass --allow-missing-manifest if this "
            f"file predates manifests."))
        print("  manifest: MISSING")

    # ---- report
    def report(title, items):
        if not items:
            return
        print(f"\n{title} ({len(items)})")
        counts = Counter(k for k, _ in items)
        for kind, n in counts.most_common():
            print(f"  {kind}  x{n}")
            for _, detail in [i for i in items if i[0] == kind][:args.show]:
                print(f"      {detail}")
            if n > args.show:
                print(f"      ... {n - args.show} more")

    # Explicit acceptance. Findings are still reported; they simply stop
    # blocking, and the fact that someone chose to accept them is printed
    # next to the pass so it cannot be mistaken for a clean file.
    allowance = {}
    for spec in args.accept:
        kind, _, n = spec.partition("=")
        allowance[kind.strip()] = int(n or 0)
    accepted = []
    if allowance:
        counts, still = Counter(), []
        for kind, detail in blocking:
            counts[kind] += 1
            if counts[kind] <= allowance.get(kind, 0):
                accepted.append((kind, detail))
            else:
                still.append((kind, detail))
        blocking = still

    report("WARNINGS, not blocking", warnings)
    report("ACCEPTED by --accept, still present in the data", accepted)
    report("BLOCKING", blocking)

    print("\n" + "=" * 74)
    if blocking:
        print(f"REFUSED. {len(blocking)} blocking finding(s). "
              f"Do not load {args.jsonl}.")
        return 1

    verdict = f"PASSED. {args.jsonl} is safe to load."
    if warnings:
        verdict += f" {len(warnings)} warning(s)."
    if accepted:
        verdict += (f" {len(accepted)} finding(s) accepted by explicit "
                    f"override, not fixed.")
    print(verdict)

    if args.load:
        # On Windows bq is a wrapper (bq.cmd / a bash script), which
        # CreateProcess cannot execute by bare name. Resolve it first.
        exe = (shutil.which("bq") or shutil.which("bq.cmd")
               or shutil.which("bq.exe"))
        if not exe:
            print("\nbq not found on PATH. Cannot load.")
            return 1
        cmd = [exe, "load", "--source_format=NEWLINE_DELIMITED_JSON"]
        if args.replace:
            cmd.append("--replace")
        cmd += [args.table, args.jsonl, args.schema]
        print("\nloading: bq " + " ".join(cmd[1:]))
        return subprocess.call(cmd, shell=(os.name == "nt"))
    print("\nNot loaded. Re-run with --load to load it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
