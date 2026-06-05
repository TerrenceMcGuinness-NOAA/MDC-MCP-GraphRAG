# Implementation Plan: graph-port-fortran-ast

## Overview

Port the legacy Fortran graph ingestion script to the Python tenant-aware
pipeline. Uses fparser2 to parse Fortran source files and creates a
comprehensive graph of Fortran code structure — FortranModule,
FortranSubroutine, FortranFunction, and FortranProgram nodes plus CALLS,
USES, and CONTAINS relationships — all scoped per tenant via label-prefix
isolation in Neptune. Graph-only (no embeddings, no OpenSearch, no SHAIndex).

TDD ordering: parser module + tests first (it's pure/deterministic), then
file discovery + tests, then the entry script with write helpers + tests, then
property tests (P1–P7), then gated live runs. Pure-test tasks are `[ ]*`.
All paths relative to `/mdc-mcp-rag/eib-mcp-rag-server/`.

References:
- Requirements: `.kiro/specs/graph-port-fortran-ast/requirements.md` (R1–R13)
- Design: `.kiro/specs/graph-port-fortran-ast/design.md` (components 1–3, Properties P1–P7)
- Legacy reference: `mcp_server_node/scripts/ingest_fortran_graph.py`
- Depends on: `ingest_code_v8.py` having run (temporal ordering — File nodes exist)
- Downstream: `create_shell_fortran_bridge.py` (from `graph-port-shell-ops`) requires FortranProgram nodes

## Tasks

- [x] 1. Implement `_fortran_parser.py` (FortranParser + FortranParseResult)
  - Per design §1. New file: `mcp_server_python/scripts/_fortran_parser.py`
  - `FortranParseResult` dataclass (file_path, relative_path, modules, subroutines, functions, programs, calls, uses)
  - `FortranParser.__init__(worktree_root)`: `ParserFactory(std='f2003')`, cached `_include_dirs`
  - `discover_fortran_files()`: rglob `sorc/` for FORTRAN_EXTENSIONS, exclude `.git`/`build`/`test` dirs, return sorted list
  - `discover_include_dirs()`: walk `sorc/` for dirs containing `.h`/`.inc`/`.fh` files
  - `parse_file(filepath)`: sanitize → CPP preprocess (if needed) → fparser2 parse → extract structure; catch `Exception`+`SystemExit` → return None
  - `_sanitize()`: fix dangling continuations, merge conflict markers, non-standard write commas
  - `_needs_preprocessing()`: detect CPP directives (#ifdef, #ifndef, #if, #include, #define, #else, #endif, #undef, #elif)
  - `_preprocess()`: `cpp -traditional-cpp -nostdinc -P` with discovered `-I` dirs; fallback to directive-stripping on failure
  - `_extract_structure()`: walk AST for Module_Stmt, Subroutine_Stmt, Function_Stmt, Program_Stmt, Call_Stmt, Use_Stmt
  - `_resolve_containment()`: assign parent_module to subroutines/functions within Module nodes
  - `_infer_executable()`: `sorc/<name>.fd` → `<name>.x`
  - Temp file cleanup in `finally` block regardless of success/failure
  - **Implements: R2.1–R2.5, R3.1–R3.4, R4.1–R4.7, R10.2, R10.3**

  - [x]* 1.1 Unit tests for FortranParser
    - Synthetic Fortran snippets exercising each extraction: MODULE, SUBROUTINE, FUNCTION, PROGRAM, CALL, USE statements
    - Preprocessing detection: file with `#ifdef` → `_needs_preprocessing()` returns True; plain Fortran → False
    - Sanitization: dangling continuation fixed, merge conflict markers commented, non-standard write commas repaired
    - SystemExit handling: mock fparser2 raising SystemExit → parse_file returns None (not crash)
    - None-return: mock fparser2 returning None → parse_file returns None
    - Module containment: subroutine inside MODULE → parent_module populated; standalone subroutine → parent_module is None
    - Executable inference: path `sorc/ufs_model.fd/atmos.F90` → `ufs_model.x`
    - File: `mcp_server_python/tests/unit/test_fortran_parser.py` (new)
    - **Validates: R2.1–R2.5, R3.1–R3.4, R4.1–R4.7**

- [x] 2. Implement Fortran file discovery
  - Per design §1 `discover_fortran_files()`. Exercised as part of `_fortran_parser.py` but tested in isolation
  - All 10 Fortran extensions: `.F90`, `.f90`, `.F`, `.f`, `.F95`, `.f95`, `.F03`, `.f03`, `.F08`, `.f08`
  - Exclude `.git/`, `build/`, `test/` directories
  - Traverse into submodule dirs (`sorc/ufs_model.fd/`, `sorc/gsi_enkf.fd/`, `sorc/gdas.cd/`) when checked out
  - `FileNotFoundError` if `sorc/` missing (R13.2)
  - Log informational message for empty submodules (R13.1)
  - **Implements: R1.1–R1.5, R13.1–R13.3**

  - [x]* 2.1 Unit tests for Fortran file discovery
    - Synthetic tmp directory tree with mixed extensions → only Fortran extensions discovered
    - `.git/`, `build/`, `test/` dirs excluded
    - No `sorc/` dir → raises FileNotFoundError
    - Empty submodule dir → logged info, no crash
    - File: `mcp_server_python/tests/unit/test_fortran_parser.py` (append to existing)
    - **Validates: R1.1–R1.5, R13.1–R13.3**

- [x] 3. Implement `ingest_fortran_graph_v8.py` entry script + Neptune write helpers
  - Per design §2/§3. New file: `mcp_server_python/scripts/ingest_fortran_graph_v8.py`
  - `build_ingestion_parser`, `resolve_tenant_and_mode`, `resolve_worktree_root` from `_ingest_common.py`
  - Add `COLLECTION_FORTRAN_GRAPH = "fortran_graph"` constant to `_ingest_common.py`
  - Graph-only: `build_ingestion_data_access()` → use `uda.graph_db` only (no vector_db, no SHAIndex)
  - Two-pass write strategy: Phase 1 parse all + write NODES, Phase 2 write all RELATIONSHIPS
  - `_write_module_nodes()`, `_write_subroutine_nodes()`, `_write_function_nodes()`, `_write_program_nodes()`: f-string-interpolated, back-tick-quoted labels, `tenant=None`
  - `_write_calls()`, `_write_uses()`, `_write_contains()`: Phase 2 relationship MERGE with placeholder creation for unresolved callees
  - `IngestionReportWriter`: files_discovered, files_parsed, files_failed, nodes by label, relationships by type
  - Per-file error resilience: OSError/Neptune error → WARN + continue
  - Startup connection failure → exit 1
  - `--dry-run`: parse all files, produce summary counts, NO Neptune connection
  - Progress log every 50 files
  - Parse success rate percentage in final summary
  - **Implements: R5.1–R5.6, R6.1–R6.5, R7.1–R7.4, R8.1–R8.5, R9.1–R9.4, R10.1–R10.6, R11.1–R11.3, R12.1–R12.4**

  - [x]* 3.1 Unit tests for Neptune write helpers
    - Each `_write_*` builds expected back-tick-quoted, prefix-interpolated cypher with `tenant=None`; verify against a stub graph_db recording (cypher, params, tenant)
    - Empty-prefix tenant (gw) → unprefixed labels (`:FortranModule`, not `:_FortranModule`)
    - `_write_calls` creates placeholder FortranSubroutine for unresolved callee (R6.5)
    - `_write_contains` creates CONTAINS edges only for subroutines/functions with parent_module set
    - File: `mcp_server_python/tests/unit/test_fortran_graph_writes.py` (new)
    - **Validates: R5.1–R5.6, R6.1–R6.5**

- [x] 4. Checkpoint — parser + script importable, unit tests green
  - `python3.12 -c "import sys; sys.path.insert(0,'mcp_server_python/scripts'); from _fortran_parser import FortranParser; from ingest_fortran_graph_v8 import main"`
  - `pytest mcp_server_python/tests/unit/test_fortran_parser.py mcp_server_python/tests/unit/test_fortran_graph_writes.py -v`
  - Ensure all pass; ask the user if questions arise

- [x]* 5. Write property tests P1 + P7 — graph completeness + parse failure resilience
  - **Property 1: Fortran graph completeness**
  - Synthetic worktree (tmp dir) with N Fortran files containing MODULE/SUBROUTINE/FUNCTION/PROGRAM stmts; drive write logic against stub graph_db; assert N files contribute nodes (N distinct file_path values across all node MERGE calls)
  - **Property 7: Parse failure resilience**
  - Batch of N Fortran files where K are intentionally unparseable (binary content, syntax errors); verify (N-K) successful files all produce node MERGE calls and the ingester does not abort
  - File: `mcp_server_python/tests/properties/test_fortran_graph_props.py` (new)
  - **Validates: R1.1, R5.1–R5.4, R10.1–R10.3**

- [x]* 6. Write property tests P2 + P3 — CALLS and USES edge correctness
  - **Property 2: CALLS edge correctness**
  - Generate Fortran with random CALL statements → parse → verify each call produces a CALLS MERGE to a FortranSubroutine with the correct callee name
  - **Property 3: USES edge correctness**
  - Generate Fortran with random USE statements → parse → verify each use produces a USES MERGE to a FortranModule with the correct module name
  - File: `mcp_server_python/tests/properties/test_fortran_graph_props.py`
  - **Validates: R4.6, R4.7, R6.1, R6.2**

- [x]* 7. Write property tests P4 + P5 — CONTAINS hierarchy + idempotence
  - **Property 4: CONTAINS hierarchy**
  - Generate Fortran with subroutines/functions inside MODULE blocks → parse → verify each contained entity gets a CONTAINS edge from its parent module
  - **Property 5: Idempotence**
  - Run the write logic twice against a stub graph_db that models MERGE semantics (dict keyed by node identity); assert the node/edge set after run 2 == after run 1
  - File: `mcp_server_python/tests/properties/test_fortran_graph_props.py`
  - **Validates: R5.5, R6.3, R6.4, R7.4**

- [x]* 8. Write property test P6 — tenant isolation
  - **Property 6: Tenant isolation**
  - Two tenants (gw_v17, gw_sfs) over the same synthetic Fortran content; assert all node labels for tenant A start with A's label_prefix and are disjoint from labels produced for B
  - File: `mcp_server_python/tests/properties/test_fortran_graph_props.py`
  - **Validates: R5.6, R8.1**

- [ ] 9. Phase A — Operational: run Fortran graph ingestion for gw_v17 (GATED)

  - [ ] 9.1 Pre-flight
    - EFS mounted at `/mnt/workflow/dev-v17`; `sorc/` directory exists with submodules checked out (`--depth 1`)
    - `python3.12 -c "import fparser; print(fparser.__version__)"` → fparser2 importable
    - `cpp --version` → cpp available on operator host

  - [ ] 9.2 Dry-run to estimate counts
    - `python3.12 mcp_server_python/scripts/ingest_fortran_graph_v8.py --tenant gw_v17 --mode full --dry-run`
    - Review: files discovered, files parsed, files failed, parse success %, estimated node/edge counts
    - Compare to baseline (gw: 671 programs, 27,941 subroutines, 5,744 functions, 4,800 modules)
    - Expected: lower counts than baseline (shallow submodules); ≥85% parse success rate

  - [ ] 9.3 STOP-AND-CONFIRM before Neptune writes
    - Writes `GW_V17_FortranModule`/`FortranSubroutine`/`FortranFunction`/`FortranProgram` nodes + CALLS/USES/CONTAINS relationships to production Neptune
    - Estimated runtime: 30–60 minutes (fparser2 parsing is CPU-bound)
    - Reversible via label-based DETACH DELETE: `MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'GW_V17_Fortran') DETACH DELETE n`
    - Confirm with the user

  - [ ] 9.4 Run live Fortran graph ingestion
    - `python3.12 mcp_server_python/scripts/ingest_fortran_graph_v8.py --tenant gw_v17 --mode full` with AWS env vars + `MCP_WORKTREE_ROOT_OVERRIDE`
    - Monitor progress logs (every 50 files); expect ~35K nodes + 2.7M edges at scale
    - **Implements: R5, R6, R9 (live)**

  - [ ] 9.5 Verify in Neptune
    - `GW_V17_FortranModule` count > 0; `GW_V17_FortranProgram` count > 0
    - CALLS edge count > 0; USES edge count > 0; CONTAINS edge count > 0
    - Spot-check: `MATCH (p:GW_V17_FortranProgram {name:'JGLOBAL_FORECAST'}) RETURN p` (or equivalent gw_v17 program name)
    - **Implements: R5, R6 (live verification)**

  - [ ] 9.6 Run the Shell→Fortran bridge (unblocked by FortranProgram nodes)
    - `python3.12 mcp_server_python/scripts/create_shell_fortran_bridge.py --tenant gw_v17 --dry-run` first to review matches
    - Then: `python3.12 mcp_server_python/scripts/create_shell_fortran_bridge.py --tenant gw_v17` (live)
    - The bridge's R7 prerequisite guard now passes (FortranProgram nodes exist)
    - Expect EXECUTES edges from ShellScript → FortranProgram
    - **Implements: R12.2 (ordering dependency satisfied)**

- [ ] 10. Checkpoint — code phase complete
  - All unit + property tests green; Fortran graph ran clean for gw_v17; bridge created EXECUTES edges
  - `trace_full_execution_chain` can now traverse Shell→Fortran→Fortran call chains (once `tenant-id-tool-exposure` runtime deploy is live)
  - Ask the user if questions arise

## Notes

- **Graph-only by design (R7)** — no Bedrock, no OpenSearch, no SHAIndex.
  Neptune MERGE is the idempotency mechanism.
- **Ordering (R12)** — the Shell→Fortran bridge (Spec 1, `graph-port-shell-ops`)
  requires `{prefix}FortranProgram` nodes to exist. This spec creates them.
  Task 9.6 runs the bridge after ingestion.
- **Label prefixing** uses f-string interpolation + `tenant=None` (the proven
  pattern from `delete_tenant_indices.py` and `graph-port-shell-ops`), NOT
  `_rewrite_cypher`.
- **fparser2 resilience** — the legacy ingester had ~15% parse failure rate on
  the full gw worktree. Non-standard Fortran is common. The sanitization step
  + per-file catch of `Exception`+`SystemExit` ensures partial failure never
  aborts the run.
- **Estimated runtime** — fparser2 is CPU-bound; expect 30–60 minutes for the
  full gw_v17 worktree. Neptune writes are async and fast.
- **Shallow submodules** — gw_v17 uses `--depth 1`; some files from deep
  submodule history may not be present. Node counts will be lower than the
  full baseline.
- Tasks marked with `*` are optional and can be skipped for faster MVP.
- Property tests validate universal correctness properties from the design.
- This is Spec 3 of the gap-B graph-relationship-parity series.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["5", "6", "7", "8"] },
    { "id": 4, "tasks": ["9.1"] },
    { "id": 5, "tasks": ["9.2"] },
    { "id": 6, "tasks": ["9.3"] },
    { "id": 7, "tasks": ["9.4"] },
    { "id": 8, "tasks": ["9.5"] },
    { "id": 9, "tasks": ["9.6"] }
  ]
}
```
