# Phase 54: OMD Multi-Program MCP Initiative

**Version**: 0.1.0 (Draft Initiative)
**Status**: Draft
**Created**: 2026-05-06
**Author**: AI Assistant + Terry McGuinness
**Type**: Initiative (multi-phase; spawns `phase54a_*` … `phase54f_*` execution specs)
**Dependency**: Phase 11E (n8n / orchestration), Phase 26 (Docker MCP Gateway), Phase 53 (Gateway Tool Quality)
**Related**: Phase 4d (Multi-tenant SDD workspaces), Phase 52 (v17 paradigm coverage)

---

## 1. Executive Summary

The **NOAA Office of Modeling Development (OMD, formerly EMC)** maintains a
portfolio of modeling programs that increasingly need first-class AI/RAG
support — not just the `global-workflow` system that the current
`eib-mcp-rag` server was built for. The portfolio includes at minimum:

- **`global-workflow:develop`** — operational GFS/GEFS line (current focus).
- **`global-workflow:gfsv17-coupled`** — divergent branch in the *same*
  repository, driving the next-generation coupled GFS. 
  AI agents indexing the repo cannot tell which branch's code
  they are reasoning about, and answers cross-contaminate.
- **UFS** — the Unified Forecast System, a shared component embedded inside
  multiple downstream programs.
- **MPAS** — Model for Prediction Across Scales, a separate modeling
  program that *contains UFS components* and will need its own GraphRAG
  surface when onboarded to the platform.
- Future OMD programs as the portfolio grows.

The current architecture has **one monolithic MCP server** (`eib-mcp-rag`)
ingesting one branch of one repo into one Neo4j database and one set of
ChromaDB collections. There is no way to ask the platform *"reason about
the v17 coupled branch"* or *"reason about MPAS"* without re-pointing the
entire server. This Initiative establishes the architecture and execution
plan to **decompose that monolith into program-scoped MCP tenants** —
one per OMD program, with shared-component inheritance, branch-scoped
isolation, and a router that helps agents pick the right tenant.

A secondary capability (third-party MCP discovery with a headless secret
broker) is included because it shares the catalog/auth machinery that the
multi-tenant arm needs and because it unlocks several adjacent OMD
workflows (literature review, external dataset ingestion). It is
intentionally framed as **supporting**, not leading.

## 2. Driving User Stories

### 2.1 OMD Configuration Manager (primary driver)

> *As a* repo configuration manager juggling `global-workflow:develop`,
> `global-workflow:gfsv17-coupled`, `ufs`, and `mpas`,
> *I want* one gateway URL where each program is a distinct MCP server
> (`gw-mcp`, `gw-v17-mcp`, `ufs-mcp`, `mpas-mcp`) with its own graph DB
> and Chroma collection, and where shared components (UFS) are referenced
> from a single source of truth,
> *so that* an agent working a v17-coupled bug never sees `develop`-branch
> code, an MPAS agent transparently inherits UFS tools, and divergence
> between branches stops causing cross-contaminated answers.

### 2.2 OMD Program Lead (portfolio expansion)

> *As an* OMD program lead onboarding a new model (e.g., MPAS, RRFS, HAFS)
> to the platform,
> *I want* a documented "tenant template" that defines what a new program
> needs (repo reference, ingestion config, optional `extends:` parent,
> auth requirements),
> *so that* onboarding a new program is a configuration change, not a
> code change to `eib-mcp-rag`.

### 2.3 OMD Researcher (supporting story — third-party MCPs)

> *As an* OMD researcher writing a forward-looking technical document,
> *I want* the agent to autonomously discover, authenticate to, and call
> third-party knowledge MCPs (arXiv, Semantic Scholar, OpenAlex) through
> the same gateway,
> *so that* literature review and citation discovery are part of the same
> conversation as the code analysis, without me hand-managing API keys.

## 3. Scope

### 3.1 In Scope — Six Workstreams

| ID | Workstream | Primary arm | Outcome |
|----|------------|-------------|---------|
| **54a** | Tenant catalog schema | Multi-program | Define the YAML schema for an OMD program tenant: `tenant_id`, `repo_ref`, `branch`, `extends:`, `neo4j_database` / `neo4j_label_prefix`, `chroma_collection_prefix`, `secrets:` block. |
| **54b** | Per-tenant data isolation | Multi-program | Implement isolation in the data layer: per-tenant Neo4j scoping (DB or label prefix per R6 outcome) and per-tenant Chroma collection prefixes. Re-package the existing 52 tools to honor `tenant_id`. |
| **54c** | Shared-component inheritance (`extends:`) | Multi-program | Allow `mpas-mcp` to declare `extends: [ufs-mcp]` and inherit UFS tool results without duplicate ingestion. Decision required on resolution semantics (catalog-time merge vs query-time fan-out — see R7). |
| **54d** | Branch-scoped tenants & ingestion dedupe | Multi-program | `gw-mcp` (develop) and `gw-v17-mcp` (gfsv17-coupled) coexist as separate tenants pointing at the same Docker image with different `WORKFLOW_REF` env vars. Content-addressed dedupe so the overlap doesn't double storage (R8). |
| **54e** | Tenant routing & attribution | Multi-program | Agent-facing `which_program(file_or_topic)` recommender; gateway-side `tenant_id` tag on every tool response so agents and audit logs can attribute results. |
| **54f** | Headless auth broker + 3rd-party MCP pilot | Supporting | Replace Docker-Desktop secrets with a Linux-native broker (`age`/`sops` or Vault); pilot one no-key MCP (`arxiv-mcp-server`) and one keyed MCP (`semantic-scholar-mcp`) to exercise the broker end-to-end. Catalog/auth schema reused from 54a. |

### 3.2 Stretch / Future Phase

- **Cross-tenant query federation** — *"find this symbol across UFS and MPAS"* — designed-for in 54a/54c schema but a separate execution phase.
- **Tenant lifecycle CLI** — `eib-tenant create mpas --extends ufs --branch main`.
- **Audit log** — who-invoked-which-tool-on-which-tenant (compliance prerequisite for any NCO-adjacent deployment).
- **Per-MCP rate-limit / cost caps** enforced at the broker layer (54f).
- **OAuth 2.0 device-code flow** for third-party MCPs that need interactive consent.
- **Tenant promotion workflow** — a tenant matures from `experimental` → `staging` → `production` with gating criteria.

### 3.3 Explicitly Out of Scope

- Re-introducing Docker Desktop on the gateway host.
- Re-implementing the existing `eib-mcp-rag` tool surface — 54b *re-packages* the existing 52 tools to be tenant-aware; their behavior is unchanged.
- Migrating away from Neo4j or ChromaDB — 54b uses native multi-DB / collection-prefix features (or label namespacing per R6).
- Onboarding non-OMD programs in v1.
- Any third-party MCP requiring a paid plan beyond a free tier.

## 4. Acceptance Criteria

The Initiative is **DONE** when all of the following hold on the production
gateway:

### 4.1 Multi-program arm (54a–54e)

1. The catalog lists ≥4 OMD program tenants: `gw-mcp`, `gw-v17-mcp`, `ufs-mcp`, `mpas-mcp` (the last may be staged per R10).
2. **Branch-isolation probe**: querying `analyze_code_structure` on a file that exists in *both* `develop` and `gfsv17-coupled` returns different content from `gw-mcp` vs `gw-v17-mcp`, each correctly matching its branch.
3. **Inheritance probe**: `mpas-mcp.find_callers_callees` on a UFS symbol returns results without `ufs-mcp` being explicitly added in the same session (transitive `extends:` resolution).
4. **Tenant attribution**: every response from any tenant carries a `tenant_id` field; audit-log entries reference it.
5. **CM-hazard regression**: an agent prompt *"summarize the v17 coupled forecast driver"* never returns code from the `develop` branch (verified by file-path inspection).
6. **Onboarding cost**: adding a fifth tenant (e.g., RRFS) is documented as a catalog-only change; no edits to `eib-mcp-rag` source code required.

### 4.2 Supporting arm (54f)

7. `mcp-find arxiv` on the production gateway returns ≥1 result (today: 0 — verified 2026-05-06).
8. `mcp-config-set` rejects a config that omits a required secret with a schema-validation error (today: silently accepts arbitrary JSON — verified 2026-05-06).
9. The agent runs ≥10 chained `search_papers` / `get_paper_details` calls against `semantic-scholar-mcp` without manual key intervention.
10. Gateway restart preserves the catalog, the secret store, and any saved tenant configurations. No manual re-bootstrap.

## 5. Risks & Open Questions

| # | Risk / Question | Owner |
|---|-----------------|-------|
| R1 | **Neo4j multi-DB licensing** — Neo4j 5.x Community supports only the default `neo4j` DB; multi-DB requires Enterprise. Per-tenant Chroma collections work today, but per-tenant Neo4j may force an alternate isolation strategy (label namespacing, separate Bolt instances on different ports, or Memgraph). | Spike in 54b |
| R2 | **`extends:` resolution semantics** — does `mpas-mcp extends: [ufs-mcp]` resolve at *catalog* time (UFS tools merged into the MPAS server's tool list) or at *query* time (MPAS server fans out to UFS server per call)? Former is simpler, latter scales better. | 54c design |
| R3 | **Branch-divergence ingestion cost** — `gw-mcp` and `gw-v17-mcp` will mostly overlap. Naive ingestion doubles ChromaDB storage and Neo4j node count. Need content-addressed dedupe or symlink ingestion. | 54d |
| R4 | **Tenant discovery UX** — if the agent has to learn 4+ tenants up front, prompt overhead grows. The `which_program` router (54e) is on the critical path, not a nice-to-have. | 54e |
| R5 | **MPAS repo readiness** — MPAS is not yet in `supported_repos/`. 54a acceptance criterion 1 may need to be staged: (a) `gw-mcp` + `gw-v17-mcp` first; (b) `ufs-mcp`; (c) `mpas-mcp` after the MPAS submodule lands. | Terry / OMD |
| R6 | **Headless secret store choice** — `age`/`sops` (file-based, simpler) vs HashiCorp Vault (network-based, scales better) — which is acceptable to NCO security review? | 54f / Terry |
| R7 | **Gateway binary support for custom secret broker** — does the `docker mcp gateway` binary honor a custom secret-store URL, or do we need to fork it? | Spike in 54f |
| R8 | **`--enable-all-servers` regression** — re-enabling dynamic discovery re-opens the path that v7.1.8 closed (Docker Desktop `/.s0` socket). Need a regression test that the gateway still starts headless before merging. | 54f |
| R9 | **Stakeholder alignment** — OMD program leads beyond global-workflow have not yet been consulted on what "tenant readiness" means for their program. The Initiative needs an OMD review checkpoint before 54b execution begins. | Terry |
| R10 | **OMD vs EPIC naming** — every public-facing artifact (briefings, demos, SDD docs cross-referenced in NOAA wiki) must consistently use "Initiative" not "EPIC" to avoid clash with the Earth Prediction Innovation Center. | All |

## 6. Decomposition into Execution Phases

Each will get its own SDD spec under `sdd_framework/workflows/` once this
Initiative is reviewed by OMD stakeholders:

```
   54a (catalog schema) ─┐
                         ├─► 54b (data isolation) ─┬─► 54c (extends:)
                         │                         └─► 54d (branch tenants + dedupe)
                         │                                          │
                         │                                          ▼
                         └──────────────────────────────────────► 54e (routing)
                         │
                         └─► 54f (auth broker + 3rd-party pilot)   [parallel]
```

- `phase54a_tenant_catalog_schema.md` — YAML schema + validator design
- `phase54b_per_tenant_data_isolation.md` — Neo4j/Chroma scoping + tool retrofit
- `phase54c_shared_component_inheritance.md` — `extends:` semantics + resolution
- `phase54d_branch_scoped_tenants.md` — `gw-mcp` vs `gw-v17-mcp` + dedupe strategy
- `phase54e_tenant_routing_and_attribution.md` — `which_program` router + `tenant_id` tagging
- `phase54f_headless_auth_broker_and_3p_mcp_pilot.md` — secret store + arxiv/semantic-scholar pilot

## 7. SDD Session Tracking

Use `start_sdd_session({phase:"phase54_omd_multi_program_mcp_initiative", role:"initiative"})`
to open the umbrella session. Each sub-phase opens its own session and
links back to this Initiative via the `parent_phase` field.

## 8. References

- [.vscode/mcp.json](../../.vscode/mcp.json) — current single-server gateway config (the monolith this Initiative decomposes)
- [supported_repos/global-workflow](../../supported_repos/global-workflow) — current monolithic ingestion target; 54d splits this by branch
- [phase4d_multi_tenant_sdd_workspaces.md](phase4d_multi_tenant_sdd_workspaces.md) — prior multi-tenant work (SDD-workspace scope, complementary)
- [phase52_v17_paradigm_coverage.md](phase52_v17_paradigm_coverage.md) — earlier work specifically on v17 paradigm gaps
- [phase26 — Docker MCP Gateway baseline](phase26_docker_mcp_gateway_baseline.md) (if present)
- Future: MPAS repo (not yet in `supported_repos/`) — see R5
- Live evidence (2026-05-06) of the supporting-arm gaps: `mcp-find` returns 0 results for any query; `mcp-config-set` accepts arbitrary JSON. Captured in conversation tool-test transcripts.

## Appendix A — Multi-Tenant Catalog Sketch (54a / 54d output)

Illustrative `~/.docker/mcp/catalogs/eib-local.yaml` after 54a–54d land:

```yaml
servers:
  ufs-mcp:
    image: eib-mcp-rag:latest
    env:
      TENANT_ID: ufs
      WORKFLOW_REF: "ufs-community/ufs-weather-model@develop"
      NEO4J_DATABASE: ufs           # or NEO4J_LABEL_PREFIX=ufs_ if Community edition (R1)
      CHROMA_COLLECTION_PREFIX: ufs_

  gw-mcp:
    image: eib-mcp-rag:latest
    extends: [ufs-mcp]              # transitive UFS tools available
    env:
      TENANT_ID: gw
      WORKFLOW_REF: "NOAA-EMC/global-workflow@develop"
      NEO4J_DATABASE: gw
      CHROMA_COLLECTION_PREFIX: gw_

  gw-v17-mcp:
    image: eib-mcp-rag:latest
    extends: [ufs-mcp]
    env:
      TENANT_ID: gw_v17
      WORKFLOW_REF: "NOAA-EMC/global-workflow@gfsv17-coupled"
      NEO4J_DATABASE: gw_v17
      CHROMA_COLLECTION_PREFIX: gw_v17_

  mpas-mcp:
    image: eib-mcp-rag:latest
    extends: [ufs-mcp]
    env:
      TENANT_ID: mpas
      WORKFLOW_REF: "MPAS-Dev/MPAS-Model@main"
      NEO4J_DATABASE: mpas
      CHROMA_COLLECTION_PREFIX: mpas_
```

Key property: **all four tenants run the same Docker image.** The 52-tool
surface is identical; only the data view differs. CM divergence between
`develop` and `gfsv17-coupled` becomes a *catalog* concern, not a
*server-code* concern. Onboarding a new OMD program (RRFS, HAFS, …) is
adding ~10 lines of YAML.
