# AI Coding Agent Instructions for EIB MCP-RAG Server

## Project Overview

MCP/RAG development platform for NOAA Global Workflow AI assistance. Provides 38 tools for code analysis, EE2 compliance validation, and semantic search across operational weather forecasting infrastructure.

**Architecture**: MCP Server (Node.js v7.1.0) → ChromaDB (vectors) + Neo4j (graph) → VS Code/Copilot

## Quick Start Commands

```bash
# Start infrastructure
docker compose -f docker-compose.devops.yaml up -d

# Verify services
curl http://localhost:8080/api/v2/heartbeat   # ChromaDB (MUST use v2 API)
curl http://localhost:7474                     # Neo4j

# Start MCP server (full mode with all tools)
cd mcp_server_node && node src/UnifiedMCPServer.js full

# Run tests
npm test                                        # Unit tests
npm run test:integration                        # Integration tests
```

## Critical Patterns

### SDD Methodology (REQUIRED for new features)

**SDD = Spec-Driven Development** with two phases:
1. **Planning Phase** - Create specification in `sdd_framework/workflows/phaseX_feature_name.md`
2. **Execution Phase** - Run via ISD or USD mode

| Acronym | Full Name | Description |
|---------|-----------|-------------|
| **SDD** | Spec-Driven Development | The methodology - plan first, then execute |
| **ISD** | Interactive Supervised Development | Human approves each side-effect step |
| **USD** | Unsupervised Development | Autonomous execution within approved scope |

**Rule**: "If it's not in the SDD, it doesn't get coded."

For detailed SDD agentic patterns and multi-step execution guidance, see:
- [spec_driven_design_core.md](sdd_framework/methodology/spec_driven_design_core.md)
- [phase4c_isd_usd_architecture.md](sdd_framework/workflows/phase4c_isd_usd_architecture.md)

### MCP-First Policy
Always try MCP tools before shell commands when analyzing code:
```javascript
// DO: Use MCP tools
analyze_code_structure({ file_path: "path/to/file" })
scan_repository_compliance({ repository_path: "/path" })

// DON'T: Fall back to shell first
// grep -r "pattern" /path  ← Only if MCP unavailable
```

### Code Style Conventions
- **Console output**: ASCII prefixes only (`[OK]`, `[ERROR]`, `[WARN]`) - NO emoji (breaks MCP stdio)
- **Indentation**: 2 spaces
- **Bash variables**: `"${variable}"` with quotes
- **Docstrings**: numpy style for Python

### SPOT (Single Point of Truth)
Configuration sources MUST be singular:
- Documentation URLs: `mcp_server_node/scripts/documentation_sources_config.py`
- Environment: `SETUP/mcp-env.sh`
- MCP config: `.vscode/mcp.json`

## Key Directories

| Path | Purpose |
|------|---------|
| `mcp_server_node/src/` | MCP server implementation |
| `mcp_server_node/src/tools/` | Tool modules (9 files) |
| `sdd_framework/workflows/` | Development workflow plans |
| `sdd_framework/methodology/` | SDD core patterns and architecture |
| `supported_repos/` | Git submodules (analysis targets, READ-ONLY) |
| `docker/chromadb/` | Custom ChromaDB image |
| `SETUP/` | Provisioning scripts and environment config |

## Domain Glossary

| Term | Meaning |
|------|---------|
| **EE2** | EMC Environment 2.0 - NCO production coding standards |
| **MCP** | Model Context Protocol - AI tool integration standard |
| **RAG** | Retrieval-Augmented Generation |
| **SDD** | Spec-Driven Development - plan first, then execute |
| **ISD** | Interactive Supervised Development - human approval gates |
| **USD** | Unsupervised Development - autonomous sub-agent execution |
| **GFS/GEFS** | Global Forecast System / Ensemble version |
| **HPC** | Hera, WCOSS2, Orion, Hercules, Gaea platforms |

## Software Stack Management (CRITICAL)

**Software CANNOT be installed arbitrarily.** All dependencies must go through the Spack module system and provisioning scripts.

### Spack-First Policy
```bash
# 1. Load gcc first (exposes py-* modules)
module load gcc/11.5.0

# 2. Load Python + dependencies from Spack
module load python/3.11 py-pip py-neo4j py-pydantic py-httpx py-requests

# 3. Only use pip --user for packages NOT in Spack
python3 -m pip install --user chromadb sentence-transformers
```

### Packages Requiring pip --user (Not in Spack)
| Package | Reason |
|---------|--------|
| `chromadb` | Vector DB client - not packaged in Spack |
| `sentence-transformers` | ML embeddings - complex torch dependency |
| `lxml`, `beautifulsoup4` | gcc-runtime hash conflicts with py-pydantic |

### Adding New Dependencies
1. Check if available in Spack: `spack list py-<package>`
2. If in Spack → Add `module load` to `SETUP/mcp-env.sh`
3. If NOT in Spack → Document in pip-only section of `mcp-env.sh`
4. Update provisioning scripts in `SETUP/`

**DO NOT:**
- Use `pip install` without `--user`
- Install without loading gcc module first
- Add undocumented dependencies

## Docker MCP Gateway Integration ✅ COMPLETE

**Status**: Phase 11 - Complete (December 17, 2025)  
**Reference**: [phase11_docker_mcp_gateway_langflow.md](sdd_framework/workflows/phase11_docker_mcp_gateway_langflow.md)

### Architecture
```
AI Clients (LangFlow, VS Code, Claude Desktop)
              │
              ▼
     Docker MCP Gateway (docker-mcp plugin)
         Port 18888 (Streamable HTTP transport)
              │
              ▼
     MCP Server Container (eib-mcp-rag:latest)
         35 tools available
              │
    ┌─────────┴─────────┐
    ▼                   ▼
ChromaDB            Neo4j
(vectors)           (graph)
```

### Quick Start - Gateway + LangFlow
```bash
# Start gateway with Streamable HTTP transport (bidirectional)
SETUP/bin/start-mcp-gateway.sh --background

# Or manually:
export MCP_GATEWAY_AUTH_TOKEN="eib-mcp-gateway-token-2025"
docker mcp gateway run --servers eib-mcp-rag --transport streaming --port 18888 --long-lived --verbose

# Gateway outputs:
# > Gateway URL: http://localhost:18888/mcp
# > Use Bearer token: Authorization: Bearer eib-mcp-gateway-token-2025
```

### Catalog Registration (CRITICAL)
The gateway requires **explicit catalog registration** - having YAML files in `~/.docker/mcp/catalogs/` is NOT sufficient:
```bash
# 1. Create catalog in docker mcp system
docker mcp catalog create eib-local

# 2. Add server from YAML file to catalog
docker mcp catalog add eib-local eib-mcp-rag ~/.docker/mcp/catalogs/eib-local.yaml

# 3. Enable server for gateway discovery
docker mcp server enable eib-mcp-rag

# 4. Verify registration
docker mcp catalog ls          # Should show: eib-local
docker mcp server ls           # Should show: eib-mcp-rag (enabled)
docker mcp tools ls            # Should show: 42 tools (35 EIB + 7 gateway)

# 5. Test discovery
docker mcp gateway run --servers eib-mcp-rag --dry-run --verbose
# Should show: > eib-mcp-rag: (35 tools)
```

### LangFlow Connection
1. Gateway URL: `http://host.docker.internal:18888/mcp` (from container) or `http://localhost:18888/mcp`
2. Transport: HTTP (Streamable HTTP)
3. Authorization header: `Bearer eib-mcp-gateway-token-2025`
4. Select `eib-mcp-rag` server in MCP Tools component

### Gateway Commands
```bash
# Build MCP server container
docker compose -f docker-compose.mcp-standalone.yaml build

# Test gateway discovery (dry-run)
docker mcp gateway run --servers eib-mcp-rag --dry-run --verbose

# List available tools
docker mcp tools ls

# Check container labels (gateway uses these for discovery)
docker inspect eib-mcp-rag --format '{{json .Config.Labels}}' | jq
```

# Check container labels (gateway uses these for discovery)
docker inspect eib-mcp-rag --format '{{json .Config.Labels}}' | jq
```

### MCP Catalog Configuration
Location: `~/.docker/mcp/catalogs/eib-local.yaml`
```yaml
version: 3
name: eib-local
registry:
  eib-mcp-rag:
    title: EIB MCP RAG Server
    type: server
    image: eib-mcp-rag:latest
    env:
      - name: CHROMADB_HOST
        value: "172.17.0.1"
      - name: NEO4J_URI
        value: bolt://172.17.0.1:7687
      - name: MCP_WORKFLOW_ROOT
        value: /app/supported_repos/global-workflow
    volumes:
      - /mcp_rag_eib/eib-mcp-rag-server/supported_repos:/app/supported_repos:ro
      - /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/scripts:/app/scripts:ro
      - /mcp_rag_eib/eib-mcp-rag-server/sdd_framework:/app/sdd_framework:ro
```

### Volume Mounts (Phase 19 - December 2025)
The gateway container mounts two directories for functionality (security-hardened):
- **supported_repos**: Full Global Workflow source code including all submodules (GSI, UFS, etc.)
- **sdd_framework**: SDD workflow definitions for development orchestration

**Security Note**: The `scripts/` directory is NOT mounted - documentation sources config is baked into the container image at build time (`config/documentation_sources.json`) to prevent external LLMs from accessing or modifying tool internals.

### Verified Working (December 17-19, 2025)
- [x] Gateway discovers all 34 tools
- [x] LangFlow connects via SSE transport
- [x] ChromaDB queries work through container
- [x] Neo4j queries work through container
- [x] Bearer token authentication working
- [x] Full source code access via volume mounts
- [x] list_job_scripts reads from container filesystem
- [x] get_ingested_urls_array reads from baked-in JSON config

### MCP Catalog Security Configuration
Location: `~/.docker/mcp/catalogs/eib-local.yaml`

**Selective Volume Mounts** (minimal exposure):
```yaml
volumes:
  # Full GFS/GEFS/SFS codebase with submodules (GSI, UFS, etc.)
  - /path/to/supported_repos/global-workflow:/app/supported_repos/global-workflow:ro
  # EE2 compliance standards document only (not full repo)
  - /path/to/supported_repos/nws-hpc-standards/docs/standards.rst:/app/supported_repos/nws-hpc-standards/docs/standards.rst:ro
  # SDD workflow definitions
  - /path/to/sdd_framework:/app/sdd_framework:ro
```

**What's NOT mounted** (security):
- `scripts/` - Tool internals (baked into image instead)
- Other supported_repos - EVS, n8n, mcp-gateway, rocoto_dryrun, etc.

## MCP Tool Selection Guide (SOC for LLMs)

**Design Principle**: Tool and server names encode their purpose so LLMs can select correctly from names alone.

### Three-Domain Separation

| Domain | System | Server | Purpose |
|--------|--------|--------|---------|
| **Global Workflow** | GFS/GEFS weather forecasting | `global-workflow-core`, `eib-mcp-gateway` | Analyze weather model code |
| **MCP/RAG Infrastructure** | This development platform | `eib-mcp-rag-full`, `eib-mcp-gateway` | Server health, RAG search |
| **SDD Framework** | Development methodology | `eib-sdd-validator` | Validate SDD specs, bootstrap progress |

### Server Selection Matrix

| If the task involves... | Use Server | Why |
|-------------------------|------------|-----|
| GFS/GEFS code on disk + call graphs | `global-workflow-core` | Neo4j graph only, fast, no RAG |
| Weather documentation search | `eib-mcp-gateway` | ChromaDB vectors for semantic search |
| EE2 compliance checking | `eib-mcp-gateway` | Needs EE2 standards in ChromaDB |
| "What does this GFS code do?" | `eib-mcp-gateway` | RAG-powered explanations |
| HPC operational procedures | `eib-mcp-gateway` | Operational guidance in vectors |
| GitHub issues/PRs | `eib-mcp-gateway` | GitHub API integration |
| **SDD framework validation** | `eib-sdd-validator` | Framework integrity, bootstrap status |
| **Development progress tracking** | `eib-sdd-validator` | Milestone completion, phase tracking |

### Tool Naming Convention

```
<domain>_<action>_<object>
```

| Component | Signals | Examples |
|-----------|---------|----------|
| **domain** | What system/standard | `mcp_`, `ee2_`, `sdd_` |
| **action** | What operation | `search_`, `analyze_`, `get_`, `list_`, `validate_` |
| **object** | What target | `_documentation`, `_compliance`, `_structure`, `_integrity` |

### Quick Reference: Tool → Server Mapping

| Tool Name Pattern | Requires | Available In |
|-------------------|----------|--------------|
| `get_workflow_structure`, `get_system_configs` | Filesystem only | All servers |
| `analyze_code_structure`, `find_*`, `trace_*` | Neo4j | `core`, `full`, `gateway` |
| `search_documentation`, `explain_with_context` | ChromaDB | `full`, `gateway` only |
| `analyze_ee2_compliance`, `scan_repository_*` | ChromaDB | `full`, `gateway` only |
| `get_operational_guidance`, `list_job_scripts` | ChromaDB | `full`, `gateway` only |
| `search_issues`, `get_pull_requests` | GitHub API | `full`, `gateway` only |
| `list_sdd_workflows`, `execute_sdd_workflow*` | Filesystem | `core`, `full`, `gateway` |
| **`sdd_validate`, `framework_integrity`** | **Filesystem** | **`eib-sdd-validator` only** |
| **`development_status`, `bootstrap_progress`** | **Filesystem** | **`eib-sdd-validator` only** |

### Decision Tree for Tool Selection

```
User Question
    │
    ├─► "Show me the GFS code structure of X" 
    │       → analyze_code_structure (global-workflow-core)
    │
    ├─► "What does this weather error mean?" / "How do I run GFS?"
    │       → search_documentation (eib-mcp-gateway)
    │
    ├─► "Is this code EE2 compliant?"
    │       → analyze_ee2_compliance (eib-mcp-gateway)
    │
    ├─► "What calls this forecast function?"
    │       → find_callers_callees (global-workflow-core)
    │
    ├─► "How do I run jobs on HERA?"
    │       → get_operational_guidance (eib-mcp-gateway)
    │
    ├─► "What are the open GFS PRs?"
    │       → get_pull_requests (eib-mcp-gateway)
    │
    ├─► "Is the SDD framework healthy?" / "What's our dev progress?"
    │       → sdd_validate, development_status (eib-sdd-validator)
    │
    └─► "What's the bootstrap capability status?"
            → bootstrap_progress (eib-sdd-validator)
```

## MCP Tool Categories

**38 tools across 8 modules** - always prefer MCP tools over shell commands:

| Module | Tools | DB Dependency | Server | Use For |
|--------|-------|---------------|--------|---------|
| WorkflowInfo | `get_workflow_structure`, `get_system_configs`, `describe_component` | None (filesystem) | All | Static queries, HPC configs |
| CodeAnalysis | `analyze_code_structure`, `find_dependencies`, `trace_execution_path`, `find_callers_callees` | Neo4j | `core`, `full`, `gateway` | Call graphs, dependencies |
| SemanticSearch | `search_documentation`, `explain_with_context`, `find_related_files`, `get_knowledge_base_status` | ChromaDB+Neo4j | `full`, `gateway` | RAG-powered search |
| EE2Compliance | `analyze_ee2_compliance`, `scan_repository_compliance`, `generate_compliance_report`, `search_ee2_standards` | ChromaDB | `full`, `gateway` | NCO standards validation |
| Operational | `get_operational_guidance`, `list_job_scripts`, `explain_workflow_component` | ChromaDB | `full`, `gateway` | HPC procedures |
| SDDWorkflow | `list_sdd_workflows`, `get_sdd_workflow`, `execute_sdd_workflow_supervised` | None | `core`, `full`, `gateway` | Development orchestration |
| GitHub | `search_issues`, `get_pull_requests` | GitHub API | `full`, `gateway` | Repository integration |
| **SDDValidator** | `sdd_validate`, `framework_integrity`, `development_status`, `bootstrap_progress` | **None** | **`eib-sdd-validator`** | **SDD framework health** |

## Infrastructure

Running containers (verify with `docker ps`):
- **chromadb** - Port 8080 → v2 API only (`/api/v2/*`)
- **global-workflow-neo4j** - Ports 7474/7687
- **eib-mcp-standalone** - MCP gateway container (when running)

## Testing & Debugging

```bash
# Health check MCP tools
mcp_health_check({ detailed: true })
get_knowledge_base_status({ include_graph: true, include_vector: true })

# View MCP logs
tail -f mcp_server_node/logs/mcp-server.log

# Check tool count
grep "tools registered" mcp_server_node/logs/mcp-server.log
```

## Anti-Patterns to Avoid

- ❌ Emoji in `console.log()` - breaks MCP stdio protocol
- ❌ ChromaDB v1 API (`/api/v1/*`) - deprecated, returns errors
- ❌ Modifying `supported_repos/` - read-only submodules
- ❌ Coding without SDD workflow for new features
- ❌ Duplicating config (violates SPOT principle)
- ❌ Installing packages without Spack/provisioning updates
- ❌ Using pip install without `--user` flag

## Important Notes

### MCP Tool "Disabled by user" Error
When an MCP tool returns "Tool is currently disabled by the user", this typically means **the tool errored** - not that the user actually disabled it. This is a VS Code/Copilot quirk. Retry the tool call or check MCP server logs for the actual error.
