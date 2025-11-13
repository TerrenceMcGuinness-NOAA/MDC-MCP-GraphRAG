#!/usr/bin/env python3
"""
Enhanced Documentation Ingestion Script - v4.0.0 Upgraded Embeddings
Ingests documentation with all-mpnet-base-v2 (768-dim) embeddings
Fixed: Added User-Agent headers + lxml parser for proper XML/HTML handling
"""

import os
import sys
import time
import json
import hashlib
import requests
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import SINGLE SOURCE OF TRUTH for documentation sources
from documentation_sources_config import (
    DOCUMENTATION_SOURCES,
    VERSION as CONFIG_VERSION,
    get_tier_names,
    get_total_source_count
)

# Configuration
CHUNK_SIZE = 1000  # characters
CHUNK_OVERLAP = 200  # character overlap
MIN_CHUNK_SIZE = 300  # minimum viable chunk
COLLECTION_NAME = "global-workflow-docs-v4-0-0-mpnet"  # UPGRADED COLLECTION
REQUEST_DELAY = 2.0  # seconds between requests (polite crawling)
EMBEDDING_MODEL = "all-mpnet-base-v2"  # 768 dimensions
VERSION = "4.0.0-mpnet"

# ChromaDB configuration
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))


class DocumentationIngester:
    """Enhanced documentation ingester with improved chunking and metadata"""
    
    def __init__(self, dry_run: bool = False, verbose: bool = True):
        self.dry_run = dry_run
        self.verbose = verbose
        self.stats = {
            'pages_processed': 0,
            'chunks_created': 0,
            'errors': 0,
            'skipped': 0
        }
        
        if not dry_run:
            self.client = chromadb.HttpClient(
                host=CHROMADB_HOST,
                port=CHROMADB_PORT,
                settings=Settings(anonymized_telemetry=False)
            )
            self.collection = self._get_or_create_collection()
        
    def _get_embedding_function(self):
        """Get upgraded embedding function with all-mpnet-base-v2"""
        # Use persistent disk cache (CACHE_ROOT from mcp-env.sh)
        import os
        cache_root = os.getenv('CACHE_ROOT', '/mcp_rag_eib/cache')
        hf_cache = os.path.join(cache_root, 'huggingface')
        os.makedirs(hf_cache, exist_ok=True)
        os.environ['HF_HOME'] = hf_cache
        os.environ['TRANSFORMERS_CACHE'] = os.path.join(cache_root, 'transformers')
        
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL,
            device='cpu',
            cache_folder=hf_cache
        )
    
    def _get_or_create_collection(self):
        """Get or create ChromaDB collection with upgraded embeddings"""
        try:
            collection = self.client.get_collection(COLLECTION_NAME)
            self.log(f"Using existing collection: {COLLECTION_NAME}")
        except Exception:
            # Create collection with explicit embedding function
            embedding_func = self._get_embedding_function()
            collection = self.client.create_collection(
                name=COLLECTION_NAME,
                embedding_function=embedding_func,
                metadata={
                    "description": f"Global Workflow Documentation {VERSION}",
                    "created": datetime.now().isoformat(),
                    "embedding_model": EMBEDDING_MODEL,
                    "embedding_dimensions": "768",
                    "chunking": f"size={CHUNK_SIZE},overlap={CHUNK_OVERLAP}",
                    "version": VERSION
                }
            )
            self.log(f"Created new collection: {COLLECTION_NAME}")
            self.log(f"  Embedding model: {EMBEDDING_MODEL} (768 dimensions)")
        return collection
    
    def log(self, message: str):
        """Log message if verbose"""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {message}")
    
    def fetch_sitemap(self, sitemap_url: str) -> List[str]:
        """Fetch URLs from ReadTheDocs sitemap.xml"""
        # Add proper User-Agent header to avoid 403/404 errors
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        try:
            self.log(f"Fetching sitemap: {sitemap_url}")
            response = requests.get(sitemap_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'xml')
            urls = [loc.text for loc in soup.find_all('loc')]
            self.log(f"Found {len(urls)} URLs in sitemap")
            return urls
        except Exception as e:
            self.log(f"Error fetching sitemap: {e}")
            return []
    
    def crawl_readthedocs_site(self, base_url: str) -> List[str]:
        """Crawl ReadTheDocs site by following navigation links"""
        # Add proper User-Agent header to avoid 403 errors
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        try:
            self.log(f"Crawling site: {base_url}")
            response = requests.get(base_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            urls = set([base_url])
            
            # Find all navigation links in common ReadTheDocs locations
            for nav_class in ['.toctree-l1', '.toctree-l2', 'nav ul li a', '.sidebar a']:
                for link in soup.select(nav_class):
                    href = link.get('href')
                    if href and not href.startswith('#') and not href.startswith('http'):
                        full_url = urljoin(base_url, href)
                        if full_url.startswith(base_url):
                            urls.add(full_url)
            
            self.log(f"Found {len(urls)} URLs via crawling")
            return list(urls)
        except Exception as e:
            self.log(f"Error crawling site: {e}")
            return [base_url]  # Return at least the base URL
    
    def fetch_page(self, url: str) -> Optional[Tuple[str, str]]:
        """Fetch page content and title"""
        # Add proper User-Agent header to avoid 403 errors
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        try:
            self.log(f"Fetching: {url}")
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Get title
            title = soup.find('title')
            title_text = title.text if title else url.split('/')[-1]
            
            # Extract main content (try common patterns)
            main_content = None
            for selector in ['main', 'article', '.document', '.body', '#content']:
                main_content = soup.select_one(selector)
                if main_content:
                    break
            
            if not main_content:
                main_content = soup.find('body')
            
            if main_content:
                # Remove script and style tags
                for tag in main_content(['script', 'style', 'nav', 'footer']):
                    tag.decompose()
                
                text = main_content.get_text(separator=' ', strip=True)
                # Clean up whitespace
                text = ' '.join(text.split())
                return title_text, text
            
            return None, None
            
        except Exception as e:
            self.log(f"Error fetching {url}: {e}")
            self.stats['errors'] += 1
            return None, None
    
    def extract_section(self, url: str, title: str) -> str:
        """Extract section from URL path"""
        path = urlparse(url).path
        parts = [p for p in path.split('/') if p and p not in ['en', 'latest', 'html']]
        
        if parts:
            section = parts[0].replace('-', ' ').replace('_', ' ').title()
            return section
        
        # Try to extract from title
        if ' — ' in title:
            section = title.split(' — ')[0]
            return section
        
        return 'General'
    
    def extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text (simple implementation)"""
        # Common workflow terms
        workflow_terms = {
            'forecast', 'analysis', 'data assimilation', 'gfs', 'gefs', 'gdas',
            'ufs', 'rocoto', 'workflow', 'hpc', 'module', 'spack-stack',
            'ee2', 'compliance', 'wcoss2', 'hera', 'orion', 'job', 'script',
            'configuration', 'installation', 'build', 'setup'
        }
        
        text_lower = text.lower()
        found_keywords = [term for term in workflow_terms if term in text_lower]
        return found_keywords[:10]  # limit to 10
    
    def calculate_quality_score(self, text: str, metadata: Dict) -> float:
        """Calculate quality score for chunk (0.0-1.0)"""
        score = 0.5  # baseline
        
        # Length factor (prefer substantial chunks)
        if len(text) >= CHUNK_SIZE:
            score += 0.2
        elif len(text) >= MIN_CHUNK_SIZE:
            score += 0.1
        
        # Keyword presence
        if metadata.get('keywords'):
            score += min(len(metadata['keywords']) * 0.02, 0.2)
        
        # Section hierarchy
        if metadata.get('doc_hierarchy'):
            score += 0.1
        
        # Cap at 1.0
        return min(score, 1.0)
    
    def create_chunks(self, text: str, url: str, title: str, source_metadata: Dict) -> List[Dict]:
        """Create overlapping chunks with enhanced metadata"""
        chunks = []
        section = self.extract_section(url, title)
        
        # Simple chunking with overlap
        start = 0
        chunk_num = 0
        
        while start < len(text):
            end = start + CHUNK_SIZE
            chunk_text = text[start:end]
            
            # Skip too-short chunks at the end
            if len(chunk_text) < MIN_CHUNK_SIZE and start > 0:
                break
            
            # Extract keywords from chunk
            keywords = self.extract_keywords(chunk_text)
            
            # Build metadata
            metadata = {
                'source_url': url,
                'source_type': source_metadata['type'],
                'source_name': source_metadata['name'],
                'source_description': source_metadata['description'],
                'doc_title': title,
                'doc_section': section,
                'doc_hierarchy': f"{section} > {title}",
                'chunk_index': chunk_num,
                'chunk_total': 0,  # will update after loop
                'priority': source_metadata['priority'],
                'last_updated': datetime.now().isoformat(),
                'keywords': ','.join(keywords),
                'text_length': len(chunk_text)
            }
            
            # Calculate quality score
            metadata['quality_score'] = self.calculate_quality_score(chunk_text, metadata)
            
            chunk_id = hashlib.md5(f"{url}:{chunk_num}".encode()).hexdigest()
            
            chunks.append({
                'id': chunk_id,
                'text': chunk_text,
                'metadata': metadata
            })
            
            chunk_num += 1
            start += (CHUNK_SIZE - CHUNK_OVERLAP)
        
        # Update chunk_total for all chunks
        for chunk in chunks:
            chunk['metadata']['chunk_total'] = len(chunks)
        
        return chunks
    
    def ingest_source(self, source: Dict) -> Dict:
        """Ingest documentation from a single source"""
        self.log(f"\n{'='*60}")
        self.log(f"Processing: {source['name']}")
        self.log(f"URL: {source['url']}")
        self.log(f"Type: {source['type']}")
        self.log(f"Priority: {source['priority']}")
        self.log(f"{'='*60}\n")
        
        source_stats = {
            'name': source['name'],
            'pages': 0,
            'chunks': 0,
            'avg_quality': 0.0,
            'errors': 0
        }
        
        # Get URLs to process
        urls = []
        if source['sitemap']:
            # Try sitemap first
            urls = self.fetch_sitemap(source['sitemap'])
            # If sitemap fails, fall back to crawling
            if not urls and source['type'] == 'readthedocs':
                self.log(f"Sitemap failed, falling back to crawler")
                urls = self.crawl_readthedocs_site(source['url'])
        elif source['type'] == 'single_page':
            urls = [source['url']]
        elif source['type'] == 'readthedocs':
            # No sitemap specified, try crawling
            urls = self.crawl_readthedocs_site(source['url'])
        else:
            # GitHub Pages - would need custom crawler
            self.log(f"Manual crawl needed for {source['name']}, trying base URL only")
            urls = [source['url']]
        
        if not urls:
            self.log(f"No URLs found for {source['name']}")
            return source_stats
        
        quality_scores = []
        
        # Process each URL
        for i, url in enumerate(urls, 1):
            self.log(f"Page {i}/{len(urls)}: {url}")
            
            title, text = self.fetch_page(url)
            if not text:
                source_stats['errors'] += 1
                continue
            
            # Create chunks
            chunks = self.create_chunks(text, url, title, source)
            
            if not chunks:
                self.log(f"  No chunks created, skipping")
                continue
            
            self.log(f"  Created {len(chunks)} chunks, avg quality: {sum(c['metadata']['quality_score'] for c in chunks)/len(chunks):.2f}")
            
            # Add to ChromaDB
            if not self.dry_run:
                try:
                    self.collection.add(
                        ids=[c['id'] for c in chunks],
                        documents=[c['text'] for c in chunks],
                        metadatas=[c['metadata'] for c in chunks]
                    )
                except Exception as e:
                    self.log(f"  Error adding to ChromaDB: {e}")
                    source_stats['errors'] += 1
                    continue
            
            source_stats['pages'] += 1
            source_stats['chunks'] += len(chunks)
            quality_scores.extend([c['metadata']['quality_score'] for c in chunks])
            
            # Polite crawling delay
            time.sleep(REQUEST_DELAY)
        
        # Calculate average quality
        if quality_scores:
            source_stats['avg_quality'] = sum(quality_scores) / len(quality_scores)
        
        self.log(f"\n{source['name']} complete:")
        self.log(f"  Pages: {source_stats['pages']}")
        self.log(f"  Chunks: {source_stats['chunks']}")
        self.log(f"  Avg Quality: {source_stats['avg_quality']:.2%}")
        self.log(f"  Errors: {source_stats['errors']}")
        
        return source_stats
    
    def ingest_all(self, tiers: Optional[List[str]] = None):
        """Ingest all documentation sources"""
        if tiers is None:
            tiers = list(DOCUMENTATION_SOURCES.keys())
        
        all_stats = []
        
        for tier in tiers:
            if tier not in DOCUMENTATION_SOURCES:
                self.log(f"Unknown tier: {tier}, skipping")
                continue
            
            self.log(f"\n{'#'*70}")
            self.log(f"# Starting {tier.upper()}")
            self.log(f"{'#'*70}\n")
            
            sources = DOCUMENTATION_SOURCES[tier]
            for source in sources:
                stats = self.ingest_source(source)
                all_stats.append(stats)
        
        # Print summary
        self.print_summary(all_stats)
    
    def print_summary(self, all_stats: List[Dict]):
        """Print ingestion summary"""
        print("\n" + "="*70)
        print("INGESTION SUMMARY")
        print("="*70)
        
        total_pages = sum(s['pages'] for s in all_stats)
        total_chunks = sum(s['chunks'] for s in all_stats)
        total_errors = sum(s['errors'] for s in all_stats)
        
        print(f"\nTotal Sources: {len(all_stats)}")
        print(f"Total Pages: {total_pages}")
        print(f"Total Chunks: {total_chunks}")
        print(f"Total Errors: {total_errors}")
        
        print("\nPer-Source Statistics:")
        print("-" * 70)
        print(f"{'Source':<25} {'Pages':<8} {'Chunks':<8} {'Avg Quality':<12} {'Errors':<8}")
        print("-" * 70)
        
        for stats in all_stats:
            print(f"{stats['name']:<25} {stats['pages']:<8} {stats['chunks']:<8} "
                  f"{stats['avg_quality']:<12.2%} {stats['errors']:<8}")
        
        print("="*70)
        
        if not self.dry_run:
            print(f"\nData ingested to collection: {COLLECTION_NAME}")
            print(f"ChromaDB: http://{CHROMADB_HOST}:{CHROMADB_PORT}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Ingest documentation with enhanced chunking')
    parser.add_argument('--dry-run', action='store_true', help='Dry run without writing to ChromaDB')
    parser.add_argument('--tier', choices=['tier1_critical', 'tier2_infrastructure', 'tier3_build_system', 'tier4_reference'],
                       help='Ingest only specific tier')
    parser.add_argument('--quiet', action='store_true', help='Suppress verbose output')
    
    args = parser.parse_args()
    
    print("\n" + "="*70)
    print("Enhanced Documentation Ingestion - Week 3")
    print("="*70)
    print(f"ChromaDB: http://{CHROMADB_HOST}:{CHROMADB_PORT}")
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Chunk Size: {CHUNK_SIZE} chars (overlap: {CHUNK_OVERLAP})")
    print(f"Dry Run: {args.dry_run}")
    print("="*70 + "\n")
    
    if args.dry_run:
        print("⚠️  DRY RUN MODE - No data will be written to ChromaDB\n")
    
    ingester = DocumentationIngester(dry_run=args.dry_run, verbose=not args.quiet)
    
    if args.tier:
        ingester.ingest_all(tiers=[args.tier])
    else:
        # Default: ingest tier1 and tier2 (critical + infrastructure)
        ingester.ingest_all(tiers=['tier1_critical', 'tier2_infrastructure', 'tier3_build_system'])


if __name__ == '__main__':
    main()
