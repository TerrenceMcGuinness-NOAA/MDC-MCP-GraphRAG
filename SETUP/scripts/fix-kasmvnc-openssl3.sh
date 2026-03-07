#!/bin/bash
################################################################################
# fix-kasmvnc-openssl3.sh - Automated KasmVNC OpenSSL 3.5.x compatibility fix
# Version: 1.0.0
# Location: SETUP/scripts/fix-kasmvnc-openssl3.sh
#
# Fixes three compounding KasmVNC defects exposed by OpenSSL >= 3.5.x on EL9:
#   1. RPM default SSL cert has CA:TRUE — rejected by OpenSSL 3.5.x strict validation
#   2. Server null-pointer crash in WebUDP code path when cert fails
#   3. Client JS defaults WebRTC to enabled, triggering the crash
#
# This script is IDEMPOTENT — safe to run on every VM boot.
# It checks current state before making changes and skips steps that are
# already applied. All original files are backed up with .bak.orig suffix
# (only on first patch; subsequent runs do not overwrite backups).
#
# Usage:
#   sudo ./fix-kasmvnc-openssl3.sh           # Apply all fixes
#   sudo ./fix-kasmvnc-openssl3.sh --check   # Dry-run: report status only
#   sudo ./fix-kasmvnc-openssl3.sh --force   # Re-apply even if already patched
#
# Reference: supported_repos/global-workflow.wiki/
#   KasmVNC-SSL-Certificate-Failure-on-EL9-OpenSSL-3.md
#
################################################################################

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────

CERT_PATH="/etc/pki/tls/private/kasmvnc.pem"
SCREEN_BUNDLE="/usr/share/kasmvnc/www/screen.bundle.js"
SELECT_DE="/usr/lib/kasmvncserver/select-de.sh"
VNC_YAML_TEMPLATE_USERS=()  # populated below

# ── Argument parsing ─────────────────────────────────────────────────────────

CHECK_ONLY=false
FORCE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)  CHECK_ONLY=true; shift ;;
    --force)  FORCE=true; shift ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "[ERROR] Unknown option: $1"; exit 2 ;;
  esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────

readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly RED='\033[0;31m'
readonly CYAN='\033[0;36m'
readonly NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()      { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()     { echo -e "${RED}[ERROR]${NC} $1"; }
skipped() { echo -e "${GREEN}[SKIP]${NC} $1 (already applied)"; }

CHANGES=0
SKIPPED=0
ERRORS=0

# Back up a file only if no .bak.orig exists yet (preserve original)
backup_once() {
  local file="$1"
  if [[ -f "${file}" ]] && [[ ! -f "${file}.bak.orig" ]]; then
    cp -a "${file}" "${file}.bak.orig"
    info "Backed up ${file} -> ${file}.bak.orig"
  fi
}

# ── Pre-flight checks ────────────────────────────────────────────────────────

if [[ "$(id -u)" -ne 0 ]]; then
  err "This script must be run as root (sudo)."
  exit 1
fi

if ! command -v vncserver &>/dev/null; then
  warn "KasmVNC is not installed (vncserver not found). Nothing to fix."
  exit 0
fi

if ! rpm -q kasmvncserver &>/dev/null && ! rpm -q kasmvnc &>/dev/null; then
  warn "KasmVNC RPM not installed. Nothing to fix."
  exit 0
fi

OPENSSL_VERSION=$(openssl version 2>/dev/null || echo "unknown")
info "OpenSSL: ${OPENSSL_VERSION}"
info "KasmVNC: $(rpm -q kasmvncserver 2>/dev/null || rpm -q kasmvnc 2>/dev/null || echo 'unknown')"

echo ""
echo "=========================================="
echo " KasmVNC OpenSSL 3.5.x Compatibility Fix"
echo "=========================================="
echo ""

# ── Step 1: Regenerate SSL Certificate ───────────────────────────────────────

fix_ssl_cert() {
  info "Step 1: Checking SSL certificate..."

  local needs_fix=false

  if [[ ! -f "${CERT_PATH}" ]]; then
    needs_fix=true
    info "Certificate not found — will generate."
  else
    # Check if cert has CA:FALSE (the fix) or CA:TRUE (the bug)
    local basic_constraints
    basic_constraints=$(openssl x509 -in "${CERT_PATH}" -text -noout 2>/dev/null \
      | grep -A1 "Basic Constraints" | tail -1 | tr -d ' ' || true)

    if echo "${basic_constraints}" | grep -qi "CA:FALSE"; then
      if [[ "${FORCE}" == true ]]; then
        needs_fix=true
        info "Certificate already has CA:FALSE but --force specified."
      else
        skipped "SSL certificate already has CA:FALSE"
        ((SKIPPED++)) || true
        return 0
      fi
    else
      needs_fix=true
      info "Certificate has CA:TRUE or missing basicConstraints — needs regeneration."
    fi
  fi

  if [[ "${CHECK_ONLY}" == true ]]; then
    if [[ "${needs_fix}" == true ]]; then
      warn "Step 1 NEEDS FIX: SSL certificate requires regeneration"
    fi
    return 0
  fi

  backup_once "${CERT_PATH}"

  openssl req -x509 -nodes -days 3650 -newkey rsa:4096 -sha256 \
    -keyout "${CERT_PATH}" \
    -out "${CERT_PATH}" \
    -subj "/C=US/ST=VA/L=None/O=NOAA-EMC/OU=EIB/CN=kasm/emailAddress=none@none.none" \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "keyUsage=digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" \
    2>/dev/null

  # Set permissions for kasmvnc-cert group
  if getent group kasmvnc-cert &>/dev/null; then
    chgrp kasmvnc-cert "${CERT_PATH}"
    chmod 640 "${CERT_PATH}"
  else
    chmod 600 "${CERT_PATH}"
  fi

  # Verify
  local verify
  verify=$(openssl x509 -in "${CERT_PATH}" -text -noout 2>/dev/null \
    | grep -A1 "Basic Constraints" | tail -1 || true)
  if echo "${verify}" | grep -qi "CA:FALSE"; then
    ok "SSL certificate regenerated with CA:FALSE, RSA-4096, SHA-256"
    ((CHANGES++)) || true
  else
    err "SSL certificate regeneration failed verification"
    ((ERRORS++)) || true
  fi
}

# ── Step 2: Configure VNC YAML (STUN/UDP disabled) ──────────────────────────

fix_vnc_yaml() {
  info "Step 2: Checking VNC YAML configurations..."

  # Find all users with a ~/.vnc directory
  local user_homes=()
  for home_dir in /home/*/; do
    if [[ -d "${home_dir}.vnc" ]]; then
      user_homes+=("${home_dir}")
    fi
  done

  if [[ ${#user_homes[@]} -eq 0 ]]; then
    info "No user .vnc directories found. Skipping YAML config."
    return 0
  fi

  for home_dir in "${user_homes[@]}"; do
    local username
    username=$(basename "${home_dir}")
    local vnc_dir="${home_dir}.vnc"
    local yaml_file="${vnc_dir}/kasmvnc.yaml"
    local needs_fix=false

    if [[ -f "${yaml_file}" ]]; then
      # Check if STUN is already disabled
      if grep -q "stun_server: off" "${yaml_file}" 2>/dev/null; then
        if [[ "${FORCE}" != true ]]; then
          skipped "kasmvnc.yaml for ${username} (STUN already off)"
          ((SKIPPED++)) || true
          continue
        fi
      fi
    fi
    needs_fix=true

    if [[ "${CHECK_ONLY}" == true ]]; then
      warn "Step 2 NEEDS FIX: kasmvnc.yaml for ${username} needs STUN/UDP disabled"
      continue
    fi

    backup_once "${yaml_file}"

    cat > "${yaml_file}" << 'EOFYAML'
# KasmVNC Configuration — OpenSSL 3.5.x compatibility
# Auto-generated by fix-kasmvnc-openssl3.sh
# See: global-workflow.wiki/KasmVNC-SSL-Certificate-Failure-on-EL9-OpenSSL-3.md

logging:
  log_writer_name: all
  log_dest: logfile
  level: 100

network:
  udp:
    public_ip: 127.0.0.1
    stun_server: off
EOFYAML

    # Fix ownership
    local user_group
    user_group=$(id -gn "${username}" 2>/dev/null || echo "${username}")
    chown "${username}:${user_group}" "${yaml_file}"
    chmod 644 "${yaml_file}"

    ok "kasmvnc.yaml updated for ${username} (STUN/UDP disabled)"
    ((CHANGES++)) || true
  done
}

# ── Step 3: Patch KasmVNC JavaScript Client ──────────────────────────────────

fix_javascript_client() {
  info "Step 3: Checking KasmVNC JavaScript client files..."

  # 3a: Patch screen.bundle.js
  if [[ -f "${SCREEN_BUNDLE}" ]]; then
    if grep -q 'e\.rfb\.enableWebRTC=e\.getSetting("enable_webrtc",!0,!1)' "${SCREEN_BUNDLE}" 2>/dev/null; then
      if [[ "${CHECK_ONLY}" == true ]]; then
        warn "Step 3a NEEDS FIX: screen.bundle.js has WebRTC default enabled"
      else
        backup_once "${SCREEN_BUNDLE}"
        sed -i \
          's/e\.rfb\.enableWebRTC=e\.getSetting("enable_webrtc",!0,!1)/e.rfb.enableWebRTC=!1/' \
          "${SCREEN_BUNDLE}"
        ok "screen.bundle.js patched: enableWebRTC hardcoded to false"
        ((CHANGES++)) || true
      fi
    elif grep -q 'e\.rfb\.enableWebRTC=!1' "${SCREEN_BUNDLE}" 2>/dev/null; then
      skipped "screen.bundle.js (WebRTC already disabled)"
      ((SKIPPED++)) || true
    else
      warn "screen.bundle.js: unexpected enableWebRTC pattern — manual inspection needed"
      warn "  File: ${SCREEN_BUNDLE}"
      grep -o '.\{20\}enableWebRTC.\{30\}' "${SCREEN_BUNDLE}" 2>/dev/null | head -3 || true
    fi
  else
    warn "screen.bundle.js not found at ${SCREEN_BUNDLE}"
  fi

  # 3b: Patch ui-*.js
  local ui_js
  ui_js=$(find /usr/share/kasmvnc/www/assets -name "ui-*.js" 2>/dev/null | head -1)

  if [[ -z "${ui_js}" ]]; then
    warn "No ui-*.js found in /usr/share/kasmvnc/www/assets/"
    return 0
  fi

  local ui_needs_patch=false

  # Check for unpatched rfb.enableWebRTC assignment
  if grep -q 'o\.rfb\.enableWebRTC=o\.getSetting("enable_webrtc")' "${ui_js}" 2>/dev/null; then
    ui_needs_patch=true
  fi

  # Check for unpatched enableWebRTC setter
  if grep -q 'set enableWebRTC(e){this\._useUdp=e' "${ui_js}" 2>/dev/null; then
    ui_needs_patch=true
  fi

  if [[ "${ui_needs_patch}" == true ]]; then
    if [[ "${CHECK_ONLY}" == true ]]; then
      warn "Step 3b NEEDS FIX: ${ui_js} has WebRTC enabled"
    else
      backup_once "${ui_js}"

      # Force the rfb.enableWebRTC assignment to false
      sed -i \
        's/o\.rfb\.enableWebRTC=o\.getSetting("enable_webrtc")/o.rfb.enableWebRTC=!1/g' \
        "${ui_js}"

      # Neuter the enableWebRTC setter so nothing can re-enable it
      sed -i \
        's/set enableWebRTC(e){this\._useUdp=e/set enableWebRTC(e){this._useUdp=!1/' \
        "${ui_js}"

      ok "$(basename "${ui_js}") patched: WebRTC assignment + setter neutered"
      ((CHANGES++)) || true
    fi
  else
    # Check if already patched
    if grep -q 'o\.rfb\.enableWebRTC=!1' "${ui_js}" 2>/dev/null; then
      skipped "$(basename "${ui_js}") (WebRTC already disabled)"
      ((SKIPPED++)) || true
    else
      warn "$(basename "${ui_js}"): unexpected enableWebRTC pattern — manual inspection needed"
      grep -o '.\{20\}enableWebRTC.\{30\}' "${ui_js}" 2>/dev/null | head -3 || true
    fi
  fi
}

# ── Step 4: Parallel Works select-de.sh override ────────────────────────────

fix_select_de() {
  info "Step 4: Checking select-de.sh override..."

  if [[ ! -f "${SELECT_DE}" ]]; then
    info "select-de.sh not found (possibly different KasmVNC version). Skipping."
    return 0
  fi

  # Check if already a no-op
  if grep -qx "exit 0" "${SELECT_DE}" 2>/dev/null && \
     [[ $(wc -l < "${SELECT_DE}") -le 3 ]]; then
    if [[ "${FORCE}" != true ]]; then
      skipped "select-de.sh (already a no-op)"
      ((SKIPPED++)) || true
      return 0
    fi
  fi

  if [[ "${CHECK_ONLY}" == true ]]; then
    warn "Step 4 NEEDS FIX: select-de.sh needs PW override (exit 0)"
    return 0
  fi

  backup_once "${SELECT_DE}"

  cat > "${SELECT_DE}" << 'EOF'
#!/bin/sh
exit 0
EOF
  chmod +x "${SELECT_DE}"

  ok "select-de.sh replaced with no-op for Parallel Works compatibility"
  ((CHANGES++)) || true
}

# ── Execute all fixes ────────────────────────────────────────────────────────

fix_ssl_cert
echo ""
fix_vnc_yaml
echo ""
fix_javascript_client
echo ""
fix_select_de

# ── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo "=========================================="
echo " Summary"
echo "=========================================="

if [[ "${CHECK_ONLY}" == true ]]; then
  info "Dry-run mode — no changes were made."
  if [[ ${CHANGES} -gt 0 ]] || [[ ${ERRORS} -gt 0 ]]; then
    warn "Issues detected. Run without --check to apply fixes."
  else
    ok "All KasmVNC OpenSSL 3.5.x fixes are already applied."
  fi
else
  echo -e "  Changes applied: ${GREEN}${CHANGES}${NC}"
  echo -e "  Already applied: ${CYAN}${SKIPPED}${NC}"
  echo -e "  Errors:          ${RED}${ERRORS}${NC}"
  echo ""
  if [[ ${CHANGES} -gt 0 ]]; then
    info "Fixes applied. Restart any running VNC sessions for changes to take effect."
    info "  vncserver -kill :<display>"
    info "  vncserver :<display> -disableBasicAuth -xstartup ~/.vnc/kasm-xstartup ..."
  fi
  if [[ ${ERRORS} -gt 0 ]]; then
    err "Some fixes failed — review output above."
    exit 1
  fi
fi

ok "Done."
