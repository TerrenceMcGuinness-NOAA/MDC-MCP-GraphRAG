#!/usr/bin/env bash
#
# populate_workflow_efs.sh
#
# Multi-tenant version: reads tenants.yaml and creates one git worktree
# per tenant under the EFS access-point root. Supersedes the Phase 0
# single-tenant script (populate_workflow_efs_phase0.sh).
#
# Implements: R2.1, R2.2, R2.3, R2.4 of omd-tenants-2-v17-pilot.
#
# Pre-requisites (run on the operator EC2 host):
#   - amazon-efs-utils installed (provides mount.efs)
#   - python3.12 + PyYAML available
#   - sudo privileges for mkdir / mount / chown / umount
#   - Outbound HTTPS to github.com for the bare clone
#
# Runtime expectation:
#   - First run with new tenant: 1-5 minutes (worktree checkout against
#     existing shared bare repo). Full bare clone: ~10-30 min if missing.
#   - Subsequent runs: seconds (fetch + merge --ff-only per worktree).
#
# Idempotency contract (R2.4):
#   - Re-running with no catalog change is a no-op (fetch + ff-only).
#   - Adding a new tenant row provisions only the new worktree.
#   - Removing a tenant row does NOT delete its worktree (explicit step).

set -euo pipefail

# ── Tunables ───────────────────────────────────────────────────────────────
EFS_FS_ID="${EFS_FS_ID:-fs-032d52e4677000758}"
STAGING_MNT="${STAGING_MNT:-/mnt/efs-staging}"
GW_REMOTE="${GW_REMOTE:-https://github.com/NOAA-EMC/global-workflow.git}"
TENANTS_YAML="${TENANTS_YAML:-mcp_server_python/src/config/tenants.yaml}"

echo "[INFO] EFS_FS_ID    = ${EFS_FS_ID}"
echo "[INFO] STAGING_MNT  = ${STAGING_MNT}"
echo "[INFO] GW_REMOTE    = ${GW_REMOTE}"
echo "[INFO] TENANTS_YAML = ${TENANTS_YAML}"

# ── Cleanup trap ──────────────────────────────────────────────────────────
cleanup() {
  if mountpoint -q "${STAGING_MNT}" 2>/dev/null; then
    sudo umount "${STAGING_MNT}" || true
  fi
}
trap cleanup EXIT

# ── Read tenant catalog via Python ────────────────────────────────────────
read_tenants() {
  python3.12 - "${TENANTS_YAML}" <<'PY'
import sys, yaml
data = yaml.safe_load(open(sys.argv[1]))
for t in data["tenants"]:
    print(f"{t['tenant_id']}\t{t['workflow_subdir']}\t{t['branch']}")
PY
}

# ── Mount EFS file-system root (NOT the access point) ─────────────────────
mount_efs() {
  sudo mkdir -p "${STAGING_MNT}"
  if mountpoint -q "${STAGING_MNT}"; then
    echo "[OK]   ${STAGING_MNT} already mounted"
  else
    echo "[STEP] mount -t efs -o tls ${EFS_FS_ID}:/ ${STAGING_MNT}"
    sudo mount -t efs -o tls "${EFS_FS_ID}:/" "${STAGING_MNT}"
  fi
}

# ── Initialize bare repo at <EFS>/.git ────────────────────────────────────
init_bare_repo() {
  if [[ -d "${STAGING_MNT}/.git" ]]; then
    echo "[OK]   bare repo present at ${STAGING_MNT}/.git"
  else
    echo "[STEP] cloning bare repo (slow step, ~10-30 minutes)"
    sudo git clone --bare "${GW_REMOTE}" "${STAGING_MNT}/.git"
  fi
}

# ── Ensure access-point root exists ───────────────────────────────────────
ensure_ap_root() {
  sudo mkdir -p "${STAGING_MNT}/supported_repos/global-workflow"
  sudo chown 1000:1000 "${STAGING_MNT}/supported_repos/global-workflow"
  sudo chmod 0755 "${STAGING_MNT}/supported_repos/global-workflow"
}

# ── Add or update a single worktree ──────────────────────────────────────
add_or_update_worktree() {
  local subdir="$1" branch="$2"
  local target="${STAGING_MNT}/supported_repos/global-workflow/${subdir}"
  local GIT_OPTS=(-c "safe.directory=*")

  if sudo git "${GIT_OPTS[@]}" -C "${STAGING_MNT}/.git" worktree list --porcelain \
       | grep -q "^worktree ${target}$"; then
    echo "[STEP] ${subdir}: fetch origin ${branch} + merge --ff-only FETCH_HEAD"
    # Phase 0 lesson: fetch from the worktree dir so FETCH_HEAD lands
    # in the worktree's gitdir (bare-repo worktrees lack remotes tracking).
    sudo git "${GIT_OPTS[@]}" -C "${target}" fetch origin "${branch}"
    sudo git "${GIT_OPTS[@]}" -C "${target}" merge --ff-only FETCH_HEAD
  else
    echo "[STEP] git worktree add ${target} ${branch}"
    sudo git "${GIT_OPTS[@]}" -C "${STAGING_MNT}/.git" worktree add "${target}" "${branch}"
  fi
  sudo chown -R 1000:1000 "${target}"
}

# ── Main ──────────────────────────────────────────────────────────────────
main() {
  mount_efs
  init_bare_repo
  ensure_ap_root

  while IFS=$'\t' read -r tid subdir branch; do
    echo "[INFO] tenant=${tid} subdir=${subdir} branch=${branch}"
    add_or_update_worktree "${subdir}" "${branch}"
  done < <(read_tenants)

  # R2.2 verification for v17 pilot
  local v17_job="${STAGING_MNT}/supported_repos/global-workflow/dev-v17/dev/jobs/JGDAS_ATMOS_ANALYSIS_WDQMS"
  if sudo test -f "${v17_job}"; then
    echo "[OK] R2.2 satisfied: dev-v17 worktree contains WDQMS J-Job"
  else
    echo "[WARN] R2.2: ${v17_job} not found (v17 branch may not have this file yet)"
  fi

  echo "[STEP] umount ${STAGING_MNT}"
  sudo umount "${STAGING_MNT}"
  echo "[DONE] Multi-tenant EFS populated."
}

main "$@"
