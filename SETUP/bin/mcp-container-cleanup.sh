#!/bin/bash
# =============================================================================
# Smart MCP Container Cleanup - Keep Newest Per Server
# =============================================================================
# The gateway communicates with containers via stdio, NOT TCP. Containers
# maintain persistent database connections (Neo4j 7687, ChromaDB 8080) that
# made the old TCP-based orphan detection ineffective — all containers always
# appeared "active".
#
# New strategy: For each docker-mcp-name, keep only the newest container.
# Older containers past the grace period are removed. Unhealthy and exited
# containers are always cleaned up.
#
# Part of Phase 23: Multi-User Gateway Architecture
# See: sdd_framework/workflows/phase23_static_mode_multiuser_gateway.md
# =============================================================================

set -euo pipefail

# Configuration
LABEL="docker-mcp=true"
NAME_LABEL="docker-mcp-name"
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

# Get container creation timestamp as epoch seconds
get_container_created_epoch() {
    local container_id="$1"
    local created
    created=$(docker inspect "$container_id" --format '{{.Created}}' 2>/dev/null)
    if [[ -z "$created" ]]; then
        echo "0"
        return
    fi
    date -d "$created" +%s 2>/dev/null || echo "0"
}

# Get container age in minutes
get_container_age_minutes() {
    local container_id="$1"
    local created_epoch
    created_epoch=$(get_container_created_epoch "$container_id")
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

# Get the docker-mcp-name label value
get_mcp_server_name() {
    local container_id="$1"
    docker inspect "$container_id" --format "{{index .Config.Labels \"$NAME_LABEL\"}}" 2>/dev/null || echo "unknown"
}

# Main cleanup logic
main() {
    log "info" "Starting smart MCP container cleanup (grace=${GRACE_PERIOD_MINUTES}min, dry_run=${DRY_RUN})"
    
    local total=0
    local cleaned=0
    local kept=0
    local grace=0
    
    # --- Phase 1: Clean unhealthy running containers ---
    while IFS= read -r container_id; do
        [[ -z "$container_id" ]] && continue
        local name
        name=$(get_container_name "$container_id")
        local health
        health=$(get_health_status "$container_id")
        if [[ "$health" == "unhealthy" ]]; then
            cleanup_container "$container_id" "unhealthy"
            cleaned=$((cleaned + 1))
        fi
    done < <(docker ps -q --filter "label=$LABEL" 2>/dev/null)
    
    # --- Phase 2: For each server name, keep only the newest container ---
    # Collect all running docker-mcp containers grouped by server name
    declare -A newest_id newest_epoch
    local all_ids=()
    
    while IFS= read -r container_id; do
        [[ -z "$container_id" ]] && continue
        
        # Skip unhealthy (already handled above)
        local health
        health=$(get_health_status "$container_id")
        [[ "$health" == "unhealthy" ]] && continue
        
        total=$((total + 1))
        all_ids+=("$container_id")
        
        local server_name
        server_name=$(get_mcp_server_name "$container_id")
        local created_epoch
        created_epoch=$(get_container_created_epoch "$container_id")
        
        # Track the newest container per server name
        if [[ -z "${newest_epoch[$server_name]:-}" ]] || [[ "$created_epoch" -gt "${newest_epoch[$server_name]}" ]]; then
            newest_id[$server_name]="$container_id"
            newest_epoch[$server_name]="$created_epoch"
        fi
    done < <(docker ps -q --filter "label=$LABEL" 2>/dev/null)
    
    # Now process: keep newest, remove older ones past grace period
    for container_id in "${all_ids[@]}"; do
        local name
        name=$(get_container_name "$container_id")
        local server_name
        server_name=$(get_mcp_server_name "$container_id")
        
        # Keep the newest container for this server name
        if [[ "$container_id" == "${newest_id[$server_name]}" ]]; then
            local age_minutes
            age_minutes=$(get_container_age_minutes "$container_id")
            log "info" "[KEEP] $name (newest for $server_name, ${age_minutes}min old)"
            kept=$((kept + 1))
            continue
        fi
        
        # Older container — check grace period before removing
        local age_minutes
        age_minutes=$(get_container_age_minutes "$container_id")
        
        if [[ "$age_minutes" -gt "$GRACE_PERIOD_MINUTES" ]]; then
            cleanup_container "$container_id" "superseded (${age_minutes}min old, newer $server_name container exists)"
            cleaned=$((cleaned + 1))
        else
            log "info" "[GRACE] $name - waiting (${age_minutes}min < ${GRACE_PERIOD_MINUTES}min threshold)"
            grace=$((grace + 1))
        fi
    done
    
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
    
    log "info" "Cleanup complete: total=$total, kept=$kept, grace=$grace, cleaned=$cleaned, exited_removed=$exited_count"
}

# Script entry point
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
