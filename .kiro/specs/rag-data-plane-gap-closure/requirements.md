# Requirements Document

## Introduction

This feature is the Kiro-spec realization of **SDD Phase 68 — RAG Data-Plane Gap
Closure & Tenant-Scope Clarification**
(`sdd_framework/workflows/phase68_rag_data_plane_gap_closure.md`). It is the
**first incremental step** toward getting the multi-tenant / multi-form-factor
RAG system back to full speed after the Phase 67 rename and the COTS re-ingest
PoC.

The 2026-07-09 full-mode health run on the COTS host surfaced eight concrete gaps
in the RAG data plane. Most are small code fixes (two Phase-67 path-rename leaks,
a missing ChromaDB metadata-sampler interface, a document-count reporting bug).
The critical finding is architectural: the manifest and tenant catalog conflate
two independent concerns and encode no principle to keep them apart —

> **Documentation is NWS-wide and belongs in a single shared embedding space.
> Tenants exist to give an LLM code-base awareness across multiple workflow
> branches — and, in future, across repos outside the global-workflow umbrella.
> Docs are NOT tenant-scoped.**

This spec makes that principle machine-readable (a required `scope: tenant |
shared` field on every manifest source, honored by the re-ingest Work_Matrix
builder), fixes the health-run gaps, and feeds two naming/matrix decisions into
the in-flight `cots-reingest-ralph-framework` spec so the next loop iteration uses
corrected collection names and a smaller (58-unit) matrix.

**This phase is spec + minor code fixes only. No re-ingest runs here.** The heavy
lifting stays in `cots-reingest-ralph-framework`. This work unblocks and clarifies
it.

### Relationship to sibling specs

- **Consumes**: Phase 67 rename (commit `c15080f`, merged to `develop`);
  `cots-reingest-ralph-loop` (PoC, superseded).
- **Feeds**: `cots-reingest-ralph-framework` — this spec's Requirement 3
  (collection naming) is the authoritative source for that spec's Task 2.3, and
  Requirement 2 (scope-aware matrix) shrinks its Task 5 matrix from 62 → 58 units.

## Glossary

- **Manifest**: The Source-of-Production-Truth declaration of every ingestion
  source. On disk: `mcp_server_python/src/config/unified_manifest.json`,
  generated from the `KNOWN_SOURCES` table in
  `mcp_server_python/scripts/generate_unified_manifest.py`; modeled by
  `SourceEntry` / `UnifiedManifest` in `mcp_server_python/src/manifest/models.py`.
- **Source_Type**: The `SourceType` enum — `url_crawl`, `on_disk_submodule`,
  `code_parse`, `config_parse`, `standards`, `community_summary`, `jjob_docs`.
- **Scope**: The new required manifest/stage field — `tenant` or `shared` —
  declaring whether a source's content is per-branch (tenant) or NWS-wide
  (shared).
- **Shared_Scope**: A source/stage whose content is identical for every tenant
  (docs, EE2 standards, general community summaries) → one embedding space, one
  ingest, an **unprefixed** collection name.
- **Tenant_Scope**: A source/stage whose content is per (repo, branch) pair
  (code, jjobs, derived graph labels) → a **tenant-prefixed** collection name and
  N units in the Work_Matrix.
- **Work_Matrix**: The `(tenant, stage)` unit set built by
  `mcp_server_python/scripts/reingest_state.py` from `tenants.yaml` ×
  `reingest_stages.yaml`.
- **Collection_Namer**: The single scope-aware function
  `resolve_collection_name(source, tenant, version)` that all ingesters, the
  reset tool, and the matrix builder use to derive a collection name.
- **Collection_Version**: The optional version suffix (e.g. `v9-0-0`); the
  default (serving) version drops the suffix so serving names are stable.
- **Path_Leak**: A remaining hard-coded `supported_repos/global-workflow[_develop]`
  path in a tool that should instead resolve the active tenant's
  `ctx.tenant.workflow_root`.
- **Metadata_Sampler**: The `sample_metadata(collection, n)` interface the
  integrity tools call to read document metadata; currently absent on the
  ChromaDB adapter, forcing two integrity checks to `[SKIP]`.
- **Framework_Spec**: `.kiro/specs/cots-reingest-ralph-framework/` — the in-flight
  spec that executes the actual re-ingest and consumes this phase's decisions.
- **Two_Axis_Tenant_Model**: The idea that a tenant is any `(repo, branch)` pair
  the LLM should be code-aware of — global-workflow branches today, arbitrary
  external repos (e.g. `parallel-works-mcp`, `nceplibs`) tomorrow.

## Requirements

### Requirement 1: Manifest declares a required `scope` field

**User Story:** As a platform maintainer, I want every manifest source to declare
`tenant` or `shared` scope so the system encodes — rather than assumes — which
content is per-branch and which is NWS-wide.

#### Acceptance Criteria

1. THE `SourceEntry` model SHALL treat `scope` as a required common field whose
   only valid values are `tenant` and `shared`.
2. WHEN `SourceEntry.from_dict` receives an entry missing `scope` or carrying any
   value other than `tenant`/`shared`, THE deserializer SHALL raise a `ValueError`
   naming the offending source and field.
3. THE `SourceEntry.to_dict` output SHALL include `scope` in the stable common-field
   ordering so regenerated manifests stay diffable.
4. THE `KNOWN_SOURCES` generator table SHALL assign `scope` to all 67 current
   sources per the classification: `on_disk_submodule`, `url_crawl`, `standards`,
   `community_summary` → `shared`; `code_parse`, `config_parse`, `jjob_docs` →
   `tenant`.
5. THE regenerated `unified_manifest.json` SHALL carry `scope` on every source,
   and the manifest version SHALL be bumped for the schema change with a dated
   note.

### Requirement 2: Work_Matrix builder honors `scope`

**User Story:** As an operator, I want shared content ingested once (not once per
tenant) so the doc embedding space is not duplicated 5× and recall is not split.

#### Acceptance Criteria

1. WHEN `reingest_state.py init` builds the Work_Matrix, THE builder SHALL emit
   exactly **one** unit for each `shared`-scope stage (tenant field `__global__`)
   and **N** units for each `tenant`-scope stage (one per catalog tenant).
2. THE `documentation` stage SHALL be reclassified `shared` (moved to a shared
   stage), so for the current 5-tenant catalog the matrix produces **58 units**
   (55 tenant-scoped + 3 shared: `documentation`, `ee2_standards`,
   `community_summaries`), down from 62.
3. WHEN `init` runs against an existing pre-scope state file, THE builder SHALL
   preserve the `status` of every unit already in a terminal state (`done`,
   `skipped`, `blocked`) and SHALL only add/regenerate non-terminal units.
4. THE previously-per-tenant `documentation` units SHALL collapse to the single
   shared unit WITHOUT discarding the PoC partial write (2,518 docs already in the
   shared `mdc-workflow-docs-*` collection is a valid starting checkpoint).
5. THE same-tenant `depends_on` gating SHALL continue to apply to tenant-scoped
   stages; shared stages SHALL have no tenant coupling.

### Requirement 3: Scope-aware collection naming (single resolver)

**User Story:** As a developer, I want one function that derives every collection
name so ingesters, the reset tool, and the matrix agree on names.

#### Acceptance Criteria

1. THE Collection_Namer `resolve_collection_name(source, tenant, version)` SHALL
   return, for `shared` scope, `mdc-{domain}-{profile}{suffix}` (no prefix); and
   for `tenant` scope, `{tenant.index_prefix}mdc-{domain}-{profile}{suffix}`.
2. THE version suffix SHALL be empty when `version` is the default serving version
   and `-{version}` otherwise, so serving collection names are stable.
3. THE `write_vector_doc` helper, the four v8 ingesters
   (`documentation`/`code`/`jjobs`/`config_files`), and `reset_tenant_cots.py`
   SHALL derive collection names through `resolve_collection_name` rather than
   ad-hoc string construction.
4. WHERE a shared source is resolved for any tenant, THE resulting name SHALL be
   the unprefixed name regardless of the tenant argument.
5. THE decision recorded here SHALL be the authoritative input to Framework_Spec
   Task 2.3.

### Requirement 4: Phase-67 path-rename leak fix

**User Story:** As an operator, I want `workflow_info` and the integrity
coverage-gap check to work on every tenant, not just fail against a stale path.

#### Acceptance Criteria

1. THE `workflow_info` module SHALL resolve its workflow root from
   `ctx.tenant.workflow_root` (the default tenant resolving to
   `.pw_workflow_mount/develop`) instead of a hard-coded
   `supported_repos/global-workflow[_develop]` path.
2. THE `check_knowledge_integrity` coverage-gap check SHALL use the same
   tenant-resolved root instead of a hard-coded path.
3. WHEN `mcp_health_check --functional` runs after the fix, THE `workflow_info`
   probe SHALL report `[OK] pass` rather than `[SKIP]`.
4. WHEN `check_knowledge_integrity` runs after the fix, THE coverage-gap check
   SHALL execute rather than emit `[SKIP] no Fortran files found in
   supported_repos/global-workflow`.

### Requirement 5: ChromaDB metadata-sampler interface

**User Story:** As an operator on COTS, I want the integrity `Path Consistency`
and `Stale Embeddings` checks to actually run against ChromaDB.

#### Acceptance Criteria

1. THE ChromaDB adapter SHALL expose `sample_metadata(collection, n=20) ->
   list[dict]`, backed by ChromaDB's `get()` with a limit, returning `[]` for an
   empty or missing collection.
2. THE two `check_knowledge_integrity` paths that currently `[SKIP]` with "vector
   adapter does not expose a metadata sampler" SHALL be wired to
   `sample_metadata` and SHALL run.

### Requirement 6: `get_knowledge_base_status` document count

**User Story:** As an operator, I want KB status to report the real document count
so a healthy store isn't reported as empty/unhealthy.

#### Acceptance Criteria

1. THE `get_knowledge_base_status` tool SHALL sum `collection.count()` across the
   applicable collections and report the sum as `Total Documents`.
2. WHEN at least one applicable collection has documents, THE reported status
   SHALL be `[OK] Healthy`; a tenant with zero applicable collections SHALL also
   be reported healthy (a fresh tenant is not "unhealthy").
3. THE tool SHALL NOT report `Total Documents: 0 [ERROR] Unhealthy` when live
   non-empty collections exist.

### Requirement 7: Two-axis tenant model documented

**User Story:** As a future onboarding engineer, I want a worked example for
adding a non-global-workflow tenant so the scope model is actionable.

#### Acceptance Criteria

1. THE steering docs SHALL gain a worked example ("adding a non-global-workflow
   tenant") walking through, e.g., a `pw_mcp` tenant pointing at
   `supported_repos/parallel-works-mcp` on branch `main`.
2. THE docs SHALL clarify that `workflow_subdir` is a repo-relative anchor (not
   necessarily a global-workflow branch checkout), requiring no `tenants.yaml`
   schema change — only naming/convention.

### Requirement 8: Feed decisions into the framework spec

**User Story:** As the maintainer of the re-ingest loop, I want this phase's
decisions recorded where the loop will read them.

#### Acceptance Criteria

1. THE Framework_Spec `progress.md` SHALL gain Corrections / Codebase-Patterns
   entries stating the shared-vs-tenant collection-naming rule, unblocking its
   Task 2.3.
2. THE Framework_Spec `design.md` SHALL gain a short note pointing at this phase
   for the scope model and at Requirement 3 for the collection namer.

### Requirement 9: AWS serving path unchanged

**User Story:** As an operator of the AWS deployment, I want this COTS-focused
gap-closure to leave OpenSearch/Neptune serving names and behavior untouched.

#### Acceptance Criteria

1. THE feature SHALL NOT change OpenSearch index names, Neptune label naming, or
   the AgentCore runtime; the scope/naming changes SHALL be additive and MUST NOT
   alter the currently-serving AWS collection resolution.

### Requirement 10: Verification pass

**User Story:** As a reviewer, I want objective proof the gaps are closed.

#### Acceptance Criteria

1. WHEN `mcp_health_check --deep --detailed --functional` runs, THE result SHALL
   show 11/11 pass with no remaining `[SKIP]` except the optional
   `community_summaries` (Gap J).
2. WHEN `check_knowledge_integrity` runs, THE result SHALL show all four checks
   executing (no `[SKIP]`).
3. WHEN `get_knowledge_base_status` runs, THE result SHALL show `Total Documents
   > 0` and status `[OK]`.
4. WHEN `list_all_sources --include_gaps` runs, THE result SHALL show a `scope` on
   every source and the collection gap-detector rows using the corrected
   (shared/tenant) names.

### Requirement 11: Boundaries and safety

**User Story:** As a maintainer, I want this phase's limits codified so it stays
the small, safe first step it is intended to be.

#### Acceptance Criteria

1. THE feature SHALL NOT execute any re-ingest; the 44 pending units + partial
   `documentation` resume remain under the Framework_Spec.
2. THE feature SHALL NOT graph-version-stamp `shell_graph`/`fortran_graph`/
   `config`/`rocoto`/`bridge` (that is Framework_Spec Task 2.2), refresh
   URL-crawl staleness (that is `url-crawl-gap-closure`/Phase 58), perform the
   serving-collection cutover (Framework_Spec Task 7), or remove the
   `phase48-scratch` collection.
3. THE feature SHALL NOT commit or push automatically; work is staged for human
   review per `.kiro/steering/08-git-operation-policy.md`.

### Requirement 12: COTS execution environment (kiro-cli engagement)

**User Story:** As the operator engaging kiro-cli on the COTS host for this gap
closure, I want the spec to encode the real COTS runtime so the session executes
and verifies against the correct stores.

#### Acceptance Criteria

1. THE engagement SHALL run via `kiro-cli` on the COTS host under the
   `DB_BACKEND=cots` environment established by `run_mcp_stdio.sh` (ChromaDB
   `localhost:8080`, Neo4j `bolt://localhost:7687`,
   `MCP_EMBEDDING_PROFILE=mpnet768`, `MCP_WORKFLOW_MOUNT=.pw_workflow_mount`).
2. THE code changes SHALL be validated against the live COTS stores (the
   2026-07-09 facts: ~15 ChromaDB collections; Neo4j ≈343,363 nodes / ≈4,220,211
   rels; GDS 2.13.7 present; `mpnet768` embeddings functional) — the same stores
   the COTS MCP server serves.
3. THE engagement SHALL NOT depend on the remote `eib-mcp-gateway` (Docker MCP
   Gateway via dev tunnel), which is currently **blocked** (speculative, awaiting
   support confirmation), nor on the AWS-targeting `agentcore-mcp-rag` /
   `eib-mcp-rag-full` MCP runtime.
4. WHERE a code change touches a serving-path module (manifest model,
   `workflow_info`, `semantic_search`, `chromadb_adapter`), a config/state
   snapshot SHALL be captured before the change (no data mutation occurs — this
   phase runs no ingest — but the COTS MCP server reads these modules live).

### Requirement 13: COTS-truthful verification

**User Story:** As a reviewer, I want the health / integrity / status probes to
reflect the COTS stores, because the MCP tools otherwise report the AWS backend.

#### Acceptance Criteria

1. THE verification probes (`mcp_health_check`, `check_knowledge_integrity`,
   `get_knowledge_base_status`, `list_all_sources`) SHALL be executed against the
   COTS backend via a **COTS-local stdio MCP server** launched with
   `DB_BACKEND=cots` (`run_mcp_stdio.sh`) and registered as a temporary MCP server
   in the kiro-cli session config, so the probes exercise the real tool code path
   against ChromaDB + Neo4j. An in-process tool call under `DB_BACKEND=cots` is a
   permitted fallback ONLY if the stdio server cannot be stood up.
2. THE verification SHALL NOT be considered satisfied by results from the
   AWS-backed `agentcore-mcp-rag` runtime or the blocked remote gateway.
3. THE verification SHALL record, in the engagement `progress.md`, which method
   was used and the concrete COTS store counts observed before and after.

### Requirement 14: Resumable, self-governed engagement

**User Story:** As the operator, I want the kiro-cli engagement to be resumable
and to carry forward PoC learnings so it does not repeat known mistakes.

#### Acceptance Criteria

1. THE engagement SHALL track progress in a durable `progress.md` in this spec
   directory (Corrections + Codebase-Patterns + a progress log), pre-seeded with
   the PoC learnings relevant to this phase.
2. THE engagement SHALL run as an SDD-tracked session (start / record step /
   complete) so a disconnect resumes from the recorded task state.
3. THE engagement SHALL honor `.kiro/steering/08-git-operation-policy.md`
   (no auto-commit, no auto-push); all changes staged for human review.
4. WHERE the work is bounded local code fixes (no ingest, no heavy embedding), it
   SHALL run **inline on the head node** and SHALL NOT use the Slurm dispatch
   layer that `cots-reingest-ralph-framework` uses for heavy stages.

### Requirement 15: EXPDIR is realtime, tenant-derived, and tenant-localized

**User Story:** As the maintainer, I want EXPDIR treated as the runtime,
per-experiment, per-tenant data it actually is — with a tenant-derived source
path — so its tenant scope stops relying on write-time label prefixing alone and
its manifest entry stops mis-describing where the data comes from.

**Context (the crept-in seam).** "expdir" names two different things: the manifest
`expdir-configs` source (a `config_parse`) declares `config_root: …/parm/config`
(static repo templates), but the actual ingester `ingest_expdir_configs_v8.py`
reads a **separate runtime tree** `supported_repos/EXPDIR` (materialized
experiment directories — pslot, resolution, resolved `config.*` + Rocoto XML).
`resolve_expdir_base(tenant)` currently **ignores its tenant argument** (single
fixed path unless `MCP_EXPDIR_BASE_OVERRIDE` is set), so tenant isolation exists
only via the write-time graph label prefix. In practice EXPDIR is materialized
only for **gw and gw_v17**.

#### Acceptance Criteria

1. THE manifest `expdir-configs` source SHALL remain `scope: tenant` AND SHALL be
   annotated as **realtime / runtime-materialized** (a materialized experiment
   directory), distinct from static `config_parse` repo templates.
2. THE `expdir-configs` source base SHALL reflect the **runtime EXPDIR tree** that
   `ingest_expdir_configs_v8.py` reads (not the repo `parm/config`), resolving the
   current `config_root` inconsistency.
3. THE `resolve_expdir_base(tenant)` function SHALL derive the EXPDIR base from the
   **active tenant** (a per-tenant base) rather than returning a single fixed path;
   `MCP_EXPDIR_BASE_OVERRIDE` SHALL remain the explicit per-run override. The exact
   per-tenant base mapping SHALL be **confirmed against COTS** (which EXPDIR trees
   exist — currently gw and gw_v17) before implementation.
4. WHERE a tenant has no materialized EXPDIR, THE `expdir` and `rocoto` stages
   SHALL `skip` with a reason (not fail), and the resolver SHALL report an **absent
   base** rather than falling back to another tenant's tree.
5. THE write-side tenant isolation (graph label prefix `{prefix}Experiment` /
   `{prefix}EXPDIRConfig`) SHALL be preserved unchanged; this phase adds
   **source-side** tenant derivation only.
6. THE realtime + tenant-localized (gw, gw_v17) nature of EXPDIR SHALL be
   documented (steering + `progress.md` Correction) so the distinction from static
   repo config is durable.
