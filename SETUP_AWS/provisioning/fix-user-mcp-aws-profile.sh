#!/usr/bin/env bash
# Remove the broken `"AWS_PROFILE": "agentcore-rag"` line from each provisioned
# user's ~/.kiro/settings/mcp.json. Idempotent — safe to re-run; users without
# the bad line are reported and skipped.
#
# Background: the agentcore-kiro-proxy reads AWS credentials via boto3's normal
# credential chain. With AWS_PROFILE set to a profile that doesn't exist in the
# user's ~/.aws/config, every proxy startup errors with:
#   "[ERROR]: The config profile (agentcore-rag) could not be found"
# Removing the env line lets boto3 fall through to the EC2 instance profile,
# which every user on this host inherits automatically.
#
# Run as root or with sudo. Skips users whose mcp.json is missing — for those,
# run provision-user-accounts.sh first to deploy from the template.

set -euo pipefail

USERS_FILE="$(dirname "$0")/users.conf"
if [[ ! -r "$USERS_FILE" ]]; then
  echo "[ERROR] cannot read $USERS_FILE" >&2
  exit 2
fi

dry_run=0
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=1
  echo "[INFO] dry-run mode — no files will be changed"
fi

fixed=0
already_clean=0
missing=0

# Read users.conf — one user per line, '#' comments stripped.
while IFS= read -r line; do
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  # users.conf entries may be "user|first.last" — take the first field.
  user="${line%%|*}"
  user="${user##*( )}"; user="${user%%*( )}"
  [[ -z "$user" ]] && continue

  cfg="/home/${user}/.kiro/settings/mcp.json"

  if [[ ! -f "$cfg" ]]; then
    echo "[SKIP] ${user}: mcp.json missing (run provision-user-accounts.sh)"
    missing=$((missing + 1))
    continue
  fi

  if ! grep -q '"AWS_PROFILE"' "$cfg"; then
    echo "[OK]   ${user}: already clean"
    already_clean=$((already_clean + 1))
    continue
  fi

  if [[ $dry_run -eq 1 ]]; then
    echo "[WOULD-FIX] ${user}: mcp.json contains AWS_PROFILE"
    fixed=$((fixed + 1))
    continue
  fi

  # Remove the AWS_PROFILE line and any trailing comma on the previous line so
  # the JSON stays valid. Preserves everything else (autoApprove, disabledTools,
  # etc.) exactly as the user has it.
  backup="${cfg}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
  cp -p "$cfg" "$backup"

  python3.12 - "$cfg" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as f:
    cfg = json.load(f)
servers = cfg.get("mcpServers", {})
changed = False
for name, server in servers.items():
    env = server.get("env") or {}
    if "AWS_PROFILE" in env:
        env.pop("AWS_PROFILE")
        server["env"] = env
        changed = True
if changed:
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
sys.exit(0 if changed else 1)
PY
  rc=$?

  # Restore correct ownership and perms.
  chown "${user}:${user}" "$cfg"
  chmod 0600 "$cfg"

  if [[ $rc -eq 0 ]]; then
    echo "[FIX]  ${user}: removed AWS_PROFILE (backup: ${backup##*/})"
    fixed=$((fixed + 1))
  else
    echo "[OK]   ${user}: nothing to remove (race?)"
    rm -f "$backup"
    already_clean=$((already_clean + 1))
  fi
done < "$USERS_FILE"

echo
echo "Summary: fixed=${fixed} already_clean=${already_clean} missing=${missing}"
