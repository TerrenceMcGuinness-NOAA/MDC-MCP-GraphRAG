#!/bin/bash
################################################################################
# 00-users.sh - Provision Linux user accounts for MCP RAG environment
# Part of modular provisioning system v4.0.0
#
# This script is intentionally idempotent: it skips users that already exist.
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/user_config.sh"

log_subsection "Provisioning Linux User Accounts"

# shellcheck disable=SC1091
source "${SETUP_DIR}/bin/provision_users.sh"

for username in "${PROVISION_USERS[@]}"; do
  provision_user "$username"
done

log_success "User provisioning step complete"
