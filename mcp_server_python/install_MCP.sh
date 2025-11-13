#!/usr/bin/env bash
# MCP Server Installation Script for Global Workflow
# This script installs or removes MCP server files to/from a global-workflow repository

set -euo pipefail

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${0}")"

# MCP files to manage
MCP_FILES=(
    "mcp-server.py"
    "mcp-server.js" 
    "package.json"
    "start-mcp-server.sh"
    "MCP_SERVER_README.md"
    "test-copilot-integration.py"
    ".vscode/settings.json"
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
${SCRIPT_NAME} - MCP Server Installation Tool for Global Workflow

USAGE:
    ${SCRIPT_NAME} install <target_repo_path>     Install MCP files to target repository
    ${SCRIPT_NAME} remove <target_repo_path>      Remove MCP files from target repository
    ${SCRIPT_NAME} list                           List MCP files that will be managed
    ${SCRIPT_NAME} check <target_repo_path>       Check which files exist in target repository
    ${SCRIPT_NAME} diff <target_repo_path>        Show differences between source and target files
    ${SCRIPT_NAME} copyback <target_repo_path>    Copy files back from target to source directory
    ${SCRIPT_NAME} help                           Show this help message

EXAMPLES:
    ${SCRIPT_NAME} install /path/to/global-workflow_forked
    ${SCRIPT_NAME} remove /home/user/global-workflow
    ${SCRIPT_NAME} check /path/to/my-workflow
    ${SCRIPT_NAME} diff /path/to/my-workflow
    ${SCRIPT_NAME} copyback /path/to/my-workflow

DESCRIPTION:
    This script manages MCP (Model Context Protocol) server files for 
    global-workflow repositories. It can install the complete MCP server
    setup, cleanly remove it, show differences between versions, or
    copy modified files back to the source directory.

    The script operates from: ${SCRIPT_DIR}
    
FILES MANAGED:
$(printf "    - %s\n" "${MCP_FILES[@]}")

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
    
    # Check if it looks like a global-workflow repository
    if [[ ! -f "${target_repo}/CMakeLists.txt" ]] || [[ ! -d "${target_repo}/jobs" ]]; then
        print_status "${YELLOW}" "WARNING: Target directory doesn't look like a global-workflow repository"
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
    
    for file in "${MCP_FILES[@]}"; do
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
    local backed_up_count=0
    
    print_status "${BLUE}" "Installing MCP server files to: ${target_repo}"
    
    validate_target_repo "${target_repo}" "install"
    check_source_files
    
    # Create .vscode directory if needed
    mkdir -p "${target_repo}/.vscode"
    
    for file in "${MCP_FILES[@]}"; do
        local source_file="${SCRIPT_DIR}/${file}"
        local target_file="${target_repo}/${file}"
        local target_dir="$(dirname "${target_file}")"
        
        # Create target directory if needed
        mkdir -p "${target_dir}"
        
        # Backup existing file if it exists
        if [[ -f "${target_file}" ]]; then
            local backup_file="${target_file}.backup.$(date +%Y%m%d_%H%M%S)"
            cp "${target_file}" "${backup_file}"
            print_status "${YELLOW}" "    Backed up existing: ${file} -> $(basename "${backup_file}")"
            backed_up_count=$((backed_up_count + 1))
        fi
        
        # Copy the file and preserve permissions
        cp "${source_file}" "${target_file}"
        chmod --reference="${source_file}" "${target_file}" 2>/dev/null || true
        
        print_status "${GREEN}" "    Installed: ${file}"
        installed_count=$((installed_count + 1))
    done
    
    # Update the VS Code settings with the correct path
    local settings_file="${target_repo}/.vscode/settings.json"
    if [[ -f "${settings_file}" ]]; then
        # Replace the cwd path with the actual target repo path
        sed -i "s|\"cwd\": \"[^\"]*\"|\"cwd\": \"${target_repo}\"|g" "${settings_file}"
        print_status "${BLUE}" "    Updated VS Code settings with correct path"
    fi
    
    print_status "${GREEN}" ""
    print_status "${GREEN}" "Installation complete!"
    print_status "${GREEN}" "    Files installed: ${installed_count}"
    if [[ ${backed_up_count} -gt 0 ]]; then
        print_status "${YELLOW}" "    Files backed up: ${backed_up_count}"
    fi
    print_status "${GREEN}" ""
    print_status "${GREEN}" "Next steps:"
    print_status "${GREEN}" "    1. Restart VS Code in the target repository"
    print_status "${GREEN}" "    2. Test the MCP server: cd ${target_repo} && ./start-mcp-server.sh test"
    print_status "${GREEN}" "    3. Read the documentation: ${target_repo}/MCP_SERVER_README.md"
}

# Function to remove MCP files
remove_mcp_files() {
    local target_repo="$1"
    local removed_count=0
    local not_found_count=0
    
    print_status "${BLUE}" "Removing MCP server files from: ${target_repo}"
    
    validate_target_repo "${target_repo}" "remove"
    
    for file in "${MCP_FILES[@]}"; do
        local target_file="${target_repo}/${file}"
        
        if [[ -f "${target_file}" ]]; then
            rm -f "${target_file}"
            print_status "${GREEN}" "    Removed: ${file}"
            removed_count=$((removed_count + 1))
        else
            print_status "${YELLOW}" "    Not found: ${file}"
            not_found_count=$((not_found_count + 1))
        fi
    done
    
    # Remove .vscode directory if it's empty (and only contains our settings.json)
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
    print_status "${BLUE}" "MCP Server files managed by this script:"
    print_status "${BLUE}" "Source directory: ${SCRIPT_DIR}"
    echo
    
    for file in "${MCP_FILES[@]}"; do
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
    
    print_status "${BLUE}" "Checking MCP files in: ${target_repo}"
    
    if [[ ! -d "${target_repo}" ]]; then
        print_status "${RED}" "ERROR: Target repository does not exist: ${target_repo}"
        exit 1
    fi
    
    echo
    
    for file in "${MCP_FILES[@]}"; do
        local target_file="${target_repo}/${file}"
        if [[ -f "${target_file}" ]]; then
            local size=$(stat -c%s "${target_file}" 2>/dev/null || echo "unknown")
            print_status "${GREEN}" "    [EXISTS] ${file} (${size} bytes)"
        else
            print_status "${YELLOW}" "    [MISSING] ${file}"
        fi
    done
}

# Function to show differences between source and target files
diff_target_files() {
    local target_repo="$1"
    
    print_status "${BLUE}" "Comparing MCP files between source and target:"
    print_status "${BLUE}" "Source: ${SCRIPT_DIR}"
    print_status "${BLUE}" "Target: ${target_repo}"
    
    if [[ ! -d "${target_repo}" ]]; then
        print_status "${RED}" "ERROR: Target repository does not exist: ${target_repo}"
        exit 1
    fi
    
    local has_differences=false
    echo
    
    for file in "${MCP_FILES[@]}"; do
        local source_file="${SCRIPT_DIR}/${file}"
        local target_file="${target_repo}/${file}"
        
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
    
    print_status "${BLUE}" "Copy back MCP files from target to source directory"
    print_status "${BLUE}" "Source: ${SCRIPT_DIR}"
    print_status "${BLUE}" "Target: ${target_repo}"
    
    if [[ ! -d "${target_repo}" ]]; then
        print_status "${RED}" "ERROR: Target repository does not exist: ${target_repo}"
        exit 1
    fi
    
    # Count files to copy back
    local files_to_copy=0
    local missing_files=()
    
    echo
    print_status "${BLUE}" "Analyzing files to copy back:"
    
    for file in "${MCP_FILES[@]}"; do
        local target_file="${target_repo}/${file}"
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
    
    for file in "${MCP_FILES[@]}"; do
        local target_file="${target_repo}/${file}"
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
