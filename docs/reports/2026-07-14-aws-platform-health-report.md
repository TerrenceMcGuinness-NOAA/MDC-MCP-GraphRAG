# AWS Platform Health Report — 2026-07-14

**Date**: July 14, 2026 (Monday post-wake)
**Platform**: AWS EC2 (`ip-10-40-136-39`, `us-east-1`)
**Runtime**: AgentCore `mdc_mcp_rag_server_python-v5K2F8BGrN`
**Backend**: Neptune (graph) + OpenSearch (vector) + Bedrock Titan (embeddings)
**Wake script**: `quickstart-wake.sh` — Neptune + OpenSearch confirmed available

---

## Executive Summary

The AWS platform woke cleanly and all 4 core components are **HEALTHY**. The
MCP runtime responds in <1s, all 52 tools across 9 modules are registered, and
functional validation passes 9/10 (the 1 SKIP is expected — `workflow_info`
requires the EFS mount, which is not active outside AgentCore containers). Both
the default `gw` tenant and the `gw_v17` tenant report healthy vector + graph
stores.

| Dimension | Status | Detail |
|---|---|---|
| Runtime | HEALTHY | v1.0.0, 52 tools, 9/9 modules |
| Vector (OpenSearch) | HEALTHY | 21 indices, 252,013 documents |
| Graph (Neptune) | HEALTHY | 148,976 nodes, 4,555,408 relationships |
| Functional probes | 9/10 pass | `workflow_info` SKIP (EFS not mounted) |
| Tenant: gw_v17 | HEALTHY | 56,876 vector docs; 80,996 nodes / 1,278,331 rels |
| Neptune direct | Available | confirmed via awslabs.amazon-neptune-mcp-server |

---

## 1. Server Info

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Total tools | 52 |
| Active modules | 9/9 |
| Tenants | 5 (default: `gw`) |
| Data access | Connected |
| Vector search | Available |
| Graph queries | Available |

Active modules: `semantic_search`, `code_analysis`, `graph_rag`, `ee2_compliance`,
`operational`, `sdd_workflow`, `workflow_info`, `github_tools`, `utility`.

---

## 2. Deep Health Check (4/4 HEALTHY)

| Component | Status | Detail |
|---|---|---|
| Base Server | [OK] | FastMCP running |
| Utility Tools | [OK] | 4 utility tools registered |
| Vector Database | [OK] | 21 indices |
| Graph Database | [OK] | 105,891 nodes, 4,729,093 relationships |

### Tenant Catalog

| tenant_id | branch | lifecycle | workflow_root reachable |
|---|---|---|---|
| gw | develop | production | no (`/mnt/workflow/develop` — EFS not mounted on EC2) |
| gw_sfs | dev/sfs | experimental | no |
| gw_jedi_gfs | dev/jedi-gfs | experimental | no |
| gw_v17 | dev/gfs.v17 | staging | no |
| gw_gefs_v12 | release/gefs_v12 | production | no |

Note: `workflow_root reachable = no` is expected on this EC2 host — the
`/mnt/workflow` EFS mount only activates inside the AgentCore container. The
runtime's tools still function via the data stores.

---

## 3. Functional Validation (9/10 pass)

| Module | Status | Latency |
|---|---|---|
| semantic_search | [OK] pass | 804ms |
| code_analysis | [OK] pass | 363ms |
| graph_rag | [OK] pass | 145ms |
| ee2_compliance | [OK] pass | 259ms |
| operational | [OK] pass | 836ms |
| sdd_workflow | [OK] pass | 0ms |
| **workflow_info** | **[SKIP]** | 0ms |
| github_tools | [OK] pass | 216ms |
| utility | [OK] pass | 0ms |
| branch_isolation | [OK] pass | 1,234ms |

`workflow_info` SKIP is expected (requires EFS at `/mnt/workflow`). All
data-plane modules including `branch_isolation` (multi-tenant probe) pass.

---

## 4. Knowledge Base Status — Default Tenant (`gw`)

### Vector (OpenSearch) — 252,013 documents across 16 indices

| Index | Documents | Profile |
|---|---|---|
| mdc-workflow-docs-titan1024 | 20,155 | titan1024 |
| mdc-workflow-docs-mpnet768 | 22,498 | mpnet768 |
| mdc-workflow-docs-nova1024 | 150 | nova1024 |
| mdc-code-context-titan1024 | 90,135 | titan1024 |
| mdc-code-context-mpnet768 | 60,576 | mpnet768 |
| mdc-code-context-nova1024 | 0 | nova1024 |
| mdc-jjobs-titan1024 | 751 | titan1024 |
| mdc-jjobs-mpnet768 | 700 | mpnet768 |
| mdc-jjobs-nova1024 | 0 | nova1024 |
| mdc-community-summaries-titan1024 | 2,113 | titan1024 |
| mdc-community-summaries-mpnet768 | 2,113 | mpnet768 |
| mdc-community-summaries-nova1024 | 0 | nova1024 |
| mdc-ee2-standards-titan1024 | 34 | titan1024 |
| mdc-ee2-standards-mpnet768 | 34 | mpnet768 |
| mdc-ee2-standards-nova1024 | 0 | nova1024 |
| mdc-content-sha-registry | 52,754 | (dedupe) |

### Graph (Neptune) — 148,976 nodes, 4,555,408 relationships

**Node labels (top 10):**

| Label | Count |
|---|---|
| Function | 87,610 |
| FortranSubroutine | 27,941 |
| File | 17,273 |
| FortranFunction | 5,744 |
| FortranModule | 4,800 |
| PythonFunction | 2,642 |
| Module | 980 |
| PythonModule | 719 |
| FortranProgram | 671 |
| ShellScript | 315 |

**Relationship types:**

| Type | Count |
|---|---|
| CALLS | 3,407,104 |
| USES | 997,616 |
| DEFINES | 91,652 |
| DEPENDS_ON_ENV | 31,601 |
| IMPORTS | 10,443 |
| EXPORTS | 7,925 |
| DEPENDS_ON | 4,752 |
| INVOKES | 2,690 |
| SOURCES | 1,528 |
| EXECUTES | 97 |

---

## 5. Knowledge Base Status — Tenant `gw_v17`

### Vector (OpenSearch) — 56,876 documents across 5 indices

| Index | Documents |
|---|---|
| gw_v17_mdc-code-context-titan1024 | 28,325 |
| gw_v17_mdc-workflow-docs-titan1024 | 28,459 |
| gw_v17_mdc-jjobs-titan1024 | 92 |
| gw_v17_mdc-community-summaries-titan1024 | 0 (Gap J) |
| gw_v17_mdc-ee2-standards-titan1024 | 0 |

### Graph (Neptune) — 80,996 nodes, 1,278,331 relationships

| Metric | Count |
|---|---|
| GW_V17_File | 30,221 |
| GW_V17_FortranSubroutine | 36,156 |
| GW_V17_FortranFunction | 8,172 |
| GW_V17_FortranModule | 4,558 |
| GW_V17_ShellScript | 1,401 |
| GW_V17_FortranProgram | 488 |
| CALLS | 1,019,436 |
| USES | 229,353 |
| DEPENDS_ON_ENV | 20,434 |
| EXPORTS | 6,064 |
| INVOKES | 1,767 |
| SOURCES | 928 |
| DEFINES | 337 |
| EXECUTES | 12 |

---

## 6. Knowledge Base Integrity

| Check | Status | Detail |
|---|---|---|
| Path Consistency | [WARN] | 2/34 sampled docs have checkout-specific prefix |
| Orphaned Graph Nodes | [OK] | 17,273 File nodes; 0/20 sampled lack identity |
| Stale Embeddings | [WARN] | 12/12 sampled docs older than 30-day threshold |
| Coverage Gap | [SKIP] | no Fortran files at `/supported_repos/global-workflow` (EFS not mounted on EC2) |

**Notes:**
- `Path Consistency` WARN (2/34) — minor; a few docs carry an old path prefix from
  a prior ingestion. Will be resolved on next full re-ingest (framework spec).
- `Stale Embeddings` WARN (12/12) — embeddings are 30+ days old (last ingest was
  pre-Phase-67 rename). Expected; the framework spec re-ingest will refresh them.
- `Coverage Gap` SKIP — this check requires the source tree on disk; the EFS mount
  is not active outside AgentCore. On COTS, this check runs fine.

---

## 7. Unified Manifest Status

| Metric | Value |
|---|---|
| Manifest version | 9.0.0 |
| Total sources | 67 (65 enabled) |

### By source type

| Type | Sources | Enabled | Declared docs |
|---|---|---|---|
| url_crawl | 58 | 56 | 19,489 |
| code_parse | 3 | 3 | 88,614 |
| config_parse | 2 | 2 | 1,484 |
| community_summary | 1 | 1 | 2,113 |
| on_disk_submodule | 1 | 1 | 1,759 |
| jjob_docs | 1 | 1 | 751 |
| standards | 1 | 1 | 34 |

### Collection coverage

| Collection | Sources | Declared | Actual | Coverage |
|---|---|---|---|---|
| code-with-context-v8-0-0 | 5 | 90,098 | 90,135 | 100.0% |
| community-summaries | 1 | 2,113 | 2,113 | 100.0% |
| ee2-standards-v5-0-0-enhanced | 1 | 34 | 34 | 100.0% |
| global-workflow-docs-v8-0-0 | 59 | 21,248 | 20,155 | 94.9% |
| jjobs-v8-0-0 | 1 | 751 | 751 | 100.0% |

### Gap detection — documentation (94.9% coverage)

**Stale** (44 sources — last ingested >30 days ago): global-workflow, ufs-utils,
esmf-user-guide, esmf-ref-pdf, esmc-ref-pdf, nuopc-ref-pdf, esmpy-pdf,
nuopc-layer-reference, ecflow, wxflow, pyflow, ufs-weather-model, jedi-docs,
mom6, cice, ww3-wiki, fv3-docs, gocart, pyioda, fms, cmaq, spack-stack, spack,
nceplibs-bufr, nceplibs-ip, nceplibs-w3emc, nceplibs-g2, nceplibs-bacio,
nceplibs-g2tmpl, wgrib2, ccpp-techdoc, kokkos-overview, fortran-best-practices,
upp, metplus, mpas-atmosphere, catchem, cece, cdeps, land-da, uwtools,
gsi-user-guide, hafs.

**Never ingested** (14 sources): rocoto, cmeps, nceplibs-nemsio, nceplibs-sfcio,
nceplibs-sigio, kokkos-api, google-shell-style, pep8, numpy-docstrings,
ufs-srweather-app, global-workflow-rst, ecmwf-atlas, jedi-academy-2021-10,
jedi-academy-2021-06.

---

## 8. Health Trend

No health history available (first wake after platform sleep). The snapshot was
persisted to `health_history.jsonl` by this run.

---

## 9. Quality Metrics

No benchmark results found — the quality benchmark harness has not been run
against the live AWS deployment. The benchmark is run via COTS
(`sdd_framework/execution_state/quality_metrics.jsonl`).

---

## 10. MCP Config Resolution

The `eib-mcp-rag-full` entry in `.kiro/settings/mcp.json` (COTS-only
`run_mcp_stdio.sh` launcher) was replaced with the correct `agentcore-mcp-rag`
proxy entry pointing at the AgentCore runtime. Kiro connects successfully.

| Server | Config level | Status |
|---|---|---|
| `agentcore-mcp-rag` | workspace + user | Connected (AgentCore proxy) |
| `awslabs.amazon-neptune-mcp-server` | workspace + user | Connected (direct Neptune) |
| `eib-mcp-gateway` | user (disabled) | Disabled (blocked dev tunnel) |

---

## 11. Actions / Follow-ups

| # | Item | Priority | Owner |
|---|---|---|---|
| 1 | **Stale embeddings** (44 URL-crawl sources >30 days) — refresh via `url-crawl-gap-closure` / framework spec re-ingest | Medium | Framework spec |
| 2 | **14 never-ingested doc sources** — investigate (missing URLs, broken crawlers, or intentionally excluded) | Low | url-crawl-gap-closure |
| 3 | **Path Consistency WARN** (2/34 old-path docs) — resolved on next full re-ingest | Low | Framework spec |
| 4 | **Coverage Gap SKIP on EC2** — expected (EFS not mounted); runs on AgentCore and COTS | None | By design |
| 5 | **Gap J** — `gw_v17_mdc-community-summaries-titan1024` empty (Neo4j GDS Leiden port pending) | Medium | Phase 68 / Q3 |
| 6 | **Quality metrics** — run the benchmark harness against the live AWS deployment | Low | Optional |
