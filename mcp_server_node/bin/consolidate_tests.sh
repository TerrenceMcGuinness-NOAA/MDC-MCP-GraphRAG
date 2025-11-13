#!/bin/bash
# Test Consolidation Script
# Run from: /mcp_rag_eib/global-workflow_MCP_node.js-RAG/dev/ci/scripts/utils/Copilot/mcp_server_node

set -e

echo "Starting test consolidation..."

# Phase 1: Archive
echo ""
echo "Phase 1: Archiving outdated tests..."
mkdir -p archive/week2_integration
[ -f test-enhanced-rag-system.js ] && mv test-enhanced-rag-system.js archive/week2_integration/ && echo "  ✓ Archived test-enhanced-rag-system.js"
[ -f test-phase3-integration.js ] && mv test-phase3-integration.js archive/week2_integration/ && echo "  ✓ Archived test-phase3-integration.js"

# Phase 2: Remove
echo ""
echo "Phase 2: Removing deprecated tests..."
[ -f test-prebuilt-onnx.js ] && rm -f test-prebuilt-onnx.js && echo "  ✓ Removed test-prebuilt-onnx.js"
[ -f test_search_detailed.js ] && rm -f test_search_detailed.js && echo "  ✓ Removed test_search_detailed.js"
[ -f test_mcp_tool.js ] && rm -f test_mcp_tool.js && echo "  ✓ Removed test_mcp_tool.js"

# Phase 3: Reorganize
echo ""
echo "Phase 3: Creating tests/ directory..."
mkdir -p tests/

# Move and rename
[ -f test-chromadb-3x.js ] && mv test-chromadb-3x.js tests/test-chromadb.js && echo "  ✓ Moved test-chromadb-3x.js → tests/test-chromadb.js"
[ -f test_chromadb.py ] && mv test_chromadb.py tests/test-chromadb.py && echo "  ✓ Moved test_chromadb.py → tests/"
[ -f test-neo4j-connection.js ] && mv test-neo4j-connection.js tests/test-neo4j.js && echo "  ✓ Moved test-neo4j-connection.js → tests/test-neo4j.js"
[ -f test-data-access.js ] && mv test-data-access.js tests/ && echo "  ✓ Moved test-data-access.js → tests/"
[ -f test-github-integration.js ] && mv test-github-integration.js tests/ && echo "  ✓ Moved test-github-integration.js → tests/"
[ -f test-ee2-vector-store.js ] && mv test-ee2-vector-store.js tests/test-ee2-compliance.js && echo "  ✓ Moved test-ee2-vector-store.js → tests/test-ee2-compliance.js"
[ -f test-optimization.js ] && mv test-optimization.js tests/ && echo "  ✓ Moved test-optimization.js → tests/"

# Phase 4: Archive remaining RAG tests
echo ""
echo "Phase 4: Consolidating RAG tests..."
[ -f test_rag_connection.js ] && mv test_rag_connection.js archive/week2_integration/ && echo "  ✓ Archived test_rag_connection.js"
[ -f test-rag-quick.js ] && mv test-rag-quick.js tests/ && echo "  ✓ Moved test-rag-quick.js → tests/"
[ -f test-ragtools-chromadb.js ] && mv test-ragtools-chromadb.js archive/week2_integration/ && echo "  ✓ Archived test-ragtools-chromadb.js"

echo ""
echo "✅ Consolidation complete!"
echo ""
echo "Summary:"
echo "  - Archived: 5 files → archive/week2_integration/"
echo "  - Removed: 3 files (deprecated)"
echo "  - Organized: 8 files → tests/"
echo ""
echo "Next: Run tests to validate"
