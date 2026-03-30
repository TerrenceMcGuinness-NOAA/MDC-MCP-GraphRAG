---
inclusion: auto
---

# MDC MCP RAG — AWS Porting Architecture Context

## What This Project Is

This workspace (`eib-mcp-rag-server`) contains the source code for the **MDC MCP RAG Server**
(formerly EIB MCP RAG Server, renamed after institutional reorganization from EIB → MDC).

It is an MCP/RAG development platform for NOAA Global Workflow AI assistance, providing 51 tools
across 9 modules for code analysis, EE2 compliance validation, semantic search, SDD workflow
tracking, and operational guidance for weather forecasting infrastructure.

## The Two-System Architecture

There are two instances of this system in play during development:

### 1. Legacy System (eib-mcp-gateway) — RUNNING NOW, DO NOT MODIFY CONFIG
The `eib-mcp-gateway` MCP server configured in `.kiro/settings/mcp.json` connects to the
**legacy production system** running on the original NOAA Parallel Works VM infrastructure.
It uses Docker (Docker MCP Gateway + Docker Compose) for container orchestration.

- This MCP connection is our **reference implementation and development aid**
- Use it to query the knowledge base, run SDD workflows, check compliance, etc.
- **Do NOT rename or reconfigure this MCP connection** — it points at the legacy system
  and we need it operational while we port

### 2. AWS Target System (mdc-mcp-rag) — WHAT WE ARE BUILDING
The port targets AWS-native services, replacing Docker with AWS equivalents:

| Legacy (Docker-based)         | AWS Target                              |
|-------------------------------|-----------------------------------------|
| Docker Compose orchestration  | AWS-native services (ECS/Fargate, etc.) |
| Docker MCP Gateway (Go binary)| AWS API Gateway / Lambda / AgentCore    |
| Docker volumes on `/mcp_rag_eib` | Persistent mount at `/mdc-mcp-rag`   |
| systemd services              | AWS-managed services                    |
| GitLab CI/CD                  | AWS CodePipeline / GitHub Actions       |
| Spack module system           | Amazon Linux packages / pip             |

## Persistent Storage

On this AWS EC2 instance, the persistent mount point is:
```
/mdc-mcp-rag
```
This replaces the legacy `/mcp_rag_eib` path. All data directories (ChromaDB, Neo4j, logs)
should be rooted here for persistence across instance reprovisioning.

## Branch Strategy

We are on branch `develop_aws`. SDD spec files and code changes are committed here.
When an SDD phase is completed and validated, it gets pushed to the legacy system
until the AWS instance is fully self-hosting.

## Workspace Layout

- `eib-mcp-rag-server/` — Main project (MCP server source, SDD framework, infrastructure)
- `guidance-for-deploying-model-context-protocol-servers-on-aws/` — AWS MCP deployment reference architecture (CDK patterns, Cognito integration, cost estimates)
- `ec2-user/` — Home directory on this EC2 instance
- `powers/` — Kiro powers configuration

## Adapter Pattern (Phase 48, Steps 6/8/10/11 — COMPLETED)

The data access layer now uses an adapter pattern for backend-agnostic database access:

```
UnifiedDataAccess (src/data/)
  ├── selectDatabaseBackend() → reads DB_BACKEND env var
  │     ├── 'legacy' → ChromaDBLegacyAdapter + Neo4jLegacyAdapter (current default)
  │     └── 'aws'    → OpenSearchAdapter + NeptuneAdapter (not yet implemented)
  │
  ├── src/data/adapters/VectorDatabaseAdapter.js    (base class, 16 methods)
  ├── src/data/adapters/GraphDatabaseAdapter.js      (base class, 34 methods)
  ├── src/data/adapters/ChromaDBLegacyAdapter.js     (passthrough to VectorDatabase.js)
  ├── src/data/adapters/Neo4jLegacyAdapter.js        (passthrough to GraphDatabase.js)
  ├── src/data/adapters/backend-selector.js          (routing logic)
  └── src/data/adapters/index.js                     (barrel export)
```

**Critical**: `UnifiedDataAccess.js` was modified (3 lines) to use `selectDatabaseBackend()`.
The `this.graphDB` and `this.vectorDB` properties are still exposed — two tool modules
(`CodeAnalysisTools`, `GraphRAGTools`) access `this.dataAccess.graphDB` directly for GGSR.
Do NOT change this property exposure pattern.

**Zero tool module files were modified.** All 51 tools work identically in legacy mode.

## Key Directories

| Path | Purpose |
|------|---------|
| `mcp_server_node/` | Node.js MCP server source (51 tools, 9 modules) |
| `sdd_framework/` | SDD methodology, workflow specs, execution state |
| `SETUP/` | Legacy provisioning scripts (Docker-based, being ported) |
| `docker/` | Docker configs (legacy, reference only on AWS) |
| `supported_repos/` | Read-only git submodules (global-workflow, etc.) |
| `docs/` | Technical docs, compliance reports, presentations |
