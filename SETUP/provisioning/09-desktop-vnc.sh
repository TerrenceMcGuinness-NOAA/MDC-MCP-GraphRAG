#!/bin/bash
################################################################################
# 09-desktop-vnc.sh - KasmVNC/TigerVNC remote desktop setup
# Part of modular provisioning system v4.2.0
#
# UPDATED (2026-03-12): KasmVNC is now primary. PW start-template-v3.sh handles
# KasmVNC natively (display selection, port allocation, nginx proxy, xstartup).
# This script ensures: MATE desktop installed, NVIDIA GPU crash prevented,
# kasmvnc-cert group membership, and user VNC config files in place.
#
# Supports KasmVNC (primary) and TigerVNC (fallback)
#
# Rocky 9 NVIDIA GPU workaround (TWO layers):
#   1. System-level: Disable libnvidia-egl-gbm.so.1 (prevents GlxExtensionInit
#      segfault in all VNC servers, including PW's own start-template-v3.sh)
#   2. Per-session: -extension GLX flag (backup, applied in helper scripts)
#   PW start-template-v3.sh uses -disableBasicAuth for auth-free desktop access.
#
# PW Integration:
#   PW's start-template-v3.sh handles KasmVNC lifecycle:
#     - Allocates display via port probing
#     - Opens kasmvnc_port via `pw agent open-port`
#     - Starts nginx wrapper on service_port proxying to kasmvnc_port
#     - Creates kasm-xstartup with DE auto-detection
#   This script pre-configures the system so PW's template works cleanly.
#
# Usage after provisioning:
#   PW Desktop: Start via PW portal (automatic)
#   Manual:     ~/bin/vnc-start.sh
#   Stop:       vncserver -kill :N
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "Remote Desktop (KasmVNC/VNC) Setup"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/user_config.sh"

usage() {
    cat << 'EOF'
Usage:
  sudo ./09-desktop-vnc.sh                    # Configure all PROVISION_USERS
  sudo ./09-desktop-vnc.sh --user <name>     # Configure a specific user (repeatable)
  sudo ./09-desktop-vnc.sh --user <name> --enable-now
  sudo ./09-desktop-vnc.sh --user <name> --display <N>
    sudo ./09-desktop-vnc.sh --status          # Print current display/unit status (no changes)

Options:
  --user <username>     Configure only this user (can be repeated)
  --display <N>         Force display number :N (only valid with a single --user)
  --enable-now          systemctl enable --now kasmvnc@<user>.service for targeted users
    --status              Print current display assignment + unit state; no changes
  -h, --help            Show this help
EOF
}

TARGET_USERS=()
ENABLE_NOW=false
FORCED_DISPLAY=""
STATUS_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user)
            [[ $# -ge 2 ]] || { log_error "--user requires a username"; exit 2; }
            TARGET_USERS+=("$2")
            shift 2
            ;;
        --display)
            [[ $# -ge 2 ]] || { log_error "--display requires a number"; exit 2; }
            FORCED_DISPLAY="$2"
            shift 2
            ;;
        --enable-now)
            ENABLE_NOW=true
            shift
            ;;
        --status)
            STATUS_ONLY=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit 2
            ;;
    esac
done

if [[ -n "${FORCED_DISPLAY}" ]]; then
    if [[ ${#TARGET_USERS[@]} -ne 1 ]]; then
        log_error "--display requires exactly one --user"
        exit 2
    fi
    if ! [[ "${FORCED_DISPLAY}" =~ ^[0-9]+$ ]]; then
        log_error "--display must be an integer (got: ${FORCED_DISPLAY})"
        exit 2
    fi
fi

USERS_TO_CONFIG=()
if [[ ${#TARGET_USERS[@]} -gt 0 ]]; then
    USERS_TO_CONFIG=("${TARGET_USERS[@]}")
else
    USERS_TO_CONFIG=("${PROVISION_USERS[@]}")
fi

print_user_status() {
    local username="$1"
    local conf="/etc/kasmvnc/${username}.conf"
    local display_num=""
    local kasm_port=""
    local rfb_port=""
    local enabled_state="n/a"
    local active_state="n/a"

    if [[ -f "${conf}" ]]; then
        display_num=$(read_display_from_user_conf "${username}" 2>/dev/null || true)
    fi

    if [[ -n "${display_num}" ]]; then
        kasm_port=$((8443 + display_num))
        rfb_port=$((5900 + display_num))
    fi

    # Best-effort unit state; if systemd/unit is missing, these will return errors which we ignore.
    enabled_state=$(systemctl is-enabled "kasmvnc@${username}.service" 2>/dev/null || true)
    active_state=$(systemctl is-active "kasmvnc@${username}.service" 2>/dev/null || true)

    if [[ -f "${conf}" ]]; then
        if [[ -n "${display_num}" ]]; then
            echo "${username}: :${display_num} (kasm web port ${kasm_port}, rfb ${rfb_port}) unit enabled=${enabled_state} active=${active_state}"
        else
            echo "${username}: config present but VNCDISPLAY missing; unit enabled=${enabled_state} active=${active_state}"
        fi
    else
        echo "${username}: not configured (no /etc/kasmvnc/${username}.conf); unit enabled=${enabled_state} active=${active_state}"
    fi
}

print_status_report() {
    log_subsection "KasmVNC Status (read-only)"

    if [[ ${#TARGET_USERS[@]} -gt 0 ]]; then
        for username in "${USERS_TO_CONFIG[@]}"; do
            print_user_status "${username}"
        done
        return 0
    fi

    # No explicit --user: summarize configured users first (from /etc/kasmvnc)
    if compgen -G "/etc/kasmvnc/*.conf" > /dev/null; then
        local conf
        local username
        for conf in /etc/kasmvnc/*.conf; do
            username=$(basename "${conf}" .conf)
            print_user_status "${username}"
        done
    else
        log_info "No /etc/kasmvnc/*.conf files found"
    fi
}



configure_user_vnc_files() {
    local username="$1"
    local user_home="/home/${username}"
    local vnc_dir="${user_home}/.vnc"
    local user_group
    user_group=$(get_user_group "${username}")

    # Create VNC directory
    mkdir -p "${vnc_dir}"
    chown "${username}:${user_group}" "${vnc_dir}"
    chmod 700 "${vnc_dir}"

    # Create VNC xstartup script for MATE
    # PW's start-template-v3.sh generates its own kasm-xstartup with DE detection.
    # This xstartup is used for manual/systemd VNC starts outside PW.
    cat > "${vnc_dir}/xstartup" << 'EOFVNC'
#!/bin/bash
# KasmVNC/VNC Desktop Startup Script - MATE Desktop
# Used for manual/systemd VNC starts. PW uses its own kasm-xstartup.

export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=MATE
export XDG_SESSION_DESKTOP=mate
export GDK_BACKEND=x11
export LIBGL_ALWAYS_SOFTWARE=1

eval $(/usr/bin/dbus-launch --sh-syntax --exit-with-session)
export DBUS_SESSION_BUS_ADDRESS

exec /usr/bin/mate-session
EOFVNC
    chmod +x "${vnc_dir}/xstartup"
    chown "${username}:${user_group}" "${vnc_dir}/xstartup"

    # Create VNC config file
    cat > "${vnc_dir}/config" << EOFCONFIG
geometry=${KASMVNC_GEOMETRY}
depth=${KASMVNC_DEPTH}
EOFCONFIG
    chown "${username}:${user_group}" "${vnc_dir}/config"
    chmod 644 "${vnc_dir}/config"

    # Create KasmVNC configuration
    # PW start-template-v3.sh overrides websocket_port and ssl at runtime,
    # but this provides sane defaults for manual starts and systemd service.
    # require_ssl: false — PW's nginx wrapper handles TLS termination.
    # hw3d: false — prevents GPU acceleration issues on headless VNC contexts.
    cat > "${vnc_dir}/kasmvnc.yaml" << 'EOFKASM'
# KasmVNC Configuration for MCP RAG Development Environment
# PW start-template-v3.sh overrides ports/SSL at runtime via CLI flags.

desktop:
    resolution:
        width: 1920
        height: 1080
    allow_resize: true
    pixel_depth: 24
    gpu:
        hw3d: false

network:
    protocol: http
    interface: 0.0.0.0
    websocket_port: auto
    use_ipv4: true
    use_ipv6: false
    udp:
        public_ip: auto
        port: auto
        stun_server: auto
    ssl:
        require_ssl: false

user_session:
    new_session_disconnects_existing_exclusive_session: false
    concurrent_connections_prompt: false
    idle_timeout: never

keyboard:
    ignore_numlock: false
    raw_keyboard: false

pointer:
    enabled: true

runtime_configuration:
    allow_client_to_override_kasm_server_settings: true
    allow_override_standard_vnc_server_settings: true

logging:
    log_writer_name: all
    log_dest: logfile
EOFKASM
    chown "${username}:${user_group}" "${vnc_dir}/kasmvnc.yaml"
    chmod 644 "${vnc_dir}/kasmvnc.yaml"
}

install_kasmvnc_systemd_template() {
    log_subsection "Installing KasmVNC systemd template"

    mkdir -p /etc/kasmvnc

    cat > /etc/systemd/system/kasmvnc@.service << 'EOF'
[Unit]
Description=KasmVNC (TigerVNC) Server for user %i
After=network.target

[Service]
Type=simple
User=%i
# Note: Group removed - systemd uses user's primary group automatically
# Group=%i was causing failures when username != group (e.g., pwuser group)
WorkingDirectory=/home/%i

# Defaults (override in /etc/kasmvnc/%i.conf)
Environment=VNCDISPLAY=:1
Environment=GEOMETRY=1920x1080
Environment=DEPTH=24

EnvironmentFile=-/etc/kasmvnc/%i.conf

ExecStartPre=-/usr/bin/vncserver -kill ${VNCDISPLAY}
ExecStart=/usr/bin/vncserver ${VNCDISPLAY} -geometry ${GEOMETRY} -depth ${DEPTH} -fg
ExecStop=/usr/bin/vncserver -kill ${VNCDISPLAY}

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    log_success "Installed /etc/systemd/system/kasmvnc@.service"
}

read_display_from_user_conf() {
    local username="$1"
    local conf="/etc/kasmvnc/${username}.conf"
    [[ -f "${conf}" ]] || return 1
    local vncdisplay
    vncdisplay=$(grep -E '^VNCDISPLAY=:' "${conf}" | head -n 1 | cut -d= -f2)
    [[ -n "${vncdisplay}" ]] || return 1
    echo "${vncdisplay#:}"
}

# Status reporting must happen after helper functions are defined.
if [[ "${STATUS_ONLY}" == true ]]; then
    print_status_report
    exit 0
fi

display_taken_by_other_user() {
    local display_num="$1"
    local username="$2"
    local existing

    for conf in /etc/kasmvnc/*.conf; do
        [[ -e "${conf}" ]] || break
        if grep -qE "^VNCDISPLAY=:${display_num}$" "${conf}"; then
            existing=$(basename "${conf}" .conf)
            if [[ "${existing}" != "${username}" ]]; then
                return 0
            fi
        fi
    done

    return 1
}

is_display_in_use() {
    local display_num="$1"
    local rfb_port=$((5900 + display_num))
    local kasm_port=$((8443 + display_num))

    # Already allocated in an existing config
    if display_taken_by_other_user "${display_num}" "__probe__"; then
        return 0
    fi

    # Port-based detection (best-effort)
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE ":(${rfb_port}|${kasm_port})$"; then
        return 0
    fi

    return 1
}

allocate_next_free_display() {
    local start_num="$1"
    local max_tries=200
    local n

    for ((n=start_num; n<start_num+max_tries; n++)); do
        if ! is_display_in_use "${n}"; then
            echo "${n}"
            return 0
        fi
    done

    return 1
}

write_per_user_kasmvnc_configs() {
    local next_display_num=${KASMVNC_DISPLAY_START}
    local username
    local display_num
    local tls_mode

    for username in "${USERS_TO_CONFIG[@]}"; do
        if ! id "${username}" &>/dev/null; then
            log_warning "User ${username} does not exist; skipping VNC config"
            continue
        fi

        # Determine display
        if [[ -n "${FORCED_DISPLAY}" ]]; then
            display_num="${FORCED_DISPLAY}"

            if display_taken_by_other_user "${display_num}" "${username}"; then
                log_error "Display :${display_num} is already assigned to a different user"
                exit 2
            fi
        else
            # Idempotency: if this user already has a config, keep its display.
            if display_num=$(read_display_from_user_conf "${username}"); then
                :
            else
                display_num=$(allocate_next_free_display "${next_display_num}") || {
                    log_error "Unable to find a free display number starting at :${next_display_num}"
                    exit 1
                }
            fi
        fi

        # Bump pointer for subsequent allocations
        next_display_num=$((display_num + 1))

        configure_user_vnc_files "${username}"

        cat > "/etc/kasmvnc/${username}.conf" << EOF
VNCDISPLAY=:${display_num}
GEOMETRY=${KASMVNC_GEOMETRY}
DEPTH=${KASMVNC_DEPTH}
EOF

        log_info "Configured KasmVNC for ${username} on :${display_num}"
    done
}

enable_now_for_target_users() {
    local username
    for username in "${USERS_TO_CONFIG[@]}"; do
        if id "${username}" &>/dev/null; then
            systemctl enable --now "kasmvnc@${username}.service" 2>/dev/null || true
            log_info "Enabled/started kasmvnc@${username}.service"
        fi
    done
}

enable_autostart_users() {
    for username in "${KASMVNC_AUTOSTART_USERS[@]}"; do
        if id "${username}" &>/dev/null; then
            systemctl enable "kasmvnc@${username}.service" 2>/dev/null || true
            log_info "Enabled kasmvnc@${username}.service"
        fi
    done
}

prevent_legacy_vnc_conflicts() {
    # If an old TigerVNC unit is present/enabled it can kill the Kasm session.
    if systemctl list-unit-files | grep -q '^vncserver@1\.service'; then
        systemctl stop vncserver@1.service 2>/dev/null || true
        systemctl disable vncserver@1.service 2>/dev/null || true
        systemctl mask vncserver@1.service 2>/dev/null || true
        systemctl reset-failed vncserver@1.service 2>/dev/null || true
        log_info "Disabled/masked legacy vncserver@1.service to prevent display conflicts"
    fi
}

################################################################################
# Detect VNC Type
################################################################################

detect_vnc_type() {
    if ! command -v vncserver &>/dev/null; then
        echo "none"
        return 0
    fi

    # IMPORTANT: Do NOT run `vncserver -help`.
    # On some builds (notably KasmVNC), `-help` is not a valid option and will
    # start an interactive server session, potentially hanging on a prompt.

    # Prefer package detection when available.
    if command -v rpm &>/dev/null; then
        # On EL9, the RPM may be named kasmvncserver (common) rather than kasmvnc.
        if rpm -q kasmvncserver &>/dev/null || rpm -q kasmvnc &>/dev/null; then
            echo "kasmvnc"
            return 0
        fi
        if rpm -q tigervnc-server &>/dev/null; then
            echo "tigervnc"
            return 0
        fi

        # Also try to identify the owning RPM for the installed binaries.
        local owning
        owning=$(rpm -qf "${vncserver_path}" 2>/dev/null || true)
        if echo "${owning}" | grep -qi 'kasmvnc'; then
            echo "kasmvnc"
            return 0
        fi
        if echo "${owning}" | grep -qi 'tigervnc'; then
            echo "tigervnc"
            return 0
        fi
    fi

    # Fallback: inspect the installed vncserver wrapper script/binary.
    local vncserver_path
    vncserver_path=$(command -v vncserver)
    if grep -qiE 'kasmvnc|kasm' "${vncserver_path}" 2>/dev/null; then
        echo "kasmvnc"
        return 0
    fi
    if grep -qiE 'tigervnc' "${vncserver_path}" 2>/dev/null; then
        echo "tigervnc"
        return 0
    fi

    echo "unknown"
}

VNC_TYPE=$(detect_vnc_type)
log_info "Detected VNC type: ${VNC_TYPE}"

################################################################################
# Install VNC Packages (if not installed)
################################################################################

if [[ "${VNC_TYPE}" == "none" ]]; then
    log_info "Installing VNC packages..."
    # Try KasmVNC first (preferred), fall back to TigerVNC
    if dnf install -y kasmvncserver 2>/dev/null || dnf install -y kasmvnc 2>/dev/null; then
        VNC_TYPE="kasmvnc"
    else
        dnf install -y tigervnc-server novnc python3-websockify xterm twm --allowerasing || {
            log_warning "Some VNC packages failed to install"
        }
        VNC_TYPE="tigervnc"
    fi
fi

# If we couldn't positively detect but vncserver exists, try one more time using owning RPM.
if [[ "${VNC_TYPE}" == "unknown" ]]; then
    if command -v rpm &>/dev/null; then
        vncserver_path=$(command -v vncserver)
        owning=$(rpm -qf "${vncserver_path}" 2>/dev/null || true)
        if echo "${owning}" | grep -qi 'kasmvnc'; then
            VNC_TYPE="kasmvnc"
        elif echo "${owning}" | grep -qi 'tigervnc'; then
            VNC_TYPE="tigervnc"
        fi
        log_info "Refined VNC type via rpm -qf: ${VNC_TYPE} (${owning})"
    fi
fi

################################################################################
# Install MATE Desktop
################################################################################

log_info "Installing MATE desktop environment..."
dnf install -y mate-desktop mate-session-manager mate-panel mate-terminal caja \
    mate-settings-daemon marco mate-notification-daemon mate-control-center \
    mate-power-manager network-manager-applet 2>/dev/null || {
    log_warning "Some MATE packages failed to install"
}

################################################################################
# NVIDIA GPU Workaround (System-Level)
#
# Rocky 9 AWS GPU instances have libnvidia-egl-gbm.so.1 which causes a
# segfault in GlxExtensionInit when any VNC server (KasmVNC or TigerVNC)
# initializes GLX in a headless context. This affects:
#   - PW's start-template-v3.sh (which we can't modify per-session)
#   - Manual vncserver starts
#   - Systemd-managed VNC services
#
# Fix: Disable the library system-wide by renaming it. This is safe because:
#   - Headless VNC does not need EGL/GBM (software rendering via swrast)
#   - The real GPU is not used for VNC desktop rendering
#   - The symlink rename is trivially reversible
################################################################################

log_subsection "NVIDIA EGL/GBM Workaround"

NVIDIA_EGL_LIB="/lib64/libnvidia-egl-gbm.so.1"
NVIDIA_EGL_DISABLED="${NVIDIA_EGL_LIB}.disabled"

if [[ -L "${NVIDIA_EGL_LIB}" ]] || [[ -f "${NVIDIA_EGL_LIB}" ]]; then
    if [[ ! -e "${NVIDIA_EGL_DISABLED}" ]]; then
        mv "${NVIDIA_EGL_LIB}" "${NVIDIA_EGL_DISABLED}"
        log_success "Disabled ${NVIDIA_EGL_LIB} (renamed to .disabled) — prevents VNC GLX segfault"
    else
        log_info "NVIDIA EGL library already disabled (${NVIDIA_EGL_DISABLED} exists)"
        # Clean up: if both exist (e.g., dnf reinstalled the package), remove the active one
        if [[ -e "${NVIDIA_EGL_LIB}" ]]; then
            rm -f "${NVIDIA_EGL_LIB}"
            log_info "Removed re-created ${NVIDIA_EGL_LIB} (package may have restored it)"
        fi
    fi
elif [[ -e "${NVIDIA_EGL_DISABLED}" ]]; then
    log_info "NVIDIA EGL library already disabled — no action needed"
else
    log_info "No NVIDIA EGL library found — GPU workaround not needed"
fi

################################################################################
# KasmVNC Configuration
################################################################################

if [[ "${VNC_TYPE}" == "kasmvnc" ]]; then
    log_subsection "Configuring KasmVNC"

        # Add all provisioned users to kasmvnc-cert group (if it exists)
        # Required even with sslOnly=0: KasmVNC checks cert readability at startup
        if getent group kasmvnc-cert &>/dev/null; then
                for username in "${USERS_TO_CONFIG[@]}"; do
                        if id "${username}" &>/dev/null; then
                                usermod -a -G kasmvnc-cert "${username}" || true
                        fi
                done
                log_info "Added provisioned users to kasmvnc-cert group"
        fi

        # PW's start-template-v3.sh backs up select-de.sh and replaces it with
        # `exit 0` to skip DE selection prompts. Pre-apply this so the backup
        # (.bak) exists cleanly and PW's mv doesn't fail on repeated sessions.
        SELECT_DE="/usr/lib/kasmvncserver/select-de.sh"
        if [[ -f "${SELECT_DE}" ]] && ! [[ -f "${SELECT_DE}.bak" ]]; then
            cp "${SELECT_DE}" "${SELECT_DE}.bak"
            printf '#!/bin/sh\nexit 0\n' > "${SELECT_DE}"
            chmod +x "${SELECT_DE}"
            log_info "Pre-applied select-de.sh bypass for PW compatibility"
        fi

        install_kasmvnc_systemd_template
        write_per_user_kasmvnc_configs
        if [[ "${ENABLE_NOW}" == true ]]; then
            enable_now_for_target_users
        else
            # Preserve existing behavior: only autostart configured users when running in bulk mode.
            if [[ ${#TARGET_USERS[@]} -eq 0 ]]; then
                enable_autostart_users
            fi
        fi
        prevent_legacy_vnc_conflicts

        log_success "KasmVNC multi-user configuration complete"

################################################################################
# TigerVNC Configuration (fallback)
################################################################################

elif [[ "${VNC_TYPE}" == "tigervnc" ]]; then
    log_subsection "Configuring TigerVNC (Rocky 9 + NVIDIA GLX workaround)"

    USER_NAME=$(get_actual_user)
    USER_GROUP=$(get_user_group "${USER_NAME}")
    USER_HOME="/home/${USER_NAME}"
    VNC_DIR="${USER_HOME}/.vnc"
    
    # Create VNC directory
    su - "${USER_NAME}" -c "mkdir -p ${VNC_DIR}"
    
    # Set VNC password (used if connecting directly, not via PW noVNC bridge)
    if [[ ! -f "${VNC_DIR}/passwd" ]]; then
        log_info "Setting default VNC password..."
        su - "${USER_NAME}" -c "printf 'mcp2025vnc\nmcp2025vnc\nn\n' | vncpasswd"
        chmod 600 "${VNC_DIR}/passwd"
        chown "${USER_NAME}:${USER_GROUP}" "${VNC_DIR}/passwd"
        log_warning "Default VNC password set to 'mcp2025vnc' - please change with: vncpasswd"
    fi
    
    # Create VNC startup script — MATE Desktop with NVIDIA GLX workaround
    log_info "Creating VNC xstartup script..."
    cat > "${VNC_DIR}/xstartup" << 'EOFVNC'
#!/bin/bash
# TigerVNC Desktop Startup Script - MATE Desktop
# Rocky 9 + NVIDIA GPU node compatible

export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=MATE
export XDG_SESSION_DESKTOP=mate

eval $(/usr/bin/dbus-launch --sh-syntax --exit-with-session)
export DBUS_SESSION_BUS_ADDRESS

if command -v mate-session &> /dev/null; then
    exec /usr/bin/mate-session
elif command -v xfce4-session &> /dev/null; then
    exec /usr/bin/xfce4-session
else
    xsetroot -solid grey
    xterm -geometry 80x24+10+10 -ls -title "Terminal" &
    exec twm
fi
EOFVNC
    chmod +x "${VNC_DIR}/xstartup"
    chown "${USER_NAME}:${USER_GROUP}" "${VNC_DIR}/xstartup"
    
    # Create VNC config
    cat > "${VNC_DIR}/config" << 'EOFCONFIG'
geometry=1920x1080
depth=24
localhost=no
EOFCONFIG
    chown "${USER_NAME}:${USER_GROUP}" "${VNC_DIR}/config"

    # ── PW noVNC bridge auto-start helper ─────────────────────────────────
    # Parallel Works starts noVNC/websockify pointing at a dynamic VNC port.
    # This helper detects that port and starts Xvnc (with the GLX workaround)
    # plus a MATE session on it.  Called from ~/bin/vnc-start.sh or manually.
    # ─────────────────────────────────────────────────────────────────────────
    cat > "${USER_HOME}/bin/pw-vnc-autostart.sh" << 'EOFPW'
#!/bin/bash
# pw-vnc-autostart.sh — Detect PW noVNC bridge target port, start Xvnc + MATE
# Rocky 9 / TigerVNC 1.15.0 / NVIDIA GPU node compatible
set -euo pipefail

# Detect the VNC port that the PW noVNC bridge (websockify) expects
VNC_PORT=$(ps aux | grep -oP '(?<=--vnc )[^ ]+:\K\d+' | head -1 || true)
if [[ -z "${VNC_PORT}" ]]; then
    echo "[WARN] Could not detect PW noVNC bridge target port."
    echo "       Falling back to display :48 (port 5948)."
    VNC_PORT=5948
fi

DISPLAY_NUM=$((VNC_PORT - 5900))
echo "[OK] PW noVNC bridge expects VNC on port ${VNC_PORT} (display :${DISPLAY_NUM})"

# Kill any existing Xvnc on this display
kill $(lsof -ti :"${VNC_PORT}" 2>/dev/null) 2>/dev/null || true
sleep 1

# Start Xvnc with NVIDIA GLX workaround + no auth for PW bridge
#   -extension GLX : prevents segfault in libnvidia-egl-gbm.so.1
#   -SecurityTypes None : PW noVNC bridge does not send VNC passwords
#   -pn : skip broken X11 access control (peer not required)
Xvnc :"${DISPLAY_NUM}" \
    -geometry 1920x1080 \
    -depth 24 \
    -SecurityTypes None \
    -extension GLX \
    -pn &
XVNC_PID=$!
sleep 2

if ! kill -0 "${XVNC_PID}" 2>/dev/null; then
    echo "[ERROR] Xvnc failed to start. Check for port conflicts."
    exit 1
fi
echo "[OK] Xvnc running (PID ${XVNC_PID}) on :${DISPLAY_NUM}"

# Launch MATE desktop session
export DISPLAY=:${DISPLAY_NUM}
nohup mate-session &>/tmp/mate-vnc-${DISPLAY_NUM}.log &
MATE_PID=$!
sleep 3

if kill -0 "${MATE_PID}" 2>/dev/null; then
    echo "[OK] MATE session running (PID ${MATE_PID})"
    echo "[OK] VNC desktop ready on display :${DISPLAY_NUM} (port ${VNC_PORT})"
else
    echo "[WARN] MATE session may have failed — check /tmp/mate-vnc-${DISPLAY_NUM}.log"
fi
EOFPW
    chmod +x "${USER_HOME}/bin/pw-vnc-autostart.sh"
    chown "${USER_NAME}:${USER_GROUP}" "${USER_HOME}/bin/pw-vnc-autostart.sh"
    
    # Create TigerVNC systemd services (for direct use without PW)
    log_subsection "Creating TigerVNC Systemd Services"
    
    # Note: ExecStart uses -extension GLX to work around NVIDIA EGL segfault
    # and -SecurityTypes None for PW noVNC bridge compatibility
    cat > /etc/systemd/system/vncserver@.service << EOF
[Unit]
Description=TigerVNC Server for display %i (Rocky 9 + NVIDIA GLX workaround)
After=syslog.target network.target

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_GROUP}
WorkingDirectory=${USER_HOME}

ExecStartPre=-/bin/sh -c 'kill \$(lsof -ti :\$((5900 + %i))) 2>/dev/null || :'
ExecStart=/usr/bin/Xvnc :%i -geometry 1920x1080 -depth 24 -SecurityTypes None -extension GLX -pn
ExecStop=-/bin/sh -c 'kill \$(lsof -ti :\$((5900 + %i))) 2>/dev/null || :'

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    
    log_success "TigerVNC configuration complete (Rocky 9 + NVIDIA GLX workaround)"
fi

################################################################################
# Create VNC Helper Script
################################################################################

log_subsection "Creating VNC Helper Script"

USER_NAME=$(get_actual_user)
USER_GROUP=$(get_user_group "${USER_NAME}")
USER_HOME="/home/${USER_NAME}"

mkdir -p "${USER_HOME}/bin"

cat > "${USER_HOME}/bin/vnc-start.sh" << 'EOFHELPER'
#!/bin/bash
################################################################################
# vnc-start.sh - Start VNC server with proper configuration
# v4.2.0 - KasmVNC primary, TigerVNC fallback
#
# For PW (Parallel Works) desktop sessions, PW's start-template-v3.sh handles
# KasmVNC lifecycle automatically. This script is for MANUAL VNC sessions
# (SSH-only access, debugging, or when PW portal is not available).
#
# Usage: vnc-start.sh [display] [geometry]
#   display:  VNC display number (default: 1)
#   geometry: Screen resolution (default: 1920x1080)
#
# Examples:
#   vnc-start.sh              # Start on :1 with 1920x1080
#   vnc-start.sh 2            # Start on :2 with 1920x1080
#   vnc-start.sh 1 2560x1440  # Start on :1 with 2560x1440
################################################################################

DISPLAY_NUM="${1:-1}"
GEOMETRY="${2:-1920x1080}"
DEPTH=24

# Warn if PW session is active — PW manages its own VNC
if pgrep -f 'start-template-v3' &>/dev/null; then
    echo "[WARN] PW desktop session detected (start-template-v3.sh running)."
    echo "[WARN] PW manages KasmVNC automatically. This starts an ADDITIONAL session."
    echo ""
fi

# Detect VNC type (KasmVNC preferred)
if command -v kasmvncserver &>/dev/null || rpm -q kasmvncserver &>/dev/null; then
    VNC_TYPE="kasmvnc"
    PORT=$((8443 + DISPLAY_NUM))
elif command -v Xvnc &>/dev/null; then
    VNC_TYPE="tigervnc"
    PORT=$((5900 + DISPLAY_NUM))
else
    echo "[ERROR] No VNC server installed (kasmvncserver or Xvnc required)"
    exit 1
fi

echo "Starting ${VNC_TYPE} on display :${DISPLAY_NUM} (port ${PORT})..."
echo "Resolution: ${GEOMETRY}"
echo ""

if [[ "${VNC_TYPE}" == "kasmvnc" ]]; then
    # Kill existing session if running
    vncserver -kill ":${DISPLAY_NUM}" 2>/dev/null || true
    sleep 1

    # Build KasmVNC flags for manual (non-PW) usage
    #   -disableBasicAuth : no username/password prompt
    #   -sslOnly 0        : allow plain HTTP (PW nginx expects HTTP upstream)
    #   -extension GLX    : backup NVIDIA crash prevention (system lib is disabled
    #                        during provisioning, but belt-and-suspenders)
    KASM_FLAGS="-geometry ${GEOMETRY} -depth ${DEPTH} -disableBasicAuth -sslOnly 0 -extension GLX"

    # KasmVNC requires kasmvnc-cert group membership even with SSL off
    if id -nG | grep -qw kasmvnc-cert; then
        vncserver ":${DISPLAY_NUM}" ${KASM_FLAGS}
    else
        echo "[WARN] Not in kasmvnc-cert group. Trying sg wrapper..."
        sg kasmvnc-cert -c "vncserver :${DISPLAY_NUM} ${KASM_FLAGS}"
    fi

    echo ""
    echo "[OK] KasmVNC started successfully!"
    echo ""
    echo "Access via browser (no password needed):"
    echo "  1. SSH tunnel:  ssh -L ${PORT}:localhost:${PORT} \$(hostname) -N"
    echo "  2. Browser:     http://localhost:${PORT}"
    echo ""
    echo "To stop:  vncserver -kill :${DISPLAY_NUM}"
else
    # TigerVNC fallback with NVIDIA GLX workaround
    # Kill any existing Xvnc on this port
    kill $(lsof -ti :"${PORT}" 2>/dev/null) 2>/dev/null || true
    sleep 1

    # Start Xvnc directly (not via deprecated vncserver wrapper)
    #   -extension GLX    : prevent NVIDIA EGL segfault on GPU nodes
    #   -SecurityTypes None : no VNC password required
    #   -pn               : skip broken X11 access control
    Xvnc ":${DISPLAY_NUM}" -geometry "${GEOMETRY}" -depth "${DEPTH}" \
         -SecurityTypes None -extension GLX -pn &
    XVNC_PID=$!
    sleep 2

    if ! kill -0 "${XVNC_PID}" 2>/dev/null; then
        echo "[ERROR] Xvnc failed to start on :${DISPLAY_NUM}"
        exit 1
    fi

    # Launch MATE desktop on this display
    export DISPLAY=":${DISPLAY_NUM}"
    export GDK_BACKEND=x11
    export LIBGL_ALWAYS_SOFTWARE=1
    nohup mate-session &>/tmp/mate-vnc-${DISPLAY_NUM}.log &
    sleep 3

    echo ""
    echo "[OK] TigerVNC started successfully!"
    echo "Xvnc PID: ${XVNC_PID}"
    echo "Display:  :${DISPLAY_NUM} (port ${PORT})"
    echo ""
    echo "To access from your local machine:"
    echo "  1. SSH tunnel:  ssh -L ${PORT}:localhost:${PORT} \$(hostname) -N"
    echo "  2. VNC client:  localhost:${PORT}"
    echo ""
    echo "To stop:  kill ${XVNC_PID}"
fi
EOFHELPER

chmod +x "${USER_HOME}/bin/vnc-start.sh"
chown -R "$(get_ownership "${USER_NAME}")" "${USER_HOME}/bin"

################################################################################
# Install Google Chrome (for web development/testing)
################################################################################

log_subsection "Installing Google Chrome"

if ! command_exists google-chrome; then
    log_info "Installing Google Chrome..."
    wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm -O /tmp/chrome.rpm 2>/dev/null && \
    dnf install -y /tmp/chrome.rpm 2>/dev/null || log_warning "Google Chrome installation failed"
    rm -f /tmp/chrome.rpm
else
    log_info "Google Chrome already installed"
fi

################################################################################
# Summary
################################################################################

log_success "Remote Desktop setup complete"
echo ""
log_info "VNC Type: ${VNC_TYPE}"

if [[ "${VNC_TYPE}" == "kasmvnc" ]]; then
    log_info ""
    log_info "=== KasmVNC (Primary) ==="
    log_info ""
    log_info "PW Desktop: Automatic via PW portal (start-template-v3.sh)"
    log_info ""
    log_info "Manual start (SSH-only):"
    log_info "  ~/bin/vnc-start.sh"
    log_info "  Then SSH tunnel + browser: http://localhost:8444"
    log_info ""
    log_info "NVIDIA GPU: libnvidia-egl-gbm.so.1 disabled (system-level)"
    log_info "Stop VNC:   vncserver -kill :1"
    log_info ""
else
    log_info ""
    log_info "=== TigerVNC (Fallback) ==="
    log_info ""
    log_info "Start: ~/bin/vnc-start.sh"
    log_info "       ssh -L 5901:localhost:5901 user@host -N"
    log_info ""
fi

exit 0
