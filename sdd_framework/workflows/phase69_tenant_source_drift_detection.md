# Phase 69 — Tenant Source-Drift Detection & Re-Ingest Flagging

**Version**: 0.1.0
**Created**: 2026-07-14
**Status**: draft (requirement captured; not scheduled)
**Estimated effort**: TBD (scoping needed)
**Depends on**: `cots-reingest-ralph-framework` (the `(tenant, stage)` Work_Matrix
and `reingest_state.py`); Phase 68 `rag-data-plane-gap-closure` (scope model +
`resolve_collection_name`); the runtime `check_knowledge_integrity` Stale-Embeddings
check
**Kiro spec**: _(to be authored — `.kiro/specs/tenant-source-drift-detection/`)_
**Owner**: Terry McGuinness (OMD CAT)

---

## 1. Executive Summary

Detect, **per tenant**, when a supported-repo checkout has **drifted** from what is
currently ingested into the COTS knowledge base — so the operator knows *which*
`(tenant, stage)` units need re-running before RAG/GraphRAG quality silently
degrades. This closes the gap left open in the Phase 68 review: the multi-tenant
tenant checkouts (e.g. `supported_repos/global-workflow_develop`) can move
their commit SHA or go `-dirty` in the working tree, and nothing today flags
that the ingested vectors/graph are now stale relative to the source.

The existing drift tooling does not cover this case:
- `mcp_server_node/scripts/drift_detector.py` detects **embedding/semantic**
  drift (cosine re-embed, 0.95 threshold) and is Node-era + AWS/SageMaker-bound;
  it is not tenant-checkout-SHA aware and was not ported to `mcp_server_python/`.
- `check_knowledge_integrity` samples **Stale Embeddings** at runtime but is not a
  per-tenant, per-stage re-ingest planner.
- `cots-reingest-ralph-*` records only `tenants_yaml_sha` catalog drift, not
  per-tenant **source** drift.

## 2. Scope

### 2.1 In Scope

- A COTS-native, tenant-aware **source-drift probe** that, for each tenant in
  `tenants.yaml`, compares the **currently checked-out source state** (checkout
  commit SHA + dirty-worktree flag under `.pw_workflow_mount/<subdir>`) against
  the **ingested provenance** recorded at ingest time (per collection / graph
  version stamp).
- A mapping from a drifted tenant to the specific `(tenant, stage)` Work_Matrix
  units that should be re-queued (`fail --requeue` / re-`init`), reusing the
  Phase-68 stage→domain scope model so **shared** stages are never redundantly
  re-run per tenant.
- A concise **drift report** (per tenant: ingested SHA, current SHA, dirty y/n,
  stages affected) surfaced through an MCP tool and/or `PROGRESS.md`.

### 2.2 Out of Scope (for now)

- Automatic re-ingest triggering (report-and-flag only; re-ingest stays
  human-gated / driven by the Ralph framework).
- Semantic/embedding drift (already covered by the Phase 49 `drift_detector.py`
  concept — a future port could unify the two).
- Any AWS/Neptune/OpenSearch/SageMaker or embedding-model change.

## 3. Open Questions

- Where is ingest provenance persisted per tenant/collection today (graph version
  stamp vs `.reingest_state/` vs manifest `last_ingested`), and is it sufficient
  to record the checkout SHA at ingest time?
- Threshold policy for `-dirty` worktrees (flag always, or only when tracked
  source files changed)?
- Standalone spec vs folding this into `cots-reingest-ralph-framework` as an
  added requirement.

## 4. Tasks

- [ ] 1. AWS-parity verification of the Phase 68 tool/data-model fixes
  - Run `mcp_health_check --deep --functional`, `check_knowledge_integrity`, and
    `get_knowledge_base_status` against the live AWS `agentcore-mcp-rag`
    (`DB_BACKEND=aws`, OpenSearch + Neptune) and compare to the COTS baseline.
  - Confirm whether the AWS Python serving path exhibits the same class of bugs
    the Phase 68 changes fixed on COTS — the `check_knowledge_integrity`
    Coverage-Gap / Stale-Embeddings `[SKIP]`s (path-leak) and the false
    `Total Documents: 0` / `Unhealthy` KB-status classification — since those
    fixes live in backend-agnostic tool code (`src/tools/semantic_search.py`).
  - Grep the AWS-side paths for any `SourceEntry` construction that omits the now
    **required** `scope` field (manifest schema change) before an AWS deploy.
  - Record which Phase 68 fixes actually close AWS gaps (vs COTS-only) in the run
    report; feed genuine AWS gaps into their own spec/phase.
  - _Verification only — no AWS serving (`resolve_index`/`aws_config.py`) change._

## 5. Notes

- Requirement captured 2026-07-14 during the Phase 68 check-in review (the
  `global-workflow_develop` submodule surfaced as `-dirty`, same SHA
  `6703c69…`). Left as a draft per operator direction — no code, no schedule yet.
