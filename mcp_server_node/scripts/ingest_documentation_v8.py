#!/usr/bin/env python3
"""
Documentation Ingestion Script v8.0.0
MPNet 768-dim embeddings with v8 collection naming

This is a v8 wrapper around the v7 ingestion logic with:
- Explicit MPNet embeddings (768 dimensions)
- v8 collection naming: global-workflow-docs-v8-0-0
- Pre-computed embeddings for consistency

Author: NOAA EMC Global Workflow MCP Team
Version: 8.0.0
Date: February 4, 2026
"""

import os
import sys
from datetime import datetime

# Phase 49: Registry-driven model selection
try:
    import sys as _sys
    from embedding_registry import EmbeddingModelRegistry as _Reg
    from collection_namer import CollectionNamer as _CN
    _args_model = os.environ.get("MCP_EMBEDDING_PROFILE", "mpnet768")
    for _i, _a in enumerate(_sys.argv):
        if _a == "--model" and _i + 1 < len(_sys.argv):
            _args_model = _sys.argv[_i + 1]
    _profile = _Reg().get_profile(_args_model)
    _namer = _CN(_profile)
    EMBEDDING_MODEL = _profile.model_id
    EMBEDDING_DIMENSIONS = _profile.dimensions
    _REGISTRY_COLLECTION = _namer.get_name("global-workflow-docs", "v8-0-0")
    _REGISTRY_AVAILABLE = True
except Exception:
    _REGISTRY_AVAILABLE = False
    EMBEDDING_MODEL = "all-mpnet-base-v2"
    EMBEDDING_DIMENSIONS = 768
    _REGISTRY_COLLECTION = None

# Optional explicit collection-name override (Task 5e.b, disk-priority-ingest).
# When absent, the default namer output (_REGISTRY_COLLECTION) is used unchanged,
# so COTS behaviour is preserved. When present, it targets a specific serving
# index (e.g. mdc-workflow-docs-titan1024 on AWS) WITHOUT altering the namer.
_args_collection = None
for _i, _a in enumerate(sys.argv):
    if _a == "--collection" and _i + 1 < len(sys.argv):
        _args_collection = sys.argv[_i + 1]

# Set v8 collection name before importing v7 module
_col = _args_collection or _REGISTRY_COLLECTION or "global-workflow-docs-v8-0-0"
os.environ['DOCS_COLLECTION'] = _col

# Import the v7 ingestion logic (uses ingestion_base with MPNet)
from ingest_documentation_v7 import (
    DocumentationIngesterV7,
    DOCUMENTATION_SOURCES,
    VERSION
)

# V8 Configuration
VERSION_V8 = "8.0.0"
COLLECTION_NAME = _args_collection or _REGISTRY_COLLECTION or "global-workflow-docs-v8-0-0"
# EMBEDDING_MODEL and EMBEDDING_DIMENSIONS set by registry block above


class DocumentationIngesterV8(DocumentationIngesterV7):
    """V8 Documentation ingester with explicit MPNet embeddings"""
    
    def __init__(self, delay: float = 1.0):
        # Override collection name
        super().__init__(COLLECTION_NAME, delay=delay)
        
        # Update collection metadata for v8
        self.collection.modify(metadata={
            "description": "Global Workflow Documentation - V8 MPNet Collection",
            "version": VERSION_V8,
            "created": datetime.now().isoformat(),
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dimensions": str(EMBEDDING_DIMENSIONS),
            "tiers": "tier1_critical, tier2_important, tier3_supplementary"
        })
        
        print(f"[OK] V8 Collection initialized: {COLLECTION_NAME}")
        print(f"[OK] Embedding model: {EMBEDDING_MODEL} ({EMBEDDING_DIMENSIONS} dimensions)")


def main():
    """Main entry point for v8 ingestion"""
    import argparse
    
    valid_tiers = list(DOCUMENTATION_SOURCES.keys())
    
    parser = argparse.ArgumentParser(description='V8 Documentation Ingestion (MPNet 768-dim)')
    parser.add_argument('--tiers', nargs='+', 
                       choices=valid_tiers,
                       help=f'Tiers to ingest (default: all). Valid: {", ".join(valid_tiers)}')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be ingested without actually ingesting')
    parser.add_argument('--delay', type=float, default=1.0,
                       help='Seconds between page fetches (default: 1.0, use 5+ for rate-limited sites)')
    parser.add_argument('--only', nargs='+', default=None,
                       help='Only ingest the listed source names (filters within --tiers)')
    parser.add_argument('--collection', default=None,
                       help='Explicit target collection/index name override. '
                            'Absent = default namer output (unchanged for COTS).')
    
    args, _ = parser.parse_known_args()
    
    print("=" * 70)
    print("DOCUMENTATION INGESTION V8.0.0 - MPNet Embeddings")
    print("=" * 70)
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Embedding:  {EMBEDDING_MODEL} ({EMBEDDING_DIMENSIONS} dimensions)")
    print(f"Delay:      {args.delay}s between fetches")
    if args.only:
        print(f"Filter:     only={args.only}")
    print("=" * 70)
    
    if args.dry_run:
        print("\n[DRY RUN] Would ingest the following:")
        for tier, sources in DOCUMENTATION_SOURCES.items():
            if args.tiers is None or tier in args.tiers:
                filtered = sources if not args.only else [s for s in sources if s['name'] in args.only]
                if not filtered:
                    continue
                print(f"\n{tier}:")
                for s in filtered:
                    print(f"  - {s['name']}: {s['url']}")
        return
    
    ingester = DocumentationIngesterV8(delay=args.delay)
    ingester.ingest_all_tiers(args.tiers, only=args.only)
    
    # Final verification
    print(f"\n[OK] V8 Ingestion complete: {ingester.collection.count()} documents")


if __name__ == '__main__':
    main()
