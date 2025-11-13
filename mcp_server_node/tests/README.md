# Test Suite - Quick Validation Tests

**Purpose**: Fast validation tests for MCP server components  
**Location**: `/mcp_rag_eib/global-workflow_MCP_node.js-RAG/dev/ci/scripts/utils/Copilot/mcp_server_node/tests/`  
**Last Updated**: November 4, 2025

---

## Test Files

### Database Connectivity Tests

**`test-chromadb.js`** (7.7K)
- Tests ChromaDB HTTP API v3.x
- Validates collections, queries, embeddings
- Checks collection metadata and document counts
- **Run**: `node tests/test-chromadb.js`

**`test-chromadb.py`** (2.8K)
- Python-based ChromaDB validation
- Used by ingestion scripts
- Validates Python client compatibility
- **Run**: `python3 tests/test-chromadb.py`

**`test-neo4j.js`** (4.2K)
- Neo4j graph database connectivity
- Tests Cypher queries
- Validates node/relationship counts
- **Run**: `node tests/test-neo4j.js`

### System Integration Tests

**`test-data-access.js`** (2.4K)
- UnifiedDataAccess layer testing
- Validates hybrid vector + graph queries
- Tests cross-database operations
- **Run**: `node tests/test-data-access.js`

**`test-rag-quick.js`** (5.4K)
- Quick RAG system validation
- End-to-end search testing
- Document retrieval verification
- **Run**: `node tests/test-rag-quick.js`

### Component Tests

**`test-github-integration.js`** (4.6K)
- GitHub MCP tools testing
- Repository analysis validation
- Issue/PR search tests
- **Run**: `node tests/test-github-integration.js`

**`test-ee2-compliance.js`** (6.5K)
- EE2 standards vector search
- Compliance checking tools
- Standards document validation
- **Run**: `node tests/test-ee2-compliance.js`

**`test-optimization.js`** (8.0K)
- Performance optimization tests
- Query timing validation
- Memory usage checks
- **Run**: `node tests/test-optimization.js`

---

## Quick Start

### Run All Tests
```bash
cd /mcp_rag_eib/global-workflow_MCP_node.js-RAG/dev/ci/scripts/utils/Copilot/mcp_server_node
./run_test_validation.sh
```

### Run Individual Test
```bash
# JavaScript test
node tests/test-chromadb.js

# Python test
python3 tests/test-chromadb.py
```

### Prerequisites
- ChromaDB running on port 8080
- Neo4j running on ports 7474/7687
- MCP server v3.0.0 installed
- Node.js 18+ and Python 3.9+

---

## Test Categories

### 1. Quick Validation (this directory)
**Purpose**: Fast smoke tests after server restart  
**When**: Before demos, after changes  
**Time**: < 1 minute total

### 2. Unit Tests (`../test/tests/unit/`)
**Purpose**: Test individual modules  
**When**: During development  
**Framework**: vitest  
**Command**: `npm run test:unit`

### 3. Integration Tests (`../test/tests/integration/`)
**Purpose**: Test component interactions  
**When**: Before commits  
**Framework**: vitest  
**Command**: `npm run test:integration`

### 4. Parser Tests (`../scripts/test-*.js`)
**Purpose**: Validate code parsers  
**When**: Modifying ingestion  
**Command**: `node scripts/test-python-code.js`

---

## Test Results

**Last Run**: November 4, 2025  
**Status**: ✅ All 15 tests passed

```
✅ ChromaDB connectivity
✅ Neo4j connectivity
✅ Python ChromaDB validation
✅ JavaScript syntax validation (7 files)
✅ Test directory structure
✅ Archive structure
✅ Root cleanup
✅ Vitest suite intact
✅ Scripts tests intact
```

---

## Troubleshooting

### ChromaDB Not Responding
```bash
# Check if running
curl http://localhost:8080/api/v1/heartbeat

# Start if needed
cd /mcp_rag_eib/mcp_server_node
./start-chromadb-server.sh
```

### Neo4j Not Responding
```bash
# Check if running
curl http://localhost:7474

# Check Docker status
docker ps | grep neo4j
```

### Test File Errors
```bash
# Validate syntax
node --check tests/test-chromadb.js

# Check dependencies
cd /mcp_rag_eib/mcp_server_node
npm list chromadb neo4j-driver
```

---

## Adding New Tests

### Quick Validation Test Template
```javascript
#!/usr/bin/env node
/**
 * Test: <Description>
 * Purpose: <What this validates>
 */

async function testMyFeature() {
  console.log('Testing my feature...');
  
  try {
    // Your test logic here
    console.log('✅ Test passed');
    return true;
  } catch (error) {
    console.error('❌ Test failed:', error.message);
    return false;
  }
}

testMyFeature().then(success => {
  process.exit(success ? 0 : 1);
});
```

### Test Naming Convention
- `test-<component>.js` - Component-specific test
- `test-<feature>-<aspect>.js` - Feature aspect test
- Executable: `chmod +x tests/test-*.js`
- Shebang: `#!/usr/bin/env node`

---

## Related Documentation

- **Test Analysis**: `../TEST_CONSOLIDATION_ANALYSIS.md`
- **Testing Guide**: `../TESTING_GUIDE.md` (if exists)
- **Quick Reference**: `../QUICK_REFERENCE.md`
- **Architecture**: `../README.md`

---

**Maintained by**: MCP Development Team  
**Questions**: See project documentation or run `./run_test_validation.sh`
