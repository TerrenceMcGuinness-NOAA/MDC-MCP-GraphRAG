#!/bin/bash
##########################################################################
# run-unit-tests.sh - Simplified Test Runner for Week 3 Phase 4
#
# Usage:
#   ./run-unit-tests.sh [test-file-pattern]
#
# Examples:
#   ./run-unit-tests.sh                           # Run all tests
#   ./run-unit-tests.sh SemanticSearchTools       # Run specific test file
#   ./run-unit-tests.sh --coverage                # Run with coverage
#
# Uses npx to bypass npm installation issues
##########################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  MCP Server Unit Test Runner (Week 3 Phase 4)              ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if vitest config exists
if [ ! -f "vitest.config.js" ]; then
    echo -e "${YELLOW}⚠️  vitest.config.js not found, using default configuration${NC}"
fi

# Determine test pattern
TEST_PATTERN="${1:-src/__tests__}"
COVERAGE=""

if [ "$1" == "--coverage" ]; then
    COVERAGE="--coverage"
    TEST_PATTERN="src/__tests__"
fi

echo -e "${GREEN}Test Pattern:${NC} ${TEST_PATTERN}"
echo -e "${GREEN}Working Dir:${NC} ${SCRIPT_DIR}"
echo ""

# Run tests with npx (bypasses npm install issues)
echo -e "${BLUE}🧪 Running tests with Vitest...${NC}"
echo ""

if [ -n "${COVERAGE}" ]; then
    npx -y vitest@3.2.4 run --coverage --reporter=verbose
else
    npx -y vitest@3.2.4 run "${TEST_PATTERN}" --reporter=verbose
fi

EXIT_CODE=$?

echo ""
if [ ${EXIT_CODE} -eq 0 ]; then
    echo -e "${GREEN}✅ Tests completed successfully!${NC}"
else
    echo -e "${RED}❌ Tests failed with exit code ${EXIT_CODE}${NC}"
fi

exit ${EXIT_CODE}
