# Requirements Document

## Introduction

Phase 79 (`shared-scope-query-routing`) made shared and tenant-prefixed
collections reachable from the read path, and Phase 80
(`default-tenant-freeze-retirement`) retired the byte-equivalence freeze that
Phase 79 leaned on. In the same window two Neptune-compatibility fixes landed on
the graph side: the APOC-free name predicate
(`toLower(toString(n.name)) CONTAINS toLower($baseName)`) in
`ggsr_traversal.py` / `graph_rag.py`, and the graph-enrichment query rewrite
from OR-disjunction to `UNION ALL` (Phase 79 R15.3 amendment).

Those fixes were code-only. **The corpus underneath them is stale, partial, and
tenancy-inconsistent.** Live `get_knowledge_base_status` (2026-08-28) shows the
COTS backend serving fifteen physical vector collections split across two
generations (v8-0-0 / v8-1-0 / v8-2-0 alongside the `mpnet768` clones), the
tenant `gw` populated end-to-end, and every other tenant partially built or
untouched. The unified manifest reports two large gaps against declared totals
(`code-with-context-v8-0-0` at 67.2 %, `global-workflow-docs-v8-0-0` at 63.0 %)
and one small gap (`jjobs-v8-0-0` at 93.2 %), with five sources declared but
never ingested and five source PDFs marked stale.

This feature drives a **full, resumable, tenant-aware, mpnet768 re-ingest of
vector *and* graph across all five tenants on the COTS backend**, using the
Ralph-loop pattern established by `cots-reingest-ralph-loop`. The re-ingest
targets a fresh `Collection_Version` built alongside the currently-serving
collections (no in-place mutation until a human-gated cutover), populates
shared-scope collections **once** unprefixed and tenant-scope collections
per-tenant prefixed (respecting the Phase 79 authority table), and rebuilds the
Neo4j graph indexes from a clean state so the query planner is not sitting on
five months of accreted plan hints.

### Empirically confirmed current state

Live `get_knowledge_base_status(all_tenants=True)` and `list_all_sources(include_gaps=True)`
against the COTS backend (2026-08-28T19:44Z, manifest v9.2.0):

| Physical collection | Docs | Manifest scope | Gap vs declared |
|---|---:|---|---|
| `mdc-code-context-mpnet768` | 60,576 | tenant (`gw`) | duplicates `code-with-context-v8-0-0` at 67.2 % coverage |
| `code-with-context-v8-0-0` | 60,574 | tenant | **32.8 % short** — 5 sources never ingested |
| `global-workflow-docs-v8-2-0` | 23,624 | shared/hybrid | current serving generation |
| `global-workflow-docs-v8-0-0` | 22,498 | shared/hybrid | **37.0 % short** — 4 sources never, 5 stale PDFs |
| `mdc-workflow-docs-mpnet768` | 22,498 | shared/hybrid | mirrors v8-0-0 gap exactly |
| `global-workflow-docs-v8-1-0` | 20,511 | shared/hybrid | intermediate generation |
| `phase48-scratch` | 3,630 | — | development artefact, not in manifest |
| `community-summaries` / `mdc-community-summaries-mpnet768` | 2,113 / 2,113 | shared | 100 % against declared |
| `jjobs-v8-1-0` / `jjobs-v8-0-0` / `mdc-jjobs-mpnet768` | 859 / 700 / 700 | tenant | v8-0-0 6.8 % short |
| `ci-test-cases-v1-0-0` | 74 | shared | 100 % against declared |
| `ee2-standards-v5-0-0-enhanced` / `mdc-ee2-standards-mpnet768` | 34 / 34 | shared | 100 % against declared |

Graph (Neo4j) — tenant `gw`: 225,836 nodes, 4,051,374 relationships; whole-graph
(all tenants) 344,604 nodes. Every other tenant is empty or partial. The label
prefix scheme (`GW_`, `GW_SFS_`, `GW_JEDI_GFS_`, `GW_V17_`, `GW_GEFS_V12_`)
is in place and the workflow filesystem mount is reachable for all five tenants
(`.pw_workflow_mount/{develop,dev-sfs,dev-jedi-gfs,dev-v17,gefs-v12}`), so
tenant plumbing is not the blocker — content is.

### Three findings that reshape the fix

**1. The mpnet768 clones and the versioned collections are not the same corpus,
and the divergence is silent.** `mdc-code-context-mpnet768` holds 60,576
documents; `code-with-context-v8-0-0` holds 60,574. Two-document differences
are consistent with partial re-runs, not deliberate content divergence. The two
generations serve the same logical scope but neither is authoritative today —
the tooling reads whichever the manifest happens to route to. A re-ingest that
does not converge the two into one canonical `mpnet768` set at a fresh
Collection_Version will preserve the ambiguity.

**2. Three declared sources for `code-with-context` have never ingested at all.**
Not "ingested and stale" — `never: fortran-code-context, shell-code-context,
python-code-context, rocoto-config, expdir-configs` per gap detection. The 67 %
coverage number understates the problem: it is 67 % of *declared* documents, but
declared totals were re-derived after two of those five sources were added to
the manifest, so the actual delta against the intended corpus is larger. A
re-ingest that only re-embeds already-ingested sources will not close this gap.

**3. `global-workflow-docs` is a hybrid domain (Phase 79 finding B, still true).**
The `global-workflow-rst` source is declared `scope: "shared"` yet its content
is repo-local `.rst` under `docs/**` and varies per branch. Phase 79's
`shared-scope-query-routing/design.md` documents the fan-out approach and the
existing v17 physical prefix (`gw_v17_mdc-workflow-docs-titan1024`, 28,459 docs
on the AWS backend). This spec inherits that resolution: the reingest writes the
external-URL portion of `global-workflow-docs` unprefixed once and the
`global-workflow-rst` portion per-tenant. A single-write-per-collection rule
would recreate the Phase 79 blind spot in a fresh generation.

### The graph side

The `graph-rag.py` and `ggsr_traversal.py` cypher predicates now assume built-in
`toString`, not `apoc.text.join`. A re-ingest that leaves the current Neo4j
schema and indexes intact will exercise the fixed predicates against a graph
whose indexes were built for the APOC predicate's access pattern (multi-valued
`name` scan). The user selection is **drop and rebuild Neo4j indexes** as part
of the re-ingest, which is the only option that leaves the graph query planner
in a state consistent with the code that now queries it.

### Scope

**In scope.** COTS backend (ChromaDB + Neo4j on the Rocky 9 Parallel Works
host); all five tenants (`gw`, `gw_sfs`, `gw_jedi_gfs`, `gw_v17`,
`gw_gefs_v12`); shared-scope corpora (community summaries, EE2 standards, CI
test cases, external documentation crawls, PDF sources) ingested once; the two
hybrid domains (`global-workflow-docs` external vs `.rst`, `code-with-context`)
handled per Phase 79's authority table; vector re-embedding at `mpnet768` with a
fresh Collection_Version; Neo4j drop-and-rebuild of indexes and per-tenant graph
re-parse; a CLI-runnable Ralph loop over the work matrix.

**Deliberately deferred.** No AWS backend changes (OpenSearch and Neptune stay
where they are; AWS re-ingest is a separate spec once the COTS pattern is
validated). No embedding-model change (the `bedrock-embedding-reingestion` and
`bedrock-native-embedding-swap` specs cover that pivot; this spec stays on
`mpnet768`). No ingester algorithm changes beyond the missing-source additions
recorded in Requirement 6. No cutover of the read path from the v8 generation
to the fresh v9 generation until Requirement 12.

## Glossary

This spec **inherits** the glossary of
`.kiro/specs/cots-reingest-ralph-loop/requirements.md` — `COTS_Host`,
`Tenant_Catalog`, `Collection_Version`, `Stage`, `Reingest_Unit`, `Work_Matrix`,
`State_File`, `State_Manager`, `Loop_Driver`, `Iteration`, `Iteration_Prompt`,
`Validation_Probe`, `Ground_Truth`, `Ralph_Loop`, `Terminal_State`. Terms
defined only here:

- **Serving_Version**: the Collection_Version currently answering production
  queries. As of 2026-08-28 this is a mixed v8 set (v8-0-0 / v8-1-0 / v8-2-0
  alongside `mpnet768` clones); the spec treats the mixed set as the effective
  Serving_Version for cutover-safety purposes.
- **Target_Version**: the Collection_Version the re-ingest is building. This
  spec fixes it at **`v9-0-0`** for the initial run, applied to every target
  collection name and every graph-node `version` stamp.
- **Shared_Once_Rule**: shared-scope collections write **once** to the
  unprefixed physical name; the read path (post-Phase 79) reaches them from
  every tenant via `Read_Router`. Any per-tenant write to a shared-scope
  collection is a spec violation.
- **Hybrid_Fan_Out**: for `global-workflow-docs` and any future hybrid-scope
  domain, the external portion writes shared-once and the repo-local portion
  writes per-tenant prefixed. The manifest MUST distinguish the two portions
  by source, not by collection.
- **Index_Rebuild_Set**: the Neo4j indexes and constraints dropped and
  recreated at the start of the re-ingest, enumerated in
  `mcp_server_python/scripts/neo4j_index_rebuild.py`.
- **Consumer_Audit**: the enumeration of in-repo callers that parse a
  collection's rendered output, carried forward from Phase 80 §
  Consumer_Audit — this spec extends it with the callers that assume v8
  collection names and would break at cutover.

## Requirements

### Requirement 1: mpnet768 v9-0-0 collections built alongside the v8 generation

**User Story:** As an operator, I want the re-ingest to build a brand-new
`v9-0-0` mpnet768 collection set (vector + graph) without touching the v8
generation, so the current serving path keeps answering queries while I validate
the new corpus.

#### Acceptance Criteria

1. THE re-ingest SHALL target `Target_Version = "v9-0-0"`, applied through
   `CollectionNamer` to every collection name and threaded to every ingester so
   no ingester derives a version string from anywhere else.
2. THE re-ingest SHALL NOT delete, truncate, or rewrite any collection whose
   name matches `code-with-context-v8-*`, `global-workflow-docs-v8-*`,
   `jjobs-v8-*`, `ee2-standards-v5-*-enhanced`, `mdc-*-mpnet768`,
   `community-summaries`, `ci-test-cases-v1-0-0`, or `phase48-scratch` before
   the Requirement 12 cutover gate.
3. THE re-ingest SHALL write mpnet768 embeddings (768-dim, local
   `all-mpnet-base-v2` via `sentence-transformers`), matching the profile the
   COTS gateway image bundles offline at `/app/.hf_cache`.
4. WHERE a v9-0-0 target collection already exists from a previous partial run,
   THE re-ingest SHALL resume against it per the State_File and SHALL NOT
   silently start a v9-0-1 to avoid the resume.

### Requirement 2: Catalog-driven all-tenant work matrix, shared-once respected

**User Story:** As an operator, I want the work matrix generated from the
tenant catalog so every tenant is covered, and I want shared-scope stages to
run exactly once so I do not silently re-embed the shared corpus five times.

#### Acceptance Criteria

1. WHEN the State_Manager initializes the Work_Matrix, THE State_Manager SHALL
   enumerate every tenant in the Tenant_Catalog (currently `gw`, `gw_sfs`,
   `gw_jedi_gfs`, `gw_v17`, `gw_gefs_v12`) and create the ordered
   tenant-scope Stages for each.
2. THE Work_Matrix SHALL include the shared-scope Stages
   (`ee2_standards`, `community_summaries`, `ci_test_cases`, `external_docs`,
   `pdf_sources`) exactly once each, not once per tenant.
3. FOR each Reingest_Unit whose Stage is shared-scope, THE ingester invocation
   SHALL be tenant-blind — no `MCP_DEFAULT_TENANT` override, no
   `--tenant-id` flag — and the resulting physical collection name SHALL be
   unprefixed (Shared_Once_Rule).
4. FOR each Reingest_Unit whose Stage is tenant-scope, THE ingester invocation
   SHALL run under the unit's tenant, and the resulting physical collection
   name SHALL carry the tenant's `index_prefix`.
5. FOR the two Hybrid_Fan_Out domains (`workflow_docs`, `code_with_context`),
   THE Work_Matrix SHALL split the domain into an external-URL sub-stage
   (shared-once) and a repo-local sub-stage (per-tenant), consistent with the
   Phase 79 authority table.

### Requirement 3: Close the five never-ingested sources

**User Story:** As an operator, I want the five declared-but-never-ingested
sources to actually ingest as part of this run, so the resulting corpus
matches the manifest instead of the current 67 % / 63 % coverage.

#### Acceptance Criteria

1. THE re-ingest SHALL execute these nine sources against `Target_Version`:
   `fortran-code-context`, `shell-code-context`, `python-code-context`
   (manifest `source_type: code_parse`, scope `tenant`, `code_with_context`
   domain); `rocoto-config`, `expdir-configs` (manifest `source_type:
   config_parse`, scope `tenant`, materializing into the
   `code_with_context` collection via the config-parse ingester);
   `rocoto`, `cmeps`, `nceplibs-sfcio` (manifest `source_type: url_crawl`,
   scope `shared`, `workflow_docs` external portion); and
   `global-workflow-rst` (manifest `source_type: on_disk_submodule`, scope
   `shared` — the hybrid domain per Finding 3, fanned out per Req 2.5).
2. WHERE a source's ingester does not exist or is a stub, THE re-ingest SHALL
   record the affected Reingest_Unit as `blocked` with a `needs_ingester`
   reason and SHALL NOT mark the parent domain complete.
3. THE five stale PDF sources (`esmf-ref-pdf`, `esmc-ref-pdf`, `nuopc-ref-pdf`,
   `esmpy-pdf`, `nuopc-layer-reference`) SHALL re-crawl and re-embed, and the
   ingester SHALL record the source URL's `Last-Modified` (or content hash if
   the origin does not provide one) into the manifest status writeback.
4. THE post-run gap-detection report SHALL show every source in scope 1-3 above
   as either `ingested` (declared ≤ actual) or `blocked` with a documented
   reason; no source SHALL remain in the `never` bucket.

### Requirement 4: Graph drop-and-rebuild aligned with the merged code

**User Story:** As an operator, I want the Neo4j graph re-parsed with the
indexes dropped and rebuilt cleanly, so the query planner is consistent with
the post-APOC-removal code and the ingested node/relationship counts match a
single run rather than five months of accretion.

#### Acceptance Criteria

1. BEFORE any graph writes, THE re-ingest SHALL drop every index and
   constraint enumerated in the Index_Rebuild_Set via
   `mcp_server_python/scripts/neo4j_index_rebuild.py --drop`, and SHALL
   record the dropped set with schema version and index definitions to
   `.reingest_state/<Target_Version>/neo4j_pre_drop.json`.
2. WHEN a tenant's `fortran_graph`, `python_graph`, and `shell_graph` stages
   have all reached `done`, THE re-ingest SHALL rebuild the same
   Index_Rebuild_Set via
   `neo4j_index_rebuild.py --create` and SHALL confirm each index reports
   `state = ONLINE` via `SHOW INDEXES` before marking the tenant's graph
   stages complete.
3. THE re-ingest SHALL NOT touch labels or relationships whose label prefix
   does not match a tenant in the current Tenant_Catalog (no orphan
   sweeping in this spec — that is a separate maintenance task).
4. THE post-run `get_knowledge_base_status(all_tenants=True)` SHALL report
   non-zero node counts under each of the five tenant `label_prefix`
   families, and the whole-graph total SHALL exceed the current 344,604
   (single-tenant `gw` today) by at least the sum of the four other
   tenants' Ground_Truth expected node counts.

### Requirement 5: Post-Phase-79 read-path verification per tenant

**User Story:** As an operator, I want the re-ingest to prove that each
tenant reaches its own tenant-scope content **and** the shared-once content
from a single query, so the Phase 79 fix is confirmed live against the fresh
corpus.

#### Acceptance Criteria

1. FOR each tenant, THE Validation_Probe SHALL run these four MCP tool calls
   scoped to that tenant, and each SHALL return a non-zero, non-empty hit
   set:
   - `search_documentation(query=<tenant-specific ground-truth phrase>, tenant_id=<tenant>)`
     — proves tenant-scope workflow-docs is reachable.
   - `search_ee2_standards(query="err_chk err_exit", tenant_id=<tenant>)`
     — proves shared-once EE2 is reachable from a non-default tenant.
   - `search_architecture(query="workflow driver", tenant_id=<tenant>)`
     — proves shared-once community-summaries is reachable.
   - `get_code_context(symbol=<tenant Ground_Truth symbol>, tenant_id=<tenant>)`
     — proves tenant-scope code-with-context + graph enrichment
     (`toString`-based predicate, post-APOC) both fire.
2. `_smoke_branch_isolation`'s Phase 79-realigned assertion 4 SHALL pass on
   every tenant after the re-ingest — shared-scope content reaching a
   non-default tenant is expected behaviour, not an isolation violation.
3. THE Validation_Probe results SHALL be recorded per-tenant to
   `.reingest_state/<Target_Version>/validation/<tenant>.json` with the
   full request/response payload, and the presence of these files SHALL
   be the Requirement 12 cutover gate's precondition.

### Requirement 6: Adds against `cots-reingest-ralph-loop` are additive, not replacing

**User Story:** As a maintainer, I want this spec to build on
`cots-reingest-ralph-loop` rather than replace it, so we do not fork the
State_Manager / Loop_Driver / Iteration_Prompt into two competing
implementations.

#### Acceptance Criteria

1. THE re-ingest SHALL reuse `mcp_server_python/scripts/reingest_state.py`
   (`State_Manager`) as-is. Any schema addition (e.g. `shared_once: bool`
   per Reingest_Unit) SHALL land as a backwards-compatible field with a
   documented migration, not a schema replacement.
2. THE re-ingest SHALL reuse `scripts/ralph_reingest_loop.sh`
   (`Loop_Driver`) as-is. Configuration differences (Target_Version,
   tenant matrix, shared-once handling) SHALL be threaded via environment
   variables the existing loop already reads, not by forking the script.
3. THE Iteration_Prompt SHALL be extended with a Phase-79-specific
   preamble section covering Shared_Once_Rule and Hybrid_Fan_Out, but the
   step structure and terminal-state contract SHALL be identical to the
   Phase-covered predecessor.
4. WHERE this spec conflicts with `cots-reingest-ralph-loop` — for example
   the version-suffix threading or the ingester CLI surface — THE
   conflicting requirement in the predecessor SHALL be amended
   atomically in the same commit as the replacement, per the Phase 80
   spec-amendment discipline.

### Requirement 7: Manifest writeback so the next status probe reflects reality

**User Story:** As an operator running `list_all_sources(include_gaps=True)`
after the re-ingest, I want the gap-detection report to show the coverage
achieved by *this* run, not carry over the pre-run gap numbers.

#### Acceptance Criteria

1. ON `done` transition for each Reingest_Unit whose Stage produced
   ingested documents, THE State_Manager SHALL write the actual document
   count and the source's `ingested_at` timestamp back to
   `mcp_server_python/src/config/unified_manifest.json` via the
   `manifest-status-writeback` mechanism.
2. THE writeback SHALL record `Target_Version` alongside the count so a
   post-run `list_all_sources` can distinguish v8 counts from v9 counts.
3. WHERE a source is blocked per Requirement 3.2, THE writeback SHALL
   record the block reason in the manifest so
   `list_all_sources(include_gaps=True)` surfaces the block instead of
   reporting the source as `never` ingested.

### Requirement 8: Destructive gates and rollback preservation

**User Story:** As an operator, I want every destructive step gated behind an
explicit confirmation and every dropped artefact preserved as a rollback
handle, so a failed re-ingest cannot lose the current serving corpus.

#### Acceptance Criteria

1. THE Neo4j index drop (Requirement 4.1) SHALL require the confirmation
   token `--i-mean-it Target_Version=v9-0-0` on the `neo4j_index_rebuild.py
   --drop` invocation and SHALL exit non-zero without it.
2. THE dropped index definitions SHALL be preserved to
   `.reingest_state/<Target_Version>/neo4j_pre_drop.json` in a form
   directly re-applicable by `neo4j_index_rebuild.py --restore
   <path>`.
3. NO ingester in this re-ingest SHALL be invoked with a
   `--recreate-collection` / `--drop-collection` flag against a v8 or
   `mpnet768` non-v9 collection. IF the ingester CLI does not support
   suppressing that flag, THEN the re-ingest SHALL wrap the ingester in
   a shim that rejects the flag when the target collection name matches
   Requirement 1.2's protected patterns.
4. THE gateway Docker image tagged `eib-mcp-rag-python:pre-shared-scope`
   (rolled from the 2026-08-28 rebuild) SHALL remain locally present
   through this re-ingest and SHALL NOT be pruned; the re-ingest SHALL
   fail-fast if it detects the tag is missing.

### Requirement 9: Fail-fast on tenancy plumbing regressions

**User Story:** As an operator, I want the re-ingest to detect a tenancy
regression the moment it happens, so a per-tenant graph write does not
silently land on the wrong prefix.

#### Acceptance Criteria

1. BEFORE any Reingest_Unit runs, THE State_Manager SHALL confirm the
   active `MCP_DEFAULT_TENANT` matches the unit's `tenant_id` (for
   tenant-scope units) or is unset (for shared-once units), and SHALL
   refuse to start the unit otherwise.
2. AFTER each Reingest_Unit completes, THE Validation_Probe SHALL confirm
   the written physical collection name matches the tenancy contract:
   unprefixed for shared-once units; `<index_prefix>` for tenant-scope
   units. A mismatch SHALL fail the unit with `tenancy_violation` and
   SHALL NOT advance the State_File.
3. FOR graph writes, THE per-tenant node count under
   `<label_prefix>Function`, `<label_prefix>File`, and
   `<label_prefix>FortranSubroutine` SHALL be strictly monotone
   increasing across the tenant's graph stages; a decrease is a
   graph-mutation violation and SHALL fail the unit.

### Requirement 10: CLI-runnable, resumable, disconnect-tolerant

**User Story:** As an operator on the disconnect-prone Parallel Works host,
I want the whole run to be a single CLI invocation that survives ssh
disconnects and multi-day wall-clock and picks up exactly where it left off.

#### Acceptance Criteria

1. THE Loop_Driver SHALL be invocable as
   `scripts/ralph_reingest_loop.sh --target-version v9-0-0
   --spec mpnet768-tenant-reingest-aug2026` and SHALL run to completion
   or terminal state without further input.
2. THE Loop_Driver SHALL run under `nohup` / `tmux` / `systemd-run`
   with no assumption of a live tty, and SHALL log every Iteration to
   `.reingest_state/<Target_Version>/loop.log`.
3. WHEN the Loop_Driver is killed and restarted, THE State_Manager
   SHALL resume from the last durable state and SHALL NOT re-run a
   Reingest_Unit already in a Terminal_State.
4. THE Loop_Driver SHALL emit a progress line every N iterations
   readable by `tail -f` (`{iteration}/{total} done={done}
   failed={failed} blocked={blocked} pending={pending}`) so an
   operator watching from a fresh ssh session can see progress
   without querying the State_File.

### Requirement 11: Bounded resource footprint on the shared host

**User Story:** As an operator sharing the COTS host with other users, I
want the re-ingest bounded in memory, CPU, and disk so it does not evict
other workloads.

#### Acceptance Criteria

1. THE re-ingest SHALL run at most **one** ingester process at a time
   (the Ralph loop is one-unit-at-a-time by construction); parallelism
   inside an ingester (e.g. embedding batch size) SHALL be capped so
   the peak RSS of the embedding worker stays under **8 GiB**.
2. THE Neo4j graph re-parse per tenant SHALL commit in bounded
   transactions (≤ 10,000 nodes / ≤ 50,000 relationships per
   transaction) so a killed transaction does not force a multi-hour
   rollback.
3. THE ChromaDB write path SHALL rate-limit writes if the ChromaDB
   process's RSS exceeds **6 GiB** or if `/api/v2/heartbeat` latency
   exceeds 500 ms sustained over one minute, and SHALL surface the
   throttle as a State_File `throttled` sub-state distinct from
   `failed`.
4. THE re-ingest SHALL fail-fast if `df` on the ChromaDB or Neo4j
   data directories reports less than **20 GiB** free at any
   Reingest_Unit start.

### Requirement 12: Human-gated cutover, deferred out of the loop

**User Story:** As an operator, I want the read-path cutover from the v8
generation to the v9 generation to be a separate, human-gated step, so a
completed re-ingest does not automatically flip production.

#### Acceptance Criteria

1. THE Loop_Driver SHALL NOT touch `unified_manifest.json`'s
   `collection` fields (which the read path resolves through) beyond
   the Requirement 7 count writeback.
2. THE cutover step SHALL be a separate, documented invocation
   (`scripts/reingest_cutover.sh --target-version v9-0-0`) that
   updates every `collection:` field in the manifest and reloads the
   MCP gateway.
3. THE cutover step SHALL run the Requirement 5 Validation_Probe
   suite against the post-cutover manifest and SHALL abort the
   cutover (leaving the v8 generation in place) if any tenant's
   probes regress relative to the pre-cutover run.
4. THE cutover step SHALL preserve the v8 generation collections
   for **at least seven days** post-cutover to support a fast
   rollback, and the retention window SHALL be recorded in
   `docs/reports/2026-XX-XX-mpnet768-tenant-reingest-cutover.md`.

## Out of Scope (explicit)

- **AWS/Neptune/OpenSearch re-ingest.** Handled by a separate spec once the
  COTS pattern is proven end-to-end.
- **Embedding-model change.** `mpnet768` stays. Bedrock-native embeddings
  are covered by `bedrock-embedding-reingestion` and
  `bedrock-native-embedding-swap`.
- **New tenant onboarding.** The five current tenants are the target; a
  sixth tenant would trigger a fresh State_File `init` per Requirement 2.3
  but does not motivate this spec.
- **Deletion of the v8 generation.** Deferred to a post-cutover
  retirement spec after the seven-day retention window (Requirement
  12.4) closes.

## Assumptions and dependencies

- The Phase 79 shared-scope routing fix is deployed on the COTS gateway
  image tagged `eib-mcp-rag-python:latest` @ `ba096b369ac7` as of
  2026-08-28. Verified via `mcp_health_check` and `get_server_info`.
- The Phase 80 default-tenant freeze is retired; the paired structural +
  benchmark gate is in force.
- The APOC-free graph predicates in `ggsr_traversal.py` and
  `graph_rag.py` are the current code, verified by the merge diff on
  `develop @ 90af7c5`.
- The workflow filesystem mount at
  `/mcp_rag_eib/eib-mcp-rag-server/.pw_workflow_mount/` is populated
  for all five tenants (`develop`, `dev-sfs`, `dev-jedi-gfs`,
  `dev-v17`, `gefs-v12`) — verified live 2026-08-28.
- The COTS gateway image bundles `sentence-transformers` + `torch` +
  the `all-mpnet-base-v2` weights offline at `/app/.hf_cache`, so the
  re-ingest does not require outbound HuggingFace access.
- The rollback image tag `eib-mcp-rag-python:pre-shared-scope` @
  `06df8cd251bf` exists locally and is pinned by Requirement 8.4.
