# Progress Log for spec: mpnet768-tenant-reingest-aug2026

# Corrections

- ❌ Asserting `scope == "global"` for global/shared stages → ✅ Assert `scope == "shared"` (Phase 81 replaced the "global" terminology with "shared"; `_stage_unit` now reads `stage.get("scope", "shared" if is_global else "tenant")`)
- ❌ Running v1→v2 migration then immediately checking scope drift → ✅ Skip drift detection after migration (migrated fields default to `False` which may differ from the catalog's declared `True` — that's expected initial state, not drift)
- ❌ Putting `--catalog`/`--dry-run` on the top-level parser with subparsers → ✅ Use `parents=[common]` on each subparser (argparse does not propagate top-level optional args past a required subcommand positional)
- ❌ UNRESOLVED: Task 9.2 cannot be completed — the live Ralph loop is at 18/58 terminal units (schema v1, pre-Phase-81 catalog), no `validation/` dir, no `loop.log`. The loop must reach `is-complete` before the verification record can be filled with live evidence. This is an external operational precondition, not a code defect.

# Codebase Patterns

**Project Structure & Modules**
- Test files for `mcp_server_python/scripts/*.py` live in `mcp_server_python/tests/unit/` with `sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))` to enable direct import.
- Fixtures use `tmp_path` + inline YAML strings written to temp files for catalog/stages.

**Data & State**
- `reingest_state.py` uses atomic writes (temp file in same dir + `os.replace`) for durability.
- State_File schema changes are additive — new fields get defaults, old files get migrated at load time.
- `_build_matrix` emits units by reading scope from the stage catalog; `shared`/`hybrid_external` emit exactly one global unit, `tenant`/`hybrid_local` emit one per catalog tenant.

**Testing**
- Test helper `_init(state_root, catalog, stages, ...)` wraps `rs.main(argv)` with stringified paths for subprocess-style testing.
- `_store(state_root)` creates a fresh `StateStore` to reload and verify state changes after mutations.
- Tests confirm idempotency by mutating state, re-running init, and verifying preservation.

---

## 2026-08-28 - Task 1: State_File schema — additive scope fields
- What was implemented:
  - Extended `reingest_state.py` with SCHEMA_VERSION=2, VALID_SCOPES constant
  - Extended `_stage_unit` to include `shared_once`, `tenancy_precheck`, `validation_path` fields
  - Updated `_build_matrix` to handle `hybrid_external`/`hybrid_local` scope and `shared_once` flag
  - Added `_migrate_state_v1_to_v2` function for backwards-compatible schema upgrade
  - Added `_detect_scope_drift` function to detect when a stage's `shared_once` flips between inits
  - Updated `cmd_init` with migration, drift detection, and `--force-scope-migration` flag
  - Added `--force-scope-migration` to the argparse `init` subparser
  - Updated existing test assertion (`"global"` → `"shared"`)
- Files changed:
  - `mcp_server_python/scripts/reingest_state.py` (modified)
  - `mcp_server_python/tests/unit/test_reingest_state_scope_field.py` (new, 21 tests)
  - `mcp_server_python/tests/unit/test_reingest_state.py` (1 assertion updated)
- Tools used: pytest (standard test runner)
- Patterns discovered: see Codebase Patterns section above
- Corrections added: 2 entries (scope terminology, migration+drift interaction)
---

## 2026-08-28 - Task 2: Stage catalog — nine missing sources + shared-once + hybrid fan-out
- What was implemented:
  - Rewrote `reingest_stages.yaml` (schema_version bumped to 2) with explicit `scope` and `shared_once` fields on all stages
  - Added `neo4j_drop_indexes` (order 5, shared-once, destructive) and `neo4j_rebuild_indexes` (order 400, shared-once, depends_on_all_tenants) stages
  - Added five shared-once vector stages: `workflow_docs_external`, `pdf_sources`, `ee2_standards` (already existed, made explicit), `community_summaries` (already existed, made explicit), `ci_test_cases` (new)
  - Split hybrid domains: `workflow_docs` → `workflow_docs_external` (shared) + `workflow_docs_local` (hybrid_local, per-tenant); `code_with_context` → `code_with_context_local` (tenant, per-tenant, replacing old `code` stage)
  - Added `depends_on_all_tenants: bool` field to `_stage_unit` and the unit dict
  - Extended `StateStore.actionable()` with `_all_tenants_deps_terminal()` for cross-tenant dependency gating
  - Added `depends_on_all_tenants` to `_migrate_state_v1_to_v2` migration
  - Updated `test_production_matrix_is_58_units` → `test_production_matrix_is_67_units` (60 tenant + 7 shared = 67)
  - Updated `validate` stage's `depends_on` to reference new stage names (`code_with_context_local`, `workflow_docs_local`)
- Files changed:
  - `mcp_server_python/scripts/reingest_stages.yaml` (rewritten, schema v2)
  - `mcp_server_python/scripts/reingest_state.py` (modified: `_stage_unit` adds `depends_on_all_tenants`, `actionable()` + `_all_tenants_deps_terminal()`, migration updated)
  - `mcp_server_python/tests/unit/test_reingest_state.py` (updated production matrix test)
  - `mcp_server_python/tests/unit/test_reingest_stages_shared_once.py` (new, 6 tests)
  - `mcp_server_python/tests/unit/test_reingest_stages_hybrid_fan_out.py` (new, 14 tests)
  - `mcp_server_python/tests/unit/test_reingest_stages_dependency_closure.py` (new, 11 tests)
- Tools used: pytest (standard test runner for verification)
- Patterns discovered: `depends_on_all_tenants` cross-tenant gating pattern — a shared-once unit can declare that its depends_on stages must be terminal for ALL tenants by setting this flag; the `_all_tenants_deps_terminal` helper iterates non-global tenant_ids
- Corrections added: none (no errors encountered)
---

## 2026-08-28 - Task 3: Neo4j index drop and rebuild
- What was implemented:
  - Created `neo4j_index_rebuild.py` with four subcommands: `list`, `drop`, `create`, `restore`
  - Index_Rebuild_Set defined with 7 templates (file_path_uniq, function_qname_uniq, function_name_text, fortran_sub_name_text, fortran_fn_name_text, python_fn_name_text, shell_script_path_uniq) parametrised across all tenant prefixes from `tenants.yaml`
  - `drop` requires `--i-mean-it Target_Version=<ver>` confirmation token (Req 8.1), writes pre-drop JSON snapshot atomically
  - `create` generates `IF NOT EXISTS` cypher for all concrete entries (7 templates × 5 prefixes = 35), verifies all are live post-create
  - `restore` reads a snapshot and re-applies the schema (rollback path)
  - All subcommands support `--dry-run` and `--catalog` (path to tenants.yaml)
  - Used `parents=` argparse pattern so `--catalog` and `--dry-run` work on every subcommand
  - Created 26 unit tests covering: prefix loading, index expansion, cypher generation, confirmation token refusal, snapshot write/restore round-trip, label parametrisation, Index_Rebuild_Set structure
- Files changed:
  - `mcp_server_python/scripts/neo4j_index_rebuild.py` (new, ~590 lines)
  - `mcp_server_python/tests/unit/test_neo4j_index_rebuild.py` (new, 26 tests)
- Tools used: pytest (standard test runner for verification)
- Patterns discovered: argparse with subparsers requires `parents=[common]` pattern when global flags must be recognized after the subcommand name (not before)
- Corrections added: 1 (argparse parents pattern — see below, added inline during implementation)
---

## 2026-08-28 - Task 4: Codified Validation_Probe
- What was implemented:
  - Created `reingest_validation.py` — thin CLI that runs 4 MCP tool calls (search_documentation, search_ee2_standards, search_architecture, get_code_context) per Requirement 5.1 via JSON-RPC 2.0 over HTTP against the local COTS gateway
  - Uses `httpx` only (no MCP Python SDK) as specified in design.md Delta 5
  - Bearer token loaded from `MCP_BEARER_TOKEN` env var, `~/.config/eib-mcp/secrets.env`, or falls back to hardcoded default `eib-mcp-gateway-token-2025`
  - Per-tenant mode (`--tenant gw_v17`) runs 4 probes with tenant_id; global mode (`--global`) runs 2 shared-once probes without tenant_id
  - Ground-truth phrases per tenant defined as a constant dict at file top (documented iteration point per design)
  - Atomic file write to `.reingest_state/<target_version>/validation/<tenant>.json` (or `_shared_once.json` for global)
  - Hit-count extraction heuristic handles zero-hit markers (`[INFO] No results`, `[INFO] Skip_Block`, etc.)
  - `--dry-run` flag prints plan without calling the gateway
  - Exit codes: 0=all pass, 1=any probe zero-hits, 2=config error or connection failure
  - Created 33 unit tests covering: hit count extraction (8), bearer token loading (5), tenant probes (5), global probes (2), result writing (5), CLI integration (8)
- Files changed:
  - `mcp_server_python/scripts/reingest_validation.py` (new, ~430 lines)
  - `mcp_server_python/tests/unit/test_reingest_validation.py` (new, 33 tests)
- Tools used: pytest (standard test runner for verification)
- Patterns discovered: none new (followed existing patterns from neo4j_index_rebuild.py for argparse + test structure)
- Corrections added: none (no errors encountered)
---

## 2026-08-28 - Task 5: Iteration_Prompt extension
- What was implemented:
  - Extended `scripts/ralph_reingest_prompt.md` with two new preamble sections:
    - `## Shared_Once_Rule` — explains the rule with 3 concrete bash examples (correct shared-once, WRONG shared-once, correct tenant-scope contrast)
    - `## Hybrid_Fan_Out` — explains the split with a table + 3 concrete bash examples (correct external, correct local, WRONG local-without-prefix)
  - Extended step 3 into two sub-steps:
    - 3a (Tenancy precheck): checks `unit.shared_once`/`unit.scope` and validates `MCP_DEFAULT_TENANT` is unset for shared-once or matches `unit.tenant_id` for tenant-scope; records `tenancy_violation` via SM fail on mismatch
    - 3b (Source precondition): preserved existing logic unchanged
  - Extended step 5 with sub-step 5b (Phase-79 read-path Validation_Probe):
    - Per-tenant: invokes `reingest_validation.py --target-version <ver> --tenant <tenant_id>`
    - Shared-once: invokes `reingest_validation.py --target-version <ver> --global`
    - Non-zero exit recorded as `validation_probe_failed` via SM fail
  - Added `neo4j_drop_indexes` and `neo4j_rebuild_indexes` execution instructions to step 4
  - Added shared-once ingest stage handling to step 4 (no `--tenant` flag)
  - Extended Hard Rules section with Shared_Once_Rule and Hybrid_Fan_Out enforcement
  - Created snapshot test with 31 assertions across 6 test classes verifying preamble content, step 3 tenancy precheck, step 5 validation probe, and structural invariants
- Files changed:
  - `scripts/ralph_reingest_prompt.md` (rewritten with Phase 81 extensions)
  - `mcp_server_python/tests/unit/test_ralph_prompt_snapshot.py` (new, 31 tests)
- Tools used: pytest (standard test runner for verification)
- Patterns discovered: none new
- Corrections added: none (no errors encountered)
---

## 2026-08-28 - Task 6: Manifest writeback
- What was implemented:
  - Added `_DEFAULT_MANIFEST`, `_WRITEBACK_KINDS`, `STAGE_TO_SOURCES`, and `_STAGES_WITH_ARGS_SOURCES` constants to `reingest_state.py`
  - Created `_resolve_stage_sources(unit, stages_data)` function that resolves manifest source names from a unit's stage via two paths: (1) parsing `--sources <csv>` from the stage catalog args for stages in `_STAGES_WITH_ARGS_SOURCES`, (2) static `STAGE_TO_SOURCES` fallback for implicit mappings
  - Created `_writeback_manifest_status(unit, manifest_path, blocked_reason, stages_data)` function that writes an `ingest_status` block to matching manifest sources atomically (temp file + `os.replace`)
  - Refactored `cmd_done` to inline its mutation (no longer uses `_mutate`) and call `_writeback_manifest_status` after state save when `unit.kind in _WRITEBACK_KINDS`
  - Refactored `cmd_fail` to inline its mutation and call `_writeback_manifest_status` with `blocked_reason` when unit transitions to `blocked` state
  - Added `--manifest` argument to both `done` and `fail` subparsers for testable path injection
  - Created 29 unit tests covering: static source resolution (8), catalog-args source resolution (4), done writeback (7), blocked writeback (2), robustness/edge-cases (4), CLI integration (4)
- Files changed:
  - `mcp_server_python/scripts/reingest_state.py` (modified: +165 lines — constants, functions, refactored cmd_done/cmd_fail, argparse additions)
  - `mcp_server_python/tests/unit/test_manifest_writeback.py` (new, 29 tests)
- Tools used: pytest (standard test runner for verification)
- Patterns discovered: none new (followed existing atomic-write + argparse patterns from Tasks 1-5)
- Corrections added: none (no errors encountered)
---

## 2026-08-28 - Task 7: Cutover script
- What was implemented:
  - Created `scripts/reingest_cutover.sh` — the human-gated cutover script per design.md Delta 6 and Requirement 12
  - Precondition checks: state is-complete, validation probe files pass for all 5 tenants + _shared_once, rollback Docker image present, manifest exists
  - Manifest rewrite: maps 5 v8-era `collection_target` values to v9-0-0 names via an associative array + Python JSON rewriter (atomic write via `tempfile + os.replace`)
  - Gateway restart: `sudo systemctl restart mcp-gateway.service` + health poll loop (60s timeout, 5s interval) checking for "HEALTHY" in `mcp_health_check` JSON-RPC response
  - Post-cutover validation: runs `reingest_validation.py` for each tenant + global; rolls back manifest on any failure
  - Rollback: restores manifest from backup file + restarts gateway
  - Cutover report: writes markdown report to `docs/reports/YYYY-MM-DD-mpnet768-tenant-reingest-cutover.md` with collection mapping table, 7-day retention window, and rollback procedure
  - `--dry-run` flag: shows the planned manifest diff (67 sources mapped) without modifying anything; only requires manifest exists (skips state/probe/image preconditions)
  - All embedded Python uses heredoc (`<<'PYEOF'`) with `sys.argv` for path/data passing to avoid bash variable interpolation issues inside Python code
- Files changed:
  - `scripts/reingest_cutover.sh` (new, ~310 lines, executable)
- Tools used: bash -n (syntax validation), live execution tests (--help, --dry-run, no-args error)
- Patterns discovered: heredoc with quoted delimiter (`<<'PYEOF'`) + `sys.argv` is safer than `python3 -c` with embedded `${var}` for multi-line Python in bash scripts (avoids double-interpretation of `${}` and quote escaping)
- Corrections added: none (no errors encountered after the heredoc pattern fix during implementation)
---

## 2026-08-28 - Task 8: End-to-end dry-run of the extended Ralph loop
- What was implemented:
  - **8.1**: Extended `scripts/ralph_reingest_prompt.md` with a `## Dry-Run Mode` section explaining `REINGEST_DRY_RUN=1` threading, updated Step 4 with `DRY_RUN_FLAG` variable pattern (set once, appended to every script invocation), updated Step 5 with dry-run bypass for validation, added "Dry-run threading" to Hard Rules section
  - Extended `scripts/ralph_reingest_loop.sh` with `--dry-run` CLI argument parsing, `REINGEST_DRY_RUN` env var (default "0"), export in `setup_env()`, and `--target-version`/`--spec` argument support
  - **8.2**: Created comprehensive integration test that walks the full 67-unit Work_Matrix programmatically (next→start→done/skip) and asserts: total unit count (67), shared-once stages visited exactly once (7), per-tenant stages visited exactly 5 times (12×5=60), neo4j_drop_indexes before all graph stages, neo4j_rebuild_indexes after all graph stages, validate is last per tenant, scope/shared_once fields correct, tenancy_precheck populated correctly, depends_on_all_tenants gating works, optional skip (community_summaries) doesn't deadlock
- Files changed:
  - `scripts/ralph_reingest_prompt.md` (modified: +35 lines dry-run section, step 4/5/hard-rules updates)
  - `scripts/ralph_reingest_loop.sh` (modified: +16 lines — REINGEST_DRY_RUN var, export, --dry-run/--target-version/--spec arg parsing)
  - `mcp_server_python/tests/integration/test_reingest_dry_run_walk.py` (new, 11 tests / ~280 lines)
- Tools used: pytest (standard test runner), bash -n (shell syntax validation)
- Patterns discovered: none new (reused existing State_Manager walk pattern from unit tests)
- Corrections added: none (no errors encountered)
---

## 2026-08-28 - Task 9: Verification record (9.1 complete, 9.2 blocked on live run)
- What was implemented:
  - Authored the Verification_Record template with 46 acceptance criteria rows (one per R1-12 criterion)
  - 28 criteria marked VERIFIED with citations to specific test classes/methods, code inspection, or design artifacts
  - 18 criteria marked PENDING LIVE RUN with placeholder instructions for what evidence to fill post-run
  - Summary table and Task 9.2 operator instructions included in the file
  - Subtask 9.2 is explicitly blocked: requires the Ralph loop to reach `is-complete` (external precondition not yet met)
- Files changed:
  - `docs/reports/2026-XX-XX-mpnet768-tenant-reingest-verification.md` (new, 156 lines)
  - `.kiro/specs/mpnet768-tenant-reingest-aug2026/tasks.md` (9.1 marked [X])
- Tools used: grep/wc for row count verification
- Patterns discovered: none new
- Corrections added: none (no errors encountered)
---

## 2026-08-28 - Task 10: CHANGELOG and Phase 81 SDD workflow doc
- What was implemented:
  - Prepended `[Unreleased] — Phase 81: mpnet768 full tenant-aware re-ingest (Aug 28, 2026)` entry to `CHANGELOG.md` with sections: Summary, Added (4 new files, 9 sources, shared-once stages, hybrid fan-out, depends_on_all_tenants, manifest writeback, verification record, unit tests, integration test), Changed (4 modified files), Fixed (empty — no bugs fixed), Notes (4 operational notes + spec pointer)
  - Authored `sdd_framework/workflows/phase81_mpnet768_tenant_reingest.md` following the Phase 80 layout: Goal, Motivating Gaps (6 empirically confirmed gaps), Deltas table (6 deltas), New Files table (4), Modified Files table (4), Run-Book (pre-flight, live run, monitor, stop/resume, cutover sections with copy-paste-ready commands), Exit Criteria (7), Canonical Spec pointer, Dependencies (4)
- Files changed:
  - `CHANGELOG.md` (modified: +72 lines at top)
  - `sdd_framework/workflows/phase81_mpnet768_tenant_reingest.md` (new, 135 lines)
- Tools used: none beyond standard file read/write
- Patterns discovered: none new
- Corrections added: none (no errors encountered)
---

## 2026-08-28 - Task 9 (9.2): Fill live-run verification rows — BLOCKED
- What was implemented: Nothing — precondition not met
- Precondition check results:
  - `.reingest_state/v9-0-0/state.json`: exists, schema_version=1 (pre-Phase-81), 58 units (18 terminal: 15 done, 3 skipped; 40 pending)
  - `.reingest_state/v9-0-0/validation/`: directory does not exist
  - `.reingest_state/v9-0-0/loop.log`: does not exist
  - The loop was initialized from the old `cots-reingest-ralph-loop` catalog (v1 schema, 58 units) not the Phase 81 catalog (v2 schema, 67 units with shared-once/hybrid fields)
- Why blocked: Task 9.2 explicitly requires "Fill live-run rows **after the loop reaches `is-complete`**". The loop is at 18/58 terminal — it has not completed. There are no validation probe results, no loop log, and no post-run tool captures to extract evidence from.
- Resolution path: Operator must either (a) re-init state with the Phase 81 catalog (`reingest_state.py init --force-scope-migration`) and run the loop to completion, or (b) complete the existing v1 run first and then re-run with the v2 catalog. Once `is-complete` returns 0 and `validation/*.json` files exist, Task 9.2 can be filled per the operator instructions in the verification record.
- Files changed: none (task is a documentation-fill activity)
- Tools used: bash (file existence checks, state.json parsing)
- Patterns discovered: none
- Corrections added: 1 (UNRESOLVED blocker documenting the external precondition)
---
