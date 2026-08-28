# Implementation Plan: mpnet768-tenant-reingest-aug2026

## Overview

This plan implements the six deltas defined in
[`design.md`](./design.md) on top of the existing `cots-reingest-ralph-loop`
machinery. No task in this plan modifies the State_Manager CLI surface, the
Loop_Driver's Kiro CLI invocation, ingester parsing logic, embedding model, or
the AWS backend. Every task is either a schema-additive edit, a new script, a
new test, or an Iteration_Prompt extension.

The tasks are ordered so each is independently shippable and independently
verifiable. Two sequencing constraints are hard and are called out where they
bind:

1. **Task 3 (`neo4j_index_rebuild.py`) must land before Task 8's live-loop
   dry-run.** The dry-run walks the Work_Matrix which now contains the
   `neo4j_drop_indexes` / `neo4j_rebuild_indexes` stages; missing script =
   Work_Matrix `init` fails.
2. **Task 5 (Iteration_Prompt extension) must land before Task 8's live-loop
   dry-run** for the same reason — the prompt's step 3 tenancy precheck reads
   the new `unit.scope` and `unit.shared_once` fields.

Standing constraints for every task:

- **No AWS/Neptune/OpenSearch touch.** This is COTS-only.
- **No embedding-model change.** `mpnet768` throughout.
- **No mutation of v8 / current mpnet768 collections** until the Requirement
  12 cutover step.
- **ASCII-only** console output; `pycodestyle` for Python; numpy-style
  docstrings; 2-space indent in shell.
- **Idempotent State_Manager `init`.** Every schema addition is
  backwards-compatible; a re-`init` after this spec ships against a
  pre-existing State_File must add the new fields with sensible defaults
  and MUST NOT discard existing unit statuses.
- **Git operation policy 08.** Commits and pushes require an explicit user
  request; the agent stages only.

## Tasks

- [X] 1. State_File schema — additive scope fields
  - Delta 1 (design.md). Independently shippable; adds fields but changes no
    runtime behaviour until Task 2 populates them.

  - [X] 1.1 Extend the State_File unit schema with `scope`, `shared_once`,
        `tenancy_precheck`, and `validation_path`
    - Edit `mcp_server_python/scripts/reingest_state.py`.
    - Add three optional fields to each unit dict:
      - `scope: Literal["shared", "tenant", "hybrid_external", "hybrid_local"]`
        — defaults to `"tenant"` for backwards compatibility with pre-existing
        state files.
      - `shared_once: bool` — defaults to `False`.
      - `tenancy_precheck: dict | None` — defaults to `None`. Structure:
        `{"expected_prefix": str, "expected_tenant": str | None}`.
      - `validation_path: str | None` — defaults to `None`. Populated when the
        unit's `kind == "validate"`.
    - Preserve the existing `init` idempotency: fields are added on missing
      units and on schema-drift-detected re-`init`, existing unit statuses are
      untouched.
    - Add `_migrate_state_v1_to_v2` for pre-existing state files without these
      fields; increment the state file's internal `schema_version` from `1`
      to `2`.

  - [X] 1.2 Add `catalog_scope_drift` detection
    - When `init` runs against a pre-existing State_File and a stage's
      `shared_once` value has changed between the old catalog and the new one,
      write a `catalog_scope_drift` entry to the State_File's `warnings[]` and
      log a WARN.
    - Do not automatically re-emit the affected units; require the operator to
      re-run `init --force-scope-migration` to accept the drift.

  - [X] 1.3 Unit tests
    - New file `mcp_server_python/tests/unit/test_reingest_state_scope_field.py`.
    - Assert defaults apply on a fresh init, are preserved on a re-init, and
      that `catalog_scope_drift` fires on a scope flip.

- [X] 2. Stage catalog — nine missing sources + shared-once + hybrid fan-out
  - Deltas 1, 2, and 4. Depends on Task 1 for the `scope` and `shared_once`
    fields to be understood by the Work_Matrix builder.

  - [X] 2.1 Add `shared_once: bool` and `scope` fields to
        `reingest_stages.yaml`
    - Edit `mcp_server_python/scripts/reingest_stages.yaml`.
    - Add the fields to every existing stage; existing tenant-scope stages
      get `scope: tenant`, `shared_once: false`.
    - `ee2_standards` and `community_summaries` get
      `scope: shared`, `shared_once: true` (correcting the predecessor's
      ad-hoc "global" handling).

  - [X] 2.2 Add `neo4j_drop_indexes` and `neo4j_rebuild_indexes` stages
    - Both `scope: shared`, `shared_once: true`, `kind: prep`.
    - `neo4j_drop_indexes` depends on `worktree` only.
    - `neo4j_rebuild_indexes` depends on the per-tenant graph stages via a
      new `depends_on_all_tenants: true` field (see Task 2.5).

  - [X] 2.3 Add the five shared-once vector stages
    - `ci_test_cases`, `workflow_docs_external`, `pdf_sources` per the
      table in design.md Delta 1.
    - All `scope: shared`, `shared_once: true`, `depends_on:
      [neo4j_drop_indexes]`.

  - [X] 2.4 Split the two hybrid domains into external and local sub-stages
    - Add `workflow_docs_external` (already covered in Task 2.3) and
      `workflow_docs_local` (per-tenant).
    - Add `code_with_context_local` (per-tenant); reserve
      `code_with_context_external` as a documented empty stage for future
      URL-crawled API references (do not emit a Work_Matrix unit today).

  - [X] 2.5 Add `depends_on_all_tenants` support to the Work_Matrix builder
    - Edit `reingest_state.py::_build_work_matrix`.
    - When a stage carries `depends_on_all_tenants: true`, the `next`
      dependency resolver requires the listed stages to be terminal for
      **every** tenant in the catalog before the shared-once stage becomes
      actionable.
    - Backwards compatible: absent field defaults to `false`.

  - [X] 2.6 Unit tests for the extended catalog
    - New file
      `mcp_server_python/tests/unit/test_reingest_stages_shared_once.py`
      — every `shared_once: true` stage produces exactly one Work_Matrix
      unit regardless of tenant count.
    - New file
      `mcp_server_python/tests/unit/test_reingest_stages_hybrid_fan_out.py`
      — the two hybrid domains split into external (shared) + local (per-
      tenant × N) with the right scope on each sub-stage.
    - New file
      `mcp_server_python/tests/unit/test_reingest_stages_dependency_closure.py`
      — `neo4j_rebuild_indexes` transitively depends on every tenant's
      `fortran_graph`, `python_graph`, `shell_graph`, `bridge`, `rocoto`,
      `expdir` stages.

- [X] 3. Neo4j index drop and rebuild
  - Delta 3. Independent of Tasks 1 and 2; independently shippable.

  - [X] 3.1 Create `mcp_server_python/scripts/neo4j_index_rebuild.py`
    - Subcommands `list`, `drop`, `create`, `restore`.
    - Reads Neo4j connection from the same environment as `run_mcp_stdio.sh`
      (`NEO4J_URI`, `NEO4J_PASSWORD`).
    - Enumerates the Index_Rebuild_Set from design.md Delta 3.
    - `drop` requires the confirmation token `--i-mean-it
      Target_Version=v9-0-0` and writes a JSON snapshot of the pre-drop
      schema to the path given by `--snapshot`.
    - `create` accepts `--target-version` and parametrises label
      constraints by every tenant's `label_prefix` read from
      `tenants.yaml`.
    - `restore` reads a snapshot and re-applies the pre-drop schema
      verbatim.
    - CLI exits non-zero and prints a diff if the current index set does
      not match the target after `create`.

  - [X] 3.2 Unit tests
    - New file
      `mcp_server_python/tests/unit/test_neo4j_index_rebuild.py`.
    - Assert `list` returns the Index_Rebuild_Set (mocked Neo4j driver).
    - Assert `drop` refuses without the confirmation token.
    - Assert `drop` writes a snapshot that `restore` accepts round-trip.
    - Assert `create` parametrises labels by every tenant's
      `label_prefix`.

- [X] 4. Codified Validation_Probe
  - Delta 5. Independent of Tasks 1-3.

  - [X] 4.1 Create `mcp_server_python/scripts/reingest_validation.py`
    - Thin CLI that runs the four MCP tool calls from Requirement 5.1
      against `http://localhost:18888/mcp` with the bearer token from
      `~/.config/eib-mcp/secrets.env`.
    - Uses `httpx` (already in the container) — does not import the
      MCP Python SDK.
    - Writes the full request/response payload to
      `.reingest_state/<target_version>/validation/<tenant>.json`.
    - Exits non-zero if any of the four probes returns zero hits or an
      error.
    - Ground-truth phrases per tenant are read from a small JSON
      constant at the top of the file (initial values in design.md
      Delta 5); the constant is a documented iteration point, not a
      config file.

  - [X] 4.2 Global (shared-once) probe variant
    - Same CLI, invoked with `--global` — runs the two shared-once
      probes (`search_ee2_standards`, `search_architecture`) with
      `MCP_DEFAULT_TENANT` unset and writes to
      `.reingest_state/<target_version>/validation/_shared_once.json`.

  - [X] 4.3 Unit tests
    - New file
      `mcp_server_python/tests/unit/test_reingest_validation.py`.
    - Mock the HTTP transport; assert the four MCP calls are made with
      the right `tenant_id`, that a zero-hit response fails the run,
      that the payload file is written atomically.

- [X] 5. Iteration_Prompt extension
  - Deltas 1 and 5. Depends on Tasks 1 and 4.

  - [X] 5.1 Extend `scripts/ralph_reingest_prompt.md`
    - Add a preamble section covering Shared_Once_Rule and
      Hybrid_Fan_Out with three concrete examples per rule.
    - Extend step 3 with the tenancy precheck: refuse to run a
      shared-once unit if `MCP_DEFAULT_TENANT` is set; refuse to run
      a tenant unit if `MCP_DEFAULT_TENANT` does not match the unit's
      `tenant_id`.
    - Extend step 5 with the Validation_Probe call:
      `python3 mcp_server_python/scripts/reingest_validation.py
      --target-version <ver> --tenant <unit.tenant_id>` for tenant
      units; `--global` for shared-once units.
    - The step structure and terminal-state contract are unchanged.

  - [X] 5.2 Iteration_Prompt snapshot test
    - New file
      `mcp_server_python/tests/unit/test_ralph_prompt_snapshot.py`.
    - Assert the preamble contains the Shared_Once_Rule and
      Hybrid_Fan_Out headings, that step 3 contains the tenancy
      precheck text verbatim, and that step 5 invokes
      `reingest_validation.py`.

- [X] 6. Manifest writeback
  - Delta 5. Depends on Task 1 for the `validation_path` field.

  - [X] 6.1 Add `_writeback_manifest_status` to `reingest_state.py`
    - Invoked from every `done` transition where the unit's kind is
      `vector`, `graph`, or `dual`.
    - Appends an `ingest_status` block to the corresponding source in
      `mcp_server_python/src/config/unified_manifest.json` with
      `collection_version`, `actual_docs`, `ingested_at`, `sha`,
      `backend`, `embedding_profile`.
    - Writes atomically (temp file + `os.replace`).
    - Records `blocked` reason via `ingest_status.blocked_reason` when
      the unit reaches `blocked`.

  - [X] 6.2 Unit tests
    - New file
      `mcp_server_python/tests/unit/test_manifest_writeback.py`.
    - Assert a `done` transition writes the correct block; a `blocked`
      transition writes `blocked_reason`; concurrent writebacks do
      not corrupt the JSON.

- [X] 7. Cutover script
  - Delta 6. Independent of Tasks 1-6; can be authored last, will not run
    until after the loop completes.

  - [X] 7.1 Create `scripts/reingest_cutover.sh`
    - Preconditions: `is-complete` returns 0 and every tenant's
      `validation/<tenant>.json` records a passing probe suite.
    - Backup `unified_manifest.json` to
      `docs/reports/YYYY-MM-DD-mpnet768-tenant-reingest-cutover.manifest.bak`.
    - Rewrite every `collection:` field to the v9-0-0 name per the naming
      table in design.md Delta 2.
    - Restart `mcp-gateway.service` via `sudo systemctl restart`.
    - Poll `mcp_health_check` via HTTP; abort if not 4/4 within 60 s.
    - Re-run the Requirement 5.1 probe suite; abort (restore backup) if
      any tenant regresses.
    - Write the cutover report to
      `docs/reports/YYYY-MM-DD-mpnet768-tenant-reingest-cutover.md`.

  - [X] 7.2 Cutover dry-run flag
    - `--dry-run` prints the planned manifest diff without touching the
      manifest or the service; used for review before the real cutover.

- [X] 8. End-to-end dry-run of the extended Ralph loop
  - Depends on Tasks 1-5 (Task 6 optional for dry-run; Task 7 not exercised).

  - [X] 8.1 Add `--dry-run` support to the extended stages
    - Every new ingester invocation and both `neo4j_index_rebuild.py`
      subcommands accept `--dry-run`; the Iteration_Prompt threads the
      flag through when `REINGEST_DRY_RUN=1`.

  - [X] 8.2 Integration test
    - New file
      `mcp_server_python/tests/integration/test_reingest_dry_run_walk.py`
      (marked `@pytest.mark.integration`).
    - Init the Work_Matrix against the current `tenants.yaml`.
    - Walk `next → start → done` in `--dry-run` mode until
      `is-complete`.
    - Assert every stage was visited exactly the expected number of
      times (shared-once = 1, tenant = 5, hybrid = 1 external + 5
      local).
    - Assert `neo4j_drop_indexes` visited before any tenant graph
      stage; `neo4j_rebuild_indexes` visited after every tenant graph
      stage.
    - Assert `.reingest_state/v9-0-0/validation/*.json` written for
      every tenant + one `_shared_once.json`.

- [F] 9. Verification record
  - Runs after the live loop completes on the COTS host.

  - [X] 9.1 Author the Verification_Record template
    - New file
      `docs/reports/2026-XX-XX-mpnet768-tenant-reingest-verification.md`.
    - One row per Requirement 1-12 acceptance criterion citing the
      test, log line, or tool-call output that proves it.
    - Empty rows for criteria that need live-run evidence
      (`ingest_count_v9`, `probe_pass_per_tenant`, `manifest_gap_closed`).

  - [F] 9.2 Fill live-run rows after the loop reaches `is-complete`
    - Copy the relevant lines from
      `.reingest_state/v9-0-0/loop.log`, the `validation/*.json`
      payloads, and a post-run `list_all_sources(include_gaps=True)`
      capture.

- [X] 10. CHANGELOG and Phase 81 SDD workflow doc
  - Bookkeeping. No behavioural change.

  - [X] 10.1 Prepend an `[Unreleased] — Phase 81` entry to
        `CHANGELOG.md`
    - Sections: Added, Changed, Fixed, Notes.
    - Cite the four new files, the extended stage catalog, the
      Iteration_Prompt extension, the cutover script, and the
      Verification_Record.

  - [X] 10.2 Author `sdd_framework/workflows/phase81_mpnet768_tenant_reingest.md`
    - Copy the Phase 80 layout (goal, motivating gaps, deltas,
      run-book, exit criteria).
    - Point to `.kiro/specs/mpnet768-tenant-reingest-aug2026/` as the
      canonical spec; keep the workflow doc as a run-book pointer,
      not a restatement of requirements.

## Live-run execution (not a task in this plan)

Once Tasks 1-10 have landed, the operator runs:

```bash
cd /mcp_rag_eib/eib-mcp-rag-server
mkdir -p logs .reingest_state/v9-0-0
CONFIRM_DESTRUCTIVE=yes nohup bash scripts/ralph_reingest_loop.sh \
  --target-version v9-0-0 \
  --spec mpnet768-tenant-reingest-aug2026 \
  > logs/reingest_$(date +%Y%m%dT%H%M%S).log 2>&1 &
```

Monitor with:

```bash
tail -f logs/reingest_*.log
tail -f .reingest_state/v9-0-0/loop.log
python3 mcp_server_python/scripts/reingest_state.py report
```

Stop with:

```bash
touch .reingest_state/STOP
```

Resume by re-launching the same nohup command — durable state does the rest.
