#!/usr/bin/env python3
"""
Comprehensive Vector Embedding Generator for RAG System
========================================================

This script performs deep crawling of documentation sites to create
a comprehensive knowledge base with extensive coverage.

Features:
- Full ReadTheDocs site crawling (all pages, not just main page)
- GitHub wiki crawling (all wiki pages)
- GitHub repository documentation files (README, docs/, etc.)
- Local workflow documentation
- ChromaDB vector storage with comprehensive metadata
- Progress tracking and resumable operations
"""

import json
import os
import sys
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from urllib.parse import urljoin, urlparse
import asyncio
import aiohttp
from bs4 import BeautifulSoup
import nltk
from nltk.tokenize import sent_tokenize
import numpy as np
import base64
import re
from collections import defaultdict

# Download required NLTK data
try:
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    print("Downloading NLTK punkt_tab...")
    nltk.download('punkt_tab', quiet=True)

try:
    from sentence_transformers import SentenceTransformer
    import chromadb
    from chromadb.config import Settings
except ImportError as e:
    print(f"Missing required packages: {e}")
    print("Install with: pip install sentence-transformers chromadb nltk beautifulsoup4 aiohttp")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ComprehensiveVectorGenerator:
    """Comprehensive vector generator with deep documentation crawling."""

    def __init__(self, knowledge_base_dir: str = "knowledge-base"):
        self.knowledge_base_dir = Path(knowledge_base_dir)
        self.knowledge_base_dir.mkdir(exist_ok=True)

        # Initialize embedding model
        logger.info("Loading sentence transformer model (all-MiniLM-L6-v2)...")
        self.model = SentenceTransformer('all-MiniLM-L6-v2')

        # Initialize ChromaDB
        logger.info("Initializing ChromaDB...")
        self.chroma_client = chromadb.PersistentClient(
            path=str(self.knowledge_base_dir / "chroma_db"),
            settings=Settings(anonymized_telemetry=False, allow_reset=False)
        )

        # Reset collection for fresh start
        try:
            self.chroma_client.delete_collection("global_workflow_docs")
            logger.info("Deleted existing collection for fresh start")
        except:
            pass

        self.collection = self.chroma_client.get_or_create_collection(
            name="global_workflow_docs",
            metadata={"description": "Comprehensive Global Workflow documentation"}
        )

        # Load documentation references
        self.doc_refs = self._load_documentation_references()

        # Track visited URLs to avoid duplicates
        self.visited_urls: Set[str] = set()

        # Track crawl statistics
        self.stats = defaultdict(int)

        # GitHub token for API
        self.github_token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
        if self.github_token:
            logger.info(f"Using GitHub token for authenticated requests (token length: {len(self.github_token)})")
        else:
            logger.warning("No GitHub token found - API rate limits will be restrictive")

    def _load_documentation_references(self) -> Dict[str, Any]:
        """Load documentation references from JSON file."""
        refs_file = Path("documentation-references.json")
        if refs_file.exists():
            with open(refs_file, 'r') as f:
                return json.load(f)
        else:
            logger.error("documentation-references.json not found!")
            return {"documentation_references": {"external": {}, "internal": {}}}

    async def crawl_readthedocs_site(self, base_url: str, max_pages: int = 100) -> List[Dict[str, Any]]:
        """Comprehensively crawl a ReadTheDocs site."""
        logger.info(f"🔍 Crawling ReadTheDocs site: {base_url} (max {max_pages} pages)")

        contents = []
        to_visit = [base_url]
        visited = set()

        parsed_base = urlparse(base_url)
        base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"

        async with aiohttp.ClientSession() as session:
            while to_visit and len(visited) < max_pages:
                url = to_visit.pop(0)

                if url in visited or url in self.visited_urls:
                    continue

                visited.add(url)
                self.visited_urls.add(url)

                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                        if response.status != 200:
                            logger.debug(f"Skipping {url} (HTTP {response.status})")
                            continue

                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')

                        # Extract main content (ReadTheDocs uses specific classes)
                        main_content = None
                        for selector in [
                            'div[role="main"]',
                            'div.document',
                            'div.rst-content',
                            'div.section',
                            'article.doc-body'
                        ]:
                            main_content = soup.select_one(selector)
                            if main_content:
                                break

                        if not main_content:
                            main_content = soup.body

                        if main_content:
                            # Extract text content
                            text = main_content.get_text(separator='\n', strip=True)

                            # Clean up text
                            text = re.sub(r'\n{3,}', '\n\n', text)
                            text = re.sub(r' {2,}', ' ', text)

                            # Get title
                            title_tag = soup.find('title')
                            title = title_tag.get_text() if title_tag else url

                            if len(text) > 200:  # Only include substantial pages
                                contents.append({
                                    "url": url,
                                    "title": title,
                                    "content": text,
                                    "word_count": len(text.split()),
                                    "fetch_time": time.time(),
                                    "source_type": "readthedocs",
                                    "base_url": base_url
                                })
                                logger.info(f"  ✓ Crawled: {title[:60]}... ({len(text)} chars)")
                                self.stats['readthedocs_pages'] += 1

                        # Find more links on same domain
                        for link in soup.find_all('a', href=True):
                            href = link['href']

                            # Convert relative URLs to absolute
                            if href.startswith('/'):
                                full_url = base_domain + href
                            elif href.startswith('http'):
                                full_url = href
                            else:
                                full_url = urljoin(url, href)

                            # Only follow links on same domain
                            if urlparse(full_url).netloc == parsed_base.netloc:
                                # Avoid anchors, downloads, etc.
                                if '#' in full_url:
                                    full_url = full_url.split('#')[0]
                                if full_url and full_url not in visited and full_url not in to_visit:
                                    to_visit.append(full_url)

                    # Be nice to the server
                    await asyncio.sleep(0.5)

                except Exception as e:
                    logger.debug(f"Error crawling {url}: {e}")
                    continue

        logger.info(f"  📊 Crawled {len(contents)} pages from {base_url}")
        return contents

    async def crawl_github_wiki(self, wiki_url: str, max_pages: int = 50) -> List[Dict[str, Any]]:
        """Crawl a GitHub wiki comprehensively."""
        logger.info(f"📖 Crawling GitHub wiki: {wiki_url} (max {max_pages} pages)")

        contents = []

        # GitHub wikis have a special structure
        # Main page: https://github.com/owner/repo/wiki
        # Individual pages: https://github.com/owner/repo/wiki/Page-Name

        async with aiohttp.ClientSession() as session:
            try:
                # Get the wiki home page
                async with session.get(wiki_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status != 200:
                        logger.warning(f"Could not access wiki: {wiki_url}")
                        return []

                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')

                    # Find all wiki page links
                    wiki_links = []
                    for link in soup.find_all('a', href=True):
                        href = link['href']
                        if '/wiki/' in href and href not in wiki_links:
                            full_url = urljoin(wiki_url, href)
                            if full_url not in self.visited_urls:
                                wiki_links.append(full_url)

                    logger.info(f"  Found {len(wiki_links)} wiki pages")

                    # Crawl each wiki page
                    for wiki_page_url in wiki_links[:max_pages]:
                        if wiki_page_url in self.visited_urls:
                            continue

                        self.visited_urls.add(wiki_page_url)

                        try:
                            async with session.get(wiki_page_url, timeout=aiohttp.ClientTimeout(total=30)) as page_response:
                                if page_response.status == 200:
                                    page_html = await page_response.text()
                                    page_soup = BeautifulSoup(page_html, 'html.parser')

                                    # Extract wiki content
                                    wiki_body = page_soup.find('div', {'class': 'markdown-body'})
                                    if not wiki_body:
                                        wiki_body = page_soup.find('div', {'id': 'wiki-body'})

                                    if wiki_body:
                                        text = wiki_body.get_text(separator='\n', strip=True)
                                        text = re.sub(r'\n{3,}', '\n\n', text)

                                        title_tag = page_soup.find('h1')
                                        title = title_tag.get_text() if title_tag else wiki_page_url.split('/')[-1]

                                        if len(text) > 100:
                                            contents.append({
                                                "url": wiki_page_url,
                                                "title": f"Wiki: {title}",
                                                "content": text,
                                                "word_count": len(text.split()),
                                                "fetch_time": time.time(),
                                                "source_type": "github_wiki",
                                                "wiki_base": wiki_url
                                            })
                                            logger.info(f"  ✓ Wiki page: {title[:50]}... ({len(text)} chars)")
                                            self.stats['github_wiki_pages'] += 1

                            await asyncio.sleep(0.5)

                        except Exception as e:
                            logger.debug(f"Error crawling wiki page {wiki_page_url}: {e}")
                            continue

            except Exception as e:
                logger.warning(f"Error accessing GitHub wiki {wiki_url}: {e}")

        logger.info(f"  📊 Crawled {len(contents)} wiki pages")
        return contents

    async def fetch_github_repo_docs(self, repo_url: str) -> List[Dict[str, Any]]:
        """Fetch comprehensive documentation from a GitHub repository."""
        logger.info(f"📦 Fetching GitHub repo docs: {repo_url}")

        # Parse repo URL
        match = re.search(r'github\.com/([^/]+)/([^/]+)', repo_url)
        if not match:
            logger.warning(f"Invalid GitHub URL: {repo_url}")
            return []

        owner, repo = match.groups()
        repo = repo.replace('.git', '')

        contents = []

        # Files to fetch
        important_files = [
            'README.md', 'README.rst', 'README',
            'INSTALL.md', 'INSTALLATION.md',
            'CONTRIBUTING.md', 'QUICKSTART.md',
            'USAGE.md', 'CONFIGURATION.md',
            'docs/index.md', 'docs/README.md',
            'doc/index.md', 'doc/README.md'
        ]

        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'Global-Workflow-RAG-System/1.0'
        }

        if self.github_token:
            headers['Authorization'] = f'token {self.github_token}'

        async with aiohttp.ClientSession() as session:
            for file_path in important_files:
                api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"

                try:
                    async with session.get(api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                        if response.status == 200:
                            data = await response.json()

                            if data.get('encoding') == 'base64':
                                try:
                                    content = base64.b64decode(data['content']).decode('utf-8')

                                    if len(content) > 100:
                                        contents.append({
                                            "url": f"{repo_url}/blob/develop/{file_path}",
                                            "title": f"{repo} - {file_path}",
                                            "content": content,
                                            "word_count": len(content.split()),
                                            "fetch_time": time.time(),
                                            "source_type": "github_file",
                                            "repository": f"{owner}/{repo}",
                                            "file_path": file_path
                                        })
                                        logger.info(f"  ✓ Fetched: {file_path} ({len(content)} chars)")
                                        self.stats['github_files'] += 1
                                except Exception as e:
                                    logger.debug(f"Error decoding {file_path}: {e}")

                        await asyncio.sleep(0.3)  # Rate limiting

                except Exception as e:
                    logger.debug(f"Could not fetch {file_path}: {e}")
                    continue

            # Try to get docs/ directory listing
            try:
                docs_url = f"https://api.github.com/repos/{owner}/{repo}/contents/docs"
                async with session.get(docs_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        docs_listing = await response.json()

                        if isinstance(docs_listing, list):
                            md_files = [item for item in docs_listing
                                       if item.get('type') == 'file' and
                                       (item.get('name', '').endswith('.md') or
                                        item.get('name', '').endswith('.rst'))]

                            logger.info(f"  Found {len(md_files)} doc files in docs/ directory")

                            for doc_file in md_files[:20]:  # Limit to 20 doc files
                                doc_path = f"docs/{doc_file['name']}"
                                doc_api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{doc_path}"

                                try:
                                    async with session.get(doc_api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as doc_response:
                                        if doc_response.status == 200:
                                            doc_data = await doc_response.json()

                                            if doc_data.get('encoding') == 'base64':
                                                doc_content = base64.b64decode(doc_data['content']).decode('utf-8')

                                                if len(doc_content) > 100:
                                                    contents.append({
                                                        "url": f"{repo_url}/blob/develop/{doc_path}",
                                                        "title": f"{repo} - {doc_file['name']}",
                                                        "content": doc_content,
                                                        "word_count": len(doc_content.split()),
                                                        "fetch_time": time.time(),
                                                        "source_type": "github_docs",
                                                        "repository": f"{owner}/{repo}",
                                                        "file_path": doc_path
                                                    })
                                                    logger.info(f"  ✓ Doc: {doc_file['name']} ({len(doc_content)} chars)")
                                                    self.stats['github_docs'] += 1

                                    await asyncio.sleep(0.3)

                                except Exception as e:
                                    logger.debug(f"Error fetching doc {doc_file['name']}: {e}")
                                    continue

            except Exception as e:
                logger.debug(f"Could not access docs/ directory: {e}")

        logger.info(f"  📊 Fetched {len(contents)} items from {owner}/{repo}")
        return contents

    def chunk_text(self, text: str, max_chunk_size: int = 1000, overlap: int = 100) -> List[str]:
        """Split text into overlapping chunks."""
        sentences = sent_tokenize(text)

        chunks = []
        current_chunk = []
        current_size = 0

        for sentence in sentences:
            sentence_words = len(sentence.split())

            if current_size + sentence_words > max_chunk_size and current_chunk:
                # Create chunk
                chunks.append(' '.join(current_chunk))

                # Start new chunk with overlap
                overlap_words = []
                overlap_size = 0
                for s in reversed(current_chunk):
                    s_words = len(s.split())
                    if overlap_size + s_words <= overlap:
                        overlap_words.insert(0, s)
                        overlap_size += s_words
                    else:
                        break

                current_chunk = overlap_words
                current_size = overlap_size

            current_chunk.append(sentence)
            current_size += sentence_words

        if current_chunk:
            chunks.append(' '.join(current_chunk))

        return chunks

    async def generate_comprehensive_knowledge_base(self):
        """Generate comprehensive knowledge base with deep crawling."""
        logger.info("=" * 80)
        logger.info("Starting COMPREHENSIVE knowledge base generation")
        logger.info("=" * 80)

        all_contents = []

        # 1. Crawl ReadTheDocs sites
        logger.info("\n📚 Phase 1: ReadTheDocs Sites")
        logger.info("-" * 80)

        readthedocs_sites = [
            "https://global-workflow.readthedocs.io/en/latest/",
            "https://ufs-weather-model.readthedocs.io/en/latest/",
            "https://spack-stack.readthedocs.io/en/latest/",
            "https://wxflow.readthedocs.io/en/latest/",
            "https://upp.readthedocs.io/en/latest/",
            "https://nws-hpc-standards.readthedocs.io/en/latest/",  # EE2 Standards (CRITICAL)
        ]

        for site in readthedocs_sites:
            site_contents = await self.crawl_readthedocs_site(site, max_pages=100)
            all_contents.extend(site_contents)
            logger.info(f"  Total contents so far: {len(all_contents)} pages")
            await asyncio.sleep(2)  # Be polite between sites

        # 2. Crawl GitHub wikis
        logger.info("\n📖 Phase 2: GitHub Wikis")
        logger.info("-" * 80)

        github_wikis = [
            "https://github.com/ufs-community/ufs-weather-model/wiki",
            "https://github.com/JCSDA/spack-stack/wiki",
            "https://github.com/NOAA-EMC/NCEPLIBS/wiki",
        ]

        for wiki in github_wikis:
            wiki_contents = await self.crawl_github_wiki(wiki, max_pages=50)
            all_contents.extend(wiki_contents)
            logger.info(f"  Total contents so far: {len(all_contents)} pages")
            await asyncio.sleep(2)

        # 3. Fetch GitHub repository documentation
        logger.info("\n📦 Phase 3: GitHub Repositories")
        logger.info("-" * 80)

        github_repos = [
            "https://github.com/NOAA-EMC/global-workflow",
            "https://github.com/NOAA-EMC/GSI",
            "https://github.com/NOAA-EMC/GDASApp",
            "https://github.com/NOAA-EMC/wxflow",
            "https://github.com/NOAA-EMC/UPP",
            "https://github.com/ufs-community/ufs-weather-model",
            "https://github.com/christopherwharrop-NOAA/rocoto",
            "https://github.com/JCSDA/spack-stack",
            "https://github.com/ufs-community/UFS_UTILS",
        ]

        for repo in github_repos:
            repo_contents = await self.fetch_github_repo_docs(repo)
            all_contents.extend(repo_contents)
            logger.info(f"  Total contents so far: {len(all_contents)} items")
            await asyncio.sleep(2)

        # 4. Generate embeddings and store in ChromaDB
        logger.info("\n🔢 Phase 4: Generating Embeddings")
        logger.info("-" * 80)

        total_words = sum(item['word_count'] for item in all_contents)
        logger.info(f"Total content collected:")
        logger.info(f"  - Pages/Files: {len(all_contents)}")
        logger.info(f"  - Total words: {total_words:,}")
        logger.info(f"  - ReadTheDocs pages: {self.stats['readthedocs_pages']}")
        logger.info(f"  - GitHub wiki pages: {self.stats['github_wiki_pages']}")
        logger.info(f"  - GitHub files: {self.stats['github_files']}")
        logger.info(f"  - GitHub docs: {self.stats['github_docs']}")

        # Chunk all content
        all_chunks = []
        for content_item in all_contents:
            chunks = self.chunk_text(content_item['content'], max_chunk_size=800, overlap=100)

            for i, chunk in enumerate(chunks):
                all_chunks.append({
                    'text': chunk,
                    'metadata': {
                        'source': content_item.get('url', 'unknown'),
                        'title': content_item.get('title', 'Unknown'),
                        'source_type': content_item.get('source_type', 'unknown'),
                        'chunk_id': f"{content_item.get('url', 'unknown')}#chunk{i}",
                        'chunk_index': i,
                        'total_chunks': len(chunks),
                        'repository': content_item.get('repository', ''),
                        'file_path': content_item.get('file_path', ''),
                        'base_url': content_item.get('base_url', ''),
                        'word_count': len(chunk.split())
                    }
                })

        logger.info(f"\nGenerated {len(all_chunks)} chunks from {len(all_contents)} documents")

        # Generate embeddings in batches
        logger.info("Generating embeddings...")
        batch_size = 32
        total_batches = (len(all_chunks) + batch_size - 1) // batch_size

        for batch_idx in range(0, len(all_chunks), batch_size):
            batch = all_chunks[batch_idx:batch_idx + batch_size]
            texts = [chunk['text'] for chunk in batch]

            embeddings = self.model.encode(texts, show_progress_bar=True)

            # Store in ChromaDB
            ids = [f"chunk_{batch_idx + i}" for i in range(len(batch))]
            metadatas = [chunk['metadata'] for chunk in batch]

            self.collection.add(
                ids=ids,
                embeddings=embeddings.tolist(),
                documents=texts,
                metadatas=metadatas
            )

            logger.info(f"  Stored batch {(batch_idx // batch_size) + 1}/{total_batches}")

        # Save summary
        summary = {
            "total_documents": len(all_contents),
            "total_chunks": len(all_chunks),
            "total_words": total_words,
            "statistics": dict(self.stats),
            "generation_time": time.time(),
            "embedding_model": "all-MiniLM-L6-v2",
            "embedding_dimensions": 384
        }

        summary_file = self.knowledge_base_dir / "comprehensive_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        logger.info("\n" + "=" * 80)
        logger.info("🎉 COMPREHENSIVE Knowledge Base Generation Complete!")
        logger.info("=" * 80)
        logger.info(f"✅ Total documents processed: {len(all_contents)}")
        logger.info(f"✅ Total chunks with embeddings: {len(all_chunks)}")
        logger.info(f"✅ Total words indexed: {total_words:,}")
        logger.info(f"✅ ChromaDB collection: global_workflow_docs")
        logger.info("=" * 80)

async def main():
    """Main execution function."""
    generator = ComprehensiveVectorGenerator()
    await generator.generate_comprehensive_knowledge_base()

if __name__ == "__main__":
    asyncio.run(main())
