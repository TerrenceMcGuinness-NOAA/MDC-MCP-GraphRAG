#!/bin/bash

# Test and Validation Runner Script
# Consolidated script to run all tests and validations from organized directories

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Base directory
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_DIR="${BASE_DIR}/tests"
VALIDATION_DIR="${BASE_DIR}/validation"

echo -e "${BLUE}🔬 MCP Server Test and Validation Runner${NC}"
echo "============================================="

# Function to run a test with error handling and timeout
run_test() {
    local test_name="$1"
    local test_command="$2"
    local test_dir="$3"
    local timeout_duration="240"  # 4 minutes timeout
    
    echo -e "\n${YELLOW}▶ Running: ${test_name}${NC}"
    echo "Command: ${test_command}"
    echo "Directory: ${test_dir}"
    echo "Timeout: ${timeout_duration}s"
    echo "----------------------------------------"
    
    cd "${test_dir}"
    
    # Use timeout command to prevent hanging
    if timeout "${timeout_duration}s" bash -c "${test_command}"; then
        echo -e "${GREEN}✅ PASSED: ${test_name}${NC}"
        return 0
    else
        local exit_code=$?
        if [ $exit_code -eq 124 ]; then
            echo -e "${RED}⏱️  TIMEOUT: ${test_name} (exceeded ${timeout_duration}s)${NC}"
        else
            echo -e "${RED}❌ FAILED: ${test_name}${NC}"
        fi
        return 1
    fi
}

# Function to run validation scripts with timeout
run_validation() {
    local validation_name="$1"
    local validation_command="$2"
    local timeout_duration="60"  # 60 second timeout for validations
    
    echo -e "\n${YELLOW}▶ Running: ${validation_name}${NC}"
    echo "Command: ${validation_command}"
    echo "Directory: ${VALIDATION_DIR}"
    echo "Timeout: ${timeout_duration}s"
    echo "----------------------------------------"
    
    cd "${VALIDATION_DIR}"
    
    # Use timeout command to prevent hanging
    if timeout "${timeout_duration}s" bash -c "${validation_command}"; then
        echo -e "${GREEN}✅ PASSED: ${validation_name}${NC}"
        return 0
    else
        local exit_code=$?
        if [ $exit_code -eq 124 ]; then
            echo -e "${RED}⏱️  TIMEOUT: ${validation_name} (exceeded ${timeout_duration}s)${NC}"
        else
            echo -e "${RED}❌ FAILED: ${validation_name}${NC}"
        fi
        return 1
    fi
}

# Parse command line arguments
case "${1:-all}" in
    "unit")
        echo -e "${BLUE}📊 Running Unit Tests${NC}"
        echo "====================="
        
        cd "${TESTS_DIR}/unit"
        for test_file in test-*.js; do
            if [[ -f "$test_file" ]]; then
                run_test "Unit Test: $test_file" "node $test_file" "${TESTS_DIR}/unit"
            fi
        done
        ;;
        
    "integration")
        echo -e "${BLUE}🔗 Running Integration Tests${NC}"
        echo "============================="
        
        run_test "MCP Protocol Compliance" "node test-mcp-protocol-compliance.js" "${TESTS_DIR}/integration"
        run_test "Copilot Integration" "python3 test-copilot-integration.py" "${TESTS_DIR}/integration"
        ;;
        
    "validation")
        echo -e "${BLUE}✅ Running Validation Scripts${NC}"
        echo "=============================="
        
        run_validation "URL Validation" "node validate-urls.js"
        run_validation "Redundancy Check" "python3 check-redundancies.py"
        run_validation "URL Relevance Check" "python3 check-url-relevance.py"
        ;;
        
    "all")
        echo -e "${BLUE}🚀 Running All Tests and Validations${NC}"
        echo "====================================="
        
        # Run unit tests
        echo -e "\n${BLUE}📊 Unit Tests${NC}"
        cd "${TESTS_DIR}/unit"
        for test_file in test-*.js; do
            if [[ -f "$test_file" ]]; then
                run_test "Unit: $test_file" "node $test_file" "${TESTS_DIR}/unit" || true
            fi
        done
        
        # Run integration tests
        echo -e "\n${BLUE}🔗 Integration Tests${NC}"
        run_test "MCP Protocol Compliance" "node test-mcp-protocol-compliance.js" "${TESTS_DIR}/integration" || true
        run_test "Copilot Integration" "python3 test-copilot-integration.py" "${TESTS_DIR}/integration" || true
        
        # Run validations
        echo -e "\n${BLUE}✅ Validation Scripts${NC}"
        run_validation "URL Validation" "node validate-urls.js" || true
        run_validation "Redundancy Check" "python3 check-redundancies.py" || true
        run_validation "URL Relevance Check" "python3 check-url-relevance.py" || true
        ;;
        
    "help"|"-h"|"--help")
        echo "Usage: $0 [OPTION]"
        echo ""
        echo "Options:"
        echo "  unit         Run unit tests only"
        echo "  integration  Run integration tests only"
        echo "  validation   Run validation scripts only"
        echo "  all          Run everything (default)"
        echo "  help         Show this help message"
        echo ""
        echo "Directory Structure:"
        echo "  tests/unit/         - Unit tests for individual components"
        echo "  tests/integration/  - Integration tests for system interactions"
        echo "  validation/         - Validation and verification scripts"
        echo ""
        echo "Examples:"
        echo "  $0              # Run all tests and validations"
        echo "  $0 unit         # Run only unit tests"
        echo "  $0 validation   # Run only validation scripts"
        ;;
        
    *)
        echo -e "${RED}❌ Unknown option: $1${NC}"
        echo "Use '$0 help' for usage information"
        exit 1
        ;;
esac

echo -e "\n${BLUE}✨ Test run completed${NC}"
