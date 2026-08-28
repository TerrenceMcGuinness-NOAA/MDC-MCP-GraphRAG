#!/usr/bin/env bash
#
# reingest_cutover.sh — Human-gated cutover from v8 to v9-0-0 collection set.
#
# After the Ralph loop reports `is-complete`, an operator runs this script to:
#   1. Validate all preconditions (state, validation probes, rollback image).
#   2. Backup unified_manifest.json.
#   3. Rewrite collection_target fields to the v9-0-0 physical names.
#   4. Restart mcp-gateway.service.
#   5. Run the Requirement 5.1 Validation_Probe suite post-cutover.
#   6. Abort + restore if any probe regresses.
#   7. Write the cutover report and pin the 7-day retention window.
#
# Spec: .kiro/specs/mpnet768-tenant-reingest-aug2026/ (Task 7).
# Requirement 12 (design.md Delta 6).
#
# Usage:
#   scripts/reingest_cutover.sh --target-version v9-0-0 [--dry-run]
#
# ──────────────────────────────────────────────────────────────────────────

set -uo pipefail

# ── Repo root (resolved relative to this script) ──────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# ── Constants ──────────────────────────────────────────────────────────────
MANIFEST="mcp_server_python/src/config/unified_manifest.json"
SM="mcp_server_python/scripts/reingest_state.py"
VALIDATION_SCRIPT="mcp_server_python/scripts/reingest_validation.py"
REPORTS_DIR="docs/reports"
GATEWAY_SERVICE="mcp-gateway.service"
HEALTH_TIMEOUT=60
HEALTH_INTERVAL=5
ROLLBACK_IMAGE_TAG="eib-mcp-rag-python:pre-shared-scope"

# Tenants from the catalog (same order as tenants.yaml).
TENANTS=(gw gw_sfs gw_jedi_gfs gw_v17 gw_gefs_v12)

# ── Argument parsing ──────────────────────────────────────────────────────
TARGET_VERSION=""
DRY_RUN=0

usage() {
  echo "Usage: $0 --target-version <ver> [--dry-run]"
  echo ""
  echo "  --target-version  Target collection version (e.g. v9-0-0)"
  echo "  --dry-run         Print planned manifest diff without modifying anything"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-version)
      TARGET_VERSION="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "[ERROR] unknown argument: $1"
      usage
      ;;
  esac
done

if [[ -z "${TARGET_VERSION}" ]]; then
  echo "[ERROR] --target-version is required"
  usage
fi

STATE_DIR="${REPO_ROOT}/.reingest_state/${TARGET_VERSION}"
VALIDATION_DIR="${STATE_DIR}/validation"
DATE_STAMP="$(date +%Y-%m-%d)"
BACKUP_PATH="${REPORTS_DIR}/${DATE_STAMP}-mpnet768-tenant-reingest-cutover.manifest.bak"
REPORT_PATH="${REPORTS_DIR}/${DATE_STAMP}-mpnet768-tenant-reingest-cutover.md"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# ── Collection name mapping (v8 → v9) ─────────────────────────────────────
#
# Design.md Delta 2 naming table:
#   global-workflow-docs-v8-0-0 → workflow-docs-external-mpnet768-v9-0-0
#                                 (shared external, covers ALL former docs targets)
#   code-with-context-v8-0-0   → code-with-context-mpnet768-v9-0-0
#                                 (per-tenant; default gw has no prefix)
#   jjobs-v8-0-0               → jjobs-mpnet768-v9-0-0
#                                 (per-tenant; default gw has no prefix)
#   ee2-standards-v5-0-0-enhanced → ee2-standards-mpnet768-v9-0-0
#                                 (shared-once)
#   community-summaries        → community-summaries-mpnet768-v9-0-0
#                                 (shared-once)
#
# Per design: the manifest has all 67 sources pointing at 5 distinct
# collection_target values. We rewrite each to the corresponding v9-0-0 name.
declare -A V9_COLLECTION_MAP=(
  ["global-workflow-docs-v8-0-0"]="workflow-docs-external-mpnet768-${TARGET_VERSION}"
  ["code-with-context-v8-0-0"]="code-with-context-mpnet768-${TARGET_VERSION}"
  ["jjobs-v8-0-0"]="jjobs-mpnet768-${TARGET_VERSION}"
  ["ee2-standards-v5-0-0-enhanced"]="ee2-standards-mpnet768-${TARGET_VERSION}"
  ["community-summaries"]="community-summaries-mpnet768-${TARGET_VERSION}"
)

# ── Precondition checks ───────────────────────────────────────────────────

check_state_complete() {
  log "checking state completeness..."
  if ! python3 "${SM}" --collection-version "${TARGET_VERSION}" is-complete; then
    log "[ERROR] state is-complete check failed. Not all units are terminal."
    log "  Run: python3 ${SM} --collection-version ${TARGET_VERSION} report"
    return 1
  fi
  log "[OK] all units in terminal state"
}

check_validation_probes() {
  log "checking validation probe files..."
  local missing=()
  for tenant in "${TENANTS[@]}"; do
    local probe_file="${VALIDATION_DIR}/${tenant}.json"
    if [[ ! -f "${probe_file}" ]]; then
      missing+=("${tenant}")
      continue
    fi
    # Check that the probe recorded a passing result.
    if ! python3 - "${probe_file}" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
if d.get('all_passed') is True:
    sys.exit(0)
probes = d.get('probes', [])
if probes and all(p.get('hit_count', 0) > 0 for p in probes):
    sys.exit(0)
sys.exit(1)
PYEOF
    then
      log "[ERROR] validation probe for tenant '${tenant}' recorded a failure"
      return 1
    fi
  done
  # Also check _shared_once.json
  local shared_probe="${VALIDATION_DIR}/_shared_once.json"
  if [[ ! -f "${shared_probe}" ]]; then
    missing+=("_shared_once")
  else
    if ! python3 - "${shared_probe}" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
if d.get('all_passed') is True:
    sys.exit(0)
probes = d.get('probes', [])
if probes and all(p.get('hit_count', 0) > 0 for p in probes):
    sys.exit(0)
sys.exit(1)
PYEOF
    then
      log "[ERROR] validation probe for _shared_once recorded a failure"
      return 1
    fi
  fi
  if [[ ${#missing[@]} -gt 0 ]]; then
    log "[ERROR] missing validation probe files: ${missing[*]}"
    return 1
  fi
  log "[OK] all validation probes pass"
}

check_rollback_image() {
  log "checking rollback image tag '${ROLLBACK_IMAGE_TAG}'..."
  if ! docker image inspect "${ROLLBACK_IMAGE_TAG}" >/dev/null 2>&1; then
    log "[ERROR] rollback image '${ROLLBACK_IMAGE_TAG}' not found locally"
    log "  Requirement 8.4: the pre-shared-scope tag must be preserved through the run"
    return 1
  fi
  log "[OK] rollback image present"
}

check_manifest_exists() {
  if [[ ! -f "${MANIFEST}" ]]; then
    log "[ERROR] manifest not found: ${MANIFEST}"
    return 1
  fi
  log "[OK] manifest found"
}

# ── Manifest rewrite ──────────────────────────────────────────────────────

compute_manifest_diff() {
  # Show which collection_target fields will change.
  local map_json
  map_json="$(_python_map)"
  python3 - "${MANIFEST}" "${map_json}" <<'PYEOF'
import json, sys

manifest_path = sys.argv[1]
mapping = json.loads(sys.argv[2])

with open(manifest_path) as f:
    m = json.load(f)

changes = []
for src in m['sources']:
    old = src.get('collection_target', '')
    if old in mapping:
        new = mapping[old]
        changes.append(f'  {src["name"]}: {old} -> {new}')

if not changes:
    print('  (no collection_target fields to rewrite)')
else:
    for c in changes:
        print(c)
print(f'\n  Total: {len(changes)} source(s) will be rewritten.')
PYEOF
}

_python_map() {
  # Emit the V9_COLLECTION_MAP as a JSON object string.
  local out="{"
  local first=1
  for k in "${!V9_COLLECTION_MAP[@]}"; do
    if [[ ${first} -eq 0 ]]; then
      out+=", "
    fi
    out+="\"${k}\": \"${V9_COLLECTION_MAP[${k}]}\""
    first=0
  done
  out+="}"
  echo "${out}"
}

rewrite_manifest() {
  log "rewriting manifest collection_target fields..."
  local map_json
  map_json="$(_python_map)"
  python3 - "${MANIFEST}" "${map_json}" <<'PYEOF'
import json, os, sys, tempfile

manifest_path = sys.argv[1]
mapping = json.loads(sys.argv[2])

with open(manifest_path) as f:
    m = json.load(f)

rewritten = 0
for src in m['sources']:
    old = src.get('collection_target', '')
    if old in mapping:
        src['collection_target'] = mapping[old]
        rewritten += 1

if rewritten == 0:
    print('[WARN] no collection_target fields matched the v8 map — already cutover?')
    sys.exit(0)

# Atomic write.
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(manifest_path), suffix='.tmp')
try:
    with os.fdopen(fd, 'w') as f:
        json.dump(m, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, manifest_path)
except Exception:
    os.unlink(tmp)
    raise

print(f'[OK] rewrote {rewritten} collection_target field(s)')
PYEOF
}

# ── Gateway restart + health check ────────────────────────────────────────

restart_gateway() {
  log "restarting ${GATEWAY_SERVICE}..."
  sudo systemctl restart "${GATEWAY_SERVICE}"
  log "waiting for gateway health (timeout: ${HEALTH_TIMEOUT}s)..."
  local elapsed=0
  while (( elapsed < HEALTH_TIMEOUT )); do
    # Poll the mcp_health_check endpoint.
    if curl -sf -H "Authorization: Bearer eib-mcp-gateway-token-2025" \
         "http://localhost:18888/mcp" \
         -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"mcp_health_check","arguments":{}}}' \
         2>/dev/null | grep -q '"HEALTHY"'; then
      log "[OK] gateway healthy after ${elapsed}s"
      return 0
    fi
    sleep "${HEALTH_INTERVAL}"
    elapsed=$(( elapsed + HEALTH_INTERVAL ))
  done
  log "[ERROR] gateway did not reach healthy state within ${HEALTH_TIMEOUT}s"
  return 1
}

# ── Post-cutover validation ───────────────────────────────────────────────

run_post_cutover_probes() {
  log "running post-cutover Validation_Probe suite..."
  local failures=()
  for tenant in "${TENANTS[@]}"; do
    log "  probe: tenant=${tenant}"
    if ! python3 "${VALIDATION_SCRIPT}" --target-version "${TARGET_VERSION}" --tenant "${tenant}"; then
      failures+=("${tenant}")
    fi
  done
  # Global shared-once probe.
  log "  probe: _shared_once"
  if ! python3 "${VALIDATION_SCRIPT}" --target-version "${TARGET_VERSION}" --global; then
    failures+=("_shared_once")
  fi
  if [[ ${#failures[@]} -gt 0 ]]; then
    log "[ERROR] post-cutover probes failed for: ${failures[*]}"
    return 1
  fi
  log "[OK] all post-cutover probes pass"
}

# ── Rollback (restore manifest backup) ────────────────────────────────────

rollback_manifest() {
  log "[ROLLBACK] restoring manifest from backup..."
  if [[ -f "${BACKUP_PATH}" ]]; then
    cp "${BACKUP_PATH}" "${MANIFEST}"
    log "[ROLLBACK] manifest restored from ${BACKUP_PATH}"
    log "[ROLLBACK] restarting gateway with old manifest..."
    sudo systemctl restart "${GATEWAY_SERVICE}"
    sleep 5
    log "[ROLLBACK] done. v8 generation remains serving."
  else
    log "[ROLLBACK] ERROR: backup not found at ${BACKUP_PATH}"
    log "[ROLLBACK] manual restoration required:"
    log "  git checkout HEAD -- ${MANIFEST}"
    log "  sudo systemctl restart ${GATEWAY_SERVICE}"
  fi
}

# ── Cutover report ────────────────────────────────────────────────────────

write_cutover_report() {
  local retention_end
  retention_end="$(date -d '+7 days' +%Y-%m-%d 2>/dev/null || date -v+7d +%Y-%m-%d 2>/dev/null || echo 'YYYY-MM-DD')"
  mkdir -p "${REPORTS_DIR}"
  cat > "${REPORT_PATH}" <<EOF
# mpnet768 Tenant Re-Ingest Cutover Report

**Date**: ${DATE_STAMP}
**Target Version**: ${TARGET_VERSION}
**Operator**: $(whoami)
**Source Spec**: .kiro/specs/mpnet768-tenant-reingest-aug2026/

## Cutover Summary

The read path has been switched from the v8 mixed-generation collection set
to the ${TARGET_VERSION} mpnet768 collection set.

### Collection Mapping Applied

| Old (v8) | New (${TARGET_VERSION}) |
|---|---|
| \`global-workflow-docs-v8-0-0\` | \`workflow-docs-external-mpnet768-${TARGET_VERSION}\` |
| \`code-with-context-v8-0-0\` | \`code-with-context-mpnet768-${TARGET_VERSION}\` |
| \`jjobs-v8-0-0\` | \`jjobs-mpnet768-${TARGET_VERSION}\` |
| \`ee2-standards-v5-0-0-enhanced\` | \`ee2-standards-mpnet768-${TARGET_VERSION}\` |
| \`community-summaries\` | \`community-summaries-mpnet768-${TARGET_VERSION}\` |

### Tenants Validated

$(for t in "${TENANTS[@]}"; do echo "- \`${t}\`: PASS"; done)
- \`_shared_once\`: PASS

## v8 Retention Window

The v8 generation collections are preserved (Requirement 1.2 — never deleted
during the run). They remain available for fast rollback.

- **Retention start**: ${DATE_STAMP}
- **Retention end (7 days)**: ${retention_end}
- **Rollback procedure**: See below.

## Rollback Procedure

\`\`\`bash
cp ${BACKUP_PATH} ${MANIFEST}
sudo systemctl restart ${GATEWAY_SERVICE}
# Verify:
curl -sf -H "Authorization: Bearer eib-mcp-gateway-token-2025" \\
  http://localhost:18888/mcp \\
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"mcp_health_check","arguments":{}}}' | python3 -m json.tool
\`\`\`

## Post-Cutover State

Manifest backup: \`${BACKUP_PATH}\`
State directory: \`${STATE_DIR}\`
Validation probes: \`${VALIDATION_DIR}/\`
EOF
  log "[OK] cutover report written to ${REPORT_PATH}"
}

# ── Main ──────────────────────────────────────────────────────────────────

main() {
  log "########## CUTOVER: ${TARGET_VERSION} ##########"

  # ── Dry-run: show planned diff and exit (only requires manifest) ──
  if [[ ${DRY_RUN} -eq 1 ]]; then
    check_manifest_exists || exit 1
    log "[DRY-RUN] planned manifest collection_target changes:"
    compute_manifest_diff
    log "[DRY-RUN] no changes applied. Remove --dry-run to execute the full cutover."
    exit 0
  fi

  # ── Preconditions (full cutover only) ──
  log "--- precondition checks ---"
  check_manifest_exists || exit 1
  check_state_complete || exit 1
  check_validation_probes || exit 1
  check_rollback_image || exit 1
  log "--- all preconditions pass ---"

  # ── Backup manifest ──
  mkdir -p "${REPORTS_DIR}"
  cp "${MANIFEST}" "${BACKUP_PATH}"
  log "[OK] manifest backed up to ${BACKUP_PATH}"

  # ── Rewrite manifest ──
  rewrite_manifest || { log "[ERROR] manifest rewrite failed"; exit 1; }

  # ── Restart gateway ──
  if ! restart_gateway; then
    log "[ERROR] gateway restart failed — rolling back"
    rollback_manifest
    exit 1
  fi

  # ── Post-cutover validation ──
  if ! run_post_cutover_probes; then
    log "[ERROR] post-cutover probes regressed — rolling back"
    rollback_manifest
    exit 1
  fi

  # ── Write report ──
  write_cutover_report

  log "########## CUTOVER COMPLETE (${TARGET_VERSION}) ##########"
  log "  Report: ${REPORT_PATH}"
  log "  Backup: ${BACKUP_PATH}"
  log "  v8 retention window: 7 days from today"
}

main "$@"
