#!/usr/bin/env bash
# Node.js MCP Server Installation Script for Global Workflow
# This script installs or removes MCP server files to/from a global-workflow-node repository

set -euo pipefail

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${0}")"

# MCP Server directory structure configuration
# Relative path from target repository root to MCP server RUN directory
MCP_RUN_SUBDIR="dev/ci/scripts/utils/Copilot/mcp_server_node/RUN"

# Node.js MCP files to manage
MCP_NODE_FILES=(
    "mcp-server.js"
    "package.json"
    "package-lock.json"
    "start-mcp-server-node.sh"
    "test-copilot-integration.py"
    "MCP_SERVER_node-js_README.md"
    ".vscode/settings-node.json"
)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function to show usage
show_usage() {
    cat << EOF
${SCRIPT_NAME} - Node.js MCP Server Installation Tool for Global Workflow

USAGE:
    ${SCRIPT_NAME} install <target_repo_path>     Install Node.js MCP files to target repository
    ${SCRIPT_NAME} remove <target_repo_path>      Remove Node.js MCP files from target repository
    ${SCRIPT_NAME} list                           List Node.js MCP files that will be managed
    ${SCRIPT_NAME} check <target_repo_path>       Check which files exist in target repository
    ${SCRIPT_NAME} diff <target_repo_path>        Show differences between source and target files
    ${SCRIPT_NAME} copyback <target_repo_path>    Copy files back from target to source directory
    ${SCRIPT_NAME} help                           Show this help message

EXAMPLES:
    ${SCRIPT_NAME} install /path/to/global-workflow-node_forked
    ${SCRIPT_NAME} remove /home/user/global-workflow-node
    ${SCRIPT_NAME} check /path/to/my-workflow
    ${SCRIPT_NAME} diff /path/to/my-workflow
    ${SCRIPT_NAME} copyback /path/to/my-workflow

DESCRIPTION:
    This script manages Node.js MCP (Model Context Protocol) server files for 
    global-workflow-node repositories. It can install the complete Node.js MCP server
    setup, cleanly remove it, show differences between versions, or
    copy modified files back to the source directory.

    The script operates from: ${SCRIPT_DIR}
    
FILES MANAGED:
$(printf "    - %s\n" "${MCP_NODE_FILES[@]}")

NOTES:
    - Target repository must exist
    - Files are copied/moved, not symlinked
    - VS Code settings are created in .vscode/ directory
    - Script preserves file permissions
    - Backup functionality for existing files (install only)
    - diff command shows detailed file differences
    - copyback command requires confirmation before proceeding
EOF
}

# Function to validate target repository
validate_target_repo() {
    local target_repo="$1"
    local operation="${2:-install}"  # Default to install if not specified
    
    if [[ ! -d "${target_repo}" ]]; then
        print_status "${RED}" "ERROR: Target repository directory does not exist: ${target_repo}"
        exit 1
    fi
    
    # Check if it looks like a global-workflow-node repository
    if [[ ! -f "${target_repo}/CMakeLists.txt" ]] || [[ ! -d "${target_repo}/jobs" ]]; then
        print_status "${YELLOW}" "WARNING: Target directory doesn't look like a global-workflow-node repository"
        print_status "${YELLOW}" "         Expected to find CMakeLists.txt and jobs/ directory"
        
        # For remove operations, just warn but continue
        if [[ "${operation}" == "remove" ]]; then
            print_status "${YELLOW}" "         Continuing with ${operation} operation anyway..."
            return 0
        fi
        
        # For install operations, ask for confirmation
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_status "${YELLOW}" "Installation cancelled"
            exit 0
        fi
    fi
}

# Function to check which files exist in source directory
check_source_files() {
    local missing_files=()
    
    for file in "${MCP_NODE_FILES[@]}"; do
        local source_file="${SCRIPT_DIR}/${file}"
        if [[ ! -f "${source_file}" ]]; then
            missing_files+=("${file}")
        fi
    done
    
    if [[ ${#missing_files[@]} -gt 0 ]]; then
        print_status "${RED}" "ERROR: Missing source files in ${SCRIPT_DIR}:"
        printf "${RED}    - %s${NC}\n" "${missing_files[@]}"
        exit 1
    fi
}

# Function to install MCP files
install_mcp_files() {
    local target_repo="$1"
    local installed_count=0
    local backed_up_run_dir=false
    
    # Define the MCP server subdirectory path
    local mcp_run_dir="${target_repo}/${MCP_RUN_SUBDIR}"
    
    print_status "${BLUE}" "Installing Node.js MCP server files to: ${mcp_run_dir}"
    
    validate_target_repo "${target_repo}" "install"
    check_source_files
    
    # Backup existing RUN directory if it exists and has files
    if [[ -d "${mcp_run_dir}" ]] && [[ $(find "${mcp_run_dir}" -type f | wc -l) -gt 0 ]]; then
        local backup_dir="${mcp_run_dir}.backup.$(date +%Y%m%d_%H%M%S)"
        print_status "${YELLOW}" "Backing up existing RUN directory..."
        cp -r "${mcp_run_dir}" "${backup_dir}"
        print_status "${YELLOW}" "    Backed up: ${mcp_run_dir} -> ${backup_dir}"
        backed_up_run_dir=true
    fi
    
    # Create MCP server directory structure (this will create all parent dirs too)
    mkdir -p "${mcp_run_dir}"
    mkdir -p "${target_repo}/.vscode"
    
    for file in "${MCP_NODE_FILES[@]}"; do
        local source_file="${SCRIPT_DIR}/${file}"
        
        # Handle .vscode files differently - they go to the repo root
        if [[ "${file}" == .vscode/* ]]; then
            local target_file="${target_repo}/${file}"
        else
            # All other files go to the RUN subdirectory
            local target_file="${mcp_run_dir}/${file}"
        fi
        
        # Copy the file and preserve permissions
        cp "${source_file}" "${target_file}"
        chmod --reference="${source_file}" "${target_file}" 2>/dev/null || true
        
        print_status "${GREEN}" "    Installed: ${file}"
        installed_count=$((installed_count + 1))
    done
    
    # Update the VS Code settings with the correct path
    local settings_file="${target_repo}/.vscode/settings-node.json"
    if [[ -f "${settings_file}" ]]; then
        # Replace the cwd path to point to the MCP RUN subdirectory using VS Code workspace variable
        sed -i "s|\${workspaceFolder}|\${workspaceFolder}/${MCP_RUN_SUBDIR}|g" "${settings_file}"
        print_status "${BLUE}" "    Updated VS Code settings with correct MCP RUN directory path"
    fi
    
    print_status "${GREEN}" ""
    print_status "${GREEN}" "Installation complete!"
    print_status "${GREEN}" "    Files installed: ${installed_count}"
    if [[ "${backed_up_run_dir}" == "true" ]]; then
        print_status "${YELLOW}" "    Previous RUN directory backed up"
    fi
    print_status "${GREEN}" ""
    print_status "${GREEN}" "Next steps:"
    print_status "${GREEN}" "    1. Restart VS Code in the target repository"
    print_status "${GREEN}" "    2. Test the MCP server: cd ${mcp_run_dir} && ./start-mcp-server-node.sh test"
    print_status "${GREEN}" "    3. Read the documentation: ${mcp_run_dir}/MCP_SERVER_node-js_README.md"
}

# Function to remove MCP files
remove_mcp_files() {
    local target_repo="$1"
    local removed_count=0
    local not_found_count=0
    
    # Define the MCP server subdirectory path
    local mcp_run_dir="${target_repo}/${MCP_RUN_SUBDIR}"
    
    print_status "${BLUE}" "Removing Node.js MCP server files from: ${mcp_run_dir}"
    
    validate_target_repo "${target_repo}" "remove"
    
    for file in "${MCP_NODE_FILES[@]}"; do
        # Handle .vscode files differently - they are in the repo root
        if [[ "${file}" == .vscode/* ]]; then
            local target_file="${target_repo}/${file}"
        else
            # All other files are in the RUN subdirectory
            local target_file="${mcp_run_dir}/${file}"
        fi
        
        if [[ -f "${target_file}" ]]; then
            rm -f "${target_file}"
            print_status "${GREEN}" "    Removed: ${file}"
            removed_count=$((removed_count + 1))
        else
            print_status "${YELLOW}" "    Not found: ${file}"
            not_found_count=$((not_found_count + 1))
        fi
    done
    
    # Remove node_modules if it exists in the RUN directory
    if [[ -d "${mcp_run_dir}/node_modules" ]]; then
        print_status "${BLUE}" "    Removing node_modules directory..."
        rm -rf "${mcp_run_dir}/node_modules"
        print_status "${GREEN}" "    Removed: node_modules/"
    fi

    # Remove .vscode directory if it's empty (and only contains our settings-node.json)
    local vscode_dir="${target_repo}/.vscode"
    if [[ -d "${vscode_dir}" ]]; then
        if [[ $(find "${vscode_dir}" -type f | wc -l) -eq 0 ]]; then
            rmdir "${vscode_dir}" 2>/dev/null || true
            print_status "${GREEN}" "    Removed empty .vscode directory"
        fi
    fi
    
    print_status "${GREEN}" ""
    print_status "${GREEN}" "Removal complete!"
    print_status "${GREEN}" "    Files removed: ${removed_count}"
    if [[ ${not_found_count} -gt 0 ]]; then
        print_status "${YELLOW}" "    Files not found: ${not_found_count}"
    fi
}

# Function to list MCP files
list_mcp_files() {
    print_status "${BLUE}" "Node.js MCP Server files managed by this script:"
    print_status "${BLUE}" "Source directory: ${SCRIPT_DIR}"
    echo
    
    for file in "${MCP_NODE_FILES[@]}"; do
        local source_file="${SCRIPT_DIR}/${file}"
        if [[ -f "${source_file}" ]]; then
            local size=$(stat -c%s "${source_file}" 2>/dev/null || echo "unknown")
            print_status "${GREEN}" "    [EXISTS] ${file} (${size} bytes)"
        else
            print_status "${RED}" "    [MISSING] ${file}"
        fi
    done
}

# Function to check files in target repository
check_target_files() {
    local target_repo="$1"
    
    # Define the MCP server subdirectory path
    local mcp_run_dir="${target_repo}/${MCP_RUN_SUBDIR}"
    
    print_status "${BLUE}" "Checking Node.js MCP files in: ${mcp_run_dir}"
    
    if [[ ! -d "${target_repo}" ]]; then
        print_status "${RED}" "ERROR: Target repository does not exist: ${target_repo}"
        exit 1
    fi
    
    echo
    
    for file in "${MCP_NODE_FILES[@]}"; do
        local source_file="${SCRIPT_DIR}/${file}"
        
        # Handle .vscode files differently - they are in the repo root
        if [[ "${file}" == .vscode/* ]]; then
            local target_file="${target_repo}/${file}"
        else
            # All other files are in the RUN subdirectory
            local target_file="${mcp_run_dir}/${file}"
        fi
        
        if [[ -f "${target_file}" ]]; then
            local size=$(stat -c%s "${target_file}" 2>/dev/null || echo "unknown")
            
            # Check if source file exists and compare with target
            if [[ -f "${source_file}" ]]; then
                if ! diff -q "${source_file}" "${target_file}" >/dev/null 2>&1; then
                    print_status "${YELLOW}" "    [DIFFER] ${file} (${size} bytes)"
                else
                    print_status "${GREEN}" "    [EXISTS] ${file} (${size} bytes)"
                fi
            else
                # Source file doesn't exist, just show EXISTS
                print_status "${GREEN}" "    [EXISTS] ${file} (${size} bytes)"
            fi
        else
            print_status "${YELLOW}" "    [MISSING] ${file}"
        fi
    done
}

# Function to show differences between source and target files
diff_target_files() {
    local target_repo="$1"
    
    # Define the MCP server subdirectory path
    local mcp_run_dir="${target_repo}/${MCP_RUN_SUBDIR}"
    
    print_status "${BLUE}" "Comparing Node.js MCP files between source and target:"
    print_status "${BLUE}" "Source: ${SCRIPT_DIR}"
    print_status "${BLUE}" "Target: ${mcp_run_dir}"
    
    if [[ ! -d "${target_repo}" ]]; then
        print_status "${RED}" "ERROR: Target repository does not exist: ${target_repo}"
        exit 1
    fi
    
    local has_differences=false
    echo
    
    for file in "${MCP_NODE_FILES[@]}"; do
        local source_file="${SCRIPT_DIR}/${file}"
        
        # Handle .vscode files differently - they are in the repo root
        if [[ "${file}" == .vscode/* ]]; then
            local target_file="${target_repo}/${file}"
        else
            # All other files are in the RUN subdirectory
            local target_file="${mcp_run_dir}/${file}"
        fi
        
        if [[ ! -f "${source_file}" ]]; then
            print_status "${RED}" "    [SOURCE MISSING] ${file}"
            has_differences=true
            continue
        fi
        
        if [[ ! -f "${target_file}" ]]; then
            print_status "${YELLOW}" "    [TARGET MISSING] ${file}"
            has_differences=true
            continue
        fi
        
        # Compare files
        if ! diff -q "${source_file}" "${target_file}" >/dev/null 2>&1; then
            print_status "${YELLOW}" "    [DIFFERENT] ${file}"
            has_differences=true
            
            # Show the actual diff
            echo
            print_status "${BLUE}" "    Differences in ${file}:"
            diff -u "${source_file}" "${target_file}" || true
            echo
        else
            print_status "${GREEN}" "    [IDENTICAL] ${file}"
        fi
    done
    
    if [[ "${has_differences}" == "false" ]]; then
        echo
        print_status "${GREEN}" "All files are identical between source and target!"
    fi
}

# Function to copy files back from target to source directory
copyback_mcp_files() {
    local target_repo="$1"
    
    # Define the MCP server subdirectory path
    local mcp_run_dir="${target_repo}/${MCP_RUN_SUBDIR}"
    
    print_status "${BLUE}" "Copy back Node.js MCP files from target to source directory"
    print_status "${BLUE}" "Source: ${SCRIPT_DIR}"
    print_status "${BLUE}" "Target: ${mcp_run_dir}"
    
    if [[ ! -d "${target_repo}" ]]; then
        print_status "${RED}" "ERROR: Target repository does not exist: ${target_repo}"
        exit 1
    fi
    
    # Count files to copy back
    local files_to_copy=0
    local missing_files=()
    
    echo
    print_status "${BLUE}" "Analyzing files to copy back:"
    
    for file in "${MCP_NODE_FILES[@]}"; do
        # Handle .vscode files differently - they are in the repo root
        if [[ "${file}" == .vscode/* ]]; then
            local target_file="${target_repo}/${file}"
        else
            # All other files are in the RUN subdirectory
            local target_file="${mcp_run_dir}/${file}"
        fi
        
        local source_file="${SCRIPT_DIR}/${file}"
        
        if [[ -f "${target_file}" ]]; then
            if [[ -f "${source_file}" ]]; then
                if ! diff -q "${source_file}" "${target_file}" >/dev/null 2>&1; then
                    print_status "${YELLOW}" "    [WILL COPY] ${file} (files differ)"
                    files_to_copy=$((files_to_copy + 1))
                else
                    print_status "${GREEN}" "    [SKIP] ${file} (identical)"
                fi
            else
                print_status "${BLUE}" "    [NEW FILE] ${file} (will create in source)"
                files_to_copy=$((files_to_copy + 1))
            fi
        else
            missing_files+=("${file}")
            print_status "${RED}" "    [MISSING] ${file}"
        fi
    done
    
    if [[ ${#missing_files[@]} -gt 0 ]]; then
        echo
        print_status "${YELLOW}" "WARNING: ${#missing_files[@]} files are missing in target repository"
    fi
    
    if [[ ${files_to_copy} -eq 0 ]]; then
        echo
        print_status "${GREEN}" "No files need to be copied back - all are identical or missing!"
        return 0
    fi
    
    echo
    print_status "${YELLOW}" "About to copy ${files_to_copy} files from target back to source directory."
    print_status "${YELLOW}" "This will overwrite any existing files in the source directory."
    echo
    
    # Confirmation prompt
    local response
    read -p "Are you sure you want to proceed? (Y/n): " -r response
    echo
    
    # Default to 'Y' if user just presses Enter
    if [[ -z "${response}" ]]; then
        response="Y"
    fi
    
    case "${response}" in
        [Yy]|[Yy][Ee][Ss])
            print_status "${GREEN}" "Proceeding with copy back operation..."
            ;;
        *)
            print_status "${YELLOW}" "Operation cancelled by user."
            return 0
            ;;
    esac
    
    # Perform the copy back operation
    local copied_count=0
    
    for file in "${MCP_NODE_FILES[@]}"; do
        # Handle .vscode files differently - they are in the repo root
        if [[ "${file}" == .vscode/* ]]; then
            local target_file="${target_repo}/${file}"
        else
            # All other files are in the RUN subdirectory
            local target_file="${mcp_run_dir}/${file}"
        fi
        
        local source_file="${SCRIPT_DIR}/${file}"
        local source_dir="$(dirname "${source_file}")"
        
        if [[ -f "${target_file}" ]]; then
            # Skip if files are identical
            if [[ -f "${source_file}" ]] && diff -q "${source_file}" "${target_file}" >/dev/null 2>&1; then
                continue
            fi
            
            # Create source directory if needed
            mkdir -p "${source_dir}"
            
            # Copy the file and preserve permissions
            cp "${target_file}" "${source_file}"
            chmod --reference="${target_file}" "${source_file}" 2>/dev/null || true
            
            print_status "${GREEN}" "    Copied back: ${file}"
            copied_count=$((copied_count + 1))
        fi
    done
    
    echo
    print_status "${GREEN}" "Copy back operation complete!"
    print_status "${GREEN}" "    Files copied: ${copied_count}"
}

# Main script logic
main() {
    local command="${1:-help}"
    
    case "${command}" in
        install)
            if [[ $# -ne 2 ]]; then
                print_status "${RED}" "ERROR: install command requires target repository path"
                echo
                show_usage
                exit 1
            fi
            install_mcp_files "$2"
            ;;
        remove)
            if [[ $# -ne 2 ]]; then
                print_status "${RED}" "ERROR: remove command requires target repository path"
                echo
                show_usage
                exit 1
            fi
            remove_mcp_files "$2"
            ;;
        list)
            list_mcp_files
            ;;
        check)
            if [[ $# -ne 2 ]]; then
                print_status "${RED}" "ERROR: check command requires target repository path"
                echo
                show_usage
                exit 1
            fi
            check_target_files "$2"
            ;;
        diff)
            if [[ $# -ne 2 ]]; then
                print_status "${RED}" "ERROR: diff command requires target repository path"
                echo
                show_usage
                exit 1
            fi
            diff_target_files "$2"
            ;;
        copyback)
            if [[ $# -ne 2 ]]; then
                print_status "${RED}" "ERROR: copyback command requires target repository path"
                echo
                show_usage
                exit 1
            fi
            copyback_mcp_files "$2"
            ;;
        help|-h|--help)
            show_usage
            ;;
        *)
            print_status "${RED}" "ERROR: Unknown command: ${command}"
            echo
            show_usage
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"
