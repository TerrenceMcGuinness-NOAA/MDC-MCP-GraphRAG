#!/usr/bin/env python3
"""
Collection Consolidation Script v5.0.0
Merge multiple ChromaDB collections with deduplication and quality filtering

Purpose: Consolidate v4-0-0, v4-1-0, v4-2-0 into unified v5-0-0 collection
Date: November 14, 2025
"""

import os
import sys
import json
import hashlib
from datetime import datetime
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict

import chromadb
from chromadb.config import Settings

# Configuration
CHROMADB_HOST = os.getenv('CHROMADB_HOST', 'localhost')
CHROMADB_PORT = int(os.getenv('CHROMADB_PORT', '8080'))

# Source collections to merge (in priority order - later = higher priority)
SOURCE_COLLECTIONS = [
    'global-workflow-docs-v4-0-0-mpnet',      # 1852 docs - base layer
    'global-workflow-docs-v4-1-0-enhanced',   # 222 docs - enhanced metadata
    'global-workflow-docs-v4-2-0-unified',    # 148 docs - most recent, highest quality
]

# Target collection
TARGET_COLLECTION = 'global-workflow-docs-v5-0-0-consolidated'

# Quality thresholds
MIN_CHUNK_SIZE = 100  # Minimum characters for a chunk to be included
MAX_CHUNK_SIZE = 5000  # Maximum characters (filter out oversized chunks)
MIN_SEMANTIC_DENSITY = 0.1  # Minimum ratio of alpha chars to total chars


class CollectionConsolidator:
    """Merge multiple ChromaDB collections with intelligent deduplication"""
    
    def __init__(self, host: str = CHROMADB_HOST, port: int = CHROMADB_PORT):
        self.client = chromadb.HttpClient(host=host, port=port)
        self.stats = {
            'total_input': 0,
            'deduplicated': 0,
            'quality_filtered': 0,
            'merged': 0,
            'by_source': defaultdict(int),
        }
        self.seen_hashes: Set[str] = set()
        self.url_to_best: Dict[str, Tuple[str, float]] = {}  # url -> (doc_id, quality_score)
        
    def compute_content_hash(self, text: str) -> str:
        """Generate SHA256 hash of normalized text content"""
        normalized = ' '.join(text.lower().split())
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    
    def compute_quality_score(self, text: str, metadata: Dict) -> float:
        """
        Calculate quality score for a document chunk
        
        Factors:
        - Length appropriateness (0-1)
        - Semantic density (0-1)
        - Has URL reference (0-1)
        - Header structure presence (0-1)
        - Metadata richness (0-1)
        """
        score = 0.0
        
        # Length score (prefer 500-2000 char chunks)
        length = len(text)
        if 500 <= length <= 2000:
            score += 1.0
        elif 200 <= length < 500 or 2000 < length <= 3000:
            score += 0.7
        elif length < 200:
            score += 0.3
        else:
            score += 0.1
        
        # Semantic density (alpha chars / total chars)
        alpha_count = sum(c.isalpha() for c in text)
        if length > 0:
            density = alpha_count / length
            score += min(density / MIN_SEMANTIC_DENSITY, 1.0)
        
        # URL reference bonus
        if metadata.get('url') or metadata.get('source_url'):
            score += 1.0
        
        # Header structure (indicates well-structured content)
        if any(marker in text for marker in ['##', '===', '---', '```']):
            score += 0.5
        
        # Metadata richness
        metadata_keys = len(metadata.keys())
        score += min(metadata_keys / 10.0, 1.0)
        
        return score / 5.5  # Normalize to 0-1 range
    
    def passes_quality_filter(self, text: str, metadata: Dict) -> bool:
        """Check if document chunk meets minimum quality standards"""
        
        # Size filters
        length = len(text)
        if length < MIN_CHUNK_SIZE or length > MAX_CHUNK_SIZE:
            return False
        
        # Semantic density filter
        alpha_count = sum(c.isalpha() for c in text)
        if length > 0:
            density = alpha_count / length
            if density < MIN_SEMANTIC_DENSITY:
                return False
        
        # Must have some content
        if not text.strip():
            return False
        
        return True
    
    def should_keep(self, doc_id: str, text: str, metadata: Dict, 
                    collection_name: str) -> bool:
        """
        Determine if document should be kept based on deduplication and quality
        
        Returns True if document should be added to target collection
        """
        
        # Quality filter first
        if not self.passes_quality_filter(text, metadata):
            self.stats['quality_filtered'] += 1
            return False
        
        # Content-based deduplication
        content_hash = self.compute_content_hash(text)
        if content_hash in self.seen_hashes:
            self.stats['deduplicated'] += 1
            return False
        
        # URL-based deduplication (keep higher quality version)
        url = metadata.get('url') or metadata.get('source_url')
        if url:
            quality_score = self.compute_quality_score(text, metadata)
            
            if url in self.url_to_best:
                existing_id, existing_score = self.url_to_best[url]
                if quality_score > existing_score:
                    # New document is better, remove old one
                    self.url_to_best[url] = (doc_id, quality_score)
                    # Mark old hash for removal if we tracked it
                    self.stats['deduplicated'] += 1
                else:
                    # Existing document is better, skip this one
                    self.stats['deduplicated'] += 1
                    return False
            else:
                self.url_to_best[url] = (doc_id, quality_score)
        
        # Mark as seen
        self.seen_hashes.add(content_hash)
        self.stats['by_source'][collection_name] += 1
        
        return True
    
    def consolidate(self, dry_run: bool = False) -> Dict:
        """
        Main consolidation workflow
        
        Args:
            dry_run: If True, analyze without creating target collection
            
        Returns:
            Statistics dictionary
        """
        
        print(f"[INIT] Collection Consolidation v5.0.0")
        print(f"[INIT] ChromaDB: {CHROMADB_HOST}:{CHROMADB_PORT}")
        print(f"[INIT] Target: {TARGET_COLLECTION}")
        print(f"[INIT] Dry run: {dry_run}\n")
        
        # Check if target already exists
        existing_collections = [c.name for c in self.client.list_collections()]
        if TARGET_COLLECTION in existing_collections and not dry_run:
            print(f"[WARN] Target collection already exists: {TARGET_COLLECTION}")
            response = input("Delete and recreate? (yes/no): ")
            if response.lower() == 'yes':
                self.client.delete_collection(TARGET_COLLECTION)
                print(f"[OK] Deleted existing collection")
            else:
                print(f"[ABORT] Consolidation cancelled")
                return self.stats
        
        # Create target collection (if not dry run)
        target_col = None
        if not dry_run:
            target_col = self.client.create_collection(
                name=TARGET_COLLECTION,
                metadata={
                    'version': '5.0.0-consolidated',
                    'created': datetime.now().isoformat(),
                    'embedding_model': 'all-mpnet-base-v2',
                    'embedding_dimensions': '768',
                    'description': 'Consolidated Global Workflow Documentation v5.0.0',
                    'source_collections': ','.join(SOURCE_COLLECTIONS),
                    'min_chunk_size': str(MIN_CHUNK_SIZE),
                    'max_chunk_size': str(MAX_CHUNK_SIZE),
                    'quality_filtered': 'true',
                    'deduplicated': 'true',
                }
            )
            print(f"[OK] Created target collection\n")
        
        # Process each source collection
        for source_name in SOURCE_COLLECTIONS:
            if source_name not in existing_collections:
                print(f"[SKIP] Collection not found: {source_name}")
                continue
            
            print(f"[PROCESS] {source_name}")
            source_col = self.client.get_collection(source_name)
            
            # Get all documents (handle ChromaDB batching)
            total_docs = source_col.count()
            batch_size = 1000
            offset = 0
            docs_kept = 0
            
            while offset < total_docs:
                # Fetch batch
                result = source_col.get(
                    limit=batch_size,
                    offset=offset,
                    include=['documents', 'metadatas', 'embeddings']
                )
                
                batch_ids = result['ids']
                batch_docs = result['documents']
                batch_metas = result['metadatas']
                batch_embeds = result['embeddings']
                
                # Process each document in batch
                keep_ids = []
                keep_docs = []
                keep_metas = []
                keep_embeds = []
                
                for i, doc_id in enumerate(batch_ids):
                    self.stats['total_input'] += 1
                    
                    text = batch_docs[i]
                    metadata = batch_metas[i] or {}
                    embedding = batch_embeds[i]
                    
                    if self.should_keep(doc_id, text, metadata, source_name):
                        # Add source collection to metadata
                        metadata['source_collection'] = source_name
                        metadata['consolidated_at'] = datetime.now().isoformat()
                        
                        keep_ids.append(doc_id)
                        keep_docs.append(text)
                        keep_metas.append(metadata)
                        keep_embeds.append(embedding)
                        docs_kept += 1
                
                # Add batch to target collection
                if keep_ids and not dry_run:
                    target_col.add(
                        ids=keep_ids,
                        documents=keep_docs,
                        metadatas=keep_metas,
                        embeddings=keep_embeds
                    )
                
                offset += batch_size
                print(f"  Processed {min(offset, total_docs)}/{total_docs} docs", end='\r')
            
            print(f"  [OK] Kept {docs_kept}/{total_docs} docs from {source_name}")
            self.stats['merged'] += docs_kept
        
        # Final statistics
        print(f"\n[COMPLETE] Consolidation Statistics:")
        print(f"  Total input documents: {self.stats['total_input']}")
        print(f"  Quality filtered: {self.stats['quality_filtered']}")
        print(f"  Deduplicated: {self.stats['deduplicated']}")
        print(f"  Final merged count: {self.stats['merged']}")
        print(f"\n  By source collection:")
        for source, count in self.stats['by_source'].items():
            print(f"    {source}: {count}")
        
        if not dry_run:
            final_count = target_col.count()
            print(f"\n[OK] Target collection document count: {final_count}")
        
        return self.stats


def main():
    """Main entry point"""
    
    import argparse
    parser = argparse.ArgumentParser(
        description='Consolidate multiple ChromaDB collections into unified v5.0.0'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Analyze without creating target collection'
    )
    parser.add_argument(
        '--host',
        default=CHROMADB_HOST,
        help=f'ChromaDB host (default: {CHROMADB_HOST})'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=CHROMADB_PORT,
        help=f'ChromaDB port (default: {CHROMADB_PORT})'
    )
    
    args = parser.parse_args()
    
    try:
        consolidator = CollectionConsolidator(host=args.host, port=args.port)
        stats = consolidator.consolidate(dry_run=args.dry_run)
        
        # Write stats to JSON
        stats_file = '/mcp_rag_eib/eib-mcp-rag-server/mcp_server_node/logs/consolidation_v5_stats.json'
        os.makedirs(os.path.dirname(stats_file), exist_ok=True)
        
        with open(stats_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'dry_run': args.dry_run,
                'stats': dict(stats),
                'by_source': dict(stats.get('by_source', {})),
            }, f, indent=2)
        
        print(f"\n[OK] Statistics written to: {stats_file}")
        
    except Exception as e:
        print(f"\n[ERROR] Consolidation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
