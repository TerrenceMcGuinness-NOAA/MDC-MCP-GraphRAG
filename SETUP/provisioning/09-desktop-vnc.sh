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

configure_user_vnc_files() {
    local username="$1"
    local user_home="/home/${username}"
    local vnc_dir="${user_home}/.vnc"

    # Create VNC directory
    mkdir -p "${vnc_dir}"
    chown "${username}:${username}" "${vnc_dir}"
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
    chown "${username}:${username}" "${vnc_dir}/xstartup"

    # Create VNC config file
    cat > "${vnc_dir}/config" << EOFCONFIG
geometry=${KASMVNC_GEOMETRY}
depth=${KASMVNC_DEPTH}
EOFCONFIG
    chown "${username}:${username}" "${vnc_dir}/config"
    chmod 644 "${vnc_dir}/config"

    # Create KasmVNC configuration (only used by KasmVNC builds)
    cat > "${vnc_dir}/kasmvnc.yaml" << 'EOFKASM'
# KasmVNC Configuration for MCP RAG Development Environment

logging:
  log_writer_name: all
  log_dest: logfile
  level: 30

network:
  ssl:
    pem_certificate: /etc/pki/tls/private/kasmvnc.pem
    pem_key: /etc/pki/tls/private/kasmvnc.pem
    require_ssl: true

desktop:
  allow_resize: true

pointer:
  enabled: true
EOFKASM
    chown "${username}:${username}" "${vnc_dir}/kasmvnc.yaml"
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
Group=%i
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

write_per_user_kasmvnc_configs() {
    local display_num=${KASMVNC_DISPLAY_START}

    for username in "${PROVISION_USERS[@]}"; do
        if ! id "${username}" &>/dev/null; then
            log_warning "User ${username} does not exist; skipping VNC config"
            display_num=$((display_num + 1))
            continue
        fi

        configure_user_vnc_files "${username}"

        cat > "/etc/kasmvnc/${username}.conf" << EOF
VNCDISPLAY=:${display_num}
GEOMETRY=${KASMVNC_GEOMETRY}
DEPTH=${KASMVNC_DEPTH}
EOF

        log_info "Configured KasmVNC for ${username} on :${display_num}"
        display_num=$((display_num + 1))
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
    if command -v vncserver &>/dev/null; then
        if vncserver -help 2>&1 | grep -qi "kasmvnc\|kasm"; then
            echo "kasmvnc"
        elif vncserver -help 2>&1 | grep -qi "tigervnc"; then
            echo "tigervnc"
        else
            echo "unknown"
        fi
    else
        echo "none"
    fi
}

VNC_TYPE=$(detect_vnc_type)
log_info "Detected VNC type: ${VNC_TYPE}"

################################################################################
# Install VNC Packages (if not installed)
################################################################################

if [[ "${VNC_TYPE}" == "none" ]]; then
    log_info "Installing VNC packages..."
    # Try KasmVNC first (preferred), fall back to TigerVNC
    if dnf install -y kasmvnc 2>/dev/null; then
        VNC_TYPE="kasmvnc"
    else
        dnf install -y tigervnc-server novnc python3-websockify xterm twm --allowerasing || {
            log_warning "Some VNC packages failed to install"
        }
        VNC_TYPE="tigervnc"
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
                for username in "${PROVISION_USERS[@]}"; do
                        if id "${username}" &>/dev/null; then
                                usermod -a -G kasmvnc-cert "${username}" || true
                        fi
                done
                log_info "Added provisioned users to kasmvnc-cert group"
        fi

        install_kasmvnc_systemd_template
        write_per_user_kasmvnc_configs
        enable_autostart_users
        prevent_legacy_vnc_conflicts

        log_success "KasmVNC multi-user configuration complete"

################################################################################
# TigerVNC Configuration (fallback)
################################################################################

elif [[ "${VNC_TYPE}" == "tigervnc" ]]; then
    log_subsection "Configuring TigerVNC"
    
    # Create VNC directory
    su - "${USER_NAME}" -c "mkdir -p ${VNC_DIR}"
    
    # Set VNC password (default: mcp2025vnc)
    if [[ ! -f "${VNC_DIR}/passwd" ]]; then
        log_info "Setting default VNC password..."
        su - "${USER_NAME}" -c "echo 'mcp2025vnc' | vncpasswd -f > ${VNC_DIR}/passwd"
        chmod 600 "${VNC_DIR}/passwd"
        chown "${USER_NAME}:${USER_NAME}" "${VNC_DIR}/passwd"
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
    chown "${USER_NAME}:${USER_NAME}" "${VNC_DIR}/xstartup"
    
    # Create VNC config
    cat > "${VNC_DIR}/config" << 'EOFCONFIG'
geometry=1920x1080
depth=24
localhost=no
EOFCONFIG
    chown "${USER_NAME}:${USER_NAME}" "${VNC_DIR}/config"
    
    # SSL Certificate for noVNC
    CERT_PATH="${USER_HOME}/novnc.pem"
    if [[ ! -f "${CERT_PATH}" ]]; then
        log_info "Generating self-signed SSL certificate for noVNC..."
        /usr/bin/openssl req -x509 -nodes -newkey rsa:2048 \
            -keyout "${CERT_PATH}" -out "${CERT_PATH}" \
            -days 365 -subj "/CN=localhost" 2>/dev/null || log_warning "Certificate generation failed"
        chown "${USER_NAME}:${USER_NAME}" "${CERT_PATH}"
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
Group=${USER_NAME}
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
Group=${USER_NAME}
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
chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME}/bin"

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
