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

# VNC defaults — TigerVNC on Rocky 9 with Parallel Works noVNC bridge
# PW provides noVNC/websockify on a dynamic port pair; our job is to start
# Xvnc on the port PW expects and launch a MATE desktop session on it.
#
# IMPORTANT (Rocky 9 + NVIDIA GPU nodes):
#   TigerVNC 1.15.0 segfaults during GlxExtensionInit when libnvidia-egl-gbm.so.1
#   is present but no GPU render nodes are available in the headless VNC context.
#   Workaround: start Xvnc with `-extension GLX` to skip GLX initialization.
#   PW's noVNC bridge does not send VNC passwords, so `-SecurityTypes None` is required.
VNC_GEOMETRY="1920x1080"
VNC_DEPTH="24"

# Legacy KasmVNC settings (retained for backward compat with 09-desktop-vnc.sh --force)
KASMVNC_GEOMETRY="${VNC_GEOMETRY}"
KASMVNC_DEPTH="${VNC_DEPTH}"
KASMVNC_DISPLAY_START=1
KASMVNC_AUTOSTART_USERS=(
  "Terry.McGuinness"
)
