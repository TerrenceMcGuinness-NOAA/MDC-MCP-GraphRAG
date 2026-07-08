#!/usr/bin/env bash
#
# setup_pw_workflow_mount.sh — Parallel Works workflow-mount bootstrap (Phase 61).
#
# The tenant catalog resolves each tenant's filesystem root as
# ``${MCP_WORKFLOW_MOUNT}/<workflow_subdir>`` (default base /mnt/workflow, the
# AgentCore EFS mount). Parallel Works has no EFS, so this script builds a
# user-writable symlink farm whose children match the catalog subdir names and
# point at the local ``supported_repos/`` checkouts (whose directory names
# differ from the subdirs).
#
# Idempotent, no root required, never writes under /mnt. Re-running is a no-op.
# Missing checkout targets warn (non-fatal) so a partial clone still bootstraps.
#
# Usage:
#   bash mcp_server_python/scripts/setup_pw_workflow_mount.sh
#   MCP_WORKFLOW_MOUNT=/custom/base bash .../setup_pw_workflow_mount.sh
#
set -euo pipefail

# ── Repo root (resolved relative to this script) ───────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"          # mcp_server_python/
REPO_ROOT="$(cd "${SERVER_ROOT}/.." && pwd)"           # repo root

# ── Mount base (SPOT default mirrors run_mcp_stdio.sh) ─────────────────────
MOUNT_BASE="${MCP_WORKFLOW_MOUNT:-${REPO_ROOT}/.pw_workflow_mount}"
REPOS_DIR="${REPO_ROOT}/supported_repos"

# ── SPOT mapping: catalog workflow_subdir -> supported_repos checkout name ──
# Keep in sync with mcp_server_python/src/config/tenants.yaml.
declare -A SUBDIR_TO_CHECKOUT=(
  [develop]="global-workflow_develop"
  [dev-sfs]="global-workflow_dev-sfs"
  [dev-jedi-gfs]="global-workflow_dev-jedi-gfs"
  [dev-v17]="global-workflow_dev-gfs.v17"
  [gefs-v12]="global-workflow_release-gefs_v12"
)

echo "[INFO] workflow mount base: ${MOUNT_BASE}"
mkdir -p "${MOUNT_BASE}"

linked=0
warned=0
for subdir in "${!SUBDIR_TO_CHECKOUT[@]}"; do
  checkout="${SUBDIR_TO_CHECKOUT[${subdir}]}"
  target="${REPOS_DIR}/${checkout}"
  link="${MOUNT_BASE}/${subdir}"

  if [[ ! -d "${target}" ]]; then
    echo "[WARN] missing checkout for subdir '${subdir}': ${target}"
    warned=$((warned + 1))
    continue
  fi

  # Relative link target (computed from the link's own directory, MOUNT_BASE).
  # This resolves both on the host AND inside the container, where
  # .pw_workflow_mount and supported_repos are sibling mounts under /app.
  # Host-absolute targets dangle inside the container (see R5.4).
  rel_target="$(realpath --relative-to="${MOUNT_BASE}" "${target}")"

  # ln -sfn: idempotent, replaces an existing symlink without nesting.
  ln -sfn "${rel_target}" "${link}"
  echo "[OK] ${subdir} -> ${rel_target}"
  linked=$((linked + 1))
done

echo "[INFO] linked=${linked} warned=${warned}"
if [[ "${linked}" -eq 0 ]]; then
  echo "[ERROR] no workflow checkouts linked; verify ${REPOS_DIR}" >&2
  exit 1
fi
