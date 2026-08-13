#!/usr/bin/env bash
# =============================================================================
# verify-chromadb-bind.sh — Preflight guard against the ChromaDB bind-mount race
# =============================================================================
# Refuses to start (exit 1) if the ChromaDB persistent-volume story is unsafe.
# Detects the exact failure mode logged in CHANGELOG [7.3.12] (Feb 9, 2026) and
# again on 2026-07-28: docker binds `/mcp_rag_eib/data/chromadb` before
# `mcp_rag_eib.mount` is ready, so the container writes a fresh empty sqlite
# over the persisted 2 GB store.
#
# Invoked as ExecStartPre by SETUP/systemd/chromadb-devops.service and can be
# run standalone: `bash SETUP/scripts/verify-chromadb-bind.sh`.
#
# Env overrides (all optional):
#   CHROMADB_PERSIST_DIR   default /mcp_rag_eib/data/chromadb
#   CHROMADB_MOUNT_UNIT    default mcp_rag_eib.mount
#   CHROMADB_MIN_SQLITE_MB default 100    (host sqlite must be >= this)
#   CHROMADB_MIN_UUID_DIRS default 5      (host must have >= this many
#                                          collection subdirs)
#   CHROMADB_STRICT_STUB   default 1      (1 = also refuse if the Docker
#                                          volume's own _data already holds a
#                                          fresh empty sqlite from a prior
#                                          racy boot — that stub shadows the
#                                          bind and must be cleared first)
#   CHROMADB_VOLUME_NAME   default eib-mcp-rag-server_chromadb-devops-data
# =============================================================================
set -euo pipefail

CHROMADB_PERSIST_DIR="${CHROMADB_PERSIST_DIR:-/mcp_rag_eib/data/chromadb}"
CHROMADB_MOUNT_UNIT="${CHROMADB_MOUNT_UNIT:-mcp_rag_eib.mount}"
CHROMADB_MIN_SQLITE_MB="${CHROMADB_MIN_SQLITE_MB:-100}"
CHROMADB_MIN_UUID_DIRS="${CHROMADB_MIN_UUID_DIRS:-5}"
CHROMADB_STRICT_STUB="${CHROMADB_STRICT_STUB:-1}"
CHROMADB_VOLUME_NAME="${CHROMADB_VOLUME_NAME:-eib-mcp-rag-server_chromadb-devops-data}"

log_ok()   { printf '[OK] %s\n'    "$*"; }
log_warn() { printf '[WARN] %s\n'  "$*" >&2; }
log_err()  { printf '[ERROR] %s\n' "$*" >&2; }

fail() {
  log_err "$1"
  log_err "Preflight aborted — refusing to start ChromaDB to protect persisted data."
  log_err "See CHANGELOG [7.3.12] (2026-02-09) for the original incident."
  exit 1
}

# 1. Persistent mount must be active.
if ! systemctl is-active --quiet "${CHROMADB_MOUNT_UNIT}"; then
  fail "${CHROMADB_MOUNT_UNIT} is not active — persistent disk not mounted."
fi
log_ok "${CHROMADB_MOUNT_UNIT} is active"

# 2. Persist dir exists on the persistent filesystem (not the ephemeral root).
if [[ ! -d "${CHROMADB_PERSIST_DIR}" ]]; then
  fail "Persist dir ${CHROMADB_PERSIST_DIR} does not exist."
fi

persist_mount="$(stat -c '%m' "${CHROMADB_PERSIST_DIR}")"
root_mount="$(stat -c '%m' /)"
if [[ "${persist_mount}" == "${root_mount}" ]]; then
  fail "Persist dir resolves to root filesystem (${persist_mount}) — bind would target ephemeral storage."
fi
log_ok "Persist dir on persistent filesystem: ${persist_mount}"

# 3. Persist dir looks populated (sqlite + collection subdirs). Guards against
#    accidental binds over an empty tree from a previous racy boot.
sqlite="${CHROMADB_PERSIST_DIR}/chroma.sqlite3"
if [[ ! -s "${sqlite}" ]]; then
  fail "Missing ${sqlite} — persist dir looks unpopulated."
fi

sqlite_bytes="$(stat -c '%s' "${sqlite}")"
min_bytes=$(( CHROMADB_MIN_SQLITE_MB * 1024 * 1024 ))
if (( sqlite_bytes < min_bytes )); then
  fail "chroma.sqlite3 is ${sqlite_bytes} bytes (< ${min_bytes} = ${CHROMADB_MIN_SQLITE_MB} MiB). Likely a racy stub."
fi
log_ok "chroma.sqlite3 size: ${sqlite_bytes} bytes (>= ${CHROMADB_MIN_SQLITE_MB} MiB threshold)"

# UUID dirs are 36-char hex-with-dashes; count them without shell globs blowing up.
uuid_dirs="$(find "${CHROMADB_PERSIST_DIR}" -mindepth 1 -maxdepth 1 -type d \
              -regextype posix-extended \
              -regex '.*/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' \
              2>/dev/null | wc -l)"
if (( uuid_dirs < CHROMADB_MIN_UUID_DIRS )); then
  fail "Found ${uuid_dirs} collection UUID dirs (< ${CHROMADB_MIN_UUID_DIRS}). Likely a racy stub."
fi
log_ok "Collection UUID dirs: ${uuid_dirs} (>= ${CHROMADB_MIN_UUID_DIRS} threshold)"

# 4. If the Docker volume's own _data already holds a fresh empty sqlite from
#    a previous racy boot, Docker's local driver will shadow the bind source
#    with that stub. Refuse to start until the stub is cleared.
if [[ "${CHROMADB_STRICT_STUB}" == "1" ]] && command -v docker >/dev/null 2>&1; then
  # Path A (root-only): inspect the volume's _data on the host.
  vol_mountpoint="$(docker volume inspect "${CHROMADB_VOLUME_NAME}" \
    --format '{{ .Mountpoint }}' 2>/dev/null || true)"
  if [[ -n "${vol_mountpoint}" && -d "${vol_mountpoint}" ]]; then
    stub_sqlite="${vol_mountpoint}/chroma.sqlite3"
    stub_bytes=0
    if [[ -r "${stub_sqlite}" ]]; then
      stub_bytes="$(stat -c '%s' "${stub_sqlite}" 2>/dev/null || echo 0)"
    elif [[ ${EUID} -ne 0 ]]; then
      log_warn "Cannot read ${stub_sqlite} without root — skipping host-side stub check."
      log_warn "Systemd unit runs as root and will enforce it; the container-side check below also applies."
    fi
    if (( stub_bytes > 0 && stub_bytes < min_bytes )); then
      persist_inode="$(stat -c '%i' "${sqlite}" 2>/dev/null || echo 0)"
      stub_inode="$(stat -c '%i' "${stub_sqlite}" 2>/dev/null || echo 0)"
      if [[ "${persist_inode}" != "${stub_inode}" ]]; then
        log_err "Docker volume ${CHROMADB_VOLUME_NAME} has a stale stub sqlite:"
        log_err "  path=${stub_sqlite}"
        log_err "  bytes=${stub_bytes} (persist=${sqlite_bytes})"
        log_err "  stub inode=${stub_inode}, persist inode=${persist_inode}"
        log_err "Remediation (host data is safe):"
        log_err "  docker compose -f docker-compose.devops.yaml stop chromadb"
        log_err "  docker compose -f docker-compose.devops.yaml rm -f chromadb"
        log_err "  docker volume rm ${CHROMADB_VOLUME_NAME}"
        log_err "  docker compose -f docker-compose.devops.yaml up -d chromadb"
        fail "Stale volume stub detected — bind mount would be shadowed."
      fi
    fi
    log_ok "Docker volume ${CHROMADB_VOLUME_NAME} passed host-side stub check"
  fi

  # Path B (no root required): if the container is running, ask it what /data
  # actually contains. If the bind is live, this matches the host persist dir.
  container_name="${CHROMADB_CONTAINER_NAME:-chromadb-devops}"
  if docker ps --format '{{.Names}}' | grep -qx "${container_name}"; then
    in_bytes="$(docker exec "${container_name}" stat -c '%s' /data/chroma.sqlite3 2>/dev/null || echo 0)"
    if (( in_bytes > 0 && in_bytes < min_bytes )); then
      log_err "Container ${container_name}:/data/chroma.sqlite3 is ${in_bytes} bytes (persist=${sqlite_bytes})."
      log_err "The bind mount is not active — container is serving a stub. Same remediation as above."
      fail "Container-side stub detected — bind mount is shadowed."
    fi
    log_ok "Container ${container_name} passed in-container stub check (/data=${in_bytes} bytes)"
  fi
fi

log_ok "ChromaDB bind-mount preflight passed"
exit 0
