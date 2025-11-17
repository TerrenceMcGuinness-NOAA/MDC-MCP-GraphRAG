#!/bin/bash
################################################################################
# User Provisioning Script for MCP RAG Development Environment
# 
# Purpose: Create user accounts with complete development environment setup
# Author: GitHub Copilot
# Date: November 17, 2025
################################################################################

set -e  # Exit on error
set -u  # Exit on undefined variable

# Configuration
USERS=("Anna.Smoot" "Brian.Curtis" "Georgios.Britzolakis")
SCRATCH_ROOT="/mcp_rag_eib/SCRATCH_SPACE"
CODE_TUNNEL_SCRIPT="/mcp_rag_eib/eib-mcp-rag-server/SETUP/bin/code.sh"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root or with sudo
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root or with sudo"
        log_info "Usage: sudo $0"
        exit 1
    fi
}

# Extract first name from full username (Anna.Smoot -> Anna)
get_first_name() {
    local username="$1"
    echo "${username%%.*}"
}

# Create user account
create_user() {
    local username="$1"
    local first_name=$(get_first_name "$username")
    
    log_info "Creating user account: $username"
    
    # Check if user already exists
    if id "$username" &>/dev/null; then
        log_warn "User $username already exists, skipping creation"
        return 0
    fi
    
    # Create user with home directory
    useradd -m -s /bin/bash "$username"
    
    # Set a temporary password (user should change on first login)
    echo "$username:ChangeMe123!" | chpasswd
    
    # Force password change on first login
    chage -d 0 "$username"
    
    log_info "User $username created successfully"
}

# Setup SSH keys
setup_ssh() {
    local username="$1"
    local home_dir=$(eval echo ~"$username")
    local ssh_dir="${home_dir}/.ssh"
    
    log_info "Setting up SSH for $username"
    
    # Create .ssh directory with proper ownership first
    mkdir -p "$ssh_dir"
    chown "$username":"$username" "$ssh_dir"
    chmod 700 "$ssh_dir"
    
    # Generate RSA key pair (4096 bits, no passphrase for automation)
    if [[ ! -f "${ssh_dir}/id_rsa" ]]; then
        # Run ssh-keygen as the user with proper HOME environment
        sudo -u "$username" HOME="$home_dir" ssh-keygen -t rsa -b 4096 -f "${ssh_dir}/id_rsa" -N "" -C "${username}@mcp-rag-dev"
        log_info "Generated RSA key pair for $username"
    else
        log_warn "SSH keys already exist for $username"
    fi
    
    # Create authorized_keys file
    touch "${ssh_dir}/authorized_keys"
    chmod 600 "${ssh_dir}/authorized_keys"
    chown "$username":"$username" "${ssh_dir}/authorized_keys"
    
    # Ensure all permissions are correct
    chown -R "$username":"$username" "$ssh_dir"
    
    log_info "SSH setup complete for $username"
}

# Create scratch space workspace
create_scratch_space() {
    local username="$1"
    local workspace_dir="${SCRATCH_ROOT}/${username}"
    
    log_info "Creating scratch space for $username: $workspace_dir"
    
    # Create scratch root if it doesn't exist
    mkdir -p "$SCRATCH_ROOT"
    
    # Create user workspace
    mkdir -p "$workspace_dir"
    
    # Set ownership and permissions
    chown -R "$username":"$username" "$workspace_dir"
    chmod 755 "$workspace_dir"
    
    log_info "Scratch space created: $workspace_dir"
}

# Setup bin directory and copy code.sh script
setup_bin_directory() {
    local username="$1"
    local first_name=$(get_first_name "$username")
    local home_dir=$(eval echo ~"$username")
    local bin_dir="${home_dir}/bin"
    local user_code_script="${bin_dir}/code.sh"
    
    log_info "Setting up bin directory for $username"
    
    # Create bin directory
    mkdir -p "$bin_dir"
    
    # Copy and customize code.sh script
    if [[ -f "$CODE_TUNNEL_SCRIPT" ]]; then
        cp "$CODE_TUNNEL_SCRIPT" "$user_code_script"
        
        # Make executable
        chmod 755 "$user_code_script"
        
        # Set ownership
        chown "$username":"$username" "$user_code_script"
        
        log_info "Copied code.sh to $user_code_script"
    else
        log_error "Source code.sh script not found: $CODE_TUNNEL_SCRIPT"
        return 1
    fi
}

# Setup bash environment
setup_bash_environment() {
    local username="$1"
    local home_dir=$(eval echo ~"$username")
    local bashrc="${home_dir}/.bashrc"
    local bash_profile="${home_dir}/.bash_profile"
    local workspace_dir="${SCRATCH_ROOT}/${username}"
    
    # Templates location
    local bashrc_template="/mcp_rag_eib/eib-mcp-rag-server/SETUP/bashrc_template"
    local bash_profile_template="/mcp_rag_eib/eib-mcp-rag-server/SETUP/bash_profile_template"
    
    log_info "Configuring bash environment for $username"
    
    # Backup existing files
    [[ -f "$bashrc" ]] && cp "$bashrc" "${bashrc}.backup.$(date +%Y%m%d)"
    [[ -f "$bash_profile" ]] && cp "$bash_profile" "${bash_profile}.backup.$(date +%Y%m%d)"
    
    # Copy template files if they exist
    if [[ -f "$bashrc_template" ]]; then
        cp "$bashrc_template" "$bashrc"
        log_info "Copied bashrc_template to $bashrc"
    else
        log_warn "bashrc_template not found, skipping"
    fi
    
    if [[ -f "$bash_profile_template" ]]; then
        cp "$bash_profile_template" "$bash_profile"
        log_info "Copied bash_profile_template to $bash_profile"
    else
        log_warn "bash_profile_template not found, skipping"
    fi
    
    # Customize 'work' alias for user's workspace
    sed -i "s|alias work=.*|alias work='cd $workspace_dir'|g" "$bash_profile" 2>/dev/null || true
    
    # Add user-specific workspace setup to bashrc
    cat >> "$bashrc" << EOF

# ============================================================
# User-Specific Workspace Configuration
# Added by provision_users.sh on $(date)
# ============================================================

# Workspace environment variable
export WORKSPACE="$workspace_dir"

# Welcome message
if [ -t 1 ]; then
    echo "================================================"
    echo "  MCP RAG Development Environment"
    echo "  User: $username"
    echo "  Workspace: $workspace_dir"
    echo "  Use 'work' to navigate to your workspace"
    echo "================================================"
fi

EOF
    
    # Set ownership
    chown "$username":"$username" "$bashrc" "$bash_profile"
    
    log_info "Bash environment configured for $username"
}

# Create welcome README in workspace
create_workspace_readme() {
    local username="$1"
    local first_name=$(get_first_name "$username")
    local workspace_dir="${SCRATCH_ROOT}/${username}"
    local readme="${workspace_dir}/README.md"
    
    log_info "Creating workspace README for $username"
    
    cat > "$readme" << EOF
# Welcome to Your MCP RAG Development Workspace

**User**: $username  
**Workspace**: $workspace_dir  
**Created**: $(date)

---

## Quick Start

### Navigate to Workspace
Use the \`work\` alias to quickly navigate here:
\`\`\`bash
work
\`\`\`

### Start VS Code Tunnel
Your account includes a \`code.sh\` script to start a VS Code tunnel:
\`\`\`bash
code.sh
# or with custom server name:
code.sh my_server_name
\`\`\`

Default tunnel name: \`pw_${first_name}\`

### Check Tunnel Status
\`\`\`bash
cat ~/pw_${first_name}.out
\`\`\`

### SSH Keys
Your SSH keys are located in \`~/.ssh/\`:
- Private key: \`~/.ssh/id_rsa\`
- Public key: \`~/.ssh/id_rsa.pub\`

---

## Environment Setup

### Important Directories
- **Home**: \`~\`
- **Workspace**: \`$workspace_dir\`
- **Bin**: \`~/bin\` (in your PATH)
- **MCP Server**: \`/mcp_rag_eib/eib-mcp-rag-server\`

### Environment Variables
- \`\$WORKSPACE\` - Your scratch space directory

### Useful Aliases
- \`work\` - Navigate to your workspace

---

## MCP RAG System Access

### Documentation
- System docs: \`/mcp_rag_eib/eib-mcp-rag-server/docs/\`
- Health check: \`/mcp_rag_eib/eib-mcp-rag-server/docs/HEALTH_CHECK_NOV17_2025.md\`

### Services
- ChromaDB: http://localhost:8080
- Neo4j: http://localhost:7474 (bolt://localhost:7687)
- LangFlow: http://localhost:7860

---

## Getting Help

For issues or questions, contact the system administrator.

**First Login**: You will be prompted to change your password.

EOF
    
    # Set ownership
    chown "$username":"$username" "$readme"
    
    log_info "README created: $readme"
}

# Add user to relevant groups
add_to_groups() {
    local username="$1"
    
    log_info "Adding $username to supplementary groups"
    
    # Add to docker group if it exists (for Docker access)
    if getent group docker > /dev/null 2>&1; then
        usermod -aG docker "$username"
        log_info "Added $username to docker group"
    fi
    
    # Add to wheel group if it exists (for potential sudo access - commented out by default)
    # Uncomment if users need sudo access
    # if getent group wheel > /dev/null 2>&1; then
    #     usermod -aG wheel "$username"
    #     log_info "Added $username to wheel group"
    # fi
}

# Generate summary report
generate_summary() {
    local username="$1"
    local first_name=$(get_first_name "$username")
    local home_dir=$(eval echo ~"$username")
    local workspace_dir="${SCRATCH_ROOT}/${username}"
    
    cat << EOF

========================================
User Provisioning Summary: $username
========================================
First Name:        $first_name
Home Directory:    $home_dir
Workspace:         $workspace_dir
SSH Keys:          ${home_dir}/.ssh/id_rsa
Bin Directory:     ${home_dir}/bin
Code Tunnel:       pw_${first_name}
Default Password:  ChangeMe123! (must change on first login)

Quick Commands:
  - SSH: ssh $username@localhost
  - Work: (as $username) work
  - Tunnel: (as $username) code.sh

Next Steps:
  1. User should change password on first login
  2. User should verify SSH keys: ssh-keygen -lf ~/.ssh/id_rsa.pub
  3. User should start VS Code tunnel: code.sh
  4. User should read workspace README: cat $workspace_dir/README.md

========================================

EOF
}

# Main provisioning function
provision_user() {
    local username="$1"
    
    echo ""
    log_info "=========================================="
    log_info "Provisioning user: $username"
    log_info "=========================================="
    
    # Execute provisioning steps
    create_user "$username"
    setup_ssh "$username"
    create_scratch_space "$username"
    setup_bin_directory "$username"
    setup_bash_environment "$username"
    create_workspace_readme "$username"
    add_to_groups "$username"
    
    # Generate summary
    generate_summary "$username"
    
    log_info "User $username provisioned successfully!"
}

# Main script execution
main() {
    echo "=========================================="
    echo "  MCP RAG User Provisioning Script"
    echo "  $(date)"
    echo "=========================================="
    echo ""
    
    # Check root privileges
    check_root
    
    # Verify scratch space root exists or create it
    log_info "Verifying scratch space root: $SCRATCH_ROOT"
    mkdir -p "$SCRATCH_ROOT"
    chmod 755 "$SCRATCH_ROOT"
    
    # Provision each user
    for username in "${USERS[@]}"; do
        provision_user "$username"
    done
    
    echo ""
    echo "=========================================="
    echo "  Provisioning Complete!"
    echo "=========================================="
    echo ""
    echo "Users provisioned: ${#USERS[@]}"
    for username in "${USERS[@]}"; do
        echo "  - $username"
    done
    echo ""
    echo "All users have been created with:"
    echo "  - Home directory with SSH keys"
    echo "  - Scratch workspace in $SCRATCH_ROOT"
    echo "  - VS Code tunnel script (code.sh)"
    echo "  - 'work' alias for quick navigation"
    echo "  - Default password: ChangeMe123! (must change on first login)"
    echo ""
    echo "To verify setup for a user:"
    echo "  sudo -u USERNAME -i"
    echo "  work"
    echo "  ls -la"
    echo ""
}

# Run main function
main "$@"
