# EIB MCP-RAG Platform — AWS Architecture Reference

**Organization:** NOAA / NWS / NCEP / EMC / EIB  
**Version:** 2.0.0 (with AWS Bedrock AgentCore)  
**Date:** May 2026  
**Authors:** EIB Development Team

---

## 1. Executive Summary

The EIB MCP-RAG Platform is an AI-assisted development system for NOAA's operational weather forecasting codebase (Global Workflow). It combines a **hybrid triple-store RAG engine** (vector + graph search) with a **Model Context Protocol (MCP) server** exposing 34+ tools, and now integrates **AWS Bedrock AgentCore** for managed AI agent deployment. The platform enables intelligent code analysis, EE2 compliance validation, and operational guidance across HPC environments (Hera, Hercules, Orion, WCOSS2, Gaea).

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              AWS CLOUD (us-east-1)                              │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │                    AWS Bedrock AgentCore Runtime                          │   │
│  │                                                                           │   │
│  │  ┌─────────────────────────────────────────────────────────────────────┐   │   │
│  │  │  HelloAgent (Strands Agent)                                        │   │   │
│  │  │  • Python 3.10 / strands-agents SDK                                │   │   │
│  │  │  • Model: Claude Sonnet 4.5 (global inference profile)             │   │   │
│  │  │  • Tools: CodeInterpreter + MCP tools + custom tools               │   │   │
│  │  │  • Memory: Session-scoped (NO_MEMORY mode)                         │   │   │
│  │  │  • Network: PUBLIC mode                                            │   │   │
│  │  │  • Protocol: HTTP                                                  │   │   │
│  │  │  • Observability: OpenTelemetry enabled                            │   │   │
│  │  └──────────────────────────┬──────────────────────────────────────────┘   │   │
│  │                             │                                             │   │
│  │                             │ Streamable HTTP (MCP)                       │   │
│  │                             ▼                                             │   │
│  │                   ┌─────────────────────┐                                 │   │
│  │                   │  AgentCore Gateway   │                                │   │
│  │                   │  (MCP Endpoint)      │                                │   │
│  │                   └─────────┬───────────┘                                 │   │
│  └─────────────────────────────┼─────────────────────────────────────────────┘   │
│                                │                                                 │
│  ┌─────────────────────────────┼─────────────────────────────────────────────┐   │
│  │  AWS Bedrock                │                                             │   │
│  │  • Foundation Models (Claude Sonnet 4.5)                                  │   │
│  │  • Global Inference Profiles                                              │   │
│  └───────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │  AWS IAM                                                                  │   │
│  │  • AgentCore Execution Role (auto-created)                                │   │
│  │  • S3 access for deployment artifacts                                     │   │
│  │  • Bedrock model invocation permissions                                   │   │
│  └───────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │  AWS S3                                                                   │   │
│  │  • Deployment artifacts (auto-created bucket)                             │   │
│  │  • Agent source code packages                                             │   │
│  └───────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │  AWS EC2 Instance (MDC Development Server)                                │   │
│  │  • OS: Rocky Linux 9 / Amazon Linux 2023                                  │   │
│  │  • Provisioned via: SETUP_AWS/provisioning/ scripts                       │   │
│  │  • Node.js 20, Python 3.12, Docker 25.x, AWS CLI v2                      │   │
│  │  • Kiro IDE + MCP client configuration                                    │   │
│  └───────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │  GitLab Container Registry (NOAA VLab)                                    │   │
│  │  • chromadb:v134clean                                                     │   │
│  │  • eib-mcp-rag:latest                                                     │   │
│  │  • mcp-server:env-dev-ops / env-staging / env-production                  │   │
│  └───────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
                                     │
                    ─ ─ ─ ─ ─ ─ ─ ─ ─│─ ─ ─ ─ ─ ─ ─ ─ ─
                                     │
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     ON-PREMISES / VM SERVER INFRASTRUCTURE                       │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │                         AI CLIENT LAYER                                   │   │
│  │                                                                           │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │   │
│  │  │  Kiro    │  │ VS Code  │  │  Claude  │  │  Cursor  │  │   n8n    │    │   │
│  │  │  IDE     │  │ Copilot  │  │ Desktop  │  │          │  │ Workflow │    │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │   │
│  │       │             │             │             │             │           │   │
│  │       └─────────────┴──────┬──────┴─────────────┴─────────────┘           │   │
│  │                            │                                              │   │
│  └────────────────────────────┼──────────────────────────────────────────────┘   │
│                               │                                                 │
│  ┌────────────────────────────┼──────────────────────────────────────────────┐   │
│  │                    GATEWAY LAYER                                           │   │
│  │                            │                                              │   │
│  │              ┌─────────────▼──────────────┐                               │   │
│  │              │    Docker MCP Gateway       │                               │   │
│  │              │    Port 18888 (Streaming)   │                               │   │
│  │              │    Bearer token auth        │                               │   │
│  │              │    systemd: mcp-gateway     │                               │   │
│  │              └─────────────┬──────────────┘                               │   │
│  │                            │ stdio                                        │   │
│  │              ┌─────────────┼──────────────┐                               │   │
│  │              │             │              │                                │   │
│  │     ┌────────▼───────┐  ┌─▼──────────┐  ┌▼──────────────┐                │   │
│  │     │ EIB-MCP-RAG    │  │ GitHub MCP │  │ Future MCP    │                │   │
│  │     │ Server (34     │  │ Server     │  │ Servers       │                │   │
│  │     │ tools)         │  │            │  │               │                │   │
│  │     │ systemd:       │  └────────────┘  └───────────────┘                │   │
│  │     │ mcp-rag        │                                                    │   │
│  │     └───────┬────────┘                                                    │   │
│  │             │                                                             │   │
│  └─────────────┼─────────────────────────────────────────────────────────────┘   │
│                │                                                                 │
│  ┌─────────────┼─────────────────────────────────────────────────────────────┐   │
│  │         DATA LAYER                                                        │   │
│  │             │                                                             │   │
│  │    ┌────────┴────────────────────┐                                        │   │
│  │    │                             │                                        │   │
│  │    ▼                             ▼                                        │   │
│  │  ┌──────────────────┐   ┌──────────────────┐                              │   │
│  │  │    ChromaDB      │   │     Neo4j        │                              │   │
│  │  │  Vector Database │   │  Graph Database  │                              │   │
│  │  │                  │   │                  │                              │   │
│  │  │  Port: 8080      │   │  HTTP: 7474      │                              │   │
│  │  │  12 collections  │   │  Bolt: 7687      │                              │   │
│  │  │  14,856 docs     │   │  2,730 files     │                              │   │
│  │  │  768-dim vectors │   │  1,481 functions │                              │   │
│  │  │  (all-mpnet-     │   │  85,894 rels     │                              │   │
│  │  │   base-v2)       │   │  APOC + GDS      │                              │   │
│  │  │                  │   │                  │                              │   │
│  │  │  Docker or       │   │  Docker          │                              │   │
│  │  │  systemd         │   │  (neo4j:5.26.20) │                              │   │
│  │  └──────────────────┘   └──────────────────┘                              │   │
│  │                                                                           │   │
│  │  Persistent Storage: /mcp_rag_eib/ (25GB mount)                           │   │
│  │  ├── data/chromadb/     ├── data/neo4j/                                   │   │
│  │  ├── cache/huggingface/ ├── supported_repos/global-workflow/              │   │
│  │  └── sdd_framework/     └── spack/ (package manager)                      │   │
│  │                                                                           │   │
│  └───────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Descriptions

### 3.1 AWS Bedrock AgentCore (NEW)

The newest addition to the platform. AgentCore provides a fully managed runtime for deploying AI agents that can use tools, maintain sessions, and execute code.

| Property | Value |
|----------|-------|
| **Agent Name** | HelloAgent_Agent |
| **Framework** | Strands Agents SDK (v1.13.0+) |
| **Language** | Python 3.10 |
| **Foundation Model** | Claude Sonnet 4.5 (global inference profile) |
| **Deployment** | Direct code deploy to AgentCore Runtime |
| **Network** | PUBLIC mode |
| **Protocol** | HTTP |
| **Observability** | OpenTelemetry enabled |
| **Memory** | NO_MEMORY (session-scoped) |

**Key capabilities:**
- **Code Interpreter** — AgentCore-managed sandbox for executing Python code
- **MCP Tool Access** — Connects to external MCP servers via Streamable HTTP
- **Custom Tools** — Python function tools (e.g., `add_numbers`)
- **Session Persistence** — Code interpreter sessions persist across invocations
- **Auto-scaling** — Managed by AgentCore runtime (no manual scaling)

**Dependencies:**
- `bedrock-agentcore >= 1.0.3` — AgentCore SDK
- `strands-agents >= 1.13.0` — Agent framework
- `strands-agents-tools >= 0.2.16` — Built-in tool library
- `mcp >= 1.19.0` — Model Context Protocol client
- `boto3 >= 1.38.0` — AWS SDK

### 3.2 EIB MCP-RAG Server (Core)

The central intelligence layer — a Node.js MCP server with 34 registered tools for code analysis, documentation search, compliance checking, and operational guidance.

| Property | Value |
|----------|-------|
| **Version** | v3.6.2 |
| **Runtime** | Node.js 20 |
| **Tools** | 34 registered |
| **Transport** | stdio (via Docker MCP Gateway) |
| **Container** | `eib-mcp-rag:latest` |
| **Resources** | 8GB RAM, 4 CPUs |

**Tool categories:**
- **Workflow Info** (3 tools) — Structure, configs, component descriptions
- **Code Analysis** (4 tools) — Dependencies, call trees, execution tracing
- **Semantic Search** (8 tools) — Hybrid vector + graph search
- **EE2 Compliance** (5 tools) — NOAA standards validation
- **SDD Workflow** (6 tools) — Structured development workflows
- **GitHub Integration** (4 tools) — Issues, PRs, repository analysis
- **Operational** (3 tools) — HPC guidance, system configs
- **Session Management** (3 tools) — Checkpoints, modifications, context

### 3.3 ChromaDB (Vector Database)

Provides semantic similarity search using 768-dimensional embeddings.

| Property | Value |
|----------|-------|
| **Version** | 1.3.4 (custom image) |
| **Port** | 8080 |
| **API** | REST v2 |
| **Collections** | 12 |
| **Documents** | 14,856 |
| **Embedding Model** | Xenova/all-mpnet-base-v2 (768-dim) |
| **Storage** | `/mcp_rag_eib/data/chromadb/` |

**Collections include:**
- `global-workflow-docs-v8-0-0` — Workflow documentation
- `jjobs-v8-0-0` — J-Job script analysis
- `ee2-standards-v5-0-0-enhanced` — EE2 compliance standards
- Code analysis, architecture summaries, and more

### 3.4 Neo4j (Graph Database)

Provides structural relationship queries — call trees, dependency graphs, cross-language execution tracing.

| Property | Value |
|----------|-------|
| **Version** | 5.26.20 Community |
| **Ports** | 7474 (HTTP), 7687 (Bolt) |
| **Plugins** | APOC, Graph Data Science (GDS) |
| **Files indexed** | 2,730 |
| **Functions indexed** | 1,481 |
| **Relationships** | 85,894 |
| **Storage** | `/mcp_rag_eib/data/neo4j/` |

**Graph capabilities:**
- Cross-language execution tracing (Shell → Fortran → Python)
- Dependency analysis (upstream/downstream)
- Environment variable dependency tracking
- Community detection and architecture analysis
- Change impact / blast radius analysis

### 3.5 Docker MCP Gateway

Bridges multiple AI clients to the MCP server ecosystem via Server-Sent Events (SSE) / Streaming HTTP transport.

| Property | Value |
|----------|-------|
| **Port** | 18888 |
| **Transport** | Streaming (SSE) |
| **Auth** | Bearer token |
| **Mode** | Static (long-lived container) |
| **systemd** | `mcp-gateway.service` |

### 3.6 n8n Workflow Automation

Visual workflow automation engine (replaced LangFlow in January 2026).

| Property | Value |
|----------|-------|
| **Port** | 5678 |
| **Auth** | admin / eib-n8n-2025 |
| **Purpose** | RAG pipeline visualization, tool chain debugging |

---

## 4. Data Flow

### 4.1 Ingestion Pipeline

```
Source Repositories                    Knowledge Stores
─────────────────                      ────────────────
global-workflow (GFS)  ──┐
nws-hpc-standards      ──┤  Parse &    ┌─────────────┐
EE2 compliance docs    ──┤  Extract ──▶│  ChromaDB    │  (semantic embeddings)
J-Job scripts          ──┤             └─────────────┘
Fortran source (sorc/) ──┘             ┌─────────────┐
                           Extract ──▶ │   Neo4j     │  (structural relationships)
                           Rels        └─────────────┘
```

### 4.2 Query Pipeline (Developer via Kiro/IDE)

```
Developer ──▶ Kiro IDE ──▶ Docker MCP Gateway ──▶ EIB-MCP-RAG Server
                                                        │
                                              ┌─────────┴─────────┐
                                              ▼                   ▼
                                          ChromaDB            Neo4j
                                       (vector search)    (graph traversal)
                                              │                   │
                                              └─────────┬─────────┘
                                                        ▼
                                                 Hybrid Results
                                                        │
                                                        ▼
                                                  Developer (IDE)
```

### 4.3 AgentCore Pipeline (NEW)

```
User/API ──▶ AgentCore Runtime ──▶ HelloAgent (Strands)
                                        │
                                        ├──▶ Claude Sonnet 4.5 (Bedrock)
                                        ├──▶ Code Interpreter (sandbox)
                                        ├──▶ MCP Client ──▶ External MCP servers
                                        └──▶ Custom tools (add_numbers, etc.)
                                                │
                                                ▼
                                          Response ──▶ User/API
```

---

## 5. Deployment Environments

| Environment | Branch | Compose File | Database Mode | Access |
|-------------|--------|-------------|---------------|--------|
| **Development** | feature/*, develop | `SETUP/docker-compose.yml` | PersistentClient (local) | Local VM |
| **DevOps** | env/dev-ops | `docker-compose.devops.yaml` | HttpClient (containers) | Docker network |
| **Staging** | env/staging | `docker-compose.staging.yaml` | HttpClient (read-only) | Pre-production |
| **Production** | env/production | `docker-compose.production.yaml` | CI/CD only | GitLab pipeline |
| **AWS (AgentCore)** | main | `bedrock_agentcore deploy` | Remote MCP | AWS managed |

---

## 6. Service Management

### systemd Services (On-Premises)

| Service | Description | Depends On |
|---------|-------------|------------|
| `chromadb-persistent.service` | ChromaDB vector database | mount |
| `mcp-rag.service` | EIB MCP-RAG container | docker, chromadb |
| `mcp-gateway.service` | Docker MCP Gateway | mcp-rag |
| `mcp-container-cleanup.timer` | Container lifecycle cleanup | docker |

### AWS Managed Services

| Service | Description | Management |
|---------|-------------|------------|
| Bedrock AgentCore Runtime | Agent hosting & scaling | Fully managed |
| Bedrock Foundation Models | Claude Sonnet 4.5 | Pay-per-token |
| AgentCore Code Interpreter | Sandboxed Python execution | Session-managed |
| S3 | Deployment artifacts | Auto-created |
| IAM | Execution roles | Auto-created |

---

## 7. Kiro Powers & MCP Ecosystem

The development environment uses **Kiro IDE** with five installed powers:

| Power | Purpose | MCP Server | Status |
|-------|---------|------------|--------|
| **aws-agentcore** | Build, deploy, operate AI agents on Bedrock AgentCore | `agentcore-mcp-server` | ✅ Active |
| **aws-infrastructure-as-code** | CDK/CloudFormation development, validation, compliance, troubleshooting | `awslabs.aws-iac-mcp-server` | ✅ Active |
| **iam-policy-autopilot** | Generate & deploy IAM policies from source code analysis | `iam-policy-autopilot-mcp` | ✅ Active |
| **opensearch-launchpad** | Build search applications with OpenSearch (local → AWS) | `opensearch-launchpad` | ✅ Active |
| **design-system-scaffold** | UI component specs, theming, accessibility | *(steering only)* | ✅ Active |

### Additional MCP Servers (via Gateway)

| Server | Transport | Purpose |
|--------|-----------|---------|
| `eib-mcp-rag` | stdio (via gateway) | Core RAG + code analysis (34 tools) |
| `eib-mcp-gateway` | HTTP (dev tunnel) | Remote access to MCP-RAG |
| GitHub MCP Server | stdio | Repository operations |

---

## 8. Security Architecture

### Authentication & Authorization

| Layer | Mechanism |
|-------|-----------|
| MCP Gateway | Bearer token authentication |
| Neo4j | Username/password (bolt) |
| n8n | Basic auth |
| AgentCore | IAM execution role |
| Bedrock Models | IAM permissions |
| GitLab Registry | CI/CD tokens |
| AWS API | IAM credentials (CLI profile) |

### Network Boundaries

- **Docker MCP Gateway** provides isolation between AI clients and backend services
- **AgentCore** runs in AWS-managed VPC with PUBLIC network mode
- **Container resources** are capped (8GB RAM, 4 CPUs per service)
- **Read-only mounts** for source repositories in MCP-RAG container
- **systemd security** — `no-new-privileges` on MCP-RAG container

---

## 9. Technology Stack Summary

| Layer | Technologies |
|-------|-------------|
| **AI Models** | Claude Sonnet 4.5 (Bedrock), Xenova/all-mpnet-base-v2 (embeddings) |
| **Agent Framework** | Strands Agents SDK, Bedrock AgentCore Runtime |
| **MCP Server** | Node.js 20, Model Context Protocol |
| **Vector DB** | ChromaDB 1.3.4 (REST API v2) |
| **Graph DB** | Neo4j 5.26.20 Community (APOC + GDS) |
| **Containers** | Docker 25.x, Docker Compose, Docker MCP Gateway |
| **Service Mgmt** | systemd (on-prem), AgentCore (AWS managed) |
| **Package Mgmt** | Spack, Lmod, npm, pip, uv/uvx |
| **Workflow** | n8n (automation), SDD Framework (24 workflows) |
| **IaC** | AWS CDK, CloudFormation |
| **CI/CD** | GitLab CI/CD, GitFlow branching |
| **Languages** | Node.js, Python, Bash |
| **IDE** | Kiro (5 powers), VS Code + Copilot |

---

## 10. Future Roadmap

| Item | Status | Description |
|------|--------|-------------|
| PostgreSQL metadata store | Planned | Third leg of triple-store (structured metadata) |
| OpenSearch integration | Available (power installed) | Full-text + vector search via opensearch-launchpad |
| AWS Neptune | Planned | Managed graph database (replace self-hosted Neo4j) |
| Multi-agent orchestration | In progress | Multiple AgentCore agents with specialized roles |
| CDK infrastructure | Available (power installed) | IaC for all AWS resources via aws-infrastructure-as-code |
| IAM policy automation | Available (power installed) | Auto-generate least-privilege policies from code |
