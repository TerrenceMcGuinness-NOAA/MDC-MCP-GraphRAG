#!/bin/bash
################################################################################
# mcp-env-aws.sh — MDC MCP RAG AWS Environment Configuration
# Version: 1.0.0
#
# Replaces legacy mcp-env.sh for AWS EC2 deployments.
# Usage: source /path/to/SETUP_AWS/mcp-env-aws.sh
################################################################################

# Core paths
export PERSISTENT_ROOT="${PERSISTENT_ROOT:-/mdc-mcp-rag}"
export MDC_REPO="${MDC_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export SETUP_AWS="${MDC_REPO}/SETUP_AWS"
export MCP_ROOT="${MDC_REPO}/mcp_server_node"
export GW_REPO="${MDC_REPO}/supported_repos/global-workflow"

# Data directories
export DATA_ROOT="${PERSISTENT_ROOT}/data"
export ETC_ROOT="${PERSISTENT_ROOT}/etc"
export CACHE_ROOT="${PERSISTENT_ROOT}/cache"

# Cache directories
export HF_HOME="${CACHE_ROOT}/huggingface"
export TRANSFORMERS_CACHE="${HF_HOME}"
export NPM_CONFIG_CACHE="${CACHE_ROOT}/npm"
export PIP_CACHE_DIR="${CACHE_ROOT}/pip"

# AWS configuration
export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="${AWS_REGION}"
export AWS_OUTPUT_FORMAT="${AWS_OUTPUT_FORMAT:-json}"

# Database backend (legacy | aws)
export DB_BACKEND="${DB_BACKEND:-legacy}"

# Node.js
export NODE_ENV="${NODE_ENV:-production}"
export NVM_DIR="${NVM_DIR:-${HOME}/.nvm}"

# Load nvm if available
if [ -s "${NVM_DIR}/nvm.sh" ]; then
  # shellcheck disable=SC1091
  source "${NVM_DIR}/nvm.sh" --no-use 2>/dev/null || true
fi

[[ "${1:-}" == "--quiet" ]] || echo "[OK] mcp-env-aws.sh loaded (PERSISTENT_ROOT=${PERSISTENT_ROOT})"
