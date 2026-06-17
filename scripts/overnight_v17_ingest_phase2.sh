#!/usr/bin/env bash
#
# overnight_v17_ingest_phase2.sh
#
# Phase 2 only: run the three v8 ingestion scripts for gw_v17.
# Assumes EFS is already mounted and submodules are initialized
# (Phase 1 completed successfully despite the waitpid error).
#
# Usage:
#   nohup sudo bash scripts/overnight_v17_ingest_phase2.sh \
#     > logs/overnight_v17_phase2_$(date +%Y%m%dT%H%M%S).log 2>&1 &

set -uo pipefail  # no -e: continue on per-script failure

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${SCRIPT_DIR}"

log() { echo "[$(date +%Y-%m-%dT%H:%M:%S)] $*"; }

STAGING_MNT="${STAGING_MNT:-/mnt/efs-staging}"

# Ensure EFS is mounted
if ! mountpoint -q "${STAGING_MNT}"; then
  log "Mounting EFS"
  mkdir -p "${STAGING_MNT}"
  mount -t efs -o tls fs-032d52e4677000758:/ "${STAGING_MNT}"
fi

# Verify sorc/ is populated
SORC_COUNT=$(find "${STAGING_MNT}/supported_repos/global-workflow/dev-v17/sorc" -type f 2>/dev/null | wc -l)
log "sorc/ file count: ${SORC_COUNT}"
if [[ "${SORC_COUNT}" -lt 1000 ]]; then
  log "[ERROR] sorc/ has fewer than 1000 files — submodules may not be initialized"
  exit 1
fi

export DB_BACKEND=aws
export OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com
export NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182
export AWS_REGION=us-east-1
export MCP_EMBEDDING_PROFILE=titan1024
export MCP_WORKTREE_ROOT_OVERRIDE="${STAGING_MNT}/supported_repos/global-workflow"

log "=== PHASE 2: v17 full-branch ingestion ==="
log "Worktree root: ${MCP_WORKTREE_ROOT_OVERRIDE}/dev-v17"
log "Total files available: $(find ${MCP_WORKTREE_ROOT_OVERRIDE}/dev-v17 -type f 2>/dev/null | wc -l)"

log "--- [1/3] Documentation ingestion ---"
START=$(date +%s)
sudo -u ec2-user -E python3.12 mcp_server_python/scripts/ingest_documentation_v8.py \
  --tenant gw_v17 --mode full --delay 0.5 2>&1
DOC_RC=$?
ELAPSED=$(( $(date +%s) - START ))
log "Documentation: exit=${DOC_RC} elapsed=${ELAPSED}s"

log "--- [2/3] Code ingestion ---"
START=$(date +%s)
sudo -u ec2-user -E python3.12 mcp_server_python/scripts/ingest_code_v8.py \
  --tenant gw_v17 --mode full --delay 0.5 2>&1
CODE_RC=$?
ELAPSED=$(( $(date +%s) - START ))
log "Code: exit=${CODE_RC} elapsed=${ELAPSED}s"

log "--- [3/3] J-Job ingestion ---"
START=$(date +%s)
sudo -u ec2-user -E python3.12 mcp_server_python/scripts/ingest_jjobs_v8.py \
  --tenant gw_v17 --mode full --delay 0.3 2>&1
JJOB_RC=$?
ELAPSED=$(( $(date +%s) - START ))
log "J-Jobs: exit=${JJOB_RC} elapsed=${ELAPSED}s"

log "=== RESULTS ==="
log "Documentation: exit ${DOC_RC}"
log "Code:          exit ${CODE_RC}"
log "J-Jobs:        exit ${JJOB_RC}"

log "Ingestion reports:"
ls -la mcp_server_python/scripts/ingestion_reports/gw_v17_* 2>/dev/null || log "(none)"

# Print report summaries
for f in mcp_server_python/scripts/ingestion_reports/gw_v17_*; do
  if [[ -f "$f" ]]; then
    log "Report: $f"
    python3.12 -c "
import json, sys
r = json.load(open(sys.argv[1]))
print(f'  files={r[\"total_files_processed\"]} docs_created={sum(r[\"documents_created\"].values()) if isinstance(r[\"documents_created\"], dict) else r[\"documents_created\"]} deduped={r[\"documents_deduped\"]} embeddings={r[\"embedding_calls\"][\"bedrock_invocations\"]} efficiency={r[\"dedupe_efficiency_pct\"]}%')
print(f'  drift_flags={r.get(\"comparison_to_phase_54_baseline\", {}).get(\"drift_flags\", [])}')
" "$f" 2>&1 || true
  fi
done

# Unmount
log "Unmounting EFS"
umount "${STAGING_MNT}" 2>/dev/null || true

log "=== OVERNIGHT PHASE 2 COMPLETE ==="
log "Exit codes: doc=${DOC_RC} code=${CODE_RC} jjob=${JJOB_RC}"

if [[ ${DOC_RC} -eq 0 && ${CODE_RC} -eq 0 && ${JJOB_RC} -eq 0 ]]; then
  log "ALL PASSED. Ready for image rebuild + Phase C verification."
  exit 0
else
  log "ONE OR MORE SCRIPTS FAILED. Check logs above for [ERROR] lines."
  exit 1
fi
