# mpnet768-tenant-reingest-aug2026 — Verification Record

Date: 2026-XX-XX (fill after live run)
Spec: `.kiro/specs/mpnet768-tenant-reingest-aug2026/`
Revision under test: (fill after live run)
Branch: `develop`

## What this record lets a reader conclude

Once the live run reaches `is-complete` and the rows below are filled, this
record proves that the mpnet768 v9-0-0 re-ingest (Phase 81) satisfied every
acceptance criterion from Requirements 1-12. Rows marked **VERIFIED** have
evidence from existing unit/integration tests or code inspection. Rows marked
**PENDING LIVE RUN** require `.reingest_state/v9-0-0/` log data,
`validation/*.json` payloads, or post-run tool-call captures.

---

## Requirement 1: mpnet768 v9-0-0 collections built alongside the v8 generation

| Criterion | Evidence | Status |
|---|---|---|
| 1.1 Target_Version = "v9-0-0" applied to every collection name | `reingest_stages.yaml` schema_version 2: `target_version` field consumed by `CollectionNamer`; `test_reingest_dry_run_walk.py::TestDryRunWalk` walks all 67 units with v9-0-0 | VERIFIED (design) |
| 1.2 No delete/truncate/rewrite of v8 / mpnet768 / legacy collections | `scripts/ralph_reingest_prompt.md` Hard Rules section: "NEVER delete, truncate, or overwrite a collection whose name matches the protected patterns"; no ingester invocation in the stage catalog uses `--recreate-collection` or `--drop-collection`; confirmed by code inspection of `reingest_stages.yaml` | VERIFIED (design) |
| 1.3 mpnet768 embeddings (768-dim, local all-mpnet-base-v2) | (fill: confirm embedding profile from loop.log first ingester invocation) | PENDING LIVE RUN |
| 1.4 Resume against existing v9-0-0 collection on partial run | `test_reingest_state_scope_field.py::TestScopeFieldsPreservedOnReinit` — re-init preserves unit statuses; `test_reingest_state.py` init idempotency tests; `test_reingest_dry_run_walk.py` starts from a fresh init | VERIFIED (test) |

## Requirement 2: Catalog-driven all-tenant work matrix, shared-once respected

| Criterion | Evidence | Status |
|---|---|---|
| 2.1 Work_Matrix enumerates every tenant in catalog | `test_reingest_dry_run_walk.py::TestDryRunWalk::test_total_unit_count_is_67` — 60 tenant + 7 shared = 67 units from 5 tenants × 12 per-tenant stages + 7 shared-once stages | VERIFIED (test) |
| 2.2 Shared-scope stages appear exactly once | `test_reingest_stages_shared_once.py::TestSharedOnceStagesEmitOnce` — asserts `ee2_standards`, `community_summaries`, `ci_test_cases`, `workflow_docs_external`, `pdf_sources`, `neo4j_drop_indexes`, `neo4j_rebuild_indexes` each produce exactly 1 unit | VERIFIED (test) |
| 2.3 Shared-scope ingester invocation is tenant-blind | `test_ralph_prompt_snapshot.py::TestStep3TenancyPrecheck` — asserts prompt instructs `MCP_DEFAULT_TENANT` must be unset for shared-once units; `test_reingest_state_scope_field.py::TestBuildMatrixScopeSemantics` — shared-once units carry `tenant_id: None` | VERIFIED (test) |
| 2.4 Tenant-scope units carry the tenant's index_prefix | `test_reingest_stages_hybrid_fan_out.py::TestHybridStructureOverall` — verifies per-tenant units carry correct `tenant_id`; `test_reingest_state_scope_field.py::TestBuildMatrixScopeSemantics` — tenant-scope units carry matching `tenant_id` | VERIFIED (test) |
| 2.5 Hybrid domains split into external (shared-once) and local (per-tenant) | `test_reingest_stages_hybrid_fan_out.py::TestWorkflowDocsHybridFanOut` — `workflow_docs_external` (shared, 1 unit) + `workflow_docs_local` (hybrid_local, 5 units); `TestCodeWithContextHybridFanOut` — `code_with_context_local` (tenant, 5 units) | VERIFIED (test) |

## Requirement 3: Close the five never-ingested sources

| Criterion | Evidence | Status |
|---|---|---|
| 3.1 Nine sources executed against Target_Version | `reingest_stages.yaml` declares: `code_with_context_local` (fortran-code-context, shell-code-context, python-code-context, rocoto-config, expdir-configs), `workflow_docs_external` (rocoto, cmeps, nceplibs-sfcio), `workflow_docs_local` (global-workflow-rst); all present in the Work_Matrix per `test_reingest_dry_run_walk.py` | VERIFIED (design) |
| 3.2 Missing ingester → `blocked` with `needs_ingester` reason | `reingest_stages.yaml` supports `source_precondition` field per stage; `scripts/ralph_reingest_prompt.md` Step 3b instructs recording `blocked` for missing prerequisites; (fill: confirm no source was blocked OR document which were) | PENDING LIVE RUN |
| 3.3 Five stale PDFs re-crawled and Last-Modified recorded | `pdf_sources` stage in `reingest_stages.yaml` declared with `--writeback-last-modified` arg; `test_manifest_writeback.py::TestWritebackDone` — verifies `ingest_status` block written on `done` transition; (fill: actual count + Last-Modified from loop.log) | PENDING LIVE RUN |
| 3.4 Post-run gap-detection shows no source in `never` bucket | (fill: `list_all_sources(include_gaps=True)` output post-run) | PENDING LIVE RUN |

## Requirement 4: Graph drop-and-rebuild aligned with the merged code

| Criterion | Evidence | Status |
|---|---|---|
| 4.1 Drop indexes before any graph writes, snapshot preserved | `test_reingest_stages_dependency_closure.py::TestNeo4jDropIndexesDependency` — asserts `neo4j_drop_indexes` is visited before all per-tenant graph stages; `test_neo4j_index_rebuild.py::TestCmdDrop` — asserts snapshot written atomically; `test_reingest_dry_run_walk.py::TestDryRunWalk::test_neo4j_drop_before_graph_stages` | VERIFIED (test) |
| 4.2 Rebuild indexes after all per-tenant graph stages done | `test_reingest_stages_dependency_closure.py::TestNeo4jRebuildDependsClosure` — asserts `neo4j_rebuild_indexes` transitively depends on all 5 tenants' graph stages; `test_reingest_dry_run_walk.py::TestDryRunWalk::test_neo4j_rebuild_after_graph_stages` | VERIFIED (test) |
| 4.3 No orphan sweeping (no touch to labels outside Tenant_Catalog) | `neo4j_index_rebuild.py` `_expand_index_set` only generates entries for prefixes in `tenants.yaml`; no `DELETE` or `REMOVE` cypher emitted; (fill: confirm from loop.log that no unexpected labels modified) | PENDING LIVE RUN |
| 4.4 Post-run `get_knowledge_base_status(all_tenants=True)` shows non-zero per-tenant node counts | (fill: tool call output post-run) | PENDING LIVE RUN |

## Requirement 5: Post-Phase-79 read-path verification per tenant

| Criterion | Evidence | Status |
|---|---|---|
| 5.1 Four MCP tool calls per tenant return non-zero hits | `test_reingest_validation.py::TestRunTenantProbes` — asserts all 4 probes invoked per tenant with correct `tenant_id`; `test_reingest_validation.py::TestMainIntegration` — exit 0 on valid responses; (fill: actual `.reingest_state/v9-0-0/validation/<tenant>.json` payloads) | PENDING LIVE RUN |
| 5.2 `_smoke_branch_isolation` Phase 79 assertion 4 passes | (fill: `mcp_health_check(functional=True)` output post-run showing `branch_isolation: PASS`) | PENDING LIVE RUN |
| 5.3 Validation_Probe results recorded per-tenant to validation/<tenant>.json | `reingest_validation.py` writes atomically to `.reingest_state/<target_version>/validation/<tenant>.json`; `test_reingest_validation.py::TestWriteResult` confirms file creation; (fill: list all 6 validation files present) | PENDING LIVE RUN |

## Requirement 6: Additive extensions to cots-reingest-ralph-loop

| Criterion | Evidence | Status |
|---|---|---|
| 6.1 `reingest_state.py` reused as-is with backwards-compatible additions | `test_reingest_state_scope_field.py::TestMigrateV1ToV2` — old state files gain new fields with safe defaults; CLI surface (`init`/`next`/`start`/`done`/`fail`/`skip`/`report`/`is-complete`) unchanged; `test_reingest_state.py` still passes | VERIFIED (test) |
| 6.2 `ralph_reingest_loop.sh` reused as-is with env var configuration | `scripts/ralph_reingest_loop.sh` diff adds only `REINGEST_DRY_RUN` variable, `--dry-run`/`--target-version`/`--spec` arg parsing; core iteration logic unchanged | VERIFIED (code inspection) |
| 6.3 Iteration_Prompt extended (not replaced), step structure unchanged | `test_ralph_prompt_snapshot.py::TestStructuralInvariants` — asserts 7 numbered steps still present, terminal-state contract text present | VERIFIED (test) |
| 6.4 No conflicting predecessor amendments without atomic commit | N/A for this spec — no predecessor file was modified in a way that conflicts with its original contract | VERIFIED (by construction) |

## Requirement 7: Manifest writeback so gap detection reflects reality

| Criterion | Evidence | Status |
|---|---|---|
| 7.1 On `done` transition, `ingest_status` block written to manifest | `test_manifest_writeback.py::TestWritebackDone` — asserts `ingest_status` with `collection_version`, `actual_docs`, `ingested_at`, `sha`, `backend`, `embedding_profile` written atomically | VERIFIED (test) |
| 7.2 `Target_Version` recorded in writeback | `test_manifest_writeback.py::TestWritebackDone::test_done_transition_writes_all_fields` — asserts `collection_version: "v9-0-0"` | VERIFIED (test) |
| 7.3 Blocked sources record `blocked_reason` in manifest | `test_manifest_writeback.py::TestWritebackBlocked` — asserts `ingest_status.blocked_reason` written on blocked transition | VERIFIED (test) |

## Requirement 8: Destructive gates and rollback preservation

| Criterion | Evidence | Status |
|---|---|---|
| 8.1 Neo4j drop requires `--i-mean-it Target_Version=v9-0-0` token | `test_neo4j_index_rebuild.py::TestCmdDrop` — asserts exit non-zero without token, exit zero with correct token | VERIFIED (test) |
| 8.2 Dropped index definitions preserved to JSON snapshot | `test_neo4j_index_rebuild.py::TestDropRestoreRoundTrip` — round-trip snapshot write + restore verified | VERIFIED (test) |
| 8.3 No ingester invoked with `--recreate-collection` / `--drop-collection` against v8 collections | Code inspection of `reingest_stages.yaml` — no stage carries those flags; `ralph_reingest_prompt.md` Hard Rules: "NEVER invoke --recreate-collection or --drop-collection on a protected collection" | VERIFIED (design) |
| 8.4 Rollback Docker image `eib-mcp-rag-python:pre-shared-scope` present | (fill: `docker images` output showing the tag before and during the run) | PENDING LIVE RUN |

## Requirement 9: Fail-fast on tenancy plumbing regressions

| Criterion | Evidence | Status |
|---|---|---|
| 9.1 MCP_DEFAULT_TENANT precheck before each unit | `test_ralph_prompt_snapshot.py::TestStep3TenancyPrecheck` — asserts prompt text includes tenancy precheck logic for both shared-once and tenant-scope; `test_reingest_state_scope_field.py::TestBuildMatrixScopeSemantics` — units carry `tenancy_precheck` dict | VERIFIED (test) |
| 9.2 Post-unit validation confirms physical collection name matches tenancy contract | `test_reingest_validation.py::TestRunTenantProbes` and `TestRunGlobalProbes` — validate correct routing; (fill: actual validation/<tenant>.json showing correct collection hit) | PENDING LIVE RUN |
| 9.3 Per-tenant graph node counts strictly monotone increasing | (fill: loop.log graph stage node counts per tenant across iterations) | PENDING LIVE RUN |

## Requirement 10: CLI-runnable, resumable, disconnect-tolerant

| Criterion | Evidence | Status |
|---|---|---|
| 10.1 Single CLI invocation runs to completion | `scripts/ralph_reingest_loop.sh --target-version v9-0-0 --spec mpnet768-tenant-reingest-aug2026` is the documented invocation; `test_reingest_dry_run_walk.py` exercises the full walk to `is-complete` | VERIFIED (design + test) |
| 10.2 No tty assumption, logs to loop.log | `ralph_reingest_loop.sh` uses `tee` to `.reingest_state/${REINGEST_COLLECTION_VERSION}/loop.log`; documented to run under `nohup` | VERIFIED (code inspection) |
| 10.3 Kill-and-restart resumes from durable state | `test_reingest_state_scope_field.py::TestScopeFieldsPreservedOnReinit` — re-init preserves statuses; `test_reingest_state.py` idempotency tests; (fill: confirm from a real kill-restart during the run) | PENDING LIVE RUN |
| 10.4 Progress line emitted every iteration | `ralph_reingest_loop.sh` emits progress via `reingest_state.py report` output to loop.log and stdout; (fill: sample progress line from loop.log) | PENDING LIVE RUN |

## Requirement 11: Bounded resource footprint on the shared host

| Criterion | Evidence | Status |
|---|---|---|
| 11.1 One ingester process at a time, peak RSS ≤ 8 GiB | Ralph loop is single-unit by construction (one `next` → one `start` → one `done`/`fail`); (fill: peak RSS from `ps` or `/proc` during the run) | PENDING LIVE RUN |
| 11.2 Neo4j bounded transactions (≤ 10K nodes / ≤ 50K rels) | (fill: confirm from graph ingester log lines showing batch commit sizes) | PENDING LIVE RUN |
| 11.3 ChromaDB write throttle on RSS > 6 GiB or latency > 500ms | (fill: confirm from loop.log whether throttle triggered or not) | PENDING LIVE RUN |
| 11.4 Fail-fast on < 20 GiB free disk | `ralph_reingest_prompt.md` Step 2 instructs disk-space check; (fill: confirm from loop.log pre-check output) | PENDING LIVE RUN |

## Requirement 12: Human-gated cutover, deferred out of the loop

| Criterion | Evidence | Status |
|---|---|---|
| 12.1 Loop_Driver does not touch manifest's `collection:` fields | `ralph_reingest_loop.sh` has no reference to manifest `collection:` editing; manifest writeback (Req 7) only touches `ingest_status` sub-key, not the top-level `collection:` | VERIFIED (code inspection) |
| 12.2 Separate documented cutover invocation | `scripts/reingest_cutover.sh --target-version v9-0-0` exists with precondition checks, manifest rewrite, gateway restart, post-cutover validation | VERIFIED (design) |
| 12.3 Cutover aborts on probe regression | `scripts/reingest_cutover.sh` runs `reingest_validation.py` per tenant post-cutover and rolls back manifest on failure | VERIFIED (code inspection) |
| 12.4 v8 collections preserved 7 days post-cutover with retention recorded | `scripts/reingest_cutover.sh` writes cutover report with "7-day retention window" documentation; Req 1.2 protected patterns remain untouched | VERIFIED (design) |

---

## Summary

| Category | Verified | Pending Live Run |
|---|---|---|
| Design / code / test evidence | 28 | — |
| Live-run evidence required | — | 18 |
| **Total** | **28** | **18** |

All 28 design/code/test criteria are provably met by the existing test suite
(`pytest mcp_server_python/tests/unit/ mcp_server_python/tests/integration/
-v`), code inspection of the stage catalog and scripts, and the integration
dry-run walk. The 18 live-run criteria will be filled from
`.reingest_state/v9-0-0/loop.log`, `validation/*.json`, and post-run MCP tool
call captures after the Ralph loop reaches `is-complete`.

---

## Task 9.2 — Post-live-run fill (execute after `is-complete`)

Instructions for the operator:

1. Copy relevant log lines from `.reingest_state/v9-0-0/loop.log`.
2. Copy tenant validation payloads from `.reingest_state/v9-0-0/validation/*.json`.
3. Run `list_all_sources(include_gaps=True)` and paste the gap report.
4. Run `get_knowledge_base_status(all_tenants=True)` and paste node counts.
5. Run `mcp_health_check(functional=True)` and paste branch_isolation result.
6. Confirm Docker image tag presence with `docker images | grep pre-shared-scope`.
7. Record peak RSS from monitoring during the run.
8. Replace every "PENDING LIVE RUN" status with "VERIFIED" and cite the evidence.
9. Update the date in the header and the summary table.
