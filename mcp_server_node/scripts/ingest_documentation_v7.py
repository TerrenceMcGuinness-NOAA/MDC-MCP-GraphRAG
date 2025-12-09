#!/usr/bin/env python3
"""
Documentation Ingestion Script v7.0.0
Unified documentation ingestion with v7 collection naming

This script consolidates all documentation ingestion into a single v7 collection
with consistent naming convention aligned with MCP server references.

Collection: global-workflow-docs-v7-0-0
Target: 2000+ documents from all tier documentation sources

╔══════════════════════════════════════════════════════════════════════════════╗
║  SPOT COMPLIANCE: This script imports from documentation_sources_config.py  ║
║  DO NOT add inline DOCUMENTATION_SOURCES dict - modify the SPOT config!     ║
╚══════════════════════════════════════════════════════════════════════════════╝

Author: NOAA EMC Global Workflow MCP Team
Version: 7.0.0
Date: December 4, 2025
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Import base library components
from ingestion_base import (
    SemanticChunker,
    ChromaDBClient,
    URLCrawler,
    MetadataEnricher,
    BaseIngester
)

# ============================================================================
# SPOT IMPORT - Single Point of Truth for Documentation Sources
# ============================================================================
# All documentation URLs are defined in documentation_sources_config.py
# This ensures consistency across all ingestion scripts and listing utilities.
# ============================================================================
from documentation_sources_config import (
    DOCUMENTATION_SOURCES,
    VERSION,
    COLLECTION_NAME as DEFAULT_COLLECTION,
    get_all_sources,
    get_tier_names,
    get_total_source_count,
    validate_sources
)

# ============================================================================
# V7 CONFIGURATION (uses SPOT values with optional env overrides)
# ============================================================================

COLLECTION_NAME = os.getenv("DOCS_COLLECTION", DEFAULT_COLLECTION)
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))


# ============================================================================
# INGESTER CLASS
# ============================================================================

class DocumentationIngesterV7(BaseIngester):
    """V7 Documentation ingester with consolidated collection naming"""
    
    def __init__(self, collection_name: str = COLLECTION_NAME):
        super().__init__(collection_name, VERSION)
        self.enricher = MetadataEnricher()
        self.crawler = URLCrawler(delay=1.0)
        self.seen_ids = set()
        self.stats = {
            'sources_processed': 0,
            'documents_processed': 0,
            'chunks_created': 0,
            'chunks_added': 0,
            'duplicates_skipped': 0,
            'errors': 0
        }
        
        # Initialize the collection (required by BaseIngester)
        self.initialize({
            "description": "Global Workflow Documentation - Unified V7 Collection",
            "version": VERSION,
            "created": datetime.now().isoformat(),
            "embedding_model": "all-mpnet-base-v2",
            "embedding_dimensions": "768",
            "tiers": "tier1_critical, tier2_important, tier3_supplementary"
        })
        
        # Load existing document IDs from collection to avoid duplicates on re-run
        self._load_existing_ids()
    
    def _load_existing_ids(self):
        """Load existing document IDs from collection to enable incremental ingestion"""
        try:
            existing = self.collection.get(include=[])
            self.seen_ids = set(existing['ids'])
            if self.seen_ids:
                print(f"[INFO] Loaded {len(self.seen_ids)} existing document IDs (incremental mode)")
        except Exception as e:
            print(f"[WARN] Could not load existing IDs: {e}")
            self.seen_ids = set()
    
    def ingest_all_tiers(self, tiers: list = None):
        """Ingest documentation from specified tiers"""
        if tiers is None:
            tiers = list(DOCUMENTATION_SOURCES.keys())
        
        print(f"\n{'='*70}")
        print(f"Documentation Ingestion v{VERSION}")
        print(f"Collection: {self.collection_name}")
        print(f"Tiers: {', '.join(tiers)}")
        print(f"{'='*70}\n")
        
        for tier_name in tiers:
            if tier_name not in DOCUMENTATION_SOURCES:
                print(f"[WARN] Unknown tier: {tier_name}")
                continue
            
            sources = DOCUMENTATION_SOURCES[tier_name]
            print(f"\n[TIER] Processing {tier_name} ({len(sources)} sources)")
            
            for source in sources:
                self._ingest_source(source)
        
        self._print_summary()
    
    def _ingest_source(self, source: dict):
        """Ingest a single documentation source"""
        name = source['name']
        url = source['url']
        max_pages = source.get('max_pages', 50)
        sitemap_url = source.get('sitemap')
        exclude_patterns = source.get('exclude_url_patterns', [])
        
        print(f"\n  [SOURCE] {name}: {url}")
        if exclude_patterns:
            print(f"    [INFO] Using {len(exclude_patterns)} URL exclusion patterns")
        
        try:
            # Create fresh crawler with exclusion patterns
            crawler = URLCrawler(delay=1.0, exclude_url_patterns=exclude_patterns)
            
            pages = []
            
            # If sitemap is specified, use it to get URLs (avoids following stale links)
            if sitemap_url:
                print(f"    [INFO] Using sitemap: {sitemap_url}")
                sitemap_urls = crawler.fetch_sitemap(sitemap_url)
                if sitemap_urls:
                    # Filter to only URLs under the base path and limit to max_pages
                    base_path = url.rstrip('/')
                    filtered_urls = [u for u in sitemap_urls if u.startswith(base_path)][:max_pages]
                    print(f"    [INFO] Found {len(sitemap_urls)} URLs in sitemap, {len(filtered_urls)} matching base path")
                    
                    # Fetch each URL from sitemap
                    for page_url in filtered_urls:
                        result = crawler.fetch_page(page_url)
                        if result:
                            title, soup = result
                            pages.append((page_url, title, soup))
                else:
                    print(f"    [WARN] Sitemap fetch failed, falling back to recursive crawl")
                    pages = crawler.crawl_recursive(url, max_pages=max_pages)
            else:
                # No sitemap - use recursive crawl (original behavior)
                pages = crawler.crawl_recursive(url, max_pages=max_pages)
            
            self.stats['sources_processed'] += 1
            
            for page_url, title, soup in pages:
                # Extract text content from soup
                if not soup:
                    continue
                    
                self.stats['documents_processed'] += 1
                
                # Use SemanticChunker's chunk_by_headers for HTML content
                raw_chunks = self.chunker.chunk_by_headers(soup, page_url)
                
                # Enrich chunks with metadata
                for chunk in raw_chunks:
                    if len(chunk.get('content', '')) < 100:
                        continue
                        
                    self.stats['chunks_created'] += 1
                    
                    doc_id = self._generate_id(chunk['content'], page_url)
                    
                    if doc_id in self.seen_ids:
                        self.stats['duplicates_skipped'] += 1
                        continue
                    
                    # Build metadata
                    metadata = {
                        'source': name,
                        'url': page_url,
                        'title': title,
                        'hierarchy': chunk.get('hierarchy', ''),
                        'priority': source['priority'],
                        'description': source['description'],
                        'content_hash': chunk.get('hash', ''),
                        'ingested_at': datetime.now().isoformat(),
                        'version': VERSION
                    }
                    
                    self.seen_ids.add(doc_id)
                    
                    # Add directly to collection
                    self.collection.add(
                        ids=[doc_id],
                        documents=[chunk['content']],
                        metadatas=[metadata]
                    )
                    self.stats['chunks_added'] += 1
            
            print(f"    [OK] {len(pages)} pages processed")
            
        except Exception as e:
            print(f"    [ERROR] {e}")
            self.stats['errors'] += 1
    
    def _generate_id(self, text: str, url: str) -> str:
        """Generate unique document ID"""
        import hashlib
        content = f"{url}:{text[:500]}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _print_summary(self):
        """Print ingestion summary"""
        print(f"\n{'='*70}")
        print("INGESTION SUMMARY")
        print(f"{'='*70}")
        print(f"Collection:         {self.collection_name}")
        print(f"Version:            {VERSION}")
        print(f"Sources processed:  {self.stats['sources_processed']}")
        print(f"Documents:          {self.stats['documents_processed']}")
        print(f"Chunks created:     {self.stats['chunks_created']}")
        print(f"Chunks added:       {self.stats['chunks_added']}")
        print(f"Duplicates skipped: {self.stats['duplicates_skipped']}")
        print(f"Errors:             {self.stats['errors']}")
        print(f"{'='*70}\n")


def main():
    """Main entry point"""
    import argparse
    
    # Get valid tier names from the SPOT config
    valid_tiers = list(DOCUMENTATION_SOURCES.keys())
    
    parser = argparse.ArgumentParser(description='V7 Documentation Ingestion')
    parser.add_argument('--collection', default=COLLECTION_NAME,
                       help=f'Collection name (default: {COLLECTION_NAME})')
    parser.add_argument('--tiers', nargs='+', 
                       choices=valid_tiers,
                       help=f'Tiers to ingest (default: all). Valid: {", ".join(valid_tiers)}')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be ingested without actually ingesting')
    
    args = parser.parse_args()
    
    if args.dry_run:
        print("[DRY RUN] Would ingest the following:")
        for tier, sources in DOCUMENTATION_SOURCES.items():
            if args.tiers is None or tier in args.tiers:
                print(f"\n{tier}:")
                for s in sources:
                    print(f"  - {s['name']}: {s['url']}")
        return
    
    ingester = DocumentationIngesterV7(args.collection)
    ingester.ingest_all_tiers(args.tiers)


if __name__ == '__main__':
    main()
