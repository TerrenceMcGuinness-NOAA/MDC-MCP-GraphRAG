# Phase 81: mpnet768 Full Tenant-Aware Re-Ingest

**Status**: IMPLEMENTATION COMPLETE (live-run pending)
**Created**: 2026-08-28
**Session**: phase81_mpnet768_tenant_reingest
**Severity**: HIGH — corpus is stale, partial, and tenancy-inconsistent;
67 % / 63 % coverage against declared totals

## Goal

Drive a full, resumable, tenant-aware, mpnet768 v9-0-0 re-ingest of vector
AND graph across all five tenants (`gw`, `gw_sfs`, `gw_jedi_gfs`, `gw_v17`,
`gw_gefs_v12`) on the COTS backend — closing the five never-ingested sources,
rebuilding Neo4j indexes for the post-APOC predicates, and proving the Phase
79 shared-scope read path end-to-end per tenant.

## Motivating Gaps

Empirically confirmed 2026-08-28 via
`get_knowledge_base_status(all_tenants=True)` and
`list_all_sources(include_gaps=True)`:

1. **Five declared sources never ingested**: `fortran-code-context`,
   `shell-code-context`, `python-code-context`, `rocoto-config`,
   `expdir-configs` — the 67 % coverage number on `code-with-context`.
2. **Five stale PDF sources** in `global-workflow-docs` — 63 % coverage.
3. **Three external doc crawls missing**: `rocoto`, `cmeps`, `nceplibs-sfcio`.
4. **Neo4j indexes built for the APOC-era predicate** — the query planner is
   inconsistent with the merged `toLower(toString(n.name)) CONTAINS`
   predicates.
5. **Non-default tenants empty or partial** — only `gw` is fully populated;
   four tenants have nodes but no graph relationships.
6. **Two mpnet768 clone generations diverging silently** — 2-document
   mismatch between `mdc-code-context-mpnet768` (60,576) and
   `code-with-context-v8-0-0` (60,574) with no single authoritative set.

## Deltas (on top of `cots-reingest-ralph-loop`)

| # | Delta | Design Section |
|---|---|---|
| 1 | Shared-once discipline | Work_Matrix emits shared-scope stages once tenant-blind |
| 2 | Hybrid_Fan_Out | `workflow_docs` and `code_with_context` split external/local |
| 3 | Neo4j index drop-and-rebuild | New `neo4j_index_rebuild.py`, explicit stages in catalog |
| 4 | Nine missing sources | Added to stage catalog with correct scope and dependencies |
| 5 | Per-tenant Validation_Probe + manifest writeback | Codified probe CLI, writeback on `done` |
| 6 | Cutover script | Human-gated, separate from the Ralph loop |

## New Files

| Path | Purpose |
|---|---|
| `mcp_server_python/scripts/neo4j_index_rebuild.py` | Index enumerate/drop/create/restore with confirmation token |
| `mcp_server_python/scripts/reingest_validation.py` | Codified MCP probe CLI (JSON-RPC over httpx) |
| `scripts/reingest_cutover.sh` | Human-invoked cutover: manifest rewrite + gateway restart + probe |
| `docs/reports/2026-XX-XX-mpnet768-tenant-reingest-verification.md` | Verification_Record template |

## Modified Files

| Path | Change |
|---|---|
| `mcp_server_python/scripts/reingest_stages.yaml` | Schema v2: scope/shared_once on all stages, hybrid sub-stages, 9 new sources |
| `mcp_server_python/scripts/reingest_state.py` | Schema v2: additive fields, migration, scope-drift, depends_on_all_tenants, writeback |
| `scripts/ralph_reingest_prompt.md` | Shared_Once_Rule + Hybrid_Fan_Out preamble, tenancy precheck, validation probe, dry-run |
| `scripts/ralph_reingest_loop.sh` | --dry-run, --target-version, --spec args; REINGEST_DRY_RUN export |

## Run-Book

### Pre-flight

```bash
cd /mcp_rag_eib/eib-mcp-rag-server

# Verify the serving image is present (Req 8.4)
docker images eib-mcp-rag-python:pre-shared-scope --format '{{.ID}}'

# Verify disk space (Req 11.4)
df -h /mcp_rag_eib

# Verify worktrees mounted for all tenants
ls .pw_workflow_mount/{develop,dev-sfs,dev-jedi-gfs,dev-v17,gefs-v12}/

# Dry-run the Work_Matrix
python3 mcp_server_python/scripts/reingest_state.py init \
  --state-root .reingest_state/v9-0-0 \
  --catalog mcp_server_python/src/config/tenants.yaml \
  --stages mcp_server_python/scripts/reingest_stages.yaml
python3 mcp_server_python/scripts/reingest_state.py report \
  --state-root .reingest_state/v9-0-0
```

### Live run

```bash
mkdir -p logs .reingest_state/v9-0-0
CONFIRM_DESTRUCTIVE=yes nohup bash scripts/ralph_reingest_loop.sh \
  --target-version v9-0-0 \
  --spec mpnet768-tenant-reingest-aug2026 \
  > logs/reingest_$(date +%Y%m%dT%H%M%S).log 2>&1 &
```

### Monitor

```bash
tail -f logs/reingest_*.log
tail -f .reingest_state/v9-0-0/loop.log
python3 mcp_server_python/scripts/reingest_state.py report \
  --state-root .reingest_state/v9-0-0
```

### Stop / resume

```bash
# Graceful stop
touch .reingest_state/STOP

# Resume (re-launch same command — durable state picks up where it left off)
rm -f .reingest_state/STOP
CONFIRM_DESTRUCTIVE=yes nohup bash scripts/ralph_reingest_loop.sh \
  --target-version v9-0-0 \
  --spec mpnet768-tenant-reingest-aug2026 \
  > logs/reingest_$(date +%Y%m%dT%H%M%S).log 2>&1 &
```

### Cutover (after `is-complete`)

```bash
bash scripts/reingest_cutover.sh --dry-run   # review the diff
bash scripts/reingest_cutover.sh             # live cutover
```

## Exit Criteria

1. All 67 Work_Matrix units in a Terminal_State (`done` or `blocked` with a
   documented reason).
2. `list_all_sources(include_gaps=True)` shows no source in the `never`
   bucket — every source is either `ingested` (v9-0-0) or `blocked` with a
   reason.
3. `.reingest_state/v9-0-0/validation/<tenant>.json` exists and records
   passing probes for all five tenants + `_shared_once.json`.
4. `get_knowledge_base_status(all_tenants=True)` shows non-zero node counts
   under all five tenant label_prefix families.
5. Neo4j `SHOW INDEXES` reports all indexes in `state = ONLINE` after
   rebuild.
6. No v8 collection was deleted, truncated, or rewritten (Req 1.2).
7. Verification_Record template filled with live-run evidence (Task 9.2).

## Canonical Spec

`.kiro/specs/mpnet768-tenant-reingest-aug2026/` — requirements, design, tasks,
progress log. This workflow doc is a run-book pointer; refer to the spec for
the full requirements and acceptance criteria.

## Dependencies

- Phase 79 (`shared-scope-query-routing`) — deployed, read path fixed.
- Phase 80 (`default-tenant-freeze-retirement`) — deployed, freeze retired.
- `cots-reingest-ralph-loop` — base machinery reused verbatim.
- APOC-free graph predicates merged on `develop @ 90af7c5`.
