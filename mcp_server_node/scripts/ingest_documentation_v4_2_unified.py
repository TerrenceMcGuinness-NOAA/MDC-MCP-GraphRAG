#!/usr/bin/env python3
"""
Unified Documentation Ingestion Script - v4.2.0
Phase 2: Comprehensive documentation ingestion using base library

Consolidates v4.0 and v4.1 capabilities:
- All readthedocs sites (global-workflow, UFS, wxflow, spack-stack, etc.)
- Quality improvements from v4.1 (semantic chunking, metadata enrichment)
- Base library code reuse (90%+ reduction in custom code)

Collection: global-workflow-docs-v4-2-0-unified
Target: ~2000-3000 chunks from 10+ documentation sources
"""

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

# Import SINGLE SOURCE OF TRUTH for documentation sources
from documentation_sources_config import (
    DOCUMENTATION_SOURCES,
    COLLECTION_NAME,
    VERSION,
    get_tier_names,
    validate_sources
)


class UnifiedDocumentationIngester(BaseIngester):
    """Unified ingester for all documentation sources"""
    
    def __init__(self, collection_name: str = COLLECTION_NAME):
        super().__init__(collection_name, VERSION)
        self.enricher = MetadataEnricher()
        self.crawler = URLCrawler(delay=1.0)
        self.seen_ids = set()  # Track seen IDs for deduplication
        # Initialize stats
        self.stats = {
            'sources_processed': 0,
            'documents_processed': 0,
            'chunks_created': 0,
            'chunks_added': 0,
            'duplicates_skipped': 0,
            'errors': 0
        }
    
    def ingest_all_tiers(self, tiers: list = None):
        """Ingest documentation from specified tiers (or all if None)"""
        if tiers is None:
            tiers = get_tier_names()
        
        print(f"\n{'='*70}")
        print(f"UNIFIED DOCUMENTATION INGESTION - v{VERSION}")
        print(f"{'='*70}")
        print(f"Target collection: {COLLECTION_NAME}")
        print(f"Tiers to ingest: {', '.join(tiers)}")
        print(f"{'='*70}\n")
        
        # Initialize database connection and collection
        print(f"[INFO] Initializing ChromaDB connection...")
        self.initialize()
        print(f"[OK] Connected to collection: {COLLECTION_NAME}\n")
        
        total_sources = sum(len(DOCUMENTATION_SOURCES[tier]) for tier in tiers 
                           if tier in DOCUMENTATION_SOURCES)
        current = 0
        
        for tier in tiers:
            if tier not in DOCUMENTATION_SOURCES:
                print(f"[WARN] Unknown tier: {tier}")
                continue
            
            print(f"\n[TIER] Processing {tier}")
            print(f"{'='*70}")
            
            for source in DOCUMENTATION_SOURCES[tier]:
                current += 1
                self._ingest_source(source, tier, current, total_sources)
        
        self.print_summary()
    
    def _ingest_source(self, source: dict, tier: str, current: int, total: int):
        """Ingest a single documentation source"""
        name = source['name']
        url = source['url']
        max_pages = source.get('max_pages', 100)
        
        print(f"\n[{current}/{total}] {name}")
        print(f"  URL: {url}")
        print(f"  Type: {source['type']}")
        print(f"  Tier: {tier}")
        
        try:
            # Crawl the documentation site
            print(f"  [INFO] Crawling (max {max_pages} pages)...")
            raw_results = self.crawler.crawl_recursive(url, max_pages=max_pages)
            
            # Convert to expected format
            raw_docs = []
            for page_url, title, soup in raw_results:
                raw_docs.append({
                    'url': page_url,
                    'title': title,
                    'content': soup
                })
            
            print(f"  [OK] Found {len(raw_docs)} pages")
            
            if not raw_docs:
                print(f"  [WARN] No documents found, skipping")
                return
            
            # Chunk documents semantically
            print(f"  [INFO] Chunking documents...")
            all_chunks = []
            for doc in raw_docs:
                # Extract text content from BeautifulSoup
                soup = doc['content']
                
                # Get main content (remove navigation, etc.)
                main_content = soup.find('main') or soup.find('article') or soup.find('body') or soup
                text_content = main_content.get_text(separator='\n', strip=True)
                
                # Chunk as markdown (most documentation is markdown-like structure)
                chunks = self.chunker.chunk_markdown(text_content, doc['url'])
                
                # Enrich metadata for each chunk
                for chunk in chunks:
                    # Build metadata dict
                    metadata = {
                        'source': name,
                        'tier': tier,
                        'priority': source['priority'],
                        'doc_type': source['type'],
                        'description': source['description'],
                        'version': VERSION,
                        'ingestion_date': datetime.now().isoformat(),
                        'url': chunk.get('source', doc['url']),
                        'section_hierarchy': chunk.get('hierarchy', ''),
                        'content_hash': chunk.get('hash', '')
                    }
                    
                    # Add quality scoring
                    quality_score = self.enricher.calculate_quality_score(
                        chunk['content'],
                        metadata
                    )
                    metadata['quality_score'] = quality_score
                    
                    # Store as final chunk format
                    all_chunks.append({
                        'text': chunk['content'],
                        'metadata': metadata
                    })
            
            print(f"  [OK] Created {len(all_chunks)} chunks")
            
            # Add to ChromaDB with deduplication
            print(f"  [INFO] Adding to ChromaDB...")
            added, skipped = self._add_chunks_with_dedup(all_chunks, name)
            print(f"  [OK] Added {added} chunks ({skipped} duplicates skipped)")
            
            # Update stats
            self.stats['sources_processed'] += 1
            self.stats['documents_processed'] += len(raw_docs)
            self.stats['chunks_created'] += len(all_chunks)
            self.stats['chunks_added'] += added
            self.stats['duplicates_skipped'] += skipped
            
        except Exception as e:
            print(f"  [ERROR] Failed to ingest {name}: {e}")
            self.stats['errors'] += 1
            import traceback
            traceback.print_exc()
    
    def _add_chunks_with_dedup(self, chunks: list, source_name: str) -> tuple:
        """Add chunks to ChromaDB with content-based deduplication"""
        added = 0
        skipped = 0
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{source_name}_{chunk['metadata'].get('content_hash', i)}"
            
            # Check if already exists
            if chunk_id in self.seen_ids:
                skipped += 1
                continue
            
            try:
                self.collection.add(
                    documents=[chunk['text']],
                    metadatas=[chunk['metadata']],
                    ids=[chunk_id]
                )
                self.seen_ids.add(chunk_id)
                added += 1
            except Exception as e:
                print(f"    [WARN] Failed to add chunk {chunk_id}: {e}")
                skipped += 1
        
        return added, skipped
    
    def print_summary(self):
        """Print ingestion summary with collection statistics"""
        print(f"\n{'='*70}")
        print("INGESTION COMPLETE")
        print(f"{'='*70}")
        print(f"Sources processed: {self.stats['sources_processed']}")
        print(f"Documents crawled: {self.stats['documents_processed']}")
        print(f"Chunks created: {self.stats['chunks_created']}")
        print(f"Chunks added: {self.stats['chunks_added']}")
        print(f"Duplicates skipped: {self.stats['duplicates_skipped']}")
        print(f"Errors: {self.stats['errors']}")
        
        # Get final collection stats
        try:
            count = self.collection.count()
            print(f"\nFinal collection size: {count} documents")
        except:
            pass
        
        print(f"{'='*70}\n")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Unified documentation ingestion for global-workflow',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run: Show what would be ingested without actually doing it
  python3 ingest_documentation_v4_2_unified.py --dry-run

  # Ingest all tiers
  python3 ingest_documentation_v4_2_unified.py

  # Ingest only tier1 (critical docs)
  python3 ingest_documentation_v4_2_unified.py --tiers tier1_critical

  # Ingest tiers 1 and 2
  python3 ingest_documentation_v4_2_unified.py --tiers tier1_critical tier2_infrastructure
        """
    )
    parser.add_argument(
        '--tiers',
        nargs='+',
        choices=['tier1_critical', 'tier2_infrastructure', 'tier3_build_system', 'tier4_reference'],
        help='Specific tiers to ingest (default: all)'
    )
    parser.add_argument(
        '--collection',
        default=COLLECTION_NAME,
        help=f'Collection name (default: {COLLECTION_NAME})'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show ingestion plan without actually crawling or ingesting'
    )
    
    args = parser.parse_args()
    
    # Dry-run mode: Just show the plan
    if args.dry_run:
        tiers = args.tiers if args.tiers else get_tier_names()
        
        print(f"\n{'='*70}")
        print(f"INGESTION DRY-RUN - v{VERSION}")
        print(f"{'='*70}")
        print(f"Target collection: {args.collection}")
        print(f"Tiers selected: {', '.join(tiers)}")
        print(f"{'='*70}\n")
        
        total_sources = 0
        total_max_pages = 0
        
        for tier in tiers:
            sources = DOCUMENTATION_SOURCES.get(tier, [])
            print(f"\n[TIER] {tier}")
            print(f"{'='*70}")
            
            for i, source in enumerate(sources, 1):
                total_sources += 1
                max_pages = source.get('max_pages', 100)
                total_max_pages += max_pages
                
                print(f"\n{i}. {source['name']}")
                print(f"   URL: {source['url']}")
                print(f"   Type: {source['type']}")
                print(f"   Priority: {source['priority']}")
                print(f"   Max pages: {max_pages}")
                print(f"   Description: {source['description']}")
        
        print(f"\n{'='*70}")
        print("INGESTION PLAN SUMMARY")
        print(f"{'='*70}")
        print(f"Total sources to crawl: {total_sources}")
        print(f"Maximum pages to fetch: {total_max_pages}")
        print(f"Estimated chunks: ~{total_max_pages * 2}-{total_max_pages * 5}")
        print(f"Rate limit: 1.0 seconds between requests")
        print(f"Estimated duration: ~{(total_max_pages * 1.5) // 60}-{(total_max_pages * 2) // 60} minutes")
        print(f"\nTo proceed with ingestion, run without --dry-run flag")
        print(f"{'='*70}\n")
        
        return 0
    
    # Actual ingestion
    ingester = UnifiedDocumentationIngester(args.collection)
    ingester.ingest_all_tiers(args.tiers)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
