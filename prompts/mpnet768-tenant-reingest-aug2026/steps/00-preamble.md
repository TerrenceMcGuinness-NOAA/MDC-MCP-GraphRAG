# Preamble — mpnet768-tenant-reingest-aug2026

Read this once before running any step. It is the fixed context for every
step in this spec's implementation harness.

## Repository state

- **Working tree**: `/mcp_rag_eib/eib-mcp-rag-server`
- **Branch**: `develop` (as of 2026-08-28)
- **Recent merges**:
  - `90af7c5` — `update_shared_scoping` into `develop` (Phase 79 + 80).
  - Post-merge fixes on `develop` for the Neptune APOC removal
    (`b7a669e`, `165c95f`) and the graph enrichment `UNION ALL` rewrite
    (`88007af`).
- **Gateway image**: `eib-mcp-rag-python:latest` @ `ba096b369ac7`
  (rebuilt 2026-08-28 20:12 UTC, includes the merge).
- **Rollback image**: `eib-mcp-rag-python:pre-shared-scope` @
  `06df8cd251bf` — pinned by Requirement 8.4; do not prune.

## What this spec adds

Six deltas on top of the existing `cots-reingest-ralph-loop` machinery:

1. **Shared-once discipline** on the Work_Matrix.
2. **Hybrid_Fan_Out** for `workflow_docs` and `code_with_context`.
3. **Neo4j drop-and-rebuild** of indexes and constraints.
4. **Nine missing sources** added to the stage catalog.
5. **Per-tenant Phase-79 Validation_Probe** and **manifest writeback**.
6. **Human-gated cutover script**, out of the loop.

The design and requirements documents are in
`.kiro/specs/mpnet768-tenant-reingest-aug2026/`. Read `requirements.md` and
`design.md` before starting any step. The task list is `tasks.md`; each
step in this harness corresponds to one top-level task.

## What this spec does NOT change

- The State_Manager CLI surface (subcommand names, argument shape).
- The Loop_Driver's non-interactive Kiro CLI invocation.
- Ingester algorithms — no parsing changes, no graph-construction changes.
- The embedding model — `mpnet768` throughout.
- The AWS backend — OpenSearch and Neptune are untouched.

## Standing rules for every step

- **ASCII-only** console and file output. No emoji anywhere (breaks MCP
  stdio protocol on the client side).
- **2-space indent** for Bash; `pycodestyle` for Python; **numpy-style
  docstrings**.
- **Bash variables always quoted** (`"${var}"`).
- **ES Modules** are irrelevant here — this spec is Python and Bash only.
- **No pip install without `--user`** and never outside the Spack module
  system. The mpnet768 wheels are already in the gateway image; nothing
  in this spec adds a new Python dependency.
- **Idempotent State_File `init`**. Every schema addition is
  backwards-compatible and does not discard existing unit status.
- **No mutation of v8 or current mpnet768 collections** until the
  cutover script runs. Enforced by Requirement 1.2's protected-name
  list.
- **Git operation policy 08**. Never `git commit`, `git push`, `git
  merge`, `git rebase`, `git reset --hard`, or `git checkout -B`
  without an explicit user request. Stage changes with `git add
  <paths>` so the operator can review the staged hunks.

## The Iteration_Prompt is not this file

`scripts/ralph_reingest_prompt.md` is the **runtime** prompt fed to each
iteration of the live Ralph loop when the reingest actually runs. This
file is the **spec-implementation** preamble — read once by a
spec-impl agent before authoring a step. Do not conflate them.

## Verification discipline

Every step that changes runtime code (Tasks 1, 2, 3, 4, 6, 7, 8) must:

1. Land the change.
2. Run the relevant unit tests (`npx vitest run` for JS,
   `python3 -m pytest mcp_server_python/tests/unit/<test_file>.py`
   for Python).
3. Show the test output in the step's log.
4. Stage the change with `git add`.

Steps that touch specs only (Tasks 9 and 10) end at the staging step.

## Rollback recipe (image level)

If a step lands and the gateway subsequently fails to serve, the
one-liner rollback is:

```bash
docker tag eib-mcp-rag-python:pre-shared-scope eib-mcp-rag-python:latest
sudo systemctl restart mcp-gateway.service
```

Verify with `mcp_health_check` via the HTTP endpoint.

## Files this spec creates or modifies

| Path | Kind |
|---|---|
| `mcp_server_python/scripts/reingest_state.py` | modified (schema fields + writeback) |
| `mcp_server_python/scripts/reingest_stages.yaml` | modified (nine sources, scope, shared_once, hybrid) |
| `mcp_server_python/scripts/neo4j_index_rebuild.py` | new |
| `mcp_server_python/scripts/reingest_validation.py` | new |
| `scripts/ralph_reingest_prompt.md` | modified (preamble + step 3 + step 5) |
| `scripts/reingest_cutover.sh` | new |
| `mcp_server_python/tests/unit/test_reingest_state_scope_field.py` | new |
| `mcp_server_python/tests/unit/test_reingest_stages_shared_once.py` | new |
| `mcp_server_python/tests/unit/test_reingest_stages_hybrid_fan_out.py` | new |
| `mcp_server_python/tests/unit/test_reingest_stages_dependency_closure.py` | new |
| `mcp_server_python/tests/unit/test_neo4j_index_rebuild.py` | new |
| `mcp_server_python/tests/unit/test_reingest_validation.py` | new |
| `mcp_server_python/tests/unit/test_ralph_prompt_snapshot.py` | new |
| `mcp_server_python/tests/unit/test_manifest_writeback.py` | new |
| `mcp_server_python/tests/integration/test_reingest_dry_run_walk.py` | new |
| `docs/reports/2026-XX-XX-mpnet768-tenant-reingest-verification.md` | new |
| `sdd_framework/workflows/phase81_mpnet768_tenant_reingest.md` | new |
| `CHANGELOG.md` | modified (Phase 81 entry) |

## Stop conditions

- If a step needs runtime access to Neo4j and the live database is
  unavailable, stop and surface the block. Do not mock the connection
  in the runtime code to bypass it.
- If a step's test suite exposes a regression outside its own scope,
  stop and surface the finding. The Phase 80 discipline of
  amending-with-replacement applies.
- If Git operation policy 08 would be violated, stop and ask the
  operator.
