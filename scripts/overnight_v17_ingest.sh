#!/usr/bin/env bash
#
# overnight_v17_ingest.sh
#
# Unattended overnight run: populate EFS worktrees (with submodule init)
# then run the three v8 ingestion scripts for gw_v17.
#
# Usage (detached, survives terminal disconnect):
#   nohup sudo bash scripts/overnight_v17_ingest.sh \
#     > logs/overnight_v17_$(date +%Y%m%dT%H%M%S).log 2>&1 &
#
# Monitor:
#   tail -f logs/overnight_v17_*.log
#
# The script is idempotent: re-running picks up where it left off
# (worktrees that exist get fetch+merge, submodules that are init'd
# get updated, ingestion overwrites documents by SHA-keyed _id).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${SCRIPT_DIR}"

LOG_PREFIX="[$(date +%Y-%m-%dT%H:%M:%S)]"
log() { echo "${LOG_PREFIX} $*"; }

# ── Phase 1: Populate EFS worktrees + submodules ──────────────────────────
log "=== PHASE 1: EFS populate + submodule init ==="

EFS_FS_ID="${EFS_FS_ID:-fs-032d52e4677000758}"
STAGING_MNT="${STAGING_MNT:-/mnt/efs-staging}"
GW_REMOTE="${GW_REMOTE:-https://github.com/NOAA-EMC/global-workflow.git}"
TENANTS_YAML="mcp_server_python/src/config/tenants.yaml"
GIT_OPTS=(-c "safe.directory=*")

# Mount EFS
mkdir -p "${STAGING_MNT}"
if mountpoint -q "${STAGING_MNT}"; then
  log "EFS already mounted at ${STAGING_MNT}"
else
  log "Mounting EFS ${EFS_FS_ID} at ${STAGING_MNT}"
  mount -t efs -o tls "${EFS_FS_ID}:/" "${STAGING_MNT}"
fi

# Ensure bare repo
if [[ -d "${STAGING_MNT}/.git" ]]; then
  log "Bare repo present — fetching latest"
  git "${GIT_OPTS[@]}" -C "${STAGING_MNT}/.git" fetch --all
else
  log "Cloning bare repo (this is slow, ~10-30 min)"
  git clone --bare "${GW_REMOTE}" "${STAGING_MNT}/.git"
fi

# Ensure AP root
mkdir -p "${STAGING_MNT}/supported_repos/global-workflow"
chown 1000:1000 "${STAGING_MNT}/supported_repos/global-workflow"

# Process only gw_v17 for tonight (the other tenants can wait)
# To do all tenants, remove the grep filter below.
TENANT_ID="gw_v17"
SUBDIR="dev-v17"
BRANCH="dev/gfs.v17"

TARGET="${STAGING_MNT}/supported_repos/global-workflow/${SUBDIR}"

log "Processing tenant=${TENANT_ID} subdir=${SUBDIR} branch=${BRANCH}"

if git "${GIT_OPTS[@]}" -C "${STAGING_MNT}/.git" worktree list --porcelain \
     | grep -q "^worktree ${TARGET}$"; then
  log "Worktree exists — fetch + merge --ff-only"
  git "${GIT_OPTS[@]}" -C "${TARGET}" fetch origin "${BRANCH}"
  git "${GIT_OPTS[@]}" -C "${TARGET}" merge --ff-only FETCH_HEAD || log "Already up to date"
else
  log "Creating worktree at ${TARGET}"
  git "${GIT_OPTS[@]}" -C "${STAGING_MNT}/.git" worktree add "${TARGET}" "${BRANCH}"
fi

log "Initializing submodules (--depth 1, recursive) — this is the long step"
log "Expected: 20-60 minutes depending on EFS throughput"
git "${GIT_OPTS[@]}" -C "${TARGET}" submodule update --init --recursive --depth 1

chown -R 1000:1000 "${TARGET}"

# Verify
if [[ -f "${TARGET}/dev/jobs/JGDAS_ATMOS_ANALYSIS_WDQMS" ]]; then
  log "[OK] WDQMS J-Job present"
else
  log "[WARN] WDQMS J-Job not found — branch may differ"
fi

# Count files to confirm submodules populated
SORC_COUNT=$(find "${TARGET}/sorc" -type f 2>/dev/null | wc -l)
log "sorc/ file count: ${SORC_COUNT} (should be >1000 if submodules init'd)"

log "=== PHASE 1 COMPLETE ==="

# ── Phase 2: Run v8 ingestion scripts ────────────────────────────────────
log "=== PHASE 2: v17 full-branch ingestion ==="

export DB_BACKEND=aws
export OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com
export NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182
export AWS_REGION=us-east-1
export MCP_EMBEDDING_PROFILE=titan1024
export MCP_WORKTREE_ROOT_OVERRIDE="${STAGING_MNT}/supported_repos/global-workflow"

log "--- Documentation ingestion ---"
python3.12 mcp_server_python/scripts/ingest_documentation_v8.py \
  --tenant gw_v17 --mode full --delay 0.3 2>&1 || {
  log "[ERROR] Documentation ingestion failed (exit $?)"
  log "Continuing to next script..."
}

log "--- Code ingestion ---"
python3.12 mcp_server_python/scripts/ingest_code_v8.py \
  --tenant gw_v17 --mode full --delay 0.3 2>&1 || {
  log "[ERROR] Code ingestion failed (exit $?)"
  log "Continuing to next script..."
}

log "--- J-Job ingestion ---"
python3.12 mcp_server_python/scripts/ingest_jjobs_v8.py \
  --tenant gw_v17 --mode full --delay 0.3 2>&1 || {
  log "[ERROR] J-Job ingestion failed (exit $?)"
}

log "=== PHASE 2 COMPLETE ==="

# ── Phase 3: Summary ─────────────────────────────────────────────────────
log "=== SUMMARY ==="
log "Ingestion reports:"
ls -la mcp_server_python/scripts/ingestion_reports/gw_v17_* 2>/dev/null || log "(no reports found)"

# Unmount EFS
log "Unmounting EFS"
umount "${STAGING_MNT}" || log "[WARN] umount failed (may already be unmounted)"

log "=== OVERNIGHT RUN COMPLETE ==="
log "Next steps: rebuild docker image, update runtime, run Phase C verification"
