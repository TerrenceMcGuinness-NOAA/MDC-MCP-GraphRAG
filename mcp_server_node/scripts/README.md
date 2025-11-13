# MCP Server Utility Scripts

**Location**: `dev/ci/scripts/utils/Copilot/mcp_server_node/scripts/`

This directory contains utility scripts for the MCP RAG system. These are NOT operational GFS scripts.

## Script Categories

### Ingestion Scripts (ChromaDB/Neo4j population)
- `ingest_documentation_week3.py` - Enhanced documentation ingestion (Week 3)
- `ingest-code.js` - Code ingestion into Neo4j graph
- `ingest-cmake.js` - CMake build system analysis
- `ingest-from-url-list.js` - Batch URL ingestion
- `ingest-github-metadata.js` - GitHub repository metadata
- `ingest-submodules.js` - Git submodule analysis

### Validation Scripts
- `validate_documentation_urls.py` - Check documentation URL health

### Test Scripts
- `test_mcp_tools.js` - MCP tool functionality tests
- `test-cmake-queries.js` - CMake query testing
- `test-deep-crawl.js` - Documentation crawler testing
- `test-github-queries.js` - GitHub integration tests
- `test-python-code.js` - Python code analysis tests
- `test-shell-code.js` - Shell script analysis tests

### Utility Scripts
- `extract-sitemap-urls.js` - Sitemap parsing
- `parse-python-ast.py` - Python AST parsing
- `demo-graph-queries.js` - Neo4j query examples
- `clear-neo4j-constraints.js` - Database maintenance

## Usage

All scripts should be run from the MCP server directory:
```bash
cd /mcp_rag_eib/global-workflow_MCP_node.js-RAG/dev/ci/scripts/utils/Copilot/mcp_server_node
./scripts/script_name.py  # or .js
```

## DO NOT Confuse With

**`/scripts/`** = Global Workflow operational scripts (exglobal_*.py, exgdas_*.sh)
- Those scripts run GFS/GDAS forecasts
- DO NOT put MCP scripts there!

## Deployment

Scripts are deployed to `/mcp_rag_eib/mcp_server_node/scripts/` via:
```bash
./deploy-to-runtime.sh
```
