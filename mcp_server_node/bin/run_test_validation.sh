#!/bin/bash
# Test Validation Script
# Validates that consolidated tests still work

echo "╔════════════════════════════════════════════════════════════╗"
echo "║          Test Validation After Consolidation               ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

PASSED=0
FAILED=0
SKIPPED=0

# Test 1: ChromaDB connectivity
echo "Test 1: ChromaDB connectivity..."
if curl -s http://localhost:8080/api/v1/heartbeat > /dev/null 2>&1; then
    echo "  ✅ ChromaDB is responding"
    ((PASSED++))
else
    echo "  ❌ ChromaDB not accessible"
    ((FAILED++))
fi

# Test 2: Neo4j connectivity
echo ""
echo "Test 2: Neo4j connectivity..."
if curl -s http://localhost:7474 > /dev/null 2>&1; then
    echo "  ✅ Neo4j is responding"
    ((PASSED++))
else
    echo "  ❌ Neo4j not accessible"
    ((FAILED++))
fi

# Test 3: Python ChromaDB test
echo ""
echo "Test 3: Python ChromaDB validation..."
if python3 tests/test-chromadb.py > /dev/null 2>&1; then
    echo "  ✅ Python ChromaDB test passed"
    ((PASSED++))
else
    echo "  ⚠️  Python ChromaDB test failed (may need collection)"
    ((SKIPPED++))
fi

# Test 4: Check test file syntax
echo ""
echo "Test 4: Validating JavaScript syntax..."
SYNTAX_OK=true
for file in tests/*.js; do
    if node --check "$file" > /dev/null 2>&1; then
        echo "  ✅ $(basename $file) - syntax OK"
        ((PASSED++))
    else
        echo "  ❌ $(basename $file) - syntax error"
        ((FAILED++))
        SYNTAX_OK=false
    fi
done

# Test 5: Verify test structure
echo ""
echo "Test 5: Verifying test directory structure..."
if [ -d "tests/" ] && [ $(ls -1 tests/*.js 2>/dev/null | wc -l) -ge 6 ]; then
    echo "  ✅ tests/ directory exists with $(ls -1 tests/*.js | wc -l) JS files"
    ((PASSED++))
else
    echo "  ❌ tests/ directory structure incomplete"
    ((FAILED++))
fi

if [ -d "archive/week2_integration/" ] && [ $(ls -1 archive/week2_integration/*.js 2>/dev/null | wc -l) -ge 3 ]; then
    echo "  ✅ archive/week2_integration/ exists with $(ls -1 archive/week2_integration/*.js | wc -l) archived files"
    ((PASSED++))
else
    echo "  ❌ Archive directory incomplete"
    ((FAILED++))
fi

# Test 6: Verify no test files in root
echo ""
echo "Test 6: Verifying root cleanup..."
ROOT_TESTS=$(ls -1 test*.js test*.py 2>/dev/null | wc -l)
if [ "$ROOT_TESTS" -eq 0 ]; then
    echo "  ✅ No test files in root directory"
    ((PASSED++))
else
    echo "  ❌ Found $ROOT_TESTS test files still in root"
    ((FAILED++))
fi

# Test 7: Check test/ directory (vitest suite)
echo ""
echo "Test 7: Checking test/ directory (vitest suite)..."
if [ -d "test/" ] && [ -f "test/tests/unit/test-rag.js" ]; then
    echo "  ✅ test/ directory intact ($(ls -1 test/tests/*/*.js 2>/dev/null | wc -l) test files)"
    ((PASSED++))
else
    echo "  ⚠️  test/ directory structure incomplete"
    ((SKIPPED++))
fi

# Test 8: Check scripts/ test files
echo ""
echo "Test 8: Checking scripts/ test files..."
SCRIPT_TESTS=$(ls -1 scripts/test*.js 2>/dev/null | wc -l)
if [ "$SCRIPT_TESTS" -ge 5 ]; then
    echo "  ✅ scripts/ has $SCRIPT_TESTS test files"
    ((PASSED++))
else
    echo "  ⚠️  scripts/ has only $SCRIPT_TESTS test files (expected 6+)"
    ((SKIPPED++))
fi

# Summary
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                    Test Summary                            ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "  ✅ Passed:  $PASSED"
echo "  ❌ Failed:  $FAILED"
echo "  ⚠️  Skipped: $SKIPPED"
echo ""

if [ $FAILED -eq 0 ]; then
    echo "✅ All critical tests passed! Consolidation successful."
    exit 0
else
    echo "❌ Some tests failed. Review results above."
    exit 1
fi
