#!/bin/bash
# fix-pw-vnc-port-mismatch.sh — Fix Parallel Works VNC nginx→KasmVNC port mismatch
#
# Root cause: PW's start-template-v3.sh generates independent random ports for
# KasmVNC (-websocketPort) and nginx (proxy_pass), but stale config files from
# prior sessions (owned by nginx UID 101) block the script from writing new ones.
# The nginx container then starts with an old config pointing to a wrong port,
# resulting in 502/504 Bad Gateway.
#
# This script detects the mismatch and fixes it by:
#   1. Finding the running KasmVNC websocket port
#   2. Finding the nginx container and its proxy_pass port
#   3. If they differ, updating the bind-mounted config.conf in-place
#   4. Reloading nginx
#
# Usage:
#   fix-pw-vnc-port-mismatch.sh [--check]
#
# Options:
#   --check   Dry-run: report mismatch without fixing
#
# Requires: docker, ss or netstat
# Run as: regular user (sudo used only if needed for docker)

set -euo pipefail

CHECK_ONLY=false
if [[ "${1:-}" == "--check" ]]; then
    CHECK_ONLY=true
fi

DOCKER_CMD="docker"
if ! docker info &>/dev/null; then
    DOCKER_CMD="sudo docker"
fi

# Step 1: Find running KasmVNC websocket port
vnc_pid=$(pgrep -f 'Xvnc.*-websocketPort' 2>/dev/null | head -1) || true
if [[ -z "${vnc_pid}" ]]; then
    echo "[ERROR] No running KasmVNC process found."
    echo "        Start KasmVNC first, then re-run this script."
    exit 1
fi

vnc_ws_port=$(ps -p "${vnc_pid}" -o args= | grep -oP '(?<=-websocketPort )\d+')
if [[ -z "${vnc_ws_port}" ]]; then
    echo "[ERROR] Could not parse -websocketPort from KasmVNC process ${vnc_pid}."
    exit 1
fi
echo "[OK] KasmVNC websocket port: ${vnc_ws_port} (pid ${vnc_pid})"

# Step 2: Find the PW nginx container
container_id=$($DOCKER_CMD ps --filter "name=nginx-" --format '{{.ID}}' | head -1) || true
if [[ -z "${container_id}" ]]; then
    echo "[ERROR] No nginx container found (expected name pattern: nginx-*)."
    exit 1
fi
container_name=$($DOCKER_CMD inspect "${container_id}" --format '{{.Name}}' | sed 's|^/||')
echo "[OK] Nginx container: ${container_name} (${container_id})"

# Step 3: Read current proxy_pass port from container config
nginx_proxy_port=$($DOCKER_CMD exec "${container_id}" grep -oP '(?<=proxy_pass https://127\.0\.0\.1:)\d+' /etc/nginx/conf.d/config.conf | head -1) || true
if [[ -z "${nginx_proxy_port}" ]]; then
    echo "[ERROR] Could not read proxy_pass port from nginx config."
    exit 1
fi
echo "[OK] Nginx proxy_pass port: ${nginx_proxy_port}"

# Step 4: Compare and fix
if [[ "${nginx_proxy_port}" == "${vnc_ws_port}" ]]; then
    echo "[OK] Ports match — no fix needed."
    exit 0
fi

echo "[WARN] Port mismatch detected: nginx proxies to ${nginx_proxy_port}, KasmVNC listens on ${vnc_ws_port}"

if [[ "${CHECK_ONLY}" == "true" ]]; then
    echo "[INFO] Dry-run mode — no changes made."
    echo "[FIX]  Run without --check to apply the fix."
    exit 1
fi

# Fix: overwrite proxy_pass port inside the container (handles bind-mount inode issue)
$DOCKER_CMD exec "${container_id}" sh -c \
    "cat /etc/nginx/conf.d/config.conf \
     | sed 's|proxy_pass https://127.0.0.1:${nginx_proxy_port}|proxy_pass https://127.0.0.1:${vnc_ws_port}|g' \
     | tee /etc/nginx/conf.d/config.conf > /dev/null"

# Verify the write took effect
new_port=$($DOCKER_CMD exec "${container_id}" grep -oP '(?<=proxy_pass https://127\.0\.0\.1:)\d+' /etc/nginx/conf.d/config.conf | head -1)
if [[ "${new_port}" != "${vnc_ws_port}" ]]; then
    echo "[ERROR] In-container tee failed (bind-mount inode issue)."
    echo "[INFO]  Trying host-side fix..."
    
    # Find host-side config.conf via docker inspect
    host_config=$($DOCKER_CMD inspect "${container_id}" --format '{{range .Mounts}}{{if eq .Destination "/etc/nginx/conf.d/config.conf"}}{{.Source}}{{end}}{{end}}') || true
    if [[ -n "${host_config}" && -f "${host_config}" ]]; then
        # Write to the same inode using dd/truncate approach
        tmpfile=$(mktemp)
        sed "s|proxy_pass https://127.0.0.1:${nginx_proxy_port}|proxy_pass https://127.0.0.1:${vnc_ws_port}|g" "${host_config}" > "${tmpfile}"
        cat "${tmpfile}" > "${host_config}"
        rm -f "${tmpfile}"
        echo "[OK] Updated host-side config: ${host_config}"
    else
        # Last resort: find it in the PW job directory
        job_dir="${HOME}/pw/jobs/marketplace.desktop.latest"
        session_dir=$(ls -td "${job_dir}"/0*/ 2>/dev/null | head -1)
        if [[ -n "${session_dir}" && -f "${session_dir}/config.conf" ]]; then
            tmpfile=$(mktemp)
            sed "s|proxy_pass https://127.0.0.1:${nginx_proxy_port}|proxy_pass https://127.0.0.1:${vnc_ws_port}|g" "${session_dir}/config.conf" > "${tmpfile}"
            cat "${tmpfile}" > "${session_dir}/config.conf"
            rm -f "${tmpfile}"
            echo "[OK] Updated PW session config: ${session_dir}/config.conf"
        else
            echo "[ERROR] Could not locate host-side config.conf. Manual fix required:"
            echo "        docker exec ${container_id} sh -c \"sed -i 's/${nginx_proxy_port}/${vnc_ws_port}/g' /etc/nginx/conf.d/config.conf\""
            exit 1
        fi
    fi
fi

# Reload nginx
$DOCKER_CMD exec "${container_id}" nginx -s reload
echo "[OK] Nginx reloaded."

# Verify end-to-end
listen_port=$($DOCKER_CMD exec "${container_id}" grep -oP '(?<=listen )\d+' /etc/nginx/conf.d/config.conf | head -1)
http_code=$(curl -sk -o /dev/null -w '%{http_code}' "http://127.0.0.1:${listen_port}/" 2>/dev/null) || true

if [[ "${http_code}" == "200" ]]; then
    echo "[OK] End-to-end verified: http://127.0.0.1:${listen_port}/ returns HTTP 200"
else
    echo "[WARN] http://127.0.0.1:${listen_port}/ returned HTTP ${http_code} (may need a moment to connect)"
fi

echo "[OK] Done. Nginx port ${nginx_proxy_port} → ${vnc_ws_port} (KasmVNC websocket)."
