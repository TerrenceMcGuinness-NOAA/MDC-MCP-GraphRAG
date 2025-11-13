#!/usr/bin/env python3
"""
Local Documentation Ingestion Script - v4.0.0 Upgraded Embeddings
Ingests from local docs/ directory and cached external_documentation_chunks.json
Uses all-mpnet-base-v2 (768-dim) embeddings
"""

import os
import sys
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

# Configuration
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
COLLECTION_NAME = "global-workflow-docs-v4-0-0-mpnet"
EMBEDDING_MODEL = "all-mpnet-base-v2"
VERSION = "4.0.0-mpnet"

# Paths
REPO_ROOT = Path("/mcp_rag_eib/global-workflow_MCP_node.js-RAG")
DOCS_DIR = REPO_ROOT / "docs" / "source"
KNOWLEDGE_BASE = Path("/mcp_rag_eib/mcp_server_node/knowledge-base")
EXTERNAL_CHUNKS = KNOWLEDGE_BASE / "external_documentation_chunks.json"

# ChromaDB config
CHROMADB_HOST = "localhost"
CHROMADB_PORT = 8080

def get_embedding_function():
    """Get upgraded embedding function"""
    # Use persistent disk cache (CACHE_ROOT from mcp-env.sh)
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

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks"""
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end]
        
        if len(chunk.strip()) > 100:  # Minimum chunk size
            chunks.append(chunk)
        
        start += (chunk_size - overlap)
    
    return chunks

def ingest_local_rst_files(collection):
    """Ingest local RST documentation files"""
    print(f"\n📄 Ingesting local RST files from {DOCS_DIR}")
    
    rst_files = list(DOCS_DIR.glob("*.rst"))
    print(f"   Found {len(rst_files)} RST files")
    
    docs = []
    metadatas = []
    ids = []
    
    for rst_file in rst_files:
        try:
            content = rst_file.read_text(encoding='utf-8', errors='ignore')
            chunks = chunk_text(content)
            
            for i, chunk in enumerate(chunks):
                doc_id = hashlib.md5(f"{rst_file.name}-{i}".encode()).hexdigest()
                docs.append(chunk)
                metadatas.append({
                    'source': 'global-workflow-local-docs',
                    'file': rst_file.name,
                    'chunk_index': i,
                    'type': 'rst',
                    'ingestion_date': datetime.now().isoformat()
                })
                ids.append(doc_id)
        
        except Exception as e:
            print(f"   ⚠️  Error processing {rst_file.name}: {e}")
    
    if docs:
        print(f"   Adding {len(docs)} chunks to collection...")
        collection.add(documents=docs, metadatas=metadatas, ids=ids)
        print(f"   ✅ Added {len(docs)} local documentation chunks")
    
    return len(docs)

def ingest_external_chunks(collection):
    """Ingest cached external documentation chunks"""
    print(f"\n📦 Ingesting cached external documentation from {EXTERNAL_CHUNKS}")
    
    if not EXTERNAL_CHUNKS.exists():
        print("   ⚠️  External chunks file not found")
        return 0
    
    try:
        with open(EXTERNAL_CHUNKS, 'r') as f:
            data = json.load(f)
        
        print(f"   Found {len(data)} cached chunks")
        
        docs = []
        metadatas = []
        ids = []
        
        for item in data:
            chunk_text = item.get('text', item.get('content', ''))
            if len(chunk_text.strip()) < 100:
                continue
            
            doc_id = item.get('id', hashlib.md5(chunk_text[:100].encode()).hexdigest())
            docs.append(chunk_text)
            
            metadata = item.get('metadata', {})
            metadata['ingestion_date'] = datetime.now().isoformat()
            metadata['source_type'] = 'external_cached'
            metadatas.append(metadata)
            
            ids.append(doc_id)
        
        if docs:
            print(f"   Adding {len(docs)} chunks to collection...")
            collection.add(documents=docs, metadatas=metadatas, ids=ids)
            print(f"   ✅ Added {len(docs)} external documentation chunks")
        
        return len(docs)
    
    except Exception as e:
        print(f"   ❌ Error loading external chunks: {e}")
        return 0

def main():
    print("=" * 70)
    print("Local Documentation Ingestion - v4.0.0 Upgraded Embeddings")
    print("=" * 70)
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Embedding Model: {EMBEDDING_MODEL} (768 dimensions)")
    print(f"ChromaDB: http://{CHROMADB_HOST}:{CHROMADB_PORT}")
    print("=" * 70)
    
    # Connect to ChromaDB
    client = chromadb.HttpClient(
        host=CHROMADB_HOST,
        port=CHROMADB_PORT,
        settings=Settings(anonymized_telemetry=False)
    )
    
    # Get or create collection
    try:
        collection = client.get_collection(COLLECTION_NAME)
        print(f"\n✅ Using existing collection: {COLLECTION_NAME}")
        print(f"   Current document count: {collection.count()}")
    except:
        print(f"\n📝 Creating new collection: {COLLECTION_NAME}")
        embedding_func = get_embedding_function()
        collection = client.create_collection(
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
        print(f"   ✅ Collection created with {EMBEDDING_MODEL}")
    
    # Ingest local documentation
    local_count = ingest_local_rst_files(collection)
    
    # Ingest cached external documentation
    external_count = ingest_external_chunks(collection)
    
    # Final summary
    final_count = collection.count()
    print("\n" + "=" * 70)
    print("INGESTION COMPLETE")
    print("=" * 70)
    print(f"Local RST files: {local_count} chunks")
    print(f"External cached: {external_count} chunks")
    print(f"Total in collection: {final_count} documents")
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Embedding Model: {EMBEDDING_MODEL} (768 dimensions)")
    print("=" * 70)

if __name__ == "__main__":
    main()
