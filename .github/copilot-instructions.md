# AI Coding Agent Instructions for MCP/RAG Development Repository

**Repository Context**: This is the **MCP/RAG Development Repository** for the NOAA Global Workflow system. This is NOT the production global-workflow repository - this is a specialized development environment for building Model Context Protocol (MCP) tools with Retrieval-Augmented Generation (RAG) capabilities.

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

This repository serves as the development platform for creating an intelligent AI assistant system that provides:
- **Real-time access** to NOAA Global Workflow documentation and code
- **Semantic search** across workflow components using vector embeddings
- **Graph-based analysis** of code dependencies and relationships
- **Operational guidance** for HPC deployment and workflow execution
- **MCP protocol integration** with VS Code and other AI coding assistants

**Goal**: Build a comprehensive knowledge base and tool ecosystem that enables AI agents to provide accurate, contextual assistance for global-workflow development and operations.

## System Architecture

### Runtime Environment
```
/mcp_rag_eib/
├── global-workflow_MCP_node.js-RAG/    # This repository (development)
│   ├── dev/ci/scripts/utils/Copilot/mcp_server_node/  # MCP server source code
│   │   ├── src/                        # Server implementation (Week 2 architecture)
│   │   ├── scripts/                    # MCP-specific utility scripts
│   │   ├── test/                       # MCP server tests
│   │   └── package.json                # Node.js dependencies
│   ├── scripts/                        # GLOBAL-WORKFLOW operational scripts (NOT MCP)
│   │   ├── exglobal_*.py               # GFS operational Python scripts
│   │   └── exglobal_*.sh               # GFS operational shell scripts
│   ├── WEEK_*_PLAN.md                  # Development planning docs
│   └── changelog.md                    # Version history
│
├── mcp_server_node/                    # Runtime deployment (25GB persistent)
│   ├── src/                            # Deployed MCP server code
│   │   ├── UnifiedMCPServer.js         # Main server (v3.0.0)
│   │   └── tools/                      # Tool modules
│   ├── scripts/                        # Deployed MCP utility scripts
│   ├── knowledge-base/                 # Local documentation cache
│   ├── database/                       # Neo4j graph database
│   └── logs/                           # Server logs
│
└── SETUP/                              # Provisioning scripts and configs
```

### Directory Structure Rules

**CRITICAL: Distinguish MCP from Global Workflow**

1. **`/scripts/`** = Global Workflow operational scripts (exglobal_*.py, exgdas_*.sh)
   - These run GFS/GDAS forecasts, not MCP tools
   - DO NOT put MCP-related scripts here

2. **`/dev/ci/scripts/utils/Copilot/mcp_server_node/`** = MCP development
   - All MCP server code, tests, and utilities go here
   - MCP ingestion scripts belong in `mcp_server_node/scripts/`

3. **Runtime deployment**: `/mcp_rag_eib/mcp_server_node/`
   - Deployed code from dev location
   - Use `deploy-to-runtime.sh` to sync

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
- **Location**: /mcp_rag_eib/mcp_server_node
- **Mode**: Full (21 tools: 3 static + 7 semantic + 4 code + 3 operational + 4 GitHub)
- **Status**: Running, auto-starts via VS Code

**Development Status**: See `WEEK_*_PLAN.md` and `changelog.md` for current progress and planning details.

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
- Setup script: `/mcp_rag_eib/mcp_server_node/setup-spack-chromadb.sh`

**DO NOT:**
- Use `python3 -m venv` (virtual environments deprecated)
- Install without sourcing spack environment
- Use system Python or conda

**References:** `SPACK_CHROMADB_QUICK_REFERENCE.md`, `SPACK_MODULE_SETUP_COMPLETE.md`

## Development Planning Paradigm

### WEEK Schema Naming Convention

**CRITICAL**: All development work follows the **WEEK_N_** naming schema for spec-driven planning:

**Planning Documents** (Repository Root):
- `WEEK_1_COMPLETE.md` - Week 1 completion report
- `WEEK_1_STATUS_REPORT.md` - Week 1 status summary  
- `WEEK_1_SUMMARY.md` - Week 1 achievements
- `WEEK_2_TOOL_AUDIT.md` - Week 2 tool inventory
- `WEEK_3_PLAN.md` - Week 3 comprehensive plan
- `WEEK_3_QUICK_START.md` - Week 3 quick reference

**Ingestion Scripts** (MCP Server Scripts):
- `ingest_documentation_week3.py` - Week 3 enhanced ingestion script
  - Location: `dev/ci/scripts/utils/Copilot/mcp_server_node/scripts/`
  - **This is the authoritative ingestion script**
  - Do NOT use root-level `populate_chromadb.py` (deprecated)

**Naming Rules**:
1. All planning docs use `WEEK_N_DESCRIPTION.md` format
2. All ingestion scripts use `ingest_*_weekN.py` format
3. Collection names use version format: `global-workflow-docs-vN-N-N`
4. Always check WEEK files before starting work

### MCP Health Check Tool

**Tool Name**: `get_knowledge_base_status` (MCP tool, available when server running)

**Purpose**: Verify system health and development state
- ChromaDB: Collections, document counts, API version
- Neo4j: Graph database connectivity, node counts
- File system: WEEK files, scripts, changelog status
- Version tracking: Current architecture version

**Usage Pattern**:
```javascript
// When resuming work or checking context
get_knowledge_base_status()
// Returns: ChromaDB status, Neo4j status, collection list, versions
```

**Integration with WEEK Schema**:
- Health check tool reads WEEK files to understand current phase
- Validates collection names match WEEK version expectations
- Ensures ingestion scripts are using correct WEEK naming

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

**Current Known Issue (Oct 16, 2025):**
- MCP tools work in Copilot Chat but not in agentic edit interface
- This is a VS Code interface limitation, not a transport issue
- Working solution: Use Copilot Chat panel for MCP tool queries
- Alternative solution being tested: Run VS Code locally with vscode.dev tunnel

### Tool Selection Guide

**Quick Static Queries** → WorkflowInfoTools (3 tools)
- Fast overview, platform configs, file system analysis
- No database dependencies (<10ms response)

**Documentation Search** → SemanticSearchTools (7 tools)
- Hybrid vector + graph search, EE2 compliance, code patterns
- RAG-enriched contextual explanations

**Code Analysis** → CodeAnalysisTools (4 tools)
- File/function/class analysis, dependency mapping
- Call chain tracing, relationship analysis

**Operational Procedures** → OperationalTools (3 tools)
- HPC platform procedures, deep component explanations
- Job script inventory and categorization

**Repository Integration** → GitHubTools (4 tools)
- Cross-repository analysis, issue search, PR tracking

See "Available MCP Tools" section below for complete tool list with exact names.

## Testing MCP Tools

### Manual Testing
```bash
# Check MCP server status
ps aux | grep UnifiedMCPServer

# View logs
tail -50 /mcp_rag_eib/mcp_server_node/logs/mcp-server.log

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

**Note**: MCP tools have NO prefix - use the base tool names directly (e.g., `list_job_scripts`, not `mcp_global-workflow-full_list_job_scripts`).

### Core Workflow Tools (3 tools)
- `get_workflow_structure` - System architecture and component overview
- `get_system_configs` - HPC platform-specific configurations
- `describe_component` - Quick component file system description

### Operational Tools (3 tools)
- `list_job_scripts` - Complete inventory of workflow job scripts
- `explain_workflow_component` - Deep component analysis and explanation
- `get_operational_guidance` - HPC operational procedures and best practices

### Semantic Search Tools (7 tools)
- `search_documentation` - Semantic search across all workflow documentation
- `search_ee2_standards` - EE2 compliance standards search
- `find_similar_code` - Vector-based code pattern matching and similarity search
- `explain_with_context` - Contextual explanations using RAG knowledge base
- `analyze_ee2_compliance` - EE2 compliance analysis
- `generate_compliance_report` - Comprehensive compliance reports
- `get_knowledge_base_status` - System health check (vector + graph DB)

### Code Analysis Tools (4 tools)
- `analyze_code_structure` - File/function/class structural analysis
- `find_dependencies` - Dependency mapping (upstream/downstream/both)
- `trace_execution_path` - Call chain traversal from starting function
- `find_callers_callees` - Function relationship analysis

### GitHub Tools (4 tools)
- `analyze_workflow_dependencies` - Graph-based workflow dependency analysis
- `search_issues` - Search GitHub issues for troubleshooting
- `get_pull_requests` - Pull request information and changes
- `analyze_repository_structure` - Multi-repository structure analysis

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

All MCP tools are implemented in `dev/ci/scripts/utils/Copilot/mcp_server_node/`:
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
- DO NOT put MCP scripts in `/scripts/` (that's for GFS operational scripts)

**Note**: If you encounter placeholder responses from RAG-enhanced tools, this indicates the vector database needs initialization or document ingestion. The core workflow tools should always provide functional responses.
