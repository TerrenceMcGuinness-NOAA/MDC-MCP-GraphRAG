#!/bin/bash
# =============================================================================
# Install MCP Nightly Benchmark Timer
# =============================================================================
# Installs the nightly RAG benchmark systemd timer + oneshot service.
# The wrapper script itself stays version-controlled in the repo
# (mcp_server_python/scripts/run_benchmark_nightly.sh) and is referenced by the
# unit's ExecStart; only the .service/.timer units are copied to systemd.
#
# Run as root or with sudo.
#
# Usage:
#   sudo ./install-benchmark-timer.sh              # install + enable + start
#   sudo ./install-benchmark-timer.sh --uninstall  # remove
#
# Part of SDD Phase 71: Nightly RAG Benchmark Harness
# Spec: .kiro/specs/nightly-rag-benchmark-harness/
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="/etc/systemd/system"
WRAPPER="/mcp_rag_eib/eib-mcp-rag-server/mcp_server_python/scripts/run_benchmark_nightly.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

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
    log_ok "Installing MCP Nightly Benchmark Timer..."

    if [[ ! -f "${WRAPPER}" ]]; then
        log_err "Wrapper not found at ${WRAPPER}"
        exit 1
    fi
    chmod +x "${WRAPPER}"
    log_ok "Ensured wrapper is executable: ${WRAPPER}"

    cp "${SCRIPT_DIR}/mcp-benchmark.service" "${SYSTEMD_DIR}/"
    cp "${SCRIPT_DIR}/mcp-benchmark.timer" "${SYSTEMD_DIR}/"
    log_ok "Installed systemd units to ${SYSTEMD_DIR}/"

    systemctl daemon-reload
    log_ok "Reloaded systemd daemon"

    systemctl enable mcp-benchmark.timer
    systemctl start mcp-benchmark.timer
    log_ok "Enabled and started benchmark timer"

    echo ""
    echo "Next scheduled run:"
    systemctl list-timers mcp-benchmark.timer --no-pager || true

    echo ""
    log_ok "Installation complete!"
    echo ""
    echo "Manual commands:"
    echo "  Run now:      systemctl start mcp-benchmark.service"
    echo "  View logs:    journalctl -u mcp-benchmark.service -f"
    echo "  Timer status: systemctl list-timers mcp-benchmark.timer"
    echo "  Regressions:  journalctl -u mcp-benchmark.service | grep rag_quality_regression"
}

uninstall() {
    log_warn "Uninstalling MCP Nightly Benchmark Timer..."

    systemctl stop mcp-benchmark.timer 2>/dev/null || true
    systemctl disable mcp-benchmark.timer 2>/dev/null || true
    log_ok "Stopped and disabled timer"

    rm -f "${SYSTEMD_DIR}/mcp-benchmark.service"
    rm -f "${SYSTEMD_DIR}/mcp-benchmark.timer"
    log_ok "Removed systemd units"

    systemctl daemon-reload
    log_ok "Reloaded systemd daemon"

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
            echo "  --uninstall, -u   Remove the benchmark timer and service"
            echo "  --help, -h        Show this help message"
            ;;
        *)
            install
            ;;
    esac
}

main "$@"
