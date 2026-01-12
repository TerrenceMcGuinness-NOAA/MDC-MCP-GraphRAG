#!/bin/bash
# =============================================================================
# Install MCP Container Cleanup Timer
# =============================================================================
# Installs the smart container cleanup systemd timer and service.
# Run as root or with sudo.
#
# Usage:
#   sudo ./install-cleanup-timer.sh [--uninstall]
#
# Part of Phase 23: Multi-User Gateway Architecture
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_BIN_DIR="/opt/eib-mcp-rag/bin"
SYSTEMD_DIR="/etc/systemd/system"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_ok() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_err() { echo -e "${RED}[ERROR]${NC} $*"; }

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_err "This script must be run as root (use sudo)"
        exit 1
    fi
}

install() {
    log_ok "Installing MCP Container Cleanup Timer..."
    
    # Create bin directory
    mkdir -p "$INSTALL_BIN_DIR"
    
    # Copy cleanup script
    local script_src="$SCRIPT_DIR/../bin/mcp-container-cleanup.sh"
    if [[ ! -f "$script_src" ]]; then
        # Try relative to SETUP directory
        script_src="$SCRIPT_DIR/../bin/mcp-container-cleanup.sh"
    fi
    
    if [[ -f "$script_src" ]]; then
        cp "$script_src" "$INSTALL_BIN_DIR/mcp-container-cleanup.sh"
        chmod +x "$INSTALL_BIN_DIR/mcp-container-cleanup.sh"
        log_ok "Installed cleanup script to $INSTALL_BIN_DIR/"
    else
        log_err "Cleanup script not found at $script_src"
        exit 1
    fi
    
    # Copy systemd units
    cp "$SCRIPT_DIR/mcp-container-cleanup.service" "$SYSTEMD_DIR/"
    cp "$SCRIPT_DIR/mcp-container-cleanup.timer" "$SYSTEMD_DIR/"
    log_ok "Installed systemd units to $SYSTEMD_DIR/"
    
    # Reload systemd
    systemctl daemon-reload
    log_ok "Reloaded systemd daemon"
    
    # Enable and start timer
    systemctl enable mcp-container-cleanup.timer
    systemctl start mcp-container-cleanup.timer
    log_ok "Enabled and started cleanup timer"
    
    # Show status
    echo ""
    echo "Timer status:"
    systemctl status mcp-container-cleanup.timer --no-pager || true
    
    echo ""
    echo "Next scheduled runs:"
    systemctl list-timers mcp-container-cleanup.timer --no-pager || true
    
    echo ""
    log_ok "Installation complete!"
    echo ""
    echo "Manual commands:"
    echo "  Test (dry-run): MCP_CLEANUP_DRY_RUN=true $INSTALL_BIN_DIR/mcp-container-cleanup.sh"
    echo "  Run now:        systemctl start mcp-container-cleanup.service"
    echo "  View logs:      journalctl -u mcp-container-cleanup.service -f"
    echo "  Timer status:   systemctl list-timers mcp-container-cleanup.timer"
}

uninstall() {
    log_warn "Uninstalling MCP Container Cleanup Timer..."
    
    # Stop and disable timer
    systemctl stop mcp-container-cleanup.timer 2>/dev/null || true
    systemctl disable mcp-container-cleanup.timer 2>/dev/null || true
    log_ok "Stopped and disabled timer"
    
    # Remove systemd units
    rm -f "$SYSTEMD_DIR/mcp-container-cleanup.service"
    rm -f "$SYSTEMD_DIR/mcp-container-cleanup.timer"
    log_ok "Removed systemd units"
    
    # Reload systemd
    systemctl daemon-reload
    log_ok "Reloaded systemd daemon"
    
    # Optionally remove script (keep bin dir as other scripts may use it)
    rm -f "$INSTALL_BIN_DIR/mcp-container-cleanup.sh"
    log_ok "Removed cleanup script"
    
    log_ok "Uninstallation complete!"
}

main() {
    check_root
    
    case "${1:-install}" in
        --uninstall|-u|uninstall)
            uninstall
            ;;
        --help|-h)
            echo "Usage: $0 [--uninstall]"
            echo ""
            echo "Options:"
            echo "  --uninstall, -u   Remove the cleanup timer and service"
            echo "  --help, -h        Show this help message"
            ;;
        *)
            install
            ;;
    esac
}

main "$@"
