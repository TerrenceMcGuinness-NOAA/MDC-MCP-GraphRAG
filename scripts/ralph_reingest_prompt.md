# Ralph Re-Ingest Iteration Prompt (ONE unit per iteration)

You are **one iteration** of the COTS full re-ingest Ralph loop. The COTS
environment (`DB_BACKEND=cots`, `MCP_EMBEDDING_PROFILE=mpnet768`, Neo4j at
`bolt://localhost:7687`, ChromaDB at `localhost:8080`, `MCP_WORKFLOW_MOUNT`
pointing at the `.pw_workflow_mount` symlink farm) is already active in your
shell environment — it was exported by the Loop_Driver before it launched you.
`REINGEST_COLLECTION_VERSION` names the target Collection_Version.

**Do exactly ONE unit of work, then STOP.** Do not pick up a second unit. The
outer loop will re-invoke you for the next one. Keeping each iteration to a
single unit is what makes the run resumable and disconnect-safe.

All state mutations go through the State_Manager. **Never hand-edit
`state.json`.** Run everything with `python3` (this host has no `python3.12`).

`SM` below is shorthand for:

```
python3 mcp_server_python/scripts/reingest_state.py \
  --collection-version "${REINGEST_COLLECTION_VERSION}"
```

## Shared_Once_Rule

Shared-scope collections (EE2 standards, community summaries, CI test cases,
external documentation crawls) are written **once** to an unprefixed physical
collection name. They are never written per-tenant. The read path (Phase 79)
reaches them from every tenant via the `Read_Router`.

A unit with `unit.shared_once == true` or `unit.scope` in
`["shared", "hybrid_external"]`:
- MUST run with `MCP_DEFAULT_TENANT` **unset** (empty string or absent from
  the environment). If the variable is set to any tenant, the write would
  land in the wrong (prefixed) collection.
- Produces a physical collection whose name has **no** tenant prefix —
  e.g. `ee2-standards-mpnet768-v9-0-0`, not `gw_ee2-standards-mpnet768-v9-0-0`.
- Appears exactly **once** in the Work_Matrix (regardless of how many tenants
  exist in the catalog).

**Example — correct shared-once invocation:**

```bash
# EE2 standards (shared-once, unprefixed)
unset MCP_DEFAULT_TENANT
python3 mcp_server_python/scripts/ingest_ee2_standards_v9.py \
  --collection-version "${REINGEST_COLLECTION_VERSION}" --delay 0.2
# Result: writes to ee2-standards-mpnet768-v9-0-0 (no prefix)
```

**Example — WRONG (would violate Shared_Once_Rule):**

```bash
# WRONG: setting MCP_DEFAULT_TENANT on a shared-once unit
MCP_DEFAULT_TENANT=gw_v17 python3 mcp_server_python/scripts/ingest_ee2_standards_v9.py \
  --collection-version "${REINGEST_COLLECTION_VERSION}" --delay 0.2
# Result: writes to gw_v17_ee2-standards-mpnet768-v9-0-0 (WRONG — tenant prefix on shared data)
```

**Example — correct tenant-scope invocation (contrast):**

```bash
# Code ingest (tenant-scope, prefixed)
MCP_DEFAULT_TENANT=gw_v17 python3 mcp_server_python/scripts/ingest_code_v9.py \
  --tenant gw_v17 --collection-version "${REINGEST_COLLECTION_VERSION}" --delay 0.2
# Result: writes to gw_v17_code-with-context-mpnet768-v9-0-0 (correct prefix)
```

## Hybrid_Fan_Out

Two domains — `workflow_docs` and `code_with_context` — are **hybrid**: they
contain both external/URL-crawled content (shared, written once unprefixed) and
repo-local content (tenant-specific, written per-tenant prefixed). The stage
catalog splits each hybrid domain into sub-stages:

| Domain | Sub-stage | Scope | Collection target |
|--------|-----------|-------|-------------------|
| `workflow_docs` | `workflow_docs_external` | shared (once) | `workflow-docs-external-mpnet768-v9-0-0` |
| `workflow_docs` | `workflow_docs_local` | per-tenant | `<prefix>workflow-docs-local-mpnet768-v9-0-0` |
| `code_with_context` | `code_with_context_local` | per-tenant | `<prefix>code-with-context-mpnet768-v9-0-0` |

The read path (Phase 79) fans out a hybrid query across both the external
(unprefixed) and local (prefixed) collections and merges results. A tenant
query for workflow docs reaches both shared external docs AND that tenant's
repo-local RST files.

**Example — correct hybrid external (shared-once):**

```bash
# External docs (shared-once portion of workflow_docs)
unset MCP_DEFAULT_TENANT
python3 mcp_server_python/scripts/ingest_documentation_v9.py \
  --sources "rocoto,cmeps,nceplibs-sfcio" \
  --collection-version "${REINGEST_COLLECTION_VERSION}" --delay 0.2
# Result: writes to workflow-docs-external-mpnet768-v9-0-0 (unprefixed)
```

**Example — correct hybrid local (per-tenant):**

```bash
# Repo-local RST docs (per-tenant portion of workflow_docs)
MCP_DEFAULT_TENANT=gw_v17 python3 mcp_server_python/scripts/ingest_documentation_v9.py \
  --tenant gw_v17 --sources "global-workflow-rst" \
  --collection-version "${REINGEST_COLLECTION_VERSION}" --delay 0.2
# Result: writes to gw_v17_workflow-docs-local-mpnet768-v9-0-0 (tenant-prefixed)
```

**Example — WRONG (writing local content to the shared collection):**

```bash
# WRONG: repo-local RST without tenant prefix
unset MCP_DEFAULT_TENANT
python3 mcp_server_python/scripts/ingest_documentation_v9.py \
  --sources "global-workflow-rst" \
  --collection-version "${REINGEST_COLLECTION_VERSION}" --delay 0.2
# Result: all tenants' RST would overwrite each other in the same unprefixed collection
```

## Dry-Run Mode

When `REINGEST_DRY_RUN=1` is set in the environment, every script invocation
in step 4 MUST include the `--dry-run` flag. In dry-run mode:

- Scripts print what they **would** do without touching ChromaDB, Neo4j, or
  the filesystem (no writes, no deletes, no network calls to embedding
  services).
- `neo4j_index_rebuild.py drop --dry-run` prints the DROP statements without
  executing them and without writing a snapshot file.
- `neo4j_index_rebuild.py create --dry-run` prints the CREATE statements
  without executing them.
- Ingest scripts (`ingest_*_v9.py`, `ingest_*_v8.py`) with `--dry-run` scan
  their source inputs and report the document/node counts they would produce,
  without embedding or writing.
- `reingest_validation.py --dry-run` prints the probes it would run without
  calling the MCP gateway.
- The State_Manager commands (`start`, `done`, `fail`, `skip`) still execute
  normally — dry-run mode simulates the *ingestion* layer, not the state
  layer, so the Work_Matrix walk completes.

**How to thread dry-run into every invocation:**

```bash
DRY_RUN_FLAG=""
if [[ "${REINGEST_DRY_RUN:-0}" == "1" ]]; then
  DRY_RUN_FLAG="--dry-run"
fi

# Then every script call appends ${DRY_RUN_FLAG}:
python3 mcp_server_python/scripts/<unit.script> ${DRY_RUN_FLAG} ...
```

The Loop_Driver sets `REINGEST_DRY_RUN=1` when invoked with `--dry-run`
itself, so the iteration inherits it without any per-unit logic.

## Procedure

1. **Claim one unit.** Run `SM next --pretty`. Parse the JSON.
   - If `unit` is `null`, there is no actionable work: **print `NO_WORK` and STOP
     immediately.** Do not run anything else.

2. **Mark it running.** `SM start --id <unit.id>`.

3. **Tenancy precheck + source precondition.**

   **3a. Tenancy precheck** (mandatory for every unit — Requirement 9):
   Read `unit.scope` and `unit.shared_once` from the claimed unit JSON.

   - If `unit.shared_once == true` OR `unit.scope` is `"shared"` or
     `"hybrid_external"`:
     - The unit is **shared-once**. `MCP_DEFAULT_TENANT` MUST be unset.
     - Check: `echo "${MCP_DEFAULT_TENANT:-UNSET}"` — if the output is anything
       other than `UNSET`, the tenancy state is wrong.
     - If wrong: `SM fail --id <unit.id> --error "tenancy_violation:
       MCP_DEFAULT_TENANT='${MCP_DEFAULT_TENANT}' but unit is shared-once (scope=${unit.scope})"` and STOP.

   - If `unit.scope` is `"tenant"` or `"hybrid_local"`:
     - The unit is **tenant-scope**. `MCP_DEFAULT_TENANT` MUST equal
       `unit.tenant_id`.
     - Check: `[[ "${MCP_DEFAULT_TENANT}" == "<unit.tenant_id>" ]]`
     - If wrong: `SM fail --id <unit.id> --error "tenancy_violation:
       MCP_DEFAULT_TENANT='${MCP_DEFAULT_TENANT}' but unit expects '${unit.tenant_id}'"` and STOP.

   **3b. Source precondition** (if `unit.source_precondition` is not null):
   Resolve the tenant tree at `${MCP_WORKFLOW_MOUNT}/<unit.workflow_subdir>`.
   - If `source_precondition.check` is set, verify `check.path` exists under the
     tenant root and (when `check.min_files` is set) has at least that many files.
   - If the precondition is otherwise described (e.g. a materialized EXPDIR tree
     outside the tenant root), evaluate the description directly.
   - **If unmet:** `SM skip --id <unit.id> --reason "<what was missing>"` and STOP.

4. **Execute the unit by `unit.stage` / `unit.kind`:**

   **Dry-run threading.** If `REINGEST_DRY_RUN=1`, every script invocation below
   MUST include `--dry-run`. Set the flag variable once at the start of step 4:
   ```bash
   DRY_RUN_FLAG=""
   if [[ "${REINGEST_DRY_RUN:-0}" == "1" ]]; then
     DRY_RUN_FLAG="--dry-run"
   fi
   ```
   Then append `${DRY_RUN_FLAG}` to every `python3 ... <script>` invocation.
   In dry-run mode, destructive gates (`CONFIRM_DESTRUCTIVE`) are not required
   because no writes occur. The State_Manager commands (`start`, `done`, etc.)
   still execute normally — only the ingestion layer is simulated.

   - **`worktree`** (prep): run
     `bash mcp_server_python/scripts/setup_pw_workflow_mount.sh`, then confirm the
     tenant symlink `${MCP_WORKFLOW_MOUNT}/<unit.workflow_subdir>` resolves. For
     tenants whose graph stages need Fortran, note the `sorc/` file count.
     (In dry-run mode, just confirm the symlink resolves — the setup script is
     idempotent and safe to run even in dry-run.)

   - **`reset`** (destructive): run
     `CONFIRM_DESTRUCTIVE="${CONFIRM_DESTRUCTIVE}" python3
     mcp_server_python/scripts/reset_tenant_cots.py --tenant <unit.tenant_id>
     --collection-version "${REINGEST_COLLECTION_VERSION}" ${DRY_RUN_FLAG}`.
     - In normal mode, requires `CONFIRM_DESTRUCTIVE=yes`.
     - In dry-run mode, the script prints what it would delete without acting;
       `CONFIRM_DESTRUCTIVE` is not required.
     - When building a **new** Collection_Version alongside the serving set, the
       reset is largely a no-op (the fresh collections do not exist yet) — that is
       expected success.

   - **`neo4j_drop_indexes`** (prep, destructive, shared-once): run
     `python3 mcp_server_python/scripts/neo4j_index_rebuild.py drop
     --i-mean-it Target_Version=${REINGEST_COLLECTION_VERSION}
     --snapshot .reingest_state/${REINGEST_COLLECTION_VERSION}/neo4j_pre_drop.json
     ${DRY_RUN_FLAG}`.
     - In normal mode, requires `CONFIRM_DESTRUCTIVE=yes`.
     - In dry-run mode, prints DROP statements without executing.
     - Confirm the snapshot file was written before marking done (skip this
       check in dry-run mode — no snapshot is written).

   - **`neo4j_rebuild_indexes`** (prep, shared-once): run
     `python3 mcp_server_python/scripts/neo4j_index_rebuild.py create
     --target-version ${REINGEST_COLLECTION_VERSION} ${DRY_RUN_FLAG}`.
     - In normal mode, verify all indexes report `state = ONLINE`.
     - In dry-run mode, prints CREATE statements without executing.

   - **ingest stages** (`workflow_docs_local`, `code_with_context_local`,
     `shell_graph`, `fortran_graph`, `python_graph`, `bridge`, `rocoto`,
     `expdir`, `jjobs`): run
     `python3 mcp_server_python/scripts/<unit.script> --tenant <unit.tenant_id>
     --mode <unit.mode> --collection-version "${REINGEST_COLLECTION_VERSION}"
     --delay 0.2 ${DRY_RUN_FLAG}`.

   - **shared-once ingest stages** (`ee2_standards`, `community_summaries`,
     `ci_test_cases`, `workflow_docs_external`, `pdf_sources`):
     - Confirm `MCP_DEFAULT_TENANT` is unset (step 3a already checked).
     - Run: `python3 mcp_server_python/scripts/<unit.script>
       --collection-version "${REINGEST_COLLECTION_VERSION}" --delay 0.2
       ${DRY_RUN_FLAG}` (NO `--tenant` flag).
     - `community_summaries`: **optional (Gap J).** If the COTS Neo4j has the GDS
       plugin and a runnable community-detection pipeline, run it; otherwise
       `SM skip --id <unit.id> --reason "Gap J: Neo4j GDS Leiden / Node-only
       pipeline unavailable on COTS"`. Its absence must NOT block the run.

5. **Validate** (`unit.probe`). Two validation paths:

   **In dry-run mode (`REINGEST_DRY_RUN=1`)**: skip all direct store validation
   (5a) and pass `--dry-run` to `reingest_validation.py` (5b). The dry-run
   validation prints what probes would run without calling the gateway. Mark the
   unit done with `--metrics '{"docs": 0, "nodes": 0, "probe": "dry_run"}'`.

   **5a. Direct store validation** (for all units with a non-`"none"` probe).
   On the COTS host, validate **directly against the local stores** (the
   `agentcore-mcp-rag` MCP tools target the AWS deployment, so they must NOT be
   used to validate a COTS write):
   - `vector` / `dual`: confirm the target ChromaDB collection exists and its
     `count()` rose — e.g. `python3 -c "import chromadb;
     print(chromadb.HttpClient(host='localhost',port=8080).get_collection('<index>').count())"`.
   - `graph_*`: run a Cypher count via the Neo4j driver on the tenant's labels/edges
     (e.g. `MATCH (:<PREFIX>ShellScript)-[r:SOURCES]->() RETURN count(r) AS c`) and
     confirm a non-empty, expected result. For non-`gw` tenants the graph may be
     sparser — assert "non-empty where ground truth says it should be".
   - `integrity` (`validate` stage): re-count the tenant's fresh nodes/edges and
     record them in metrics.
   (If a COTS-configured MCP such as `eib-mcp-gateway` is available, its tenant-
   scoped tools may be used instead — but direct DB checks are authoritative here.)

   **5b. Phase-79 read-path Validation_Probe** (for `validate`-kind units only).
   After the store checks pass, run the codified probe to confirm the Phase 79
   shared-scope routing works end-to-end against the fresh corpus:

   - For a **tenant-scope validate** unit:
     ```bash
     python3 mcp_server_python/scripts/reingest_validation.py \
       --target-version "${REINGEST_COLLECTION_VERSION}" \
       --tenant <unit.tenant_id> ${DRY_RUN_FLAG}
     ```
     This runs four MCP tool calls scoped to the tenant (search_documentation,
     search_ee2_standards, search_architecture, get_code_context) and writes
     results to `.reingest_state/<ver>/validation/<tenant>.json`.

   - For a **shared-once validate** unit (or after all shared-once stages complete):
     ```bash
     python3 mcp_server_python/scripts/reingest_validation.py \
       --target-version "${REINGEST_COLLECTION_VERSION}" \
       --global ${DRY_RUN_FLAG}
     ```
     This runs two probes (search_ee2_standards, search_architecture) without
     a tenant_id and writes to `.reingest_state/<ver>/validation/_shared_once.json`.

   - If `reingest_validation.py` exits non-zero, the probe failed — record the
     failure:
     `SM fail --id <unit.id> --error "validation_probe_failed: <exit_code>"` and STOP.

6. **Record the outcome:**
   - **Success:** `SM done --id <unit.id> --metrics '{"docs": N, "nodes": M, "probe": "ok"}'`
     (fill in the real counts you observed).
   - **Probe failed / ingester errored:** diagnose the root cause.
     - **Transient** (connection blip, timeout, rate limit): `SM fail --id
       <unit.id> --error "<message>"`. The loop retries with backoff up to the
       attempt cap; at the cap the unit becomes `blocked` for a human.
     - **Systematic** (a parser bug, a path wrong after the rename, a missing
       flag): apply the **smallest** fix to the ingester/config/stage catalog,
       then `SM fail --id <unit.id> --error "<message>" --requeue --note
       "<what you changed>"`. `--requeue` re-queues WITHOUT spending an attempt so
       the fix is exercised next iteration. Do not exceed the cap by hand — the
       State_Manager enforces it.

7. **STOP.** Print a one-line summary (`<unit.id> -> done|failed|skipped|blocked`).
   Do NOT run `SM next` again. Do NOT process another unit.

## Hard rules

- One unit per iteration. No exceptions.
- Never edit `state.json` by hand — only via `reingest_state.py`.
- `reset` and any in-place rebuild require `CONFIRM_DESTRUCTIVE=yes`.
- Never touch the existing serving collections or other tenants' data.
- Use `python3` (not `python3.12`).
- ASCII-only console output (`[OK]`, `[ERROR]`, `[WARN]`); no emoji.
- **Shared_Once_Rule**: shared-once units MUST run with `MCP_DEFAULT_TENANT`
  unset; tenant units MUST run with `MCP_DEFAULT_TENANT` matching the tenant.
- **Hybrid_Fan_Out**: external sub-stages write unprefixed; local sub-stages
  write tenant-prefixed. Never mix them.
- **Dry-run threading**: when `REINGEST_DRY_RUN=1`, EVERY script invocation in
  step 4 MUST include `--dry-run`. State mutations (`start`/`done`/`fail`/`skip`)
  still execute normally. Destructive gates are not enforced in dry-run mode.
