#!/usr/bin/env bash
#
# remediate_v17_reingest.sh
#
# Robust, idempotent, resumable overnight remediation for the gw_v17 tenant:
# clean up the BAD data from the collection-blind-dedupe run, then re-ingest
# with the FIXED pipeline (collection-scoped dedupe + unconditional graph write).
#
# This is the operator-run execution of Task 12 of
#   .kiro/specs/ingest-dedupe-and-graph-fix/
# and depends on the rollback CLI fix from
#   .kiro/specs/rollback-cli-real-adapters/
#
# ──────────────────────────────────────────────────────────────────────────
# SAFETY: this script PERFORMS DESTRUCTIVE AWS WRITES (deletes gw_v17 indices,
# Neptune labels, and registry rows) followed by hours of re-ingestion.
# It refuses to run unless CONFIRM_DESTRUCTIVE=yes is set in the environment.
#
# Usage (detached, survives disconnect):
#   CONFIRM_DESTRUCTIVE=yes nohup sudo -E bash scripts/remediate_v17_reingest.sh \
#     > logs/remediate_v17_$(date +%Y%m%dT%H%M%S).log 2>&1 &
#
# Monitor:    tail -f logs/remediate_v17_*.log
# Resume:     just re-run the same command — completed phases are skipped.
# Force redo: rm -rf .remediation_state/v17  (CAREFUL — clears checkpoints)
# ──────────────────────────────────────────────────────────────────────────

set -uo pipefail   # NOT -e: we handle per-phase failures explicitly

# ── Resolve repo root regardless of cwd ──────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${SCRIPT_DIR}"

# ── Config (override via env) ─────────────────────────────────────────────
TENANT="${TENANT:-gw_v17}"
SUBDIR="${SUBDIR:-dev-v17}"
EFS_FS_ID="${EFS_FS_ID:-fs-032d52e4677000758}"
STAGING_MNT="${STAGING_MNT:-/mnt/efs-staging}"
CATALOG="${CATALOG:-mcp_server_python/src/config/tenants.yaml}"
STATE_DIR="${STATE_DIR:-${SCRIPT_DIR}/.remediation_state/${TENANT}}"
DELAY="${DELAY:-0.5}"

export DB_BACKEND="${DB_BACKEND:-aws}"
export OPENSEARCH_ENDPOINT="${OPENSEARCH_ENDPOINT:-https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com}"
export NEPTUNE_ENDPOINT="${NEPTUNE_ENDPOINT:-https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export MCP_EMBEDDING_PROFILE="${MCP_EMBEDDING_PROFILE:-titan1024}"
export MCP_WORKTREE_ROOT_OVERRIDE="${STAGING_MNT}/supported_repos/global-workflow"

# Run python ingestion/query as the unprivileged user (it has opensearchpy);
# root does not. When the script itself runs under sudo, drop to ec2-user for
# the python steps via RUN_AS. When not under sudo, run directly.
RUN_AS_USER="${RUN_AS_USER:-ec2-user}"
if [[ "$(id -u)" -eq 0 ]]; then
  PyRUN=(sudo -u "${RUN_AS_USER}" -E python3.12)
else
  PyRUN=(python3.12)
fi

mkdir -p "${STATE_DIR}" logs

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
die() { log "FATAL: $*"; cleanup_mount; exit 1; }

# Phase checkpointing ──────────────────────────────────────────────────────
phase_done()  { [[ -f "${STATE_DIR}/$1.done" ]]; }
mark_done()   { date -u +%Y-%m-%dT%H:%M:%SZ > "${STATE_DIR}/$1.done"; }
mark_failed() { date -u +%Y-%m-%dT%H:%M:%SZ > "${STATE_DIR}/$1.failed"; }
clear_failed(){ rm -f "${STATE_DIR}/$1.failed"; }

# EFS mount lifecycle ───────────────────────────────────────────────────────
WE_MOUNTED=0
cleanup_mount() {
  if [[ "${WE_MOUNTED}" -eq 1 ]] && mountpoint -q "${STAGING_MNT}" 2>/dev/null; then
    log "Unmounting EFS (we mounted it)"
    umount "${STAGING_MNT}" 2>/dev/null || log "[WARN] umount failed"
  fi
}
trap cleanup_mount EXIT

ensure_mounted() {
  if mountpoint -q "${STAGING_MNT}"; then
    log "EFS already mounted at ${STAGING_MNT}"
  else
    log "Mounting EFS ${EFS_FS_ID} at ${STAGING_MNT}"
    mkdir -p "${STAGING_MNT}"
    mount -t efs -o tls "${EFS_FS_ID}:/" "${STAGING_MNT}" \
      || die "EFS mount failed — cannot proceed"
    WE_MOUNTED=1
  fi
}

# ── Pre-flight guards (fail fast, before any destructive action) ──────────
preflight() {
  log "=== PRE-FLIGHT ==="

  # 1. Destructive confirmation
  [[ "${CONFIRM_DESTRUCTIVE:-no}" == "yes" ]] \
    || die "refusing to run without CONFIRM_DESTRUCTIVE=yes (this DELETES ${TENANT} data)"

  # 2. The FIXED rollback CLI must be present (no None stub).
  if grep -q "vector_db = None" mcp_server_python/scripts/delete_tenant_indices.py \
       && ! grep -q "build_ingestion_data_access" mcp_server_python/scripts/delete_tenant_indices.py; then
    die "delete_tenant_indices.py still has the None-stub main() — rollback-cli-real-adapters fix not deployed"
  fi

  # 3. The FIXED ingestion must be present (collection-scoped dedupe).
  grep -q "COLLECTION_CODE" mcp_server_python/scripts/ingest_code_v8.py \
    || die "ingest_code_v8.py missing collection token — ingest-dedupe-and-graph-fix not deployed"

  # 4. opensearchpy importable for the python we will run as.
  "${PyRUN[@]}" -c "import opensearchpy" 2>/dev/null \
    || die "opensearchpy not importable for ${RUN_AS_USER} — fix the environment first"

  # 5. EFS + submodule tree present (graph ingestion needs sorc/).
  ensure_mounted
  local sorc="${STAGING_MNT}/supported_repos/global-workflow/${SUBDIR}/sorc"
  local n
  n="$(find "${sorc}" -type f 2>/dev/null | wc -l)"
  [[ "${n}" -ge 1000 ]] \
    || die "sorc/ has only ${n} files (<1000) — submodules not initialized; run populate_workflow_efs.sh first"
  log "[OK] pre-flight passed (sorc/ files=${n})"
}

# ── Phase 1: dry-run rollback (always, read-only, for the log record) ─────
phase_dryrun() {
  log "=== PHASE dryrun: rollback plan (read-only) ==="
  "${PyRUN[@]}" mcp_server_python/scripts/delete_tenant_indices.py \
      --tenant "${TENANT}" --clear-registry-entries --dry-run \
      --catalog "${CATALOG}" \
    || die "dry-run rollback failed — the rollback CLI is not operational; aborting BEFORE any destructive action"
  log "[OK] dry-run plan produced"
}

# ── Phase 2: destructive rollback (idempotent — only once) ────────────────
phase_rollback() {
  if phase_done rollback; then
    log "=== PHASE rollback: SKIP (already done $(cat "${STATE_DIR}/rollback.done")) ==="
    return 0
  fi
  log "=== PHASE rollback: DESTRUCTIVE delete of ${TENANT} data ==="
  if "${PyRUN[@]}" mcp_server_python/scripts/delete_tenant_indices.py \
       --tenant "${TENANT}" --clear-registry-entries \
       --catalog "${CATALOG}"; then
    mark_done rollback; clear_failed rollback
    log "[OK] rollback complete"
  else
    mark_failed rollback
    die "rollback FAILED — NOT proceeding to re-ingest (would ingest on top of partial state)"
  fi
}

# ── Re-ingest phases (idempotent — SHA registry + MERGE make re-runs safe) ─
ingest_phase() {
  local name="$1" script="$2"; shift 2
  if phase_done "ingest_${name}"; then
    log "=== PHASE ingest_${name}: SKIP (already done) ==="
    return 0
  fi
  log "=== PHASE ingest_${name}: ${script} ==="
  local start; start=$(date +%s)
  if "${PyRUN[@]}" "mcp_server_python/scripts/${script}" \
       --tenant "${TENANT}" --mode full --delay "${DELAY}" "$@"; then
    mark_done "ingest_${name}"; clear_failed "ingest_${name}"
    log "[OK] ingest_${name} complete (elapsed $(( $(date +%s) - start ))s)"
  else
    mark_failed "ingest_${name}"
    die "ingest_${name} FAILED (exit $?) — halting chain; fix and re-run to resume from here"
  fi
}

# ── Phase 6: empirical verification (prove the fix, don't trust exit codes) ─
phase_verify() {
  log "=== PHASE verify: empirical checks ==="
  "${PyRUN[@]}" - "${TENANT}" <<'PY'
import os, sys
sys.path.insert(0, "mcp_server_python")
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
import boto3

tenant = sys.argv[1]
region = os.environ["AWS_REGION"]
host = os.environ["OPENSEARCH_ENDPOINT"].replace("https://", "")
c = boto3.Session().get_credentials()
auth = AWS4Auth(c.access_key, c.secret_key, region, "es", session_token=c.token)
os_client = OpenSearch(hosts=[{"host": host, "port": 443}], http_auth=auth,
                       use_ssl=True, verify_certs=True,
                       connection_class=RequestsHttpConnection)

ok = True
def check(name, cond, detail):
    global ok
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}: {detail}")
    ok = ok and cond

# 1. Code index has REAL content (not all references) — Defect 1 fixed
code_idx = f"{tenant}_mdc-code-titan1024"
total = os_client.count(index=code_idx)["count"]
refs = os_client.count(index=code_idx, body={"query": {"term": {"metadata.is_reference": True}}})["count"]
real = total - refs
check("code real content", real > 0, f"{real} real / {refs} refs / {total} total")

# 2. Registry has per-collection keys (code: and jjobs: present) — re-key worked
reg = "mdc-content-sha-registry"
for coll in ("code", "jjobs", "documentation"):
    n = os_client.count(index=reg, body={"query": {"term": {"collection": coll}}})["count"]
    check(f"registry collection={coll}", n > 0, f"{n} entries")

print(f"\nVERIFY {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
PY
  local rc=$?
  if [[ ${rc} -eq 0 ]]; then
    log "[OK] OpenSearch verification passed"
  else
    log "[WARN] OpenSearch verification FAILED — inspect before declaring success"
  fi

  # Neptune node count — Defect 2 fixed (graph non-empty)
  log "Neptune GW_V17_ node check (manual follow-up if 0):"
  "${PyRUN[@]}" - <<'PY' || true
import os, sys
sys.path.insert(0, "mcp_server_python")
import asyncio
from src.config.environment import load_config
from src.data.backend_selector import create_data_access

async def main():
    uda = await create_data_access(load_config())
    rows = await uda.graph_db.query(
        "MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'GW_V17_') "
        "RETURN count(n) AS c", tenant=None)
    c = rows[0]["c"] if rows else 0
    print(f"  [{'PASS' if c>0 else 'FAIL'}] Neptune GW_V17_ nodes: {c}")
    await uda.close()
asyncio.run(main())
PY
}

# ── Main orchestration ─────────────────────────────────────────────────────
main() {
  log "########## v17 REMEDIATION START (tenant=${TENANT}) ##########"
  log "state_dir=${STATE_DIR}"
  preflight
  phase_dryrun
  phase_rollback
  ingest_phase documentation ingest_documentation_v8.py
  ingest_phase code          ingest_code_v8.py
  ingest_phase jjobs         ingest_jjobs_v8.py
  phase_verify

  log "Ingestion reports:"
  ls -la mcp_server_python/scripts/ingestion_reports/${TENANT}_* 2>/dev/null | tail -5 || true

  cleanup_mount
  log "########## v17 REMEDIATION COMPLETE ##########"
  log "Next: rebuild image w/ v17-pilot code, update runtime, run Phase C smoke probe"
}

main "$@"
