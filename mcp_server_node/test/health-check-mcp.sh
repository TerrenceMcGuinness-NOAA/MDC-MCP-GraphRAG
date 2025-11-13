#!/bin/bash

# MCP Server Health Check Script
# This script diagnoses and maintains the MCP connection for Claude Code

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURSOR_CONFIG_DIR="$HOME/.cursor"
MCP_CONFIG_FILE="$CURSOR_CONFIG_DIR/mcp.json"
SERVER_SCRIPT="$SCRIPT_DIR/start-mcp-server-node.sh"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

# Function to check Node.js installation
check_nodejs() {
    log_info "Checking Node.js installation..."
    
    if ! command -v node >/dev/null 2>&1; then
        log_error "Node.js is not installed or not in PATH"
        return 1
    fi
    
    local node_version=$(node --version 2>/dev/null | sed 's/v//')
    local major_version=$(echo "${node_version}" | cut -d. -f1)
    
    if [[ ! "${major_version}" =~ ^[0-9]+$ ]] || [[ "${major_version}" -lt 18 ]]; then
        log_error "Node.js version ${node_version} is too old (requires 18+)"
        return 1
    fi
    
    log_success "Node.js version ${node_version} is compatible"
    return 0
}

# Function to check MCP configuration
check_mcp_config() {
    log_info "Checking MCP configuration..."
    
    if [[ ! -f "$MCP_CONFIG_FILE" ]]; then
        log_error "MCP configuration file not found: $MCP_CONFIG_FILE"
        return 1
    fi
    
    # Validate JSON syntax
    if ! python3 -m json.tool "$MCP_CONFIG_FILE" >/dev/null 2>&1; then
        log_error "Invalid JSON syntax in MCP configuration file"
        return 1
    fi
    
    # Check required fields
    if ! grep -q '"type".*"stdio"' "$MCP_CONFIG_FILE"; then
        log_error "Missing or incorrect 'type' field in MCP configuration"
        log_info "Should be: \"type\": \"stdio\""
        return 1
    fi
    
    # Check command path
    local command_path=$(grep -o '"command": "[^"]*' "$MCP_CONFIG_FILE" | cut -d'"' -f4)
    if [[ ! -f "$command_path" ]]; then
        log_error "MCP server script not found: $command_path"
        return 1
    fi
    
    if [[ ! -x "$command_path" ]]; then
        log_error "MCP server script is not executable: $command_path"
        return 1
    fi
    
    log_success "MCP configuration is valid"
    return 0
}

# Function to check server dependencies
check_server_dependencies() {
    log_info "Checking server dependencies..."
    
    cd "$SCRIPT_DIR" || {
        log_error "Cannot access server directory: $SCRIPT_DIR"
        return 1
    }
    
    if [[ ! -f "package.json" ]]; then
        log_error "package.json not found in server directory"
        return 1
    fi
    
    # Check node_modules
    if [[ -L "node_modules" ]]; then
        local link_target=$(readlink "node_modules")
        if [[ ! -d "$link_target" ]]; then
            log_error "Broken symbolic link to node_modules: $link_target"
            return 1
        fi
        log_success "Using centralized node_modules: $link_target"
    elif [[ -d "node_modules" ]]; then
        log_success "Using local node_modules"
    else
        log_error "No node_modules found (neither local nor linked)"
        return 1
    fi
    
    # Check main server file exists
    if [[ ! -f "mcp-server-rag.js" ]]; then
        log_error "Main server file not found: mcp-server-rag.js"
        return 1
    fi
    
    log_success "Server dependencies are available"
    return 0
}

# Function to test server startup
test_server_startup() {
    log_info "Testing server startup..."
    
    cd "$SCRIPT_DIR" || return 1
    
    # Test with timeout
    if timeout 3s "$SERVER_SCRIPT" test >/dev/null 2>&1; then
        log_success "Server startup test passed"
        return 0
    else
        local exit_code=$?
        if [[ $exit_code -eq 124 ]]; then
            log_success "Server starts correctly (timeout expected)"
            return 0
        else
            log_error "Server startup test failed (exit code: $exit_code)"
            return 1
        fi
    fi
}

# Function to check Cursor process
check_cursor_process() {
    log_info "Checking Cursor IDE process..."
    
    if pgrep -f "cursor" >/dev/null 2>&1; then
        log_success "Cursor IDE is running"
        return 0
    else
        log_warning "Cursor IDE is not currently running"
        return 1
    fi
}

# Function to show connection status
show_connection_status() {
    log_info "MCP Connection Status:"
    echo "  Server Directory: $SCRIPT_DIR"
    echo "  Config File: $MCP_CONFIG_FILE"
    echo "  Server Script: $SERVER_SCRIPT"
    
    if [[ -f "$MCP_CONFIG_FILE" ]]; then
        echo "  Configuration Preview:"
        head -10 "$MCP_CONFIG_FILE" | sed 's/^/    /'
    fi
}

# Function to fix common issues
fix_issues() {
    log_info "Attempting to fix common issues..."
    
    # Ensure script is executable
    if [[ ! -x "$SERVER_SCRIPT" ]]; then
        log_info "Making server script executable..."
        chmod +x "$SERVER_SCRIPT"
        log_success "Server script is now executable"
    fi
    
    # Check and fix MCP config type field
    if [[ -f "$MCP_CONFIG_FILE" ]] && ! grep -q '"type".*"stdio"' "$MCP_CONFIG_FILE"; then
        log_info "Adding missing 'type' field to MCP configuration..."
        # Create backup
        cp "$MCP_CONFIG_FILE" "$MCP_CONFIG_FILE.backup"
        
        # Add type field using sed
        sed 's/"command":/"type": "stdio",\n\t\t\t"command":/' "$MCP_CONFIG_FILE.backup" > "$MCP_CONFIG_FILE"
        log_success "Added 'type': 'stdio' to MCP configuration"
    fi
    
    # Enable lightweight mode for stability if RAG server is having issues
    if [[ -f "$SCRIPT_DIR/mcp-config.env" ]]; then
        if ! grep -q "LIGHTWEIGHT_MODE=true" "$SCRIPT_DIR/mcp-config.env"; then
            log_info "Enabling lightweight mode for better stability..."
            sed -i 's/LIGHTWEIGHT_MODE=false/LIGHTWEIGHT_MODE=true/' "$SCRIPT_DIR/mcp-config.env"
            log_success "Enabled lightweight mode (uses stable basic MCP server)"
        fi
    fi
    
    log_success "Common issues have been addressed"
}

# Main diagnostic function
run_diagnostics() {
    echo "=========================================="
    echo "MCP Server Health Check & Diagnostics"
    echo "=========================================="
    
    local all_passed=true
    
    # Run all checks
    check_nodejs || all_passed=false
    echo
    check_mcp_config || all_passed=false
    echo
    check_server_dependencies || all_passed=false
    echo
    test_server_startup || all_passed=false
    echo
    check_cursor_process || all_passed=false
    echo
    
    show_connection_status
    echo
    
    if [[ "$all_passed" == "true" ]]; then
        log_success "All checks passed! MCP server should be working correctly."
        echo
        log_info "To restart Cursor and reconnect to MCP:"
        log_info "1. Close Cursor completely"
        log_info "2. Reopen Cursor"
        log_info "3. The MCP server will start automatically when needed"
    else
        log_warning "Some issues were detected. Running auto-fix..."
        echo
        fix_issues
        echo
        log_info "Please restart Cursor to apply the fixes."
    fi
}

# Show usage
show_usage() {
    echo "MCP Server Health Check Script"
    echo ""
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  check       Run full diagnostics (default)"
    echo "  fix         Attempt to fix common issues"
    echo "  status      Show connection status only"
    echo "  test        Test server startup only"
    echo "  help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                    # Run full diagnostics"
    echo "  $0 check              # Run full diagnostics"
    echo "  $0 fix                # Fix common issues"
    echo "  $0 status             # Show status only"
    echo "  $0 test               # Test server startup"
}

# Main script execution
main() {
    local command="${1:-check}"
    
    case "$command" in
        check|"")
            run_diagnostics
            ;;
        fix)
            log_info "Running auto-fix for common issues..."
            fix_issues
            ;;
        status)
            show_connection_status
            ;;
        test)
            test_server_startup
            ;;
        help|-h|--help)
            show_usage
            ;;
        *)
            log_error "Unknown command: $command"
            show_usage
            exit 1
            ;;
    esac
}

# Execute main function
main "$@"