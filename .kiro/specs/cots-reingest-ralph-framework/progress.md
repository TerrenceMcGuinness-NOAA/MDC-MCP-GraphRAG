# Progress — cots-reingest-ralph-framework

> Ralph-Loop memory file. The **Corrections** table is re-read before every task;
> never repeat a listed mistake. **Codebase Patterns** are conventions to follow.
> Pre-seeded from the `cots-reingest-ralph-loop` PoC (2026-07-08/09) so iteration
> 1 already knows the gotchas.

## Corrections

- ❌ `python3.12 …` → ✅ `python3 …` (the COTS head node has only Python 3.11.14; no `python3.12`)
- ❌ Validate a COTS write with `agentcore-mcp-rag` MCP tools → ✅ validate with **direct ChromaDB `count()` / Neo4j Cypher** (the `agentcore-mcp-rag` MCP targets the AWS deployment, not the COTS stores; use `eib-mcp-gateway` only if it is confirmed COTS-configured)
- ❌ `MATCH (n) RETURN count(n) c` → ✅ `MATCH (n) RETURN count(n) AS c` (openCypher requires `AS`)
- ❌ Vector ingest via `raw_os_client.index(...)` on COTS → ✅ use `_ingest_common.write_vector_doc(...)` which upserts to ChromaDB (`ChromaDBAdapter` has no `_raw_client`; the raw path is AWS-only)
- ❌ `reset_tenant_cots.py` real run without `CONFIRM_DESTRUCTIVE=yes` → ✅ export `CONFIRM_DESTRUCTIVE=yes` (it refuses otherwise); use `--dry-run` to preview
- ❌ `reset` with `--full-prefix-wipe` on a fresh version → ✅ let it default to **version-scoped** (fresh version deletes only `collection_version=<ver>` nodes; full-prefix-wipe deletes the tenant's entire serving graph)
- ❌ Assume the graph ingest is version-isolated → ✅ only `code`/`jjobs` stamp `collection_version` today; `shell_graph`/`fortran_graph`/`config`/`rocoto`/`bridge` MERGE into serving labels until Task 2.2 lands the stamp
- ❌ Run a heavy stage (documentation/code/fortran_graph) inline in one LLM iteration → ✅ `sbatch` it to `emcmcpminicluster` (documentation alone is 20 min+ for ~2,500 docs; a killed iteration leaves the unit `running` and stuck)
- ❌ On a Slurm compute node set `CHROMADB_HOST=localhost` → ✅ point `CHROMADB_HOST`/`NEO4J_URI` at the **head-node** address (the DBs run on the head node)
- ❌ Conclude "embeddings unavailable" from the `mpnet768` "sentence-transformers is not installed" warning → ✅ the warning is cosmetic; `sentence-transformers` 5.1.2 imports and produces real 768-dim vectors (~5 s first load)
- ❌ Treat `config`/`expdir`/`rocoto`/`fortran_graph` empties as failures → ✅ they are legitimate skips: `dev-v17` has no `parm/config`; only `gw`/`gw_v17` have EXPDIR; `gefs-v12` `sorc`=265 (<1000)
- ❌ Assume a fresh `mdc-*-titan1024-<ver>` collection is queryable on COTS → ✅ COTS queries resolve `mdc-*-mpnet768`; until Task 2.3 the ingesters write `titan1024`-named collections that the serving query path won't find

## Codebase Patterns

- **Ingestion entry scripts** (`mcp_server_python/scripts/ingest_*_v8.py`) share
  `_ingest_common.build_ingestion_parser()` (has `--tenant/--mode/--collection-version/--dry-run/--delay`),
  `resolve_tenant_and_mode()`, `resolve_worktree_root()`, and
  `build_ingestion_data_access()` (returns `(uda, raw_os_client)`; `raw_os_client`
  is `None` on COTS).
- **Collection versioning**: `resolve_collection_version(args)` (flag > env
  `REINGEST_COLLECTION_VERSION` > `DEFAULT_COLLECTION_VERSION=v8-0-0`);
  `versioned_collection_name(base, version)` returns `base` for the default version,
  else `base-<version>`.
- **Tenant resolution**: `tenant.workflow_root = ${MCP_WORKFLOW_MOUNT}/<workflow_subdir>`;
  the `.pw_workflow_mount` symlink farm is built by `setup_pw_workflow_mount.sh`
  (needs the dir owned by the run user — `sudo chown` if root-owned).
- **Graph writes** go through `uda.graph_db.query(cypher, params=..., tenant=None)`
  (pass `tenant=None` to avoid the adapter re-prefixing hand-written labels);
  labels are back-tick-quoted, e.g. `` MERGE (n:`GW_V17_File` ...) ``.
- **State backend**: `reingest_state.py` (`init/next/start/done/fail/skip/report/
  is-complete`) is the `(tenant, stage)` DAG; `next` gates on same-tenant
  `depends_on` terminality + attempt cap; `.reingest_state/<ver>/` is gitignored.
- **COTS env** (SPOT: `mcp_server_python/scripts/run_mcp_stdio.sh`): `DB_BACKEND=cots`,
  `MCP_EMBEDDING_PROFILE=mpnet768`, `NEO4J_URI=bolt://localhost:7687`
  (user `neo4j` / pw `gfsworkflow2025`), `CHROMADB_HOST=localhost:8080`,
  `MCP_WORKFLOW_MOUNT=<repo>/.pw_workflow_mount`.
- **ASCII-only console output** (`[OK]`/`[ERROR]`/`[WARN]`); 2-space bash indent;
  quote `"${vars}"`; no auto-commit/push.

## Progress log

### 2026-07-09 — spec authored (carry-over from PoC)
Carried from `.reingest_state/v9-0-0` (PoC, real live work, idempotent/resumable):
- **Done (15 units)**: `worktree`×5, `reset`×5 (version-scoped no-op — serving
  untouched), and gw_v17 `jjobs` (92 docs in `gw_v17_mdc-jjobs-titan1024-v9-0-0`
  + 92 `GW_V17_JJob` stamped `v9-0-0`), `shell_graph` (1,479 SOURCES / 6,069
  EXPORTS / 21,005 DEPENDS_ON_ENV), `expdir` (1,582 `GW_V17_EXPDIRConfig`),
  `rocoto` (724 `GW_V17_RocotoTask`), `bridge` (12 `EXECUTES`).
- **Partial**: gw_v17 `documentation` wrote 2,518 docs before the 20-min cap
  (idempotent; resumes via upsert-by-SHA) — re-queued pending.
- **Skipped (3)**: gw_v17 `config` (no `parm/config` in dev-v17); global
  `ee2_standards` (no COTS ingester); global `community_summaries` (Gap J —
  GDS 2.13.7 present but Node-only, not tenant-aware).
- **Pending (44)**: everything else (heavy stages → Slurm in this iteration).
