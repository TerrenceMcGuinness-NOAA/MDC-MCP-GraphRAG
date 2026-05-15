#!/bin/bash
################################################################################
# provision.sh — MDC MCP RAG AWS Provisioning Orchestrator
# Version: 1.0.0
#
# Usage:
#   sudo ./provision.sh              # Run all scripts
#   sudo ./provision.sh --skip 03    # Skip script 03
#   sudo ./provision.sh --only 07    # Only run script 07
#   sudo ./provision.sh --list       # List scripts and exit
################################################################################
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

declare -a SCRIPTS=(
  "00-users.sh:User Accounts"
  "01-directories.sh:Directory Structure"
  "02-system-deps.sh:System Dependencies"
  "03-nodejs.sh:Node.js + CDK"
  "04-python.sh:Python + pip + uvx"
  "05-aws-cli-config.sh:AWS CLI Configuration"
  "06-kiro-cli-fix.sh:Kiro CLI Shell Hook Fix"
  "07-mcp-server-deps.sh:MCP Server Dependencies"
  "08-verification.sh:Verification"
)

SKIP_SCRIPTS=()
ONLY_SCRIPTS=()
LIST_ONLY=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --skip) shift; SKIP_SCRIPTS+=("$1"); shift ;;
    --only) shift; ONLY_SCRIPTS+=("$1"); shift ;;
    --list) LIST_ONLY=true; shift ;;
    --help|-h)
      echo "Usage: sudo $0 [--skip NN] [--only NN] [--list]"
      exit 0 ;;
    *) log_error "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ "${LIST_ONLY}" == true ]]; then
  echo "Available scripts:"
  for entry in "${SCRIPTS[@]}"; do
    printf "  %s  %s\n" "${entry%%:*}" "${entry#*:}"
  done
  exit 0
fi

require_root
clear_status_file

log_section "MDC MCP RAG AWS Provisioning v${PROVISION_VERSION}"
echo "  PERSISTENT_ROOT: ${PERSISTENT_ROOT}"
echo "  MDC_REPO:        ${MDC_REPO}"
echo ""

FAILED_COUNT=0

for entry in "${SCRIPTS[@]}"; do
  script="${entry%%:*}"
  description="${entry#*:}"
  prefix="${script:0:2}"

  # --skip check
  for skip in "${SKIP_SCRIPTS[@]:-}"; do
    [[ "${prefix}" == "${skip}" ]] && { log_info "Skipping: ${script}"; record_result "${script}" "skipped" "user skip"; continue 2; }
  done

  # --only check
  if [[ ${#ONLY_SCRIPTS[@]} -gt 0 ]]; then
    found=false
    for only in "${ONLY_SCRIPTS[@]}"; do
      [[ "${prefix}" == "${only}" ]] && found=true && break
    done
    [[ "${found}" == false ]] && { record_result "${script}" "skipped" "not in --only"; continue; }
  fi

  run_subscript "${script}" "${description}" || ((FAILED_COUNT++)) || true
  echo ""
done

print_summary_report

echo ""
if [[ ${FAILED_COUNT} -eq 0 ]]; then
  log_success "Provisioning complete"
  echo "  Next: source ${SETUP_AWS}/mcp-env-aws.sh"
  exit 0
else
  log_error "Provisioning completed with ${FAILED_COUNT} failure(s)"
  exit 1
fi
