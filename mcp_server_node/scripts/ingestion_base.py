#!/usr/bin/env python3
"""
Base Ingestion Library for MCP Documentation System
Consolidates v4.0 + v4.1 improvements with reusable components

Features:
- Semantic chunking (by headers, sections)
- MPNet 768-dim embeddings
- Quality filtering and deduplication
- RST and Markdown parsing
- Recursive crawling
- Metadata enrichment

Author: NOAA EMC Global Workflow MCP Team
Version: 4.2.0 (Consolidated)
Date: November 10, 2025
"""

import os
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

# Default configurations
DEFAULT_MIN_CHUNK_SIZE = 200
DEFAULT_MAX_CHUNK_SIZE = 2000
DEFAULT_CHUNK_OVERLAP = 200
DEFAULT_REQUEST_DELAY = 1.0
EMBEDDING_MODEL = "all-mpnet-base-v2"  # 768 dimensions

# Content quality filters
SKIP_PATTERNS = [
    r'^Navigation\s*$',
    r'^Table of Contents\s*$',
    r'^Search\s*$',
    r'^©\s*Copyright',
    r'^Next\s*$',
    r'^Previous\s*$',
    r'^Edit on GitHub\s*$',
    r'^\s*$',
]

HEADER_TAGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']


class SemanticChunker:
    """
    Chunks documents semantically by section headers and content structure.
    Merged improvements from v4.0 and v4.1.
    """
    
    def __init__(self, min_size=DEFAULT_MIN_CHUNK_SIZE, max_size=DEFAULT_MAX_CHUNK_SIZE, 
                 overlap=DEFAULT_CHUNK_OVERLAP):
        self.min_size = min_size
        self.max_size = max_size
        self.overlap = overlap
        
    def chunk_by_headers(self, soup: BeautifulSoup, url: str) -> List[Dict]:
        """
        Chunk HTML content by semantic sections (headers).
        From v4.1 enhanced.
        """
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
            if tag_name in HEADER_TAGS:
                # Save previous chunk if substantial
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
    
    def chunk_rst_document(self, rst_content: str, source_path: str) -> List[Dict]:
        """
        Chunk RST (ReStructuredText) documents by sections.
        Specialized for Sphinx documentation like EE2 standards.
        """
        chunks = []
        
        # Split by RST section markers (lines of ===, ---, ~~~, etc.)
        section_pattern = r'\n(.+)\n([=\-~`:.\'\"^_*+#<>]{3,})\n'
        sections = re.split(section_pattern, rst_content)
        
        current_content = []
        current_header = None
        hierarchy = []
        
        i = 0
        while i < len(sections):
            if i + 2 < len(sections) and re.match(r'[=\-~`:.\'\"^_*+#<>]{3,}', sections[i + 2]):
                # This is a header
                header_text = sections[i + 1].strip()
                underline = sections[i + 2].strip()
                
                # Determine level from underline character
                level = self._get_rst_header_level(underline[0])
                
                # Save previous section if substantial
                if current_content and len(''.join(current_content)) >= self.min_size:
                    chunk = self._finalize_rst_chunk(current_content, hierarchy, source_path)
                    chunks.append(chunk)
                
                # Update hierarchy
                while hierarchy and hierarchy[-1]['level'] >= level:
                    hierarchy.pop()
                hierarchy.append({'level': level, 'text': header_text})
                
                current_content = [f"\n## {header_text}\n\n"]
                i += 3
            else:
                # Regular content
                content = sections[i].strip()
                if content and self._is_quality_content(content):
                    current_content.append(content + '\n\n')
                    
                    # Split if too large
                    if len(''.join(current_content)) >= self.max_size:
                        chunk = self._finalize_rst_chunk(current_content, hierarchy, source_path)
                        chunks.append(chunk)
                        current_content = []
                i += 1
        
        # Add final chunk
        if current_content and len(''.join(current_content)) >= self.min_size:
            chunk = self._finalize_rst_chunk(current_content, hierarchy, source_path)
            chunks.append(chunk)
        
        return chunks
    
    def chunk_markdown(self, md_content: str, source_path: str) -> List[Dict]:
        """
        Chunk Markdown documents by headers.
        """
        chunks = []
        
        # Split by headers
        sections = re.split(r'\n(#{1,6}\s+.+)\n', md_content)
        
        current_content = []
        hierarchy = []
        
        for i, section in enumerate(sections):
            if re.match(r'^#{1,6}\s+', section):
                # This is a header
                level = len(section.split()[0])  # Count #'s
                header_text = section.lstrip('#').strip()
                
                # Save previous section
                if current_content and len(''.join(current_content)) >= self.min_size:
                    chunk = self._finalize_md_chunk(current_content, hierarchy, source_path)
                    chunks.append(chunk)
                
                # Update hierarchy
                while hierarchy and hierarchy[-1]['level'] >= level:
                    hierarchy.pop()
                hierarchy.append({'level': level, 'text': header_text})
                
                current_content = [section + '\n']
            else:
                content = section.strip()
                if content and self._is_quality_content(content):
                    current_content.append(content + '\n\n')
        
        # Add final chunk
        if current_content and len(''.join(current_content)) >= self.min_size:
            chunk = self._finalize_md_chunk(current_content, hierarchy, source_path)
            chunks.append(chunk)
        
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
    
    def _get_rst_header_level(self, char: str) -> int:
        """Determine RST header level from underline character"""
        # Common RST hierarchy (Sphinx default)
        levels = {'=': 1, '-': 2, '~': 3, '`': 4, ':': 5, "'": 6, '"': 7}
        return levels.get(char, 3)
    
    def _finalize_chunk(self, chunk: Dict) -> Dict:
        """Clean and finalize HTML chunk"""
        content = chunk['content'].strip()
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        hierarchy_str = ' > '.join([h['text'] for h in chunk['hierarchy']])
        
        return {
            'content': content,
            'hierarchy': hierarchy_str,
            'url': chunk['url'],
            'headers': chunk['headers'],
            'hash': hashlib.md5(content.encode()).hexdigest()
        }
    
    def _finalize_rst_chunk(self, content_parts: List[str], hierarchy: List[Dict], 
                           source_path: str) -> Dict:
        """Finalize RST chunk"""
        content = ''.join(content_parts).strip()
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        hierarchy_str = ' > '.join([h['text'] for h in hierarchy])
        
        return {
            'content': content,
            'hierarchy': hierarchy_str,
            'source': source_path,
            'headers': [h['text'] for h in hierarchy],
            'hash': hashlib.md5(content.encode()).hexdigest()
        }
    
    def _finalize_md_chunk(self, content_parts: List[str], hierarchy: List[Dict],
                          source_path: str) -> Dict:
        """Finalize Markdown chunk"""
        content = ''.join(content_parts).strip()
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        hierarchy_str = ' > '.join([h['text'] for h in hierarchy])
        
        return {
            'content': content,
            'hierarchy': hierarchy_str,
            'source': source_path,
            'headers': [h['text'] for h in hierarchy],
            'hash': hashlib.md5(content.encode()).hexdigest()
        }


class ChromaDBClient:
    """
    Manages ChromaDB connections and collections.
    Consolidated from v4.0 and v4.1.
    """
    
    def __init__(self, host="localhost", port=8080):
        self.host = host
        self.port = port
        self.client = None
        self.embedding_function = None
        
    def connect(self):
        """Connect to ChromaDB"""
        self.client = chromadb.HttpClient(
            host=self.host,
            port=self.port,
            settings=Settings(allow_reset=False, anonymized_telemetry=False)
        )
        return self.client
    
    def get_embedding_function(self):
        """Get or create embedding function with MPNet 768-dim"""
        if self.embedding_function is None:
            # Use persistent cache
            cache_root = os.getenv('CACHE_ROOT', '/mcp_rag_eib/cache')
            hf_cache = os.path.join(cache_root, 'huggingface')
            os.makedirs(hf_cache, exist_ok=True)
            os.environ['HF_HOME'] = hf_cache
            os.environ['TRANSFORMERS_CACHE'] = os.path.join(cache_root, 'transformers')
            
            self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=EMBEDDING_MODEL,
                device='cpu',
                cache_folder=hf_cache
            )
        
        return self.embedding_function
    
    def get_or_create_collection(self, name: str, metadata: Dict = None) -> chromadb.Collection:
        """Get existing collection or create new one"""
        if self.client is None:
            self.connect()
        
        try:
            collection = self.client.get_collection(
                name=name,
                embedding_function=self.get_embedding_function()
            )
            print(f"[OK] Using existing collection: {name} ({collection.count()} documents)")
        except:
            if metadata is None:
                metadata = {
                    "description": f"MCP Documentation Collection",
                    "created": datetime.now().isoformat(),
                    "embedding_model": EMBEDDING_MODEL,
                    "embedding_dimensions": "768"
                }
            
            collection = self.client.create_collection(
                name=name,
                embedding_function=self.get_embedding_function(),
                metadata=metadata
            )
            print(f"[OK] Created new collection: {name}")
        
        return collection
    
    def add_documents_batch(self, collection, documents: List[str], 
                           metadatas: List[Dict], ids: List[str],
                           batch_size: int = 100):
        """Add documents in batches to avoid memory issues"""
        total = len(documents)
        
        for i in range(0, total, batch_size):
            batch_docs = documents[i:i+batch_size]
            batch_metas = metadatas[i:i+batch_size]
            batch_ids = ids[i:i+batch_size]
            
            collection.add(
                documents=batch_docs,
                metadatas=batch_metas,
                ids=batch_ids
            )
            
            if (i + batch_size) % 500 == 0:
                print(f"  [PROGRESS] Added {min(i+batch_size, total)}/{total} documents")


class URLCrawler:
    """
    Crawls documentation websites with recursive, sitemap, and single-page support.
    Merged from v4.0 and v4.1.
    """
    
    def __init__(self, delay=DEFAULT_REQUEST_DELAY, user_agent=None):
        self.delay = delay
        self.user_agent = user_agent or 'NOAA-EMC-MCP-Crawler/4.2.0'
        self.visited = set()
        
    def fetch_sitemap(self, sitemap_url: str) -> List[str]:
        """Fetch URLs from sitemap.xml"""
        try:
            headers = {'User-Agent': self.user_agent}
            response = requests.get(sitemap_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'xml')
            urls = [loc.text for loc in soup.find_all('loc')]
            return urls
        except Exception as e:
            print(f"[WARN] Sitemap fetch failed: {e}")
            return []
    
    def fetch_page(self, url: str) -> Optional[Tuple[str, BeautifulSoup]]:
        """Fetch single page and return title + parsed content"""
        try:
            headers = {'User-Agent': self.user_agent}
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Get title
            title = soup.find('title')
            title_text = title.text if title else url.split('/')[-1]
            
            return title_text, soup
            
        except Exception as e:
            print(f"[ERROR] Failed to fetch {url}: {e}")
            return None
    
    def crawl_recursive(self, base_url: str, max_pages: int = 100) -> List[Tuple[str, str, BeautifulSoup]]:
        """
        Recursively crawl website from base URL.
        Returns: List of (url, title, soup) tuples
        """
        to_visit = {base_url}
        pages = []
        
        while to_visit and len(self.visited) < max_pages:
            url = to_visit.pop()
            
            if url in self.visited:
                continue
            
            result = self.fetch_page(url)
            if result:
                title, soup = result
                pages.append((url, title, soup))
                self.visited.add(url)
                
                # Extract links
                links = self._extract_same_domain_links(soup, base_url)
                for link in links:
                    if link not in self.visited:
                        to_visit.add(link)
                
                time.sleep(self.delay)
        
        return pages
    
    def _extract_same_domain_links(self, soup: BeautifulSoup, base_url: str) -> Set[str]:
        """Extract same-domain links from page"""
        base_domain = urlparse(base_url).netloc
        base_parsed = urlparse(base_url)
        links = set()
        
        # Patterns to exclude from crawling
        exclude_patterns = [
            '/_sources/',      # RST source files
            '/_static/',       # Static assets
            '/_images/',       # Image files
            '/_modules/',      # Module documentation (often auto-generated)
            '/genindex',       # Generated index pages
            '/search.html',    # Search page
            '/py-modindex',    # Python module index
            '.txt',            # Text files
            '.pdf',            # PDF files
            '.zip',            # Archives
            '.tar.gz',         # Archives
        ]
        
        # Extract version path from base URL for ReadTheDocs normalization
        # e.g., /en/latest/ or /en/v1.0/
        rtd_version_match = None
        if 'readthedocs.io' in base_domain:
            import re
            match = re.search(r'/en/([^/]+)/', base_url)
            if match:
                rtd_version_match = match.group(1)  # e.g., 'latest', 'v1.0'
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(base_url, href)
            full_url = full_url.split('#')[0]  # Remove fragments
            
            # Skip excluded patterns
            if any(pattern in full_url for pattern in exclude_patterns):
                continue
            
            # Normalize ReadTheDocs URLs - fix missing version in path
            # e.g., /en/configuration.html -> /en/latest/configuration.html
            if rtd_version_match and 'readthedocs.io' in full_url:
                parsed = urlparse(full_url)
                path = parsed.path
                # Check if path is missing the version segment
                if path.startswith('/en/') and not path.startswith(f'/en/{rtd_version_match}/'):
                    # Fix: /en/foo.html -> /en/latest/foo.html
                    fixed_path = path.replace('/en/', f'/en/{rtd_version_match}/', 1)
                    full_url = f"{parsed.scheme}://{parsed.netloc}{fixed_path}"
            
            if urlparse(full_url).netloc == base_domain:
                links.add(full_url)
        
        return links


class LocalRepoParser:
    """
    Parses local documentation repositories (RST, Markdown).
    New for EE2 local repo support.
    """
    
    def __init__(self, chunker: SemanticChunker):
        self.chunker = chunker
        
    def parse_rst_repo(self, repo_path: Path) -> List[Dict]:
        """Parse all RST files in repository"""
        chunks = []
        
        for rst_file in repo_path.rglob('*.rst'):
            try:
                with open(rst_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                file_chunks = self.chunker.chunk_rst_document(content, str(rst_file))
                chunks.extend(file_chunks)
                
                print(f"[OK] Parsed {rst_file.name}: {len(file_chunks)} chunks")
                
            except Exception as e:
                print(f"[ERROR] Failed to parse {rst_file}: {e}")
        
        return chunks
    
    def parse_markdown_repo(self, repo_path: Path) -> List[Dict]:
        """Parse all Markdown files in repository"""
        chunks = []
        
        for md_file in repo_path.rglob('*.md'):
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                file_chunks = self.chunker.chunk_markdown(content, str(md_file))
                chunks.extend(file_chunks)
                
                print(f"[OK] Parsed {md_file.name}: {len(file_chunks)} chunks")
                
            except Exception as e:
                print(f"[ERROR] Failed to parse {md_file}: {e}")
        
        return chunks


class MetadataEnricher:
    """
    Enriches chunks with metadata (keywords, quality scores, categories).
    Consolidated from v4.0 and v4.1.
    """
    
    # Common workflow keywords
    WORKFLOW_KEYWORDS = {
        'forecast', 'analysis', 'data assimilation', 'gfs', 'gefs', 'gdas',
        'ufs', 'rocoto', 'workflow', 'hpc', 'module', 'spack-stack',
        'ee2', 'compliance', 'wcoss2', 'hera', 'orion', 'job', 'script',
        'configuration', 'installation', 'build', 'setup', 'environment',
        'error handling', 'production', 'utility'
    }
    
    # EE2 compliance categories
    EE2_CATEGORIES = {
        'environment_variables': ['DATAROOT', 'DATA', 'HOMEmodel', 'USHmodel', 'EXECmodel', 
                                  'PARMmodel', 'FIXmodel', 'envir', 'job', 'jobid', 'NET', 
                                  'RUN', 'PDY', 'cyc', 'COMIN', 'COMOUT'],
        'workflow_structure': ['JAAAAA', 'exaaaaa', 'ecFlow', 'J-job', 'ex-script', 'ush'],
        'error_handling': ['err_chk', 'err_exit', 'prep_step', 'startmsg', 'postmsg', 
                          'FATAL', 'ERROR', 'WARNING', 'set -e', 'set -u'],
        'file_naming': ['GRIB2', 'forecast hours', 'f001', 'f006'],
        'production_utilities': ['prep_step', 'startmsg', 'postmsg', 'cpreq', 'module load'],
        'code_standards': ['shebang', 'licensing', 'GNU LGPL', 'documentation', 'comments'],
        'directory_structure': ['jobs/', 'scripts/', 'ush/', 'parm/', 'fix/', 'exec/', 'sorc/']
    }
    
    def extract_keywords(self, text: str) -> List[str]:
        """Extract relevant keywords from text"""
        text_lower = text.lower()
        found = [kw for kw in self.WORKFLOW_KEYWORDS if kw in text_lower]
        return found[:10]  # Limit to 10
    
    def calculate_quality_score(self, text: str, metadata: Dict = None) -> float:
        """Calculate quality score (0.0-1.0)"""
        score = 0.5  # Baseline
        
        # Length factor
        if len(text) >= 1000:
            score += 0.2
        elif len(text) >= 500:
            score += 0.1
        
        # Keyword presence
        keywords = self.extract_keywords(text)
        if keywords:
            score += min(len(keywords) * 0.02, 0.2)
        
        # Has code examples
        if '```' in text or 'export ' in text or 'def ' in text:
            score += 0.1
        
        return min(score, 1.0)
    
    def identify_compliance_categories(self, text: str) -> List[Dict]:
        """Identify EE2 compliance categories in text"""
        categories = []
        text_lower = text.lower()
        
        for category_name, keywords in self.EE2_CATEGORIES.items():
            matches = sum(1 for kw in keywords if kw.lower() in text_lower)
            if matches > 0:
                categories.append({
                    'name': category_name,
                    'matches': matches,
                    'confidence': min(matches / 5.0, 1.0)
                })
        
        return categories
    
    def enrich_chunk(self, chunk: Dict, source_metadata: Dict) -> Dict:
        """Add comprehensive metadata to chunk"""
        content = chunk['content']
        
        # Extract information
        keywords = self.extract_keywords(content)
        quality_score = self.calculate_quality_score(content)
        compliance_cats = self.identify_compliance_categories(content)
        
        # Build metadata
        metadata = {
            'content_hash': chunk['hash'],
            'hierarchy': chunk.get('hierarchy', ''),
            'section_headers': ', '.join(chunk.get('headers', [])[:3]),
            'keywords': ','.join(keywords),
            'quality_score': quality_score,
            'text_length': len(content),
            'ingestion_date': datetime.now().isoformat(),
            **source_metadata
        }
        
        # Add compliance categories if found
        if compliance_cats:
            metadata['compliance_categories'] = json.dumps(compliance_cats)
        
        return metadata


class BaseIngester:
    """
    Base class for all specialized ingesters.
    Provides common functionality and workflow.
    """
    
    def __init__(self, collection_name: str, version: str):
        self.collection_name = collection_name
        self.version = version
        
        # Initialize components
        self.chunker = SemanticChunker()
        self.db_client = ChromaDBClient(
            host=os.getenv("CHROMADB_HOST", "localhost"),
            port=int(os.getenv("CHROMADB_PORT", "8080"))
        )
        self.crawler = URLCrawler()
        self.repo_parser = LocalRepoParser(self.chunker)
        self.enricher = MetadataEnricher()
        
        # State
        self.collection = None
        self.seen_hashes = set()
        self.stats = {
            'pages_processed': 0,
            'chunks_created': 0,
            'duplicates_skipped': 0
        }
    
    def initialize(self, metadata: Dict = None):
        """Initialize database connection and collection"""
        self.db_client.connect()
        
        if metadata is None:
            metadata = {
                "description": f"MCP Documentation Collection",
                "version": self.version,
                "created": datetime.now().isoformat(),
                "embedding_model": EMBEDDING_MODEL,
                "embedding_dimensions": "768"
            }
        
        self.collection = self.db_client.get_or_create_collection(
            self.collection_name,
            metadata
        )
    
    def process_chunks(self, chunks: List[Dict], source_metadata: Dict):
        """Process and add chunks to collection"""
        documents = []
        metadatas = []
        ids = []
        
        for i, chunk in enumerate(chunks):
            # Skip duplicates
            if chunk['hash'] in self.seen_hashes:
                self.stats['duplicates_skipped'] += 1
                continue
            
            self.seen_hashes.add(chunk['hash'])
            
            # Enrich metadata
            metadata = self.enricher.enrich_chunk(chunk, source_metadata)
            
            # Create ID
            doc_id = f"{source_metadata.get('source', 'unknown')}_{chunk['hash']}_{i}"
            
            documents.append(chunk['content'])
            metadatas.append(metadata)
            ids.append(doc_id)
            self.stats['chunks_created'] += 1
        
        # Batch add to collection
        if documents:
            self.db_client.add_documents_batch(
                self.collection,
                documents,
                metadatas,
                ids
            )
    
    def print_stats(self):
        """Print ingestion statistics"""
        print("\n" + "="*60)
        print("INGESTION STATISTICS")
        print("="*60)
        for key, value in self.stats.items():
            print(f"  {key}: {value}")
        if self.collection:
            print(f"\nFinal collection size: {self.collection.count()} documents")
        print("="*60)


class RSTDirectiveParser:
    """
    Parse RST (reStructuredText) directives for MCP semantic metadata extraction.
    Specialized for EE2 compliance standards with custom mcp:* directives.
    
    Version: 5.0.0
    Date: November 14, 2025
    """
    
    # MCP custom directives for compliance documentation
    # Phase 1 directives (original)
    MCP_DIRECTIVES = [
        'mcp:standard',      # Core compliance requirement
        'mcp:example',       # Code example demonstrating compliance
        'mcp:guidance',      # Implementation guidance for developers
        'mcp:reference',     # Links to related standards or documentation
        'mcp:validation',    # Validation rules or test criteria
        # Phase 2 directives (SME corrections)
        'mcp:sme_correction',   # Documents systematic false positives
        'mcp:anti_pattern',     # Explicitly marks prohibited patterns
        'mcp:correct_pattern',  # Shows approved alternatives
        'mcp:context_types',    # Defines script contexts (operational/utility/test)
        'mcp:ai_guidance_rule', # Machine-readable rules for AI query processing
        'mcp:sme_validation',   # Marks SME-validated content
        # Phase 1 aliases (compatibility)
        'mcp:compliance',    # Marks compliance requirement sections
        'mcp:intent'         # Describes purpose and rationale
    ]
    
    # EE2 compliance categories (from EE2VectorStore.js)
    COMPLIANCE_CATEGORIES = {
        'environment_variables': {
            'weight': 2.5,
            'keywords': ['environment', 'variable', 'export', 'env', 'path', 'comroot', 'dataroot']
        },
        'error_handling': {
            'weight': 2.5,
            'keywords': ['error', 'exception', 'exit', 'trap', 'cleanup', 'failure', 'err_']
        },
        'production_utilities': {
            'weight': 2.2,
            'keywords': ['utility', 'script', 'module', 'library', 'tool', 'function']
        },
        'workflow_structure': {
            'weight': 2.0,
            'keywords': ['workflow', 'rocoto', 'job', 'task', 'dependency', 'sequence']
        },
        'file_naming': {
            'weight': 1.8,
            'keywords': ['filename', 'naming', 'convention', 'path', 'directory']
        },
        'directory_structure': {
            'weight': 1.8,
            'keywords': ['directory', 'folder', 'structure', 'hierarchy', 'organization']
        },
        'code_standards': {
            'weight': 1.5,
            'keywords': ['style', 'format', 'documentation', 'comment', 'best practice']
        }
    }
    
    # Intent classification keywords
    INTENT_KEYWORDS = {
        'validation': ['must', 'required', 'shall', 'check', 'validate', 'verify', 'test', 'ensure'],
        'guidance': ['should', 'recommend', 'suggest', 'consider', 'best practice', 'tip', 'note'],
        'example': ['example', 'sample', 'demonstration', 'shows', 'illustrates', 'usage'],
        'reference': ['see', 'refer', 'related', 'link', 'documentation', 'section', 'chapter']
    }
    
    def __init__(self):
        self.stats = {
            'directives_parsed': 0,
            'sections_extracted': 0,
            'code_blocks_found': 0,
            'attributes_extracted': 0
        }
    
    def parse_document(self, rst_content: str, source_file: str = None) -> List[Dict]:
        """
        Parse RST document into structured sections with directive metadata.
        
        Args:
            rst_content: Raw RST document content
            source_file: Optional source file path for tracking
            
        Returns:
            List of dicts with {text, metadata, directive_type, attributes}
        """
        sections = []
        
        # Split by directive boundaries using regex
        directive_pattern = r'\.\.\s+(' + '|'.join(re.escape(d) for d in self.MCP_DIRECTIVES) + r')::\s*([^\n]*)'
        
        # Find all directive positions
        matches = list(re.finditer(directive_pattern, rst_content))
        
        if not matches:
            # No MCP directives found - treat as single section
            return [{
                'text': rst_content.strip(),
                'metadata': {'source_file': source_file} if source_file else {},
                'directive_type': None,
                'attributes': {}
            }]
        
        # Process each directive section
        for i, match in enumerate(matches):
            directive_type = match.group(1)
            directive_arg = match.group(2).strip()
            
            # Extract section content (until next directive or end)
            start_pos = match.start()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(rst_content)
            section_content = rst_content[start_pos:end_pos]
            
            # Extract directive attributes and content
            attributes = self.extract_directive_metadata(section_content, directive_arg)
            content_text = self.extract_content_from_section(section_content)
            
            sections.append({
                'text': content_text.strip(),
                'metadata': {'source_file': source_file} if source_file else {},
                'directive_type': directive_type,
                'attributes': attributes
            })
            
            self.stats['directives_parsed'] += 1
            self.stats['sections_extracted'] += 1
        
        return sections
    
    def extract_directive_metadata(self, directive_block: str, directive_arg: str = None) -> Dict:
        """
        Extract :attribute: values from directive block.
        
        Example:
            .. mcp:standard:: environment_variables
               :category: environment_variables
               :level: must
               :intent: validation
               :platforms: hera,hercules
        
        Returns:
            Dict of attribute name -> value
        """
        attributes = {}
        
        # Add directive argument if present (e.g., "environment_variables")
        if directive_arg:
            attributes['directive_arg'] = directive_arg
        
        # Extract :attribute: value pairs
        attr_pattern = r'^\s*:([a-z_]+):\s*(.+)$'
        
        for line in directive_block.split('\n'):
            match = re.match(attr_pattern, line)
            if match:
                attr_name = match.group(1)
                attr_value = match.group(2).strip()
                attributes[attr_name] = attr_value
                self.stats['attributes_extracted'] += 1
        
        return attributes
    
    def extract_content_from_section(self, section_text: str) -> str:
        """
        Extract the actual content body from a directive section.
        Removes directive syntax, keeps text and code blocks.
        """
        lines = section_text.split('\n')
        content_lines = []
        in_content = False
        
        for line in lines:
            # Skip directive declaration line
            if line.strip().startswith('..') and any(d in line for d in self.MCP_DIRECTIVES):
                continue
            
            # Skip attribute lines
            if re.match(r'^\s*:[a-z_]+:', line):
                continue
            
            # Start collecting content after attributes
            if line.strip() and not line.strip().startswith(':'):
                in_content = True
            
            if in_content:
                content_lines.append(line)
        
        return '\n'.join(content_lines)
    
    def identify_intent(self, text: str, directive_type: str = None) -> Tuple[str, float]:
        """
        Classify document intent with confidence score.
        
        Args:
            text: Document text content
            directive_type: Optional directive type (mcp:example, etc.)
            
        Returns:
            (intent, confidence) where intent in:
            - 'validation': Checking/testing compliance
            - 'guidance': Implementation instructions
            - 'example': Code examples demonstrating compliance
            - 'reference': Background/links to related material
        """
        text_lower = text.lower()
        
        # Directive type provides strong signal
        if directive_type:
            if 'example' in directive_type:
                return ('example', 0.95)
            elif 'validation' in directive_type:
                return ('validation', 0.95)
            elif 'guidance' in directive_type:
                return ('guidance', 0.95)
            elif 'reference' in directive_type:
                return ('reference', 0.95)
            elif 'standard' in directive_type:
                return ('validation', 0.85)
        
        # Keyword-based classification
        intent_scores = {}
        
        for intent, keywords in self.INTENT_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            intent_scores[intent] = score
        
        # Find highest scoring intent
        if intent_scores:
            max_intent = max(intent_scores, key=intent_scores.get)
            max_score = intent_scores[max_intent]
            
            # Normalize confidence (max 20 keyword matches = 1.0 confidence)
            confidence = min(max_score / 20.0, 0.9)
            
            # Must have at least 1 match
            if max_score > 0:
                return (max_intent, max(confidence, 0.5))
        
        # Default: validation intent with low confidence
        return ('validation', 0.3)
    
    def extract_code_blocks(self, text: str) -> List[Dict]:
        """
        Extract code examples with language detection.
        
        Supports:
        - RST code-block directive: .. code-block:: python
        - Markdown-style: ```python
        - Indented code blocks
        """
        code_blocks = []
        
        # RST code-block directive
        rst_code_pattern = r'\.\.\s+code-block::\s+(\w+)\s*\n\s*\n((?:(?:\s{3,}|\t).+\n?)+)'
        for match in re.finditer(rst_code_pattern, text):
            language = match.group(1)
            code = match.group(2)
            # Remove leading indentation
            code = '\n'.join(line[3:] if len(line) > 3 else line for line in code.split('\n'))
            
            code_blocks.append({
                'language': language,
                'code': code.strip(),
                'type': 'rst_directive'
            })
            self.stats['code_blocks_found'] += 1
        
        # Markdown-style code blocks
        md_code_pattern = r'```(\w+)?\s*\n(.*?)```'
        for match in re.finditer(md_code_pattern, text, re.DOTALL):
            language = match.group(1) or 'unknown'
            code = match.group(2)
            
            code_blocks.append({
                'language': language,
                'code': code.strip(),
                'type': 'markdown'
            })
            self.stats['code_blocks_found'] += 1
        
        return code_blocks
    
    def categorize_compliance(self, text: str, directive_attrs: Dict = None) -> List[Tuple[str, float]]:
        """
        Determine compliance categories based on content and attributes.
        
        Args:
            text: Document text content
            directive_attrs: Directive attributes (may include explicit :category:)
            
        Returns:
            List of (category, confidence) tuples, sorted by confidence
        """
        categories = []
        
        # Check for explicit category attribute
        if directive_attrs and 'category' in directive_attrs:
            explicit_cat = directive_attrs['category']
            if explicit_cat in self.COMPLIANCE_CATEGORIES:
                categories.append((explicit_cat, 1.0))
                return categories
        
        # Keyword-based categorization
        text_lower = text.lower()
        
        for category, info in self.COMPLIANCE_CATEGORIES.items():
            keywords = info['keywords']
            weight = info['weight']
            
            # Count keyword matches
            matches = sum(1 for kw in keywords if kw in text_lower)
            
            if matches > 0:
                # Confidence = (matches * category_weight) / max_possible
                # Normalized to 0-1 range
                confidence = min((matches * weight) / 20.0, 0.95)
                categories.append((category, confidence))
        
        # Sort by confidence descending
        categories.sort(key=lambda x: x[1], reverse=True)
        
        # Return top 3 categories
        return categories[:3]
    
    def get_stats(self) -> Dict:
        """Return parsing statistics"""
        return self.stats.copy()


# Export public API
__all__ = [
    'SemanticChunker',
    'ChromaDBClient',
    'URLCrawler',
    'LocalRepoParser',
    'MetadataEnricher',
    'BaseIngester',
    'RSTDirectiveParser',
    'EMBEDDING_MODEL',
    'DEFAULT_MIN_CHUNK_SIZE',
    'DEFAULT_MAX_CHUNK_SIZE'
]
