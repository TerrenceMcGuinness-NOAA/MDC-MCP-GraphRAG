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
  "Anton.Fernando"
)

# Scratch workspace root for provisioned users
SCRATCH_ROOT="/mcp_rag_eib/SCRATCH_SPACE"

# VNC defaults — KasmVNC on Rocky 9 with Parallel Works start-template-v3.sh
# PW's template handles: display allocation, port assignment via `pw agent open-port`,
# nginx proxy (service_port → kasmvnc_port), kasm-xstartup DE auto-detection.
# Our provisioning ensures: MATE installed, NVIDIA GPU crash prevented,
# kasmvnc-cert group, kasmvnc.yaml defaults, and user xstartup files.
#
# NVIDIA GPU workaround (Rocky 9 AWS GPU instances):
#   libnvidia-egl-gbm.so.1 causes segfault in GlxExtensionInit during headless
#   VNC startup. Two-layer fix:
#     1. System-level: Rename the library to .disabled (09-desktop-vnc.sh)
#     2. Per-session:  -extension GLX flag (backup, in helper scripts)
#   PW's start-template-v3.sh uses -disableBasicAuth (no OS password needed with AWS IAM).
VNC_GEOMETRY="1920x1080"
VNC_DEPTH="24"

# KasmVNC settings (primary VNC server for PW integration)
KASMVNC_GEOMETRY="${VNC_GEOMETRY}"
KASMVNC_DEPTH="${VNC_DEPTH}"
KASMVNC_DISPLAY_START=1
KASMVNC_AUTOSTART_USERS=(
  "Terry.McGuinness"
)

# Primary group for provisioned users on this host.
# Rationale: matches the pre-existing `pwuser` convention shared by all
# operator accounts; overrideable per site.
PROVISION_PRIMARY_GROUP="pwuser"

# When "yes", 00-users.sh will chown pre-existing content under
# ${SCRATCH_ROOT}/${username} to the target user. Default "no" preserves
# operator-staged files (see R3).
PROVISION_ADOPT_PRESTAGED="${PROVISION_ADOPT_PRESTAGED:-no}"

# Path to a mode-0600 file containing the initial password for new users.
# If unset, 00-users.sh falls back to an interactive prompt or a generated
# password (never both). See R5.
PROVISION_INITIAL_PASSWORD_FILE="${PROVISION_INITIAL_PASSWORD_FILE:-}"
