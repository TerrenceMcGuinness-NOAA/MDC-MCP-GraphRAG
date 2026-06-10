# Implementation Plan — `fortran-parse-fallback`

## Overview

This plan adds a regex-based fallback extractor to the Fortran AST parser so the
~15% of files fparser2 cannot parse still contribute definition nodes and
CALLS/USES edges. Work is incremental and test-backed: provenance plumbing first
(Task 1), then the line preprocessor and extractor (Tasks 2–3), wiring (Task 4),
unit + property tests (Tasks 5, 7), ingester telemetry (Task 6), and a gated
operator-run live verification (Task 8).

All code changes are confined to `mcp_server_python/scripts/_fortran_parser.py`
and `ingest_fortran_graph_v8.py`, behind the existing never-raise contract, so
partial progress cannot regress the current parse path or the Neptune write logic.

## Tasks

- [x] 1. Add provenance field and counters
  - Add `source: str = "fparser2"` to the `FortranParseResult` dataclass (defaulted
    so all existing constructors and tests stay valid).
  - Extend `FortranParser.stats` with `files_parsed_fparser2`, `files_parsed_fallback`,
    and `files_failed` (initialized to 0).
  - _Requirements: 4.1, 5.1, 5.3_

- [x] 2. Build the logical-line preprocessor for the fallback
  - Add a private helper that, given source text, yields `(physical_line_no,
    logical_line)` tuples: strip full-line comments (`!` first non-blank;
    `c`/`C`/`*` in column 1 for fixed-form), strip inline `!` comments outside
    string literals, and join free-form trailing-`&` continuations into one
    logical line carrying the first physical line number.
  - Unit-test the joiner on continuation-split `CALL`/`USE` and on comment forms.
  - _Requirements: 2.6, 3.3, 6.3_

- [x] 3. Implement the regex set and `_fallback_extract`
  - Compile the seven class-level regexes (`END_RE`, `MODULE_RE`, `SUBROUTINE_RE`,
    `FUNCTION_RE`, `PROGRAM_RE`, `CALL_RE`, `USE_RE`), all `IGNORECASE` and anchored
    to line start.
  - Implement `_fallback_extract(actual_path, original_path)`: read text
    (`errors="replace"`; read error returns None), iterate logical lines, track
    the current MODULE context for containment, populate a
    `FortranParseResult(source="fallback")`. Dedup calls on `(callee, line)`.
    Infer program executable via the existing `_infer_executable`. Return None when
    all six lists are empty. Wrap the whole body so it never raises.
  - _Requirements: 1.3, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.7, 3.1, 3.2, 3.4, 3.5, 3.6, 4.2, 4.3, 4.4, 6.1, 6.2_

- [x] 4. Wire the fallback into `parse_file`
  - Wrap the fparser2 call in an inner `try/except (Exception, SystemExit)` so a
    fparser2 failure falls through to the fallback rather than the outer guard.
  - On non-None tree: set `result.source = "fparser2"`, increment
    `files_parsed_fparser2`, return.
  - On None/exception: call `_fallback_extract`; on non-None increment
    `files_parsed_fallback` and return; else increment `files_failed`, return None.
  - Preserve the outer never-raise guard and the temp-file `finally` cleanup.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 5.1_

- [x] 5. Unit tests for the fallback extractor
  - New `tests/unit/test_fortran_fallback.py` with `tmp_path` source fixtures:
    triggering (fparser2 success vs malformed-recoverable), definition recovery
    (prefixed subroutine/function, module, program, END skipped), edge recovery
    (CALL/USE incl. ONLY and continuations), false-positive guard (`IF (`, `DO `,
    array refs, commented/inline-commented CALL), containment, provenance counters,
    never-raises (monkeypatch internals), and result-shape via `_result_node_counts`/
    `_result_rel_counts`.
  - _Requirements: 1.1, 1.2, 1.5, 2.2, 2.3, 2.4, 2.7, 3.1, 3.2, 3.3, 4.2, 4.5, 6.2, 6.3_

- [x] 6. Provenance in the ingester summary and report
  - In `ingest_fortran_graph_v8.py`, add the `files_parsed_fparser2 /
    files_parsed_fallback / files_failed` breakdown to the live end-of-run summary
    and to `_dry_run`'s summary, reading from `fortran_parser.stats`.
  - Record the same breakdown in the `IngestionReportWriter` output.
  - _Requirements: 5.2, 5.4_

- [x] 7. Property-based tests for the correctness properties
  - New `tests/properties/test_fortran_fallback_props.py` (Hypothesis, 100 examples):
    Property 1 (no fallback on success), Property 2 (never raises on arbitrary
    bytes), Property 3 (definition completeness), Property 4 (edge completeness incl.
    continuations), Property 5 (no invented edges from control constructs/comments),
    Property 6 (result-shape invariance), Property 7 (containment soundness),
    Property 8 (provenance accounting sums to call count).
  - _Requirements: 1.1, 1.5, 2.1, 2.2, 2.3, 2.4, 2.7, 3.1, 3.2, 3.3, 4.1, 4.2, 4.5, 5.1, 6.1, 6.2, 6.3_

- [x] 8. Operator-run live dry-run verification (gated)
  - Run `ingest_fortran_graph_v8.py --tenant gw_v17 --mode full --dry-run` against
    the EFS worktree and confirm: total discovered unchanged (~6,935), fparser2 ~5,915,
    fallback recovers a meaningful share of the ~1,020 prior failures, and the summary
    prints the provenance split. No Neptune writes in dry-run.
  - Document the recovered counts; only after review, run the live (non-dry-run)
    ingest to MERGE the recovered nodes/edges. MERGE idempotency means a re-run over
    already-ingested files is safe.
  - DONE 2026-06-10: dry-run (parallel, --workers 3) parsed 6,923/6,935 (99.8%).
    Live ingest then ran ~3.2h: 6,926/6,935 parsed (99.9%), 45,155 nodes +
    297,712 relationships written, 0 write errors. v17 graph grew to 80,996
    nodes / 1,278,330 rels. Used the [8.34.0] parallel/streaming runner to stay
    within memory on the 7.6 GiB host.
  - _Requirements: 5.4, 6.4_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2"] },
    { "id": 1, "tasks": ["3"] },
    { "id": 2, "tasks": ["4"] },
    { "id": 3, "tasks": ["5", "6", "7"] },
    { "id": 4, "tasks": ["8"] }
  ]
}
```

Wave 0 runs the independent groundwork (provenance plumbing and the logical-line
preprocessor) in parallel. Wave 1 builds the extractor on top of both. Wave 2
wires it into `parse_file`. Wave 3 runs unit tests, property tests, and the
ingester-telemetry change in parallel (all depend only on the wired extractor and
the counters). Wave 4 is the gated operator-run live verification, which depends
on all tests passing and the telemetry being in place.

## Notes

- **Scope discipline:** production changes are limited to `_fortran_parser.py`
  (Tasks 1–4) and `ingest_fortran_graph_v8.py` (Task 6). The Neptune write helpers
  and tenant logic are untouched — the fallback returns the identical
  `FortranParseResult` shape.
- **Never-raise contract:** the fallback and its wiring must preserve the existing
  guarantee that a single bad file never aborts a multi-hour ingestion run. Task 5
  and Property 2 assert this directly.
- **No deploy required:** this feature changes an offline ingestion script, not the
  AgentCore runtime. There is no container rebuild or `update-agent-runtime` step —
  Task 8 is run on the operator host like the original Fortran ingest.
- **Idempotency:** re-running the live ingest after this lands is safe; Neptune
  MERGE de-duplicates fallback-recovered nodes/edges against any existing ones.
- **Gating:** Task 8 is operator-run and gated on review of the dry-run recovery
  counts, consistent with the AWS write-safety policy for live data changes.
