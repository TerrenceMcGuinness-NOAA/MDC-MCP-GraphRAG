# Implementation Plan: ECF Manual Documentation Generator

## Overview

Implement `add_ecf_manual_docs.py` — a single-file Python CLI tool that reads a CSV reference file and inserts standardized `%manual`/`%end` documentation blocks into ecFlow `.ecf` script files. The tool uses only Python 3.12 stdlib (`csv`, `textwrap`, `pathlib`, `argparse`, `re`). Tests use pytest + hypothesis.

Build order follows a bottom-up approach: core text utilities → CSV parsing → block generation → file operations → CLI orchestration → property tests → integration tests.

## Tasks

- [ ] 1. Core text utilities
  - [ ] 1.1 Implement `sanitize_text` and `wrap_text` functions
    - Create file `supported_repos/global-workflow_forked/tools/add_ecf_manual_docs.py`
    - Implement `sanitize_text(text: str) -> str` — replaces em-dashes (U+2014) with `--`, normalizes whitespace
    - Implement `wrap_text(text: str, width: int = 72) -> str` — wraps text to 72 chars preserving paragraph breaks (double-newline sequences)
    - Implement `derive_task_name(ecf_filename: str) -> str` — strips `.ecf` extension and leading `j` character
    - _Requirements: 8.1, 8.2, 8.3, 3.2_

  - [ ]* 1.2 Write property tests for text utilities (Properties 3, 9, 10, 11)
    - **Property 3: Task name derivation** — for any alphanumeric+underscore string X, `derive_task_name("j" + X + ".ecf")` == X
    - **Property 9: Text wrapping respects 72-character limit** — every output line ≤ 72 chars (except single words > 72)
    - **Property 10: Em-dash sanitization** — output contains zero U+2014 characters; each replaced by `--`
    - **Property 11: Paragraph preservation** — paragraph breaks in output ≥ paragraph breaks in input
    - **Validates: Requirements 3.2, 8.1, 8.2, 8.3**

- [ ] 2. CSV parsing and entry consolidation
  - [ ] 2.1 Implement `parse_csv` and `consolidate_entries`
    - Define dataclasses: `CsvRow`, `ConsolidatedEntry`, `Stats`
    - Implement `parse_csv(csv_path: Path) -> list[dict[str, str]]` — uses `csv.DictReader`, handles quoted fields with embedded commas
    - Implement `consolidate_entries(rows: list[dict[str, str]]) -> dict[str, ConsolidatedEntry]` — groups rows by job_name preserving order
    - Handle edge cases: missing file (exit code 1, stderr message), malformed rows (skip + warn)
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ]* 2.2 Write property tests for CSV parsing (Properties 1, 2)
    - **Property 1: CSV parsing round-trip for quoted fields** — strings with commas survive quote→parse round-trip
    - **Property 2: Consolidation groups all entries** — K rows with same job_name produce one entry with K descriptions and K troubleshooting texts in order
    - **Validates: Requirements 1.2, 1.3**

- [ ] 3. Manual block generation
  - [ ] 3.1 Implement `format_manual_block`
    - Implement `format_manual_block(entry: ConsolidatedEntry, task_name: str) -> str`
    - Single-entry format: `%manual\n\nTASK <name>\n\nPURPOSE: <desc>\n\nTROUBLESHOOTING\n\n<text>\n\n%end\n`
    - Multi-entry format: numbered sub-sections (1., 2., ...) for both PURPOSE and TROUBLESHOOTING
    - Apply `sanitize_text` and `wrap_text` to all description and troubleshooting content
    - Ensure block ends with exactly `%end\n`
    - _Requirements: 3.1, 3.3, 3.4, 8.1, 8.3, 8.4_

  - [ ]* 3.2 Write property tests for block generation (Properties 4, 5, 12)
    - **Property 4: Manual block structural invariants** — starts with `%manual\n`, ends with `%end\n`, contains TASK line, PURPOSE section, TROUBLESHOOTING heading in order
    - **Property 5: All consolidated descriptions appear in output** — N descriptions produce N numbered items in PURPOSE; M troubleshooting produce M numbered items
    - **Property 12: Trailing newline invariant** — block ends with exactly `%end\n`
    - **Validates: Requirements 3.1, 3.3, 3.4, 8.4**

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. File operations
  - [ ] 5.1 Implement `resolve_file_path` and `insert_manual_block`
    - Implement `resolve_file_path(job_name: str, base_dir: Path) -> Path | None` — tries literal path first, then searches `ecf/scripts/` tree by basename
    - Implement `insert_manual_block(file_content: str, manual_block: str) -> str` — insertion priority: replace existing `%manual`...`%end`, insert after `%include <tail.h>`, or append at EOF
    - Preserve all content above the insertion point byte-for-byte
    - _Requirements: 2.1, 2.2, 2.3, 4.1, 4.2, 4.3, 4.4_

  - [ ]* 5.2 Write property tests for file operations (Properties 6, 7, 8)
    - **Property 6: Insertion after tail.h preserves prefix content** — content up to and including `%include <tail.h>` remains byte-for-byte identical
    - **Property 7: Existing manual block replacement produces single block** — result contains exactly one `%manual`...`%end` block matching new content
    - **Property 8: Idempotent insertion** — `insert(insert(content, block), block) == insert(content, block)`
    - **Validates: Requirements 4.1, 4.2, 4.4, 5.1, 5.2**

- [ ] 6. CLI and main orchestration
  - [ ] 6.1 Implement `parse_args`, `print_summary`, and `main`
    - Implement `parse_args(argv: list[str] | None = None) -> argparse.Namespace` — flags: `--base-dir`, `--csv-path`, `--dry-run`, `--verbose`
    - Implement `print_summary(stats: Stats) -> None` — ASCII-only output with `[OK]`, `[WARN]`, `[ERROR]`, `[DRY-RUN]` markers
    - Implement `main() -> int` — orchestrates the full pipeline: parse CSV → consolidate → resolve paths → generate blocks → insert/write → report summary
    - Exit codes: 0 (success), 1 (fatal error), 2 (partial failure)
    - Support `--dry-run` (print what would change, write nothing) and `--verbose` (per-file action log)
    - Handle SKIPPED/NOT ON DISK entries (generate block with notation if file exists, skip if file not found)
    - _Requirements: 2.4, 4.3, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3_

  - [ ]* 6.2 Write property tests for summary statistics (Property 14)
    - **Property 14: Summary statistics consistency** — `files_updated + files_not_found + errors` == total unique job_names attempted
    - **Validates: Requirements 6.3**

- [ ] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Integration and dry-run tests
  - [ ]* 8.1 Write property test for dry-run (Property 13)
    - **Property 13: Dry-run does not modify files** — invoke with `--dry-run`, verify all files remain byte-for-byte identical
    - **Validates: Requirements 7.2**

  - [ ]* 8.2 Write integration test (end-to-end with temp directory)
    - Create temp directory with sample `.ecf` files (with and without existing `%manual` blocks, with and without `%include <tail.h>`)
    - Create a small CSV with 3-4 rows including a consolidated (duplicate job_name) entry
    - Run the tool, verify: correct block inserted at correct location, idempotent on re-run, summary counts match
    - Test against `example_doc.ecf` reference format
    - _Requirements: 4.1, 4.2, 4.3, 5.1, 5.2, 7.1_

  - [ ]* 8.3 Write unit tests for specific scenarios
    - Test CSV file not found → exit code 1 + stderr message
    - Test SKIPPED entries → block contains SKIPPED text
    - Test verbose output → per-file log lines emitted
    - Test real CSV subset → 3-4 rows from actual `ecf_script_discriptions.txt`
    - _Requirements: 1.4, 6.1, 7.3_

- [ ] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the 14 universal correctness properties from the design document using Hypothesis
- Unit tests validate specific examples and edge cases
- The tool is a single file (`add_ecf_manual_docs.py`) — all functions coexist in one module
- Tests live at `supported_repos/global-workflow_forked/tools/tests/test_add_ecf_manual_docs.py`
- Python 3.12 stdlib only for the tool; pytest + hypothesis for tests
- ASCII-only console output (`[OK]`, `[WARN]`, `[ERROR]`, `[DRY-RUN]`)
- No auto-commit — the tool modifies files in-place but does not interact with git

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1"] },
    { "id": 3, "tasks": ["3.2", "5.1"] },
    { "id": 4, "tasks": ["5.2", "6.1"] },
    { "id": 5, "tasks": ["6.2", "8.1"] },
    { "id": 6, "tasks": ["8.2", "8.3"] }
  ]
}
```
