#!/bin/bash
################################################################################
# 08-verification.sh — Validate all components, report status table
# Idempotent: read-only checks only
################################################################################
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

log_section "Installation Verification"

OWNER=$(get_actual_user)
NVM_DIR_TARGET="$(eval echo "~${OWNER}")/.nvm"
PASS=0
FAIL=0

check() {
  local label="$1" cmd="$2"
  if eval "${cmd}" &>/dev/null; then
    echo -e "  ${GREEN}[OK]${NC}    ${label}"
    ((PASS++))
  else
    echo -e "  ${RED}[FAIL]${NC}  ${label}"
    ((FAIL++))
  fi
}

echo ""
echo "Component Status:"

# Node.js
check "Node.js (via nvm)" \
  "sudo -u \"${OWNER}\" bash -c 'export NVM_DIR=\"${NVM_DIR_TARGET}\"; [[ -s \"\${NVM_DIR}/nvm.sh\" ]] && source \"\${NVM_DIR}/nvm.sh\"; node --version'"

# npm
check "npm" \
  "sudo -u \"${OWNER}\" bash -c 'export NVM_DIR=\"${NVM_DIR_TARGET}\"; [[ -s \"\${NVM_DIR}/nvm.sh\" ]] && source \"\${NVM_DIR}/nvm.sh\"; npm --version'"

# AWS CDK
check "AWS CDK CLI" \
  "sudo -u \"${OWNER}\" bash -c 'export NVM_DIR=\"${NVM_DIR_TARGET}\"; [[ -s \"\${NVM_DIR}/nvm.sh\" ]] && source \"\${NVM_DIR}/nvm.sh\"; cdk --version'"

# Python 3.11+
check "Python 3.11+" \
  "python3 -c 'import sys; assert sys.version_info >= (3,11)'"

# pip
check "pip" "python3 -m pip --version"

# uvx
check "uvx" "sudo -u \"${OWNER}\" bash -c 'command -v uvx'"

# AWS CLI
check "AWS CLI" "aws --version"

# AWS region configured
check "AWS region configured" \
  "sudo -u \"${OWNER}\" bash -c 'aws configure get default.region | grep -q .'"

# Persistent root
check "Persistent root ${PERSISTENT_ROOT}" "[[ -d \"${PERSISTENT_ROOT}\" ]]"

# MCP server node_modules
check "MCP server node_modules" "[[ -d \"${MCP_ROOT}/node_modules\" ]]"

# CDK stacks synthesized
check "CDK cdk.out exists" "[[ -f \"${MDC_REPO}/infrastructure/cdk/cdk.out/cdk.out\" ]]"

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
echo ""

if [[ "${FAIL}" -gt 0 ]]; then
  log_warning "Some checks failed — review above and re-run failed provisioning scripts"
  exit 1
else
  log_success "All checks passed"
fi
