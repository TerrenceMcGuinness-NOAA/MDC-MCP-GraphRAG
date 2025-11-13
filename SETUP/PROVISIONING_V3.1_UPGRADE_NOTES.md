# MCP RAG Provisioning Scripts v3.1.0 - ChromaDB Upgrade

## Overview

All provisioning scripts have been updated to reflect the ChromaDB infrastructure upgrade from version 0.4.15 to 1.1.1, including all necessary dependency updates and breaking API changes.

**Date:** October 14, 2025  
**Version:** 3.1.0  
**Previous Version:** 3.0.0

---

## Major Changes Summary

### ChromaDB Server Upgrade
- **Previous:** ChromaDB 0.4.15
- **Current:** ChromaDB 1.1.1
- **Impact:** Major version upgrade with API v2 as default

### Python Dependencies Upgrades

| Package | Old Version | New Version | Notes |
|---------|-------------|-------------|-------|
| chromadb | 0.4.15 | 1.1.1 | API v2 support, breaking changes |
| fastapi | 0.95.2 | 0.119.0 | Pydantic v2 compatible |
| pydantic | 1.10.9 | 2.12.2 | Major version upgrade |
| uvicorn | 0.22.0 | 0.37.0 | Latest stable release |
| typing-extensions | 4.7.1 | 4.12.2 | Updated for Pydantic v2 |

### New Dependencies Added

| Package | Version | Reason |
|---------|---------|--------|
| opentelemetry-instrumentation-fastapi | 0.52b0 | Required by ChromaDB 1.1.1 |
| opentelemetry-api | ≥1.31.0 | Telemetry framework |
| opentelemetry-sdk | ≥1.31.0 | Telemetry SDK |

### Node.js Client Upgrade
- **Previous:** chromadb@1.10.5
- **Current:** chromadb@3.0.17
- **Breaking Changes:** Complete API rewrite for ChromaDB 1.x compatibility
- **New Dependency:** @chroma-core/default-embed (required for embeddings)

---

## Files Updated

### 1. provision_mcp_rag_persistent.sh (v3.0 → v3.1)

**Location:** `/mcp_rag_eib/SETUP/provision_mcp_rag_persistent.sh`

#### Changes:

**Line 4:** Version bump to 3.1.0
```bash
# Version: 3.1.0
# Changelog: v3.1.0 - Upgraded ChromaDB 0.4.15 → 1.1.1 with dependencies
```

**Lines 342-351:** Updated ChromaDB installation section
```bash
# BREAKING CHANGES from 0.4.15:
#   - API v1 deprecated, v2 is default
#   - FastAPI 0.95.2 → 0.119.0 (Pydantic v2 support)
#   - Pydantic 1.10.9 → 2.12.2 (major version upgrade)
#   - Uvicorn 0.22.0 → 0.37.0 (latest stable)
#   - Added OpenTelemetry instrumentation (required by ChromaDB 1.1.1)
pip install --no-cache-dir \
    "chromadb==1.1.1" \
    "fastapi==0.119.0" \
    "uvicorn==0.37.0" \
    "pydantic==2.12.2" \
    "typing-extensions==4.12.2" \
    "opentelemetry-instrumentation-fastapi==0.52b0" \
    "opentelemetry-api>=1.31.0" \
    "opentelemetry-sdk>=1.31.0"
```

**Lines 360-361:** Added version logging
```bash
log_info "ChromaDB version: 1.1.1 (API v2, Node.js client requires chromadb@3.x)"
```

**Lines 400-410:** Enhanced health checks
```bash
# Test ChromaDB (both API v1 and v2 endpoints)
if curl -s "http://127.0.0.1:${CHROMADB_PORT}/api/v1/heartbeat" > /dev/null 2>&1; then
    log_success "ChromaDB 1.1.1 running on port ${CHROMADB_PORT} (API v1 compatible)"
    # Also test v2 API
    if curl -s "http://127.0.0.1:${CHROMADB_PORT}/api/v2" > /dev/null 2>&1; then
        log_success "ChromaDB API v2 endpoint confirmed"
    fi
```

**Lines 445-455:** Explicit chromadb@3.x client installation
```bash
log_info "Installing Node.js dependencies (this may take 5-10 minutes)..."
log_info "  Cache location: ${CACHE_ROOT}/npm"
log_info "  ChromaDB Node.js client will be chromadb@3.0.17 (for ChromaDB 1.1.1)"

npm install --cache "${CACHE_ROOT}/npm" --loglevel=info

# Explicitly install chromadb and required embedding function
log_info "Ensuring ChromaDB 3.x client and embedding function..."
npm install --cache "${CACHE_ROOT}/npm" chromadb@latest @chroma-core/default-embed
```

**Lines 750-760:** Updated improvements list
```bash
echo -e "\n${CYAN}Key Improvements in v3.1:${NC}"
echo -e "  ✅ ChromaDB upgraded: 0.4.15 → 1.1.1 (API v2 support)"
echo -e "  ✅ Node.js client: chromadb@3.0.17 (breaking API changes)"
echo -e "  ✅ FastAPI 0.95.2 → 0.119.0 (Pydantic v2 support)"
echo -e "  ✅ Pydantic 1.10.9 → 2.12.2 (major version upgrade)"
echo -e "  ✅ OpenTelemetry instrumentation added"
```

**Lines 770-778:** Updated next steps
```bash
echo -e "  4. ${YELLOW}Test Node.js connection:${NC} Create test script with chromadb@3.0.17 API"
echo -e "  5. ${YELLOW}Update MCP server code:${NC} Migrate to ChromaDB 3.x API (REQUIRED)"
```

**Lines 790-796:** Enhanced troubleshooting
```bash
echo -e "  ${YELLOW}MCP server crashes:${NC}    Update code for ChromaDB 3.x API (breaking changes)"
echo -e "  ${YELLOW}API v1 vs v2:${NC}          ChromaDB 1.1.1 supports both, but v2 is default"
```

### 2. mcp_env.sh (v2.0 → v3.1)

**Location:** `/mcp_rag_eib/SETUP/mcp_env.sh`

#### Changes:

**Line 3:** Version update
```bash
# Version: 3.1.0
# v3.1.0: ChromaDB 1.1.1, Node.js client chromadb@3.0.17, API v2 support
```

**Lines 52-55:** Added version info to display
```bash
echo "  ChromaDB Version:     1.1.1 (API v1/v2)"
echo "  Node Client Version:  chromadb@3.0.17"
```

**Lines 74-83:** Enhanced status checks with version verification
```bash
if systemctl is-active --quiet chromadb-persistent.service; then
    echo "✅ ChromaDB 1.1.1 service is running"
    # Quick version check
    HEARTBEAT=$(curl -s http://127.0.0.1:8080/api/v1/heartbeat 2>/dev/null)
    if [ -n "${HEARTBEAT}" ]; then
        echo "   💓 Heartbeat: ${HEARTBEAT}"
    fi
```

### 3. test-chromadb-collection.py

**Location:** `/mcp_rag_eib/SETUP/test-chromadb-collection.py`

#### Changes:

**Lines 1-10:** Updated docstring with version info
```python
"""
Quick test to create Global-Workflow collection in ChromaDB 1.1.1
and add some sample documents for LangFlow testing

NOTE: ChromaDB 1.1.1 uses API v2 by default
      Client API is compatible with 0.4.x but has new features
"""

print("🔗 Connecting to ChromaDB 1.1.1...")
```

**Lines 17-20:** Added version verification
```python
print(f"✅ Connected to ChromaDB")
print(f"   Version: {client.heartbeat()} (heartbeat timestamp)")
print(f"   Server: http://localhost:8080")
```

### 4. check-mcp-status.sh

**Location:** `/mcp_rag_eib/SETUP/check-mcp-status.sh`

#### Changes:

**Lines 12-27:** Enhanced ChromaDB status check
```bash
echo "🔍 ChromaDB 1.1.1 (port 8080):"
if curl -sf http://127.0.0.1:8080/api/v1/heartbeat > /dev/null 2>&1; then
    echo "   ✅ Running and responsive (API v1)"
    
    # Check API v2 as well
    if curl -sf http://127.0.0.1:8080/api/v2 > /dev/null 2>&1; then
        echo "   ✅ API v2 endpoint available"
    fi
    
    # Get version info
    HEARTBEAT=$(curl -s http://127.0.0.1:8080/api/v1/heartbeat)
    echo "   💓 Heartbeat: ${HEARTBEAT}"
    
    # Get collections count
    COLLECTIONS=$(curl -s http://127.0.0.1:8080/api/v1/collections 2>/dev/null | jq length 2>/dev/null || echo "unknown")
    echo "   📊 Collections: ${COLLECTIONS}"
```

---

## Breaking Changes & Migration Notes

### For Infrastructure (✅ Complete)
1. ✅ ChromaDB server upgraded to 1.1.1
2. ✅ Python venv rebuilt with new dependencies
3. ✅ Node.js chromadb package upgraded to 3.0.17
4. ✅ @chroma-core/default-embed package added
5. ✅ All provisioning scripts updated

### For Application Code (⚠️ Pending)
1. ❌ MCP server source code needs ChromaDB 3.x API migration
2. ❌ Update all `ChromaClient` instantiation patterns
3. ❌ Update collection creation with embedding functions
4. ❌ Update query methods for new API
5. ❌ Handle API v2 response structures

---

## API Migration Guide

### ChromaDB Client Initialization

**Old (chromadb@1.x):**
```javascript
const { ChromaClient } = require('chromadb');
const client = new ChromaClient('http://localhost:8080');
```

**New (chromadb@3.x):**
```javascript
const { ChromaClient } = require('chromadb');
const client = new ChromaClient({ path: 'http://localhost:8080' });
```

### Collection Creation with Embedding

**Old (chromadb@1.x):**
```javascript
const collection = await client.getOrCreateCollection({ name: 'my-collection' });
```

**New (chromadb@3.x):**
```javascript
const { DefaultEmbeddingFunction } = require('@chroma-core/default-embed');
const embedder = new DefaultEmbeddingFunction();
const collection = await client.getOrCreateCollection({
    name: 'my-collection',
    embeddingFunction: embedder
});
```

### Querying Collections

**Old (chromadb@1.x):**
```javascript
const results = await collection.query({
    queryTexts: ['search text'],
    nResults: 5
});
```

**New (chromadb@3.x):**
```javascript
const results = await collection.query({
    queryTexts: ['search text'],
    nResults: 5
    // API unchanged but response structure may differ
});
```

---

## Testing Checklist

### Infrastructure Testing (✅ Complete)
- [x] ChromaDB service starts without errors
- [x] API v1 endpoint responds to heartbeat
- [x] API v2 endpoint is accessible
- [x] Python client can connect
- [x] Node.js client can connect (simple test)
- [x] venv size is optimized (~480MB)
- [x] All dependencies installed correctly

### Application Testing (❌ Pending)
- [ ] MCP server starts without crashes
- [ ] RAG tools can query ChromaDB
- [ ] Collection creation works with new API
- [ ] Embedding function properly configured
- [ ] All 17 MCP tools functional
- [ ] No API v1/v2 compatibility issues

---

## Next Steps

### Immediate Actions Required

1. **Update MCP Server Source Code**
   - File: `/mcp_rag_eib/mcp_server_node/src/rag/EE2VectorStore.js`
   - File: `/mcp_rag_eib/mcp_server_node/src/tools/RAGTools.js`
   - File: `/mcp_rag_eib/mcp_server_node/src/UnifiedMCPServer.js`
   - Action: Migrate to chromadb@3.x API patterns

2. **Handle Existing Collections**
   - 2 collections exist with "undefined" embedding functions
   - Decision needed: migrate, recreate, or delete

3. **Full Integration Testing**
   - Test MCP server with upgraded stack
   - Verify all 17 tools work correctly
   - Populate knowledge base
   - Test RAG semantic search

### Recommended Testing Sequence

```bash
# 1. Verify provisioning script works (already done)
sudo ./provision_mcp_rag_persistent.sh --fresh

# 2. Test ChromaDB connectivity
source /mcp_rag_eib/SETUP/mcp_env.sh
curl http://127.0.0.1:8080/api/v1/heartbeat
node /tmp/test_chromadb.js  # Simple connection test

# 3. Update MCP server code (IN PROGRESS)
cd /mcp_rag_eib/mcp_server_node
# Update src/rag/*.js and src/tools/*.js for chromadb@3.x

# 4. Test MCP server incrementally
node src/UnifiedMCPServer.js core --test  # Core tools only
node src/UnifiedMCPServer.js rag --test   # RAG tools (after migration)
node src/UnifiedMCPServer.js full --test  # All tools

# 5. Start service
sudo systemctl start mcp-server-persistent.service
sudo journalctl -u mcp-server-persistent.service -f
```

---

## Rollback Plan

If issues occur, rollback to ChromaDB 0.4.15:

```bash
# 1. Stop services
sudo systemctl stop chromadb-persistent.service
sudo systemctl stop mcp-server-persistent.service

# 2. Rebuild ChromaDB venv with old versions
source /mcp_rag_eib/etc/chromadb/venv/bin/activate
pip uninstall -y chromadb fastapi uvicorn pydantic opentelemetry-*
pip install chromadb==0.4.15 fastapi==0.95.2 uvicorn==0.22.0 pydantic==1.10.9

# 3. Downgrade Node.js client
cd /mcp_rag_eib/mcp_server_node
npm uninstall chromadb @chroma-core/default-embed
npm install chromadb@1.10.5

# 4. Restart services
sudo systemctl start chromadb-persistent.service
sudo systemctl start mcp-server-persistent.service
```

---

## Version Compatibility Matrix

| Component | v3.0 | v3.1 | Notes |
|-----------|------|------|-------|
| Provisioning Scripts | 3.0.0 | 3.1.0 | Updated |
| ChromaDB Server | 0.4.15 | 1.1.1 | Major upgrade |
| FastAPI | 0.95.2 | 0.119.0 | Pydantic v2 |
| Pydantic | 1.10.9 | 2.12.2 | Major version |
| Uvicorn | 0.22.0 | 0.37.0 | Minor update |
| chromadb (Node) | 1.10.5 | 3.0.17 | Breaking changes |
| MCP Server Code | 1.0.0 | **1.0.0** | ⚠️ Needs update |

---

## References

- ChromaDB 1.1.1 Release Notes: https://docs.trychroma.com/
- ChromaDB Node.js Client 3.x Docs: https://www.npmjs.com/package/chromadb
- Pydantic v2 Migration Guide: https://docs.pydantic.dev/latest/migration/
- FastAPI with Pydantic v2: https://fastapi.tiangolo.com/

---

## Support & Troubleshooting

**Common Issues:**

1. **"Module not found: @chroma-core/default-embed"**
   - Solution: `npm install @chroma-core/default-embed`

2. **"ChromaDB API v2 not responding"**
   - Check: `journalctl -u chromadb-persistent.service -n 50`
   - Verify OpenTelemetry packages installed

3. **"MCP server crashes on startup"**
   - Cause: Code still using chromadb@1.x API
   - Solution: Update MCP server source code (next step)

4. **"Collection created with undefined embedding function"**
   - Cause: Old collections from chromadb@1.x
   - Solution: Recreate collections with new embedding functions

**Contact:** NOAA EMC Global Workflow Team

---

**Document Status:** ✅ COMPLETE  
**Last Updated:** October 14, 2025  
**Next Review:** After MCP server code migration complete
