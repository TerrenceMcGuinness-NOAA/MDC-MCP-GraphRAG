# MCP RAG Persistent Infrastructure Setup - Progress Log
**Date**: 2025-10-10  
**Status**: Phase 1 & 2 Complete ✅

## Architecture Overview

```
/mcp_rag_eib/ (25GB Persistent Drive)
├── SETUP/                              # Bootstrap and provisioning scripts
│   ├── bootstrap.sh                    # Main bootstrap script (updated)
│   ├── mcp_env.sh                      # Environment configuration
│   ├── provision_mcp_rag_persistent.sh # Full provisioning script
│   └── ...
├── etc/
│   └── chromadb/                       # ChromaDB installation
│       └── venv/                       # Python virtual environment
├── data/
│   └── chromadb/                       # ChromaDB persistent data
├── cache/                              # Shared cache directory
│   ├── transformers/                   # Hugging Face models
│   ├── npm/                            # npm package cache
│   ├── pip/                            # Python package cache
│   └── huggingface/                    # HF_HOME cache
├── mcp_server_node/                    # MCP server infrastructure
│   ├── src/                            # MCP server source code
│   │   ├── core/                       # Base server components
│   │   ├── tools/                      # Tool modules
│   │   ├── ingestion/                  # Document ingestion
│   │   ├── rag/                        # RAG components
│   │   └── UnifiedMCPServer.js         # Main server
│   ├── node_modules/                   # Node.js dependencies (407 packages)
│   ├── database/                       # MCP database storage
│   ├── knowledge-base/                 # RAG knowledge base
│   ├── logs/                           # Application logs
│   └── package*.json                   # Dependency manifests
└── global-workflow_MCP_node.js-RAG/    # Git repository for development
    └── dev/ci/scripts/utils/Copilot/mcp_server_node/ (source of truth)
```

## ✅ Phase 1: ChromaDB Installation (COMPLETE)

### What Was Accomplished
1. **Directory Structure**: Created persistent directories on `/mcp_rag_eib`
2. **Python Environment**: Python 3.11.12 virtual environment
3. **ChromaDB Installation**: Version 0.4.15 with all dependencies
4. **Systemd Service**: `chromadb-persistent.service` running on port 8080
5. **Data Persistence**: Storage configured in `/mcp_rag_eib/data/chromadb`

### Service Details
- **Service Name**: chromadb-persistent.service
- **Status**: ✅ Active and running
- **Port**: 8080
- **API Endpoint**: http://127.0.0.1:8080/api/v1/heartbeat
- **User**: Terry.McGuinness
- **Auto-start**: Enabled

### Testing Results
```bash
curl -s http://127.0.0.1:8080/api/v1/heartbeat
# {"nanosecond heartbeat": 1760111758499688297}

curl -s http://127.0.0.1:8080/api/v1/collections
# [] (empty, ready for data)
```

## ✅ Phase 2: Bootstrap & Environment Setup (COMPLETE)

### Bootstrap Script Updates
**File**: `/mcp_rag_eib/SETUP/bootstrap.sh`

**New Features**:
- Dynamic `$SETUP` environment variable (script location)
- Exported persistent root paths
- All paths now relative to `$SETUP`
- Improved error handling
- Calls `provision_mcp_rag_persistent.sh`

**Environment Variables Exported**:
```bash
SETUP="/mcp_rag_eib/SETUP"
PERSISTENT_ROOT="/mcp_rag_eib"
MCP_ROOT="/mcp_rag_eib/mcp_server_node"
GIT_REPO="/mcp_rag_eib/global-workflow_MCP_node.js-RAG"
```

### Environment Configuration Script
**File**: `/mcp_rag_eib/SETUP/mcp_env.sh`

**Purpose**: Centralized environment setup for all MCP components

**Exports**:
- Core paths (PERSISTENT_ROOT, MCP_ROOT, GIT_REPO)
- ChromaDB configuration (URL, data paths, port)
- MCP infrastructure paths (knowledge base, database, logs)
- Cache directories (transformers, npm, pip, huggingface)
- Node.js configuration (NODE_ENV, NODE_PATH)
- Python module loading

**Usage**:
```bash
source /mcp_rag_eib/SETUP/mcp_env.sh
# Shows status display with service checks
```

### MCP Server Directory Setup
**Location**: `/mcp_rag_eib/mcp_server_node`

**Created Directories**:
- `src/` - MCP server source code (copied from git repo)
- `node_modules/` - 407 packages installed
- `database/` - MCP database storage
- `knowledge-base/` - RAG knowledge base storage
- `logs/` - Application logs
- `bin/` - Executable scripts
- `cache/` - Local cache

**Source Code Copied**:
- `UnifiedMCPServer.js` - Main server entry point
- `core/` - BaseServer components
- `tools/` - WorkflowTools, RAGTools, GitHubTools
- `ingestion/` - Document ingestion system
- `rag/` - EE2VectorStore and RAG components
- `tests/` - Test suites

**Node.js Dependencies**: 407 packages installed
- @modelcontextprotocol/sdk
- chromadb client
- @xenova/transformers
- And 404 more packages

## Key Architectural Decisions

### 1. Separation of Concerns
- **Git Repo**: `/mcp_rag_eib/global-workflow_MCP_node.js-RAG` (development, version control)
- **Running System**: `/mcp_rag_eib/mcp_server_node` (persistent runtime)
- **Configuration**: `/mcp_rag_eib/SETUP` (bootstrap and environment)

### 2. Cache Strategy
Single cache root `/mcp_rag_eib/cache/` for:
- Transformers models (large ML models)
- npm packages (build cache)
- pip packages (Python dependencies)
- Hugging Face datasets/models

**Benefits**:
- Shared across components
- Survives system restarts
- Reduces redundant downloads
- Easy to clean/manage

### 3. Environment Management
Two-tier approach:
1. **bootstrap.sh**: One-time setup, runs provisioning
2. **mcp_env.sh**: Reusable environment, source anytime

### 4. Path Portability
All scripts use `$SETUP` variable, making the system relocatable if needed.

## Testing and Verification

### ChromaDB Service
```bash
sudo systemctl status chromadb-persistent.service
# ● chromadb-persistent.service - ChromaDB Vector Database (Persistent Storage)
#      Active: active (running)
```

### Environment Loading
```bash
source /mcp_rag_eib/SETUP/mcp_env.sh
# Displays full environment status
# ✅ ChromaDB service is running
# ✅ MCP Node.js dependencies installed
```

### Node.js Environment
```bash
cd /mcp_rag_eib/mcp_server_node
node -e "console.log(process.version)"
# v20.19.2
```

## ✅ Phase 2.5: Submodule Ecosystem Clone (COMPLETE)

### Accomplishment
- **50+ repositories** cloned recursively with `-j 4` parallel jobs
- Full V17 coupled modeling system now available locally
- Includes: UFS, GDAS, GSI, JEDI, MOM6, CICE, WW3, and all nested dependencies
- **Total size**: ~3-5 million lines of code across all components
- **Languages**: Fortran, Python, C/C++, Shell, CMake, YAML

### Major Components
- **Global Workflow**: Main orchestration and workflows
- **GDAS**: 20+ submodules (JEDI ecosystem, SOCA, IODA, etc.)
- **UFS Model**: Full coupled system (atmosphere, ocean, ice, wave, land, aerosol)
- **GSI/EnKF**: Data assimilation system
- **Supporting Tools**: Verification, utilities, monitoring

## 🎯 Phase 3: Enhanced RAG Ingestion (IN PROGRESS)

### Context7-Inspired Architecture
**Design Document**: `ENHANCED_INGESTION_ARCHITECTURE.md`

**Primary Use Case**: **Intelligent Error Diagnosis and Resolution**
- Query historical error logs (1+ year training data)
- Search across code, docs, GitHub issues/PRs
- Provide root cause analysis and proven solutions
- Reduce debugging time from hours to minutes

### Enhanced Capabilities
1. **Intelligent Code Chunking** - Semantic-aware, not line-based
2. **Multi-Dimensional Indexing** - 8 specialized ChromaDB collections
3. **GitHub Intelligence** - Issues, PRs, commits with authentication
4. **Relationship Mapping** - Cross-component dependency graphs
5. **Error Pattern Recognition** - Training on year+ of logs

### New Ingestion Scripts (To Create)
- [ ] `EnhancedIngester.js` - Main orchestrator
- [ ] `CodeChunker.js` - Context7-inspired semantic chunking
- [ ] `GitHubIngester.js` - GitHub API with GH_TOKEN auth
- [ ] `ErrorLogIngester.js` - Error analysis training data
- [ ] `RelationshipMapper.js` - Dependency graph builder
- [ ] `SemanticChunker.js` - Smart content splitting
- [ ] `IngestionOrchestrator.js` - Pipeline manager

### ChromaDB Collections Design
```
1. code_knowledge          - Source code with context
2. documentation           - Official docs + examples
3. error_patterns          - Historical error logs
4. solutions_knowledge     - Proven fixes
5. github_intelligence     - Issues/PRs/commits
6. workflow_dependencies   - Component relationships
7. build_system_knowledge  - CMake + build logs
8. test_results            - Test history + regressions
```

## Next Steps - Phase 3: Implementation

### Immediate Tasks
1. **Update bootstrap.sh** - Add GH_TOKEN configuration
2. **Create enhanced ingestion scripts** - All modules above
3. **Configure environment** - Add ingestion-specific variables
4. **Test documentation ingestion** - Start with existing docs
5. **Begin code ingestion** - Python files first (fastest to parse)

### Parallel Track: MCP Server
1. **Copy startup scripts** from git repo to `/mcp_rag_eib/mcp_server_node/bin/`
2. **Create systemd service** for MCP server
3. **Configure VS Code** MCP integration (`.vscode/mcp.json`)
4. **Test MCP server** with ChromaDB connection

### Files to Create/Update
- [ ] `/mcp_rag_eib/mcp_server_node/src/ingestion/` (7 new files)
- [ ] `/mcp_rag_eib/SETUP/bootstrap.sh` (add GH_TOKEN)
- [ ] `/mcp_rag_eib/SETUP/mcp_env.sh` (add ingestion vars)
- [ ] `/etc/systemd/system/mcp-server-persistent.service`
- [ ] `/mcp_rag_eib/mcp_server_node/bin/start-mcp-server.sh`
- [ ] `/mcp_rag_eib/global-workflow_MCP_node.js-RAG/.vscode/mcp.json`

## Storage Usage

```bash
df -h /mcp_rag_eib
# /dev/nvme2n1     25G  XXX   XXG   X% /mcp_rag_eib
```

**Current Usage**:
- ChromaDB venv: ~200MB
- Node.js dependencies: ~150MB
- Source code: <10MB
- **Total**: ~360MB used of 25GB (1.4%)

## Lessons Learned

### ✅ What Worked Well
1. **Direct persistent installation** - No copying between locations
2. **Iterative approach** - Testing ChromaDB first before full provisioning
3. **Clear directory structure** - Logical separation of components
4. **Environment variables** - Dynamic path resolution
5. **Service management** - Systemd for reliable service management

### 📝 Important Notes
1. All paths are on persistent storage - survives VM restarts
2. Git repo is separate from running system - clean development workflow
3. Cache directory shared across components - efficient storage use
4. Bootstrap script is idempotent - can be run multiple times safely
5. Environment script provides status checks - easy troubleshooting

---
**Progress**: Phase 1 & 2 Complete (40% overall)  
**Next**: Phase 3 - MCP Server Service Configuration  
**Updated**: 2025-10-10 16:25 UTC
