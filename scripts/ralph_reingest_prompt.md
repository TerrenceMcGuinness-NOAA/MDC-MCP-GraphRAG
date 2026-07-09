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

## Procedure

1. **Claim one unit.** Run `SM next --pretty`. Parse the JSON.
   - If `unit` is `null`, there is no actionable work: **print `NO_WORK` and STOP
     immediately.** Do not run anything else.

2. **Mark it running.** `SM start --id <unit.id>`.

3. **Check the source precondition** (if `unit.source_precondition` is not null).
   Resolve the tenant tree at `${MCP_WORKFLOW_MOUNT}/<unit.workflow_subdir>`.
   - If `source_precondition.check` is set, verify `check.path` exists under the
     tenant root and (when `check.min_files` is set) has at least that many files.
   - If the precondition is otherwise described (e.g. a materialized EXPDIR tree
     outside the tenant root), evaluate the description directly.
   - **If unmet:** `SM skip --id <unit.id> --reason "<what was missing>"` and STOP.

4. **Execute the unit by `unit.stage` / `unit.kind`:**

   - **`worktree`** (prep): run
     `bash mcp_server_python/scripts/setup_pw_workflow_mount.sh`, then confirm the
     tenant symlink `${MCP_WORKFLOW_MOUNT}/<unit.workflow_subdir>` resolves. For
     tenants whose graph stages need Fortran, note the `sorc/` file count.

   - **`reset`** (destructive): run
     `CONFIRM_DESTRUCTIVE="${CONFIRM_DESTRUCTIVE}" python3
     mcp_server_python/scripts/reset_tenant_cots.py --tenant <unit.tenant_id>
     --collection-version "${REINGEST_COLLECTION_VERSION}"`.
     - This requires `CONFIRM_DESTRUCTIVE=yes`. If it is not set, the script
       refuses; record `SM fail --id <unit.id> --error "CONFIRM_DESTRUCTIVE not set"`
       and STOP.
     - When building a **new** Collection_Version alongside the serving set, the
       reset is largely a no-op (the fresh collections do not exist yet) — that is
       expected success.

   - **ingest stages** (`documentation`, `code`, `jjobs`, `config`, `shell_graph`,
     `fortran_graph`, `expdir`, `rocoto`, `bridge`): run
     `python3 mcp_server_python/scripts/<unit.script> --tenant <unit.tenant_id>
     --mode <unit.mode> --collection-version "${REINGEST_COLLECTION_VERSION}"
     --delay 0.2`.

   - **global stages** (`unit.tenant_id == "__global__"`):
     - `ee2_standards`: run the confirmed EE2 ingester once into the shared
       (non-prefixed) collection. If no runnable COTS EE2 ingester exists, `SM skip`
       with that reason.
     - `community_summaries`: **optional (Gap J).** If the COTS Neo4j has the GDS
       plugin and a runnable community-detection pipeline, run it; otherwise
       `SM skip --id <unit.id> --reason "Gap J: Neo4j GDS Leiden / Node-only
       pipeline unavailable on COTS"`. Its absence must NOT block the run.

5. **Validate** (`unit.probe`). On the COTS host, validate **directly against the
   local stores** (the `agentcore-mcp-rag` MCP tools target the AWS deployment, so
   they must NOT be used to validate a COTS write):
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
