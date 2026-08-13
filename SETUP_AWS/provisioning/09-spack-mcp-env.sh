#!/bin/bash
################################################################################
# 09-spack-mcp-env.sh — Provision (or re-provision) the shared Spack mcp-venv
#
# Run as ec2-user (NOT root). Creates or rebuilds:
#   /mnt/mdc-mcp-rag/spack/var/mcp-venv
#
# All MCP Python dependencies (boto3, fastmcp, opensearch-py, strands-agents,
# opentelemetry, etc.) are pinned to the versions in pyproject.toml [project.dependencies].
# The venv is group=developers, g+rX so all provisioned developer accounts can
# activate it via source /mnt/mdc-mcp-rag/spack/mcp-env-activate.sh.
#
# Usage:
#   bash SETUP_AWS/provisioning/09-spack-mcp-env.sh            # create / validate
#   bash SETUP_AWS/provisioning/09-spack-mcp-env.sh --rebuild  # wipe and recreate
#   bash SETUP_AWS/provisioning/09-spack-mcp-env.sh --update   # pip install -U only
#
# Idempotent unless --rebuild is passed.
################################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SPACK_ROOT="/mnt/mdc-mcp-rag/spack"
VENV_ROOT="${SPACK_ROOT}/var/mcp-venv"
ACTIVATE_SCRIPT="${SPACK_ROOT}/mcp-env-activate.sh"
PYPROJECT="${REPO_ROOT}/mcp_server_python/pyproject.toml"

# Must NOT be run as root (venv ownership must be ec2-user)
if [[ $EUID -eq 0 ]]; then
  echo "[ERROR] Run as ec2-user, not root." >&2
  exit 1
fi

REBUILD=false
UPDATE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild) REBUILD=true; shift ;;
    --update)  UPDATE=true;  shift ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

log() { echo "[$(date -u +%H:%M:%SZ)] $*"; }

# ── 1. Validate Spack installation ────────────────────────────────────────────
if [[ ! -f "${SPACK_ROOT}/share/spack/setup-env.sh" ]]; then
  echo "[ERROR] Spack not found at ${SPACK_ROOT}" >&2
  echo "        Clone spack first: git clone --depth=1 --branch releases/v0.23 https://github.com/spack/spack.git ${SPACK_ROOT}" >&2
  exit 1
fi
log "Spack found: $(${SPACK_ROOT}/bin/spack --version)"

# ── 2. Verify Python 3.12 ─────────────────────────────────────────────────────
if ! command -v python3.12 &>/dev/null; then
  echo "[ERROR] python3.12 not found. Run 04-python.sh first (as root)." >&2
  exit 1
fi
log "Python: $(python3.12 --version)"

# ── 3. Rebuild or reuse venv ─────────────────────────────────────────────────
if [[ "${REBUILD}" == "true" && -d "${VENV_ROOT}" ]]; then
  log "Removing existing venv for rebuild..."
  rm -rf "${VENV_ROOT}"
fi

if [[ ! -d "${VENV_ROOT}" ]]; then
  log "Creating venv at ${VENV_ROOT}..."
  python3.12 -m venv "${VENV_ROOT}" --prompt "mcp-env"
  log "Venv created"
else
  log "Venv exists at ${VENV_ROOT} — skipping create (use --rebuild to wipe)"
fi

# ── 4. Upgrade pip inside venv ────────────────────────────────────────────────
log "Upgrading pip..."
"${VENV_ROOT}/bin/pip" install --upgrade pip --quiet

# ── 5. Install pinned MCP deps ────────────────────────────────────────────────
# Pinned to exact versions from mcp_server_python/pyproject.toml [project.dependencies].
# Core AWS deps only — NOT the [cots] extras (chromadb, neo4j, sentence-transformers).
# Update this list in lock-step with pyproject.toml when bumping versions.
log "Installing MCP server dependencies..."
"${VENV_ROOT}/bin/pip" install \
  "fastmcp==3.2.4" \
  "opensearch-py==3.2.0" \
  "boto3==1.42.70" \
  "botocore==1.42.70" \
  "urllib3==2.6.3" \
  "httpx==0.28.1" \
  "strands-agents==1.39.0" \
  "strands-agents-tools==0.5.2" \
  "opentelemetry-api==1.41.1" \
  "opentelemetry-sdk==1.41.1" \
  2>&1 | grep -E "(Successfully installed|already satisfied|ERROR)" || true

# ── 6. Set group permissions ──────────────────────────────────────────────────
log "Setting group permissions (developers)..."
sudo chgrp -R developers "${VENV_ROOT}"
sudo chmod -R g+rX "${VENV_ROOT}"
sudo chmod g+rx "${VENV_ROOT}/bin/"*

# ── 7. Verify key imports ─────────────────────────────────────────────────────
log "Verifying imports..."
"${VENV_ROOT}/bin/python3" -c "
import boto3, fastmcp, opensearchpy, httpx
from opentelemetry import trace
print('boto3:', boto3.__version__)
print('fastmcp:', fastmcp.__version__)
print('opensearch-py:', opensearchpy.__version__)
print('httpx:', httpx.__version__)
print('otel/trace: ok')
" || { echo "[ERROR] Import verification failed" >&2; exit 1; }

log "[OK] mcp-venv ready at ${VENV_ROOT}"
log "[OK] Activate with: source ${ACTIVATE_SCRIPT}"
