# Implementation Plan: RAG Data-Plane Gap Closure & Tenant-Scope Clarification

## Overview

Kiro-spec realization of SDD Phase 68 — the first incremental step back to full
speed. Spec + minor code fixes only; **no re-ingest runs here**. Adds a required
`scope: tenant | shared` field to the manifest and honors it in the Work_Matrix
builder and collection namer; fixes the two Phase-67 path leaks, the missing
ChromaDB metadata sampler, and the KB-status count; documents the two-axis tenant
model; and feeds naming/matrix decisions into `cots-reingest-ralph-framework`.

Groups: schema + matrix + namer (Tasks 1–3) are the durable core; the health-run
fixes (Tasks 4–6) are independent and can proceed in parallel; docs + framework
feed + verification + staging (Tasks 7–10) close it out. All changes are staged
for human review — no commit, no push. Sub-tasks marked `*` are test-only and may
be skipped to ship faster.

## Tasks

- [ ] 0. Engagement kickoff (COTS, gated prerequisites)
  - [ ] 0.1 Confirm the COTS runtime: `kiro-cli` present + `--no-interactive`
    works; ChromaDB `:8080` and Neo4j `:7687` reachable; `mpnet768` provider
    imports and embeds (ignore the false "sentence-transformers not installed"
    warning); GDS present. Source the `DB_BACKEND=cots` env from `run_mcp_stdio.sh`
    - _Requirements: 12.1, 12.2_
    - _Tag: research_
  - [ ] 0.2 Stand up the COTS-truthful verification path: launch the COTS-local
    stdio MCP server (`run_mcp_stdio.sh`, `DB_BACKEND=cots`) and register it as a
    temporary MCP server in the kiro-cli session config; smoke-test one probe
    (e.g. `get_server_info` / `get_knowledge_base_status`) and prove it reports the
    COTS stores — NOT the AWS `agentcore-mcp-rag`, NOT the blocked
    `eib-mcp-gateway`. In-process call under `DB_BACKEND=cots` is the fallback only
    - _Requirements: 13.1, 13.2_
    - _Tag: configure_
  - [ ] 0.3 Seed `progress.md` (Corrections + Codebase-Patterns from the PoC) and
    start the SDD session for this phase
    - _Requirements: 14.1, 14.2_
    - _Tag: configure_
  - [ ] 0.4 Snapshot serving-path module state and record baseline COTS counts
    (`get_knowledge_base_status`, `check_knowledge_integrity`) into `progress.md`
    - _Requirements: 12.4, 13.3_
    - _Tag: configure_

- [ ] 1. Manifest schema — add `scope` field
  - [ ] 1.1 Extend the manifest model: `scope` is a required common field in
    `SourceEntry` (`src/manifest/models.py`); `from_dict` rejects missing `scope`
    and any value other than `tenant`/`shared` with a `ValueError` naming the
    source; `to_dict` emits `scope` in stable order; add `"scope"` to the
    `common_keys` set so it isn't swept into `type_fields`
    - _Requirements: 1.1, 1.2, 1.3_
  - [ ] 1.2 Classify all 67 sources in `generate_unified_manifest.py`
    `KNOWN_SOURCES` (`shared`: url_crawl, on_disk_submodule, standards,
    community_summary; `tenant`: code_parse, config_parse, jjob_docs) via a small
    `_default_scope(source_type)` helper; regenerate `unified_manifest.json`
    - _Requirements: 1.4, 1.5_
  - [ ] 1.3 Bump the manifest version for the schema change; dated note
    - _Requirements: 1.5_
    - _Tag: document_
  - [ ]* 1.4 Unit test: schema round-trip; missing `scope` raises; unknown value raises
    - _Requirements: 1.1, 1.2_

- [ ] 2. Work_Matrix builder respects `scope`
  - [ ] 2.1 Add `scope` to `reingest_stages.yaml` stages; reclassify
    `documentation` as shared; tag `ee2_standards` / `community_summaries` shared,
    all other per-tenant stages `tenant`. In `reingest_state.py` matrix build,
    emit one `__global__` unit per shared stage and N units per tenant stage
    - _Requirements: 2.1, 2.2, 2.5_
  - [ ] 2.2 Verify idempotent migration: a pre-scope `state.json` preserves
    terminal (`done`/`skipped`/`blocked`) statuses; the five per-tenant
    `documentation` units collapse to one shared unit without discarding the PoC
    partial (2,518-doc) checkpoint
    - _Requirements: 2.3, 2.4_
  - [ ] 2.3 Regenerate `PROGRESS.md`; confirm the 5→1 `documentation` collapse and
    the 58-unit total for the current catalog
    - _Requirements: 2.2_
  - [ ]* 2.4 Unit test: builder yields exactly 55 tenant + 3 shared from a fixture
    catalog + stages
    - _Requirements: 2.1, 2.2_
  - [ ]* 2.5 Unit test: migration from a pre-scope state preserves terminal
    statuses; only regenerates non-terminal units
    - _Requirements: 2.3_

- [ ] 3. Scope-aware collection namer (feeds Framework Task 2.3)
  - [ ] 3.1 Define `resolve_collection_name(source, tenant, version)` in
    `mcp_server_python/src/data/collection_namer.py` — shared →
    `mdc-{domain}-{profile}{suffix}`, tenant →
    `{tenant.index_prefix}mdc-{domain}-{profile}{suffix}`, suffix empty for the
    default serving version
    - _Requirements: 3.1, 3.2, 3.4_
  - [ ] 3.2 Route `_ingest_common.write_vector_doc`, the four v8 ingesters, and
    `reset_tenant_cots.py` through `resolve_collection_name` (existing
    `versioned_collection_name` delegates to it); preserve default serving names
    byte-for-byte
    - _Requirements: 3.3, 9.1_
  - [ ]* 3.3 Unit test: 8 cases across (shared|tenant) × (default|explicit ver) ×
    (empty|non-empty prefix)
    - _Requirements: 3.1, 3.2, 3.4_

- [ ] 4. Phase-67 path-rename leak fix
  - [ ] 4.1 `workflow_info` — resolve the workflow root from
    `ctx.tenant.workflow_root` (default → `.pw_workflow_mount/develop`) instead of
    the hard-coded `supported_repos/global-workflow_develop`; keep env/`HOMEgfs`
    fallbacks for out-of-context startup
    - _Requirements: 4.1_
  - [ ] 4.2 `check_knowledge_integrity` coverage-gap check (`_resolve_repo_base`) —
    same tenant-resolved substitution
    - _Requirements: 4.2_
  - [ ]* 4.3 Functional assertion: `workflow_info` returns `[OK] pass` in
    `mcp_health_check --functional`
    - _Requirements: 4.3, 4.4_

- [ ] 5. ChromaDB adapter — `metadata_sampler`
  - [ ] 5.1 Add `sample_metadata(collection, n=20) -> list[dict]` to the ChromaDB
    adapter (ChromaDB `get()` with a limit; `[]` on empty/missing)
    - _Requirements: 5.1_
  - [ ] 5.2 Wire the two `check_knowledge_integrity` `[SKIP]` paths (Path
    Consistency, Stale Embeddings) to `sample_metadata`
    - _Requirements: 5.2_
  - [ ]* 5.3 Unit test: 3-doc mock returns 3; empty returns `[]`
    - _Requirements: 5.1_

- [ ] 6. `get_knowledge_base_status` — fix document count
  - [ ] 6.1 Sum `collection.count()` across applicable collections; report the sum
    as `Total Documents`
    - _Requirements: 6.1, 6.3_
  - [ ] 6.2 Status `[OK] Healthy` when count > 0 OR the tenant has zero applicable
    collections
    - _Requirements: 6.2_
  - [ ]* 6.3 Unit test with a mocked adapter returning 3 collections × N docs
    - _Requirements: 6.1_

- [ ] 7. Tenant catalog — document the two-axis model
  - [ ] 7.1 Add a worked "adding a non-global-workflow tenant" example in
    `.kiro/steering/11-tenant-roadmap.md` (e.g. `pw_mcp` →
    `supported_repos/parallel-works-mcp`, branch `main`)
    - _Requirements: 7.1_
    - _Tag: document_
  - [ ] 7.2 Clarify that `workflow_subdir` is a repo-relative anchor, not a
    global-workflow branch checkout — no `tenants.yaml` schema change
    - _Requirements: 7.2_
    - _Tag: document_

- [ ] 8. Framework spec cross-references
  - [ ] 8.1 Add Corrections / Codebase-Patterns entries to
    `cots-reingest-ralph-framework/progress.md` for the shared-vs-tenant naming
    rule (unblocks its Task 2.3)
    - _Requirements: 8.1_
    - _Tag: document_
  - [ ] 8.2 Add a two-line note to `cots-reingest-ralph-framework/design.md`
    pointing at this phase (scope model) and Requirement 3 (namer)
    - _Requirements: 8.2_
    - _Tag: document_

- [ ] 9. EXPDIR — realtime, tenant-derived source reconciliation
  - [ ] 9.1 Reconcile the manifest `expdir-configs` source: keep `scope: tenant`,
    annotate it realtime/runtime-materialized (distinct from static `config_parse`),
    and point its source base at the runtime EXPDIR tree that
    `ingest_expdir_configs_v8.py` reads (not `parm/config`); regenerate the manifest
    - _Requirements: 15.1, 15.2_
  - [ ] 9.2 Make `resolve_expdir_base(tenant)` tenant-derived — a per-tenant EXPDIR
    base (exact mapping confirmed from COTS; gw / gw_v17 today) with
    `MCP_EXPDIR_BASE_OVERRIDE` as the explicit override; an absent base returns
    "no EXPDIR" rather than another tenant's tree
    - _Requirements: 15.3, 15.4_
  - [ ] 9.3 Confirm `expdir`/`rocoto` `skip` (not fail) for tenants with no
    materialized EXPDIR; keep the write-side `{prefix}Experiment` /
    `{prefix}EXPDIRConfig` labeling unchanged
    - _Requirements: 15.4, 15.5_
  - [ ] 9.4 Document the realtime + tenant-localized (gw, gw_v17) nature in steering
    and record the EXPDIR base mapping + Correction in `progress.md`
    - _Requirements: 15.6, 14.1_
    - _Tag: document_
  - [ ]* 9.5 Unit test: `resolve_expdir_base` returns per-tenant bases; absent base
    → skip signal; `MCP_EXPDIR_BASE_OVERRIDE` respected
    - _Requirements: 15.3_

- [ ] 10. Verification pass (COTS-truthful — via the Task 0.2 method, NOT AWS/gateway)
  - [ ] 10.1 `mcp_health_check --deep --detailed --functional` → 11/11 pass, no
    SKIP except optional `community_summaries`; `workflow_info` now `[OK] pass`
    - _Requirements: 10.1, 13.1, 13.2_
    - _Tag: validate_
  - [ ] 10.2 `check_knowledge_integrity` → 4/4 checks run (no SKIP for the metadata
    sampler or the coverage-gap path)
    - _Requirements: 10.2, 13.1_
    - _Tag: validate_
  - [ ] 10.3 `get_knowledge_base_status` → `Total Documents > 0` (matching the ~15
    live COTS collections), status `[OK]`
    - _Requirements: 10.3, 13.1_
    - _Tag: validate_
  - [ ] 10.4 `list_all_sources --include_gaps` → every source has a scope; gap-
    detector rows show corrected (shared/tenant, profile-derived) names, and
    `expdir-configs` shows its realtime EXPDIR base
    - _Requirements: 10.4, 15.2_
    - _Tag: validate_
  - [ ] 10.5 Regression: run the `reingest_state` + ingester unit suites and record
    the before/after COTS counts in `progress.md`; confirm default serving
    collection names are byte-for-byte unchanged
    - _Requirements: 9.1, 13.3_
    - _Tag: validate_

- [ ] 11. Commit staging (no push)
  - [ ] 11.1 Add a dated `[Unreleased]` CHANGELOG entry (scope schema change, the
    EXPDIR realtime/tenant-derived reconciliation, two leak fixes, adapter
    interface, KB-status fix, framework cross-reference); stage all changes; leave
    for human review
    - _Requirements: 11.3_
    - _Tag: document_

## Notes

- The durable value is the tenant-vs-shared scope principle — it stops the next N
  tenants (global-workflow branches or external repos) from duplicating the doc
  embedding space by default.
- The manifest SPOT is `generate_unified_manifest.py::KNOWN_SOURCES` →
  `unified_manifest.json` (not a hand-edited YAML); the model lives in
  `src/manifest/models.py`.
- Default (serving) collection names must stay byte-for-byte unchanged (R9); the
  namer's version suffix is empty for the default version. The live ChromaDB doc
  collections are ALREADY unprefixed — this aligns the ingester with reality.
- This phase runs no ingest and touches no AWS resource; the actual re-ingest and
  cutover remain in `cots-reingest-ralph-framework`. Commits/pushes are
  human-gated (`08-git-operation-policy.md`).
- **Executed by kiro-cli on COTS, inline on the head node** (no Slurm — this is
  bounded local code work). Track progress in this spec's `progress.md`
  (Corrections + Codebase-Patterns + log); run as an SDD session so a disconnect
  resumes from the recorded task.
- **Verification must be COTS-truthful** (Task 0.2 method): the `agentcore-mcp-rag`
  / `eib-mcp-rag-full` MCP reports the **AWS** backend and `eib-mcp-gateway` is the
  **blocked** dev tunnel — neither reflects the COTS stores. A green check against
  AWS proves nothing here.
- Task 0 gates the rest; Task 3 (namer) is the authoritative hand-off to
  `cots-reingest-ralph-framework` Task 2.3.
- Task 9 (EXPDIR) closes the "crept-in" scope seam: EXPDIR is **realtime**,
  tenant-derived, and tenant-localized to **gw + gw_v17**. Task 9.2's exact
  per-tenant base mapping is confirmed from COTS first (see the EXPDIR base table
  in `progress.md`); the manifest base is reconciled to the runtime EXPDIR tree,
  not `parm/config`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["0.1", "0.2", "0.3", "0.4"] },
    { "id": 1, "tasks": ["1.1"] },
    { "id": 2, "tasks": ["1.2", "1.4", "4.1", "4.2", "5.1", "6.1", "9.2"] },
    { "id": 3, "tasks": ["1.3", "2.1", "3.1", "4.3", "5.2", "5.3", "6.2", "6.3", "7.1", "7.2", "9.1", "9.4"] },
    { "id": 4, "tasks": ["2.2", "3.2", "9.3", "9.5"] },
    { "id": 5, "tasks": ["2.3", "2.4", "2.5", "3.3", "8.1", "8.2"] },
    { "id": 6, "tasks": ["10.1", "10.2", "10.3", "10.4", "10.5"] },
    { "id": 7, "tasks": ["11.1"] }
  ]
}
```
