#!/bin/bash
################################################################################
# 09-desktop-vnc.sh - VNC/noVNC remote desktop setup
# Part of modular provisioning system v4.0.0
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "Remote Desktop (VNC/noVNC) Setup"

USER_NAME=$(get_actual_user)
VNC_DIR="/home/${USER_NAME}/.vnc"

################################################################################
# Install VNC Packages
################################################################################

log_info "Installing VNC and noVNC packages..."
dnf install -y tigervnc-server novnc python3-websockify xterm twm --allowerasing || {
    log_warning "Some VNC packages failed to install"
}

################################################################################
# Install MATE Desktop
################################################################################

log_info "Installing MATE desktop environment..."
dnf install -y mate-desktop mate-session-manager mate-panel mate-terminal caja \
    mate-settings-daemon marco mate-notification-daemon mate-control-center \
    mate-power-manager network-manager-applet || {
    log_warning "Some MATE packages failed to install"
}

################################################################################
# Configure VNC
################################################################################

log_subsection "Configuring VNC"

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
# VNC Desktop Startup Script - MATE Desktop for MCP RAG Development

# Clean PATH to avoid conda/miniforge conflicts
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

# Clean up environment
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS

# Set XDG variables
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=MATE
export XDG_SESSION_DESKTOP=mate

# Start D-Bus session bus
eval $(/usr/bin/dbus-launch --sh-syntax --exit-with-session)
export DBUS_SESSION_BUS_ADDRESS

# Start MATE desktop (preferred)
if command -v mate-session &> /dev/null; then
    exec /usr/bin/mate-session
elif command -v xfce4-session &> /dev/null; then
    exec /usr/bin/xfce4-session
else
    # Minimal fallback with xterm
    xsetroot -solid grey
    xterm -geometry 80x24+10+10 -ls -title "Terminal" &
    exec twm
fi
EOFVNC
chmod +x "${VNC_DIR}/xstartup"
chown "${USER_NAME}:${USER_NAME}" "${VNC_DIR}/xstartup"

# Create VNC config
cat > "${VNC_DIR}/config" << 'EOFCONFIG'
# TigerVNC configuration
geometry=1920x1080
depth=24
localhost=no
EOFCONFIG
chown "${USER_NAME}:${USER_NAME}" "${VNC_DIR}/config"

################################################################################
# SSL Certificate for noVNC
################################################################################

CERT_PATH="/home/${USER_NAME}/novnc.pem"
if [[ ! -f "${CERT_PATH}" ]]; then
    log_info "Generating self-signed SSL certificate for noVNC..."
    /usr/bin/openssl req -x509 -nodes -newkey rsa:2048 \
        -keyout "${CERT_PATH}" -out "${CERT_PATH}" \
        -days 365 -subj "/CN=localhost" 2>/dev/null || log_warning "Certificate generation failed"
    chown "${USER_NAME}:${USER_NAME}" "${CERT_PATH}"
fi

################################################################################
# VNC Systemd Services
################################################################################

log_subsection "Creating VNC Systemd Services"

# VNC Server service
cat > /etc/systemd/system/vncserver@.service << EOF
[Unit]
Description=TigerVNC Server for display %i
After=syslog.target network.target

[Service]
Type=simple
User=${USER_NAME}
Group=${USER_NAME}
WorkingDirectory=/home/${USER_NAME}

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

################################################################################
# Start VNC Services
################################################################################

log_subsection "Starting VNC Services"

log_info "Starting VNC server on display :1 (port 5901)..."
systemctl enable vncserver@1.service
systemctl start vncserver@1.service || {
    log_warning "Systemd VNC service failed, trying direct start..."
    su - "${USER_NAME}" -c "vncserver :1 -geometry 1920x1080 -depth 24" || log_warning "VNC server start failed"
}

log_info "Starting websockify (noVNC proxy on port 6080)..."
systemctl enable websockify.service
systemctl start websockify.service || log_warning "Websockify start failed"

# Verify VNC is running
sleep 2
if su - "${USER_NAME}" -c "vncserver -list" 2>/dev/null | grep -q ":1"; then
    log_success "VNC server running on display :1 (port 5901)"
else
    log_warning "VNC server may not be running - check manually with: vncserver -list"
fi

################################################################################
# Install Google Chrome
################################################################################

log_subsection "Installing Google Chrome"

if ! command_exists google-chrome; then
    log_info "Installing Google Chrome..."
    wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm -O /tmp/chrome.rpm
    dnf install -y /tmp/chrome.rpm || log_warning "Google Chrome installation failed"
    rm -f /tmp/chrome.rpm
else
    log_info "Google Chrome already installed"
fi

log_success "Remote Desktop setup complete"
log_info "  VNC Server: localhost:5901 (display :1)"
log_info "  noVNC Web:  https://localhost:6080/vnc.html (forward port 6080)"
log_info "  VNC Password: mcp2025vnc (change with: vncpasswd)"

exit 0
