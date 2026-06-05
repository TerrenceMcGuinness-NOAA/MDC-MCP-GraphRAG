---
inclusion: always
---

# AgentCore MCP for Global Workflow — Consumer Guide

**CRITICAL: Global Workflow is a production weather forecasting system supporting
NOAA's operational GFS, GEFS, and SFS. The MDC MCP-RAG server is a read-mostly
analysis aid over that codebase — it never modifies operational code. Treat its
output as guidance, verify against the source tree before acting, and never let
an MCP answer substitute for testing a real change.**

This file is the agent-facing guide for working on the NOAA Global Workflow
through the **AWS Bedrock AgentCore** MCP-RAG server (`agentcore-mcp-rag`). It is
modeled on the global-workflow repo's `.github/copilot-instructions.md`, but is
specific to our AWS-native deployment and the multi-tenant accounts.

> The full tool catalog (52 tools / 9 modules) lives in the companion steering
> file `.kiro/steering/10-agentcore-mcp-tool-guide.md`. This file covers *how to
> consume the service*; that file covers *which tool to pick*.

## What This Service Is (AWS-native stack)

The `agentcore-mcp-rag` server is a shared, authenticated, auto-scaling **tool
library** deployed on AWS Bedrock AgentCore Runtime. It exposes 52 MCP tools over
a hybrid knowledge base:

| Layer | AWS Service | Role |
|-------|-------------|------|
| Compute | Bedrock AgentCore Runtime (ARM64 microVM, MCP / Streamable-HTTP) | Hosts the tool server, session isolation, scaling |
| Graph | Amazon Neptune (openCypher, IAM SigV4) | Code structure graph — files, functions, CALLS/USES/CONTAINS, env vars, configs, Rocoto, J-Jobs |
| Vector | Amazon OpenSearch (k-NN + BM25, IAM SigV4) | Documentation + code embeddings for semantic search |
| Embeddings | Amazon Bedrock Titan (`amazon.titan-embed-text-v2:0`, 1024-dim) + baked-in MPNet (768-dim) | Query + ingest embeddings |

There is **no Docker, no Neo4j, and no ChromaDB** in this deployment. Any
reference you encounter to those is legacy material and does not describe the
live AWS system.

## How to Connect

The server is reached through a stdio proxy configured in
`.kiro/settings/mcp.json` as `agentcore-mcp-rag`:

- **Proxy**: `tools/agentcore-kiro-proxy.py` (translates stdio JSON-RPC ↔ boto3
  `invoke_agent_runtime` SSE).
- **Runtime**: `arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN`
- **Region**: `us-east-1`
- **Auth**: the runtime assumes `mdc-mcp-rag-ecs-task-role` (Neptune, OpenSearch,
  Bedrock InvokeModel, logs). Inbound auth is handled by AgentCore.

No setup is needed inside a session — the tools appear automatically. If they are
absent, the proxy or runtime is down; check `mcp_health_check`.

## MCP-First Policy

**Prefer MCP tools over shell commands** for code analysis, documentation search,
architecture questions, and EE2 compliance checks. The graph and vector stores
answer relationship and semantic questions that `grep` cannot.

Use `read`/`grep`/`glob` only for:
- Exact line-level reads of a known file (`read`).
- Literal string searches (`grep`).
- Path discovery by name (`glob`).

Best practice: **MCP tool for discovery, then `read` for the precise lines.**

## Two-Layer Consumer Model

The AgentCore runtime is **Layer 1** — a stable, composable library of tool
primitives that performs no orchestration of its own. Consumers are **Layer 2**:

- **Tier A — Direct consumers**: Kiro on a developer workstation, CI pipelines,
  HPC researcher sessions. Each needs only an endpoint + credentials. *(This
  session is a Tier A consumer.)*
- **Tier B — Agent-wrapped consumers**: task-specific agents (EE2 analyzer, build-
  failure diagnoser, code-review assistant) that wrap the MCP behind one endpoint.
- **Tier C — Scheduled consumers**: cron-style jobs (drift monitor, EE2 baseline
  bot, release-notes generator).

Implication: when proposing a new capability, ask whether it is a Layer 1 tool
primitive (rare, keep the library narrow) or a Layer 2 consumer (default).

## Multi-Tenant Accounts — Finer Details

The knowledge base is **multi-tenant**: one shared Neptune cluster and one shared
OpenSearch domain hold several global-workflow branches side by side, isolated by
label/index prefixing. This is the "multi-user accounts" capability.

### The tenant catalog

Source of truth: `mcp_server_python/src/config/tenants.yaml`. Current tenants:

| `tenant_id` | Branch | Index prefix | Label prefix | Worktree subdir | Lifecycle |
|-------------|--------|--------------|--------------|-----------------|-----------|
| `gw` *(default)* | `develop` | *(none)* | *(none)* | `develop` | production |
| `gw_sfs` | `dev/sfs` | `gw_sfs_` | `GW_SFS_` | `dev-sfs` | experimental |
| `gw_jedi_gfs` | `dev/jedi-gfs` | `gw_jedi_gfs_` | `GW_JEDI_GFS_` | `dev-jedi-gfs` | experimental |
| `gw_v17` | `dev/gfs.v17` | `gw_v17_` | `GW_V17_` | `dev-v17` | staging |
| `gw_gefs_v12` | `release/gefs_v12` | `gw_gefs_v12_` | `GW_GEFS_V12_` | `gefs-v12` | production |

### The `tenant_id` contract

- **24 of the 52 tools accept an optional `tenant_id` parameter** (see file 10 for
  the exact list). These are the data-plane tools — anything that reads the graph
  or vector store for a specific branch.
- **Omitting `tenant_id` resolves to the default `gw` tenant** (the `develop`
  branch, unprefixed labels/indices). This preserves the original single-tenant
  behavior byte-for-byte.
- **To query any other branch, pass `tenant_id` explicitly**, e.g.
  `search_documentation(query="...", tenant_id="gw_v17")`.
- **An unknown `tenant_id` returns an `[ERROR] ...` message — never a silent
  fallback to `gw`.** If you see a tenant error, check the spelling against the
  catalog table above.
- Resolution path: `tenant_id` → `resolve_tenant` → request-scoped `ContextVar`
  → adapter prefix-scoping → attribution header on the response.

### How isolation works

- **Neptune**: each tenant's nodes carry a prefixed label, e.g.
  `:GW_V17_FortranModule`, `:GW_V17_ShellScript`. The default `gw` tenant uses
  unprefixed labels (`:FortranModule`). Queries are scoped to the active tenant's
  prefix automatically.
- **OpenSearch**: each tenant's documents live in prefixed indices, e.g.
  `gw_v17_documentation`, `gw_v17_code`. The default `gw` tenant uses the legacy
  unprefixed indices.
- **Attribution**: tool responses echo the resolved tenant so you can confirm you
  queried the branch you intended, e.g. a header line of
  `*Tenant: gw_v17*` / `*Branch: dev/gfs.v17*`. A response showing
  `*Tenant: gw*` / `*Branch: develop*` means no `tenant_id` was passed.

### Choosing the right tenant

- Default to **`gw`** for general global-workflow questions and for the richest
  graph (the `develop` baseline is fully ingested with relationships).
- Pass **`gw_v17`**, **`gw_sfs`**, etc. only when the user is explicitly working on
  that branch, or when comparing branch-specific behavior.
- The branch on disk for a tenant lives under its worktree
  (`/mnt/workflow/<workflow_subdir>`); read tools operate on the catalog branch,
  not whatever is checked out in this repo's `supported_repos/`.

### Current limitation — non-`gw` graph relationships (Gap B)

Node ingestion for the non-default tenants is complete, but the
**relationship-producing ingesters are still being ported** (the `graph-port-*`
spec series). Practical impact for any tenant other than `gw`:

- Vector/semantic tools (`search_documentation`, `search_architecture`, etc.)
  work fully — embedded content is present.
- Graph-traversal tools (`find_dependencies`, `find_callers_callees`,
  `trace_execution_path`, `trace_full_execution_chain`, `trace_data_flow`,
  `get_change_impact`) may return **sparse or empty** results for `gw_v17` and
  friends until their relationship ingestion runs live. The `gw` baseline is
  unaffected and returns full call/dependency chains.

When a traversal comes back empty for a non-`gw` tenant, that is the expected
current state — not a tool failure. Confirm against `gw` if you need a populated
graph, and flag the gap rather than presenting "no results" as ground truth.

## Development Guidelines (when changes are warranted)

These mirror the global-workflow repo conventions and the workspace steering:

- **Change logging**: note code changes in `CHANGELOG.md` with date + semantic
  version; never auto-commit (see `08-git-operation-policy.md`).
- **Code style**: 2-space indent; quote Bash variables (`"${var}"`); no trailing
  whitespace; `pycodestyle` for Python; `shfmt` + `shellcheck` for shell;
  numpy-style docstrings.
- **Quality**: prefer readable, modular code over cleverness; write tests for new
  features and fixes; avoid over-engineering.
- **ASCII-only console output** (`[OK]`, `[ERROR]`, `[WARN]`) — emoji break MCP
  stdio.

## Relationship to Other Steering

- `01-architecture-context.md` / `02-development-workflow.md` — for *building* the
  MCP server (the porting project). This file is for *consuming* it.
- `10-agentcore-mcp-tool-guide.md` — the full tool catalog + selection tables.
- `07-tenant-usability-gaps.md` — the running record of the multi-tenant gaps
  (Gap A resolved; Gap B in progress).

Source of truth for everything in this file: `src/tools/*.py`,
`src/config/tenants.yaml`, and `.kiro/settings/mcp.json`. If those disagree with
this doc, the code wins — update this file.

---
Remember: Global Workflow is a production forecasting system. MCP answers
accelerate understanding; they do not replace testing, review, or the operational
change process.
