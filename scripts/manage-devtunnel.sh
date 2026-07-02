#!/usr/bin/env bash
# scripts/manage-devtunnel.sh
# Manage the standalone devtunnel for the Docker MCP Gateway (localhost:18888).
#
# Creates a dedicated devtunnel if none exists, ensures the host process is
# running, and offers to update .vscode/mcp.json when the public URL changes.
#
# Usage:
#   ./scripts/manage-devtunnel.sh           # start / verify tunnel (default)
#   ./scripts/manage-devtunnel.sh --stop    # stop the tunnel host process
#   ./scripts/manage-devtunnel.sh --status  # show current status, no changes

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_JSON="${REPO_ROOT}/.vscode/mcp.json"

TUNNEL_DESC="eib-mcp-gateway-18888"
TUNNEL_PORT=18888
TUNNEL_LOG="/tmp/devtunnel-mcp-gateway.log"
TUNNEL_PID_FILE="/tmp/devtunnel-mcp-gateway.pid"

# ── helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[$(date -u +%H:%M:%SZ)] $*"; }
ok()   { echo "[OK]    $*"; }
warn() { echo "[WARN]  $*"; }
err()  { echo "[ERROR] $*" >&2; }

ask_yes_no() {
  local prompt="$1"
  local reply
  read -r -p "${prompt} [y/N] " reply
  [[ "${reply,,}" == "y" || "${reply,,}" == "yes" ]]
}

# ── install devtunnel if missing ──────────────────────────────────────────────
require_devtunnel() {
  if command -v devtunnel &>/dev/null; then
    return 0
  fi
  warn "devtunnel CLI not found. Installing to /usr/local/bin ..."
  local tmp
  tmp="$(mktemp)"
  curl -sL "https://tunnelsassetsprod.blob.core.windows.net/cli/linux-x64-devtunnel" \
    -o "${tmp}"
  sudo install -m 0755 "${tmp}" /usr/local/bin/devtunnel
  rm -f "${tmp}"
  ok "devtunnel installed: $(devtunnel --version 2>&1 | grep 'CLI version' | head -1)"
}

# ── ensure logged in ─────────────────────────────────────────────────────────
require_login() {
  if devtunnel user show 2>/dev/null | grep -q "Logged in"; then
    return 0
  fi
  warn "Not logged in to devtunnel. Starting device-code login..."
  devtunnel user login -d
}

# ── find tunnel ID by description (returns bare ID without .use suffix) ───────
find_tunnel_id() {
  devtunnel list 2>/dev/null \
    | grep "eib-mcp-gateway" \
    | awk '{print $1}' \
    | sed 's/\.use$//' \
    | head -1
}

# ── get public URL from devtunnel show (empty if not hosted) ──────────────────
get_tunnel_url() {
  local tunnel_id="$1"
  devtunnel show "${tunnel_id}" 2>/dev/null \
    | grep -oE "https://[a-z0-9]+-${TUNNEL_PORT}\.use\.devtunnels\.ms" \
    | head -1
}

# ── check if our host process is alive ───────────────────────────────────────
is_host_running() {
  local tunnel_id="$1"
  # Check PID file first
  if [[ -f "${TUNNEL_PID_FILE}" ]]; then
    local pid
    pid="$(cat "${TUNNEL_PID_FILE}")"
    if kill -0 "${pid}" 2>/dev/null; then
      return 0
    fi
  fi
  # Fallback: scan process table
  pgrep -f "devtunnel host ${tunnel_id}" &>/dev/null
}

# ── start tunnel host in background, wait for it to become ready ─────────────
start_host() {
  local tunnel_id="$1"
  log "Starting devtunnel host for ${tunnel_id} ..."
  devtunnel host "${tunnel_id}" >"${TUNNEL_LOG}" 2>&1 &
  local pid=$!
  echo "${pid}" >"${TUNNEL_PID_FILE}"

  # Wait for the host to announce it's ready (up to 20 s)
  local timeout=20 elapsed=0
  while (( elapsed < timeout )); do
    if grep -q "Ready to accept connections" "${TUNNEL_LOG}" 2>/dev/null; then
      break
    fi
    sleep 1
    (( elapsed++ ))
  done

  if (( elapsed >= timeout )); then
    err "Timeout waiting for tunnel host to become ready."
    err "Check log: ${TUNNEL_LOG}"
    exit 1
  fi

  ok "devtunnel host started (PID ${pid})"
}

# ── update mcp.json ───────────────────────────────────────────────────────────
sync_mcp_json() {
  local new_base_url="$1"            # e.g. https://blp11zs1-18888.use.devtunnels.ms
  local new_mcp_url="${new_base_url}/mcp"

  # Extract the current URL (any devtunnels.ms URL on the "url" line)
  local current
  current="$(grep -oP 'https://[^"]+\.devtunnels\.ms[^"]*' "${MCP_JSON}" 2>/dev/null \
             | head -1 || true)"

  if [[ "${current}" == "${new_mcp_url}" ]]; then
    ok ".vscode/mcp.json is already up to date"
    echo "    URL: ${new_mcp_url}"
    return 0
  fi

  warn ".vscode/mcp.json has a different URL:"
  echo "  Current : ${current:-<none>}"
  echo "  New     : ${new_mcp_url}"
  echo ""

  if ask_yes_no "Update .vscode/mcp.json with the new tunnel URL?"; then
    # Replace any devtunnels.ms URL value in the "url" field
    sed -i "s|\"url\": \"https://[^\"]*\.devtunnels\.ms[^\"]*\"|\"url\": \"${new_mcp_url}\"|" \
      "${MCP_JSON}"
    ok ".vscode/mcp.json updated → ${new_mcp_url}"
    warn "Reload the MCP server in VS Code to pick up the new URL."
  else
    warn "Skipped. Update manually in: ${MCP_JSON}"
  fi
}

# ── --stop ────────────────────────────────────────────────────────────────────
cmd_stop() {
  local stopped=0
  if [[ -f "${TUNNEL_PID_FILE}" ]]; then
    local pid
    pid="$(cat "${TUNNEL_PID_FILE}")"
    if kill "${pid}" 2>/dev/null; then
      ok "Stopped devtunnel host (PID ${pid})"
      stopped=1
    fi
    rm -f "${TUNNEL_PID_FILE}"
  fi
  if pgrep -f "devtunnel host" &>/dev/null; then
    pkill -f "devtunnel host" 2>/dev/null
    ok "Killed remaining devtunnel host processes"
    stopped=1
  fi
  if (( stopped == 0 )); then
    warn "No devtunnel host processes were running"
  fi
}

# ── --status ──────────────────────────────────────────────────────────────────
cmd_status() {
  require_devtunnel
  require_login

  local tunnel_id
  tunnel_id="$(find_tunnel_id)"

  if [[ -z "${tunnel_id}" ]]; then
    warn "No tunnel found with description '${TUNNEL_DESC}'"
    echo "  Run without --status to create one."
    return 0
  fi

  ok "Tunnel ID : ${tunnel_id}"
  echo ""
  devtunnel show "${tunnel_id}" 2>&1
  echo ""

  local url
  url="$(get_tunnel_url "${tunnel_id}")"

  if [[ -z "${url}" ]]; then
    warn "Tunnel is not currently hosted (no active host connection)"
    echo "  Run without --status to start it."
    return 0
  fi

  ok "Public MCP endpoint : ${url}/mcp"

  local current_in_json
  current_in_json="$(grep -oP 'https://[^"]+\.devtunnels\.ms[^"]*' "${MCP_JSON}" \
                     2>/dev/null | head -1 || true)"

  if [[ "${current_in_json}" == "${url}/mcp" ]]; then
    ok "mcp.json URL matches — no update needed"
  else
    warn "mcp.json URL is out of date:"
    echo "  mcp.json : ${current_in_json:-<none>}"
    echo "  Tunnel   : ${url}/mcp"
    echo "  Run without --status to fix."
  fi
}

# ── main ──────────────────────────────────────────────────────────────────────
main() {
  case "${1:-}" in
    --stop)   cmd_stop;   exit 0 ;;
    --status) cmd_status; exit 0 ;;
    --help|-h)
      sed -n '/^# Usage:/,/^$/p' "$0"
      exit 0
      ;;
  esac

  require_devtunnel
  require_login

  # ── find or create the dedicated tunnel ──────────────────────────────────
  local tunnel_id
  tunnel_id="$(find_tunnel_id)"

  if [[ -z "${tunnel_id}" ]]; then
    log "No tunnel found. Creating '${TUNNEL_DESC}' ..."
    local create_out
    create_out="$(devtunnel create --allow-anonymous --description "${TUNNEL_DESC}" 2>&1)"
    tunnel_id="$(echo "${create_out}" | awk '/^Tunnel ID/{print $NF}' | sed 's/\.use$//')"
    devtunnel port create "${tunnel_id}" -p "${TUNNEL_PORT}" --protocol http >/dev/null 2>&1
    ok "Created tunnel ${tunnel_id} with port ${TUNNEL_PORT}/http"
  else
    ok "Found existing tunnel: ${tunnel_id}"
  fi

  # ── ensure host process is running ───────────────────────────────────────
  if is_host_running "${tunnel_id}"; then
    ok "devtunnel host is already running"
  else
    start_host "${tunnel_id}"
  fi

  # ── get authoritative public URL ─────────────────────────────────────────
  local url
  url="$(get_tunnel_url "${tunnel_id}")"

  if [[ -z "${url}" ]]; then
    err "Could not determine public tunnel URL from 'devtunnel show ${tunnel_id}'"
    err "Check host log: ${TUNNEL_LOG}"
    exit 1
  fi

  ok "Public URL : ${url}"
  echo ""

  # ── sync mcp.json ─────────────────────────────────────────────────────────
  sync_mcp_json "${url}"
}

main "$@"
