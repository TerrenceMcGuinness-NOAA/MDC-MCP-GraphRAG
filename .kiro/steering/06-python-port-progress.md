# Python MCP Server Port — Progress Notes

Short-form progress log for the Python port of the Node.js MCP server
(spec: `.kiro/specs/python-mcp-server-port/`). The Node.js server
(`mcp_server_node/`) continues to serve production traffic; the Python
port (`mcp_server_python/`) is validated module-by-module via parity
tests before cutover.

## 2026-06-03 — Gap A deployed: tenant_id reachable on the live runtime (v22)

### Status

- **`tenant-id-tool-exposure` Task 14 DONE.** Built + pushed
  `python-tenants-v2` (ECR digest `sha256:341891b9...`) and cut the
  runtime `mdc_mcp_rag_server_python-v5K2F8BGrN` from
  v21/`python-tenants-v1` → **v22/`python-tenants-v2`** (READY).
- **Gap A verified live.** `search_documentation(query, tenant_id="gw_v17")`
  → `*Tenant: gw_v17*` / `*Branch: dev/gfs.v17*`; without `tenant_id`
  → `*Tenant: gw*` / `*Branch: develop*` with real doc hits. The
  pydantic `Unexpected keyword argument` error is gone — `tenant_id`
  is in the schema for all 24 tenant-scoped tools.
- **`mcp_health_check(functional=True)`**: 8/10 pass, github SKIP
  (no GITHUB_TOKEN), `branch_isolation` FAIL — but the failure is
  **Gap B, not Gap A**. Probe assertion 1 needs a relationship
  (`MATCH (f {name:'JGDAS_ATMOS_ANALYSIS_WDQMS'})-[r]-(m)`); confirmed
  directly in Neptune the node exists under `GW_V17_JJob` with
  `rel_count=0`. Goes green when `graph-port-shell-ops` lands.

### Rollback

Same `update-agent-runtime` call with
`containerUri=...:python-tenants-v1`. v1 image preserved in ECR.

### Deploy payload note

**CRITICAL**: The `update-agent-runtime` API does NOT carry forward env vars,
EFS mounts, or metadata from the previous version. Every call must include the
full payload or the runtime boots in degraded mode (no Neptune, no OpenSearch,
no EFS workflow mount). The deploy template in "How to rebuild / redeploy"
below includes all required flags. The key flags that are easy to forget:
- `--environment-variables` (6 vars: DB_BACKEND, NEPTUNE_ENDPOINT, OPENSEARCH_ENDPOINT, AWS_REGION, MCP_STATELESS_HTTP, MCP_WORKFLOW_ROOT)
- `--filesystem-configurations` (EFS access point `fsap-03e641f056b341f29` at `/mnt/workflow`)
- `--metadata-configuration` (`requireMMDSV2:true`)

Other constants: 2 subnets (`subnet-0e13af6b3a9a6416f`,
`subnet-04447750c61bd7e06`), sg `sg-096489a0876cc78c1`.

## 2026-05-21 — MPAS RAG bug: path-prefix scoping for non-RTD Sphinx sites

### Status

- **MPAS-Atmosphere ingestion fixed.** `mpas-atmosphere` source now
  has 439 docs in `mdc-workflow-docs-titan1024` (was 0). Verified via
  `search_documentation("MPAS Voronoi unstructured mesh dynamical
  core")` — top 5 hits are real MPAS content (Voronoi mesh, dynamical
  core, DART interface) at 100% similarity.
- The Phase 58 url-crawl-gap-closure run had silently completed with
  `mpas-atmosphere: doc_count=0, last_ingested=null` (and
  `ufs-srweather-app: doc_count=0` — a separate, unresolved case).

### Root cause

The MPAS docs live on `www2.mmm.ucar.edu/projects/mpas/site/` — a
Sphinx-built site hosted on a multi-project UCAR/MMM domain (the
domain also hosts WRF and other projects). Two compounding issues:

1. **Multi-project domain.** The crawler's same-domain BFS would
   leak budget into unrelated `/projects/...` sub-trees if the seed
   page linked there (it doesn't here, but the pattern is fragile).
2. **Broken Sphinx TOC at depth.** The site's theme renders one
   global TOC fragment with relative `href` values (e.g.
   `documentation/users_guide/foreword.html`) on every page. From
   the index that resolves correctly. From a deeper page like
   `gpu_mpas/known_issues.html`, `urljoin` produces
   `gpu_mpas/documentation/users_guide/foreword.html` — a 404. The
   crawler's queue fills with hundreds of these URLs, exhausting the
   `max_pages` budget on broken links and leaving very few real
   pages indexed.

### Fix (applied to `develop_aws`)

Added an optional `path_prefix` field to URL-crawl sources that
constrains the BFS to a path sub-tree of the domain:

- `mcp_server_node/scripts/ingestion_base.py` — `URLCrawler` accepts
  `path_prefix=None`; `_extract_same_domain_links` filters discovered
  links by prefix.
- `mcp_server_node/scripts/ingest_documentation_v7.py` — plumbs
  `source.get('path_prefix')` into the crawler; adds `--only
  <source...>` flag for re-running individual sources.
- `mcp_server_node/scripts/ingest_documentation_v8.py` — exposes
  `--only` at the v8 wrapper.
- `mcp_server_node/scripts/documentation_sources_config.py` — sets
  `path_prefix: '/projects/mpas/site/'` on `mpas-atmosphere`,
  bumps `max_pages` 150 → 200; validator rejects malformed prefixes.
- `mcp_server_python/src/config/unified_manifest.json` — same
  `path_prefix` mirrored on the manifest entry.
- `mcp_server_python/scripts/generate_unified_manifest.py` — passes
  `path_prefix` through `type_fields` so future regenerations
  preserve it.

### When to set `path_prefix`

Use it for **any non-ReadTheDocs Sphinx site on a multi-project
domain** (UCAR/MMM, NCAR, GFDL, JCSDA project pages, etc.). Symptoms
that warrant it:

- Source URL path is `/projects/<name>/...` or similarly nested under
  a generic top-level path on a domain that hosts other projects.
- Live test of `URLCrawler.crawl_recursive(seed, max_pages=20)`
  returns many `[ERROR] 404` lines for URLs whose paths look like
  partial-relative TOC artefacts (missing path segments, or
  unexpected segment duplication).
- `last_ingested: null` after a tier run that succeeded for other
  RTD-hosted sources in the same tier.

ReadTheDocs-hosted sites (`*.readthedocs.io`) typically don't need
this — RTD generates a clean per-project sub-domain and a
`sitemap.xml` that the ingester prefers when present.

### Re-running a single source

```bash
DB_BACKEND=aws \
  OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com \
  NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182 \
  AWS_REGION=us-east-1 \
  MCP_EMBEDDING_PROFILE=titan1024 \
  python3.12 mcp_server_node/scripts/ingest_documentation_v8.py \
    --model titan1024 \
    --tiers tier3_models \
    --only mpas-atmosphere \
    --delay 0.5
```

Then `python3.12 mcp_server_python/scripts/backfill_manifest_status.py`
to refresh `doc_count` / `last_ingested` from OpenSearch.

### Still open

- `ufs-srweather-app` shows `doc_count: 0` after the same Phase 58
  run despite the seed URL returning HTTP 200. Different root cause
  (it's RTD-hosted, no path_prefix needed). Track separately.

---

## 2026-05-15 — Phase C-3: Bedrock IAM gap resolved

### Status

- **Bedrock `InvokeModel` permission added** to
  `mdc-mcp-rag-ecs-task-role`. Admin applied the inline policy
  `bedrock-invoke-titan-embed-v2` on 2026-05-15.
- Resource ARN: `arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-*`
  (admin chose wildcard over pinned `v2:0` — covers future Titan embed
  versions).
- Verified via `aws bedrock-runtime invoke-model` — returns 1024-dim
  embedding vector successfully.
- The semantic search path (`search_documentation` with titan1024
  collections) is now unblocked on both the Node.js and Python
  runtimes.
- **All known IAM blockers are resolved.** Ready for live parity
  testing.

### What was blocking

The AgentCore microVM assumed `mdc-mcp-rag-ecs-task-role` which had
Neptune, OpenSearch, ECR, logs, X-Ray, secretsmanager, and ssm — but
no `bedrock:InvokeModel`. Every `BedrockProvider` embedding call
failed with `AccessDeniedException`. The sentence-transformers
(mpnet768) path worked because it runs locally; the Titan (titan1024)
path requires Bedrock API access.

### Admin request doc

`docs/bedrock-invoke-model-role-request.txt` — submitted and applied
2026-05-15. Includes verbatim denial proof, exact CLI command, and
rollback instructions.

### Next

Live parity testing (Phase C-4): run the parity suite comparing
Node.js and Python runtimes now that both have full data-layer +
embedding access.

### Cutover

**2026-05-15: `.kiro/settings/mcp.json` switched to Python runtime.**
Both workspace and user configs now point `agentcore-mcp-rag` at
`mdc_mcp_rag_server_python-v5K2F8BGrN`. The Node.js runtime
(`mdc_mcp_rag_server-TMXDllG2Wi`) remains deployed but is no longer
the active MCP target — it continues to exhibit Issue A
(`RuntimeClientError` on health check).

---

## 2026-05-14 — Phase C-2b: Issue C resolved (data layer connected)

### Status

- **Issue C resolved.** The Python staging runtime can now reach
  Neptune and OpenSearch from inside the AgentCore microVM. Health
  check reports `HEALTHY (4/4 components healthy)`.
- Root cause was NOT a VPC SG gap (the SGs were already correct).
  Three Phase B2 modules were never committed:
  `src/data/neptune_adapter.py`, `src/data/unified_data_access.py`,
  `src/data/backend_selector.py`. This update lands them.
- 27 new unit tests cover the new modules; suite count
  716 (was 689 at C-2a `55058b9`).
- Staging runtime is now in the correct shape for live parity.
  **Issue A (Node.js production runtime unhealthy)** is the only
  remaining blocker to cutover.

### Runtimes in play (post-C-2b)

| Runtime | ID | Version | Image | Use |
|---|---|---|---|---|
| **Node.js (production)** | `mdc_mcp_rag_server-TMXDllG2Wi` | v10 | (unchanged) | **Issue A still pending** — operator-side |
| **Python (staging)** | `mdc_mcp_rag_server_python-v5K2F8BGrN` | **v5** | `python-all-tools-v3` | All 9 modules, 51 tools, **3/3 components healthy** (Base + Utility + Vector + Graph DB), 105 891 nodes / 2 941 593 rels via Neptune, 5 OpenSearch indices |

### Env vars set on the staging runtime

| Var | Value |
|---|---|
| `DB_BACKEND` | `aws` |
| `NEPTUNE_ENDPOINT` | `https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182` |
| `OPENSEARCH_ENDPOINT` | `https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com` |
| `AWS_REGION` | `us-east-1` |
| `MCP_STATELESS_HTTP` | `true` |
| `MCP_WORKFLOW_ROOT` | `/app/supported_repos/global-workflow` |

### Deploy artifacts

| Artifact | Value |
|---|---|
| Local image SHA | `sha256:9d085318b4c6d20b230a2000c1c20fad3857f7e1a8fc8c56eda23afe1a8f1b6a` |
| ECR manifest digest | `sha256:652bd658a4ae9c2b59791feb7bcb44b2eec4f575b6af3643b81f90ce9ae0d531` |
| ECR tag (new) | `python-all-tools-v3` |
| Rollback targets (preserved) | `python-utility-v1` (B4) / `python-all-tools-v1` (C-1, chown bug) / `python-all-tools-v2` (C-2a, no data layer) |
| Deploy timestamp | 2026-05-14T18:54 UTC |

### Cosmetic follow-up

`get_knowledge_base_status` renders correct per-label / per-rel-type
breakdowns but the summary lines and the `Status` flag underreport.
The underlying data layer is healthy; this is a rendering-aggregation
bug in `semantic_search.get_knowledge_base_status`. Not a C-2b
blocker; track as a separate follow-up.

### Reference

- Full Phase C-2b Post-Fix Status:
  `docs/reports/2026-05-14-phase-c1-parity-assessment.md`
- CHANGELOG: `[8.22.2]` (this hot-fix), `[8.22.1]` (C-2a chown),
  `[8.22.0]` (C-1 deploy + parity assessment).


## 2026-05-14 — Phase C-2a: Issue B (chown) hot-fix deployed

### Status

- Phase C-1 surfaced 3 blockers; this update resolves the only one
  the CLI could fix autonomously (**Issue B**).
- Python staging runtime now reports **51/51 tools, 9/9 modules**
  registered (was 33/51 before the fix).
- `.kiro/settings/mcp.json` **untouched** — still points at the
  Node.js runtime per the cutover-deferred decision.

### Runtimes in play (unchanged from C-1, version updated)

| Runtime | ID | Version | Image | Use |
|---|---|---|---|---|
| **Node.js (production)** | `mdc_mcp_rag_server-TMXDllG2Wi` | v10 | (unchanged) | **Issue A: data-plane unhealthy** — operator-side |
| **Python (staging)** | `mdc_mcp_rag_server_python-v5K2F8BGrN` | **v4** | `python-all-tools-v2` | All 9 modules, 51 tools, `Data Access Layer: disabled` (Issue C still pending) |

### What changed in this hot-fix

Single-line Dockerfile change (`mcp_server_python/Dockerfile`):

```dockerfile
RUN groupadd --system --gid 1000 app \
 && useradd  --system --uid 1000 --gid app --home /app app \
 && chown -R app:app /app
```

Plus a regression test (`test_register_module_catches_session_manager_permission_error`)
in `mcp_server_python/tests/unit/test_mcp_server.py` that simulates
the production failure mode (monkey-patches `Path.mkdir` to raise
`PermissionError` on `sdd_framework/` paths, asserts
`_register_module` catches it cleanly for both `graph_rag` and
`sdd_workflow`). Suite count: **689 passed** (was 688 at B11 baseline
`e325e61`).

### Deploy artifacts

| Artifact | Value |
|---|---|
| Local image SHA | `sha256:63bd11f23ffa5131f786af52ac0169c28c18053d60d1b0c1ed30e6e49d6a946a` |
| ECR manifest digest | `sha256:32763889d8bda4f1b317b1dfcf3a9cd7004ef7f7d79e4ae28f26d7db60e732f1` |
| ECR tag (new) | `python-all-tools-v2` |
| Rollback targets (preserved) | `python-utility-v1` (B4 baseline) and `python-all-tools-v1` (C-1, has chown bug) |
| Deploy timestamp | 2026-05-14T17:42 UTC |
| Smoke-test verification | proxy `get_server_info` → 51 tools, 9 active modules |
| Health check | `HEALTHY (2/3 components healthy)` |

### Still pending (operator-side, blocks cutover)

- **Issue A — Node.js production runtime unhealthy**
  (`mdc_mcp_rag_server-TMXDllG2Wi` v10). 732 health-check failures /
  35 init-time-exceeded / 57 502s during the C-1 parity run. Either
  needs restoration (operator + AgentCore admin) OR formal designation
  of the Python staging runtime as the new reference.
- **Issue C — VPC security group `sg-096489a0876cc78c1` does not
  permit egress** to Neptune (8182) or OpenSearch (443) from the
  AgentCore microVM. Pre-existing Phase 51b blocker; operator-side
  AWS console / CDK action.

When both are resolved, re-run the live parity suite (Phase C-2b)
for the real comparison.

### Reference

- Full Phase C-1 assessment + Post-Fix Status section:
  `docs/reports/2026-05-14-phase-c1-parity-assessment.md`
- CHANGELOG: `[8.22.1]` (this hot-fix), `[8.22.0]` (C-1 deploy and
  parity assessment).


## 2026-05-12 — Phase B4 + early B11 deployed (utility-only smoke test)

### Status

- First AgentCore Runtime deployment for the Python server: **PASSED**.
- New staging runtime coexists with the production Node.js runtime.
- `.kiro/settings/mcp.json` still points at the Node.js runtime — the
  operator will flip it manually once the Python path is ready for
  end-to-end use.

### Runtimes in play

| Runtime | ID | Version | Use |
|---|---|---|---|
| **Node.js (production)** | `mdc_mcp_rag_server-TMXDllG2Wi` | v10 | Active MCP target for `.kiro/settings/mcp.json`. 51 tools. **Untouched.** |
| **Python (staging)** | `mdc_mcp_rag_server_python-v5K2F8BGrN` | v2 | Utility-only smoke test. 4 tools: `get_server_info`, `mcp_health_check`, `get_health_trend`, `get_quality_metrics`. |

### Completed phases

- **B1** — project scaffolding, `pyproject.toml`, Dockerfile, environment
  config (committed as `8.11.0`).
- **B2** — `VectorDBProtocol` / `GraphDBProtocol`, OpenSearch + Neptune
  adapters, `UnifiedDataAccess` facade, backend selector (also in
  `8.11.0`).
- **B3** — GGSR traversal engine, GraphGuidedRetrieval hybrid, SDD
  `SessionManager` with JSONL parity (committed as `8.12.0`).
- **B4** — parity-testing framework (`tests/parity/parity_runner.py`),
  mock adapter library in `tests/conftest.py` (committed as `8.13.0`).
- **Early B11** — `src/tools/utility.py` with the 4 utility tools ported
  from `UnifiedMCPServer.js`. Pulled forward from its spec slot so this
  smoke-test deployment has a minimal working tool set that does not
  need Neptune/OpenSearch connectivity. Remainder of B11 (`github_tools`,
  etc.) will be ported in its original slot. (Also `8.13.0`.)

### Known issue resolved during this deploy

- **FastMCP `stateless_http=True` is required for AgentCore MCP mode.**
  Stateful mode rejects AgentCore's platform-generated `Mcp-Session-Id`
  with HTTP 400, which AgentCore surfaces as a 500-class runtime error.
  `src/mcp_server.py` now sets `stateless_http=True` by default; override
  via the `MCP_STATELESS_HTTP=false` env var for local stateful testing.
  Full root-cause analysis is in
  `docs/reports/2026-05-12-python-server-smoke-test.md`.

### Verified outputs

Per the smoke test (full report at
`docs/reports/2026-05-12-python-server-smoke-test.md`):

- `mcp_health_check({})` → `Overall Status: HEALTHY (2/3 components healthy)`,
  with `Data Access Layer: disabled` — exactly the degraded-mode-boot
  shape.
- `get_server_info({})` → version `1.0.0`, 4 tools registered, active
  module `utility`.

### Next

- **B5** (`semantic_search`, 7 tools) — the parity framework from B4 will
  validate this against the Node.js baseline once both runtimes are
  callable from the same client.
- Subsequent phases (B6 – B10) add the remaining tool modules.
- Phase B11 completion: `github_tools` and any residual utility tools.

### How to rebuild / redeploy the staging runtime

```bash
cd mcp_server_python
docker build --platform linux/arm64 \
    -t 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-utility-v1 \
    -f Dockerfile .

aws ecr get-login-password --region us-east-1 \
    | docker login --username AWS --password-stdin \
        903050880929.dkr.ecr.us-east-1.amazonaws.com
docker push 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-utility-v1

aws bedrock-agentcore-control update-agent-runtime \
    --region us-east-1 \
    --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN \
    --agent-runtime-artifact '{"containerConfiguration":{"containerUri":"903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-utility-v1"}}' \
    --role-arn arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role \
    --network-configuration '{"networkMode":"VPC","networkModeConfig":{"subnets":["subnet-0e13af6b3a9a6416f","subnet-04447750c61bd7e06"],"securityGroups":["sg-096489a0876cc78c1"]}}' \
    --protocol-configuration '{"serverProtocol":"MCP"}' \
    --lifecycle-configuration '{"idleRuntimeSessionTimeout":900,"maxLifetime":28800}' \
    --metadata-configuration '{"requireMMDSV2":true}' \
    --environment-variables '{"DB_BACKEND":"aws","NEPTUNE_ENDPOINT":"https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182","OPENSEARCH_ENDPOINT":"https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com","AWS_REGION":"us-east-1","MCP_STATELESS_HTTP":"true","MCP_WORKFLOW_ROOT":"/mnt/workflow"}' \
    --filesystem-configurations '[{"efsAccessPoint":{"accessPointArn":"arn:aws:elasticfilesystem:us-east-1:903050880929:access-point/fsap-03e641f056b341f29","mountPath":"/mnt/workflow"}}]'
```

Use a new tag (e.g. `python-utility-v2`, `python-semantic-v1`) when the
change is not strictly iterative on the same smoke-test scope, so a
rollback target is preserved.

### How to delete the staging runtime

Safe at any time — the Node.js runtime is the production target and has
never been modified:

```bash
aws bedrock-agentcore-control delete-agent-runtime \
    --region us-east-1 \
    --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN
```
