# Design Document

## Overview

This design closes eight RAG data-plane gaps found in the 2026-07-09 COTS health
run and encodes the missing **tenant-vs-shared scope** principle. It is the
Kiro-spec form of SDD Phase 68 and the first incremental step back to full speed.

The centerpiece is a one-field schema change — `scope: tenant | shared` on every
manifest source — plus the two places that must honor it (the Work_Matrix builder
and the collection namer). The rest are small, localized fixes: two Phase-67 path
leaks, a ChromaDB `sample_metadata` interface, and a `get_knowledge_base_status`
count fix. No re-ingest runs here; the heavy work stays in
`cots-reingest-ralph-framework`, which consumes two decisions from this phase.

### Why scope is the durable value

Two independent concerns were conflated in the manifest:

| Concern | Correct scope | Rationale |
|---|---|---|
| NWS-wide docs, EE2 standards, general community summaries | **shared** | Same text → same embeddings for every tenant. Prefixing wastes storage 5×, splits recall, and forces a re-ingest for every new tenant. |
| Per-branch code, jjobs, derived graph labels | **tenant** | Two branches diverge; a `gw_v17` `JJob` is not a `gw` `JJob`. |
| Repos outside global-workflow (future) | **tenant** | A tenant is any `(repo, branch)` pair the LLM should be code-aware of — same mechanism. |

Encoding this once prevents the next N tenants (global-workflow branches *or*
external repos) from silently duplicating the doc embedding space.

## Architecture

```
                         Manifest SPOT                         Runtime consumers
   ┌───────────────────────────────────────────┐     ┌──────────────────────────────┐
   │ generate_unified_manifest.py KNOWN_SOURCES │     │ reingest_state.py init        │
   │   + scope: tenant|shared  (R1.4)           │     │   Work_Matrix builder (R2)    │
   │            │ regenerate                     │     │   shared → 1 unit (__global__)│
   │            ▼                                 │     │   tenant → N units            │
   │ src/config/unified_manifest.json (R1.5)     │────►│   reads reingest_stages.yaml  │
   └───────────────────────────────────────────┘     │     (documentation → shared)  │
                    ▲ validated by                     └──────────────┬───────────────┘
   ┌────────────────┴───────────────────────────┐                    │ names via
   │ src/manifest/models.py                       │                    ▼
   │   SourceEntry: scope required common field   │     ┌──────────────────────────────┐
   │   from_dict rejects missing/invalid (R1.1-3) │     │ collection_namer              │
   └──────────────────────────────────────────────┘     │  resolve_collection_name(     │
                                                          │    source, tenant, version)  │
   Health-run gap fixes (independent, localized):         │  shared → mdc-{d}-{p}{ver?}  │
   ┌──────────────────────────────────────────┐          │  tenant → {prefix}mdc-…      │ (R3)
   │ workflow_info / check_knowledge_integrity │          └───────────┬──────────────────┘
   │   hard-coded path → ctx.tenant.workflow_root (R4)                │ used by
   ├──────────────────────────────────────────┤          ┌───────────▼──────────────────┐
   │ chromadb_adapter.sample_metadata (R5)     │          │ write_vector_doc + 4 v8       │
   │   → integrity Path/Stale checks run        │          │ ingesters + reset_tenant_cots │
   ├──────────────────────────────────────────┤          └───────────────────────────────┘
   │ get_knowledge_base_status count sum (R6)  │
   └──────────────────────────────────────────┘          feeds ► cots-reingest-ralph-framework
                                                              (progress.md + design.md, R8)
```

## Components and changes

### 1. Manifest schema — `scope` field (R1)

**Files:** `mcp_server_python/src/manifest/models.py`,
`mcp_server_python/scripts/generate_unified_manifest.py`,
`mcp_server_python/src/config/unified_manifest.json`.

- `models.py` — add `scope: str` as an explicit `SourceEntry` field; add `"scope"`
  to `_COMMON_REQUIRED_FIELDS`; in `from_dict`, after presence validation, reject
  values not in `{"tenant", "shared"}` with a `ValueError` naming the source;
  emit `scope` in `to_dict` right after `description` in the stable ordering; add
  `"scope"` to the `common_keys` set so it is not swept into `type_fields`.
- `generate_unified_manifest.py` — add `"scope"` to each `KNOWN_SOURCES` entry per
  the R1.4 classification (a small helper `_default_scope(source_type)` keeps it
  DRY: shared for `{url_crawl, on_disk_submodule, standards, community_summary}`,
  tenant for `{code_parse, config_parse, jjob_docs}`); bump the manifest `version`.
- Regenerate `unified_manifest.json`; every source carries `scope`.

Classification (matches the live ChromaDB collection reality):

| Collection | Scope | Sources |
|---|---|---|
| `mdc-workflow-docs-*` | shared | 58 url_crawl + 1 on_disk_submodule |
| `mdc-ee2-standards-*` | shared | 1 standards |
| `mdc-community-summaries-*` | shared | 1 community_summary |
| `mdc-code-context-*` | tenant | 3 code_parse + 2 config_parse |
| `mdc-jjobs-*` | tenant | 1 jjob_docs |

### 2. Work_Matrix builder respects scope (R2)

**Files:** `mcp_server_python/scripts/reingest_state.py`,
`mcp_server_python/scripts/reingest_stages.yaml`.

- `reingest_stages.yaml` — add a `scope` field to each stage; **move
  `documentation` from `per_tenant_stages` to a shared stage** (or tag it
  `scope: shared` and have the builder route accordingly). `ee2_standards` and
  `community_summaries` are already global/shared; tag them `shared`. All other
  per-tenant stages are `tenant`.
- `reingest_state.py` matrix build — for a `shared` stage emit one unit with
  `tenant_id="__global__"` (no tenant coupling); for a `tenant` stage emit one
  unit per catalog tenant (unchanged). For the current 5-tenant catalog this
  yields **55 tenant + 3 shared = 58 units** (was 62).
- Idempotent migration — `init` already preserves existing statuses and only adds
  missing units; verify + regression-test that a pre-scope `state.json` migrates
  with terminal statuses intact and the five per-tenant `documentation` units
  collapse to one shared unit (the PoC's 2,518-doc partial write is a valid
  checkpoint since it landed in the shared `mdc-workflow-docs-*` collection).
- Regenerate `PROGRESS.md`.

### 3. Scope-aware collection namer (R3)

**Files:** new `mcp_server_python/src/data/collection_namer.py` (canonical home
per the SDD) delegated to by `mcp_server_python/scripts/_ingest_common.py`
(which currently holds `versioned_collection_name`); consumers
`ingest_{documentation,code,jjobs,config_files}_v8.py` and `reset_tenant_cots.py`.

```python
def resolve_collection_name(source, tenant, version) -> str:
    domain  = source.domain            # e.g. "workflow-docs", "code-context", "jjobs"
    profile = source.embedding_profile # e.g. "mpnet768" (COTS) / "titan1024" (AWS)
    suffix  = "" if version == DEFAULT_COLLECTION_VERSION else f"-{version}"
    if source.scope == "shared":
        return f"mdc-{domain}-{profile}{suffix}"
    return f"{tenant.index_prefix}mdc-{domain}-{profile}{suffix}"
```

- The existing `_ingest_common.versioned_collection_name` becomes a thin wrapper
  that delegates to `resolve_collection_name` (or is replaced call-site by
  call-site). Behaviour for the default serving version is preserved exactly
  (suffix empty → current names).
- This is the authoritative naming rule for Framework_Spec Task 2.3.

### 4. Phase-67 path-rename leak fix (R4)

**Files:** `mcp_server_python/src/tools/workflow_info.py`,
`mcp_server_python/src/tools/semantic_search.py`.

- `workflow_info` currently falls back to a hard-coded `DEFAULT_WORKFLOW_ROOT =
  "supported_repos/global-workflow_develop"` (Phase 67 renamed the literal but it
  is still hard-coded). Resolve from `ctx.tenant.workflow_root` when a tenant
  context exists; the default tenant resolves to `.pw_workflow_mount/develop` via
  the mount base. Keep the env/`HOMEgfs` fallbacks for out-of-context startup.
- `check_knowledge_integrity`'s coverage-gap check (`_resolve_repo_base` in
  `semantic_search.py`) makes the same substitution, so it no longer emits
  `[SKIP] no Fortran files found in supported_repos/global-workflow`.
- Grep the exact strings before/after; add the functional-health assertion (R4.3).

### 5. ChromaDB `sample_metadata` (R5)

**File:** `mcp_server_python/src/data/chromadb_adapter.py`.

```python
def sample_metadata(self, collection: str, n: int = 20) -> list[dict]:
    col = self._get_collection_or_none(collection)
    if col is None:
        return []
    got = col.get(limit=n, include=["metadatas"])
    return got.get("metadatas") or []
```

Wire the two `check_knowledge_integrity` `[SKIP]` branches (Path Consistency,
Stale Embeddings) to call it so both run on COTS.

### 6. `get_knowledge_base_status` count (R6)

**File:** `mcp_server_python/src/tools/semantic_search.py`.

Iterate the applicable collections and sum `collection.count()`; report the sum
as `Total Documents`. Status is `[OK] Healthy` when `count > 0` **or** the tenant
has zero applicable collections (a fresh tenant is healthy, not unhealthy). Never
report `Total Documents: 0 [ERROR]` when live non-empty collections exist.

### 7. Two-axis tenant model docs (R7)

**File:** `.kiro/steering/11-tenant-roadmap.md` (or a sibling).

Add a worked "adding a non-global-workflow tenant" example (e.g. `pw_mcp` →
`supported_repos/parallel-works-mcp`, branch `main`), clarifying that
`workflow_subdir` is a repo-relative anchor and no `tenants.yaml` schema change is
needed.

### 8. Feed decisions into the framework spec (R8)

**Files:** `.kiro/specs/cots-reingest-ralph-framework/progress.md`,
`.kiro/specs/cots-reingest-ralph-framework/design.md`.

Record the shared-vs-tenant naming rule in `progress.md`
(Corrections / Codebase-Patterns) to unblock Framework Task 2.3, and add a
two-line pointer in that spec's `design.md` back to this phase (scope model) and
Requirement 3 (namer).

### 9. EXPDIR — realtime, tenant-derived source reconciliation (R15)

**Files:** `mcp_server_python/scripts/ingest_expdir_configs_v8.py`
(`resolve_expdir_base`, `discover_experiments`, `_ingest_experiment`);
`generate_unified_manifest.py` + `unified_manifest.json` (`expdir-configs`
source); `reingest_stages.yaml` (`expdir`/`rocoto` preconditions); steering +
`progress.md`.

EXPDIR is a **crept-in scope seam** — "expdir" denotes two different things:

- the manifest `expdir-configs` source declares `config_root: …/parm/config`
  (static repo templates), but
- the ingester reads a **separate runtime tree** `supported_repos/EXPDIR`
  (materialized experiment dirs: pslot, resolution, **resolved** `config.*` +
  Rocoto XML — realtime data produced by `setup_expt`, not repo content).

And `resolve_expdir_base(tenant)` **ignores its `tenant` argument** (returns a
single fixed path unless `MCP_EXPDIR_BASE_OVERRIDE` is set), so tenant isolation
today comes only from the write-time graph label prefix. In practice EXPDIR is
materialized only for **gw and gw_v17**.

**Fix (minor code + config; no re-ingest):**
1. Annotate `expdir-configs` as realtime/runtime + `scope: tenant`, and point its
   source base at the runtime EXPDIR tree (not `parm/config`) — reconciling the
   manifest with what the ingester actually reads.
2. Make `resolve_expdir_base(tenant)` **tenant-derived** — a per-tenant base
   (exact mapping confirmed from COTS; gw / gw_v17 today), keeping
   `MCP_EXPDIR_BASE_OVERRIDE` as the explicit override. An absent base returns "no
   EXPDIR" and **never** falls back to another tenant's tree.
3. Keep the write-side `{prefix}Experiment` / `{prefix}EXPDIRConfig` labeling
   unchanged; `expdir`/`rocoto` continue to `skip` (not fail) for tenants with no
   materialized experiment.
4. Document the realtime + tenant-localized nature so it is not re-conflated with
   static repo config.

## Data model delta

`SourceEntry` gains one field:

```
  name, source_type, collection_target, embedding_profile, enabled, description,
  scope,            # NEW — "tenant" | "shared" (required common field)
  last_ingested, ingestion_script, doc_count, type_fields{…}
```

`reingest_stages.yaml` stages gain `scope: tenant | shared`; `documentation`
moves to shared.

## Error handling

- Missing/invalid `scope` → `ValueError` at manifest load naming the source
  (fail fast; the manifest is human-curated).
- `sample_metadata` on an empty/missing collection → `[]` (never raises), so
  integrity checks degrade gracefully rather than crash.
- Matrix migration → terminal statuses preserved; a corrupt/absent pre-scope state
  is rebuilt from scratch (no silent status loss for terminal units).

## Testing strategy

- **Unit** (`test` sub-tasks, may be skipped to ship): manifest schema round-trip
  + missing/unknown `scope` raises; matrix builder produces the exact 55+3 shape
  from a fixture catalog+stages and migrates a pre-scope state preserving terminal
  statuses; collection-namer 8 cases across (shared|tenant)×(default|explicit
  ver)×(empty|non-empty prefix); `sample_metadata` returns 3 for a 3-doc mock and
  `[]` for empty; `get_knowledge_base_status` count with a mocked 3-collection
  adapter.
- **Functional** (on COTS, R10): `mcp_health_check --deep --detailed --functional`
  → 11/11 (only `community_summaries` may SKIP); `check_knowledge_integrity` → 4/4
  run; `get_knowledge_base_status` → `Total Documents > 0`, `[OK]`;
  `list_all_sources --include_gaps` → scope on every source + corrected names.
- **Regression**: the existing ingester + `reingest_state` suites still pass;
  default (serving) collection names are byte-for-byte unchanged.

## Execution on COTS — kiro-cli engagement

This phase is executed by **kiro-cli running on the COTS host**. It is bounded,
local code work — no ingest, no heavy embedding, no Slurm — so it runs **inline on
the head node** as a single self-governed, resumable session. (Contrast with
`cots-reingest-ralph-framework`, which dispatches heavy stages to the Slurm
minicluster.)

### Environment (established by `run_mcp_stdio.sh`)

```
DB_BACKEND=cots
MCP_EMBEDDING_PROFILE=mpnet768                 # local all-mpnet-base-v2, 768-dim
CHROMADB_HOST=localhost  CHROMADB_PORT=8080    # ~15 live serving collections
NEO4J_URI=bolt://localhost:7687                # ~343k nodes / ~4.2M rels; GDS 2.13.7
MCP_WORKFLOW_MOUNT=${REPO_ROOT}/.pw_workflow_mount   # tenant worktrees
```

The COTS stores hold **live serving data**. This phase mutates none of it (no
ingest); it only changes code the COTS MCP server reads. Capture a config/state
snapshot before touching serving-path modules (R12.4) so a bad edit is trivially
reverted.

### Verification must be COTS-truthful (the critical constraint)

The MCP tools the acceptance criteria reference (`mcp_health_check`,
`check_knowledge_integrity`, `get_knowledge_base_status`, `list_all_sources`)
report **whatever backend they are wired to**. On this host:

- `eib-mcp-gateway` in `.amazonq/mcp.json` → the **blocked** Docker-MCP-Gateway
  dev tunnel. Do not rely on it.
- `agentcore-mcp-rag` / `eib-mcp-rag-full` → the **AWS** backend
  (Neptune/OpenSearch). Its results do NOT reflect the COTS stores.

So every Phase-68 verification (Tasks 9.x) MUST run against the COTS backend. The
**specified method** (decided) is the COTS-local stdio server; the in-process call
is a fallback only.

1. **COTS-local stdio server (specified)** — launch `run_mcp_stdio.sh` (which
   forces `DB_BACKEND=cots`, `mpnet768`, and the ChromaDB/Neo4j endpoints) and
   register it as a temporary MCP server entry in the kiro-cli session's config
   (do NOT reuse the AWS `agentcore-mcp-rag` entry, do NOT use the blocked
   `eib-mcp-gateway`). Call the probes as MCP tools so the real server + tool code
   path is exercised end-to-end against the live COTS stores. Tear the temporary
   entry down at session end.
2. **In-process tool call (fallback only)** — if the stdio server cannot be stood
   up, invoke the tool function directly under `DB_BACKEND=cots` (the PoC pattern),
   e.g. `python3 -c "from src.tools... import get_knowledge_base_status; ..."` with
   the COTS data-access layer.

The method used and the observed COTS counts (before/after) are recorded in
`progress.md` (R13.3). This is the single most important lesson from the PoC:
a green health check against AWS proves nothing about COTS.

### Session protocol (self-governed, resumable)

1. **Kickoff** — start an SDD session for this phase; read this spec + `progress.md`.
   Seed/refresh the Corrections table from the PoC learnings (see `progress.md`).
2. **Snapshot** — capture the serving-path module state + record baseline COTS
   counts (`get_knowledge_base_status`, `check_knowledge_integrity`) via the
   COTS-truthful method, into `progress.md`.
3. **Drive tasks in `tasks.md` order** — the DAG is small and mostly parallel
   (see the dependency graph). For each task: implement → run its `test`/probe →
   record the result and any Correction in `progress.md` → mark the task.
4. **Verify** — Task 9 re-runs the four probes COTS-truthfully; assert the exit
   criteria (11/11 health, 4/4 integrity, `Total Documents > 0`, scope on every
   source).
5. **Stage + report** — Task 10 writes the CHANGELOG entry and stages everything;
   **no commit, no push** (R11.3 / R14.3). Complete the SDD session.
6. **Resume** — on disconnect, re-read `progress.md` + the SDD session state and
   continue from the first unfinished task; the durable file, not chat memory, is
   the source of truth.

Suggested kickoff (confirm the installed CLI's flags first):

```bash
# on the COTS head node, repo root, DB_BACKEND=cots env sourced
kiro-cli chat --trust-all-tools --no-interactive \
  "Engage .kiro/specs/rag-data-plane-gap-closure. Read the spec + progress.md.
   Verify COTS-truthfully (DB_BACKEND=cots; NOT the AWS agentcore-mcp-rag and
   NOT the blocked eib-mcp-gateway). Work tasks in order, updating progress.md
   after each. Stage changes; do not commit or push."
```

### Prerequisites (gated at kickoff — Task 0)

- kiro-cli present on COTS and able to run `--no-interactive` (the framework spec
  confirmed `kiro-cli chat --trust-all-tools --no-interactive`).
- COTS stack up: ChromaDB `:8080` and Neo4j `:7687` reachable; `mpnet768` provider
  imports and embeds (the "sentence-transformers not installed" line is a known
  false warning — it works).
- The COTS-truthful verification method (1 or 2 above) chosen and smoke-tested on
  one probe before starting.
- `progress.md` seeded; SDD session started.

### Relationship to the framework spec

Phase 68 is the **unblocking** step; `cots-reingest-ralph-framework` is the
**execution** engagement that follows. Completing Phase 68:
- gives Framework Task 2.3 an authoritative, profile-derived collection name
  (`mdc-{domain}-mpnet768{-ver}` shared / `{prefix}mdc-…` tenant) — this also
  resolves the framework's noted `titan1024`→`mpnet768` naming reconcile for COTS;
- shrinks the framework's Task 5 matrix from 62 → 58 units (docs ingested once);
- removes the two integrity `[SKIP]`s that were hiding real problems, so the
  framework's per-stage validation is trustworthy.

## Out of scope (deferred / owned elsewhere)

- Any re-ingest execution → Framework_Spec.
- Graph version-stamping of shell/fortran/config/rocoto/bridge → Framework Task 2.2.
- URL-crawl staleness refresh → `url-crawl-gap-closure` / Phase 58.
- Serving-collection cutover → Framework Task 7 (human-gated).
- Removing the `phase48-scratch` collection → separate confirmed destructive action.
- Any OpenSearch/Neptune/AgentCore (AWS) change (R9).

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Matrix rebuild loses terminal statuses | Re-run gw_v17's completed graph stages | Idempotent `init` preserves done/skipped (R2.3) + regression test |
| Shared docs need re-embed under corrected name | One extra doc ingest | Framework Task 5 will ingest anyway; fixing the name now avoids double-writing |
| A consumer assumes tenant-prefixed doc collections | Serving query 404 | Live ChromaDB docs are ALREADY unprefixed; the fix aligns the ingester with reality |
| An unaudited caller hard-codes the old path | Runtime error | Grep the exact string before/after; functional health assertion (R4.3) |
