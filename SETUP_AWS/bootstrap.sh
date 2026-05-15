#!/bin/bash
################################################################################
# bootstrap.sh — MDC MCP RAG AWS Bootstrap Entry Point
# Version: 1.0.0
#
# Usage: sudo bash bootstrap.sh
# Idempotent: safe to re-run on an already-provisioned instance.
################################################################################
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source environment config
source "${SCRIPT_DIR}/mcp-env-aws.sh" --quiet

echo "=========================================="
echo "MDC MCP RAG AWS Bootstrap"
echo "=========================================="
echo "PERSISTENT_ROOT: ${PERSISTENT_ROOT}"
echo "MDC_REPO:        ${MDC_REPO}"
echo "MCP_ROOT:        ${MCP_ROOT}"
echo "AWS_REGION:      ${AWS_REGION}"
echo "=========================================="

# Delegate to modular provisioning orchestrator
exec sudo bash "${SCRIPT_DIR}/provisioning/provision.sh" "$@"
