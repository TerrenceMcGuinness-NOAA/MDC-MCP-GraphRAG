# EIB MCP-RAG Server

**AI-Assisted Development Platform for NOAA Operational Weather Systems**

A comprehensive Model Context Protocol (MCP) and Retrieval-Augmented Generation (RAG) framework developed by NOAA EMC/EIB for intelligent workflow assistance, code analysis, and EE2 compliance validation.

## Current Status (December 2025)

| Component | Status | Details |
|-----------|--------|---------|
| **MCP Server** | ✅ Operational | v3.6.2, 34 tools registered |
| **Docker MCP Gateway** | ✅ Complete | Phase 11, SSE transport on port 8888 |
| **ChromaDB** | ✅ Healthy | 12 collections, 14,856 documents |
| **Neo4j** | ✅ Healthy | 2,730 files, 1,481 functions, 85,894 relationships |
| **GitLab Registry** | ✅ Ready | `chromadb:v134clean`, `eib-mcp-rag:latest` |
| **GitFlow Branches** | ✅ Created | develop, env/dev-ops, env/staging, env/production |

## Overview

This framework provides AI-assisted development capabilities for complex systems through:
- **MCP Server Integration** - 16+ tools for code analysis, documentation search, and operational guidance
- **RAG Knowledge Base** - Hybrid vector (ChromaDB) + graph (Neo4j) semantic search
- **EE2 Compliance Analysis** - Automated NCO standards validation for WCOSS2 production
- **HPC Integration** - Platform-specific configs for Hera, Hercules, Orion, WCOSS2, Gaea
- **SDD Workflow Framework** - 24 structured workflows with supervised execution

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP-RAG System                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ MCP Server  │  │  ChromaDB   │  │   Neo4j     │          │
│  │ (Node.js)   │  │  (Vectors)  │  │  (Graph)    │          │
│  │  34 Tools   │  │ 14,856 docs │  │ 85K+ rels   │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
│         └────────────────┼────────────────┘                 │
│                          │                                  │
│         ┌────────────────┴────────────────┐                 │
│         │     Hybrid Query Engine         │                 │
│         │  (Semantic + Structural)        │                 │
│         └────────────────┬────────────────┘                 │
└──────────────────────────┼──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │   VS Code + Copilot     │
              │   (Developer Interface) │
              └─────────────────────────┘
```

### Docker MCP Gateway Architecture (Phase 11)

The system supports multi-client AI access via Docker MCP Gateway, enabling integration with VS Code Copilot, LangFlow, Claude Desktop, and other MCP-compatible clients:

```
┌────────────────────────────────────────────────────────────────┐
│                     AI Clients                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ LangFlow │  │ VS Code  │  │  Claude  │  │  Cursor  │        │
│  │          │  │ Copilot  │  │ Desktop  │  │          │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│       │             │             │             │              │
│       └─────────────┴──────┬──────┴─────────────┘              │
│                            │                                   │
│                   ┌────────▼────────┐                          │
│                   │  Docker MCP     │                          │
│                   │    Gateway      │ Port 8888 (SSE)          │
│                   │  (docker-mcp)   │                          │
│                   └────────┬────────┘                          │
│                            │ stdio                             │
│           ┌────────────────┼────────────────┐                  │
│           │                │                │                  │
│   ┌───────▼───────┐ ┌──────▼──────┐ ┌──────▼──────┐            │
│   │ EIB-MCP-RAG   │ │  GitHub     │ │  Future     │            │
│   │ Server        │ │  MCP Server │ │  Servers    │            │
│   │ (34 tools)    │ │             │ │             │            │
│   └───────┬───────┘ └─────────────┘ └─────────────┘            │
│           │                                                    │
│   ┌───────┴────────────────────┐                               │
│   │                            │                               │
│   ▼                            ▼                               │
│ ┌──────────────┐       ┌──────────────┐                        │
│ │   ChromaDB   │       │    Neo4j     │                        │
│ │  (Vectors)   │       │   (Graph)    │                        │
│ │  Port 8080   │       │  Port 7687   │                        │
│ └──────────────┘       └──────────────┘                        │
└────────────────────────────────────────────────────────────────┘
```

```
┌───────────────────────────────────────────────────────────────────────┐
│                    CURRENT ARCHITECTURE (Phase 11)                    │
│                                                                       │
│  Your VM Server (3.236.197.228)                                       │
│  ═══════════════════════════════                                      │
│  ├── Spack Environment (gcc, python, py-* modules)                    │
│  ├── Node.js (system or spack)                                        │
│  ├── /mcp_rag_eib/ (persistent data root)                             │
│  │                                                                    │
│  │   Docker Containers (depend on host mounts):                       │
│  │   ┌─────────────────────────────────────────────────────────┐      │
│  │   │  eib-mcp-rag:latest                                     │      │
│  │   │  • Volume: /mcp_rag_eib/supported_repos → /app/:ro      │      │
│  │   │  • Volume: /mcp_rag_eib/sdd_framework → /app/:ro        │      │
│  │   │  • Network: connects to chromadb, neo4j containers      │      │
│  │   └─────────────────────────────────────────────────────────┘      │
│  │   ┌──────────────┐  ┌──────────────┐                               │
│  │   │  ChromaDB    │  │   Neo4j      │  ← Separate containers        │
│  │   │  (8080)      │  │  (7474/7687) │    with volume mounts         │
│  │   └──────────────┘  └──────────────┘                               │
│  │                                                                    │
│  └── Docker MCP Gateway (8888) ← Bridges to AI clients                │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```



**Key Benefits:**
- **Multi-Client Support**: Single MCP server serves VS Code, LangFlow, Claude Desktop, and Cursor simultaneously
- **SSE Transport**: Server-Sent Events enable real-time streaming responses to AI clients
- **Tool Composition**: LangFlow enables visual debugging of tool chains and intermediate response inspection
- **Container Isolation**: Gateway provides security boundary between AI clients and backend services

**Quick Start with Gateway:**
```bash
# Start infrastructure
docker compose -f docker-compose.devops.yaml up -d

# Start MCP Gateway (SSE transport for multi-client support)
docker mcp gateway run --servers eib-mcp-rag --transport sse --port 8888 --long-lived

# Gateway outputs bearer token for client authentication
# Connect LangFlow to: http://localhost:8888/sse
```

For detailed gateway configuration, see [Phase 11 SDD](sdd_framework/workflows/phase11_docker_mcp_gateway_langflow.md).

## Repository Structure

```
eib-mcp-rag-server/
├── mcp_server_node/           # Node.js MCP server (v3.0.0)
│   ├── src/                   # Server source code
│   │   ├── UnifiedMCPServer.js
│   │   ├── tools/             # MCP tool modules
│   │   └── config/            # Environment configuration
│   ├── scripts/               # Ingestion and utility scripts
│   └── test/                  # Test suites
├── docker/                    # Container definitions
│   └── chromadb/              # Custom ChromaDB 1.3.4 image
├── docker-compose.*.yaml      # Environment-specific stacks
├── sdd_framework/             # SDD workflows and templates
│   ├── workflows/             # 24 structured workflows
│   └── PRIORITY_ROADMAP.md    # Executive roadmap
├── docs/                      # Documentation
│   ├── EE2_compliance_reports/  # EE2 audit reports
│   ├── development/           # Dev docs
│   └── technical_specification/
├── supported_repos/           # Git submodules (analysis targets)
│   ├── global-workflow/       # NOAA GFS operational code
│   └── nws-hpc-standards/     # EE2 compliance standards
└── SETUP/                     # Provisioning scripts
```

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Node.js 18+
- Access to GitLab Container Registry (for production images)

### Development Mode (Local)

```bash
# Clone with submodules
git clone --recursive git@gitlab-licensed.vlab.noaa.gov:NWS/Operations/NCEP/EMC/EIB/eib-mcp-rag-server.git
cd eib-mcp-rag-server

# Start databases
docker compose -f docker-compose.devops.yaml up -d chromadb neo4j

# Start MCP server
cd mcp_server_node
npm install
node src/UnifiedMCPServer.js full
```

### Container Mode (DevOps)

```bash
# Pull from GitLab Registry
docker login registry.gitlab-licensed.vlab.noaa.gov

# Start full stack
MCP_ENV=devops docker compose -f docker-compose.devops.yaml up -d
```

## Environment Isolation

| Environment | Branch | Database Access | Purpose |
|-------------|--------|-----------------|---------|
| `development` | feature/*, develop | PersistentClient (local) | Experimentation |
| `devops` | env/dev-ops | HttpClient (containers) | Container validation |
| `staging` | env/staging | HttpClient (read-only) | Pre-production |
| `production` | env/production | CI/CD only | Live deployment |

## MCP Tools Available

| Category | Tools | Purpose |
|----------|-------|---------|
| **Workflow Info** | 3 | System structure, platform configs |
| **Code Analysis** | 4 | Dependencies, call chains, structure |
| **Semantic Search** | 8 | Documentation, EE2 compliance, patterns |
| **Operational** | 3 | HPC guidance, job scripts |

## Key Documentation

- [SDD Priority Roadmap](sdd_framework/PRIORITY_ROADMAP.md) - Executive summary and delivery roadmap
- [Phase 12 DevOps SDD](sdd_framework/workflows/phase12_devops_gitflow_containerization.md) - GitFlow and containerization
- [EE2 Compliance Reports](docs/EE2_compliance_reports/) - Audit reports for EVS, seaice-concentration
- [MCP Server README](mcp_server_node/README.md) - Detailed server documentation

## GitLab Container Registry

```
registry.gitlab-licensed.vlab.noaa.gov/nws/operations/ncep/emc/eib/eib-mcp-rag-server/
├── chromadb:v134clean     # Custom ChromaDB 1.3.4 (matches data schema)
├── chromadb:latest        # Official image (reference only)
└── mcp-server:*           # MCP server images (via CI/CD)
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for GitFlow branch strategy and development workflow.

---
**NOAA Environmental Modeling Center / Enterprise Infrastructure Branch**  
**Lead**: Terrence McGuinness  
**Last Updated**: December 11, 2025
