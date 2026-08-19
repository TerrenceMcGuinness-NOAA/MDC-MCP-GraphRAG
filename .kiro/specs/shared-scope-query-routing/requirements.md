# Requirements Document

## Introduction

The MCP-RAG data plane separates content into two scopes. **Shared** content is
NWS-wide and ingested once (external documentation crawls, the on-disk
global-workflow `.rst` tree, EE2/NCO standards, graph-derived community
summaries). **Tenant** content is per `(repo, branch)` and ingested once per
tenant (parsed code, J-Job headers, config-derived documents). The write path
honours this split: `src/data/collection_namer.py::resolve_collection_name`
returns an unprefixed physical name for `scope="shared"` and a
`{tenant.index_prefix}`-prefixed name for `scope="tenant"`.

The read path has no concept of scope. `ChromaDBAdapter.query` and
`OpenSearchAdapter.query` both call `resolve_index(...)` to map the logical
collection to a physical name, then unconditionally hand that name to
`resolve_tenant_index(...)`, which prepends the active tenant's `index_prefix`
to **every** collection regardless of scope. A non-default tenant therefore
addresses a physical collection that the shared write path never created — or,
worse, one that exists and is empty.

### Empirically confirmed current state

Live `get_knowledge_base_status` against the AWS backend (2026-08-18 session,
active profile `titan1024`) shows the shared corpora populated under the
default `gw` tenant and the corresponding `gw_v17_`-prefixed collections either
empty or holding unrelated per-branch content:

| Logical collection | Manifest scope | `gw` (unprefixed) | `gw_v17_` prefixed |
|---|---|---|---|
| `global-workflow-docs-v8-0-0` | shared | 35,980 | 28,459 (v17 repo-local) |
| `ee2-standards-v5-0-0-enhanced` | shared | 34 | 0 (exists, empty) |
| `community-summaries` | shared | 2,113 | 0 (exists, empty) |
| `code-with-context-v8-0-0` | tenant | 90,135 | 52,662 |
| `jjobs-v8-0-0` | tenant | 751 | 92 |

Direct probes confirm the user-visible symptom.
`search_ee2_standards(tenant_id="gw_v17")` returns `Found 0 standards`;
the same query without `tenant_id` returns the `err_chk` / `err_exit` standard.
`search_architecture(tenant_id="gw_v17")` returns no matches; the same query
under `gw` returns ranked communities.

### Three findings that reshape the fix

**1. The failure mode is an empty index, not a 404.** Phase 79 describes the
symptom as a silently-swallowed missing-index exception. For the two pure-shared
domains the prefixed collections *exist* and hold zero documents, so
`_is_missing_index_exc` never matches and the `graceful-missing-index-handling`
Skip_Block never renders. The tools report a clean "found 0" with no indication
that the tenant is structurally unable to reach the content. Any fix that probes
physical existence and falls back on absence would find the empty collection,
treat the routing as successful, and preserve the blind spot.

**2. `workflow-docs` is a hybrid domain.** The `global-workflow-rst` source is
declared `scope: "shared"` in the manifest, yet its content is repo-local `.rst`
under `docs/**` and therefore varies per branch. The 28,459 documents in
`gw_v17_mdc-workflow-docs-titan1024` are v17-specific and reachable **only**
through the prefixed name. A rule of the form "shared means never prefix" would
trade the current blind spot for a new one of comparable size. Steering Gap H
reaches the same conclusion independently and recommends fanning out to both.

**3. The defect has three code-path manifestations, not one.** Three
independent code paths each re-derive "which physical collections belong to
tenant T", and each derives it differently:

| Path | Derivation | Consequence |
|---|---|---|
| `query()` in both adapters | prefix everything | shared content unreachable |
| `_filter_indices_by_tenant()` (status + health) | keep prefixed names only | shared content invisible in reports |
| `_build_vector_sampler()` → `sample_metadata(collection=None)` | no scoping at all | integrity checks mix every tenant together |

The absence of a single authority for that question is the root cause. A fix
confined to `query()` leaves two of the three paths wrong.

### Blast radius

Ten query sites pass a shared-scope logical collection into an adapter together
with the active tenant, across five modules: `search_documentation`,
`explain_with_context` and `find_related_files` (`semantic_search.py`); the
three `EE2_COLLECTION` sites (`ee2_compliance.py`); `search_architecture` and
the two `COMMUNITY_COLLECTION` helper sites feeding `get_code_context`
(`graph_rag.py`); `get_operational_guidance` and `explain_workflow_component`
(`operational.py`). Tenant-scoped sites (`find_similar_code`, `get_job_details`,
`list_job_scripts`) are correct today and must stay correct.

### A conflicting existing assertion

`_smoke_branch_isolation` in `src/tools/smoke_queries.py` asserts, as assertion
4 of the `branch_isolation` probe, that a `gw_v17` query against
`global-workflow-docs-v8-0-0` returning develop-sourced content is a **tenant
isolation violation**. After this fix, shared content is expected to reach
`gw_v17`. The isolation invariant needs restating and the probe needs realigning
in the same change, rather than being left to fail or be silently weakened.

### Factual corrections to the Phase 79 source document

The Phase 79 write-up is the problem statement for this spec. Four of its
incidental claims drifted and this document supersedes them: scope metadata
lives in `src/config/unified_manifest.json`, not a `sources_manifest.yaml` (no
such file exists); the default-tenant preservation invariant is **Property 3 —
Empty-prefix passthrough** in `.kiro/specs/omd-tenants-1-foundation/design.md`,
not Property 4 (Property 4 is Resolution determinism, and the mis-citation has
already propagated into three code comments); live v17 physical collections
carry no `-v9-0-0` version suffix; and the impact table's per-collection counts
predate the current ingest state.

### Scope

**In scope.** Read-path scope resolution across both vector adapters, plus the
status, integrity, and health reporting paths that re-derive the same
tenant-to-collection mapping (Phase 79 must-have items 1-6 and should-have items
7-9). Parity across the AWS backend (OpenSearch on AgentCore Runtime) and the
COTS backend (ChromaDB in Parallel Works Docker container services).

**Deliberately deferred.** Phase 79 nice-to-have items 10-12 are ingestion work,
not read-path work: the v17 Python graph ingest, v17 code-context and `mpnet768`
parity ingestion, and vector/graph backfill for `gw_sfs`, `gw_jedi_gfs`, and
`gw_gefs_v12`. This spec is a prerequisite for those runs being useful but does
not gate them, and none of them are required for this spec to deliver value.

**Adjacent findings recorded, not addressed.** Two defects surfaced during
investigation and are noted so a later spec can pick them up. The
`mdc-content-sha-registry` index (53,016 documents) is an ingestion dedupe
ledger that `get_knowledge_base_status` counts toward the searchable corpus
total for `gw`. This change leaves that over-count asymmetric on purpose:
Requirement 9 criterion 7 excludes bookkeeping indices from the listing and the
total for any Tenant whose Index_Prefix is non-empty, so the shared/tenant
listing is correct for non-default tenants from this change onward, while
Requirement 6 criterion 3 holds the `gw` block byte-equivalent and therefore
retains the pre-existing over-count. The follow-up spec that drops the ledger
from the `gw` total is where the two paths converge; until then the asymmetry is
the deliberate cost of the default-tenant preservation invariant. And
`DEFAULT_SEMANTIC_COLLECTION` in
`src/graphrag/graph_guided_retrieval.py` is hard-coded to the *physical* name
`mdc-code-context-mpnet768`, bypassing profile resolution; Requirement 2 governs
the layering violation that makes such an identifier unclassifiable, but the
constant's profile pinning is out of scope.

### Design decision left open

Phase 79 documents four candidate mechanisms and recommends the first: tag the
collection-name constants with scope (Option 1); teach the adapters to read the
manifest (Option 2); probe physical existence and fall back (Option 3);
or split the fan-out into shared and tenant lists (Option 4). This document does
not select one. Option 3 is no longer among the candidates left open — it is
excluded by requirement, because Requirement 5 criterion 1 forbids
collection-existence probes during resolution and finding 1 above shows a
provisioned-but-empty collection defeats the fall-back trigger the mechanism
depends on. Requirements 1, 2, 4, and 5 are written to be evaluated against
each remaining candidate on single-point-of-truth strength, drift resistance,
cross-backend symmetry, and the no-network-probe constraint that finding 1 above
imposes.

## Glossary

- **Logical_Collection**: A backend-independent collection identifier used by
  tool modules, e.g. `global-workflow-docs-v8-0-0`. The five in service are the
  keys of `PRODUCTION_INDICES_BY_PROFILE`.
- **Physical_Collection**: The concrete OpenSearch index or ChromaDB collection
  name, e.g. `gw_v17_mdc-workflow-docs-titan1024`.
- **Embedding_Profile**: The active embedding short-name (`titan1024`,
  `mpnet768`, `nova1024`) read from `MCP_EMBEDDING_PROFILE`, which selects the
  Logical_Collection to Physical_Collection map.
- **Index_Prefix**: A tenant's `index_prefix` field from
  `src/config/tenants.yaml`, e.g. `gw_v17_`. Empty for the Default_Tenant.
- **Tenant**: A `(repo, branch)` pair in the tenant catalog, resolved from the
  optional `tenant_id` tool parameter.
- **Default_Tenant**: The `gw` tenant, whose Index_Prefix and `label_prefix` are
  both the empty string.
- **Collection_Condition**: One of exactly three values, `unprovisioned`,
  `provisioned-empty`, or `provisioned-populated`, that a Vector_Adapter assigns
  to each addressed Physical_Collection per read. `unprovisioned` means the
  Physical_Collection is absent from the active Backend; `provisioned-empty`
  means it is present and holds zero documents; `provisioned-populated` means it
  is present and holds one or more documents, whether or not the query matched
  any of them.
- **Collection_Scope**: One of exactly two values, `shared` or `tenant`,
  declaring whether a Logical_Collection holds NWS-wide or per-Tenant content.
- **Scope_Authority**: The single component that answers "what is the
  Collection_Scope of this Logical_Collection".
- **Read_Router**: The component that maps a `(Logical_Collection, Tenant)` pair
  to the set of Physical_Collections a read should address.
- **Collection_Namer**: The existing write-side naming authority,
  `src/data/collection_namer.py::resolve_collection_name`.
- **Configuration_Transport**: The mechanism that supplies tenant catalog
  content and Collection_Scope configuration content to a running process —
  either an environment variable or a file mounted into the Form_Factor's
  filesystem.
- **Vector_Adapter**: Either `ChromaDBAdapter` or `OpenSearchAdapter`, both
  implementing `VectorDBProtocol`.
- **Backend**: The value of `DB_BACKEND`. `aws` selects OpenSearch plus Neptune;
  `cots` selects ChromaDB plus Neo4j.
- **Form_Factor**: A deployment shape. `agentcore` is the Bedrock AgentCore
  Runtime ARM64 microVM; `container` is a locally-run Docker container service
  on Parallel Works.
- **Hybrid_Domain**: A Logical_Collection of Collection_Scope `shared` that is
  declared in configuration as also carrying per-Tenant content, and whose reads
  therefore address both the unprefixed and the Index_Prefix-prefixed
  Physical_Collection. `global-workflow-docs-v8-0-0` is one, because its
  `global-workflow-rst` source reads repo-local `docs/**/*.rst` that varies per
  branch.
- **Resolved_Collection_Set**: The set of Physical_Collections the Read_Router
  returns for one `(Logical_Collection, Tenant)` pair.
- **Routing_Diagnostic**: A server-log-channel-only line naming the
  Physical_Collections a read addressed and the Collection_Scope that selected
  them. A Routing_Diagnostic never appears in a tool response body (Requirement
  7 criterion 6).
- **Skip_Block**: The `[INFO]`-prefixed markdown produced by
  `src/tools/_common.py::_missing_index_skip` for an unprovisioned collection.
- **Status_Reporter**: The `get_knowledge_base_status` tool.
- **Integrity_Checker**: The `check_knowledge_integrity` tool.
- **Health_Reporter**: The `mcp_health_check` tool.
- **Isolation_Probe**: The `_smoke_branch_isolation` functional probe in
  `src/tools/smoke_queries.py`.
- **Scope_Consistency_Check**: A validation that compares the Scope_Authority's
  classifications against the `scope` values declared in
  `src/config/unified_manifest.json`, reporting four classes of finding: a
  Logical_Collection whose classification differs from its sources' declared
  `scope`; a non-Hybrid_Domain `collection_target` whose enabled sources declare
  more than one distinct `scope`; a source whose `scope` is absent or outside the
  set `{shared, tenant}`; and a `collection_target` for which the
  Scope_Authority holds no entry.
- **Verification_Record**: The single markdown file under `docs/reports/` that
  records the live invocations and test-suite runs evidencing this change, in the
  form Requirement 13 criterion 8 specifies.

## Requirements

### Requirement 1: Single authority for collection scope

**User Story:** As a maintainer of the data plane, I want one component to own
the question "is this collection shared or tenant-scoped", so that read routing,
status reporting, and integrity checking cannot drift apart the way the three
current code paths have.

#### Acceptance Criteria

1. THE Scope_Authority SHALL return, for every Logical_Collection registered
   for the active Embedding_Profile in `PRODUCTION_INDICES_BY_PROFILE` (five
   today), exactly one Collection_Scope value drawn from the set
   `{shared, tenant}`, SHALL return the same value on every invocation for the
   same Logical_Collection, and SHALL do so without issuing a network request
   to either Backend.
2. THE Scope_Authority SHALL classify `global-workflow-docs-v8-0-0`,
   `ee2-standards-v5-0-0-enhanced`, and `community-summaries` as `shared`, and
   SHALL classify `code-with-context-v8-0-0` and `jjobs-v8-0-0` as `tenant`,
   matching the `(collection_target, scope)` pairs declared for all 67 sources
   in `src/config/unified_manifest.json`, and SHALL return these five
   classifications unchanged for every Tenant and every Embedding_Profile.
3. WHEN the Read_Router resolves a Resolved_Collection_Set, THE Read_Router
   SHALL obtain both the Collection_Scope and the Hybrid_Domain membership of
   that Logical_Collection from the Scope_Authority and SHALL NOT derive
   either value from any other source, so that changing a Logical_Collection's
   Scope_Authority classification between `shared` and `tenant` changes the
   Resolved_Collection_Set the Read_Router returns for that Logical_Collection
   with no other change.
4. WHEN the Status_Reporter, the Integrity_Checker, or the Health_Reporter
   requires the Physical_Collections of a Tenant, THE requiring component
   SHALL obtain that set from the Read_Router, SHALL NOT derive it by
   filtering physical collection names for an Index_Prefix, SHALL NOT leave it
   unscoped, and the set SHALL equal the union of the Read_Router's
   Resolved_Collection_Sets over the Logical_Collections of criterion 1.
5. IF a collection identifier reaches the Read_Router for which the
   Scope_Authority yields no Collection_Scope because the identifier is not a
   Logical_Collection, THEN THE Read_Router SHALL treat that identifier as
   Collection_Scope `tenant`, SHALL return a Resolved_Collection_Set whose
   single member is the Index_Prefix-prefixed form of that identifier, SHALL
   emit a Routing_Diagnostic naming the identifier and the applied `tenant`
   fallback, and SHALL NOT raise an exception or return an empty
   Resolved_Collection_Set. This fallback applies only where the
   Scope_Authority's backing configuration loaded successfully and the
   identifier is not a Logical_Collection; a configuration source that cannot be
   read or parsed is a hard error governed by Requirement 5 criterion 6 and
   SHALL NOT reach this fallback.
6. THE Scope_Consistency_Check SHALL report a finding naming the collection
   identifier and the conflicting values for each of: a Logical_Collection
   whose Scope_Authority classification differs from the `scope` value
   declared by that collection's sources in
   `src/config/unified_manifest.json`; a `collection_target` that is not a
   Hybrid_Domain and whose enabled sources declare more than one distinct
   `scope` value; a source whose `scope` value is absent or falls outside the
   set `{shared, tenant}`; and a `collection_target` for which the
   Scope_Authority holds no entry.
7. WHEN the automated test suite runs, THE Scope_Consistency_Check SHALL
   execute without issuing a network request to either Backend.
8. THE Scope_Authority SHALL determine Hybrid_Domain membership from
   configuration without issuing a network request to either Backend, SHALL
   restrict Hybrid_Domain membership to Logical_Collections it classifies
   `shared`, and SHALL declare `global-workflow-docs-v8-0-0` as the only
   Hybrid_Domain among the Logical_Collections of criterion 1.
9. IF the Scope_Consistency_Check reports at least one finding, THEN THE
   Scope_Consistency_Check SHALL fail the test-suite run and SHALL name every
   reported finding in the failure output.

### Requirement 2: Scope-aware physical name resolution on the read path

**User Story:** As a developer working on the `dev/gfs.v17` branch, I want a
query issued with `tenant_id="gw_v17"` to reach the shared documentation and
standards corpora, so that switching tenants narrows my code view without
removing my access to NWS-wide knowledge.

#### Acceptance Criteria

1. WHEN the Read_Router resolves a `(Logical_Collection, Tenant,
   Embedding_Profile)` triple, THE Read_Router SHALL first obtain the
   Physical_Collection name for the active Embedding_Profile, and SHALL form
   every Index_Prefix-carrying member of the Resolved_Collection_Set by
   prepending the active Tenant's Index_Prefix to that Physical_Collection name
   rather than to the Logical_Collection identifier.
2. WHERE the Collection_Scope is `tenant`, THE Read_Router SHALL return a
   Resolved_Collection_Set containing exactly one member — the
   Index_Prefix-prefixed Physical_Collection — and SHALL exclude the unprefixed
   Physical_Collection whenever the active Tenant's Index_Prefix is non-empty.
3. WHERE the Collection_Scope is `shared` and the Logical_Collection is not a
   Hybrid_Domain, THE Read_Router SHALL return a Resolved_Collection_Set
   containing exactly one member — the unprefixed Physical_Collection — for
   every Tenant, and SHALL exclude any Index_Prefix-prefixed
   Physical_Collection.
4. WHEN a tool queries a `shared` Logical_Collection under a Tenant whose
   Index_Prefix is non-empty, THE Vector_Adapter SHALL address the unprefixed
   Physical_Collection, SHALL draw every returned hit from a member of the
   Resolved_Collection_Set, and SHALL NOT substitute the Index_Prefix-prefixed
   Physical_Collection for the unprefixed one.
5. THE ten query sites named in the Introduction, across `semantic_search.py`,
   `ee2_compliance.py`, `graph_rag.py`, and `operational.py`, SHALL pass to the
   Vector_Adapter a Logical_Collection identifier that is a key of the active
   Embedding_Profile's entry in `PRODUCTION_INDICES_BY_PROFILE`, and SHALL NOT
   pass a Physical_Collection name.
6. WHEN `search_ee2_standards`, `search_architecture`,
   `get_operational_guidance`, `explain_workflow_component`,
   `search_documentation`, `explain_with_context`, `find_related_files`, or
   `get_code_context` runs against a `shared` Logical_Collection that is not a
   Hybrid_Domain under a Tenant whose Index_Prefix is non-empty, THE invoked
   tool SHALL return the same ordered sequence of document identifiers, with the
   same similarity scores, that the tool returns under the Default_Tenant for
   the same query text, the same result limit in the range 1 to 1000, and the
   same value of every other tool argument.
7. WHEN a tool named in criterion 6 runs against a Hybrid_Domain under a Tenant
   whose Index_Prefix is non-empty, THE invoked tool SHALL return every hit that
   the same invocation returns under the Default_Tenant, except those hits
   displaced beyond the result limit by a higher-scoring hit drawn from the
   Index_Prefix-prefixed Physical_Collection.
8. IF the active Embedding_Profile has no Physical_Collection mapping for a
   Logical_Collection, THEN THE Read_Router SHALL apply the Collection_Scope
   decision of criteria 2 and 3 to the unmapped identifier, SHALL leave the
   Resolved_Collection_Set otherwise unchanged in cardinality, and SHALL emit a
   Routing_Diagnostic naming the Logical_Collection and the active
   Embedding_Profile.
9. WHEN `find_similar_code`, `get_job_details`, or `list_job_scripts` runs under
   a Tenant whose Index_Prefix is non-empty, THE invoked tool SHALL return only
   hits drawn from that Tenant's Index_Prefix-prefixed Physical_Collection.

### Requirement 3: Additive resolution for hybrid domains

**User Story:** As a developer on `dev/gfs.v17`, I want both the shared external
documentation and the 28,459 v17-specific repo-local documents available from a
single documentation search, so that the fix for one blind spot does not create
another.

#### Acceptance Criteria

1. WHERE a Logical_Collection is a Hybrid_Domain, WHILE the active Tenant's
   Index_Prefix is non-empty, THE Read_Router SHALL return a
   Resolved_Collection_Set of exactly two members, ordered with the unprefixed
   Physical_Collection first and the Index_Prefix-prefixed Physical_Collection
   second.
2. WHEN a Resolved_Collection_Set contains more than one Physical_Collection,
   THE Vector_Adapter SHALL issue one read against every member of that set,
   passing each member the same query text, the same result limit `k`, the same
   similarity threshold, and the same metadata filter that the caller supplied.
3. WHEN results arrive from more than one Physical_Collection, THE
   Vector_Adapter SHALL order the merged results by similarity score in
   descending order, where the similarity score is the value on the 0.0 to 1.0
   inclusive scale that the Vector_Adapter attaches to each hit.
4. WHEN results arrive from more than one Physical_Collection, THE
   Vector_Adapter SHALL return the first `k` results of the ordering established
   by criteria 3 and 7 after de-duplication, where `k` is an integer from 1 to
   1000 inclusive, and SHALL return every remaining result when fewer than `k`
   remain after de-duplication.
5. THE Vector_Adapter SHALL attach to each returned hit exactly one
   Physical_Collection name, and that name SHALL be a member of the
   Resolved_Collection_Set that the read addressed.
6. THE Read_Router SHALL determine Hybrid_Domain membership from configuration
   content alone, independent of the presence, the absence, and the document
   count of any Physical_Collection on either Backend, and SHALL treat
   `global-workflow-docs-v8-0-0` as the only Hybrid_Domain among the five
   Logical_Collections in service.
7. WHEN two or more merged results carry equal similarity scores, THE
   Vector_Adapter SHALL order those results by the position of the producing
   Physical_Collection in the Resolved_Collection_Set in ascending order, and
   SHALL order results produced by the same Physical_Collection by hit
   identifier in ascending lexicographic order, so that the merged ordering is
   a total order.
8. WHEN two or more merged results carry equal document content, THE
   Vector_Adapter SHALL treat those results as duplicates of one another, SHALL
   retain only the result that the ordering of criteria 3 and 7 places first,
   and SHALL attach to the retained result the name of the Physical_Collection
   that produced that retained result.
9. WHEN the same query text, result limit, similarity threshold, and metadata
   filter are issued twice against an unchanged Resolved_Collection_Set holding
   unchanged Physical_Collection content, THE Vector_Adapter SHALL return the
   same ordered sequence of hits, with the same attached Physical_Collection
   names, for both invocations.

### Requirement 4: Symmetric behaviour across backends

**User Story:** As an operator running the same tool surface on AWS and on
Parallel Works, I want identical routing semantics on both, so that a result
observed on one backend is reproducible on the other and neither adapter becomes
the reference implementation by accident.

#### Acceptance Criteria

1. WHEN the Read_Router resolves a `(Logical_Collection, Tenant,
   Embedding_Profile)` triple under Backend `aws` and under Backend `cots` with
   identical configuration content, THE Read_Router SHALL produce
   Resolved_Collection_Sets holding the same Physical_Collection names, compared
   as case-sensitive exact strings and without regard to ordering (property P3).
2. THE Read_Router SHALL be the only component that applies an Index_Prefix on
   the read path, such that substituting its resolution behaviour changes the
   Physical_Collections addressed by `ChromaDBAdapter` and by
   `OpenSearchAdapter` identically.
3. WHEN a Physical_Collection in a Resolved_Collection_Set is absent from the
   active Backend, THE Vector_Adapter SHALL surface that absence as an
   unprovisioned-collection condition that the tool layer distinguishes from a
   query failure, producing the same classification under Backend `aws` and
   Backend `cots` and independently of the exception type the underlying client
   library raises.
4. WHEN a tool renders a Skip_Block for an unprovisioned collection, THE tool
   SHALL render text that is character-for-character identical under Backend
   `aws` and Backend `cots` for the same `(tool, Logical_Collection,
   tenant_id)` triple.
5. THE property-based tests covering scope resolution SHALL execute as the same
   parameterised test bodies against both `ChromaDBAdapter` and
   `OpenSearchAdapter`, covering property P3 and the classification outcomes
   required by criteria 3, 6, 7, and 8.
6. IF a read against a Physical_Collection in a Resolved_Collection_Set fails
   for any reason other than that collection's absence, including connection
   failure, authentication failure, and embedding-generation failure, THEN THE
   Vector_Adapter SHALL surface the condition as a query failure distinct from
   the unprovisioned-collection condition of criterion 3, under both Backend
   values, and SHALL NOT present it as an unprovisioned collection.
7. IF every Physical_Collection in a Resolved_Collection_Set is absent from the
   active Backend, THEN THE tool SHALL render exactly one Skip_Block naming the
   Logical_Collection and the active `tenant_id`, under both Backend values.
8. WHEN a read addresses a Resolved_Collection_Set in which at least one
   Physical_Collection is present on the active Backend, THE tool SHALL return
   the results gathered from the present Physical_Collections without rendering
   a Skip_Block, under both Backend values.

### Requirement 5: Operation across deployment form factors

**User Story:** As an operator deploying to the AgentCore Runtime microVM and to
Parallel Works Docker container services, I want scope routing to work in both
without per-environment special-casing, so that the same image behaves the same
way wherever it runs.

#### Acceptance Criteria

1. THE Read_Router SHALL determine Collection_Scope and Index_Prefix from
   configuration content alone, issuing exactly zero network requests and zero
   collection-existence probes to either Backend per resolution, and SHALL
   return equal Resolved_Collection_Sets for repeated invocations with the same
   `(Logical_Collection, Tenant, Embedding_Profile)` triple within one process
   lifetime.
2. WHEN the Read_Router resolves a `(Logical_Collection, Tenant,
   Embedding_Profile)` triple under Form_Factor `agentcore` and under
   Form_Factor `container` with identical tenant catalog content, identical
   Collection_Scope configuration content, and the same Backend value, THE
   Read_Router SHALL produce Resolved_Collection_Sets that are equal as
   unordered sets of Physical_Collection names.
3. WHERE tenant configuration is supplied by an environment variable whose
   content is byte-identical to the content of a configuration file mounted into
   the Form_Factor's filesystem, THE Read_Router SHALL produce, for the same
   `(Logical_Collection, Tenant, Embedding_Profile)` triple, a
   Resolved_Collection_Set equal as an unordered set of Physical_Collection
   names to the set it produces from the mounted file.
4. WHEN the active Embedding_Profile changes among the three Embedding_Profile
   values named in the Glossary (`titan1024`, `mpnet768`, `nova1024`), including
   a value for which no Logical_Collection-to-Physical_Collection map is
   registered, THE Read_Router SHALL classify every Logical_Collection with the
   same Collection_Scope, SHALL apply the Index_Prefix to the same
   Logical_Collections, SHALL produce Resolved_Collection_Sets of equal
   cardinality, and SHALL vary only the Physical_Collection names.
5. WHERE a Tenant has no Index_Prefix-prefixed Physical_Collection provisioned
   on the active Backend for the active Embedding_Profile, THE Read_Router SHALL
   include the unprefixed Physical_Collection of every `shared`
   Logical_Collection and the Index_Prefix-prefixed Physical_Collection of every
   `tenant` Logical_Collection in the Resolved_Collection_Set, deciding
   membership without reference to provisioning state and leaving each absent
   member to be reported as unprovisioned under Requirement 7 criterion 3.
6. IF the tenant configuration or the Collection_Scope configuration cannot be
   read or cannot be parsed, THEN THE Read_Router SHALL resolve no
   Resolved_Collection_Set, SHALL issue no read to either Backend, SHALL NOT
   fall back to treating every Logical_Collection as Collection_Scope `tenant`,
   and THE invoked tool SHALL return an error indicating which configuration
   source failed to load. This hard-error condition is distinct from the
   unrecognised-identifier fallback of Requirement 1 criterion 5, which applies
   only where configuration loaded successfully and the identifier reaching the
   Read_Router is not a Logical_Collection.
7. IF both an environment variable and a mounted file supply tenant
   configuration within one process, THEN THE Read_Router SHALL resolve every
   Resolved_Collection_Set from exactly one of the two Configuration_Transports,
   SHALL apply that same precedence under Form_Factor `agentcore` and under
   Form_Factor `container`, and SHALL emit a Routing_Diagnostic naming the
   Configuration_Transport it resolved from.

### Requirement 6: Preservation of default-tenant behaviour

**User Story:** As an operator responsible for the production `gw` tenant, I
want this change to leave every `gw` response unchanged, so that a read-path
refactor carries no regression risk for the default path.

#### Acceptance Criteria

1. WHERE the active Tenant is the Default_Tenant, THE Read_Router SHALL produce,
   for every Logical_Collection and every Embedding_Profile, a
   Resolved_Collection_Set containing exactly one member equal to the
   Physical_Collection that `resolve_index(collection, profile)` returns,
   preserving Property 3 (Empty-prefix passthrough) of
   `.kiro/specs/omd-tenants-1-foundation/design.md`.
2. WHEN any tool named in Requirement 2 criterion 6, or `find_similar_code`,
   `get_job_details`, or `list_job_scripts`, runs without a `tenant_id`
   argument, THE tool SHALL return a complete rendered response byte-equivalent
   to the response that tool returns before this change for the same query text,
   the same result limit in the range 1 to 1000, the same Backend, the same
   Embedding_Profile, and the same store content, including the tenant
   attribution header lines.
3. WHEN the Status_Reporter, the Integrity_Checker, or the Health_Reporter runs
   without a `tenant_id` argument, THE invoked component SHALL render a complete
   response byte-equivalent to the response that component renders before this
   change, listing the same Physical_Collections with the same document counts,
   in preference to the scope-labelling and totalling behaviour that
   Requirements 9, 10, and 11 require for a Tenant whose Index_Prefix is
   non-empty.

   **Superseded 2026-08-19 by `default-tenant-freeze-retirement` (SDD Phase
   80).** Byte-equivalence is retired for the Status_Reporter, the
   Integrity_Checker, and the Health_Reporter and replaced by Structural
   Equivalence. Under the superseding relation, a no-`tenant_id` render of any
   of the three reporters is equivalent to the pre-change render when, and only
   when, all three of the following hold: the set of Physical_Collection names
   each response lists is equal; the document count each response reports for
   each listed Physical_Collection is equal; and the pass, fail, or skip verdict
   each response reports for each named check is equal. Wording, line order,
   label text, field captions, and whitespace are free to change. This retires
   the "in preference to" ranking above, so the `mdc-content-sha-registry`
   over-count in the `gw` status total can be corrected and the Default_Tenant
   integrity sample can be scoped; `default-tenant-freeze-retirement` is the
   authority for changing Default_Tenant reporter output. The relation is
   defined and enforced by
   `mcp_server_python/tests/baselines/structural.py` and
   `mcp_server_python/tests/unit/test_default_tenant_byte_equivalence.py`. The
   query-result freeze of criterion 2 is unaffected by this supersession and
   remains in force for the Query_Tools.
4. THE code comments and docstrings in `src/tools/semantic_search.py` and
   `src/data/opensearch_adapter.py` that cite the default-preservation invariant
   SHALL cite Property 3 (Empty-prefix passthrough) of
   `.kiro/specs/omd-tenants-1-foundation/design.md` and SHALL contain no
   remaining citation of Property 4 (Resolution determinism) as that invariant.
5. THE byte-equivalence comparison required by criteria 2 and 3 SHALL be
   performed against a response capture recorded from the revision immediately
   preceding this change under identical inputs, and SHALL tolerate a difference
   only in a character sequence that also differs between two consecutive
   invocations of that preceding revision under those same identical inputs,
   such as a generated timestamp.
6. WHERE the active Tenant is the Default_Tenant, THE Read_Router SHALL confine
   every Routing_Diagnostic it emits, including the unknown-identifier
   Routing_Diagnostic required by Requirement 1 criterion 5, to the log channel,
   so that no Routing_Diagnostic text appears in the responses compared under
   criteria 2 and 3 and its emission does not constitute a difference under
   criterion 5.
7. WHERE the active Tenant is the Default_Tenant AND a Logical_Collection is a
   Hybrid_Domain, THE Read_Router SHALL produce a Resolved_Collection_Set
   containing exactly one member, the unprefixed Physical_Collection, because
   the empty Index_Prefix collapses the two members that Requirement 3
   criterion 1 would otherwise return.
8. WHERE the active Tenant is the Default_Tenant, THE invoked tool SHALL omit
   from its response body the zero-hit annotation that Requirement 7 criterion 7
   requires for a Tenant whose Index_Prefix is non-empty, so that an addressed
   Physical_Collection carrying the `unprovisioned` or the `provisioned-empty`
   Collection_Condition under the Default_Tenant leaves the response
   byte-equivalent as criteria 2 and 3 require, and SHALL record that
   Collection_Condition on the log channel only.

### Requirement 7: Observable routing and tolerated partial state

**User Story:** As an operator triaging an empty result, I want to distinguish a
tenant that legitimately has no content for a collection from a tenant that
cannot reach content that exists, so that a structural blind spot surfaces
instead of reading as a normal zero-hit answer.

#### Acceptance Criteria

1. IF at least one Physical_Collection in a Resolved_Collection_Set of at most
   two members is absent and at least one member of that set is present, THEN
   THE Vector_Adapter SHALL return the results gathered from the present
   Physical_Collections, ranked and de-duplicated per Requirement 3 criteria
   3-4, and SHALL not propagate a Backend error to the calling tool.
2. WHEN a read addresses a Resolved_Collection_Set under any Tenant, including
   the Default_Tenant, THE Read_Router SHALL emit exactly one Routing_Diagnostic
   that names every Physical_Collection in that set, the Collection_Scope that
   selected each member, whether each member carries the active Tenant's
   Index_Prefix or no prefix, and the active Tenant's `tenant_id`.
3. IF the active Backend reports that a Physical_Collection in a
   Resolved_Collection_Set does not exist, THEN THE Vector_Adapter SHALL emit a
   Routing_Diagnostic carrying the condition classification `unprovisioned` for
   that Physical_Collection.
4. IF a Physical_Collection in a Resolved_Collection_Set exists and reports a
   document count of zero, THEN THE Vector_Adapter SHALL emit a
   Routing_Diagnostic carrying the condition classification `provisioned-empty`
   for that Physical_Collection, distinct from the `unprovisioned` classification
   of criterion 3.
5. IF a Resolved_Collection_Set for a `shared` Logical_Collection contains no
   unprefixed Physical_Collection, THEN THE Read_Router SHALL emit a
   Routing_Diagnostic carrying the condition classification
   `routing-misconfiguration` that names the Logical_Collection and the active
   Tenant, and SHALL return the Resolved_Collection_Set so the read proceeds
   over its remaining members.
6. THE Routing_Diagnostic SHALL be emitted on the server log channel only, SHALL
   be absent from every tool response body, SHALL contain ASCII characters only,
   SHALL not exceed 1,000 characters per emission, and SHALL omit query text,
   document content, and credentials.
7. IF a read returns zero hits under a Tenant whose Index_Prefix is non-empty
   and at least one addressed Physical_Collection carries the `unprovisioned` or
   the `provisioned-empty` classification, THEN THE invoked tool SHALL name each
   such Physical_Collection and its Collection_Scope in the response body, SHALL
   indicate that the zero-hit result reflects an unreachable or empty collection
   rather than an absence of matching content, and SHALL leave the remainder of
   the response body unchanged from the zero-hit response the tool renders when
   every addressed Physical_Collection carries the `provisioned-populated`
   classification.
8. THE Vector_Adapter SHALL classify each addressed Physical_Collection as
   exactly one of `unprovisioned`, `provisioned-empty`, or
   `provisioned-populated` per read, and SHALL classify a Physical_Collection
   that exists and holds one or more documents as `provisioned-populated` even
   when that Physical_Collection returns zero hits for the query.
9. IF every Physical_Collection in a Resolved_Collection_Set is absent, THEN THE
   invoked tool SHALL render a Skip_Block naming the Logical_Collection and the
   active Tenant, and SHALL not propagate a Backend error to the caller.

### Requirement 8: Restated isolation invariant and realigned probe

**User Story:** As a maintainer of the tenancy test suite, I want the isolation
invariant to say what isolation now means, so that shared-content visibility
registers as correct behaviour rather than as a violation.

#### Acceptance Criteria

1. THE isolation invariant, as recorded in Correctness Properties P5 and P6,
   SHALL state that a hit whose attached Physical_Collection name carries the
   non-empty Index_Prefix of one Tenant is absent from results returned to any
   other Tenant, and that a hit whose attached Physical_Collection name carries
   no Tenant's non-empty Index_Prefix is present in results returned to every
   Tenant, including every Tenant whose Index_Prefix is non-empty.
2. THE Isolation_Probe SHALL assert that a query against
   `global-workflow-docs-v8-0-0` with a result limit of 10 issued under `gw_v17`
   returns no hit whose attached Physical_Collection name carries the non-empty
   Index_Prefix of any Tenant other than `gw_v17`, and that the same query
   issued under the Default_Tenant returns no hit whose attached
   Physical_Collection name carries any Tenant's non-empty Index_Prefix.
3. THE Isolation_Probe SHALL assert that a query against
   `ee2-standards-v5-0-0-enhanced` with a result limit of 10 issued under
   `gw_v17` returns at least one hit whose attached Physical_Collection name
   carries no Tenant's non-empty Index_Prefix.
4. THE Isolation_Probe SHALL derive the originating Tenant of a hit from the
   Physical_Collection name attached under Requirement 3 criterion 5,
   classifying a hit as originating from a Tenant when that name carries that
   Tenant's non-empty Index_Prefix and as shared when that name carries no
   Tenant's non-empty Index_Prefix, rather than from document metadata values or
   source-path substring matching.
5. THE graph-side label isolation assertions of the Isolation_Probe — that a
   Tenant-specific J-Job is reachable through a label-scoped graph query issued
   under `gw_v17`, and that the same query issued under the Default_Tenant
   returns no rows — SHALL retain their query text and label scoping, and SHALL
   produce, for any given data state, the same pass or fail outcome that they
   produce before this change.
6. THE Isolation_Probe SHALL assert that a query against
   `global-workflow-docs-v8-0-0` with a result limit of 10 issued under `gw_v17`
   returns at least one hit whose attached Physical_Collection name carries the
   `gw_v17` Index_Prefix and at least one hit whose attached
   Physical_Collection name carries no Tenant's non-empty Index_Prefix.
7. IF a hit evaluated by an Isolation_Probe assertion carries no attached
   Physical_Collection name, THEN THE Isolation_Probe SHALL report that
   assertion as failed and SHALL name the Logical_Collection and the Tenant of
   the query that produced the hit.
8. IF a Physical_Collection addressed by the assertion in criterion 3 or
   criterion 6 is unprovisioned, is provisioned and holds zero documents, or
   returns a query error, THEN THE Isolation_Probe SHALL report that assertion
   as failed and SHALL name that Physical_Collection, its Collection_Scope, and
   which of those three conditions was observed, distinguishing the
   unprovisioned condition from the provisioned-empty condition per Requirement
   7 criteria 3 and 4.

### Requirement 9: Accurate scope reporting in knowledge-base status

**User Story:** As an operator checking what a tenant can actually see, I want
the status report to list the shared collections alongside the tenant-prefixed
ones, so that the report stops implying that `gw_v17` has only five
collections.

#### Acceptance Criteria

1. WHERE the active Tenant's Index_Prefix is non-empty, WHEN the Status_Reporter
   runs, THE Status_Reporter SHALL list exactly the Physical_Collections that the
   Read_Router returns for that Tenant across the five Logical_Collections, and
   SHALL list no Physical_Collection outside those Resolved_Collection_Sets.
2. WHERE the active Tenant's Index_Prefix is non-empty, THE Status_Reporter SHALL
   label each listed Physical_Collection with the single Collection_Scope value
   that the Scope_Authority reports for the Logical_Collection that
   Physical_Collection resolves from, labelling both members a Hybrid_Domain
   contributes with that same value.
3. THE Status_Reporter SHALL compute the reported document total as the
   arithmetic sum of the document counts of the listed Physical_Collections,
   counting an unprovisioned Physical_Collection as zero, rather than from a
   Backend-reported aggregate that spans collections outside the listed set.
4. THE Status_Reporter SHALL omit from both the listing and the reported document
   total every Physical_Collection whose name carries an Index_Prefix that the
   tenant catalog declares for a Tenant other than the active one.
5. IF a listed Physical_Collection is present on the active Backend and holds
   zero documents, THEN THE Status_Reporter SHALL render a document count of zero
   for that Physical_Collection.
6. IF a Physical_Collection in the active Tenant's Resolved_Collection_Sets is
   absent from the active Backend, THEN THE Status_Reporter SHALL render that
   Physical_Collection as unprovisioned, distinguishable from the zero-document
   rendering required by criterion 5.
7. WHERE the active Tenant's Index_Prefix is non-empty, THE Status_Reporter SHALL
   omit from the listing and from the reported document total every
   Physical_Collection that is not a member of that Tenant's
   Resolved_Collection_Sets, including collections that serve ingestion
   bookkeeping rather than search, so that the byte-equivalent Default_Tenant
   block required by Requirement 6 criterion 3 is preserved.
8. IF one or more listed Physical_Collections are absent from the active Backend,
   THEN THE Status_Reporter SHALL render the document counts and Collection_Scope
   labels for the remaining listed Physical_Collections rather than returning an
   error result.

### Requirement 10: Accurate scope reporting in integrity checks

**User Story:** As an operator running an integrity check for one tenant, I want
the sample drawn from that tenant's reachable collections, so that the findings
describe that tenant rather than an unscoped mixture of all five.

#### Acceptance Criteria

1. WHEN the Integrity_Checker runs, THE Integrity_Checker SHALL draw at most
   `sample_size` document-metadata records, and SHALL draw them only from the
   union of the active Tenant's Resolved_Collection_Sets across all five
   Logical_Collections.
2. THE Integrity_Checker SHALL exclude from that sample every
   Physical_Collection that is not a member of the active Tenant's
   Resolved_Collection_Sets, including Physical_Collections carrying another
   Tenant's Index_Prefix and Physical_Collections that are not the resolution of
   any Logical_Collection.
3. THE Integrity_Checker SHALL name, in the rendered report, each
   Physical_Collection in the union together with the number of sampled records
   drawn from that Physical_Collection.
4. THE Integrity_Checker coverage-gap check SHALL compute its ingested-document
   count as the sum of the per-Physical_Collection document counts of every
   member of the active Tenant's Resolved_Collection_Sets, counting both the
   `shared` and the `tenant` members.
5. WHEN the Integrity_Checker runs without a `tenant_id` argument, THE
   Integrity_Checker SHALL draw its sample from the union of the
   Default_Tenant's Resolved_Collection_Sets across all five
   Logical_Collections, identically to criterion 1 and to every Tenant.

   **Resolved 2026-08-19 by `default-tenant-freeze-retirement` (SDD Phase 80).**
   The earlier amendment (Task 10/11 implementation) narrowed this criterion to
   preserve the legacy unscoped `sample_metadata(collection=None)` call for the
   Default_Tenant, because Requirement 6 criterion 3 required the no-`tenant_id`
   integrity response to remain byte-equivalent and the per-member reporting
   criterion 3 requires necessarily moves the rendered bytes, so both could not
   hold for the Default_Tenant. `default-tenant-freeze-retirement` removes that
   obstacle: it supersedes Requirement 6 criterion 3 with Structural_Equivalence,
   which is insensitive to per-member reporting text. The criterion is therefore
   restored to its original union-scoped form and applies to every Tenant, the
   Default_Tenant included. Actually scoping the Default_Tenant sampler is the
   second entry of that feature's Follow_Up_Sequence, performed under the
   quality-benchmark gate that feature builds; this restatement records the
   requirement, and that follow-up satisfies it in the code.
6. WHEN the union of the active Tenant's Resolved_Collection_Sets contains more
   than one Physical_Collection, THE Integrity_Checker SHALL limit any single
   member's contribution to `ceil(sample_size / member_count)` records for as
   long as another member holds unsampled records, and SHALL allocate the sample
   budget across members in an order identical across repeated invocations for
   the same `(Tenant, Embedding_Profile, sample_size)` triple.
7. IF a Physical_Collection in that union is absent or holds zero documents when
   the Integrity_Checker samples or counts it, THEN THE Integrity_Checker SHALL
   record that Physical_Collection as contributing zero records, and SHALL
   complete the remaining sub-checks and render the report using the remaining
   members.
8. IF `sample_size` is below 1 or above 1000, THEN THE Integrity_Checker SHALL
   use the nearest value within the range 1 to 1000 inclusive, and SHALL state
   the value used in the rendered report.

### Requirement 11: Accurate scope reporting in the health check

**User Story:** As an operator reading `mcp_health_check`, I want per-tenant
collection enumeration to route through the same resolution the query path uses,
so that the health view and the query behaviour cannot disagree.

#### Acceptance Criteria

1. WHEN the Health_Reporter runs, THE Health_Reporter SHALL obtain from the
   Read_Router an enumeration of Physical_Collections for the active Tenant
   equal to the union of the Read_Router's Resolved_Collection_Sets over the
   five Logical_Collections for the active Embedding_Profile, and SHALL report
   the vector-database collection count as the number of members of that
   enumeration.
2. WHERE the active Tenant's Index_Prefix is non-empty, THE Health_Reporter
   SHALL include in that enumeration the unprefixed Physical_Collection of every
   `shared` Logical_Collection.
3. THE Health_Reporter SHALL omit from that enumeration every
   Physical_Collection carrying the Index_Prefix of any Tenant in the tenant
   catalog other than the active Tenant.
4. WHEN the Health_Reporter runs with `functional=True` and the data state
   satisfies the Isolation_Probe assertions of Requirement 8 criteria 2 and 3,
   THE Health_Reporter SHALL report the Isolation_Probe result as passing.
5. WHERE the active Tenant's Index_Prefix is non-empty, THE Health_Reporter
   SHALL name each Physical_Collection in that enumeration together with its
   Collection_Scope.
6. IF a Physical_Collection in that enumeration is absent on the active Backend,
   THEN THE Health_Reporter SHALL name that Physical_Collection as
   unprovisioned, and SHALL report the vector-database component as degraded only
   where the absent Physical_Collection is the unprefixed Physical_Collection of
   a `shared` Logical_Collection.
7. IF the Isolation_Probe cannot execute when the Health_Reporter runs with
   `functional=True`, THEN THE Health_Reporter SHALL report the Isolation_Probe
   result as skipped, distinct from passing and from failing, with an indication
   of the blocking condition.

### Requirement 12: Write path left unchanged

**User Story:** As a maintainer of the ingestion pipeline, I want this change
confined to the read path, so that no re-ingestion is triggered and the
already-correct write-side naming stays untouched.

#### Acceptance Criteria

1. THE Collection_Namer SHALL produce the same observable result after this
   change that `resolve_collection_name` produces before this change — either a
   byte-identical Physical_Collection name or a rejection of the combination —
   for every `(domain, scope, tenant, version, profile)` combination drawn from
   the five Logical_Collection domains, both Collection_Scope values, every
   Tenant in the tenant catalog, the default collection version and one
   non-default collection version, and each Embedding_Profile named in the
   Glossary.
2. THE ingestion scripts under `mcp_server_python/scripts/`, and the helper
   modules in that directory that those scripts import, SHALL be byte-identical
   after this change to their content before this change.
3. THE Read_Router SHALL include every Physical_Collection already populated by
   the write path in the Resolved_Collection_Set for the Tenant that owns that
   Physical_Collection and the Embedding_Profile that ingested it, so that no
   re-ingestion of any Physical_Collection is required (Property P7).
4. IF this change modifies the Collection_Namer, a file named in criterion 2, or
   a Vector_Adapter's collection-creation or document-write behaviour, THEN THE
   design document SHALL name that modification, state why the read-path-only
   boundary does not hold, and state whether re-ingestion of any
   Physical_Collection becomes necessary.
5. WHEN a tool, the Read_Router, the Status_Reporter, the Integrity_Checker, or
   the Health_Reporter addresses a Resolved_Collection_Set, THE Vector_Adapter
   SHALL NOT create, delete, or write to any Physical_Collection, including an
   absent member of that Resolved_Collection_Set.
6. WHERE a module is consumed by both the Read_Router and the write path, THE
   read-path-only boundary SHALL classify that module as a shared module rather
   than as a write-path modification, provided the module satisfies criterion 1
   and does not depend on the Read_Router, the Vector_Adapters, or the tool
   modules; the Scope_Authority is the expected case.
7. THE automated test suite SHALL contain a check that fails when a file named
   in criterion 2 differs from its pre-change content or when the
   Collection_Namer's observable results differ from those required by
   criterion 1.

### Requirement 13: Verification evidence across backends and form factors

**User Story:** As a reviewer approving a data-plane refactor, I want evidence
from both backends rather than from one plus an assertion of symmetry, so that
the cross-platform claim is demonstrated rather than assumed.

#### Acceptance Criteria

1. THE test suite SHALL contain unit tests that, for each Logical_Collection
   that is not a Hybrid_Domain (`ee2-standards-v5-0-0-enhanced`,
   `community-summaries`, `code-with-context-v8-0-0`, `jjobs-v8-0-0`), for the
   Default_Tenant and for at least one Tenant whose Index_Prefix is non-empty,
   and for each of the Embedding_Profiles `titan1024` and `mpnet768`, assert
   that the Resolved_Collection_Set equals exactly `{resolve_index(collection,
   profile)}` where the Collection_Scope is `shared`, and equals exactly
   `{Index_Prefix + resolve_index(collection, profile)}` where the
   Collection_Scope is `tenant`.
2. THE test suite SHALL contain a unit test asserting that, for the
   Hybrid_Domain `global-workflow-docs-v8-0-0` under a Tenant whose
   Index_Prefix is non-empty, the Resolved_Collection_Set contains exactly two
   Physical_Collections, exactly one of which carries that Tenant's
   Index_Prefix and exactly one of which carries no Index_Prefix, and that a
   read against that set issues a query against both members.
3. THE test suite SHALL contain regression tests asserting the byte-equivalence
   required by Requirement 6 criterion 2 for at least one tool from each of
   `src/tools/semantic_search.py`, `src/tools/ee2_compliance.py`,
   `src/tools/graph_rag.py`, and `src/tools/operational.py`, each comparing the
   tool's rendered output against a baseline captured from the pre-change
   revision for one fixed query text and one fixed result limit, with the same
   recorded Backend responses supplied to the pre-change and post-change runs.
4. THE Verification_Record SHALL include an entry for a live invocation of
   `search_ee2_standards` with `tenant_id="gw_v17"` on the `aws` Backend under
   Form_Factor `agentcore` with Embedding_Profile `titan1024` that returned at
   least one standard, whose attribution header names Tenant `gw_v17`, and
   whose Routing_Diagnostic names the unprefixed Physical_Collection
   `mdc-ee2-standards-titan1024` with Collection_Scope `shared`.
5. THE Verification_Record SHALL include an entry for a live invocation of
   `search_documentation` with `tenant_id="gw_v17"` on the `aws` Backend under
   Form_Factor `agentcore` with Embedding_Profile `titan1024` that returned at
   least one hit naming `mdc-workflow-docs-titan1024` and at least one hit
   naming `gw_v17_mdc-workflow-docs-titan1024`, with each hit's originating
   Physical_Collection read from the name attached under Requirement 3
   criterion 5.
6. THE Verification_Record SHALL include an entry for a live invocation of one
   tool named in Requirement 2 criterion 6 on the `cots` Backend under
   Form_Factor `container` with Embedding_Profile `mpnet768` and a Tenant whose
   Index_Prefix is non-empty, that returned at least one hit naming the
   unprefixed `mpnet768` Physical_Collection of a `shared` Logical_Collection,
   and whose Routing_Diagnostic reports every absent Index_Prefix-prefixed
   member of the Resolved_Collection_Set as an unprovisioned collection rather
   than as a query failure.
7. THE test suite SHALL contain one executable property-based test for each of
   the correctness properties P1 through P10, each marked `property`, each
   generating at least 100 examples drawn from the five Logical_Collections,
   the Tenants declared in `src/config/tenants.yaml`, and the
   Embedding_Profiles `titan1024` and `mpnet768`, with `k` drawn from 1 to 1000
   for P10, and each executing against both `ChromaDBAdapter` and
   `OpenSearchAdapter` where the property references a Vector_Adapter.
8. THE Verification_Record SHALL be a single markdown file under
   `docs/reports/`, containing ASCII characters only and no credentials and no
   document body text, in which each live-invocation entry records the UTC
   timestamp, the `DB_BACKEND` value, the Form_Factor, the active
   Embedding_Profile, the tool name, the complete argument list including
   `tenant_id`, the resolved Tenant attribution header, every
   Physical_Collection named in the Routing_Diagnostic together with its
   Collection_Scope, the returned hit count, and at least one returned hit
   identifier, and in which each test-suite entry records the count of passed
   tests, the count of failed tests, the `DB_BACKEND` value the suite ran
   under, and the revision identifier of the code under test.
9. IF a live invocation required by criteria 4 through 6 cannot be executed
   because a Physical_Collection is unprovisioned or a Backend is unreachable,
   or an entry omits an item required by criterion 8, THEN THE
   Verification_Record SHALL mark the corresponding criterion as unmet, SHALL
   name the blocking condition, and SHALL identify the unit or property-based
   test that covers the same `(Logical_Collection, Tenant, Embedding_Profile)`
   triple in its place.

## Correctness Properties (for Property-Based Testing)

These properties are candidates for Hypothesis property-based tests written
during implementation. They are not acceptance criteria themselves but are
cross-referenced from the criteria above.

- **P1 — Prefix applies exactly when scope is tenant**: For every
  Logical_Collection `c` that is not a Hybrid_Domain, every Tenant `T`, and every
  Embedding_Profile `p`, every member of `Read_Router(c, T, p)` carries
  `T.index_prefix` if and only if `Scope_Authority(c) == "tenant"`. For a
  Hybrid_Domain `c` and a Tenant `T` whose Index_Prefix is non-empty,
  `Read_Router(c, T, p)` has exactly two members, the first carrying no
  Index_Prefix and the second carrying `T.index_prefix`, in that order.
  (Requirement 2 criteria 2-3, Requirement 3 criterion 1.)
- **P2 — Default-tenant identity**: For every Logical_Collection `c` and every
  profile `p`, `Read_Router(c, T_default, p) == {resolve_index(c, p)}` where
  `T_default.index_prefix == ""`. This holds for Hybrid_Domains as well: the
  empty Index_Prefix collapses the two members of Requirement 3 criterion 1 to
  the single unprefixed name, so the set has exactly one member. This is
  Property 3 (Empty-prefix passthrough) of `omd-tenants-1-foundation` lifted to
  the set-valued router. (Requirement 6 criteria 1 and 7.)
- **P3 — Backend invariance**: For every `(c, T, p)` triple,
  `Read_Router(c, T, p)` under `DB_BACKEND=aws` equals `Read_Router(c, T, p)`
  under `DB_BACKEND=cots`. (Requirement 4 criterion 1.)
- **P4 — Form-factor invariance**: For every `(c, T, p)` triple and every pair
  of configuration transports carrying equal content (environment variable
  versus mounted file), `Read_Router(c, T, p)` is equal across the pair.
  (Requirement 5 criteria 2-3.)
- **P5 — Cross-tenant disjointness of tenant scope**: For every pair of Tenants
  `A` and `B` with distinct non-empty Index_Prefixes and every
  Logical_Collection `c` with `Scope_Authority(c) == "tenant"`,
  `Read_Router(c, A, p)` and `Read_Router(c, B, p)` are disjoint.
  (Requirement 8 criteria 1-2.)
- **P6 — Universal reachability of shared scope**: For every Tenant `T` and
  every Logical_Collection `c` with `Scope_Authority(c) == "shared"`,
  `resolve_index(c, p)` is a member of `Read_Router(c, T, p)`.
  (Requirement 2 criterion 3, Requirement 5 criterion 5, Requirement 8
  criterion 3.)
- **P7 — Write-read round trip**: For every manifest source `s` with
  `(collection_target, scope)` and every Tenant `T` for which `s` was ingested,
  the Physical_Collection that `resolve_collection_name` produced for `(s, T)` is
  a member of `Read_Router(s.collection_target, T, p)` for the profile `p` that
  ingested `s`. Every collection the write path created is reachable by the read
  path for the Tenant that owns it. (Requirement 1 criterion 6, Requirement 12
  criterion 1.)
- **P8 — Reporting agreement**: For every Tenant `T`, the set of
  Physical_Collections the Status_Reporter lists, the set the Integrity_Checker
  samples, and the set the Health_Reporter enumerates are each equal to the
  union of `Read_Router(c, T, p)` over the five Logical_Collections `c`.
  (Requirement 1 criterion 4, Requirement 9 criterion 1, Requirement 10
  criterion 1, Requirement 11 criterion 1.)
- **P9 — Router purity**: For every `(c, T, p)` triple, repeated invocations of
  `Read_Router(c, T, p)` return equal Resolved_Collection_Sets and issue no
  Backend network request. (Requirement 3 criterion 6, Requirement 5
  criterion 1.)
- **P10 — Result-cap and provenance**: For every Resolved_Collection_Set and
  every `k` in `[1, 1000]`, a multi-collection read returns at most `k` hits and
  every returned hit names a Physical_Collection drawn from that set.
  (Requirement 3 criteria 4-5.)
