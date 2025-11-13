#!/usr/bin/env python3
"""
Enhanced Documentation Ingestion Script - v4.1.0
Week 3 Task 2: Better chunking, metadata enrichment, quality improvements

Improvements over v4.0:
1. Semantic chunking (by headers, not arbitrary size)
2. Rich metadata (section hierarchy, document type, source tier)
3. Quality filtering (remove navigation, boilerplate)
4. Deduplication (content-based hashing)
5. Local markdown support (docs/ directory)
"""

import os
import sys
import re
import time
import json
import hashlib
import requests
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup, NavigableString
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

# Cache configuration
CACHE_ROOT = os.getenv('CACHE_ROOT', '/mcp_rag_eib/cache')
os.environ['HF_HOME'] = f'{CACHE_ROOT}/huggingface'
os.environ['TRANSFORMERS_CACHE'] = f'{CACHE_ROOT}/transformers'

# Configuration
COLLECTION_NAME = "global-workflow-docs-v4-1-0-enhanced"
EMBEDDING_MODEL = "all-mpnet-base-v2"  # 768 dimensions
VERSION = "4.1.0-enhanced"
MIN_CHUNK_SIZE = 200  # Minimum characters for a chunk
MAX_CHUNK_SIZE = 2000  # Maximum characters per chunk
HEADER_PRIORITY = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']

# ChromaDB configuration
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))

# Content quality filters
SKIP_PATTERNS = [
    r'^Navigation\s*$',
    r'^Table of Contents\s*$',
    r'^Search\s*$',
    r'^©\s*Copyright',
    r'^Next\s*$',
    r'^Previous\s*$',
    r'^Edit on GitHub\s*$',
    r'^\s*$',  # Empty lines
]

class SemanticChunker:
    """Chunks documents semantically by section headers"""
    
    def __init__(self, min_size=MIN_CHUNK_SIZE, max_size=MAX_CHUNK_SIZE):
        self.min_size = min_size
        self.max_size = max_size
        
    def chunk_by_headers(self, soup: BeautifulSoup, url: str) -> List[Dict]:
        """Chunk HTML content by semantic sections"""
        chunks = []
        current_chunk = {
            'content': '',
            'hierarchy': [],
            'url': url,
            'headers': []
        }
        
        # Track header hierarchy
        header_stack = []
        
        for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'pre', 'ul', 'ol', 'table']):
            tag_name = element.name
            
            # Handle headers - start new chunk if needed
            if tag_name in HEADER_PRIORITY:
                # Save previous chunk if it's substantial
                if len(current_chunk['content']) >= self.min_size:
                    chunks.append(self._finalize_chunk(current_chunk))
                    current_chunk = {
                        'content': '',
                        'hierarchy': header_stack.copy(),
                        'url': url,
                        'headers': []
                    }
                
                # Update header hierarchy
                level = int(tag_name[1])
                header_text = element.get_text(strip=True)
                
                # Pop headers at same or lower level
                while header_stack and header_stack[-1]['level'] >= level:
                    header_stack.pop()
                
                # Add new header
                header_stack.append({'level': level, 'text': header_text})
                current_chunk['headers'].append(header_text)
                current_chunk['content'] += f"\n\n## {header_text}\n\n"
            
            # Handle content elements
            elif tag_name in ['p', 'pre']:
                text = element.get_text(strip=True)
                if self._is_quality_content(text):
                    current_chunk['content'] += text + '\n\n'
                    
                    # Split if chunk gets too large
                    if len(current_chunk['content']) >= self.max_size:
                        chunks.append(self._finalize_chunk(current_chunk))
                        current_chunk = {
                            'content': '',
                            'hierarchy': header_stack.copy(),
                            'url': url,
                            'headers': current_chunk['headers'].copy()
                        }
            
            # Handle lists
            elif tag_name in ['ul', 'ol']:
                list_text = '\n'.join(['- ' + li.get_text(strip=True) for li in element.find_all('li')])
                if list_text:
                    current_chunk['content'] += list_text + '\n\n'
            
            # Handle tables
            elif tag_name == 'table':
                table_text = self._extract_table_text(element)
                if table_text:
                    current_chunk['content'] += table_text + '\n\n'
        
        # Add final chunk
        if len(current_chunk['content']) >= self.min_size:
            chunks.append(self._finalize_chunk(current_chunk))
        
        return chunks
    
    def _is_quality_content(self, text: str) -> bool:
        """Filter out navigation, boilerplate, and low-quality content"""
        if not text or len(text) < 20:
            return False
        
        for pattern in SKIP_PATTERNS:
            if re.match(pattern, text, re.IGNORECASE):
                return False
        
        # Check for substantial alphanumeric content
        alphanum_ratio = sum(c.isalnum() for c in text) / len(text)
        return alphanum_ratio > 0.5
    
    def _extract_table_text(self, table) -> str:
        """Extract readable text from HTML table"""
        rows = []
        for tr in table.find_all('tr'):
            cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
            if cells:
                rows.append(' | '.join(cells))
        return '\n'.join(rows) if rows else ''
    
    def _finalize_chunk(self, chunk: Dict) -> Dict:
        """Clean and finalize chunk"""
        # Clean up content
        content = chunk['content'].strip()
        content = re.sub(r'\n{3,}', '\n\n', content)  # Max 2 newlines
        
        # Create hierarchy string
        hierarchy_str = ' > '.join([h['text'] for h in chunk['hierarchy']])
        
        return {
            'content': content,
            'hierarchy': hierarchy_str,
            'url': chunk['url'],
            'headers': chunk['headers'],
            'hash': hashlib.md5(content.encode()).hexdigest()
        }


class EnhancedDocumentationIngester:
    """Enhanced documentation ingestion with quality improvements"""
    
    def __init__(self):
        self.chunker = SemanticChunker()
        self.seen_hashes = set()
        self.visited_urls = set()
        self.stats = {
            'pages_crawled': 0,
            'chunks_created': 0,
            'duplicates_skipped': 0,
            'low_quality_skipped': 0
        }
        
        # Initialize ChromaDB
        print(f"[INIT] Connecting to ChromaDB at {CHROMADB_HOST}:{CHROMADB_PORT}")
        self.client = chromadb.HttpClient(
            host=CHROMADB_HOST,
            port=CHROMADB_PORT,
            settings=Settings(allow_reset=True, anonymized_telemetry=False)
        )
        
        # Initialize embedding function
        print(f"[INIT] Loading embedding model: {EMBEDDING_MODEL}")
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL,
            cache_folder=os.environ['HF_HOME']
        )
        
        # Create or get collection
        self.collection = self._setup_collection()
    
    def _setup_collection(self):
        """Create enhanced collection with metadata"""
        try:
            print(f"[INIT] Getting existing collection: {COLLECTION_NAME}")
            collection = self.client.get_collection(
                name=COLLECTION_NAME,
                embedding_function=self.embedding_function
            )
            print(f"[OK] Found existing collection with {collection.count()} documents")
        except:
            print(f"[INIT] Creating new collection: {COLLECTION_NAME}")
            collection = self.client.create_collection(
                name=COLLECTION_NAME,
                embedding_function=self.embedding_function,
                metadata={
                    "description": "Enhanced Global Workflow Documentation v4.1.0",
                    "version": VERSION,
                    "embedding_model": EMBEDDING_MODEL,
                    "embedding_dimensions": "768",
                    "chunking_strategy": "semantic_headers",
                    "created": datetime.now().isoformat(),
                    "min_chunk_size": str(MIN_CHUNK_SIZE),
                    "max_chunk_size": str(MAX_CHUNK_SIZE),
                    "quality_filtered": "true",
                    "deduplicated": "true"
                }
            )
            print(f"[OK] Created new collection")
        
        return collection
    
    def _is_same_domain(self, base_url: str, target_url: str) -> bool:
        """Check if target URL is on same domain as base"""
        base_domain = urlparse(base_url).netloc
        target_domain = urlparse(target_url).netloc
        return base_domain == target_domain
    
    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> Set[str]:
        """Extract all same-domain links from page"""
        links = set()
        for link in soup.find_all('a', href=True):
            href = link['href']
            # Resolve relative URLs
            full_url = urljoin(base_url, href)
            # Remove fragments
            full_url = full_url.split('#')[0]
            # Only include same-domain links
            if self._is_same_domain(base_url, full_url):
                links.add(full_url)
        return links
    
    def ingest_url(self, url: str, source_name: str, tier: str, recursive: bool = True, max_pages: int = 200):
        """Ingest documentation from URL with semantic chunking and optional recursive crawling"""
        if not recursive:
            # Single page mode
            self._ingest_single_page(url, source_name, tier)
            return
        
        # Recursive crawling mode
        to_visit = {url}
        base_domain = urlparse(url).netloc
        
        print(f"\n[CRAWL] {source_name}: Starting recursive crawl from {url}")
        print(f"[CRAWL] Max pages: {max_pages}")
        
        while to_visit and len(self.visited_urls) < max_pages:
            current_url = to_visit.pop()
            
            if current_url in self.visited_urls:
                continue
            
            # Ingest this page
            try:
                links = self._ingest_single_page(current_url, source_name, tier)
                self.visited_urls.add(current_url)
                
                # Add new links to visit queue
                for link in links:
                    if link not in self.visited_urls:
                        to_visit.add(link)
                
                # Progress update every 10 pages
                if len(self.visited_urls) % 10 == 0:
                    print(f"  [PROGRESS] Crawled {len(self.visited_urls)} pages, {len(to_visit)} in queue")
                
                time.sleep(0.5)  # Be polite
                
            except Exception as e:
                print(f"  [ERROR] Failed to crawl {current_url}: {e}")
                self.visited_urls.add(current_url)  # Don't retry
        
        print(f"  [OK] Crawled {len(self.visited_urls)} pages total")
    
    def _ingest_single_page(self, url: str, source_name: str, tier: str) -> Set[str]:
        """Ingest a single page and return links found"""
        try:
            headers = {
                'User-Agent': 'NOAA-EMC-MCP-Documentation-Crawler/4.1.0 (+https://github.com/NOAA-EMC/global-workflow)'
            }
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'lxml')
            self.stats['pages_crawled'] += 1
            
            # Extract links for recursive crawling
            links = self._extract_links(soup, url)
            
            # Semantic chunking
            chunks = self.chunker.chunk_by_headers(soup, url)
            
            # Process chunks with quality filtering
            documents = []
            metadatas = []
            ids = []
            
            for i, chunk in enumerate(chunks):
                # Skip duplicates
                if chunk['hash'] in self.seen_hashes:
                    self.stats['duplicates_skipped'] += 1
                    continue
                
                self.seen_hashes.add(chunk['hash'])
                
                # Create rich metadata
                metadata = {
                    'source': source_name,
                    'url': chunk['url'],
                    'tier': tier,
                    'hierarchy': chunk['hierarchy'],
                    'section_headers': ', '.join(chunk['headers'][:3]),  # First 3 headers
                    'ingestion_date': datetime.now().isoformat(),
                    'version': VERSION,
                    'chunk_index': i,
                    'content_hash': chunk['hash']
                }
                
                doc_id = f"{source_name}_{chunk['hash']}_{i}"
                
                documents.append(chunk['content'])
                metadatas.append(metadata)
                ids.append(doc_id)
                self.stats['chunks_created'] += 1
            
            # Batch insert
            if documents:
                self.collection.add(
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids
                )
            
            return links
            
        except Exception as e:
            print(f"  [ERROR] {e}")
            return set()  # Return empty set on error
    
    def ingest_local_docs(self, docs_dir: Path):
        """Ingest local markdown files"""
        print(f"\n[LOCAL] Ingesting from {docs_dir}")
        
        for md_file in docs_dir.rglob('*.md'):
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Simple markdown chunking by headers
                sections = re.split(r'\n(#{1,6}\s+.+)\n', content)
                
                current_content = []
                for i, section in enumerate(sections):
                    if re.match(r'^#{1,6}\s+', section):
                        # This is a header
                        if current_content and len(''.join(current_content)) >= MIN_CHUNK_SIZE:
                            self._add_local_chunk(current_content, md_file, i)
                        current_content = [section + '\n']
                    else:
                        current_content.append(section)
                
                # Add final chunk
                if current_content and len(''.join(current_content)) >= MIN_CHUNK_SIZE:
                    self._add_local_chunk(current_content, md_file, len(sections))
                
                print(f"  [OK] {md_file.name}")
                
            except Exception as e:
                print(f"  [ERROR] {md_file}: {e}")
    
    def _add_local_chunk(self, content_parts: List[str], file_path: Path, index: int):
        """Add local markdown chunk"""
        content = ''.join(content_parts).strip()
        content_hash = hashlib.md5(content.encode()).hexdigest()
        
        if content_hash in self.seen_hashes:
            self.stats['duplicates_skipped'] += 1
            return
        
        self.seen_hashes.add(content_hash)
        
        metadata = {
            'source': 'local-docs',
            'file': str(file_path),
            'tier': 'tier1_critical',
            'ingestion_date': datetime.now().isoformat(),
            'version': VERSION,
            'chunk_index': index,
            'content_hash': content_hash
        }
        
        doc_id = f"local_{content_hash}_{index}"
        
        self.collection.add(
            documents=[content],
            metadatas=[metadata],
            ids=[doc_id]
        )
        self.stats['chunks_created'] += 1
    
    def print_stats(self):
        """Print ingestion statistics"""
        print("\n" + "="*60)
        print("INGESTION STATISTICS")
        print("="*60)
        for key, value in self.stats.items():
            print(f"  {key}: {value}")
        print(f"\nFinal collection size: {self.collection.count()} documents")
        print("="*60)


def main():
    """Main ingestion workflow"""
    print("="*60)
    print("Enhanced Documentation Ingestion v4.1.0")
    print("Week 3 Task 2: Quality Improvements + Recursive Crawling")
    print("="*60)
    
    ingester = EnhancedDocumentationIngester()
    
    # Tier 1: Critical documentation (with recursive crawling)
    tier1_sources = [
        ('https://global-workflow.readthedocs.io/en/latest/', 'global-workflow', 'tier1', True, 100),
        ('https://nws-hpc-standards.readthedocs.io/en/latest/', 'ee2-standards', 'tier1', True, 100),
    ]
    
    for url, name, tier, recursive, max_pages in tier1_sources:
        ingester.ingest_url(url, name, tier, recursive=recursive, max_pages=max_pages)
        time.sleep(2)  # Be polite between sites
    
    # Local documentation
    docs_dir = Path('/mcp_rag_eib/global-workflow_MCP_node.js-RAG/docs')
    if docs_dir.exists():
        ingester.ingest_local_docs(docs_dir)
    
    # Print statistics
    ingester.print_stats()
    
    print(f"\n[OK] Enhanced ingestion complete!")
    print(f"[OK] Collection: {COLLECTION_NAME}")
    print(f"[OK] Ready for testing")


if __name__ == "__main__":
    main()
