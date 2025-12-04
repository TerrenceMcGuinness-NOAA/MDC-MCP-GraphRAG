#!/usr/bin/env python3
"""
Documentation Ingestion Script v7.0.0
Unified documentation ingestion with v7 collection naming

This script consolidates all documentation ingestion into a single v7 collection
with consistent naming convention aligned with MCP server references.

Collection: global-workflow-docs-v7-0-0
Target: 2000+ documents from all tier documentation sources

Author: NOAA EMC Global Workflow MCP Team
Version: 7.0.0
Date: December 3, 2025
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
# V7 CONFIGURATION
# ============================================================================

VERSION = "7.0.0"
COLLECTION_NAME = os.getenv("DOCS_COLLECTION", "global-workflow-docs-v7-0-0")
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))

# Documentation sources organized by tier
DOCUMENTATION_SOURCES = {
    'tier1_critical': [
        {
            'name': 'global-workflow',
            'url': 'https://global-workflow.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 1,
            'description': 'Main global-workflow documentation',
            'max_pages': 100
        },
        {
            'name': 'ee2-standards',
            'url': 'https://nws-hpc-standards.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 1,
            'description': 'NOAA EE2 HPC standards and compliance',
            'max_pages': 100
        },
        {
            'name': 'ufs-utils',
            'url': 'https://noaa-emcufs-utils.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 1,
            'description': 'UFS utilities and pre-processing tools',
            'max_pages': 100
        }
    ],
    'tier2_important': [
        {
            'name': 'wxflow',
            'url': 'https://wxflow.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'Workflow execution library',
            'max_pages': 50
        },
        {
            'name': 'spack-stack',
            'url': 'https://spack-stack.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'Spack-stack for HPC environments',
            'max_pages': 50
        },
        {
            'name': 'ufs-weather-model',
            'url': 'https://ufs-weather-model.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 2,
            'description': 'UFS Weather Model documentation',
            'max_pages': 50
        }
    ],
    'tier3_supplementary': [
        {
            'name': 'rocoto',
            'url': 'https://christopherwharrop.github.io/rocoto/',
            'type': 'github_pages',
            'priority': 3,
            'description': 'Rocoto workflow manager',
            'max_pages': 30
        },
        {
            'name': 'spack',
            'url': 'https://spack.readthedocs.io/en/latest/',
            'type': 'readthedocs',
            'priority': 3,
            'description': 'Spack package manager',
            'max_pages': 50
        }
    ]
}


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
        
        print(f"\n  [SOURCE] {name}: {url}")
        
        try:
            # Crawl pages
            pages = self.crawler.crawl(url, max_pages=max_pages)
            self.stats['sources_processed'] += 1
            
            for page_url, content in pages:
                self.stats['documents_processed'] += 1
                
                # Create semantic chunks
                chunks = self.chunker.chunk(content, {
                    'source': name,
                    'url': page_url,
                    'priority': source['priority'],
                    'description': source['description'],
                    'ingested_at': datetime.now().isoformat(),
                    'version': VERSION
                })
                
                self.stats['chunks_created'] += len(chunks)
                
                # Add chunks to collection
                for chunk in chunks:
                    doc_id = self._generate_id(chunk['text'], page_url)
                    
                    if doc_id in self.seen_ids:
                        self.stats['duplicates_skipped'] += 1
                        continue
                    
                    self.seen_ids.add(doc_id)
                    self.add_document(doc_id, chunk['text'], chunk['metadata'])
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
    
    parser = argparse.ArgumentParser(description='V7 Documentation Ingestion')
    parser.add_argument('--collection', default=COLLECTION_NAME,
                       help=f'Collection name (default: {COLLECTION_NAME})')
    parser.add_argument('--tiers', nargs='+', 
                       choices=['tier1_critical', 'tier2_important', 'tier3_supplementary'],
                       help='Tiers to ingest (default: all)')
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
