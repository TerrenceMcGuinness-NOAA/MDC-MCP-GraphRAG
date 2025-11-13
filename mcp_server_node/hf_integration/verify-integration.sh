#!/bin/bash

# Integration Status Verification Script
# Ensures all integration components are working before check-in

echo "🔍 Verifying Hugging Face MCP Integration Status"
echo "=============================================="
echo ""

# Change to integration directory
INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${INTEGRATION_DIR}"

echo "📁 Integration Directory: ${INTEGRATION_DIR}"
echo ""

# Function to check file existence
check_file() {
    local file="$1"
    local description="$2"
    
    if [[ -f "${file}" ]]; then
        echo "✅ ${description}: ${file}"
        return 0
    else
        echo "❌ MISSING: ${description}: ${file}"
        return 1
    fi
}

# Function to run test
run_test() {
    local test_name="$1"
    local test_command="$2"
    
    echo ""
    echo "🧪 Testing: ${test_name}"
    echo "Command: ${test_command}"
    echo ""
    
    if eval "${test_command}"; then
        echo ""
        echo "✅ ${test_name}: PASSED"
        return 0
    else
        echo ""
        echo "❌ ${test_name}: FAILED"
        return 1
    fi
}

# Check required files
echo "📋 Checking Required Files..."
echo ""

FAILED_CHECKS=0

# Core files
check_file "package.json" "Package configuration" || ((FAILED_CHECKS++))
check_file "README.md" "Documentation" || ((FAILED_CHECKS++))
check_file "run-connection-status.sh" "Connection Status Runner" || ((FAILED_CHECKS++))

# Integration files
check_file "huggingface-mcp-bridge.js" "MCP Bridge" || ((FAILED_CHECKS++))
check_file "huggingface-rag-utils.js" "RAG Utils" || ((FAILED_CHECKS++))
check_file "mcp-server-enhanced-rag.js" "Enhanced Server" || ((FAILED_CHECKS++))
check_file "setup-huggingface-integration.js" "Setup Script" || ((FAILED_CHECKS++))

# Demo files
check_file "integration-architecture-status.js" "Architecture Status" || ((FAILED_CHECKS++))
check_file "live-integration-status.js" "Live Integration Status" || ((FAILED_CHECKS++))
check_file "test-huggingface-integration.js" "Basic Test" || ((FAILED_CHECKS++))
check_file "test-complete-hf-integration.js" "Complete Test" || ((FAILED_CHECKS++))

# Configuration
check_file "config/huggingface.json" "HF Configuration" || ((FAILED_CHECKS++))

# Documentation
check_file "INTEGRATION_QA_ANSWERS.md" "Q&A Documentation" || ((FAILED_CHECKS++))
check_file "MCP_INTEGRATION_ARCHITECTURE.md" "Architecture Docs" || ((FAILED_CHECKS++))

echo ""
if [[ "${FAILED_CHECKS}" -eq 0 ]]; then
    echo "✅ All required files present"
else
    echo "❌ ${FAILED_CHECKS} files missing"
    exit 1
fi

# Check Node.js
echo ""
echo "🔧 Checking Node.js..."
if command -v node >/dev/null 2>&1; then
    NODE_VERSION=$(node --version)
    echo "✅ Node.js ${NODE_VERSION} available"
else
    echo "❌ Node.js not found"
    exit 1
fi

# Check node_modules
echo ""
echo "📦 Checking Dependencies..."
if [[ -L "node_modules" && -d "node_modules" ]]; then
    echo "✅ Node modules linked successfully"
else
    echo "❌ Node modules not available"
    exit 1
fi

# Run tests
echo ""
echo "🧪 Running Integration Tests..."

FAILED_TESTS=0

# Test architecture demo
run_test "Architecture Status" "node integration-architecture-status.js" || ((FAILED_TESTS++))

# Test live status check
run_test "Live Integration Status" "node live-integration-status.js" || ((FAILED_TESTS++))

# Test basic integration
run_test "Basic Integration Test" "node test-huggingface-integration.js" || ((FAILED_TESTS++))

# Final status
echo ""
echo "📊 VERIFICATION SUMMARY"
echo "======================"
echo ""

if [[ "${FAILED_CHECKS}" -eq 0 && "${FAILED_TESTS}" -eq 0 ]]; then
    echo "🎉 ALL CHECKS PASSED!"
    echo ""
    echo "✅ Demo is ready for check-in"
    echo "✅ All components working correctly"
    echo "✅ Documentation complete"
    echo "✅ Tests passing"
    echo ""
    echo "Next steps:"
    echo "1. Review the demo with: ./run-demo.sh"
    echo "2. Add files to git: git add demo/"
    echo "3. Commit: git commit -m 'Add Hugging Face MCP integration demo'"
    echo ""
    exit 0
else
    echo "❌ VERIFICATION FAILED"
    echo ""
    echo "Failed file checks: ${FAILED_CHECKS}"
    echo "Failed tests: ${FAILED_TESTS}"
    echo ""
    echo "Please resolve issues before check-in"
    exit 1
fi
