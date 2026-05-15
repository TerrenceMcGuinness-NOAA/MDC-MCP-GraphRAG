---
inclusion: auto
---

# MDC MCP RAG — AWS Porting Architecture Context

## Infrastructure as Code (IaC) — Primary Principle

All AWS infrastructure MUST be defined and deployed via Infrastructure as Code:
- **CDK** for VPC, Neptune, OpenSearch, EFS, S3, IAM roles (existing `infrastructure/cdk/`)
- **AWS Bedrock AgentCore** for MCP server deployment (Runtime, Gateway, Memory)
- **CloudFormation** as the underlying deployment mechanism
- **No manual AWS console changes** — all config via code, CLI, or CDK
- Hand-rolled scripts (HTTP wrappers, manual port forwarding) are acceptable ONLY as
  temporary bridges during development. Production deployment uses managed AWS services.

## What This Project Is

This workspace (`eib-mcp-rag-server`) contains the source code for the **MDC MCP RAG Server**
(formerly EIB MCP RAG Server, renamed after institutional reorganization from EIB → MDC).

It is an MCP/RAG development platform for NOAA Global Workflow AI assistance, providing 51 tools
across 9 modules for code analysis, EE2 compliance validation, semantic search, SDD workflow
tracking, and operational guidance for weather forecasting infrastructure.

## Two-Layer Architecture: MCP-as-a-Service + Agent Consumers

The AgentCore deployment creates a clean architectural split that unlocks new delivery patterns beyond the original MCP/Kiro use case.

### Layer 1 — MCP-as-a-Service (what we built)

The `mdc_mcp_rag_server` AgentCore Runtime is a shared, authenticated, auto-scaling
**tool library**. AgentCore provides microVM session isolation, inbound auth (Cognito
JWT after Phase B), VPC-private backend access, and observability. It hosts our
51 tools but does not itself perform reasoning or orchestration — it is a library
of primitives.

This layer stays dumb, stable, and composable. Changes to Layer 2 do not require
redeploying Layer 1.

### Layer 2 — Consumers (three tiers)

**Tier A — Direct consumers** use the MCP as their own tool source. Each just needs
an endpoint URL and a JWT:
- Kiro IDE (developer workstation, macOS laptop)
- GitHub Actions CI pipelines (Phase B flagship)
- HPC researcher sessions (Phase B)

**Tier B — Agent-wrapped consumers** are full AgentCore Runtime deployments (one
per agent, each with its own IAM role and Cognito client) that wrap the MCP behind
a task-specific interface. They give end users a single endpoint for a multi-step
analytical workflow:
- EE2 Compliance Analyzer (takes code/logs, returns synthesized diagnosis)
- Build Failure Diagnoser (takes Rocoto log, returns root-cause narrative)
- Code Review Assistant (takes PR diff, returns review comments)
- Onboarding Docent (natural-language Q&A for new team members)

The `HelloAgent/` folder is an AWS-provided scaffold of this pattern — ~80 lines
of Strands + Bedrock + MCP client showing the complete agent shape. It is retained
as a reference, not used in production.

**Tier C — Scheduled consumers** run on a cadence against the MCP:
- Drift monitor (nightly `check_knowledge_integrity`)
- EE2 baseline bot (weekly `scan_repository_compliance`)
- Release notes generator (on-tag change analysis)

### Why this partition is correct

- **Trust boundaries are clean**: each Tier B agent has its own IAM role; revoking
  one agent does not affect the MCP or other agents.
- **Cost is attributable**: each agent runtime is billed independently.
- **Models evolve separately**: agents can use different Bedrock models (Sonnet,
  Haiku, Nova) without touching the MCP.
- **Agent CI/CD is lightweight**: new agents are ~80-line forks of HelloAgent;
  creating one does not touch `mcp_server_node/` or the infrastructure stacks.

### Implication for Kiro

When designing new features, ask: is this a Layer 1 addition (a new MCP tool
primitive) or a Layer 2 addition (a new agent or direct consumer)? Default to
Layer 2 unless the capability is a reusable primitive that multiple consumers
will need. Keep Layer 1 narrow and stable.

## AWS Bedrock AgentCore — MCP Deployment Target

The MCP server is deployed to **AWS Bedrock AgentCore Runtime** as an ARM64 container:

- **Runtime ID**: `mdc_mcp_rag_server-TMXDllG2Wi` (status: READY)
- **Protocol**: MCP (Streamable HTTP on port 8000)
- **Entrypoint**: `mcp_server_node/src/mcp-agentcore-entrypoint.js`
- **Container**: `903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:agentcore`
- **Network**: VPC mode (private subnets us-east-1a, us-east-1b)
- **Lifecycle**: idle timeout 900s, max lifetime 28800s
- **Kiro Proxy**: `tools/agentcore-kiro-proxy.py` (stdio bridge via boto3 `invoke_agent_runtime`)

AgentCore handles session isolation (microVMs), scaling, and lifecycle management.
The proxy translates Kiro's stdio JSON-RPC into AgentCore's SSE-based invocation API.

## Neptune Graph Database (AWS)

The knowledge graph is hosted on **Amazon Neptune** (openCypher):

- **Cluster**: `mdc-mcp-graprag-neptune-1`
- **Endpoint**: `wss://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182`
- **Data**: 164,916 nodes, 2,941,593 relationships (as of Phase 53 Track B re-ingestion)
- **Node labels**: File, ShellScript, FortranProgram, FortranModule, FortranSubroutine,
  FortranFunction, PythonModule, PythonClass, PythonFunction, CodeFile, CodeFunction,
  CodeClass, Community, EnvironmentVariable, ConfigFile, RocotoTask, RocotoMetatask,
  Experiment, CITestCase, Developer, Documentation, and more
- **Key relationships**: CALLS, INVOKES, EXECUTES, SOURCES, USES, IMPORTS, DEFINES,
  DEPENDS_ON, DEPENDS_ON_ENV, EXPORTS, MEMBER_OF, PARENT_OF, INTERACTS_WITH
- **Auth**: IAM SigV4 (via `mdc-mcp-rag-ecs-task-role`)
- **Access from Kiro**: Direct via Neptune MCP server (configured in `.kiro/settings/mcp.json`)

## OpenSearch (Vector Database)

- **Domain**: `vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com`
- **Data**: 85,921+ documents across 17 indices
- **Embedding model**: `Xenova/all-mpnet-base-v2` (768-dim, baked into container image)
- **Auth**: IAM SigV4

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
| `mcp_server_node/src/mcp-agentcore-entrypoint.js` | AgentCore Runtime entrypoint |
| `mcp_server_node/Dockerfile.agentcore` | ARM64 container for AgentCore |
| `mcp_server_node/.bedrock_agentcore.yaml` | AgentCore deployment config |
| `tools/agentcore-kiro-proxy.py` | Kiro ↔ AgentCore stdio bridge |
| `infrastructure/cdk/` | CDK stacks (VPC, Security, Data) |
| `sdd_framework/` | SDD methodology, workflow specs, execution state |
| `SETUP/` | Legacy provisioning scripts (Docker-based, reference only) |
| `supported_repos/` | Read-only git submodules (global-workflow, etc.) |
| `docs/` | Technical docs, compliance reports, presentations |
| `HelloAgent/` | Bedrock AgentCore starter template (Python, reference) |

## Steering vs Instruction Files — Boundary

| System | Location | Purpose | Loaded By |
|--------|----------|---------|-----------|
| **Kiro Steering** | `.kiro/steering/*.md` | Guides Kiro agent behavior — architecture, workflow, safety | Kiro (always-on) |
| **Kiro Hooks** | `.kiro/hooks/*.kiro.hook` | Automated triggers (CDK safety review on file edit) | Kiro (event-driven) |
| **COTS Instruction Files** | `.github/instructions/*.md` | Legacy MCP tool-usage reference for Copilot/Cursor | GitHub Copilot / Cursor |

**Do NOT conflate these.** Steering is the authoritative source for Kiro. The `.github/instructions/`
file is a COTS IDE integration artifact for when Copilot or Cursor connects to the legacy
`eib-mcp-gateway` server. It documents the same 51 tools but is not maintained for Kiro and
may drift from current architecture.
