# Phase 51: Gateway Health, Explain, and Architecture-Search Fixes

**Version**: 1.0.0
**Status**: In Progress
**Created**: 2026-04-18
**Author**: AI Assistant + Terry McGuinness
**Dependency**: Phase 48 (AWS Infrastructure Port — introduced `HealthChecker.js`)
**Related**: Phase 27 (J-Job graph ingestion), Phase 24E (hierarchical communities), Phase 43 (expert self-diagnosis)

---

## 1. Executive Summary

Three independent defects make the EIB MCP Gateway report a degraded graph database, return empty `explain_workflow_component` responses, and surface irrelevant micro-communities from `search_architecture` — even though the underlying Neo4j (2,758 files, 2.65M relationships) and ChromaDB (85,995 docs across 6 collections) are fully populated and healthy.

This phase patches each defect, rebuilds the `eib-mcp-rag:latest` Docker image, restarts the gateway, and re-validates with the same probes that exposed the bugs.

## 2. Defects

### Defect 1 — `HealthChecker._checkGraph` reads a non-existent field

`src/health/HealthChecker.js` (Phase 48) does:
```js
const stats = await graphDB.getStatistics();
const nodeCount = stats?.nodes ?? 0;     // BUG: field is fileCount/functionCount/classCount
const ok = nodeCount > 0;
```
But `src/data/GraphDatabase.js#getStatistics()` returns `{ fileCount, functionCount, classCount, moduleCount }` — there is no `nodes` field. Result: `nodeCount` is always `0`, `ok` is always `false`, the gateway always reports DEGRADED.

### Defect 2 — `explain_workflow_component` returns only the heading

`src/tools/OperationalTools.js#explainWorkflowComponent` calls `multiSourceSearch(component, { sources: ['vector','graph'] })`. For J-job names (e.g., `JGLOBAL_FORECAST`), both arms return empty:

* The graph arm matches `:File`/`:Function` nodes; J-jobs are ingested under Phase 27B labels (`:JJob`/`:Script`), so they never match.
* The vector arm targets the default code/docs collections, not the dedicated `jjobs-v8-0-0` collection (700 docs) where every J-job lives.

Function falls through every conditional and emits just the `# Workflow Component: <name>` heading.

### Defect 3 — `search_architecture` ranks tiny L0 communities with negative similarity

Result observed: `Community 3525 (relevance: -0.379)` containing one file `yr2day.F` for the query "GFS forecast job UFS coupled model". Two compounding issues:

1. The ranker reports raw cosine without any threshold; any of 2,113 community summaries can win even when scores are negative.
2. There is no preference for the curated L1/L2 hierarchy added in Phase 24E — micro 2-node L0 leaves dominate.

## 3. Acceptance Criteria

| # | Probe | Pre-fix | Post-fix |
|---|-------|---------|----------|
| 1 | `mcp_health_check` | DEGRADED (8/9) | HEALTHY (9/9) |
| 2 | `explain_workflow_component({component:"JGLOBAL_FORECAST"})` | heading only | populated Documentation + Code Structure sections |
| 3 | `search_architecture({query:"GFS forecast job"})` | L0 micro-communities, negative scores | L1/L2 communities only, similarity ≥ 0.2 |
| 4 | `get_knowledge_base_status` | unchanged (2,758 files, 85,995 docs) | unchanged |
| 5 | `npx vitest run src/__tests__` | passing | still passing |

## 4. Implementation Plan

### Step 1 — Fix HealthChecker field mismatch
* File: `mcp_server_node/src/health/HealthChecker.js`
* Compute `nodeCount = (stats.fileCount ?? 0) + (stats.functionCount ?? 0) + (stats.classCount ?? 0)`.
* Add new `relCount` from `graphDB.getRelationshipStats()` for richer reporting.

### Step 2 — Extend `multiSourceSearch` to recognize J-jobs
* File: `mcp_server_node/src/data/UnifiedDataAccess.js`
* When `queryText` matches `/^J(GFS|GDAS|GLOBAL|ENKF)/i`, add `jjobs-v8-0-0` to the vector collections searched and add `:JJob` / `:Script` to the graph node labels matched.

### Step 3 — Filter `search_architecture` results
* File: `mcp_server_node/src/tools/GraphRAGTools.js`
* Apply `WHERE c.level >= 1 AND similarity >= 0.2`; rerank by `similarity * (1 + 0.25 * level)` so curated L2 summaries beat noisy L0 leaves of equal similarity.
* If no results pass the floor, emit `"No high-confidence architectural matches; try a more specific symbol or filename."` rather than negative-score noise.

### Step 4 — Unit tests
* Add `HealthChecker.test.js` case asserting `nodeCount > 0` when `getStatistics` returns `{fileCount: N}`.
* Extend `OperationalTools.test.js` with a J-job lookup case using a mocked `multiSourceSearch`.
* Extend `GraphRAGTools.test.js` with a similarity-floor assertion.

### Step 5 — Rebuild image and restart gateway
```bash
docker build -f SETUP/dockerfiles/Dockerfile.mcp-server -t eib-mcp-rag:latest ./mcp_server_node
pkill -f "docker-mcp gateway"
docker stop $(docker ps -q --filter "label=docker-mcp-name=eib-mcp-rag") 2>/dev/null
docker rm   $(docker ps -aq --filter "label=docker-mcp-name=eib-mcp-rag") 2>/dev/null
MCP_GATEWAY_AUTH_TOKEN="eib-mcp-gateway-token-2025" docker mcp gateway run \
  --catalog eib-local.yaml --servers eib-mcp-rag \
  --transport streaming --port 18888 --long-lived &
```

### Step 6 — Re-validate against acceptance criteria
* Re-run probes 1–4 from §3.
* Capture before/after into `docs/development/phase51_validation.md` (one-shot, not an ongoing doc).

### Step 7 — Update `CHANGELOG.md`
* New entry: `[8.2.2] - Phase 51: Gateway Health/Explain/Architecture Fixes (April 18, 2026)`
* List per-defect fix, file paths, and image rebuild requirement.

## 5. Out of Scope

* Re-tuning of community embeddings (Phase 24G/H territory).
* Migration of J-job nodes to the `:File` label (would break Phase 27B graph contracts).
* Persistent health trending (Phase 43 §3.1).

## 6. Rollback Plan

All changes are local to four JS files. If validation fails, `git revert` the commit and restore the previous Docker image (`eib-mcp-rag:8.2.1`) by retagging.
