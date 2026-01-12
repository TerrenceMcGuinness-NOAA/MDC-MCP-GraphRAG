#!/bin/bash
# =============================================================================
# Smart MCP Container Cleanup - Connection Aware
# =============================================================================
# Only removes containers with NO active TCP connections after grace period.
# Uses /proc/net/tcp to detect ESTABLISHED connections (st=01 in hex).
#
# Part of Phase 23: Multi-User Gateway Architecture
# See: sdd_framework/workflows/phase23_static_mode_multiuser_gateway.md
# =============================================================================

set -euo pipefail

# Configuration
LABEL="docker-mcp=true"
GRACE_PERIOD_MINUTES="${MCP_CLEANUP_GRACE_MINUTES:-30}"
LOG_TAG="mcp-cleanup"
DRY_RUN="${MCP_CLEANUP_DRY_RUN:-false}"

# Logging helper
log() {
    local level="$1"
    shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*"
    logger -t "$LOG_TAG" -p "user.$level" "$*" 2>/dev/null || true
}

# Count ESTABLISHED TCP connections inside container
# Returns: integer count (0 = no connections = orphan candidate)
get_connection_count() {
    local container_id="$1"
    # st=01 in /proc/net/tcp means ESTABLISHED
    docker exec "$container_id" awk 'NR>1 && $4=="01" {c++} END {print c+0}' /proc/net/tcp 2>/dev/null || echo "0"
}

# Get container age in minutes
get_container_age_minutes() {
    local container_id="$1"
    local created
    created=$(docker inspect "$container_id" --format '{{.Created}}' 2>/dev/null)
    if [[ -z "$created" ]]; then
        echo "0"
        return
    fi
    local created_epoch
    created_epoch=$(date -d "$created" +%s 2>/dev/null || echo "0")
    local now_epoch
    now_epoch=$(date +%s)
    echo $(( (now_epoch - created_epoch) / 60 ))
}

# Get container health status
get_health_status() {
    local container_id="$1"
    docker inspect "$container_id" --format '{{.State.Health.Status}}' 2>/dev/null || echo "none"
}

# Get container name for logging
get_container_name() {
    local container_id="$1"
    docker inspect "$container_id" --format '{{.Name}}' 2>/dev/null | sed 's/^\///'
}

# Cleanup a container (stop + remove)
cleanup_container() {
    local container_id="$1"
    local reason="$2"
    local name
    name=$(get_container_name "$container_id")
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log "info" "[DRY-RUN] Would cleanup $name ($container_id) - $reason"
        return 0
    fi
    
    log "info" "[CLEANUP] $name ($container_id) - $reason"
    if docker stop "$container_id" >/dev/null 2>&1; then
        docker rm "$container_id" >/dev/null 2>&1 || true
        log "info" "[OK] Removed $name"
        return 0
    else
        log "warn" "[WARN] Failed to stop $name"
        return 1
    fi
}

# Main cleanup logic
main() {
    log "info" "Starting smart MCP container cleanup (grace=${GRACE_PERIOD_MINUTES}min, dry_run=${DRY_RUN})"
    
    local total=0
    local cleaned=0
    local active=0
    local grace=0
    
    # Process running containers with docker-mcp label
    while IFS= read -r container_id; do
        [[ -z "$container_id" ]] && continue
        total=$((total + 1))
        
        local name
        name=$(get_container_name "$container_id")
        
        # 1. Check health status first
        local health
        health=$(get_health_status "$container_id")
        if [[ "$health" == "unhealthy" ]]; then
            cleanup_container "$container_id" "unhealthy"
            cleaned=$((cleaned + 1))
            continue
        fi
        
        # 2. Check TCP connections
        local connections
        connections=$(get_connection_count "$container_id")
        
        if [[ "$connections" -gt 0 ]]; then
            log "info" "[ACTIVE] $name - $connections connection(s)"
            active=$((active + 1))
            continue
        fi
        
        # 3. No connections - check age for grace period
        local age_minutes
        age_minutes=$(get_container_age_minutes "$container_id")
        
        if [[ "$age_minutes" -gt "$GRACE_PERIOD_MINUTES" ]]; then
            cleanup_container "$container_id" "orphaned (${age_minutes}min old, 0 connections)"
            cleaned=$((cleaned + 1))
        else
            log "info" "[GRACE] $name - waiting (${age_minutes}min < ${GRACE_PERIOD_MINUTES}min threshold)"
            grace=$((grace + 1))
        fi
        
    done < <(docker ps -q --filter "label=$LABEL" 2>/dev/null)
    
    # Cleanup exited containers unconditionally (they're already stopped)
    local exited_count=0
    while IFS= read -r container_id; do
        [[ -z "$container_id" ]] && continue
        local name
        name=$(get_container_name "$container_id")
        if [[ "$DRY_RUN" == "true" ]]; then
            log "info" "[DRY-RUN] Would remove exited container $name"
        else
            docker rm "$container_id" >/dev/null 2>&1 && log "info" "[REMOVED] Exited container $name"
        fi
        exited_count=$((exited_count + 1))
    done < <(docker ps -aq --filter "label=$LABEL" --filter "status=exited" 2>/dev/null)
    
    log "info" "Cleanup complete: total=$total, active=$active, grace=$grace, cleaned=$cleaned, exited_removed=$exited_count"
}

# Script entry point
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
