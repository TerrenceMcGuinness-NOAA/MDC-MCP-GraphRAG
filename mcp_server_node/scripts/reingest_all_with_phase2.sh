#!/bin/bash
###############################################################################
# Complete Re-Ingestion Script with Phase 2 Annotations
# 
# Purpose: Re-ingest ALL documentation sources when changing embedding models
#          (e.g., upgrading to Gemini Pro API or different embedding dimensions)
#
# Usage:
#   ./reingest_all_with_phase2.sh <new_collection_name>
#
# Example:
#   ./reingest_all_with_phase2.sh global-workflow-docs-v5-0-0-gemini-pro
#
# What this does:
#   1. Ingests standard documentation sources (global-workflow, EE2, UFS, etc.)
#   2. Ingests Phase 2 semantic annotations (sdd_framework/phase2_annotations/)
#   3. Generates updated phase2_anti_patterns.json config
#   4. Validates ingestion results
#
# Author: NOAA EMC Global Workflow MCP Team
# Version: 1.0.0
# Date: November 19, 2025
###############################################################################

set -e  # Exit on any error
set -x  # Debug logging

# Check arguments
if [ $# -lt 1 ]; then
    echo "ERROR: Collection name required"
    echo "Usage: $0 <collection_name>"
    echo "Example: $0 global-workflow-docs-v5-0-0-gemini-pro"
    exit 1
fi

COLLECTION_NAME="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_SERVER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PHASE2_ANNOTATIONS_DIR="$(cd "$MCP_SERVER_DIR/../sdd_framework/phase2_annotations" && pwd)"

echo "======================================================================="
echo "COMPLETE RE-INGESTION WITH PHASE 2 ANNOTATIONS"
echo "======================================================================="
echo "Collection: $COLLECTION_NAME"
echo "Script Directory: $SCRIPT_DIR"
echo "MCP Server Directory: $MCP_SERVER_DIR"
echo "Phase 2 Annotations: $PHASE2_ANNOTATIONS_DIR"
echo "======================================================================="

# Step 1: Ingest standard documentation sources
echo ""
echo "[STEP 1/4] Ingesting standard documentation sources..."
echo "-----------------------------------------------------------------------"
cd "$SCRIPT_DIR"
python3 ingest_documentation_week3.py \
    --collection "$COLLECTION_NAME" \
    --verbose

# Check if ingestion succeeded
if [ $? -ne 0 ]; then
    echo "[ERROR] Standard documentation ingestion failed"
    exit 1
fi

# Step 2: Ingest Phase 2 semantic annotations
echo ""
echo "[STEP 2/4] Ingesting Phase 2 semantic annotations..."
echo "-----------------------------------------------------------------------"
python3 ingest_ee2_enhanced_v5.py \
    "$PHASE2_ANNOTATIONS_DIR" \
    --collection "$COLLECTION_NAME" \
    --pattern "*.rst"

# Check if ingestion succeeded
if [ $? -ne 0 ]; then
    echo "[ERROR] Phase 2 annotations ingestion failed"
    exit 1
fi

# Step 3: Generate Phase 2 configuration
echo ""
echo "[STEP 3/4] Generating Phase 2 anti-pattern configuration..."
echo "-----------------------------------------------------------------------"
cd "$MCP_SERVER_DIR"

# Update generatePhase2Config.js to use new collection if needed
# For now, assume it uses COLLECTION_NAME environment variable or default
COLLECTION_NAME="$COLLECTION_NAME" node scripts/generatePhase2Config.js

# Check if config generation succeeded
if [ $? -ne 0 ]; then
    echo "[ERROR] Phase 2 config generation failed"
    exit 1
fi

# Step 4: Validate results
echo ""
echo "[STEP 4/4] Validating ingestion results..."
echo "-----------------------------------------------------------------------"

# Query ChromaDB to verify collection exists and has documents
python3 << EOF
import chromadb
from chromadb.config import Settings

client = chromadb.HttpClient(
    host='localhost',
    port=8080,
    settings=Settings(anonymized_telemetry=False)
)

# Get collection
try:
    collection = client.get_collection('$COLLECTION_NAME')
    count = collection.count()
    print(f"[OK] Collection '$COLLECTION_NAME' has {count} documents")
    
    # Count Phase 2 annotations
    results = collection.get(limit=count)
    phase2_count = 0
    for meta in results['metadatas']:
        if 'phase2_annotations' in str(meta.get('source_file', '')):
            phase2_count += 1
    
    print(f"[OK] Phase 2 annotations: {phase2_count} chunks")
    
    # Verify phase2_anti_patterns.json exists
    import os
    config_path = '$MCP_SERVER_DIR/phase2_anti_patterns.json'
    if os.path.exists(config_path):
        import json
        with open(config_path) as f:
            config = json.load(f)
        print(f"[OK] Phase 2 config generated:")
        print(f"     - Anti-patterns: {sum(len(v) for v in config['anti_patterns'].values())}")
        print(f"     - Correct patterns: {sum(len(v) for v in config['correct_patterns'].values())}")
        print(f"     - AI guidance rules: {len(config['ai_guidance_rules'])}")
    else:
        print(f"[WARN] Phase 2 config not found at {config_path}")
    
except Exception as e:
    print(f"[ERROR] Validation failed: {e}")
    exit(1)
EOF

if [ $? -ne 0 ]; then
    echo "[ERROR] Validation failed"
    exit 1
fi

# Success!
echo ""
echo "======================================================================="
echo "RE-INGESTION COMPLETE"
echo "======================================================================="
echo "Collection: $COLLECTION_NAME"
echo ""
echo "Next steps:"
echo "  1. Update MCP server to use new collection"
echo "  2. Restart MCP server to load new embeddings"
echo "  3. Test semantic search with new embeddings"
echo ""
echo "MCP Server Configuration:"
echo "  - Update: mcp_server_node/.env or mcp-config.env"
echo "  - Set: COLLECTION_NAME=$COLLECTION_NAME"
echo "  - Restart: pkill -9 -f UnifiedMCPServer && code ."
echo "======================================================================="
