# Multi-Tenant Gap Tracker

Living document tracking the remaining gaps between the `gw` (develop) baseline
and non-default tenants (primarily `gw_v17`). Updated as gaps are resolved.

Last updated: 2026-06-11 (Gap J added: community-summaries pipeline blockers — feeds Q3 tech report on Neo4j↔Neptune + Node↔Python gaps)

## Summary Table

| # | Gap | Priority | Tenant(s) | Status | Spec / Fix | Notes |
|---|-----|----------|-----------|--------|------------|-------|
| A | `tenant_id` not exposed on tool schemas | HIGH | all | RESOLVED | `tenant-id-tool-exposure` [8.28.0] | Deployed v22, 2026-06-03 |
| B | Shell graph relationships incomplete for non-gw | LOW | gw_v17 | RESOLVED (data accurate) | `graph-port-shell-ops` (req+design done; no further code) | Investigated 2026-06-10 with live counts. v17 has 1,401 shell scripts vs gw's 315; absolute counts are mostly higher in v17 (SOURCES 928, INVOKES 1,767, EXPORTS 6,064, DEPENDS_ON_ENV 20,434, DEFINES 337). Per-script density is lower in v17 because JEDI/CRTM submodules dominate its script population — those scripts are simpler (CI helpers, build/doc utilities) with few cross-references, not an ingest gap. Re-ran shell→fortran bridge: EXECUTES 11→12 (16 attempts, 36 unmatched refs to non-graph executables). 23 v17 orphan scripts confirmed legitimate standalone third-party utilities. READS_CONFIG works correctly via `re.compile(r'config\.(\w+)')`; low counts reflect the data, not a parser bug. No re-ingest needed. |
| C | Graph queries used hardcoded labels / no tenant= | HIGH | all non-gw | RESOLVED | [8.30.0] commit `9c66084` | Deployed v29, 2026-06-08. |
| D | Rewriter mangled relationship types for non-gw | HIGH | all non-gw | RESOLVED | [8.31.0] commit `a8f76ec` | `_rewrite_cypher` prefixed `:CALLS` → `:GW_V17_CALLS`. Now bracket-aware. Was the real root cause behind much of what looked like "Gap B empty results". Deployed v30, 2026-06-08. Verified: v17 shows 934,873 rels; find_callers_callees works. |
| E | Label-less graph queries leak across tenants | LOW | all non-gw | RESOLVED | [8.32.0] commit `9d64b53` | `tenant_label_predicate()` scopes label-less / name-anchored queries via `labels(n)` (tenant_id property is unreliable — null on placeholder nodes). Applied to ~16 queries in graph_rag.py + code_analysis.py. Deployed v31, 2026-06-08. Verified: setuprad resolves to GW_V17_File for v17, FortranSubroutine for gw. |
| F | Fortran parse failures (15% / 1,020 files) | MEDIUM | gw_v17 | RESOLVED | `fortran-parse-fallback` [8.33.0] `7c77ffd` + parallel/streaming [8.34.0] `1520577` | Regex fallback + parallel streaming ingest. Live ingest run 2026-06-10: 6,926/6,935 parsed (99.9%), 45,155 nodes + 297,712 rels written, 0 errors, ~3.2h. v17 graph now 80,996 nodes / 1,278,330 rels (CALLS 1.02M, USES 229K). No deploy — offline script. |
| G | Deep traversal OOMs on Neptune | MEDIUM | gw, gw_v17 | RESOLVED | `bounded-graph-traversal` [8.36.0] commits `fc6ad31..f09c66b` | Pre-flight degree probe + depth cap + 30s statement-timeout backstop on `NeptuneAdapter.query`. Deployed v32 (`python-tenants-v8`), 2026-06-10. Verified live: `find_callers_callees("setuprad", gw_v17)` short-circuits cleanly (degree 174 > threshold 100); `trace_full_execution_chain("JGLOBAL_FORECAST", gw)` falls through to timeout backstop with one-hop Degraded_Result; non-hub `setuprad` `get_code_context` unchanged. |
| H | No tenant-specific docs collection | BY DESIGN | non-gw | REVISIT | — | See detail below. Docs are branch-agnostic (RTD, EE2 standards, etc.) but v17 has unique repo-local documentation. Current state: `gw_v17_mdc-workflow-docs-titan1024` holds 10,523 docs (v17-specific on-disk content from the code tree). A `shared_indices` config is the next step — see Gap H detail. |
| I | v17 vector indices had float mapping (not knn_vector) | HIGH | gw_v17 | RESOLVED | `v17-knn-vector-reindex` [8.36.2 deploy + ops] | See detail below. |
| J | Community-summaries pipeline not portable to Neptune / not ported to Python / not tenant-aware | MEDIUM | gw_v17, all non-gw | OPEN | — | See detail below. Three intersecting gaps: (1) Neo4j GDS Leiden vs Neptune's no-GDS surface; (2) `mcp_server_node/` JS pipeline never ported to Python; (3) no `--tenant` plumbing in any of the four pipeline stages. Captures intrinsic Neo4j↔Neptune gaps for the Q3 technical report. |

## Detail: Open Gaps

### Gap B — Shell graph relationships for v17

**What's missing:** The shell graph ingester (`ingest_shell_graph_v8.py`) creates
SOURCES, INVOKES, EXECUTES, DEFINES, IMPORTS, EXPORTS, and DEPENDS_ON_ENV edges
by parsing shell scripts. This has run for `gw` (the develop baseline) but NOT
for `gw_v17`.

**Impact:** `find_dependencies`, `find_callers_callees`, `trace_execution_path`,
`trace_full_execution_chain` all return empty for shell-script relationships in
v17. Fortran CALLS/USES/CONTAINS edges DO exist (230K from the 37-hour Fortran
ingestion run) — but the shell→Fortran bridge (EXECUTES) only has 15 edges
(from a quick bridge run).

**Fix:** Run `ingest_shell_graph_v8.py --tenant gw_v17 --mode full`. The spec
`graph-port-shell-ops` has requirements and design complete; tasks are pending.

**ETA:** ~4-8 hours runtime (1,401 shell scripts to parse).

---

### Gap D — Rewriter mangled relationship types (RESOLVED 2026-06-08)

**Symptom:** `get_knowledge_base_status(tenant_id="gw_v17")` reported
`Total Relationships: 0` even though Neptune has 738K+ CALLS edges for
`GW_V17_FortranSubroutine` nodes.

**Actual root cause:** The `_rewrite_cypher` label rewriter in `neptune_adapter.py`
used a regex (`:([A-Za-z_]...)`) that matched ALL colon-tokens — including
relationship types inside `[...]`. So `MATCH (s:File)-[r:CALLS]->()` was rewritten
to `MATCH (s:GW_V17_File)-[r:GW_V17_CALLS]->()`. Neptune only prefixes node labels,
not relationship types, so `:GW_V17_CALLS` matched nothing → count 0.

**Confirmed via debug harness:** running `_safe_relationship_counts` against live
Neptune returned `[]` in 0.5s (not a timeout — a logic bug). The Neptune MCP server
confirmed the *correct* (unmangled) queries return 738K in ~1.2s.

**Fix:** Made `_label_token_offsets` bracket-aware via a new `_square_bracket_mask`
helper. Tokens inside `[...]` (relationship types) are skipped; only node labels
get prefixed. [8.31.0].

**Broader impact:** This bug silently broke ALL relationship-traversal queries for
non-gw tenants (`find_related_files`, `find_callers_callees`, `trace_execution_path`,
etc.), not just the count display. Much of what was attributed to "Gap B — missing
relationships" was actually this rewriter bug masking relationships that DO exist.

---

### Gap E — Label-less queries (RESOLVED in code 2026-06-08)

**Symptom:** Label-less queries (`MATCH (n) WHERE n.name = $name`) and
name-anchored relationship queries matched nodes from ANY tenant — the
label-prefix rewriter only acts on `:Label` tokens, of which these have none.
A `gw_v17` lookup could surface `gw` baseline nodes and vice versa.

**Why not tenant_id property:** The obvious fix (filter `n.tenant_id = $tid`)
is unreliable. Confirmed in Neptune: 4,168 of 29,605 `GW_V17_FortranSubroutine`
nodes have `tenant_id = null` (placeholder nodes the Fortran ingester's CALLS
MERGE creates without the property), and several label types
(`GW_V17_EnvironmentVariable`, `GW_V17_ShellFunction`, `GW_V17_DataDependency`)
carry no `tenant_id` at all. All gw baseline nodes also have null. The **label**
is the only reliable discriminator.

**Fix:** `tenant_label_predicate(var)` in `resolver.py` builds a `labels(n)`-based
WHERE fragment using Neptune's list-comprehension `size([l IN labels(n) WHERE
l STARTS WITH '<prefix>'])`:
- Non-default tenant: `... > 0` (node owns a label with the tenant's prefix).
- Default gw: `... = 0` over all OTHER tenant prefixes (node is base/unprefixed).

Applied via a `_scope_and(var)` helper to ~16 leaky queries across
`graph_rag.py` and `code_analysis.py`. For name-anchored relationship queries,
only the named anchor needs scoping (edges are within-tenant). [8.32.0].

**Verified live:** the `setuprad` lookup that returned 5 nodes across both tenants
now returns 2 (v17) or 3 (gw) correctly.

---

### Gap F — Fortran parse fallback

**Problem:** fparser2 fails on 15% of Fortran files (1,020 of 6,935 in v17).
Common failure modes: deeply nested preprocessor logic, non-standard extensions,
OpenMP directives, C interop patterns.

**Impact:** ~50K potential CALL/USE relationships unextracted from those files.

**Proposed fix:** Regex-based fallback that scans for `CALL subroutine_name` and
`USE module_name` patterns when fparser2 returns None. Won't get line numbers or
containment, but captures the relationship edges.

**Spec status:** Directory exists at `.kiro/specs/fortran-parse-fallback/` but
requirements.md not yet written.

---

### Gap G — Deep traversal OOM / timeout

**Problem:** `trace_execution_path` and `trace_full_execution_chain` with
highly-connected nodes (JGLOBAL_FORECAST has 500+ direct edges) can cause Neptune
to timeout or return massive result sets that blow the MCP response size.

**Fix:** Add configurable `max_fan_out` (default 50) and `max_depth` cap (default 3)
in the traversal queries. Drop to summary mode when a node exceeds the fan-out
threshold.

---

## Resolved Gaps (for reference)

### Gap A — tenant_id tool exposure (RESOLVED 2026-06-03)

24 tenant-scoped tools now expose `tenant_id: str | None = None` in their FastMCP
schema. Commit `ca44057`, version [8.28.0], deployed as v22.

### Gap C — Label-prefix scoping in graph queries (RESOLVED 2026-06-08)

Graph tools (get_knowledge_base_status, list_job_scripts, get_job_details,
explain_workflow_component) were returning gw baseline data regardless of tenant.
Fixed by adding `tenant=` passing and restructuring label-less queries to use
proper MATCH labels. Commit `9c66084`, version [8.30.0], deployed as v29.


---

### Gap H — Shared vs tenant-specific documentation indices (REVISIT)

**Original design (BY DESIGN):** All tenants share the gw baseline's documentation
vector indices (`mdc-workflow-docs-titan1024`, `mdc-ee2-standards-titan1024`, etc.)
because URL-crawled docs (RTD, EE2 standards, Spack, UFS model docs) are
branch-agnostic — the same content regardless of which branch you're developing on.

**Revised understanding (2026-06-11):** v17 is a coupled-model system with
substantially more submodules (JEDI, CRTM, UFS, MOM6, CICE, WW3, etc.) than the
`develop` baseline. Its repo tree contains unique on-disk documentation that does
NOT exist on `develop` — build guides, physics configuration references, coupling
interface docs, submodule-specific READMEs. The v17 code ingester captured 28,325
of these into `gw_v17_mdc-code-context-titan1024`, and the docs ingester captured
10,523 into `gw_v17_mdc-workflow-docs-titan1024` (repo-local content, not URL-crawled).

This means the tenant-prefixed docs index is NOT purely redundant — it holds v17-
specific content that the shared gw baseline docs do not have. The URL-crawled
external docs (RTD, Spack, etc.) ARE shared, but the repo-local docs are unique
per branch.

**Next step (config-driven shared_indices):** Add a `shared_indices` list to the
tenant model (in `tenants.yaml` or a sibling config) that names collections whose
**external/URL-crawled** content should fall through to the unprefixed gw baseline
index rather than the (empty) tenant-prefixed copy. For collections that also have
repo-local content (like `workflow-docs`), the adapter would fan out to BOTH the
shared baseline AND the tenant-prefixed index, then merge/dedupe results.

Candidate shared collections (v17 has no tenant-specific content in these):
- `mdc-ee2-standards-titan1024` — EE2/NCO standards are org-wide, not branch-specific.
- `mdc-community-summaries-titan1024` — community detection output is graph-derived
  (already tenant-scoped via the graph, not via the vector index).

Candidate hybrid collections (shared external + unique repo-local):
- `mdc-workflow-docs-titan1024` — RTD docs are shared, but v17 repo-local docs are unique.

This is a MEDIUM priority follow-up. The current state works (v17 has its own docs
index with repo-local content; the shared external docs are missing from it but
available via the gw baseline if the caller omits `tenant_id`). The fix would make
`search_documentation(tenant_id="gw_v17")` transparently include both sources.

---

### Gap I — v17 vector indices had float mapping (RESOLVED 2026-06-11)

**Symptom:** After `opensearch-tenant-resolution-fix` [8.36.2] corrected the index
resolution order, queries reached the v17 indices but returned
`RequestError(400, Field 'embedding' is not knn_vector type)`.

**Root cause:** `create-opensearch-indices.js` had no `--prefix` parameter, so
tenant-prefixed indices were never pre-created with the correct `knn_vector`
mapping. When the v17 bulk ingestion ran, OpenSearch auto-created the indices with
dynamic mapping that maps float arrays as `float` type. OpenSearch does not allow
changing a field's mapping type on a live index.

**Fix:** Added `--prefix` to `create-opensearch-indices.js` (commit `2a2693d`).
Operator steps: deleted broken indices, cleared stale dedupe registry entries,
recreated with correct knn_vector mapping (`--prefix gw_v17_ --model titan1024`),
re-ingested all three collections.

**Additional finding:** The code ingester hardcodes `gw_v17_mdc-code-titan1024`
(no `-context-`), but queries resolve to `gw_v17_mdc-code-context-titan1024`.
Resolved via alias reversal: data lives in the correctly-named
`gw_v17_mdc-code-context-titan1024`, with a thin write-alias
`gw_v17_mdc-code-titan1024 → gw_v17_mdc-code-context-titan1024` routing the
ingester's writes. Rule 3.6 (no ingester code changes) preserved.

**Final state (2026-06-11):**

| Index | Docs | Mapping |
|---|---|---|
| `gw_v17_mdc-code-context-titan1024` | 28,325 | knn_vector ✓ |
| `gw_v17_mdc-workflow-docs-titan1024` | 10,523 | knn_vector ✓ |
| `gw_v17_mdc-jjobs-titan1024` | 92 | knn_vector ✓ |
| `gw_v17_mdc-community-summaries-titan1024` | 0 (empty, correctly mapped) | knn_vector ✓ |
| `gw_v17_mdc-ee2-standards-titan1024` | 0 (empty, correctly mapped) | knn_vector ✓ |

**Verified live:** `find_similar_code("setuprad", tenant_id="gw_v17")` returns
ranked hits. `search_documentation("GEMPAK", tenant_id="gw_v17")` returns hits.
Default-tenant (`gw`) preservation confirmed unchanged.


---

### Gap J — Community-summaries pipeline (Neo4j↔Neptune, Node↔Python, multi-tenant)

**Status:** OPEN. Slated for Q3 work — feeds the technical report on intrinsic
graph-engine and runtime-port gaps.

**Symptom (today):** `gw_v17_mdc-community-summaries-titan1024` exists (correctly
mapped, 0 documents). Calls to `search_architecture(tenant_id="gw_v17")` and
`get_code_context(tenant_id="gw_v17", include_community=True)` return clean
`[INFO] Skip_Block` diagnostics via the `graceful-missing-index-handling` fix,
but they cannot return real subsystem-level summaries because the index is
empty. The gw baseline has 2,113 community summaries; v17 has zero.

**Background — what community-summaries are.** A graph-derived view of the
codebase. The pipeline:

1. **Leiden community detection** runs on the graph and assigns a `communityId`
   to every node, grouping files / functions / modules into clusters that
   interact with each other more densely than with the rest of the graph
   (modularity-maximising partitioning).
2. **Community node materialisation** writes hierarchical `Community` nodes
   into the graph with `MEMBER_OF`, `PARENT_OF`, and `INTERACTS_WITH` edges.
3. **LLM summarisation** feeds each community's structure (member names,
   dominant labels, interaction patterns) to a generative model and produces
   a 4-8 sentence prose description of what that subsystem does.
4. **Embed + import** writes the summary text + Titan embedding into the
   `community-summaries` vector index, keyed by `community-L<level>-<id>`.

For gw, this surfaces architectural communities like "GSI EnKF", "atmospheric
forecast model", "shell script source dependency graph" (real examples from
the gw benchmark ground truth at
`mcp_server_node/scripts/config/benchmark_ground_truth.json`).

**Three intersecting blockers (the Q3 tech report's spine):**

#### Blocker 1 — Neo4j Graph Data Science vs Amazon Neptune

The existing pipeline (`mcp_server_node/scripts/run_community_detection.js`,
`mcp_server_node/src/graphrag/CommunityDetection.js`) assumes a Neo4j graph
with the **Graph Data Science (GDS) plugin** and calls procedures like
`gds.graph.project`, `gds.leiden.write`, and `gds.louvain.stream`. The
deployed graph is **Amazon Neptune**, which:

- Speaks openCypher (mostly compatible) and Gremlin (fully).
- Does **not** ship the GDS plugin. Neptune has no `gds.*` procedure surface.
- Does not expose modularity-optimising community detection as a server-side
  primitive at all — `gds.leiden`, `gds.louvain`, `gds.wcc`, the entire
  algorithm catalog is absent.

This is an **intrinsic engine-feature gap**, not a bug. The pipeline was
designed against Neo4j's algorithm catalog and the Q1 migration to Neptune
moved the data without a feature-parity port. Three options for the Q3 fix:

- **Option A — External Leiden, in-process import:** Export the v17 graph (or
  any tenant's graph) via openCypher, run Leiden in Python using
  `leidenalg` + `igraph` or `networkx` + `python-louvain`, then write
  `communityId` properties + `Community` nodes back to Neptune via
  parameterised openCypher updates. This is the most faithful reproduction of
  the gw pipeline's output.
  - Trade-off: extra hop through a Python process, but the algorithm runs on
    a host with full memory access and is well-tested in the scientific
    Python ecosystem.
  - Estimated wall-clock: ~10-30 min for v17's 80K-node / 1.28M-rel graph
    (Leiden is near-linear in edges).
- **Option B — Native Neptune approximations:** Neptune supports
  weakly-connected-components-style traversals via openCypher path queries,
  but these are not modularity-optimising. The output would be coarser
  components rather than communities. Lower quality but no external runtime.
- **Option C — Migrate to Neptune Analytics:** AWS's separate analytics
  graph service does include some community detection algorithms (WCC, label
  propagation, weakly-connected components). Not Leiden specifically. Also
  involves a second graph store (data duplication, sync cost) and wasn't in
  scope for the Q1 migration.

**Recommendation for Q3:** Option A. It preserves output parity with the gw
pipeline (same Leiden algorithm → same modularity quality → same downstream
benchmark queries), runs offline (no operational dependency), and the Python
graph stack is mature.

#### Blocker 2 — Node.js → Python port not done

All four pipeline stages live in `mcp_server_node/`:

| Stage | File | Status |
|-------|------|--------|
| Community detection (Leiden) | `mcp_server_node/src/graphrag/CommunityDetection.js` | Node only; depends on Neo4j GDS |
| Pipeline runner | `mcp_server_node/scripts/run_community_detection.js` | Node only |
| LLM summary generation | `mcp_server_node/scripts/generate_llm_summaries.js` | Node only |
| Vector import | `mcp_server_node/scripts/import_llm_summaries.js` | Node only |

The Python port (`mcp_server_python/`) has placeholders only:
- `mcp_server_python/src/manifest/models.py` declares `SourceType.COMMUNITY_SUMMARY`.
- `mcp_server_python/src/config/unified_manifest.json` lists
  `"community-summaries"` as a manifest source pointing at
  `scripts/import_llm_summaries.js` (the Node script — it has not been
  re-pointed at a Python equivalent).
- No `mcp_server_python/scripts/ingest_community_summaries.py` exists.
- No `mcp_server_python/src/graphrag/community_detection.py` exists.

**Why the port matters:** every other ingester has been ported to Python so
the v8 pipeline can run with a single runtime, single dependency tree, and
the tenancy plumbing (`--tenant`, label-prefix awareness, dedupe registry
keyed by `(collection, sha)` per tenant) that landed in Q2. The community-
summaries pipeline is the last stage still anchored to the Node toolchain.

**Recommendation for Q3:** Port the four stages to Python with the same shape
as the existing v8 ingesters (`ingest_documentation_v8.py`, `ingest_code_v8.py`,
`ingest_jjobs_v8.py`):
- `mcp_server_python/src/graphrag/community_detection.py` — wraps `leidenalg`
  + Neptune export/import.
- `mcp_server_python/src/graphrag/community_summarizer.py` — Bedrock
  Claude/Nova call that produces a 4-8 sentence summary per community.
- `mcp_server_python/scripts/ingest_community_summaries.py` — pipeline runner
  with `--tenant`, `--model`, `--mode {full,diff}` matching the other
  ingesters' interface.
- Update `unified_manifest.json` to point at the new Python script.

#### Blocker 3 — No tenant awareness in any pipeline stage

Even if Blockers 1 and 2 were resolved, the existing scripts have no
`--tenant` parameter. Concretely:

- The detection stage writes `communityId` properties to nodes via plain
  openCypher / Cypher — no label prefix, no tenant filter.
- The summariser reads `Community` nodes by label only — would mix gw and
  gw_v17 communities together if both ran.
- The importer writes to the unprefixed `community-summaries` collection — no
  `gw_v17_` prefix on the OpenSearch index name.

The Python ports of `ingest_documentation_v8.py` and friends already solved
this (label-prefix aware Cypher rewriter, tenant-prefixed OpenSearch indices,
per-tenant dedupe registry keys). The community-summaries pipeline needs the
same plumbing applied:
- Detection writes `${prefix}_Community` labels and tenant-scoped
  `communityId` properties.
- Summariser scopes its read query to the active tenant's prefix via
  `tenant_label_predicate()`.
- Importer respects `OpenSearchAdapter.resolve_tenant_index` so summaries
  land in `gw_v17_mdc-community-summaries-titan1024` (already correctly
  knn_vector-mapped).

#### Cost factors (per tenant, one-time)

- **Leiden run:** ~10-30 min for an 80K-node / 1.28M-rel graph (v17 size).
- **LLM summary calls:** ~1,000-1,500 communities × 1 Bedrock call each.
  Estimated $1-5 per tenant in Bedrock spend.
- **Embedding calls:** ~1,000-1,500 Titan embed-text-v2 calls. Cents per
  tenant.
- **Vector ingestion:** seconds.
- **Total wall-clock:** roughly 1-2 hours per tenant if calls are sequential,
  20-40 min with reasonable concurrency.

#### Why this matters for the Q3 technical report

This gap is the cleanest example of three intersecting cross-cutting
concerns the platform has accumulated:

1. **Engine-feature parity** between Neo4j (Q0 baseline) and Neptune (Q1
   migration target). Where Neo4j ships an algorithm catalog as part of the
   product, Neptune treats community detection as a client-side or
   sister-service concern. The pipeline either runs externally (Option A) or
   adopts a different algorithm (Option B) or a different graph product
   (Option C). All three are documentable trade-offs.
2. **Runtime port completeness** between `mcp_server_node/` (Q0/Q1) and
   `mcp_server_python/` (Q2). Eight of nine ingesters ported, one
   outstanding. The community-summaries pipeline is the canonical "long
   tail" port artefact and demonstrates the cost of partial ports.
3. **Multi-tenancy retrofit** of pipelines that were originally
   single-tenant. The same `--tenant` plumbing pattern (resolver +
   label-prefix rewriter + index-prefix translator + dedupe-registry
   key composition) applied to ingest_code, ingest_documentation,
   ingest_jjobs, and the shell-graph ingester needs one more application
   here.

#### Spec sequencing for Q3

A single spec (`v17-community-detection`, or more generally
`tenant-community-detection-port`) should:
- Land Blocker 2's Python port + Blocker 3's tenant awareness as the code
  change.
- Land Blocker 1's external Leiden as the operator step (run for gw and
  gw_v17 simultaneously, populate both `mdc-community-summaries-titan1024`
  and `gw_v17_mdc-community-summaries-titan1024`).
- Capture the Neo4j↔Neptune trade-off discussion as a design-doc artefact
  the Q3 tech report can lift directly.

#### Reference state (today, 2026-06-11)

- gw `mdc-community-summaries-titan1024`: 2,113 docs (populated via Q1
  Node pipeline against the original Neo4j deployment, then migrated)
- v17 `gw_v17_mdc-community-summaries-titan1024`: 0 docs (correctly
  knn_vector-mapped; ready to receive content once the pipeline runs)
- Other non-gw tenants: same as v17 — index exists, empty, ready.
