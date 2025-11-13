#!/usr/bin/env python3
"""
Enhanced Vector Embedding Generator for RAG System
==================================================

This script generates vector embeddings for both local content and external URL content,
creating a complete knowledge base for semantic search in the RAG system.

Features:
- Local content embedding generation
- External URL content fetching and processing
- ChromaDB vector storage
- Progress tracking and error handling
"""

import json
import os
import sys
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse
import asyncio
import aiohttp
from bs4 import BeautifulSoup
import nltk
from nltk.tokenize import sent_tokenize
import numpy as np
import base64

# Download required NLTK data
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

try:
    from sentence_transformers import SentenceTransformer
    import chromadb
except ImportError as e:
    print(f"Missing required packages: {e}")
    print("Install with: pip install sentence-transformers chromadb nltk beautifulsoup4 aiohttp")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class EnhancedVectorGenerator:
    """Enhanced vector generator with URL content fetching and ChromaDB storage."""
    
    def __init__(self, knowledge_base_dir: str = "knowledge-base"):
        self.knowledge_base_dir = Path(knowledge_base_dir)
        self.knowledge_base_dir.mkdir(exist_ok=True)
        
        # Initialize embedding model
        logger.info("Loading sentence transformer model...")
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Initialize ChromaDB
        logger.info("Initializing ChromaDB...")
        self.chroma_client = chromadb.PersistentClient(path=str(self.knowledge_base_dir / "chroma_db"))
        self.collection = self.chroma_client.get_or_create_collection(
            name="global_workflow_docs",
            metadata={"description": "Global Workflow documentation with external references"}
        )
        
        # Load documentation references
        self.doc_refs = self._load_documentation_references()
        
    def _load_documentation_references(self) -> Dict[str, Any]:
        """Load documentation references from JSON file."""
        refs_file = Path("documentation-references.json")
        if refs_file.exists():
            with open(refs_file, 'r') as f:
                return json.load(f)
        else:
            logger.warning("documentation-references.json not found")
            return {"documentation_references": {"external": {}}}
    
    def extract_python_documentation(self, python_code: str) -> str:
        """Extract docstrings and meaningful comments from Python code."""
        import re
        
        documentation_parts = []
        
        # Extract module docstring
        module_docstring_match = re.search(r'^[\s]*["\'][\s]*(["\'])\1\1(.*?)\1{3}', python_code, re.DOTALL | re.MULTILINE)
        if module_docstring_match:
            documentation_parts.append("MODULE DOCUMENTATION:")
            documentation_parts.append(module_docstring_match.group(2).strip())
        
        # Extract function and class docstrings
        docstring_pattern = r'(def\s+\w+.*?|class\s+\w+.*?):\s*[\s]*["\'][\s]*(["\'])\2\2(.*?)\2{3}'
        docstring_matches = re.finditer(docstring_pattern, python_code, re.DOTALL)
        
        for match in docstring_matches:
            function_def = match.group(1).strip()
            docstring = match.group(3).strip()
            if docstring and len(docstring) > 20:  # Only meaningful docstrings
                documentation_parts.append(f"\n{function_def}:")
                documentation_parts.append(docstring)
        
        # Extract meaningful comments (not just # TODO or # FIXME)
        comment_lines = []
        for line in python_code.split('\n'):
            line = line.strip()
            if (line.startswith('#') and 
                len(line) > 10 and 
                not any(skip in line.lower() for skip in ['todo', 'fixme', 'hack', 'xxx'])):
                comment_lines.append(line[1:].strip())
        
        if comment_lines:
            documentation_parts.append("\nCODE COMMENTS:")
            documentation_parts.extend(comment_lines[:10])  # Limit comments
        
        result = '\n'.join(documentation_parts)
        return result if len(result) > 50 else ""

    def extract_github_repo_info(self, url: str) -> Optional[tuple]:
        """Extract owner and repo from GitHub URL."""
        try:
            parts = url.replace("https://github.com/", "").rstrip("/").split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]
        except:
            pass
        return None

    async def fetch_github_repository_content(self, url: str) -> List[Dict[str, Any]]:
        """Fetch comprehensive content from a GitHub repository using enhanced GitHub API."""
        repo_info = self.extract_github_repo_info(url)
        if not repo_info:
            return []
        
        owner, repo = repo_info
        logger.info(f"Fetching comprehensive GitHub repository content: {owner}/{repo}")
        
        contents = []
        
        try:
            # 1. Get README file - try multiple formats
            readme_files = ["README.md", "README.rst", "README.txt", "README", "readme.md", "readme.txt"]
            for readme_name in readme_files:
                try:
                    readme_content = await self.call_github_api(owner, repo, readme_name)
                    if readme_content and len(readme_content.strip()) > 100:  # Ensure meaningful content
                        contents.append({
                            "url": f"{url}/{readme_name}",
                            "title": f"{repo} - {readme_name}",
                            "content": readme_content,
                            "word_count": len(readme_content.split()),
                            "fetch_time": time.time(),
                            "source_type": "github_readme",
                            "repository": f"{owner}/{repo}"
                        })
                        logger.info(f"Fetched README: {len(readme_content)} characters")
                        break
                except Exception as e:
                    logger.debug(f"Could not fetch {readme_name}: {e}")
                    continue
            
            # 2. Get documentation directory contents
            doc_directories = ["docs", "doc", "documentation", "Documentation"]
            for doc_dir in doc_directories:
                try:
                    docs_listing = await self.call_github_api(owner, repo, f"{doc_dir}/", is_directory=True)
                    if docs_listing and isinstance(docs_listing, list):
                        logger.info(f"Found {len(docs_listing)} items in {doc_dir}/ directory")
                        
                        # Process documentation files
                        for item in docs_listing[:15]:  # Limit to avoid rate limits
                            if (item.get("type") == "file" and 
                                item.get("name", "").lower().endswith((".md", ".rst", ".txt", ".asciidoc"))):
                                try:
                                    file_content = await self.call_github_api(owner, repo, item["path"])
                                    if file_content and len(file_content.strip()) > 50:
                                        contents.append({
                                            "url": f"{url}/{item['path']}",
                                            "title": f"{repo} - {item['name']}",
                                            "content": file_content,
                                            "word_count": len(file_content.split()),
                                            "fetch_time": time.time(),
                                            "source_type": "github_docs",
                                            "repository": f"{owner}/{repo}",
                                            "file_path": item["path"]
                                        })
                                        logger.info(f"Fetched doc file: {item['name']} ({len(file_content)} chars)")
                                except Exception as e:
                                    logger.debug(f"Could not fetch {item['path']}: {e}")
                                    continue
                        break  # Found a documentation directory, stop looking
                except Exception as e:
                    logger.debug(f"Could not access {doc_dir}/ directory: {e}")
            
            # 3. Get key configuration files
            config_files = [
                "CHANGELOG.md", "CHANGELOG.rst", "HISTORY.md",
                "CONTRIBUTING.md", "INSTALL.md", "INSTALLATION.md",
                "USAGE.md", "QUICKSTART.md", "GETTING_STARTED.md",
                "CONFIGURATION.md", "CONFIG.md"
            ]
            
            for config_file in config_files:
                try:
                    config_content = await self.call_github_api(owner, repo, config_file)
                    if config_content and len(config_content.strip()) > 100:
                        contents.append({
                            "url": f"{url}/{config_file}",
                            "title": f"{repo} - {config_file}",
                            "content": config_content,
                            "word_count": len(config_content.split()),
                            "fetch_time": time.time(),
                            "source_type": "github_config",
                            "repository": f"{owner}/{repo}",
                            "file_path": config_file
                        })
                        logger.info(f"Fetched config file: {config_file} ({len(config_content)} chars)")
                except Exception as e:
                    logger.debug(f"Could not fetch {config_file}: {e}")
                    continue
            
            # 4. Get important source files with docstrings (Python files)
            try:
                root_listing = await self.call_github_api(owner, repo, "", is_directory=True)
                if root_listing and isinstance(root_listing, list):
                    python_files = [item for item in root_listing 
                                  if (item.get("type") == "file" and 
                                      item.get("name", "").endswith(".py") and
                                      item.get("size", 0) > 1000)]  # Only substantial files
                    
                    for py_file in python_files[:5]:  # Limit to 5 main Python files
                        try:
                            py_content = await self.call_github_api(owner, repo, py_file["name"])
                            if py_content and len(py_content.strip()) > 200:
                                # Extract docstrings and comments
                                docstring_content = self.extract_python_documentation(py_content)
                                if docstring_content:
                                    contents.append({
                                        "url": f"{url}/{py_file['name']}",
                                        "title": f"{repo} - {py_file['name']} (Documentation)",
                                        "content": docstring_content,
                                        "word_count": len(docstring_content.split()),
                                        "fetch_time": time.time(),
                                        "source_type": "github_code_docs",
                                        "repository": f"{owner}/{repo}",
                                        "file_path": py_file["name"]
                                    })
                                    logger.info(f"Extracted docs from: {py_file['name']}")
                        except Exception as e:
                            logger.debug(f"Could not process Python file {py_file['name']}: {e}")
            except Exception as e:
                logger.debug(f"Could not list root directory for Python files: {e}")
            
            total_words = sum(item.get("word_count", 0) for item in contents)
            logger.info(f"✅ Successfully retrieved {len(contents)} content items from {owner}/{repo}")
            logger.info(f"📊 Total words collected: {total_words:,}")
            return contents
            
        except Exception as e:
            logger.error(f"Error fetching GitHub repository {url}: {str(e)}")
            return []

    async def call_github_api(self, owner: str, repo: str, path: str, is_directory: bool = False) -> Optional[str]:
        """Fetch content directly from GitHub API with enhanced error handling."""
        try:
            # Use GitHub API v4 for better content access
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
            
            headers = {
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'Global-Workflow-RAG-System/1.0'
            }
            
            # Add GitHub token if available in environment
            github_token = os.environ.get('GITHUB_TOKEN')
            if github_token:
                headers['Authorization'] = f'token {github_token}'
                logger.debug(f"Using GitHub token for authenticated requests")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if is_directory:
                            # Return list of directory contents
                            if isinstance(data, list):
                                return data
                            else:
                                return None
                        else:
                            # Decode file content
                            if data.get('encoding') == 'base64':
                                content = base64.b64decode(data['content']).decode('utf-8')
                                logger.info(f"Successfully fetched {len(content)} characters from {owner}/{repo}/{path}")
                                return content
                            else:
                                logger.warning(f"Unexpected encoding for {path}: {data.get('encoding')}")
                                return None
                    elif response.status == 404:
                        logger.debug(f"File not found: {owner}/{repo}/{path}")
                        return None
                    else:
                        logger.warning(f"GitHub API error for {path}: HTTP {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"GitHub API error for {owner}/{repo}/{path}: {str(e)}")
            return None

    async def fetch_url_content(self, session: aiohttp.ClientSession, url: str) -> Optional[Dict[str, Any]]:
        """Fetch and process content from a URL."""
        try:
            logger.info(f"Fetching: {url}")
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.decompose()
                    
                    # Extract text content
                    text = soup.get_text()
                    
                    # Clean up text
                    lines = (line.strip() for line in text.splitlines())
                    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                    text = ' '.join(chunk for chunk in chunks if chunk)
                    
                    # Extract title
                    title = soup.title.string if soup.title else urlparse(url).netloc
                    
                    return {
                        "url": url,
                        "title": title.strip() if title else "Unknown",
                        "content": text,
                        "word_count": len(text.split()),
                        "fetch_time": time.time()
                    }
                else:
                    logger.warning(f"Failed to fetch {url}: HTTP {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            return None
    
    async def fetch_all_urls(self) -> List[Dict[str, Any]]:
        """Fetch content from all validated URLs."""
        urls = []
        
        # Load validated URLs from validation results
        validation_file = Path(__file__).parent / "validation" / "url-validation-results.json"
        if validation_file.exists():
            with open(validation_file, 'r') as f:
                validation_data = json.load(f)
                
            # Extract all valid URLs
            valid_urls = validation_data.get("results", {}).get("valid", [])
            for url_entry in valid_urls:
                url = url_entry.get("url", "")
                if url.startswith("http") and not url.endswith(".git"):
                    urls.append(url)
            
            logger.info(f"Loaded {len(urls)} validated URLs from validation results")
        else:
            # Fallback to documentation references if validation file doesn't exist
            logger.warning("Validation file not found, using documentation references as fallback")
            for category_name, category_data in self.doc_refs.get("documentation_references", {}).items():
                if isinstance(category_data, dict):
                    for item_name, item_data in category_data.items():
                        if isinstance(item_data, dict):
                            for key, value in item_data.items():
                                if key in ["documentation", "url", "user_guide", "github"] and isinstance(value, str):
                                    if value.startswith("http"):
                                        urls.append(value)
        
        # Remove duplicates and filter out .git URLs
        urls = list(set(url for url in urls if not url.endswith(".git")))
        logger.info(f"Found {len(urls)} unique URLs to process")
        
        # Fetch content from all URLs
        url_contents = []
        
        # Separate GitHub URLs from other URLs for different processing
        github_urls = [url for url in urls if "github.com" in url]
        other_urls = [url for url in urls if "github.com" not in url]
        
        logger.info(f"Processing {len(github_urls)} GitHub repositories and {len(other_urls)} other URLs")
        
        # Process GitHub repositories with enhanced API extraction
        for github_url in github_urls:
            try:
                logger.info(f"🔍 Processing GitHub repository: {github_url}")
                github_contents = await self.fetch_github_repository_content(github_url)
                if github_contents:
                    url_contents.extend(github_contents)
                    logger.info(f"✅ GitHub API: Extracted {len(github_contents)} content items from {github_url}")
                else:
                    # Fallback to regular web scraping for GitHub if API fails
                    logger.info(f"⬇️ GitHub API failed, falling back to web scraping for {github_url}")
                    async with aiohttp.ClientSession() as session:
                        fallback_content = await self.fetch_url_content(session, github_url)
                        if fallback_content:
                            url_contents.append(fallback_content)
            except Exception as e:
                logger.error(f"Error processing GitHub repository {github_url}: {str(e)}")
                continue
        
        # Process other URLs with regular web scraping
        async with aiohttp.ClientSession() as session:
            tasks = []
            for url in other_urls:
                task = asyncio.create_task(self.fetch_url_content(session, url))
                tasks.append(task)
            
            logger.info(f"🌐 Fetching {len(tasks)} regular URLs concurrently...")
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Error fetching {other_urls[i]}: {str(result)}")
                elif result:
                    url_contents.append(result)
        
        # Calculate and log content statistics
        total_words = sum(content.get("word_count", 0) for content in url_contents)
        github_words = sum(content.get("word_count", 0) for content in url_contents if content.get("source_type", "").startswith("github"))
        web_words = total_words - github_words
        
        logger.info(f"📊 Content Extraction Summary:")
        logger.info(f"   Total sources processed: {len(url_contents)}")
        logger.info(f"   GitHub API content: {len([c for c in url_contents if c.get('source_type', '').startswith('github')])} items ({github_words:,} words)")
        logger.info(f"   Web scraped content: {len([c for c in url_contents if not c.get('source_type', '').startswith('github')])} items ({web_words:,} words)")
        logger.info(f"   Total words collected: {total_words:,}")
        
        return url_contents
        return url_contents
    
    def chunk_text(self, text: str, max_length: int = 1000, overlap: int = 100) -> List[str]:
        """Split text into overlapping chunks."""
        sentences = sent_tokenize(text)
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            if len(current_chunk) + len(sentence) < max_length:
                current_chunk += " " + sentence if current_chunk else sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence
        
        # Add the last chunk
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # Add overlap between chunks
        overlapped_chunks = []
        for i, chunk in enumerate(chunks):
            if i > 0 and overlap > 0:
                # Add overlap from previous chunk
                prev_words = chunks[i-1].split()[-overlap//10:]  # Rough word-based overlap
                overlap_text = " ".join(prev_words)
                chunk = overlap_text + " " + chunk
            overlapped_chunks.append(chunk)
        
        return overlapped_chunks
    
    def process_url_contents(self, url_contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process URL contents into chunks with metadata."""
        processed_chunks = []
        
        for url_content in url_contents:
            # Split content into chunks
            text_chunks = self.chunk_text(url_content["content"])
            
            for i, chunk in enumerate(text_chunks):
                processed_chunks.append({
                    "id": f"url_{hash(url_content['url'])}_{i}",
                    "content": chunk,
                    "metadata": {
                        "source_type": "external_url",
                        "url": url_content["url"],
                        "title": url_content["title"],
                        "chunk_index": i,
                        "total_chunks": len(text_chunks),
                        "word_count": len(chunk.split()),
                        "fetch_time": url_content["fetch_time"]
                    }
                })
        
        return processed_chunks
    
    def load_existing_chunks(self) -> List[Dict[str, Any]]:
        """Load existing chunks from JSON file."""
        chunks_file = self.knowledge_base_dir / "chunks.json"
        if chunks_file.exists():
            with open(chunks_file, 'r') as f:
                chunks = json.load(f)
            logger.info(f"Loaded {len(chunks)} existing chunks")
            return chunks
        else:
            logger.info("No existing chunks found")
            return []
    
    def generate_embeddings(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate embeddings for all chunks."""
        logger.info(f"Generating embeddings for {len(chunks)} chunks...")
        
        # Extract text content
        texts = [chunk["content"] for chunk in chunks]
        
        # Generate embeddings in batches
        batch_size = 32
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            embeddings = self.model.encode(batch)
            all_embeddings.extend(embeddings)
            logger.info(f"Processed batch {i//batch_size + 1}/{(len(texts) + batch_size - 1)//batch_size}")
        
        # Add embeddings to chunks
        for chunk, embedding in zip(chunks, all_embeddings):
            chunk["embedding"] = embedding.tolist()
        
        logger.info("Embedding generation complete")
        return chunks
    
    def store_in_chromadb(self, chunks: List[Dict[str, Any]]) -> None:
        """Store chunks with embeddings in ChromaDB."""
        logger.info(f"Storing {len(chunks)} chunks in ChromaDB...")
        
        # Prepare data for ChromaDB
        ids = [chunk["id"] for chunk in chunks]
        documents = [chunk["content"] for chunk in chunks]
        embeddings = [chunk["embedding"] for chunk in chunks]
        
        # Sanitize metadata for ChromaDB compatibility
        metadatas = []
        for chunk in chunks:
            metadata = chunk.get("metadata", {})
            sanitized_metadata = {}
            for key, value in metadata.items():
                # Only keep scalar values that ChromaDB supports (exclude None)
                if isinstance(value, (str, int, float, bool)) and value is not None:
                    sanitized_metadata[key] = value
                elif isinstance(value, list) and len(value) > 0:
                    # Convert non-empty lists to comma-separated strings
                    sanitized_metadata[key] = ", ".join(str(item) for item in value)
                elif value is not None:
                    # Convert other non-None types to strings
                    sanitized_metadata[key] = str(value)
                # Skip None values and empty lists entirely
            metadatas.append(sanitized_metadata)
        
        # Clear existing collection and add new data
        try:
            self.collection.delete()
        except:
            pass  # Collection might not exist
        
        self.collection = self.chroma_client.get_or_create_collection(
            name="global_workflow_docs",
            metadata={"description": "Global Workflow documentation with external references"}
        )
        
        # Add in batches
        batch_size = 100
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            batch_docs = documents[i:i + batch_size]
            batch_embeddings = embeddings[i:i + batch_size]
            batch_metadatas = metadatas[i:i + batch_size]
            
            self.collection.add(
                ids=batch_ids,
                documents=batch_docs,
                embeddings=batch_embeddings,
                metadatas=batch_metadatas
            )
            logger.info(f"Stored batch {i//batch_size + 1}/{(len(ids) + batch_size - 1)//batch_size}")
        
        logger.info("ChromaDB storage complete")
    
    def save_enhanced_knowledge_base(self, chunks: List[Dict[str, Any]]) -> None:
        """Save enhanced knowledge base with embeddings."""
        # Save chunks with embeddings
        chunks_file = self.knowledge_base_dir / "chunks_with_embeddings.json"
        with open(chunks_file, 'w') as f:
            json.dump(chunks, f, indent=2)
        
        # Update summary
        summary = {
            "total_chunks": len(chunks),
            "local_chunks": len([c for c in chunks if c.get("metadata", {}).get("source_type") != "external_url"]),
            "external_chunks": len([c for c in chunks if c.get("metadata", {}).get("source_type") == "external_url"]),
            "embedding_model": "all-MiniLM-L6-v2",
            "embedding_dimension": len(chunks[0]["embedding"]) if chunks else 0,
            "generated_at": time.time(),
            "chromadb_enabled": True
        }
        
        summary_file = self.knowledge_base_dir / "summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Enhanced knowledge base saved with {summary['total_chunks']} chunks")
        logger.info(f"  - Local chunks: {summary['local_chunks']}")
        logger.info(f"  - External chunks: {summary['external_chunks']}")
    
    async def generate_complete_knowledge_base(self) -> None:
        """Generate complete knowledge base with embeddings and URL content."""
        logger.info("Starting complete knowledge base generation...")
        
        # Step 1: Load existing local chunks
        local_chunks = self.load_existing_chunks()
        
        # Step 2: Fetch external URL content
        logger.info("Fetching external URL content...")
        url_contents = await self.fetch_all_urls()
        
        # Step 3: Process URL content into chunks
        external_chunks = self.process_url_contents(url_contents)
        
        # Step 4: Combine all chunks
        all_chunks = local_chunks + external_chunks
        logger.info(f"Total chunks to process: {len(all_chunks)}")
        
        # Step 5: Generate embeddings
        chunks_with_embeddings = self.generate_embeddings(all_chunks)
        
        # Step 6: Store in ChromaDB
        self.store_in_chromadb(chunks_with_embeddings)
        
        # Step 7: Save enhanced knowledge base
        self.save_enhanced_knowledge_base(chunks_with_embeddings)
        
        logger.info("Complete knowledge base generation finished!")

async def main():
    """Main function to run the enhanced vector generation."""
    try:
        generator = EnhancedVectorGenerator()
        await generator.generate_complete_knowledge_base()
        
        print("\n🎉 Enhanced RAG Knowledge Base Complete!")
        print("✅ Local content processed")
        print("✅ External URLs fetched and processed")
        print("✅ Vector embeddings generated")
        print("✅ ChromaDB storage configured")
        print("\nNext steps:")
        print("1. Update MCP server to use ChromaDB for semantic search")
        print("2. Test semantic search functionality")
        print("3. Verify VS Code integration")
        
    except Exception as e:
        logger.error(f"Failed to generate enhanced knowledge base: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
