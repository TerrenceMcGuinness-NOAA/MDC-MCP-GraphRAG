#!/bin/bash
################################################################################
# 13-container-cleanup.sh - Smart MCP Container Cleanup Service
# Part of modular provisioning system v4.0.0
#
# This script:
#   1. Installs the smart container cleanup script
#   2. Configures systemd timer for automatic cleanup
#   3. Enables connection-aware container lifecycle management
#
# Reference: Phase 23 SDD - sdd_framework/workflows/phase23_static_mode_multiuser_gateway.md
#
# The cleanup service:
#   - Detects active TCP connections via /proc/net/tcp
#   - Preserves containers with active MCP sessions
#   - Applies 30-minute grace period for disconnected containers
#   - Immediately removes unhealthy containers
#   - Runs every 15 minutes via systemd timer
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_section "Smart MCP Container Cleanup Service"

USER_NAME=$(get_actual_user)
USER_OWNERSHIP=$(get_ownership "${USER_NAME}")

################################################################################
# Configuration
################################################################################

INSTALL_BIN_DIR="/opt/eib-mcp-rag/bin"
CLEANUP_SCRIPT="${SETUP_DIR}/bin/mcp-container-cleanup.sh"
SYSTEMD_DIR="/etc/systemd/system"

# Grace period for disconnected containers (minutes)
GRACE_PERIOD_MINUTES="${MCP_CLEANUP_GRACE_MINUTES:-30}"

# Cleanup timer interval (minutes)
TIMER_INTERVAL="${MCP_CLEANUP_INTERVAL_MINUTES:-15}"

################################################################################
# Validate Source Files
################################################################################

log_subsection "Validating Source Files"

if [[ ! -f "${CLEANUP_SCRIPT}" ]]; then
    log_error "Cleanup script not found: ${CLEANUP_SCRIPT}"
    log_info "Expected at: SETUP/bin/mcp-container-cleanup.sh"
    exit 1
fi

if [[ ! -f "${SETUP_DIR}/systemd/mcp-container-cleanup.service" ]]; then
    log_error "Service unit not found: ${SETUP_DIR}/systemd/mcp-container-cleanup.service"
    exit 1
fi

if [[ ! -f "${SETUP_DIR}/systemd/mcp-container-cleanup.timer" ]]; then
    log_error "Timer unit not found: ${SETUP_DIR}/systemd/mcp-container-cleanup.timer"
    exit 1
fi

log_success "All source files found"

################################################################################
# Install Cleanup Script
################################################################################

log_subsection "Installing Cleanup Script"

# Create install directory
mkdir -p "${INSTALL_BIN_DIR}"

# Copy and set permissions
cp "${CLEANUP_SCRIPT}" "${INSTALL_BIN_DIR}/mcp-container-cleanup.sh"
chmod +x "${INSTALL_BIN_DIR}/mcp-container-cleanup.sh"

log_success "Installed: ${INSTALL_BIN_DIR}/mcp-container-cleanup.sh"

################################################################################
# Install Systemd Units
################################################################################

log_subsection "Installing Systemd Units"

# Create service unit with configured grace period
cat > "${SYSTEMD_DIR}/mcp-container-cleanup.service" << EOF
[Unit]
Description=Smart MCP Container Cleanup Service
Documentation=https://github.com/NOAA-EMC/eib-mcp-rag-server
# Phase 23: Multi-User Gateway Architecture
# See: sdd_framework/workflows/phase23_static_mode_multiuser_gateway.md

[Service]
Type=oneshot
ExecStart=${INSTALL_BIN_DIR}/mcp-container-cleanup.sh
Environment=MCP_CLEANUP_GRACE_MINUTES=${GRACE_PERIOD_MINUTES}
Environment=MCP_CLEANUP_DRY_RUN=false

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

# Allow docker socket access
SupplementaryGroups=docker
EOF

log_info "Created service: ${SYSTEMD_DIR}/mcp-container-cleanup.service"

# Create timer unit with configured interval
cat > "${SYSTEMD_DIR}/mcp-container-cleanup.timer" << EOF
[Unit]
Description=Smart MCP Container Cleanup Timer
Documentation=https://github.com/NOAA-EMC/eib-mcp-rag-server
# Phase 23: Multi-User Gateway Architecture
# Runs connection-aware cleanup every ${TIMER_INTERVAL} minutes
# See: sdd_framework/workflows/phase23_static_mode_multiuser_gateway.md

[Timer]
# Start 10 minutes after boot
OnBootSec=10min
# Then run every ${TIMER_INTERVAL} minutes
OnUnitActiveSec=${TIMER_INTERVAL}min
# Persist timer across reboots
Persistent=true
# Add randomized delay to avoid thundering herd
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
EOF

log_info "Created timer: ${SYSTEMD_DIR}/mcp-container-cleanup.timer"

################################################################################
# Enable and Start Timer
################################################################################

log_subsection "Enabling Cleanup Timer"

# Reload systemd to pick up new units
systemctl daemon-reload
log_info "Reloaded systemd daemon"

# Enable timer to start on boot
systemctl enable mcp-container-cleanup.timer
log_info "Enabled timer for boot startup"

# Start timer now
systemctl start mcp-container-cleanup.timer
log_success "Started mcp-container-cleanup.timer"

################################################################################
# Verify Installation
################################################################################

log_subsection "Verifying Installation"

# Check timer status
if systemctl is-active --quiet mcp-container-cleanup.timer; then
    log_success "Timer is active"
else
    log_warning "Timer may not be active yet"
fi

# Show next scheduled run
echo ""
echo "Timer Status:"
systemctl list-timers mcp-container-cleanup.timer --no-pager 2>/dev/null || true

################################################################################
# Test Cleanup Script (Dry Run)
################################################################################

log_subsection "Testing Cleanup Script (Dry Run)"

echo ""
if MCP_CLEANUP_DRY_RUN=true "${INSTALL_BIN_DIR}/mcp-container-cleanup.sh" 2>&1; then
    log_success "Cleanup script test passed"
else
    log_warning "Cleanup script test completed with warnings"
fi

################################################################################
# Summary
################################################################################

log_subsection "Installation Summary"

echo ""
log_success "Smart MCP Container Cleanup installed successfully!"
echo ""
log_info "Configuration:"
log_info "  Grace Period: ${GRACE_PERIOD_MINUTES} minutes"
log_info "  Timer Interval: ${TIMER_INTERVAL} minutes"
log_info "  Script Location: ${INSTALL_BIN_DIR}/mcp-container-cleanup.sh"
echo ""
log_info "Management Commands:"
log_info "  View logs:      journalctl -u mcp-container-cleanup.service -f"
log_info "  Timer status:   systemctl list-timers mcp-container-cleanup.timer"
log_info "  Manual run:     systemctl start mcp-container-cleanup.service"
log_info "  Dry run:        MCP_CLEANUP_DRY_RUN=true ${INSTALL_BIN_DIR}/mcp-container-cleanup.sh"
echo ""
log_info "Cleanup Algorithm:"
log_info "  1. Unhealthy containers → Immediate cleanup"
log_info "  2. Active connections → Preserved (never interrupted)"
log_info "  3. No connections + age > ${GRACE_PERIOD_MINUTES}min → Cleanup"
log_info "  4. No connections + age < ${GRACE_PERIOD_MINUTES}min → Grace period"

record_result "13-container-cleanup" "success" "Timer installed and running"

exit 0
