#!/bin/bash
################################################################################
# 09-desktop-vnc.sh - KasmVNC/VNC remote desktop setup
# Part of modular provisioning system v4.0.0
#
# Supports both KasmVNC (preferred) and TigerVNC
# KasmVNC provides built-in HTTPS web interface on port 8443+display
#
# Usage after provisioning:
#   Start VNC:  sg kasmvnc-cert -c "vncserver :1 -geometry 1920x1080 -depth 24"
#   Stop VNC:   vncserver -kill :1
#   SSH tunnel: ssh -L 8444:localhost:8444 user@host -N
#   Access:     https://localhost:8444
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
    cat > "${vnc_dir}/xstartup" << 'EOFVNC'
#!/bin/bash
# KasmVNC Desktop Startup Script - MATE Desktop

export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=MATE
export XDG_SESSION_DESKTOP=mate

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

    # Create KasmVNC configuration (only used by KasmVNC builds)
    # For prototype cohort access via SSH port forwarding, keep origin HTTP.
    cat > "${vnc_dir}/kasmvnc.yaml" << 'EOFKASM'
# KasmVNC Configuration for MCP RAG Development Environment

logging:
    log_writer_name: all
    log_dest: logfile
    level: 30

network:
    ssl:
        require_ssl: false

desktop:
    allow_resize: true

pointer:
    enabled: true
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
# KasmVNC Configuration
################################################################################

if [[ "${VNC_TYPE}" == "kasmvnc" ]]; then
    log_subsection "Configuring KasmVNC"

        # Add all provisioned users to kasmvnc-cert group (if it exists)
        if getent group kasmvnc-cert &>/dev/null; then
                for username in "${USERS_TO_CONFIG[@]}"; do
                        if id "${username}" &>/dev/null; then
                                usermod -a -G kasmvnc-cert "${username}" || true
                        fi
                done
                log_info "Added provisioned users to kasmvnc-cert group"
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
    log_subsection "Configuring TigerVNC"

    USER_NAME=$(get_actual_user)
    USER_GROUP=$(get_user_group "${USER_NAME}")
    USER_HOME="/home/${USER_NAME}"
    VNC_DIR="${USER_HOME}/.vnc"
    
    # Create VNC directory
    su - "${USER_NAME}" -c "mkdir -p ${VNC_DIR}"
    
    # Set VNC password (default: mcp2025vnc)
    if [[ ! -f "${VNC_DIR}/passwd" ]]; then
        log_info "Setting default VNC password..."
        su - "${USER_NAME}" -c "echo 'mcp2025vnc' | vncpasswd -f > ${VNC_DIR}/passwd"
        chmod 600 "${VNC_DIR}/passwd"
        chown "${USER_NAME}:${USER_GROUP}" "${VNC_DIR}/passwd"
        log_warning "Default VNC password set to 'mcp2025vnc' - please change with: vncpasswd"
    fi
    
    # Create VNC startup script
    log_info "Creating VNC xstartup script..."
    cat > "${VNC_DIR}/xstartup" << 'EOFVNC'
#!/bin/bash
# TigerVNC Desktop Startup Script - MATE Desktop

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
    
    # SSL Certificate for noVNC
    CERT_PATH="${USER_HOME}/novnc.pem"
    if [[ ! -f "${CERT_PATH}" ]]; then
        log_info "Generating self-signed SSL certificate for noVNC..."
        /usr/bin/openssl req -x509 -nodes -newkey rsa:2048 \
            -keyout "${CERT_PATH}" -out "${CERT_PATH}" \
            -days 365 -subj "/CN=localhost" 2>/dev/null || log_warning "Certificate generation failed"
        chown "${USER_NAME}:${USER_GROUP}" "${CERT_PATH}"
    fi
    
    # Create TigerVNC systemd services
    log_subsection "Creating TigerVNC Systemd Services"
    
    cat > /etc/systemd/system/vncserver@.service << EOF
[Unit]
Description=TigerVNC Server for display %i
After=syslog.target network.target

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_GROUP}
WorkingDirectory=${USER_HOME}

ExecStartPre=-/bin/sh -c '/usr/bin/vncserver -kill :%i > /dev/null 2>&1 || :'
ExecStart=/usr/bin/vncserver :%i -geometry 1920x1080 -depth 24 -fg
ExecStop=/usr/bin/vncserver -kill :%i

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    # Websockify service (noVNC proxy)
    cat > /etc/systemd/system/websockify.service << EOF
[Unit]
Description=Websockify for noVNC (Browser-based VNC)
After=network.target vncserver@1.service
Wants=vncserver@1.service

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_GROUP}
ExecStart=/usr/bin/websockify --web=/usr/share/novnc/ --cert=${CERT_PATH} 6080 localhost:5901
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    
    log_success "TigerVNC configuration complete"
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
# 
# Usage: vnc-start.sh [display] [geometry]
#   display:  VNC display number (default: 1)
#   geometry: Screen resolution (default: 1920x1080)
#
# Examples:
#   vnc-start.sh           # Start on :1 with 1920x1080
#   vnc-start.sh 2         # Start on :2 with 1920x1080  
#   vnc-start.sh 1 2560x1440  # Start on :1 with 2560x1440
################################################################################

DISPLAY_NUM="${1:-1}"
GEOMETRY="${2:-1920x1080}"
DEPTH=24

# Detect VNC type
if vncserver -help 2>&1 | grep -qi "kasmvnc\|kasm"; then
    VNC_TYPE="kasmvnc"
    PORT=$((8443 + DISPLAY_NUM))
else
    VNC_TYPE="tigervnc"
    PORT=$((5900 + DISPLAY_NUM))
fi

echo "Starting ${VNC_TYPE} on display :${DISPLAY_NUM} (port ${PORT})..."
echo "Resolution: ${GEOMETRY}"
echo ""

# Kill existing session if running
vncserver -kill ":${DISPLAY_NUM}" 2>/dev/null || true
sleep 1

# Start VNC
if [[ "${VNC_TYPE}" == "kasmvnc" ]]; then
    # KasmVNC requires kasmvnc-cert group for SSL access
    if groups | grep -q kasmvnc-cert; then
        vncserver ":${DISPLAY_NUM}" -geometry "${GEOMETRY}" -depth "${DEPTH}"
    else
        echo "Running with kasmvnc-cert group..."
        sg kasmvnc-cert -c "vncserver :${DISPLAY_NUM} -geometry ${GEOMETRY} -depth ${DEPTH}"
    fi
    
    echo ""
    echo "VNC started successfully!"
    echo ""
    echo "To access from your local machine:"
    echo "  1. SSH tunnel:  ssh -L ${PORT}:localhost:${PORT} \$(hostname) -N"
    echo "  2. Browser:     https://localhost:${PORT}"
    echo ""
    echo "To stop:  vncserver -kill :${DISPLAY_NUM}"
else
    vncserver ":${DISPLAY_NUM}" -geometry "${GEOMETRY}" -depth "${DEPTH}"
    
    echo ""
    echo "VNC started successfully!"
    echo ""
    echo "To access from your local machine:"
    echo "  1. SSH tunnel:  ssh -L ${PORT}:localhost:${PORT} \$(hostname) -N"
    echo "  2. VNC client:  localhost:${PORT}"
    echo ""
    echo "To stop:  vncserver -kill :${DISPLAY_NUM}"
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
    log_info "=== KasmVNC Quick Start ==="
    log_info ""
    log_info "Start VNC:"
    log_info "  sg kasmvnc-cert -c \"vncserver :1 -geometry 1920x1080 -depth 24\""
    log_info "  Or use: ~/bin/vnc-start.sh"
    log_info ""
    log_info "SSH Port Forward (from local machine):"
    log_info "  ssh -L 8444:localhost:8444 user@host -N"
    log_info ""
    log_info "Access in browser:"
    log_info "  https://localhost:8444"
    log_info ""
    log_info "Stop VNC:"
    log_info "  vncserver -kill :1"
    log_info ""
else
    log_info ""
    log_info "=== TigerVNC Quick Start ==="
    log_info ""
    log_info "Start VNC:"
    log_info "  vncserver :1 -geometry 1920x1080 -depth 24"
    log_info ""
    log_info "SSH Port Forward (from local machine):"
    log_info "  ssh -L 5901:localhost:5901 user@host -N"
    log_info ""
    log_info "VNC Password: mcp2025vnc"
    log_info ""
fi

exit 0
