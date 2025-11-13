#!/bin/bash

##
# Unified MCP Server Startup Script
# 
# Provides a clean, standardized way to start the unified MCP server
# with different configuration scenarios and proper environment setup.
#
# @version 2.0.0
# @author NOAA EMC Global Workflow Team
##

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_SCRIPT="${SCRIPT_DIR}/src/UnifiedMCPServer.js"
PACKAGE_JSON="${SCRIPT_DIR}/unified-package.json"
NODE_MODULES="${SCRIPT_DIR}/node_modules"

# Default values
SCENARIO="full"
VERBOSE=false
CHECK_DEPS=true
QUIET=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    if [[ "$QUIET" != "true" ]]; then
        echo -e "${BLUE}ℹ️  $1${NC}" >&2
    fi
}

log_success() {
    if [[ "$QUIET" != "true" ]]; then
        echo -e "${GREEN}✅ $1${NC}" >&2
    fi
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}" >&2
}

log_error() {
    echo -e "${RED}❌ $1${NC}" >&2
}

# Help function
show_help() {
    cat << EOF
Unified MCP Server Startup Script

USAGE:
    $0 [OPTIONS] [SCENARIO]

SCENARIOS:
    full     - All features enabled (RAG + GitHub integration)
    core     - Core workflow tools only
    rag      - Workflow tools + semantic search (no GitHub)
    github   - Workflow tools + GitHub integration (no RAG)

OPTIONS:
    -h, --help       Show this help message
    -v, --verbose    Enable verbose output
    -q, --quiet      Quiet mode (minimal output)
    --no-deps-check  Skip dependency checking
    --test           Run health check after startup
    --info           Show server info after startup

EXAMPLES:
    $0                    # Start with full configuration
    $0 core               # Start with core tools only
    $0 --verbose rag      # Start RAG server with verbose output
    $0 --quiet github     # Start GitHub server in quiet mode

ENVIRONMENT VARIABLES:
    GITHUB_TOKEN         GitHub API token for repository integration
    MCP_KNOWLEDGE_BASE   Path to knowledge base directory
    MCP_WORKFLOW_ROOT    Path to global-workflow root directory
    NODE_ENV             Node environment (development/production)

EOF
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            -q|--quiet)
                QUIET=true
                shift
                ;;
            --no-deps-check)
                CHECK_DEPS=false
                shift
                ;;
            --test)
                POST_STARTUP_TEST=true
                shift
                ;;
            --info)
                POST_STARTUP_INFO=true
                shift
                ;;
            full|core|rag|github)
                SCENARIO=$1
                shift
                ;;
            -*)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
            *)
                log_error "Unknown argument: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# Check system requirements
check_system() {
    log_info "Checking system requirements..."
    
    # Check Node.js version
    if ! command -v node &> /dev/null; then
        log_error "Node.js is not installed"
        exit 1
    fi
    
    local node_version
    node_version=$(node --version | sed 's/v//')
    local required_version="18.0.0"
    
    if ! node -e "process.exit(process.version.slice(1).split('.').map(Number).every((v,i) => v >= '$required_version'.split('.')[i] || 0) ? 0 : 1)"; then
        log_error "Node.js version $node_version is below required $required_version"
        exit 1
    fi
    
    log_success "Node.js version $node_version is compatible"
}

# Check and install dependencies
check_dependencies() {
    if [[ "$CHECK_DEPS" != "true" ]]; then
        log_info "Skipping dependency check"
        return 0
    fi
    
    log_info "Checking dependencies..."
    
    if [[ ! -d "$NODE_MODULES" ]]; then
        log_warning "Node modules not found, installing dependencies..."
        if [[ -f "$PACKAGE_JSON" ]]; then
            npm install --package-lock-only --prefix "$SCRIPT_DIR" --package.json="$PACKAGE_JSON"
        else
            npm install --prefix "$SCRIPT_DIR"
        fi
    fi
    
    # Check for critical dependencies
    local critical_deps=("@modelcontextprotocol/sdk")
    for dep in "${critical_deps[@]}"; do
        if [[ ! -d "$NODE_MODULES/$dep" ]]; then
            log_warning "Critical dependency $dep missing, installing..."
            npm install "$dep" --prefix "$SCRIPT_DIR"
        fi
    done
    
    log_success "Dependencies verified"
}

# Validate server files
validate_server() {
    log_info "Validating server files..."
    
    if [[ ! -f "$SERVER_SCRIPT" ]]; then
        log_error "Server script not found: $SERVER_SCRIPT"
        exit 1
    fi
    
    # Validate Node.js syntax
    if ! node --check "$SERVER_SCRIPT" 2>/dev/null; then
        log_error "Server script has syntax errors"
        exit 1
    fi
    
    log_success "Server files validated"
}

# Setup environment
setup_environment() {
    log_info "Setting up environment for scenario: $SCENARIO"
    
    # Set Node environment if not set
    export NODE_ENV="${NODE_ENV:-development}"
    
    # Validate scenario-specific requirements
    case $SCENARIO in
        github|full)
            if [[ -z "${GITHUB_TOKEN:-}" ]]; then
                log_warning "GITHUB_TOKEN not set - GitHub features will be limited"
            else
                log_success "GitHub token configured"
            fi
            ;;
    esac
    
    # Check knowledge base for RAG scenarios
    case $SCENARIO in
        rag|full)
            local kb_path="${MCP_KNOWLEDGE_BASE:-$SCRIPT_DIR/knowledge-base}"
            if [[ ! -d "$kb_path" ]]; then
                log_warning "Knowledge base not found at $kb_path - RAG features may be limited"
            else
                log_success "Knowledge base found at $kb_path"
            fi
            ;;
    esac
}

# Start the server
start_server() {
    log_info "Starting Unified MCP Server with '$SCENARIO' configuration..."
    
    local node_args=()
    if [[ "$VERBOSE" == "true" ]]; then
        node_args+=("--trace-warnings")
    fi
    
    # Start the server
    exec node "${node_args[@]}" "$SERVER_SCRIPT" "$SCENARIO"
}

# Post-startup actions
post_startup_actions() {
    if [[ "${POST_STARTUP_TEST:-}" == "true" ]]; then
        log_info "Running health check..."
        echo '{"method": "tools/call", "params": {"name": "health_check", "arguments": {"detailed": true}}, "id": 1}' | \
            node "$SERVER_SCRIPT" "$SCENARIO" | grep -q "health" && \
            log_success "Health check passed" || \
            log_warning "Health check failed"
    fi
    
    if [[ "${POST_STARTUP_INFO:-}" == "true" ]]; then
        log_info "Getting server info..."
        echo '{"method": "tools/call", "params": {"name": "get_server_info", "arguments": {"include_capabilities": true}}, "id": 1}' | \
            node "$SERVER_SCRIPT" "$SCENARIO"
    fi
}

# Signal handlers for clean shutdown
cleanup() {
    log_info "Shutting down server..."
    exit 0
}

trap cleanup SIGINT SIGTERM

# Main execution
main() {
    parse_args "$@"
    
    if [[ "$QUIET" != "true" ]]; then
        echo -e "${BLUE}"
        echo "🚀 Global Workflow Unified MCP Server"
        echo "======================================"
        echo -e "${NC}"
    fi
    
    check_system
    check_dependencies
    validate_server
    setup_environment
    
    # Run post-startup actions in background if requested
    if [[ "${POST_STARTUP_TEST:-}${POST_STARTUP_INFO:-}" ]]; then
        (sleep 2 && post_startup_actions) &
    fi
    
    start_server
}

# Execute main function with all arguments
main "$@"