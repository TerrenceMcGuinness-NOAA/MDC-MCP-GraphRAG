#!/usr/bin/env bash
#
# populate_workflow_efs_phase0.sh
#
# Phase 0 of omd-tenants-1-foundation: populate the Workflow_EFS with the
# canonical NOAA-EMC global-workflow develop worktree under the access-point
# root, so the AgentCore runtime mounted at /mnt/workflow can read
# /mnt/workflow/develop/jobs and the workflow_info smoke probe reports green.
#
# This is a SIMPLIFIED, single-tenant version of the full populate script
# (mcp_server_python/scripts/populate_workflow_efs.sh, Task 12.2). It is
# superseded by 12.2 once the full tenancy stack lands. For Phase 0 we only
# need the gw tenant's develop worktree.
#
# Implements: Requirements 12.1, 12.2 (gw worktree only), 12.4 (live).
# Spec: .kiro/specs/omd-tenants-1-foundation/tasks.md §0.3
#
# Pre-requisites (run on the operator EC2 host):
#   - amazon-efs-utils installed (provides mount.efs)
#   - Host has IAM permission to mount the EFS file system (security-group
#     ingress on TCP 2049 already permits this VPC)
#   - sudo privileges for mkdir / mount / chown / umount
#   - Outbound HTTPS to github.com for the bare clone
#
# Runtime expectation:
#   - First run: ~10-30 minutes (git clone --bare of ~1.3 GB into EFS).
#     The clone is the bottleneck — git network plus EFS write throughput.
#   - Subsequent runs: a few seconds (git worktree already present, just
#     git pull --ff-only against origin/develop).
#
# Reversibility:
#   - The script is idempotent. Re-running picks up where it left off.
#   - To start over, sudo umount /mnt/efs-staging then sudo rm -rf the
#     /mnt/efs-staging mount root after re-mounting (NEVER do this casually
#     on a populated EFS — the data is shared with the runtime).

set -euo pipefail

# ── Tunables (override via env) ────────────────────────────────────────────
EFS_FS_ID="${EFS_FS_ID:-fs-032d52e4677000758}"
STAGING_MNT="${STAGING_MNT:-/mnt/efs-staging}"
GW_REMOTE="${GW_REMOTE:-https://github.com/NOAA-EMC/global-workflow.git}"
GW_BRANCH="${GW_BRANCH:-develop}"
GW_SUBDIR="${GW_SUBDIR:-develop}"   # /mnt/workflow/<subdir> after AgentCore mounts the AP

echo "[INFO] EFS_FS_ID    = ${EFS_FS_ID}"
echo "[INFO] STAGING_MNT  = ${STAGING_MNT}"
echo "[INFO] GW_REMOTE    = ${GW_REMOTE}"
echo "[INFO] GW_BRANCH    = ${GW_BRANCH}"
echo "[INFO] GW_SUBDIR    = ${GW_SUBDIR}"

# ── Always unmount on exit (success or failure) ───────────────────────────
cleanup() {
  if mountpoint -q "${STAGING_MNT}" 2>/dev/null; then
    sudo umount "${STAGING_MNT}" || true
  fi
}
trap cleanup EXIT

# Git's CVE-2022-24765 "dubious ownership" check rejects worktrees whose
# files are not owned by the current effective UID (root, here, since we run
# under sudo) and the worktree contents are owned by 1000:1000 to match the
# AgentCore access-point posixUser. Disable that check for the bare repo and
# the worktree we touch — these paths are operator-curated.
GIT_OPTS=(
  -c safe.directory="${STAGING_MNT}/.git"
  -c safe.directory="${STAGING_MNT}/supported_repos/global-workflow/${GW_SUBDIR}"
)

# ── 1. Mount EFS file-system root (NOT the access point) ───────────────────
sudo mkdir -p "${STAGING_MNT}"
if mountpoint -q "${STAGING_MNT}"; then
  echo "[OK]   ${STAGING_MNT} already mounted"
else
  echo "[STEP] mount -t efs -o tls ${EFS_FS_ID}:/ ${STAGING_MNT}"
  sudo mount -t efs -o tls "${EFS_FS_ID}:/" "${STAGING_MNT}"
fi

# ── 2. Initialize the Workflow_Bare_Repo at <EFS>/.git ─────────────────────
# Lives outside the access-point root /supported_repos/global-workflow
# so it is not visible to the AgentCore runtime (R12.4).
if [[ -d "${STAGING_MNT}/.git" ]]; then
  echo "[OK]   bare repo present at ${STAGING_MNT}/.git"
else
  echo "[STEP] cloning bare repo (this is the slow step, ~10-30 minutes)"
  sudo git clone --bare "${GW_REMOTE}" "${STAGING_MNT}/.git"
fi

# ── 3. Ensure access-point root exists with POSIX 1000:1000 ───────────────
sudo mkdir -p "${STAGING_MNT}/supported_repos/global-workflow"
sudo chown 1000:1000 "${STAGING_MNT}/supported_repos/global-workflow"
sudo chmod 0755     "${STAGING_MNT}/supported_repos/global-workflow"

# ── 4. Add or update the gw tenant's worktree at <root>/<GW_SUBDIR> ───────
target="${STAGING_MNT}/supported_repos/global-workflow/${GW_SUBDIR}"

if sudo git "${GIT_OPTS[@]}" -C "${STAGING_MNT}/.git" worktree list --porcelain \
     | grep -q "^worktree ${target}$"; then
  echo "[STEP] worktree ${target} present — git fetch + merge --ff-only FETCH_HEAD"
  # Bare-repo worktrees share the bare's refs directly, so refs/remotes/origin/*
  # is not populated. Use FETCH_HEAD (set by `git fetch`) for the merge.
  sudo git "${GIT_OPTS[@]}" -C "${target}" fetch origin "${GW_BRANCH}"
  sudo git "${GIT_OPTS[@]}" -C "${target}" merge --ff-only FETCH_HEAD
else
  echo "[STEP] git worktree add ${target} ${GW_BRANCH}"
  sudo git "${GIT_OPTS[@]}" -C "${STAGING_MNT}/.git" worktree add "${target}" "${GW_BRANCH}"
fi

# ── 5. chown the worktree so the runtime's app user (UID 1000) can read ──
sudo chown -R 1000:1000 "${target}"

# ── 6. Verify and unmount ──────────────────────────────────────────────────
# Mirror the smoke probe's dual-path acceptance: <root>/jobs OR <root>/dev/jobs
# (R13.2). NOAA-EMC develop currently uses <root>/dev/jobs/.
echo "[VERIFY] checking ${target}/jobs and ${target}/dev/jobs"
if sudo test -d "${target}/jobs"; then
  echo "[OK]   ${target}/jobs is a directory"
elif sudo test -d "${target}/dev/jobs"; then
  echo "[OK]   ${target}/dev/jobs is a directory"
  sudo ls "${target}/dev/jobs" | head -5
else
  echo "[ERROR] neither ${target}/jobs nor ${target}/dev/jobs exists"
  echo "        workflow_info smoke would fail"
  sudo umount "${STAGING_MNT}" || true
  exit 1
fi

echo "[STEP] umount ${STAGING_MNT}"
sudo umount "${STAGING_MNT}"

echo "[DONE] Phase 0 EFS populated. AccessPointId fsap-03e641f056b341f29 will see:"
echo "       /supported_repos/global-workflow/${GW_SUBDIR}/jobs (R13.5 ready)"