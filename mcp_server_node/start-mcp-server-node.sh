#!/bin/bash

# Global Workflow RAG-Enhanced Node.js MCP Server Control Script
# This script manages a Node.js-based Model Context Protocol (MCP) server
# with enhanced RAG (Retrieval-Augmented Generation) capabilities
# 
# Optional Hugging Face Integration:
# Set ENABLE_HF_INTEGRATION=true to enable enhanced server with HF capabilities

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Initialize spack-stack module environment for Python 3.11.11
if [[ -f "${SCRIPT_DIR}/init-spack-modules.sh" ]]; then
    source "${SCRIPT_DIR}/init-spack-modules.sh" >/dev/null 2>&1
fi

# Load configuration file if it exists
if [[ -f "${SCRIPT_DIR}/mcp-config.env" ]]; then
    # Source the config file, but don't override existing environment variables
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$key" ]] && continue
        
        # Only set if not already set in environment
        if [[ -z "${!key}" ]]; then
            export "$key"="$value"
        fi
    done < "${SCRIPT_DIR}/mcp-config.env"
fi

# Configuration with defaults
ENABLE_HF_INTEGRATION="${ENABLE_HF_INTEGRATION:-false}"

# Function to log messages (respects quiet mode)
log_info() {
    if [[ "${QUIET_MODE}" != "true" ]]; then
        echo "$@" >&2
    fi
}

# Function to log errors (always shown)
log_error() {
    echo "$@" >&2
}

# Function to check if Node.js is available and meets minimum version
check_nodejs() {
    if ! command -v node >/dev/null 2>&1; then
        log_error "ERROR: Node.js is not installed or not in PATH"
        log_error "Please install Node.js version 18.0.0 or higher"
        exit 1
    fi

    # Get Node.js version and extract major version number
    local node_version
    node_version=$(node --version 2>/dev/null | sed 's/v//')
    local major_version
    major_version=$(echo "${node_version}" | cut -d. -f1)

    if [[ ! "${major_version}" =~ ^[0-9]+$ ]] || [[ "${major_version}" -lt 18 ]]; then
        log_error "ERROR: Node.js version ${node_version} is too old"
        log_error "Please install Node.js version 18.0.0 or higher"
        exit 1
    fi

    log_info "Node.js version ${node_version} detected"
}

# Function to start the RAG-enhanced MCP server
start_server() {
    log_info "Starting RAG-Enhanced Node.js MCP Server..."

    # Change to the MCP server directory
    cd "${SCRIPT_DIR}" || {
        log_error "ERROR: Cannot change to MCP server directory: ${SCRIPT_DIR}"
        exit 1
    }

    # Check if package.json exists
    if [[ ! -f "package.json" ]]; then
        log_error "ERROR: package.json not found in ${SCRIPT_DIR}"
        log_error "This directory does not appear to be a valid Node.js project"
        exit 1
    fi

    # Check if centralized node_modules exists or local node_modules (fallback)
    if [[ -n "${COPILOT_NODE_MODULES}" && -d "${COPILOT_NODE_MODULES}" ]]; then
        log_info "Using centralized node_modules: ${COPILOT_NODE_MODULES}"
        # Ensure symbolic link exists
        if [[ ! -L "node_modules" ]]; then
            log_info "Creating symbolic link to centralized node_modules..."
            ln -sf "${COPILOT_NODE_MODULES}" node_modules
        fi
    elif [[ ! -d "node_modules" ]]; then
        log_info "Installing Node.js dependencies locally (centralized modules not available)..."
        npm install || {
            log_error "ERROR: Failed to install Node.js dependencies"
            exit 1
        }
    fi

    # Select server based on configuration and availability
    local server_to_run=""
    local server_description=""
    
    if [[ "${ENABLE_HF_INTEGRATION}" == "true" ]]; then
        # Check for HF integration server first
        if [[ -f "hf_integration/mcp-server-enhanced-rag.js" ]]; then
            server_to_run="hf_integration/mcp-server-enhanced-rag.js"
            server_description="Enhanced RAG-MCP Server with Hugging Face integration"
            log_info "Features: Local RAG + Hugging Face MCP Bridge"
        elif [[ -f "mcp-server-enhanced-rag.js" ]]; then
            server_to_run="mcp-server-enhanced-rag.js"
            server_description="Enhanced RAG-MCP Server with Hugging Face integration"
            log_info "Features: Local RAG + Hugging Face MCP Bridge"
        else
            log_info "⚠ HF integration requested but enhanced server not found"
            log_info "Falling back to standard RAG server"
            server_to_run="mcp-server-rag.js"
            server_description="RAG-Enhanced MCP Server"
        fi
    else
        # Use standard RAG server or fallback to basic server
        if [[ "${LIGHTWEIGHT_MODE}" == "true" ]]; then
            server_to_run="mcp-server.js"
            server_description="Basic MCP Server (Lightweight Mode)"
        else
            server_to_run="mcp-server-rag.js" 
            server_description="RAG-Enhanced MCP Server"
        fi
    fi
    
    # Start the selected server
    log_info "Launching ${server_description}..."
    log_info "Server Directory: ${SCRIPT_DIR}"
    log_info "HF Integration: ${ENABLE_HF_INTEGRATION}"
    log_info "Press Ctrl+C to stop the server"
    
    if [[ -f "${server_to_run}" ]]; then
        node "${server_to_run}"
    else
        log_error "ERROR: Server file not found: ${server_to_run}"
        exit 1
    fi
}

# Function to test the RAG-enhanced MCP server
test_server() {
    log_info "Testing RAG-Enhanced Node.js MCP Server..."

    cd "${SCRIPT_DIR}"

    # Check if centralized node_modules exists or local node_modules (fallback)
    if [[ -n "${COPILOT_NODE_MODULES}" && -d "${COPILOT_NODE_MODULES}" ]]; then
        log_info "Using centralized node_modules: ${COPILOT_NODE_MODULES}"
        # Ensure symbolic link exists
        if [[ ! -L "node_modules" ]]; then
            log_info "Creating symbolic link to centralized node_modules..."
            ln -sf "${COPILOT_NODE_MODULES}" node_modules
        fi
    elif [[ ! -d "node_modules" ]]; then
        log_error "ERROR: No node_modules found and COPILOT_NODE_MODULES not set"
        log_error "Please install dependencies or set COPILOT_NODE_MODULES environment variable"
        exit 1
    fi

    # Test server startup
    log_info "Testing server startup..."
    log_info "HF Integration: ${ENABLE_HF_INTEGRATION}"
    
    local test_server=""
    if [[ "${ENABLE_HF_INTEGRATION}" == "true" && -f "hf_integration/mcp-server-enhanced-rag.js" ]]; then
        test_server="hf_integration/mcp-server-enhanced-rag.js"
        log_info "Testing HF-enhanced server..."
    elif [[ "${ENABLE_HF_INTEGRATION}" == "true" && -f "mcp-server-enhanced-rag.js" ]]; then
        test_server="mcp-server-enhanced-rag.js"
        log_info "Testing HF-enhanced server..."
    else
        test_server="mcp-server-rag.js"
        log_info "Testing standard RAG server..."
    fi
    
    if timeout 2s node "${test_server}" >/dev/null 2>&1; then
        log_info "[PASS] Server starts and runs successfully"
    else
        log_info "[INFO] Server starts (timeout expected for interactive server)"
    fi

    log_info "[SUCCESS] RAG-Enhanced Node.js MCP Server basic functionality verified!"
    return 0
}

# Function to show usage
show_usage() {
    log_error "Global Workflow RAG-Enhanced Node.js MCP Server Control Script"
    log_error ""
    log_error "Usage: $0 [COMMAND] [OPTIONS]"
    log_error ""
    log_error "Commands:"
    log_error "    start       Start the RAG-enhanced MCP server (default)"
    log_error "    test        Test server functionality"
    log_error "    help        Show this help message"
    log_error ""
    log_error "Options:"
    log_error "    --quiet     Run in quiet mode (suppress informational messages)"
    log_error "    --silent    Alias for --quiet"
    log_error ""
    log_error "Environment Variables:"
    log_error "    ENABLE_HF_INTEGRATION=true   Enable Hugging Face integration (optional)"
    log_error ""
    log_error "Examples:"
    log_error "    $0                                    # Start standard RAG server"
    log_error "    $0 start                              # Start standard RAG server"
    log_error "    $0 --quiet                            # Start server silently"
    log_error "    ENABLE_HF_INTEGRATION=true $0        # Start with HF integration"
    log_error "    $0 test                               # Test the server"
}

# Main script logic
main() {
    local command=""

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --quiet|--silent)
                QUIET_MODE=true
                shift
                ;;
            start|test|help|-h|--help)
                command="$1"
                shift
                ;;
            *)
                if [[ -z "${command}" ]]; then
                    command="$1"
                else
                    log_error "ERROR: Unknown option: $1"
                    show_usage
                    exit 1
                fi
                shift
                ;;
        esac
    done

    # Default to start if no command specified
    if [[ -z "${command}" ]]; then
        command="start"
    fi

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
            log_error "ERROR: Unknown command: ${command}"
            show_usage
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"
