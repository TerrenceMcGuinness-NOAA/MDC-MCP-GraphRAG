# AI Coding Agent Instructions for MCP/RAG Development Repository

**Repository Context**: This is the **eib-mcp-rag-server** repository - a dedicated MCP/RAG development environment that provides intelligent AI assistance for the NOAA Global Workflow system. This repository contains MCP servers and tools that analyze, document, and support development of the operational GFS forecasting infrastructure.

## Empirical Accuracy Principle

**CRITICAL**: All responses, specifications, and technical details must be based on **empirical evidence from actual sources**:
- Verify system specifications by checking runtime context and system prompts (e.g., `<budget:token_budget>`)
- Reference official documentation URLs when citing capabilities
- Inspect actual file contents, configurations, and code before making statements
- Use tool outputs and command results as authoritative sources
- When uncertain, explicitly state assumptions and verify with workspace inspection
- **Never guess or assume** - always check the evidence on hand first

This principle ensures accuracy and builds trust in the AI assistance provided throughout the development process.

## Project Mission

This repository provides an intelligent AI assistant system for the **NOAA Global Workflow** - the operational infrastructure running GFS (Global Forecast System), GEFS (Global Ensemble Forecast System), and related atmospheric models. The MCP tools built here enable:

- **Real-time access** to Global Workflow documentation, code structure, and operational procedures
- **Semantic search** across workflow components using vector embeddings (ChromaDB)
- **Graph-based analysis** of code dependencies and relationships (Neo4j)
- **Operational guidance** for HPC deployment across NOAA platforms (Hera, Hercules, Orion, WCOSS2, Gaea)
- **MCP protocol integration** with VS Code, Claude, and other AI coding assistants

**Goal**: Enable AI agents to provide accurate, contextual assistance for global-workflow development, operations, and troubleshooting - supporting the critical infrastructure that produces operational weather forecasts.

**Target Repository**: [ufs-community/global-workflow](https://github.com/ufs-community/global-workflow) - The operational GFS workflow system

## System Architecture

### Runtime Environment (Co-located Architecture)
```
/mcp_rag_eib/
├── eib-mcp-rag-server/                 # THIS REPOSITORY (co-located source + runtime)
│   ├── .github/                        # Copilot/Cursor instructions
│   ├── SETUP/                          # Provisioning and bootstrap scripts
│   │   ├── bootstrap.sh                # Complete system initialization
│   │   ├── provision_mcp_rag_persistent.sh  # Full provisioning
│   │   └── mcp-env.sh                  # Single source of truth for environment
│   ├── mcp_server_node/                # MCP servers (co-located runtime/source)
│   │   ├── src/                        # Server implementation (Week 2 architecture)
│   │   │   ├── UnifiedMCPServer.js     # Main server (v3.0.0)
│   │   │   └── tools/                  # Tool modules
│   │   ├── scripts/                    # MCP ingestion/utility scripts
│   │   ├── test/                       # MCP server tests
│   │   ├── knowledge-base/             # Documentation cache (gitignored)
│   │   ├── chromadb_data/              # Vector DB data (gitignored)
│   │   ├── logs/                       # Runtime logs (gitignored)
│   │   ├── node_modules/               # npm packages (gitignored)
│   │   └── package.json                # Node.js dependencies
│   ├── supported_repos/                # Git submodules (analysis targets)
│   │   ├── global-workflow/            # Submodule: Global Workflow operational code
│   │   │   ├── scripts/                # GFS operational scripts (exglobal_*.py/sh)
│   │   │   ├── jobs/                   # Rocoto job definitions
│   │   │   ├── parm/                   # Configuration files
│   │   │   └── workflow/               # Workflow orchestration
│   │   └── nws-hpc-standards/          # Submodule: EE2 compliance standards (RST format)
│   │       ├── standards/              # EE2 standard documents
│   │       ├── examples/               # Compliance examples
│   │       └── docs/                   # Standards documentation
│   ├── docs/                           # Development documentation
│   └── changelog.md                    # Version history
│
├── data/                               # Persistent data storage
│   ├── chromadb/                       # ChromaDB persistent data
│   └── neo4j/                          # Neo4j graph database
│
├── cache/                              # Build/runtime caches
│   ├── npm/                            # npm cache
│   ├── pip/                            # Python package cache
│   └── transformers/                   # Hugging Face model cache
│
└── spack/                              # Spack package manager
```

### Directory Structure Rules

**CRITICAL: Co-located Architecture with Git Submodules**

1. **`eib-mcp-rag-server/`** = This MCP development repository
   - Source code and runtime data in same tree
   - Runtime data excluded via `.gitignore` (node_modules/, chromadb_data/, logs/)
   - No deployment/sync needed - direct execution from repo
   - Git submodules for analysis target repositories

2. **`eib-mcp-rag-server/mcp_server_node/`** = MCP servers location
   - `src/` - Server source code (in git)
   - `scripts/` - MCP ingestion/utility scripts (in git)
   - `test/` - Test suites (in git)
   - `node_modules/`, `chromadb_data/`, `logs/` - Runtime data (gitignored)

3. **`eib-mcp-rag-server/supported_repos/`** = Git submodules (analysis targets)
   - **`global-workflow/`** - Git submodule tracking TerrenceMcGuinness-NOAA/global-workflow
     - Global Workflow operational code (GFS/GEFS/GDAS)
     - **DO NOT modify** - MCP tools provide read-only analysis
     - `scripts/` contains GFS operational scripts (exglobal_*.py, exgdas_*.sh)
     - Branch: develop
   - **`nws-hpc-standards/`** - Git submodule tracking TerrenceMcGuinness-NOAA/nws-hpc-standards
     - EE2 compliance standards in RST format
     - MCP tools ingest for enhanced EE2 embeddings
     - Branch: develop (mcp_enhanced_embedings branch to be pushed)
   - **Submodule Usage**:
     ```bash
     # Initialize submodules after cloning
     git submodule update --init --recursive
     
     # Update submodules to latest
     git submodule update --remote
     
     # Check submodule status
     git submodule status
     ```

4. **`SETUP/`** = Provisioning and bootstrap
   - `bootstrap.sh` - Complete system initialization (idempotent)
   - `provision_mcp_rag_persistent.sh` - Full infrastructure setup
   - `mcp-env.sh` - Single source of truth for environment variables

### Data Infrastructure

**ChromaDB** (Vector Database)
- **Location**: http://localhost:8080
- **Service**: systemd user service (chromadb.service)
- **Collections**: 
  - Current: `global-workflow-docs`, `global_workflow_docs` (duplicates - needs cleanup)
  - Target: `global-workflow-docs-v2-0-0` (Week 3 re-ingestion)
- **Status**: Operational, needs duplicate cleanup

**Neo4j** (Graph Database)
- **Location**: bolt://localhost:7687
- **Purpose**: Code structure, dependencies, call chains
- **Nodes**: Files, Functions, Classes, Components, Documentation
- **Status**: Running, Up 27+ hours

**MCP Server** (Node.js)
- **Version**: 3.0.0 (Week 2 architecture)
- **Location**: /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
- **Mode**: Full (20 tools: 3 static + 7 semantic + 4 code + 3 operational + 3 system)
- **Status**: Running via VS Code MCP integration
- **Tools Available**: WorkflowInfoTools, SemanticSearchTools, CodeAnalysisTools, OperationalTools
- **GitHub Tools**: Available as separate MCP server (mcp-server-github)

**Development Status**: See `changelog.md` for version history and `docs/development/` for planning documents.

### Python Package Management

**CRITICAL: Use Spack-Managed Python**

All Python packages MUST be installed in the spack-managed environment:

```bash
# REQUIRED: Source spack environment before pip install
source /mcp_rag_eib/mcp_server_node/setup-spack-chromadb.sh

# Then install packages to user directory
pip3 install --user <package_name>
```

**Key Locations:**
- Spack Python: `/mcp_rag_eib/spack/opt/spack/linux-skylake_avx512/.../python-3.11.14/`
- User packages: `~/.local/lib/python3.11/site-packages/`
- Setup script: `/mcp_rag_eib/eib-mcp-rag-server/SETUP/mcp-env.sh`

**DO NOT:**
- Use `python3 -m venv` (virtual environments deprecated)
- Install without sourcing spack environment
- Use system Python or conda

**References:** See `docs/development/SPACK_CHROMADB_QUICK_REFERENCE.md` and `SPACK_MODULE_SETUP_COMPLETE.md` in documentation.

## Development Planning Paradigm

### Documentation Organization

**Planning Documents** (Repository Root `docs/development/`):
- Development plans, architecture docs, and status reports
- `changelog.md` - Version history and changes
- `WEEK_*_PLAN.md` files archived in documentation

**Ingestion Scripts** (MCP Server Scripts):
- Location: `mcp_server_node/scripts/`
- Latest: `ingest_documentation_week3.py` - Week 3 enhanced ingestion
- **Do NOT use** root-level `populate_chromadb.py` (deprecated)

**Collection Naming**:
- Format: `global-workflow-docs-vN-N-N`
- Example: `global-workflow-docs-v4-2-0-unified`
- Version matches ingestion script generation

### MCP Health Check Tools

**Available Health Check Tools** (MCP tools):
- `get_knowledge_base_status` - Vector + graph DB status, collection counts
- `mcp_health_check` - Complete system health (all components)

**Purpose**: Verify system health and development state
- ChromaDB: Collections, document counts, API version
- Neo4j: Graph database connectivity, node/relationship counts
- File system: MCP server status, tool availability
- Version tracking: Current architecture version

**Usage Pattern**:
```javascript
// Check overall system health
mcp_health_check({ detailed: true })

// Check knowledge base specifics
get_knowledge_base_status({ detailed: true, include_graph: true, include_vector: true })
```

## Development Guidelines

### When Working on This Repository

**This is a development/prototyping environment** - Changes here do NOT affect production global-workflow.

### Change Logging
- Update `changelog.md` with semantic versioning
- Include date and description of changes
- Commit frequently with clear messages
- Never change branch (stay on MCP_node.js-RAG_ParallelWorks)

### Code Style
- Follow existing code style in repository
- Use consistent indentation (2 spaces)
- BASH style: `"${variable}"` for variables
- No extra whitespace at line ends
- Use pycodestyle for Python, shellcheck for shell scripts
- **NEVER use emoji or Unicode characters in console.log/error statements**
  - Use plain ASCII prefixes: `[OK]`, `[ERROR]`, `[WARN]`, `[INFO]`, `[INIT]`, `[START]`
  - Reason: MCP stdio protocol fails to parse Unicode characters, causing log warnings
  - Example: `console.log('[OK] Connected')` not `console.log('✅ Connected')`

### Code Quality
- Keep it simple - average developer should understand
- Avoid over-engineering
- Readable code over comments
- Write unit tests for new features
- Ensure modularity and reusability

### Documentation
- Use numpy style docstrings for Python functions/classes
- Document MCP tool usage in planning docs
- Keep WEEK_*_PLAN.md files updated with current phase
- Update changelog.md with version changes
- Reference correct ingestion scripts (week3, not root-level populate)


## MCP Tool Usage Patterns

Always use MCP tools when asked about any generalities regarding global-workflow as those are always intended to test the MCP system under development in this repository.

### Current Status Check
Before using RAG-enhanced tools, check system health:
```javascript
// Returns vector DB and graph DB status
get_knowledge_base_status
```

**Expected Behavior**: 
- Tools return JSON: `{"content":[{"type":"text","text":"..."}]}`
- MCP tools accessible in GitHub Copilot Chat interface
- stdio transport works correctly over SSH (no HTTP/SSE needed)

### Tool Selection Guide

**Quick Static Queries** → Workflow Info Tools (3 tools)
- Fast overview, platform configs, file system analysis
- No database dependencies (<10ms response)

**Documentation Search** → Semantic Search Tools (8 tools)
- Hybrid vector + graph search, EE2 compliance, code patterns
- RAG-enriched contextual explanations
- Repository-wide compliance scanning

**Code Analysis** → Code Analysis Tools (4 tools)
- File/function/class analysis, dependency mapping
- Call chain tracing, relationship analysis
- Graph-based traversal

**Operational Procedures** → Operational Tools (3 tools)
- HPC platform procedures, deep component explanations
- Job script inventory and categorization
- Platform-specific operational guidance

**System Health** → System Health Tools (2 tools)
- Knowledge base status and statistics
- Complete MCP system health checks

See "Available MCP Tools" section below for complete tool list with exact names.

## Testing MCP Tools

### Manual Testing
```bash
# Check MCP server status
ps aux | grep UnifiedMCPServer

# View logs
tail -50 /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/logs/mcp-server.log

# Test ChromaDB connection
curl http://localhost:8080/api/v1/heartbeat

# Test Neo4j connection
curl http://localhost:7474
```

### Expected Tool Responses
All MCP tools should return this format:
```json
{
  "content": [
    {
      "type": "text",
      "text": "Tool response content here..."
    }
  ]
}
```

If you see `unknown content part ({"content":[...]})` - this is a VS Code UI rendering issue. The tool IS working correctly.

## Global Workflow Context (Reference)

**Note**: This section describes the production global-workflow system that our MCP tools provide access to. Changes here in this dev repo do NOT affect production.

### Production System Overview
- **Global Workflow**: NOAA's operational weather forecasting framework
- **UFS Weather Model**: Unified Forecast System (GFS, GEFS, SFS, GCAFS)
- **GSI/GDAS**: Global Data Assimilation System
- **wxflow**: Python workflow execution library
- **Rocoto**: XML-based workflow orchestration

### Production System Structure

**This describes the actual global-workflow repository structure. Our MCP tools provide intelligent access to this system.**

For detailed information about production global-workflow components, job scripts, and workflow orchestration, use the MCP tools:
- `get_workflow_structure` - Complete system architecture
- `list_job_scripts` - Job inventory with categorization
- `explain_workflow_component` - Deep component analysis
- `search_documentation` - Search across all documentation

## Available MCP Tools (Complete List)

**Note**: MCP tools have NO prefix - use the base tool names directly (e.g., `list_job_scripts`, not `mcp_eib-mcp-rag-r_list_job_scripts`).

### Workflow Info Tools (3 tools)
- `get_workflow_structure` - System architecture and component overview
- `get_system_configs` - HPC platform-specific configurations (hera, hercules, orion, wcoss2, gaea)
- `describe_component` - Quick component file system description (static analysis)

### Semantic Search Tools (8 tools)
- `search_documentation` - Hybrid semantic + graph search across workflow documentation and code
- `search_ee2_standards` - Search EE2 compliance standards and documentation
- `find_related_files` - Find files with similar dependencies and import relationships
- `explain_with_context` - Provide comprehensive explanations using hybrid search
- `analyze_ee2_compliance` - Analyze code or documentation for EE2 compliance
- `generate_compliance_report` - Generate comprehensive EE2 compliance report
- `scan_repository_compliance` - Scan entire repository for EE2 compliance issues
- `get_knowledge_base_status` - Get comprehensive knowledge base statistics (vector + graph DB)

### Code Analysis Tools (4 tools)
- `analyze_code_structure` - Analyze code structure, relationships, and dependencies for a specific file
- `find_dependencies` - Find all dependencies (imports) and dependents (importers) for a file or module
- `trace_execution_path` - Trace the execution path from a starting function through call chains
- `find_callers_callees` - Find all functions that call a target function (callers) and functions it calls (callees)

### Operational Tools (3 tools)
- `get_operational_guidance` - Get operational guidance and best practices for HPC operations
- `explain_workflow_component` - Get detailed explanation of a workflow component with graph context
- `list_job_scripts` - List and categorize job scripts in the workflow

### System Health Tools (2 tools)
- `get_knowledge_base_status` - Vector + graph DB status, collection counts (also in Semantic Search Tools)
- `mcp_health_check` - Complete system health check (all components)

## MCP Tool Usage Examples

When using MCP tools, acknowledge their usage to demonstrate intelligent tool selection:

```markdown
**Research Approach:** Using `search_documentation` to find relevant 
examples and `get_operational_guidance` for HPC-specific procedures.
```

**Example Integration:**
```markdown
Let me research this using the MCP tools to ensure comprehensive coverage:

[Tool usage and results]

Based on the MCP analysis above, here's the recommended approach...
```

## MCP Server Location

All MCP tools are implemented in `mcp_server_node/`:
- `src/UnifiedMCPServer.js` - Main server (v3.0.0)
- `src/tools/` - Tool modules (WorkflowInfoTools, SemanticSearchTools, CodeAnalysisTools, OperationalTools, GitHubTools)
- `scripts/` - MCP utility scripts (ingestion, validation, parsing)
- `test/` - Test suites for MCP functionality
- `start-mcp-server-node.sh` - Startup script
- Configuration: `mcp-config.env`, `package.json`

**MCP Script Organization:**
- Ingestion scripts: `scripts/ingest_*.py` (ChromaDB population)
- Validation scripts: `scripts/validate_*.py` (URL/data validation)
- Test scripts: `test/test_*.js` (Node.js) or `scripts/test_*.py` (Python)
- DO NOT put MCP scripts in `global-workflow_forked/scripts/` (that's for GFS operational scripts)

**Note**: If you encounter placeholder responses from RAG-enhanced tools, this indicates the vector database needs initialization or document ingestion. The core workflow tools should always provide functional responses.
