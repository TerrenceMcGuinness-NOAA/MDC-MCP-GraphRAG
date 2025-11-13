#!/bin/bash

# Enhanced RAG System Setup Script
#
# This script sets up and validates the Enhanced RAG System with external
# documentation ingestion capabilities.
#
# Usage: ./setup-enhanced-rag.sh [option]
# Options:
#   --quick     Quick setup with validation only
#   --full      Full setup with complete ingestion
#   --test      Run tests only
#   --help      Show help

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_MODE="${1:-quick}"

print_header() {
    echo -e "${BLUE}🚀 Enhanced RAG System Setup${NC}"
    echo "═════════════════════════════════════"
    echo "Mode: ${SETUP_MODE}"
    echo "Directory: ${SCRIPT_DIR}"
    echo ""
}

print_step() {
    echo -e "${BLUE}$1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

show_help() {
    cat << EOF
Enhanced RAG System Setup Script

USAGE:
    ./setup-enhanced-rag.sh [option]

OPTIONS:
    --quick     Quick setup with validation only (~5 minutes)
    --full      Full setup with complete documentation ingestion (~30 minutes)
    --test      Run comprehensive test suite only
    --help      Show this help message

EXAMPLES:
    ./setup-enhanced-rag.sh --quick
    ./setup-enhanced-rag.sh --full
    ./setup-enhanced-rag.sh --test

DESCRIPTION:
    This script sets up the Enhanced RAG System which provides access to
    60+ external documentation sources including UFS, Rocoto, GSI, HPC
    systems, and compliance standards.

    The system transforms the RAG from local-only to comprehensive multi-source
    knowledge platform supporting the entire NOAA Global Workflow ecosystem.
EOF
}

check_dependencies() {
    print_step "🔍 Checking dependencies..."

    # Check Node.js
    if ! command -v node &> /dev/null; then
        print_error "Node.js is not installed. Please install Node.js 18+ first."
        exit 1
    fi

    local node_version=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
    if [ "$node_version" -lt 18 ]; then
        print_error "Node.js version 18+ required. Current: $(node --version)"
        exit 1
    fi

    # Check npm
    if ! command -v npm &> /dev/null; then
        print_error "npm is not installed."
        exit 1
    fi

    # Check if we're in the right directory
    if [ ! -f "${SCRIPT_DIR}/package.json" ]; then
        print_error "package.json not found. Make sure you're in the MCP server directory."
        exit 1
    fi

    # Check if documentation-references.json exists
    if [ ! -f "${SCRIPT_DIR}/test/documentation-references.json" ]; then
        print_error "documentation-references.json not found in test directory."
        exit 1
    fi

    print_success "Dependencies check passed"
}

install_packages() {
    print_step "📦 Installing npm packages..."

    cd "${SCRIPT_DIR}"

    if npm install; then
        print_success "npm packages installed"
    else
        print_error "npm install failed"
        exit 1
    fi
}

run_quick_setup() {
    print_step "⚡ Running quick setup and validation..."

    cd "${SCRIPT_DIR}"

    # Validate URLs without ingesting
    print_step "🔍 Validating external documentation URLs..."
    if node run-documentation-ingestion.js --validate; then
        print_success "URL validation completed"
    else
        print_warning "Some URLs may be inaccessible (this is normal)"
    fi

    # Run quick tests
    print_step "🧪 Running quick functionality tests..."
    if node test-enhanced-rag-system.js --quick; then
        print_success "Quick tests passed"
    else
        print_error "Quick tests failed"
        exit 1
    fi
}

run_full_setup() {
    print_step "🌍 Running full setup with documentation ingestion..."

    cd "${SCRIPT_DIR}"

    # First run validation
    print_step "🔍 Validating external documentation URLs..."
    node run-documentation-ingestion.js --validate || print_warning "Some URLs may be inaccessible"

    # Run full ingestion
    print_step "📚 Ingesting all external documentation sources..."
    print_warning "This will take 15-30 minutes and fetch content from 60+ sources"
    read -p "Continue with full ingestion? (y/N): " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if node run-documentation-ingestion.js; then
            print_success "Documentation ingestion completed"
        else
            print_error "Documentation ingestion failed"
            exit 1
        fi
    else
        print_warning "Full ingestion skipped"
        return 0
    fi

    # Run comprehensive tests
    print_step "🧪 Running comprehensive test suite..."
    if node test-enhanced-rag-system.js --full; then
        print_success "Full test suite passed"
    else
        print_error "Some tests failed - check test report"
        exit 1
    fi
}

run_tests_only() {
    print_step "🧪 Running comprehensive test suite..."

    cd "${SCRIPT_DIR}"

    if node test-enhanced-rag-system.js --full; then
        print_success "Test suite completed"
    else
        print_error "Tests failed"
        exit 1
    fi
}

show_next_steps() {
    print_step "💡 Next Steps:"
    echo ""
    echo "1. 🎯 Test the Enhanced RAG System:"
    echo "   node test-enhanced-rag-system.js --quick"
    echo ""
    echo "2. 📚 Run full documentation ingestion (if not done):"
    echo "   node run-documentation-ingestion.js"
    echo ""
    echo "3. 🚀 Update your UnifiedMCPServer to use EnhancedRAGTools:"
    echo "   - Replace RAGTools import with EnhancedRAGTools"
    echo "   - Restart your MCP server"
    echo ""
    echo "4. 🔍 Test multi-source search capabilities:"
    echo "   - Query for 'UFS model installation'"
    echo "   - Query for 'Rocoto workflow dependencies'"
    echo "   - Query for 'EE2 compliance standards'"
    echo ""
    echo "5. 📊 Monitor knowledge base status:"
    echo "   - Use get_knowledge_base_status MCP tool"
    echo "   - Check source health and update frequencies"
    echo ""
    echo "6. 🔄 Set up periodic updates:"
    echo "   - Schedule weekly: node run-documentation-ingestion.js --incremental"
    echo "   - Schedule monthly: full re-ingestion"
    echo ""

    if [ -f "${SCRIPT_DIR}/knowledge-base/external_documentation_chunks.json" ]; then
        local chunk_count=$(jq '.chunks | length' "${SCRIPT_DIR}/knowledge-base/external_documentation_chunks.json" 2>/dev/null || echo "unknown")
        print_success "Knowledge base ready with ${chunk_count} external documentation chunks"
    fi

    echo ""
    print_step "📖 Documentation:"
    echo "- Architecture: docs/ENHANCED_RAG_ARCHITECTURE.md"
    echo "- Upgrade Plan: docs/RAG_MAJOR_UPGRADE_PLAN.md"
    echo "- Test Results: knowledge-base/test-report.json"
}

main() {
    case "${SETUP_MODE}" in
        "--help")
            show_help
            exit 0
            ;;
        "--quick")
            print_header
            check_dependencies
            install_packages
            run_quick_setup
            show_next_steps
            ;;
        "--full")
            print_header
            check_dependencies
            install_packages
            run_full_setup
            show_next_steps
            ;;
        "--test")
            print_header
            check_dependencies
            run_tests_only
            ;;
        *)
            print_error "Unknown option: ${SETUP_MODE}"
            show_help
            exit 1
            ;;
    esac

    print_success "Enhanced RAG System setup completed!"
}

# Check if jq is available (optional but helpful)
if ! command -v jq &> /dev/null; then
    print_warning "jq not found - some features may not work optimally"
    print_warning "Install jq for better JSON processing: sudo apt-get install jq"
fi

# Run main function
main