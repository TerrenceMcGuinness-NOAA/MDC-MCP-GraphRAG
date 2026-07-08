#!/usr/bin/env bash
#
# run_mcp_stdio.sh — Native (no-gateway) launcher for the Python MCP/RAG server.
#
# Bridges the Spack module system into the stdio transport so an MCP client
# (e.g. VS Code) can spawn the server directly and the tools get real
# filesystem write access — unlike the Docker MCP gateway, whose read-only
# sdd_framework mount blocks SDD session-state writes.
#
# Backend: legacy (local Neo4j + ChromaDB on Parallel Works).
# Transport: stdio. Logs go to stderr; JSON-RPC speaks on stdout.
#
# Invoked by .vscode/mcp.json (server "eib-mcp-rag-python-local"). Env overrides
# are honored, so the same script works for ad-hoc CLI runs:
#   bash mcp_server_python/scripts/run_mcp_stdio.sh
#
set -euo pipefail

# ── Repo + server roots (resolved relative to this script) ─────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"          # mcp_server_python/
REPO_ROOT="$(cd "${SERVER_ROOT}/.." && pwd)"           # repo root

# ── Spack environment + modules (SPOT: same set verified for legacy boot) ──
SPACK_SETUP="${SPACK_SETUP:-/mcp_rag_eib/spack/share/spack/setup-env.sh}"
# shellcheck disable=SC1090
source "${SPACK_SETUP}"
module load python/3.11.14 py-pip py-neo4j py-httpx py-pydantic >/dev/null 2>&1

# ── Local secrets (gitignored, outside the repo) ───────────────────────────
# Keeps GITHUB_TOKEN (and any other secret) out of mcp.json and shell history.
# Create ~/.config/eib-mcp/secrets.env (chmod 600) with e.g.:
#   export GITHUB_TOKEN=ghp_xxx
# Override the path with MCP_SECRETS_FILE.
MCP_SECRETS_FILE="${MCP_SECRETS_FILE:-${HOME}/.config/eib-mcp/secrets.env}"
if [[ -f "${MCP_SECRETS_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${MCP_SECRETS_FILE}"
fi

# ── FastMCP startup banner (stderr noise; VS Code renders it as warnings) ──
# Suppressed in code via show_banner=False; this env is a backup for CLI runs.
export FASTMCP_SHOW_SERVER_BANNER="${FASTMCP_SHOW_SERVER_BANNER:-false}"

# ── Backend + connection config (cots: Neo4j + ChromaDB) ──────────────────
export DB_BACKEND="${DB_BACKEND:-cots}"
export MCP_EMBEDDING_PROFILE="${MCP_EMBEDDING_PROFILE:-mpnet768}"
export NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
export NEO4J_USER="${NEO4J_USER:-neo4j}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-gfsworkflow2025}"
export CHROMADB_HOST="${CHROMADB_HOST:-localhost}"
export CHROMADB_PORT="${CHROMADB_PORT:-8080}"

# ── Filesystem-tool roots (absolute — cwd is the server dir) ───────────────
# SDD state + workflow specs MUST point at the REPO-level sdd_framework, else
# cwd-relative resolution would land under mcp_server_python/ (split-brain) and
# lose the canonical session history and phase specs.
export SDD_STATE_DIR="${SDD_STATE_DIR:-${REPO_ROOT}/sdd_framework/execution_state}"
export SDD_WORKFLOWS_DIR="${SDD_WORKFLOWS_DIR:-${REPO_ROOT}/sdd_framework/workflows}"
export MCP_TENANT_CATALOG_PATH="${MCP_TENANT_CATALOG_PATH:-${SERVER_ROOT}/src/config/tenants.yaml}"
export MCP_WORKFLOW_ROOT="${MCP_WORKFLOW_ROOT:-${REPO_ROOT}/supported_repos/global-workflow_develop}"

# ── Per-tenant workflow mount base (Phase 61) ──────────────────────────────
# The tenant catalog resolves each tenant's filesystem root as
# ${MCP_WORKFLOW_MOUNT}/<workflow_subdir>. Default base /mnt/workflow is the
# AgentCore EFS mount, absent on Parallel Works — point it at the local
# symlink farm built by setup_pw_workflow_mount.sh.
export MCP_WORKFLOW_MOUNT="${MCP_WORKFLOW_MOUNT:-${REPO_ROOT}/.pw_workflow_mount}"

cd "${SERVER_ROOT}"
exec python3 -m src.mcp_server --transport stdio "$@"
