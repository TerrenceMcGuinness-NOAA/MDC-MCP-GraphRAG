# Requirements Document

## Introduction

The Fortran AST ingester (`ingest_fortran_graph_v8.py` + `_fortran_parser.py`)
parses Fortran source with fparser2. On the `gw_v17` worktree it parses 5,915 of
6,935 discovered files (85.3%) — **1,020 files (14.7%) fail** and produce zero
nodes and zero relationships. `parse_file` catches every failure (including
fparser2's `SystemExit`) and returns `None`, so those files contribute nothing
to the graph: their modules, subroutines, functions, CALLS, and USES edges are
all missing.

This feature adds a **regex-based fallback extractor** that runs only when
fparser2 returns `None` for a file. The fallback scans the (sanitized,
preprocessed) source text for the structural statements that matter most for the
graph — `SUBROUTINE`/`FUNCTION`/`MODULE`/`PROGRAM` definitions, `CALL` statements,
and `USE` statements — using line-oriented regular expressions. It does not build
a full AST and does not attempt expression-level accuracy; it recovers the
relationship edges (CALLS, USES) and the definition nodes that a full parse would
have produced, accepting some imprecision (no reliable line numbers for callees,
best-effort containment).

After this feature lands:
- Parse coverage rises from ~85% toward ~99% of discovered files (the residual
  being files too malformed for even regex extraction, e.g. truncated files)
- The ~1,020 currently-silent files contribute FortranSubroutine / FortranFunction
  / FortranModule / FortranProgram nodes plus CALLS and USES edges
- Per-file telemetry distinguishes `parsed_fparser2`, `parsed_fallback`, and
  `failed` so the recovery rate is observable in the ingestion report

This feature is independent of the `graph-port-*` series and the
`scalable-ingestion-pipeline` spec. It modifies only `_fortran_parser.py` (adds
the fallback path) and the report counters; the two-pass Neptune write strategy
in `ingest_fortran_graph_v8.py` is unchanged because the fallback produces the
same `FortranParseResult` shape.

## Glossary

- **FortranParser**: The existing class in `_fortran_parser.py` that wraps
  fparser2, applies Source_Sanitization and CPP_Preprocessing, and extracts a
  `FortranParseResult` from a Fortran source file
- **FortranParseResult**: The dataclass returned by `parse_file` carrying lists
  of modules, subroutines, functions, programs, calls, and uses for one file
- **fparser2**: The Fortran 2003/2008 parser library; the primary (preferred)
  parse path. Fails on ~15% of GFS/UFS/JEDI sources via exceptions or `SystemExit`
- **Fallback_Extractor**: The new regex-based extractor that runs only when the
  fparser2 path returns `None`, recovering structural definitions and CALLS/USES
  edges from the source text without building an AST
- **Source_Sanitization**: The existing pre-parse step that fixes dangling
  continuations, merge-conflict markers, and non-standard write commas
- **CPP_Preprocessing**: The existing pre-parse step that runs `cpp` (or a
  directive-stripping fallback) on files containing C preprocessor directives
- **Parse_Provenance**: A per-result marker recording whether a file was parsed
  by fparser2, recovered by the Fallback_Extractor, or failed entirely
- **Free_Form / Fixed_Form**: Fortran source layouts. Free-form (`.f90`/`.F90`)
  uses `&` continuations and `!` comments anywhere; fixed-form (`.f`/`.F`) uses
  column-6 continuation and `c`/`*`/`!` comment markers in column 1
- **Continuation_Line**: A statement split across multiple physical lines with a
  trailing `&` (free-form) so a `CALL` or `USE` may span more than one line

## Requirements

### Requirement 1: Fallback Triggering

**User Story:** As an ingestion operator, I want the regex fallback to run only
when fparser2 fails, so that successful AST parses keep their full fidelity and
the fallback adds coverage without regressing accurate results.

#### Acceptance Criteria

1. WHEN the fparser2 parse path produces a non-None tree, THE FortranParser SHALL
   use the AST extraction result and SHALL NOT invoke the Fallback_Extractor
2. WHEN the fparser2 parse path returns `None` or raises any `Exception` or
   `SystemExit`, THE FortranParser SHALL invoke the Fallback_Extractor on the
   sanitized/preprocessed source text before returning
3. WHEN the Fallback_Extractor also recovers nothing (zero definitions and zero
   edges), THE FortranParser SHALL return `None` so the file is counted as failed
4. THE FortranParser SHALL run the Fallback_Extractor on the same
   sanitized/preprocessed text used for the fparser2 attempt, so that merge-marker
   and continuation fixes already apply
5. THE Fallback_Extractor SHALL NOT raise; any internal error SHALL be caught and
   treated as "recovered nothing" so a fallback bug can never abort an ingestion run

### Requirement 2: Definition Extraction

**User Story:** As a graph consumer, I want the fallback to recover module,
subroutine, function, and program definitions, so that nodes exist for files
fparser2 cannot parse.

#### Acceptance Criteria

1. THE Fallback_Extractor SHALL recognize `MODULE <name>` statements (excluding
   `MODULE PROCEDURE`) and emit a module entry with the module name
2. THE Fallback_Extractor SHALL recognize `SUBROUTINE <name>` statements,
   including those with a leading prefix (`PURE`, `ELEMENTAL`, `RECURSIVE`,
   `MODULE`), and emit a subroutine entry with the subroutine name
3. THE Fallback_Extractor SHALL recognize `FUNCTION <name>` statements, including
   those with a leading type/attribute prefix (e.g. `REAL FUNCTION`,
   `INTEGER(i_kind) FUNCTION`, `PURE FUNCTION`), and emit a function entry
4. THE Fallback_Extractor SHALL recognize `PROGRAM <name>` statements and emit a
   program entry, inferring the executable name from a `sorc/<name>.fd` path
   segment when present (matching the existing `_infer_executable` behavior)
5. THE Fallback_Extractor SHALL be case-insensitive for all Fortran keywords
6. THE Fallback_Extractor SHALL ignore keyword occurrences inside comments
   (lines whose first non-blank character is `!`, or `c`/`C`/`*` in column 1 for
   fixed-form) and inside character-string literals where feasible
7. THE Fallback_Extractor SHALL ignore `END SUBROUTINE`, `END FUNCTION`,
   `END MODULE`, and `END PROGRAM` statements so closings are not mistaken for
   definitions

### Requirement 3: Relationship Extraction

**User Story:** As a graph consumer, I want the fallback to recover CALLS and USES
edges, so that traversal tools return results for files fparser2 cannot parse.

#### Acceptance Criteria

1. THE Fallback_Extractor SHALL recognize `CALL <name>` statements and emit a call
   entry with the callee name, stripping any argument list (`(...)`) from the name
2. THE Fallback_Extractor SHALL recognize `USE <module>` statements and emit a use
   entry with the module name, capturing the `ONLY:` clause text when present
3. THE Fallback_Extractor SHALL handle a `CALL` or `USE` statement split across
   Continuation_Lines by joining trailing-`&` continuations before matching
4. THE Fallback_Extractor SHALL NOT emit a call entry for `CALL` tokens that are
   substrings of other identifiers (e.g. a variable named `recall`); matching
   SHALL require a Fortran statement boundary before the keyword
5. WHERE a callee or module name cannot be determined for a candidate line, THE
   Fallback_Extractor SHALL skip that line rather than emit a malformed entry
6. THE Fallback_Extractor MAY set `line` to the physical line number of the
   statement when cheaply available, and SHALL otherwise set it to `None`

### Requirement 4: Result Shape and Containment

**User Story:** As the ingestion script, I want the fallback result to be the same
`FortranParseResult` shape as a full parse, so that the existing two-pass Neptune
writer needs no changes.

#### Acceptance Criteria

1. THE Fallback_Extractor SHALL return a `FortranParseResult` populated with the
   same fields (`file_path`, `relative_path`, `modules`, `subroutines`,
   `functions`, `programs`, `calls`, `uses`) as the fparser2 path
2. THE Fallback_Extractor SHALL set each subroutine's and function's
   `parent_module` to the name of the most recently opened `MODULE` block when the
   definition textually follows a module statement and precedes its `END MODULE`,
   and SHALL set it to `None` otherwise
3. THE Fallback_Extractor SHALL populate `line_start` with the physical line
   number of each definition statement
4. THE Fallback_Extractor SHALL set `return_type` to `None` for functions (the
   fallback does not resolve return types)
5. THE node and relationship counting helpers (`_result_node_counts`,
   `_result_rel_counts`) SHALL operate unchanged on a fallback-produced result

### Requirement 5: Telemetry and Provenance

**User Story:** As an ingestion operator, I want the report to distinguish
fparser2 parses from fallback recoveries, so that I can measure the fallback's
contribution and watch for over-broad regex matches.

#### Acceptance Criteria

1. THE FortranParser SHALL maintain counters for files parsed by fparser2, files
   recovered by the Fallback_Extractor, and files that failed both paths
2. THE Fortran_AST_Ingester SHALL include the fparser2 / fallback / failed
   breakdown in its end-of-run summary and in the JSON ingestion report
3. THE FortranParser SHALL record Parse_Provenance on each `FortranParseResult`
   (e.g. a `source` field valued `"fparser2"` or `"fallback"`) without breaking
   existing consumers that ignore the field
4. THE dry-run mode (`--dry-run`) SHALL report the same fparser2 / fallback /
   failed breakdown so coverage can be measured without writing to Neptune

### Requirement 6: Correctness Safeguards

**User Story:** As a graph maintainer, I want the fallback to avoid polluting the
graph with false edges, so that the recovered data is trustworthy.

#### Acceptance Criteria

1. THE Fallback_Extractor SHALL NOT emit duplicate call entries for the same
   (callee, line) pair within a single file
2. THE Fallback_Extractor SHALL NOT treat Fortran intrinsic control constructs
   (`IF`, `DO`, `WHERE`, `FORALL`, `SELECT`) or array/function references as `CALL`
   statements
3. THE Fallback_Extractor SHALL exclude `CALL` statements that are themselves
   commented out or appear after an inline `!` comment on the same line
4. WHEN the same file is ingested twice, THE Neptune MERGE_Semantics SHALL ensure
   fallback-produced nodes and edges are idempotent (no duplication), identical to
   the fparser2 path
5. THE feature SHALL include unit tests with representative malformed-but-recoverable
   Fortran fixtures (free-form and fixed-form) asserting the recovered definitions
   and edges, plus a negative fixture asserting no false `CALL` edges from `IF (`
   / `DO ` / array references
