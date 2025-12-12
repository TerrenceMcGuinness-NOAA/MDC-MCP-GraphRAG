# MCP RAG Modular Provisioning System

**Version:** 4.0.0  
**Date:** December 2025

## Overview

This directory contains a modular provisioning system for the MCP RAG infrastructure. Instead of a single monolithic script, provisioning is split into focused, independently runnable scripts that can be orchestrated together or run individually.

## Quick Start

```bash
# Run all provisioning scripts
sudo ./provision.sh

# Run with options
sudo ./provision.sh --skip 09        # Skip VNC setup
sudo ./provision.sh --only 06        # Only run ChromaDB setup
sudo ./provision.sh --fresh          # Clean start (wipe caches)
sudo ./provision.sh --list           # List available scripts
```

## Script Inventory

| Script | Description | Dependencies |
|--------|-------------|--------------|
| `01-directories.sh` | Create directory structure | None |
| `00-users.sh` | Create Linux user accounts | None |
| `02-system-deps.sh` | Install system packages | None |
| `03-docker.sh` | Docker installation | 02 |
| `04-nodejs.sh` | Node.js environment | 02 |
| `05-python-spack.sh` | Python and Spack modules | 02 |
| `06-chromadb.sh` | ChromaDB Docker container | 01, 03 |
| `07-mcp-server.sh` | MCP server deployment | 01, 04 |
| `08-services.sh` | Neo4j, LangFlow, systemd | 03, 06 |
| `09-desktop-vnc.sh` | VNC/noVNC remote desktop | 02 |
| `10-verification.sh` | Final verification | All |

## Architecture

```
provisioning/
├── provision.sh          # Master orchestrator
├── common.sh             # Shared functions and variables
├── user_config.sh         # Provisioned users + defaults (SPOT)
├── 00-users.sh            # Linux user provisioning
├── 01-directories.sh     # Directory structure
├── 02-system-deps.sh     # System dependencies
├── 03-docker.sh          # Docker setup
├── 04-nodejs.sh          # Node.js setup
├── 05-python-spack.sh    # Python/Spack setup
├── 06-chromadb.sh        # ChromaDB container
├── 07-mcp-server.sh      # MCP server
├── 08-services.sh        # Docker Compose services
├── 09-desktop-vnc.sh     # VNC remote desktop
├── 10-verification.sh    # Verification
└── README.md             # This file
```

## Common Library (common.sh)

The `common.sh` library provides:

- **Color output functions**: `log_info`, `log_success`, `log_warning`, `log_error`
- **Section headers**: `log_section`, `log_subsection`
- **Environment variables**: `PERSISTENT_ROOT`, `MCP_ROOT`, `CHROMADB_URL`, etc.
- **Helper functions**: `require_root`, `command_exists`, `wait_for_service`
- **Result tracking**: `record_result`, `print_summary_report`

### Using in Scripts

```bash
#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "My Script Section"
log_info "Doing something..."
log_success "Done!"
```

## Running Individual Scripts

Each script can be run independently:

```bash
# Run a single script
sudo ./06-chromadb.sh

# Check script syntax
bash -n 06-chromadb.sh
```

## Master Orchestrator Options

```bash
# Show help
sudo ./provision.sh --help

# List all scripts
sudo ./provision.sh --list

# Skip specific scripts
sudo ./provision.sh --skip 09 --skip 10

# Run only specific scripts
sudo ./provision.sh --only 01 --only 06

# Fresh start (clean caches)
sudo ./provision.sh --fresh
```

## Summary Report

At the end of provisioning, a summary report is displayed:

```
════════════════════════════════════════════════════════════════
  Provisioning Summary Report
════════════════════════════════════════════════════════════════

Script                              Status       Details
----------------------------------- ------------ --------
01-directories.sh                   SUCCESS      3s
02-system-deps.sh                   SUCCESS      45s
03-docker.sh                        SUCCESS      12s
...
09-desktop-vnc.sh                   SKIPPED      User requested skip
10-verification.sh                  SUCCESS      2s

Total: 10 | Success: 9 | Failed: 0 | Skipped: 1
```

## Comparison with Legacy Script

| Feature | Legacy (v3.x) | Modular (v4.0) |
|---------|---------------|----------------|
| Single file | 1200+ lines | ~100 lines each |
| Error handling | Exits on first error | Continues, reports all |
| Selective run | No | `--skip`, `--only` |
| Independent testing | No | Yes |
| Summary report | No | Yes |
| Maintenance | Difficult | Easy |

## Migration from Legacy

The legacy `provision_mcp_rag_persistent.sh` is preserved for reference. To migrate:

1. Use `./provision.sh` for new installations
2. For updates, run only needed scripts: `./provision.sh --only 07`
3. Legacy script remains functional but unmaintained

## Troubleshooting

### Script fails with "common.sh not found"

```bash
# Ensure you're in the provisioning directory
cd /mcp_rag_eib/eib-mcp-rag-server/SETUP/provisioning
sudo ./provision.sh
```

### Permission denied

```bash
# Make scripts executable
chmod +x *.sh
```

### Check individual script logs

```bash
# Run script with verbose output
sudo bash -x ./06-chromadb.sh
```

## Contributing

When adding new provisioning steps:

1. Create a new numbered script (e.g., `11-new-feature.sh`)
2. Source `common.sh` at the start
3. Use `log_*` functions for output
4. Add to `SCRIPTS` array in `provision.sh`
5. Update this README

## Version History

- **4.0.0** (Dec 2025): Initial modular provisioning system
- Refactored from `provision_mcp_rag_persistent.sh` v3.6.x
