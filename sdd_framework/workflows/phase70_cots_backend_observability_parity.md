# Phase 70 — COTS Backend Observability Parity (ChromaDB Adapter)

**Version**: 0.1.0
**Created**: 2026-07-20
**Status**: draft (requirement captured; not scheduled)
**Estimated effort**: TBD (scoping needed — small-to-medium)
**Depends on**: Phase 63a (`backend_label_rename_legacy_to_cots`); Phase 68
(`rag-data-plane-gap-closure`) for the manifest gap-detection contract
**Kiro spec**: _(to be authored — `.kiro/specs/cots-backend-observability-parity/`)_
**Owner**: TBD

---

## 1. Executive Summary

The ChromaDB (`DB_BACKEND=cots`) adapter is missing the observability methods
that the OpenSearch (`DB_BACKEND=aws`) adapter implements. As a result, on the
COTS deployment (which is the current Parallel Works default):

- `get_knowledge_base_status` reports **`Total Documents: 0`** and marks the
  vector database `[ERROR] Unhealthy`, despite ChromaDB serving 17 collections
  with hundreds of thousands of embedded documents.
- `check_knowledge_integrity` **skips 3 of 4 sub-checks** (Path Consistency,
  Stale Embeddings, and — indirectly — coverage-related sampling) with the
  message *"vector adapter does not expose a metadata sampler"*.
- `list_all_sources --include_gaps` reports **0.0% coverage on every declared
  collection**, because the gap detector's "actual" count is hard-wired to the
  OpenSearch `_count` API and returns 0 for ChromaDB.

The graph side is fine — the same three tools report Neo4j nodes/relationships
correctly. This is a vector-adapter-only gap.

Observed on 2026-07-20 during the post-cutover full-sweep gap analysis (see
`supported_repos/global-workflow.wiki/agentcore-mcp-rag-Gap-Analysis-2026-07-20.md`,
Gaps 1 & 2).

## 2. Scope

### 2.1 In Scope

- Add `count_documents(collection: str) -> int` to the ChromaDB adapter, using
  ChromaDB's native `collection.count()` API. Wire it into
  `UnifiedDataAccess.get_backend().vector.count(...)`.
- Add `sample_metadata(collection: str, limit: int = 50) -> list[dict]` using
  `collection.get(limit=N, include=["metadatas", "documents"])`.
- Update `get_knowledge_base_status` to prefer the backend-abstract
  `vector.count()` path over any hard-wired OpenSearch call.
- Update `list_all_sources --include_gaps` so the "actual" side dispatches
  through the active backend (`config.db_backend`) rather than assuming
  OpenSearch.
- Restore Path Consistency and Stale Embeddings sub-checks in
  `check_knowledge_integrity` on COTS (they only need the new sampler).
- Add a `Vector.count()` contract test to `mcp_server_python/tests/unit/` that
  both backend adapters must pass.

### 2.2 Out of Scope

- Any change to the OpenSearch/AWS adapter's existing behavior (it already
  works — this phase is COTS-side parity only).
- The Fortran coverage-gap check's hard-coded workflow path — that is Phase 72.
- Node-count scope documentation across `get_knowledge_base_status` vs
  `mcp_health_check` — that is Phase 73.
- Nightly benchmark harness scheduling — that is Phase 71.

## 3. Success Criteria

1. On `DB_BACKEND=cots`, `get_knowledge_base_status` returns a non-zero
   `Total Documents` count matching a direct
   `curl http://localhost:8080/api/v2/tenants/default_tenant/databases/default_database/collections/<id>/count`.
2. On `DB_BACKEND=cots`, `check_knowledge_integrity` executes all four
   sub-checks (no `[SKIP] vector adapter does not expose a metadata sampler`).
3. On `DB_BACKEND=cots`, `list_all_sources --include_gaps` reports a coverage
   percentage > 0% for every collection that has documents present.
4. On `DB_BACKEND=aws`, all three tools produce output byte-identical (modulo
   timestamp) to the pre-change baseline.
5. New adapter contract test passes for both backends.

## 4. Open Questions

- Should `count_documents()` be lazy per-call, or cached per-invocation to
  amortize collection lookups? (Health check calls it 17× in a tight loop.)
- Do we need pagination on `sample_metadata()` for the 60,000+ doc
  collections, or is `limit=50` sufficient forever?
- Does the `mdc-*-mpnet768` collection family need a compatibility shim for
  ChromaDB v2 vs v1 metadata schemas? (Some entries pre-date the v2 cutover.)

## 5. Risks

- Fixing the `Unhealthy` false negative may unmask *real* stale-embedding
  issues that were previously masked by the SKIP. Budget review time for
  triaging Path Consistency findings on first successful run.

## 6. References

- Gap Analysis wiki: `supported_repos/global-workflow.wiki/agentcore-mcp-rag-Gap-Analysis-2026-07-20.md`
- OpenSearch adapter (reference implementation): `mcp_server_python/src/data/opensearch_adapter.py`
- ChromaDB adapter (to be extended): `mcp_server_python/src/data/chromadb_adapter.py`
- Backend selector: `mcp_server_python/src/data/backend_selector.py`
