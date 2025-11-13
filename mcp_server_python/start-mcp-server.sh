#!/usr/bin/env bash
# MCP Server Startup Script for Global Workflow

set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Function to check if Python is available
check_python() {
    if ! command -v python3 &> /dev/null; then
        echo "ERROR: python3 is not installed or not in PATH"
        exit 1
    fi
    
    local python_version
    python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "Using Python ${python_version}"
    
    if [[ "${python_version}" < "3.8" ]]; then
        echo "WARNING: Python 3.8+ recommended, found ${python_version}"
    fi
}

# Function to start the MCP server
start_server() {
    echo "Starting Global Workflow MCP Server..."
    echo "Repository: ${SCRIPT_DIR}"
    echo "Server: ${SCRIPT_DIR}/mcp-server.py"
    echo ""
    echo "Server is ready for MCP connections on stdin/stdout"
    echo "Logs will appear on stderr"
    echo ""
    
    cd "${SCRIPT_DIR}"
    exec python3 mcp-server.py
}

# Function to test the server
test_server() {
    echo "Testing MCP Server..."
    
    cd "${SCRIPT_DIR}"
    
    # Test initialization
    echo "Testing initialization..."
    local init_response
    init_response=$(echo '{"method": "initialize", "id": 1, "params": {"protocolVersion": "2024-11-05", "capabilities": {}}}' | python3 mcp-server.py 2>/dev/null)
    
    if echo "${init_response}" | grep -q '"name": "global-workflow-mcp"'; then
        echo "[PASS] Server initializes correctly"
    else
        echo "[FAIL] Server initialization failed"
        return 1
    fi
    
    # Test tools list
    echo "Testing tools list..."
    local tools_response
    tools_response=$(echo '{"method": "tools/list", "id": 2}' | python3 mcp-server.py 2>/dev/null)
    
    if echo "${tools_response}" | grep -q '"name": "get_workflow_info"'; then
        echo "[PASS] Tools are available"
    else
        echo "[FAIL] Tools list failed"
        return 1
    fi
    
    echo "[SUCCESS] MCP Server is working correctly!"
    return 0
}

# Function to show usage
show_usage() {
    cat << EOF
Global Workflow MCP Server Control Script

Usage: $0 [COMMAND]

Commands:
    start       Start the MCP server (default)
    test        Test server functionality
    check       Check Python installation
    help        Show this help message

Examples:
    $0              # Start the server
    $0 start        # Start the server
    $0 test         # Test the server
    $0 check        # Check Python setup

Note: The server communicates via stdin/stdout using JSON-RPC.
      Logs are written to stderr.
EOF
}

# Main script logic
main() {
    local command="${1:-start}"
    
    case "${command}" in
        start|"")
            check_python
            start_server
            ;;
        test)
            check_python
            test_server
            ;;
        check)
            check_python
            echo "Python setup is correct for MCP server"
            ;;
        help|-h|--help)
            show_usage
            ;;
        *)
            echo "ERROR: Unknown command: ${command}"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"
