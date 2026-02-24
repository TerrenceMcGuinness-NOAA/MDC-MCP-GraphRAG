# AI Coding Agent Instructions for EIB MCP-RAG Server

## Project Overview

MCP/RAG development platform for NOAA Global Workflow AI assistance. Provides 48 tools for code analysis, EE2 compliance validation, semantic search, and session state tracking across operational weather forecasting infrastructure.

**Architecture**: Node.js MCP Server → ChromaDB (vectors) + Neo4j (graph) → AI Clients (VS Code, Copilot CLI, Claude, n8n)

## Build, Test, and Lint

All commands run from `mcp_server_node/`:

```bash
# Start MCP server
npm start                    # full mode (all tools, requires ChromaDB + Neo4j)
npm run start:core           # core mode (code analysis only, requires Neo4j)
npm run dev                  # watch mode

# Tests (custom runner — NOT vitest/jest)
npm test                     # full test suite
npm run test:verbose         # with detailed output

# Vitest unit tests (if vitest installed)
npx vitest run src/__tests__                              # all unit tests
npx vitest run src/__tests__/CodeAnalysisTools.test.js    # single test file
./run-unit-tests.sh SemanticSearchTools                   # by module name
./run-unit-tests.sh --coverage                            # with coverage

# Validate syntax only (no lint configured)
npm run validate             # node --check on core files

# Infrastructure
docker compose -f docker-compose.devops.yaml up -d    # start ChromaDB + Neo4j
curl http://localhost:8080/api/v2/heartbeat            # verify ChromaDB (MUST use v2)
curl http://localhost:7474                              # verify Neo4j
```

### Docker MCP Gateway

The MCP server can run natively (stdio) or via the **Docker MCP Gateway** (Streamable HTTP on port 18888). The gateway spawns containers from the `eib-mcp-rag:latest` Docker image.

**CRITICAL: The Docker image is a snapshot.** Unlike native mode (which runs live source code), the gateway runs code **baked into the image at build time**. Any changes to files under `mcp_server_node/` require an image rebuild before they take effect in gateway mode.

```bash
# Rebuild after ANY code change
docker build -f SETUP/dockerfiles/Dockerfile.mcp-server -t eib-mcp-rag:latest ./mcp_server_node

# Restart gateway to use new image
pkill -f "docker-mcp gateway"
docker stop $(docker ps -q --filter "label=docker-mcp-name=eib-mcp-rag") 2>/dev/null
docker rm $(docker ps -aq --filter "label=docker-mcp-name=eib-mcp-rag") 2>/dev/null
MCP_GATEWAY_AUTH_TOKEN="eib-mcp-gateway-token-2025" docker mcp gateway run \
  --catalog eib-local.yaml --servers eib-mcp-rag \
  --transport streaming --port 18888 --long-lived &
```

#### What requires an image rebuild

| Changed File/Directory | Baked into Image? | Rebuild? |
|------------------------|-------------------|----------|
| `mcp_server_node/src/` (tools, core, data) | Yes | **Yes** |
| `mcp_server_node/utils/` | Yes | **Yes** |
| `mcp_server_node/config/` | Yes | **Yes** |
| `mcp_server_node/phase2_anti_patterns.json` | Yes | **Yes** |
| `mcp_server_node/package.json` (dependencies) | Yes | **Yes** |
| `sdd_framework/` | No (volume-mounted) | No |
| `supported_repos/` | No (volume-mounted) | No |
| `.vscode/mcp.json` | No (client-side) | No |
| `~/.docker/mcp/catalogs/eib-local.yaml` | No (gateway config) | No |

**Common pitfall**: Adding/modifying tools in `src/tools/` and testing only via native mode. The gateway will still serve the old tools until rebuilt.

## Architecture

### Server Scenarios

`UnifiedMCPServer.js` loads tool modules based on scenario:

| Scenario | Flag | Tools | Databases Required |
|----------|------|-------|--------------------|
| `full` | `npm start` | 48 (all) | ChromaDB + Neo4j |
| `core` | `npm run start:core` | ~20 | Neo4j only |
| `rag` | `npm run start:rag` | ~38 | ChromaDB + Neo4j |
| `github` | `npm run start:github` | ~24 | Neo4j + GitHub API |

### Data Flow

```
Tool Modules (9 files in src/tools/)
       │
       ▼
UnifiedDataAccess (src/data/)
  ├── GraphDatabase.js  → Neo4j (bolt://localhost:7687)
  └── VectorDatabase.js → ChromaDB (http://localhost:8080)
       │
       ▼
BaseServer (src/core/) → MCP SDK → stdio transport → AI client
```

### Tool Modules → Database Dependencies

| Module | Key Tools | Requires |
|--------|-----------|----------|
| WorkflowInfoTools (3) | `get_workflow_structure`, `get_system_configs`, `describe_component` | Filesystem only |
| CodeAnalysisTools (6) | `analyze_code_structure`, `find_dependencies`, `find_callers_callees`, `find_env_dependencies`, `trace_execution_path`, `trace_full_execution_chain` | Neo4j |
| SemanticSearchTools (6) | `search_documentation`, `explain_with_context`, `find_related_files`, `get_knowledge_base_status`, `list_ingested_urls`, `get_ingested_urls_array` | ChromaDB + Neo4j |
| EE2ComplianceTools (5) | `analyze_ee2_compliance`, `scan_repository_compliance`, `search_ee2_standards`, `generate_compliance_report`, `extract_code_for_analysis` | ChromaDB |
| OperationalTools (4) | `get_operational_guidance`, `list_job_scripts`, `explain_workflow_component`, `get_job_details` | ChromaDB |
| GraphRAGTools (9) | `get_code_context`, `search_architecture`, `find_similar_code`, `get_change_impact`, `trace_data_flow`, `mark_as_modified`, `get_session_context`, `checkpoint_state`, `restore_checkpoint` | ChromaDB + Neo4j |
| GitHubTools (4) | `search_issues`, `get_pull_requests`, `analyze_repository_structure`, `analyze_workflow_dependencies` | GitHub API |
| SDDWorkflowTools (9) | `list_sdd_workflows`, `get_sdd_workflow`, `start_sdd_session`, `record_sdd_step`, `get_sdd_session`, `complete_sdd_session`, `get_sdd_execution_history`, `validate_sdd_compliance`, `get_sdd_framework_status` | Filesystem |

### SDD Methodology (REQUIRED for new features)

**SDD = Spec-Driven Development**: "If it's not in the SDD, it doesn't get coded."

1. **Plan** → Create spec in `sdd_framework/workflows/phaseX_feature_name.md`
2. **Execute** → Start a session (`start_sdd_session`), record steps as you work (`record_sdd_step`), complete when done (`complete_sdd_session`)

Session model: `start_sdd_session` → `record_sdd_step` (repeat) → `complete_sdd_session`. State persists in `sdd_framework/execution_state/`.

Phase naming: `phase<N><letter>_<descriptor>.md` (e.g., `phase24e_hierarchical_communities.md`). Currently 31+ phases with sub-phases.

See `sdd_framework/methodology/spec_driven_design_core.md` for the full protocol.

## Key Conventions

### Code Style
- **Console output**: ASCII prefixes only (`[OK]`, `[ERROR]`, `[WARN]`) — NO emoji in `console.log()` (breaks MCP stdio protocol)
- **Indentation**: 2 spaces (JS and Bash)
- **Bash variables**: Always quoted `"${variable}"`
- **Python docstrings**: numpy style
- **ES Modules**: All `.js` files use `import`/`export` (package `"type": "module"`)

### SPOT (Single Point of Truth)
Each config has exactly one source:
- Documentation URLs → `mcp_server_node/scripts/documentation_sources_config.py`
- Environment config → `SETUP/mcp-env.sh`
- MCP server config → `.vscode/mcp.json`
- **Changelog** → `CHANGELOG.md` (root) — update for ALL version changes

### Changelog Practice
**Always update `CHANGELOG.md`** when modifying tools, infrastructure, or completing SDD phases. Format: semantic versioning with dated headers and commit refs.

### Software Stack
Dependencies go through the **Spack module system**, not arbitrary `pip install`:
```bash
module load gcc/11.5.0
module load python/3.11 py-pip py-neo4j py-pydantic py-httpx
python3 -m pip install --user chromadb sentence-transformers  # only if not in Spack
```
Never `pip install` without `--user`. Document any new dependency in `SETUP/mcp-env.sh`.

### Anti-Patterns
- ChromaDB v1 API (`/api/v1/*`) — deprecated, use v2
- Modifying `supported_repos/` — read-only git submodules
- Duplicating configuration across files (violates SPOT)

## Domain Glossary

| Term | Meaning |
|------|---------|
| **EE2** | EMC Environment 2.0 — NCO production coding standards |
| **GFS/GEFS** | Global Forecast System / Ensemble version |
| **HPC** | Hera, WCOSS2, Orion, Hercules, Gaea compute platforms |
| **GGSR** | Graph-Guided Semantic Retrieval (hybrid Neo4j+ChromaDB queries) |
| **SDD/ISD/USD** | Spec-Driven Development / Interactive Supervised / Unsupervised Development |
