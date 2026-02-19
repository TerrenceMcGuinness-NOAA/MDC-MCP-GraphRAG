#!/bin/bash
# Shared configuration for modular provisioning scripts.
# This file is sourced by provisioning scripts under SETUP/provisioning/.

# Provisioned Linux users (order matters for display assignment).
# NOTE: Keep this as the single source of truth.
PROVISION_USERS=(
  "Terry.McGuinness"
  "Anna.Smoot"
  "Brian.Curtis"
  "Georgios.Britzolakis"
)

# Scratch workspace root for provisioned users
SCRATCH_ROOT="/mcp_rag_eib/SCRATCH_SPACE"

# VNC defaults (DEPRECATED 2026-02-19 — Parallel Works now provides VNC/desktop)
# Retained for backward compatibility if 09-desktop-vnc.sh is run with --force.
KASMVNC_GEOMETRY="1920x1080"
KASMVNC_DEPTH="24"

# Display assignment policy: first user gets :1, then :2, etc.
KASMVNC_DISPLAY_START=1

# Which users should have KasmVNC enabled at boot?
# Keep minimal to avoid unexpected multi-session resource usage.
KASMVNC_AUTOSTART_USERS=(
  "Terry.McGuinness"
)
