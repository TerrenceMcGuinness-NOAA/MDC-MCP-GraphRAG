# Implementation Plan: graph-port-shell-ops

## Overview

Port the legacy shell operational graph (`ingest_shell_graph_v8.py`) and the
Shell→Fortran execution bridge (`create_shell_fortran_bridge.py`) to the
Python tenant-aware pipeline. Graph-only (no embeddings, no OpenSearch, no
SHAIndex) — Neptune `MERGE` provides idempotency. Produces SOURCES, INVOKES,
EXPORTS, DEPENDS_ON_ENV, READS_CONFIG, DEFINES (shell graph) and EXECUTES
(Fortran bridge), all tenant-label-prefixed.

TDD ordering: parser module + tests first (it's pure/deterministic), then the
shell-graph entry script, then the Fortran bridge, then property tests, then
gated live runs. Pure-test tasks are `[ ]*`. All paths relative to
`/mdc-mcp-rag/eib-mcp-rag-server/`.

References:
- Requirements: `.kiro/specs/graph-port-shell-ops/requirements.md` (R1–R10)
- Design: `.kiro/specs/graph-port-shell-ops/design.md` (components 1–6, Properties P1–P6)
- Legacy reference: `mcp_server_node/scripts/ingest_shell_graph_v8.py`, `create_shell_fortran_bridge.py`
- Depends on: `ingest_code_v8.py` having created `{prefix}FortranProgram` nodes (for the bridge)

## Tasks

- [ ] 1. Implement `_shell_parser.py` (ShellScriptParser + ShellParseResult)
  - Per design §1. New file: `mcp_server_python/scripts/_shell_parser.py`
  - `ShellParseResult` dataclass (path, name, type, category, sources, invokes, exports, env_deps, functions, configs)
  - `ShellScriptParser` with the 7 verbatim regex patterns (source, invoke_var, invoke_direct, export, env_use, function, config), the builtin-var/func filters, the `_PATH_RESOLUTIONS` and `_EXTERNAL_PACKAGES` tables
  - `parse(file_path, content) -> ShellParseResult`, `classify_type()`, `classify_category()`, `_resolve_path()`
  - Skip comment lines; truncate export values to 200 chars; dedupe env_deps
  - **Implements: R2.1–R2.8, R1.3, R1.4**

  - [ ]* 1.1 Unit tests for ShellScriptParser
    - Synthetic shell content exercising each extraction: `. x.sh` / `source x.sh` (SOURCES), `${VAR}/y.sh` + `./z.sh` (INVOKES), `export A=b` (EXPORTS), `$C`/`${D}` (env_deps), `foo() {` / `function bar {` (functions), `config.base` (configs)
    - Edge cases: comment lines skipped, builtin vars filtered, multi-line content, quoted paths, type/category classification per path
    - File: `mcp_server_python/tests/unit/test_shell_parser.py` (new)
    - **Validates: R2.1–R2.8**

- [ ] 2. Implement shell-script discovery
  - Per design §3/§6. In `mcp_server_python/scripts/ingest_shell_graph_v8.py` (or a shared `_shell_discovery` helper)
  - `discover_shell_scripts(worktree_root, mode)`: full mode = rglob filtering `.sh/.bash/.ksh` + extensionless J-Jobs (dev/jobs or uppercase J-prefix) + ex-scripts (dev/scripts, ex-prefix); diff mode = `git diff --name-only baseline..HEAD` through the same filter
  - Exclude `.git/`; skip binary files (null byte in first 512 bytes)
  - **Implements: R1.1, R1.2**

- [ ] 3. Implement `ingest_shell_graph_v8.py` entry script
  - Per design §2/§4. New file: `mcp_server_python/scripts/ingest_shell_graph_v8.py`
  - `build_ingestion_parser`, `resolve_tenant_and_mode`, `resolve_worktree_root`; graph-only (use `uda.graph_db`, ignore vector_db)
  - Per-file: parse → write script node + all 6 relationship types via the f-string-interpolated, back-tick-quoted, `tenant=None` cypher templates from design §4
  - `IngestionReportWriter`: total_files_processed, nodes-by-label, relationships-by-type
  - Per-file error resilience (OSError/Neptune error → WARN + continue); startup connection failure → exit 1
  - `--dry-run`: parse + summarize, zero writes
  - **Implements: R3.1–R3.7, R5.1–R5.4, R6.1–R6.4, R8.1/R8.3, R9.1–R9.4, R10.1/R10.3**

  - [ ]* 3.1 Unit tests for the cypher write helpers
    - Each `_write_*` builds the expected back-tick-quoted, prefix-interpolated cypher with `tenant=None`; verify against a stub graph_db recording (cypher, params, tenant)
    - Empty-prefix tenant (gw) → unprefixed labels (`:ShellScript`, not `:_ShellScript`)
    - File: `mcp_server_python/tests/unit/test_shell_graph_writes.py` (new)
    - **Validates: R3.1–R3.7**

- [ ] 4. Implement `create_shell_fortran_bridge.py` entry script
  - Per design §5. New file: `mcp_server_python/scripts/create_shell_fortran_bridge.py`
  - `KNOWN_EXEC_MAPPINGS` table, `EXEC_PATTERNS` list, `extract_exec_references(content)`, `match_exec_to_program(exec_name, programs)` with all 6 strategies
  - R7 guard: query `{prefix}FortranProgram` count; exit 1 with warning if zero
  - Fetch programs, scan shell scripts, match, MERGE EXECUTES edges (`tenant=None`); unmatched → log + continue
  - `IngestionReportWriter`: scripts scanned, refs found, matches created, unmatched count; `--dry-run` reports without writing
  - **Implements: R4.1–R4.5, R7.1–R7.3, R8.2/R8.4, R10.2**

  - [ ]* 4.1 Unit tests for `match_exec_to_program`
    - Exercise all 6 strategies: known-mapping (enkf→enkf_main), exact, _main suffix, prefix, exec-starts-with-program, progressive suffix stripping
    - `None`-mapped known exec (wgrib2) → no match; unmatched exec → None
    - File: `mcp_server_python/tests/unit/test_fortran_bridge_match.py` (new)
    - **Validates: R4.2, R4.4**

- [ ] 5. Checkpoint — parser + scripts importable, unit tests green
  - `python3.12 -c "import sys; sys.path.insert(0,'mcp_server_python'); from scripts.ingest_shell_graph_v8 import main; from scripts.create_shell_fortran_bridge import main"`
  - `pytest mcp_server_python/tests/unit/test_shell_parser.py test_shell_graph_writes.py test_fortran_bridge_match.py`
  - Ensure all pass; ask the user if questions arise

- [ ]* 6. Write property test P1 — shell graph completeness
  - **Property 1: Shell graph completeness**
  - Synthetic worktree (tmp dir) with N shell scripts; drive the write logic against a stub graph_db; assert N `{prefix}ShellScript` MERGE calls
  - File: `mcp_server_python/tests/properties/test_shell_graph_props.py` (new)
  - **Validates: R1.1, R3.1**

- [ ]* 7. Write property test P3 — env-var tenant isolation
  - **Property 3: Env-var tenant isolation**
  - Two tenants (gw_v17, gw_sfs) over the same synthetic content; assert all EnvironmentVariable MERGE labels for tenant A start with A's prefix and are disjoint from B's
  - File: `mcp_server_python/tests/properties/test_shell_graph_props.py`
  - **Validates: R3.2, R5.1**

- [ ]* 8. Write property test P5 — idempotence
  - **Property 5: Idempotence**
  - Run the write logic twice against a stub graph_db that models MERGE semantics (dict keyed by node identity); assert the node/edge set after run 2 == after run 1
  - File: `mcp_server_python/tests/properties/test_shell_graph_props.py`
  - **Validates: R3.5, R6.4**

- [ ]* 9. Write property test P4 + P6 — bridge correctness + prerequisite guard
  - **Property 4: EXECUTES bridge correctness** — for synthetic shell content referencing exec X and a stub program set containing the match, assert an EXECUTES MERGE from the script to the matched program
  - **Property 6: Fortran-node prerequisite guard** — with zero FortranProgram nodes, assert the bridge exits 1 with the warning and creates no edges
  - File: `mcp_server_python/tests/properties/test_shell_graph_props.py`
  - **Validates: R4.1–R4.3, R7.1, R7.2**

- [ ] 10. Phase A — Operational: run shell graph + bridge for gw_v17 (GATED)

  - [ ] 10.1 Pre-flight
    - EFS mounted; `{prefix}FortranProgram` nodes exist for gw_v17 (from the completed code ingest — verified 2026-05-30)
    - `opensearchpy`/data layer importable as the run-as user

  - [ ] 10.2 STOP-AND-CONFIRM before Neptune writes
    - Writes `GW_V17_ShellScript`/`EnvironmentVariable`/`ConfigFile`/`ShellFunction` nodes + 6 relationship types to production Neptune
    - Reversible via `delete_tenant_indices.py --tenant gw_v17` (per-label DETACH DELETE now covers these labels)
    - Confirm with the user

  - [ ] 10.3 Run shell graph ingestion
    - `python3.12 mcp_server_python/scripts/ingest_shell_graph_v8.py --tenant gw_v17 --mode full` with the AWS env vars + `MCP_WORKTREE_ROOT_OVERRIDE`
    - Expect ~300+ ShellScript nodes, SOURCES/INVOKES/EXPORTS/DEPENDS_ON_ENV/READS_CONFIG/DEFINES edges (compare to the legacy gw counts in requirements)
    - **Implements: R3 (live)**

  - [ ] 10.4 Run the Fortran bridge
    - `python3.12 mcp_server_python/scripts/create_shell_fortran_bridge.py --tenant gw_v17` (dry-run first to review matches)
    - Expect ~85 EXECUTES edges (legacy gw baseline)
    - **Implements: R4, R7 (live)**

  - [ ] 10.5 Verify
    - Neptune: `GW_V17_ShellScript` count > 0; SOURCES/INVOKES/EXECUTES edge counts non-zero
    - `trace_full_execution_chain("JGLOBAL_FORECAST", tenant_id="gw_v17")` traverses Shell→Shell→Fortran (NOTE: requires `tenant-id-tool-exposure` to be deployed for the tenant_id parameter)
    - **Implements: R3, R4 (live verification)**

- [ ] 11. Checkpoint — code phase complete
  - All unit + property tests green; shell graph + bridge ran clean for gw_v17; trace traversal confirmed (post tenant-id deploy)
  - Ask the user if questions arise

## Notes

- **Graph-only by design (R6)** — no Bedrock, no OpenSearch, no SHAIndex.
  Neptune MERGE is the idempotency mechanism.
- **Ordering (R7)** — the bridge needs `{prefix}FortranProgram` nodes; gw_v17
  already has them from the 2026-05-30 code ingest, so Phase A can run without
  re-running code ingestion.
- **Label prefixing** uses f-string interpolation + `tenant=None` (the proven
  pattern from `delete_tenant_indices.py`), NOT `_rewrite_cypher`.
- **Live trace verification (10.5)** depends on `tenant-id-tool-exposure` being
  deployed so the `tenant_id` parameter is reachable — sequence this spec's
  Phase A verification after that bugfix deploys, or verify via direct Neptune
  queries in the interim.
- This is Spec 1 (Gap B) of the graph-relationship-parity series;
  `graph-port-workflow-structure` and `graph-port-python-community` follow.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2"] },
    { "id": 2, "tasks": ["3"] },
    { "id": 3, "tasks": ["4"] },
    { "id": 4, "tasks": ["5"] },
    { "id": 5, "tasks": ["6", "7", "8", "9"] },
    { "id": 6, "tasks": ["10.1"] },
    { "id": 7, "tasks": ["10.2"] },
    { "id": 8, "tasks": ["10.3"] },
    { "id": 9, "tasks": ["10.4"] },
    { "id": 10, "tasks": ["10.5"] },
    { "id": 11, "tasks": ["11"] }
  ]
}
```
