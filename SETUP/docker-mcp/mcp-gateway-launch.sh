#!/usr/bin/env bash
#
# mcp-gateway-launch.sh — launch wrapper for the Docker MCP Gateway
# (Phase 63b). Invoked by mcp-gateway.service (ExecStart).
#
# Purpose: bridge the GitHub token from the shell secrets SPOT
# (~/.config/eib-mcp/secrets.env, the same file run_mcp_stdio.sh sources)
# into docker-mcp's `--secrets` switch. docker-mcp classifies GITHUB_TOKEN
# as a secret and refuses plain `-e` pass-through, so it must be supplied via
# a `--secrets <.env>` file whose key matches the catalog `secrets:` block.
#
# The token value is materialized to a tmpfs file (mode 600, wiped on reboot,
# never committed to git). Keeping this in a wrapper — not inline in the unit's
# ExecStart — avoids systemd's own `$VAR` expansion mangling the shell.
#
set -euo pipefail

# ── SPOT paths ─────────────────────────────────────────────────────────────
SECRETS_SRC="${MCP_SECRETS_FILE:-/home/Terry.McGuinness/.config/eib-mcp/secrets.env}"
SECRETS_ENV="${MCP_GATEWAY_SECRETS_ENV:-/run/mcp-gateway-secrets.env}"
DOCKER_MCP="${DOCKER_MCP_BIN:-/root/.docker/cli-plugins/docker-mcp}"
CATALOG_DIR="/mcp_rag_eib/eib-mcp-rag-server/SETUP/docker-mcp"

# ── Inherit the token from the shell secrets file (export-format) ──────────
set -a
# shellcheck disable=SC1090
[[ -f "${SECRETS_SRC}" ]] && . "${SECRETS_SRC}"
set +a

# ── Materialize a docker-mcp-format .env (KEY=VALUE, no `export`) on tmpfs ─
umask 077
: >"${SECRETS_ENV}"
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  printf 'GITHUB_TOKEN=%s\n' "${GITHUB_TOKEN}" >>"${SECRETS_ENV}"
  echo "[OK] GITHUB_TOKEN wired to ${SECRETS_ENV} (len=${#GITHUB_TOKEN})" >&2
else
  echo "[WARN] GITHUB_TOKEN not found in ${SECRETS_SRC}; github_tools will skip" >&2
fi

# ── Launch the gateway (command otherwise byte-for-byte unchanged) ─────────
exec "${DOCKER_MCP}" gateway run \
  --catalog "${CATALOG_DIR}/catalogs/eib-local.yaml" \
  --registry "${CATALOG_DIR}/registry.yaml" \
  --config "${CATALOG_DIR}/config.yaml" \
  --tools-config "${CATALOG_DIR}/tools.yaml" \
  --secrets "${SECRETS_ENV}" \
  --enable-all-servers \
  --transport streaming \
  --port 18888 \
  --long-lived \
  --verbose
