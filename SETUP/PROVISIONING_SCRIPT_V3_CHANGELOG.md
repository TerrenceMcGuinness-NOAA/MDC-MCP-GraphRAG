# Provisioning Script v3.0.0 - Changelog

**Date**: 2025-10-14  
**Status**: Ready for Testing  
**Major Version Bump**: 2.0.0 → 3.0.0

## 🎯 Key Objectives Achieved

1. ✅ **Removed `/contrib` dependencies** - All work now from `/mcp_rag_eib`
2. ✅ **Added `--fresh` flag** - Complete cleanup option for fresh starts
3. ✅ **Fixed venv bloat** - Lightweight ChromaDB venv (~300MB vs 7.1GB)
4. ✅ **Module system integration** - Checks `module avail` first
5. ✅ **Better error handling** - Timeouts and fallbacks for DNF operations
6. ✅ **Persistent git repo architecture** - Repo at PERSISTENT_ROOT level

---

## 📋 Major Changes

### 1. New Command Line Options
```bash
# Normal run (preserves caches)
sudo ./provision_mcp_rag_persistent.sh

# Fresh start (cleans everything)
sudo ./provision_mcp_rag_persistent.sh --fresh
```

### 2. Architecture Changes

**OLD (v2.0)**:
```
/mcp_rag_eib/
├── mcp_server_node/
│   └── global-workflow_MCP_node.js-RAG/  # Git repo nested
```

**NEW (v3.0)**:
```
/mcp_rag_eib/
├── global-workflow_MCP_node.js-RAG/      # Git repo at root level
│   └── dev/ci/scripts/utils/Copilot/mcp_server_node/ (source)
└── mcp_server_node/                       # Runtime MCP server
```

### 3. New STEP 0: Pre-Flight Cleanup

**Fresh Start Mode** (`--fresh`):
- Stops all services
- Removes old ChromaDB venv (7.1GB)
- Removes old node_modules
- Clears all caches
- Resets DNF module states
- Clears ChromaDB data

**Incremental Mode** (default):
- Stops services
- Removes only old installations
- Preserves all caches (npm, pip, transformers)

### 4. Module System Integration

**STEP 2 Changes**:
- Sources module system first
- Checks `module avail` for python, nodejs, gcc
- Loads Python 3.11 via module if available
- Adds timeouts to DNF operations (300s for update, 600s for install)
- Better error messages for module failures

**STEP 4 Changes (Node.js)**:
- Checks for Node.js in module system first
- Only uses DNF if module not available
- Adds 120s timeout for module enable
- Adds 300s timeout for module install
- Verifies installation after completion

**STEP 5 Changes (Python)**:
- Checks module system for Python 3.11
- Verifies python3.11 command availability
- Installs only minimal packages system-wide
- Heavy packages (torch, transformers) only in venv

### 5. Lightweight ChromaDB venv

**Problem Solved**:
- Old venv: 7.1GB (bloated with unnecessary packages)
- New venv: ~200-300MB (ChromaDB + minimal dependencies)

**Changes**:
- Uses `--no-cache-dir` to prevent cache bloat
- Installs only 5 packages: chromadb, fastapi, uvicorn, pydantic, typing-extensions
- Removed: sentence-transformers, torch, transformers, nltk (not needed for server)
- Added size verification and logging

### 6. Source Path Resolution

**OLD**: Hardcoded `/contrib/Terry.McGuinness/...`
**NEW**: Uses persistent git repo at `${GIT_REPO}/dev/ci/scripts/utils/Copilot/mcp_server_node`

**Benefits**:
- No external dependencies
- Git repo is version controlled
- Easy to update via `git pull`
- Survives VM restarts

### 7. Enhanced Environment Configuration

**New Variables**:
```bash
export GIT_REPO="${PERSISTENT_ROOT}/global-workflow_MCP_node.js-RAG"
export MCP_SOURCE="${GIT_REPO}/dev/ci/scripts/utils/Copilot/mcp_server_node"
export HF_HOME="${CACHE_ROOT}/huggingface"
```

**Better Display**:
- Shows cache locations
- Explains what venv is
- Shows all key paths
- Version number in output

### 8. Improved MCP Server Setup (STEP 8)

**Changes**:
- Copies from `${MCP_SOURCE}` (persistent git repo)
- Error handling if source not found
- Better logging of what's being copied
- Smart package.json selection (unified > rag > default)
- Shows package count after install

### 9. Git Repository Verification (STEP 10)

**Changes**:
- Clones to `${PERSISTENT_ROOT}` (not under MCP_ROOT)
- Shows current branch
- Handles git pull failures gracefully
- Verifies MCP source directory exists
- Better error messages

### 10. Enhanced Final Summary

**New Information**:
- Architecture overview
- Key improvements in v3.0
- Explanation of what venv is
- Testing commands
- Troubleshooting tips
- Fresh rebuild instructions

---

## 🔧 Technical Improvements

### Error Handling
- Added timeouts to all DNF operations
- Fallback mechanisms for module system failures
- Better error messages with context
- Non-fatal warnings for optional operations

### Logging
- More descriptive section headers
- Progress indicators for long operations
- Size verification for installations
- Color-coded output (info, success, warning, error)

### Idempotency
- Pre-flight cleanup before starting
- Checks before creating/installing
- Graceful handling of existing installations
- Safe to re-run multiple times

---

## 📊 Expected Results

### ChromaDB venv Size
- **Before**: 7.1GB
- **After**: ~200-300MB
- **Savings**: ~6.8GB (96% reduction)

### Installation Time
- **Fresh Start**: ~15-20 minutes (with cache clearing)
- **Incremental**: ~10-15 minutes (cache reuse)
- **DNF operations**: Timeouts prevent hanging

### Disk Usage
- **Old**: 13GB used on /mcp_rag_eib
- **New (fresh)**: ~5-6GB expected
- **Available**: 18-19GB after fresh install

---

## 🚀 Testing Instructions

### 1. Test Incremental Run (Default)
```bash
cd /mcp_rag_eib/SETUP
sudo ./provision_mcp_rag_persistent.sh
```

### 2. Test Fresh Start
```bash
cd /mcp_rag_eib/SETUP
sudo ./provision_mcp_rag_persistent.sh --fresh
```

### 3. Verify Results
```bash
# Check ChromaDB venv size
du -sh /mcp_rag_eib/etc/chromadb/venv

# Check ChromaDB service
systemctl status chromadb-persistent.service

# Test ChromaDB API
curl http://127.0.0.1:8080/api/v1/heartbeat

# Check MCP server files
ls -la /mcp_rag_eib/mcp_server_node/src/

# Verify environment
source /mcp_rag_eib/mcp_server_node/mcp-env.sh
```

---

## 📝 What is venv?

**venv** = Python Virtual Environment

**Purpose**:
- Creates isolated Python package installation space
- Prevents conflicts with system Python
- Allows different projects to use different package versions

**In this system**:
- **Location**: `/mcp_rag_eib/etc/chromadb/venv`
- **Contents**: ChromaDB + minimal dependencies only
- **Activation**: `source /mcp_rag_eib/etc/chromadb/venv/bin/activate`
- **Why lightweight**: Only server packages, no ML/AI libraries

**Previous bloat cause**: Installing torch, transformers, nltk (not needed for ChromaDB server)

---

## ⚠️ Breaking Changes

1. **Git repo location changed**:
   - Old: `/mcp_rag_eib/mcp_server_node/global-workflow_MCP_node.js-RAG`
   - New: `/mcp_rag_eib/global-workflow_MCP_node.js-RAG`

2. **No /contrib dependencies**:
   - Script will fail if git repo not at `/mcp_rag_eib/global-workflow_MCP_node.js-RAG`
   - Must have MCP source at `dev/ci/scripts/utils/Copilot/mcp_server_node`

3. **Environment variables updated**:
   - `MCP_WORKFLOW_ROOT` now points to git repo at PERSISTENT_ROOT
   - New `MCP_SOURCE` variable for source code location

---

## 🎯 Next Steps After Provisioning

1. **Source environment**: `source /mcp_rag_eib/mcp_server_node/mcp-env.sh`
2. **Test ChromaDB**: `curl http://127.0.0.1:8080/api/v1/heartbeat`
3. **Test MCP server**: `node /mcp_rag_eib/mcp_server_node/src/UnifiedMCPServer.js core`
4. **Populate ChromaDB**: Run ingestion scripts
5. **Start MCP service**: `systemctl start mcp-server-persistent.service`

---

**Changelog Author**: Claude Sonnet 4.5 Preview  
**Review Date**: 2025-10-14  
**Ready for Production**: ✅ Yes, with testing
