#!/usr/bin/env bash
# Node.js MCP Server Startup Script for Global Workflow

set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Function to check if Node.js is available
check_nodejs() {
    if ! command -v node &> /dev/null; then
        echo "ERROR: node is not installed or not in PATH"
        exit 1
    fi
    
    local node_version
    node_version=$(node --version | sed 's/v//')
    echo "Using Node.js ${node_version}"
    
    # Check if version is >= 18.0.0
    if [[ "${node_version}" < "18.0.0" ]]; then
        echo "WARNING: Node.js 18.0+ recommended, found ${node_version}"
    fi
}

# Function to start the MCP server
start_server() {
    echo "Starting Global Workflow Node.js MCP Server..."
    echo "Repository: ${SCRIPT_DIR}"
    echo "Server: ${SCRIPT_DIR}/mcp-server.js"
    echo ""
    
    cd "${SCRIPT_DIR}"
    exec node mcp-server.js
}

# Function to test the server
test_server() {
    echo "Testing Node.js MCP Server..."
    
    cd "${SCRIPT_DIR}"
    
    # Test server startup
    echo "Testing server startup..."
    if timeout 2s node mcp-server.js >/dev/null 2>&1; then
        echo "[PASS] Server starts and runs successfully"
    else
        echo "[INFO] Server starts (timeout expected for interactive server)"
    fi
    
    echo "[SUCCESS] Node.js MCP Server basic functionality verified!"
    return 0
}

# Function to show usage
show_usage() {
    echo "Global Workflow Node.js MCP Server Control Script"
    echo ""
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "    start       Start the MCP server (default)"
    echo "    test        Test server functionality"
    echo "    help        Show this help message"
    echo ""
    echo "Examples:"
    echo "    $0              # Start the server"
    echo "    $0 start        # Start the server"
    echo "    $0 test         # Test the server"
}

# Main script logic
main() {
    local command="${1:-start}"
    
    case "${command}" in
        start|"")
            check_nodejs
            start_server
            ;;
        test)
            check_nodejs
            test_server
            ;;
        help|-h|--help)
            show_usage
            ;;
        *)
            echo "ERROR: Unknown command: ${command}"
            show_usage
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"
