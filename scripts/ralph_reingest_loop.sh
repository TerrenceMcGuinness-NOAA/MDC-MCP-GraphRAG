#!/usr/bin/env bash
#
# ralph_reingest_loop.sh — Loop_Driver for the COTS full re-ingest Ralph loop.
#
# Repeatedly invokes the Kiro CLI once per iteration; each iteration does exactly
# ONE (tenant, stage) unit (see scripts/ralph_reingest_prompt.md), checkpointing
# to the durable State_File so the run survives disconnects and completes over
# many hours.
#
# Spec: .kiro/specs/cots-reingest-ralph-loop/ (Task 2.2).
#
# ──────────────────────────────────────────────────────────────────────────
# SAFETY: iterations may run the DESTRUCTIVE `reset` stage (deletes the target
# Collection_Version's tenant-prefixed ChromaDB collections + Neo4j labels) and
# hours of re-ingestion. Reset units refuse to run unless CONFIRM_DESTRUCTIVE=yes.
# Building a NEW Collection_Version alongside the serving set is non-destructive
# to the serving data; an in-place rebuild is not — choose the version carefully.
#
# Usage (detached, survives disconnect):
#   CONFIRM_DESTRUCTIVE=yes REINGEST_COLLECTION_VERSION=v9-0-0 \
#     nohup bash scripts/ralph_reingest_loop.sh \
#       > logs/reingest_$(date +%Y%m%dT%H%M%S).log 2>&1 &
#
# Monitor:   tail -f logs/reingest_*.log ; cat .reingest_state/<ver>/PROGRESS.md
# Pause:     touch .reingest_state/STOP     (halts after the current iteration)
# Resume:    re-run the same command — state is durable, done/skipped units skip.
# ──────────────────────────────────────────────────────────────────────────

set -uo pipefail   # NOT -e: per-iteration failures are recorded, not fatal.

# ── Repo root (resolved relative to this script) ──────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# ── Tunables (override via env) ───────────────────────────────────────────
REINGEST_COLLECTION_VERSION="${REINGEST_COLLECTION_VERSION:-v9-0-0}"
MAX_ITERATIONS="${MAX_ITERATIONS:-500}"
ITER_TIMEOUT="${ITER_TIMEOUT:-3600}"           # seconds per iteration
SLEEP_BETWEEN="${SLEEP_BETWEEN:-5}"            # base sleep between iterations
CONFIRM_DESTRUCTIVE="${CONFIRM_DESTRUCTIVE:-no}"
REINGEST_DRY_RUN="${REINGEST_DRY_RUN:-0}"
KIRO_AGENT="${KIRO_AGENT:-kiro_default}"
KIRO_MODEL="${KIRO_MODEL:-}"
KIRO_BIN="${KIRO_BIN:-kiro-cli}"

STATE_DIR="${REPO_ROOT}/.reingest_state/${REINGEST_COLLECTION_VERSION}"
STOP_FILE="${REPO_ROOT}/.reingest_state/STOP"
PROMPT="${SCRIPT_DIR}/ralph_reingest_prompt.md"
SM="mcp_server_python/scripts/reingest_state.py"
LOG_DIR="${REPO_ROOT}/logs"
mkdir -p "${LOG_DIR}" "${STATE_DIR}"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# ── COTS environment (SPOT: mirror mcp_server_python/scripts/run_mcp_stdio.sh) ─
# run_mcp_stdio.sh exec's the server at its tail, so it cannot be sourced here;
# the env block is replicated with the same defaults. Operator overrides win.
setup_env() {
  local SPACK_SETUP="${SPACK_SETUP:-/mcp_rag_eib/spack/share/spack/setup-env.sh}"
  if [[ -f "${SPACK_SETUP}" ]]; then
    # shellcheck disable=SC1090
    source "${SPACK_SETUP}" 2>/dev/null || log "[WARN] spack setup-env failed (non-fatal)"
    module load python/3.11.14 py-pip py-neo4j py-httpx py-pydantic >/dev/null 2>&1 \
      || log "[WARN] module load failed (non-fatal; using base python3)"
  fi
  export DB_BACKEND="${DB_BACKEND:-cots}"
  export MCP_EMBEDDING_PROFILE="${MCP_EMBEDDING_PROFILE:-mpnet768}"
  export NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
  export NEO4J_USER="${NEO4J_USER:-neo4j}"
  export NEO4J_PASSWORD="${NEO4J_PASSWORD:-gfsworkflow2025}"
  export CHROMADB_HOST="${CHROMADB_HOST:-localhost}"
  export CHROMADB_PORT="${CHROMADB_PORT:-8080}"
  export MCP_WORKFLOW_MOUNT="${MCP_WORKFLOW_MOUNT:-${REPO_ROOT}/.pw_workflow_mount}"
  export MCP_TENANT_CATALOG_PATH="${MCP_TENANT_CATALOG_PATH:-${REPO_ROOT}/mcp_server_python/src/config/tenants.yaml}"
  # Threaded into every ingester + the state manager.
  export REINGEST_COLLECTION_VERSION CONFIRM_DESTRUCTIVE REINGEST_DRY_RUN
}

sm() { python3 "${SM}" --collection-version "${REINGEST_COLLECTION_VERSION}" "$@"; }

# ── Pre-flight ─────────────────────────────────────────────────────────────
preflight() {
  [[ -f "${PROMPT}" ]] || { log "[ERROR] prompt not found: ${PROMPT}"; exit 1; }
  command -v "${KIRO_BIN}" >/dev/null 2>&1 \
    || { log "[ERROR] ${KIRO_BIN} not on PATH"; exit 1; }
  if [[ ! -f "${STATE_DIR}/state.json" ]]; then
    log "[ERROR] no state at ${STATE_DIR}/state.json — run reingest_state.py init first:"
    log "  python3 ${SM} --collection-version ${REINGEST_COLLECTION_VERSION} init --attempt-cap 3"
    exit 1
  fi
  if [[ "${CONFIRM_DESTRUCTIVE}" != "yes" ]]; then
    log "[WARN] CONFIRM_DESTRUCTIVE!=yes — reset units will fail until it is set."
  fi
  rm -f "${STOP_FILE}"   # clear a stale stop-file from a prior run
  log "[OK] pre-flight passed (version=${REINGEST_COLLECTION_VERSION}, "\
"max_iter=${MAX_ITERATIONS}, iter_timeout=${ITER_TIMEOUT}s)"
}

run_iteration() {
  local i="$1"
  local cmd=("${KIRO_BIN}" chat --no-interactive --trust-all-tools --agent "${KIRO_AGENT}")
  [[ -n "${KIRO_MODEL}" ]] && cmd+=(--model "${KIRO_MODEL}")
  cmd+=("$(cat "${PROMPT}")")
  log "=== iteration ${i} ==="
  if timeout "${ITER_TIMEOUT}" "${cmd[@]}"; then
    log "iteration ${i} exited 0"
  else
    log "[WARN] iteration ${i} exited non-zero (unit state is recorded by the CLI; continuing)"
  fi
}

# ── Main loop ──────────────────────────────────────────────────────────────
main() {
  setup_env
  preflight
  log "########## COTS RE-INGEST RALPH LOOP START (${REINGEST_COLLECTION_VERSION}) ##########"

  local i=0
  while :; do
    if [[ -f "${STOP_FILE}" ]]; then
      log "STOP file present (${STOP_FILE}) — halting gracefully after current pass"
      break
    fi
    if sm is-complete; then
      log "all units terminal — run complete"
      break
    fi
    if (( i >= MAX_ITERATIONS )); then
      log "max iterations (${MAX_ITERATIONS}) reached — stopping"
      break
    fi
    i=$(( i + 1 ))
    run_iteration "${i}"
    # Exponential-ish backoff bounded to 60s (attempts are per-unit in state).
    local nap=$(( SLEEP_BETWEEN ))
    (( nap > 60 )) && nap=60
    sleep "${nap}"
  done

  log "final report:"
  sm report || true
  log "PROGRESS.md: ${STATE_DIR}/PROGRESS.md"
  log "########## COTS RE-INGEST RALPH LOOP END (${i} iterations) ##########"
}

# ── Argument parsing ───────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      REINGEST_DRY_RUN=1
      shift
      ;;
    --target-version)
      REINGEST_COLLECTION_VERSION="$2"
      shift 2
      ;;
    --spec)
      # Informational — recorded in logs but does not change behaviour.
      log "[INFO] spec: $2"
      shift 2
      ;;
    *)
      log "[ERROR] unknown argument: $1"
      exit 1
      ;;
  esac
done

main
