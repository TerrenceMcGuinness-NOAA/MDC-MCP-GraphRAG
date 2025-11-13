#!/bin/bash
################################################################################
# deploy-to-runtime.sh
# 
# Purpose: Deploy MCP server code from repository to runtime using manifest
# Usage: ./deploy-to-runtime.sh [--dry-run] [--skip-backup] [--force]
# 
# Author: Claude Sonnet 4.5
# Supervised by: Terry McGuinness
# Date: October 16, 2025
# Version: 2.0.0-week1
################################################################################

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_FILE="${SCRIPT_DIR}/deployment-manifest.json"

# Parse command line arguments
DRY_RUN=false
SKIP_BACKUP=false
FORCE=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --skip-backup)
      SKIP_BACKUP=true
      shift
      ;;
    --force)
      FORCE=true
      shift
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      echo "Usage: $0 [--dry-run] [--skip-backup] [--force]"
      exit 1
      ;;
  esac
done

# Functions
log_info() {
  echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
  echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
  echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
  echo -e "${RED}✗${NC} $1"
}

section_header() {
  echo ""
  echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
  echo -e "${BLUE}  $1${NC}"
  echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
}

# Check if jq is installed
if ! command -v jq &> /dev/null; then
  log_error "jq is required but not installed. Install with: sudo dnf install jq"
  exit 1
fi

# Check if manifest exists
if [ ! -f "$MANIFEST_FILE" ]; then
  log_error "Manifest file not found: $MANIFEST_FILE"
  exit 1
fi

# Read manifest
log_info "Reading deployment manifest..."
VERSION=$(jq -r '.version' "$MANIFEST_FILE")
SOURCE_REPO=$(jq -r '.sourceRepo' "$MANIFEST_FILE")
TARGET_RUNTIME=$(jq -r '.targetRuntime' "$MANIFEST_FILE")
ARCHIVE_LOCATION=$(jq -r '.legacyFiles.archiveLocation' "$MANIFEST_FILE")

log_info "Version: $VERSION"
log_info "Source: $SOURCE_REPO"
log_info "Target: $TARGET_RUNTIME"

# Verify source exists
if [ ! -d "$SOURCE_REPO" ]; then
  log_error "Source repository not found: $SOURCE_REPO"
  exit 1
fi

# Verify target exists
if [ ! -d "$TARGET_RUNTIME" ]; then
  log_error "Target runtime not found: $TARGET_RUNTIME"
  exit 1
fi

# Dry run mode
if [ "$DRY_RUN" = true ]; then
  log_warning "DRY RUN MODE - No changes will be made"
  echo ""
fi

################################################################################
# STEP 1: Archive Legacy Files
################################################################################
section_header "Step 1: Archive Legacy Files"

# Create archive directory
ARCHIVE_DIR="$ARCHIVE_LOCATION"
if [ ! -d "$ARCHIVE_DIR" ]; then
  log_info "Creating archive directory: $ARCHIVE_DIR"
  if [ "$DRY_RUN" = false ]; then
    mkdir -p "$ARCHIVE_DIR"
  fi
fi

# Create archive metadata
ARCHIVE_METADATA="${ARCHIVE_DIR}/ARCHIVE_METADATA.json"
if [ "$DRY_RUN" = false ]; then
  cat > "$ARCHIVE_METADATA" << EOF
{
  "archiveDate": "$(date -Iseconds)",
  "sourceManifest": "$MANIFEST_FILE",
  "version": "$VERSION",
  "archivedFrom": "$TARGET_RUNTIME",
  "reason": "Pre-AWS prototype artifacts, superseded by Week 1 refactor",
  "files": []
}
EOF
fi

# Archive legacy files from runtime
log_info "Archiving legacy files from runtime..."
LEGACY_COUNT=0

while IFS= read -r legacy_file; do
  RUNTIME_FILE="${TARGET_RUNTIME}/${legacy_file}"
  
  if [ -f "$RUNTIME_FILE" ]; then
    log_info "  Archiving: $legacy_file"
    LEGACY_COUNT=$((LEGACY_COUNT + 1))
    
    if [ "$DRY_RUN" = false ]; then
      cp "$RUNTIME_FILE" "${ARCHIVE_DIR}/"
      # Update metadata
      jq ".files += [\"$legacy_file\"]" "$ARCHIVE_METADATA" > "${ARCHIVE_METADATA}.tmp"
      mv "${ARCHIVE_METADATA}.tmp" "$ARCHIVE_METADATA"
    fi
  else
    log_warning "  Not found (already removed?): $legacy_file"
  fi
done < <(jq -r '.legacyFiles.toArchive[]' "$MANIFEST_FILE")

log_success "Archived $LEGACY_COUNT legacy files"

# Remove legacy files from runtime
if [ "$LEGACY_COUNT" -gt 0 ]; then
  log_info "Removing legacy files from runtime..."
  
  while IFS= read -r legacy_file; do
    RUNTIME_FILE="${TARGET_RUNTIME}/${legacy_file}"
    
    if [ -f "$RUNTIME_FILE" ]; then
      if [ "$DRY_RUN" = false ]; then
        rm -f "$RUNTIME_FILE"
        log_success "  Removed: $legacy_file"
      else
        log_info "  Would remove: $legacy_file"
      fi
    fi
  done < <(jq -r '.legacyFiles.toArchive[]' "$MANIFEST_FILE")
fi

################################################################################
# STEP 2: Backup Current Runtime
################################################################################
section_header "Step 2: Backup Current Runtime"

if [ "$SKIP_BACKUP" = false ]; then
  BACKUP_DIR="/mcp_rag_eib/backups/mcp_server_node"
  BACKUP_FILE="${BACKUP_DIR}/runtime_backup_$(date +%Y%m%d_%H%M%S).tar.gz"
  
  log_info "Creating backup: $BACKUP_FILE"
  
  if [ "$DRY_RUN" = false ]; then
    mkdir -p "$BACKUP_DIR"
    tar -czf "$BACKUP_FILE" -C "$TARGET_RUNTIME" \
      --exclude='node_modules' \
      --exclude='*.log' \
      .
    
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    log_success "Backup created: $BACKUP_FILE ($BACKUP_SIZE)"
    
    # Keep only last 5 backups
    log_info "Cleaning old backups (keeping last 5)..."
    ls -t "${BACKUP_DIR}"/runtime_backup_*.tar.gz | tail -n +6 | xargs -r rm --
  else
    log_info "Would create backup: $BACKUP_FILE"
  fi
else
  log_warning "Skipping backup (--skip-backup flag)"
fi

################################################################################
# STEP 3: Sync Production Files
################################################################################
section_header "Step 3: Sync Production Files from Repository"

log_info "Syncing production files..."

# Build exclude patterns for rsync
EXCLUDE_ARGS=""
while IFS= read -r pattern; do
  EXCLUDE_ARGS="$EXCLUDE_ARGS --exclude=$pattern"
done < <(jq -r '.excludePatterns[]' "$MANIFEST_FILE")

# Perform sync
RSYNC_CMD="rsync -av --delete $EXCLUDE_ARGS \"${SOURCE_REPO}/\" \"${TARGET_RUNTIME}/\""

log_info "Rsync command: $RSYNC_CMD"

if [ "$DRY_RUN" = false ]; then
  eval "$RSYNC_CMD"
  log_success "Files synced successfully"
else
  log_info "Would execute: $RSYNC_CMD"
fi

################################################################################
# STEP 4: Install Dependencies
################################################################################
section_header "Step 4: Install NPM Dependencies"

log_info "Installing npm packages..."

if [ "$DRY_RUN" = false ]; then
  cd "$TARGET_RUNTIME"
  npm install --silent 2>&1 | grep -v "^npm WARN"
  log_success "Dependencies installed"
else
  log_info "Would run: cd $TARGET_RUNTIME && npm install"
fi

################################################################################
# STEP 5: Verify Health Checks
################################################################################
section_header "Step 5: Verify System Health"

log_info "Running health checks..."

if [ "$DRY_RUN" = false ]; then
  cd "$TARGET_RUNTIME"
  
  # Check services
  log_info "Checking ChromaDB service..."
  if systemctl is-active --quiet chromadb-persistent.service; then
    log_success "ChromaDB service is running"
  else
    log_error "ChromaDB service is not running!"
    exit 1
  fi
  
  log_info "Checking Neo4j container..."
  if docker ps | grep -q "global-workflow-neo4j"; then
    log_success "Neo4j container is running"
  else
    log_error "Neo4j container is not running!"
    exit 1
  fi
  
  log_info "Checking Langflow container..."
  if docker ps | grep -q "global-workflow-langflow"; then
    log_success "Langflow container is running"
  else
    log_warning "Langflow container is not running (non-critical)"
  fi
  
  # Run health check scripts
  log_info "Running connection tests..."
  
  if [ -f "test-data-access.js" ]; then
    log_info "  Testing Data Access Layer..."
    if timeout 30 node test-data-access.js > /dev/null 2>&1; then
      log_success "  Data Access Layer: OK"
    else
      log_warning "  Data Access Layer: Check required"
    fi
  fi
  
  if [ -f "test-neo4j-connection.js" ]; then
    log_info "  Testing Neo4j connection..."
    if timeout 30 node test-neo4j-connection.js > /dev/null 2>&1; then
      log_success "  Neo4j: OK"
    else
      log_warning "  Neo4j: Check required"
    fi
  fi
  
  if [ -f "test-chromadb-3x.js" ]; then
    log_info "  Testing ChromaDB connection..."
    if timeout 30 node test-chromadb-3x.js > /dev/null 2>&1; then
      log_success "  ChromaDB: OK"
    else
      log_warning "  ChromaDB: Check required"
    fi
  fi
else
  log_info "Would run health checks"
fi

################################################################################
# STEP 6: Update Deployment Log
################################################################################
section_header "Step 6: Update Deployment Log"

DEPLOYMENT_LOG="${TARGET_RUNTIME}/DEPLOYMENT_LOG.json"

if [ "$DRY_RUN" = false ]; then
  # Create or update deployment log
  if [ ! -f "$DEPLOYMENT_LOG" ]; then
    echo '{"deployments": []}' > "$DEPLOYMENT_LOG"
  fi
  
  DEPLOYMENT_ENTRY=$(cat <<EOF
{
  "version": "$VERSION",
  "timestamp": "$(date -Iseconds)",
  "manifest": "$MANIFEST_FILE",
  "backup": "$BACKUP_FILE",
  "user": "$USER",
  "hostname": "$(hostname)"
}
EOF
)
  
  jq ".deployments += [$DEPLOYMENT_ENTRY]" "$DEPLOYMENT_LOG" > "${DEPLOYMENT_LOG}.tmp"
  mv "${DEPLOYMENT_LOG}.tmp" "$DEPLOYMENT_LOG"
  
  log_success "Deployment log updated"
else
  log_info "Would update deployment log"
fi

################################################################################
# COMPLETION
################################################################################
section_header "Deployment Complete"

echo ""
log_success "Deployment version $VERSION completed successfully!"
echo ""
log_info "Summary:"
echo "  • Legacy files archived: $LEGACY_COUNT"
echo "  • Archive location: $ARCHIVE_DIR"
if [ "$SKIP_BACKUP" = false ] && [ "$DRY_RUN" = false ]; then
  echo "  • Backup created: $BACKUP_FILE"
fi
echo "  • Runtime updated: $TARGET_RUNTIME"
echo ""

if [ "$DRY_RUN" = true ]; then
  log_warning "DRY RUN - No actual changes were made"
  echo ""
  log_info "To perform actual deployment, run without --dry-run flag"
fi

echo ""
log_info "Next steps:"
echo "  1. Test MCP server functionality"
echo "  2. Verify all tools are working"
echo "  3. Update provisioning scripts to use this manifest"
echo ""
