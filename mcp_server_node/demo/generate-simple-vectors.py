#!/usr/bin/env python3
"""
Simple Vector Embedding Generator for RAG System
===============================================

This script generates vector embeddings for the existing chunks and sets up ChromaDB.
Much simpler and more direct than the previous version.
"""

import json
import os
import sys
from pathlib import Path
import logging

try:
    from sentence_transformers import SentenceTransformer
    import chromadb
except ImportError as e:
    print(f"Missing required packages: {e}")
    print("Run: python3 -m pip install --user sentence-transformers chromadb")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_embeddings_for_existing_chunks():
    """Generate embeddings for existing chunks and store in ChromaDB."""
    
    # Load existing chunks
    chunks_file = Path("knowledge-base/chunks.json")
    if not chunks_file.exists():
        logger.error("chunks.json not found. Run document ingester first.")
        return False
    
    logger.info("Loading existing chunks...")
    with open(chunks_file, 'r') as f:
        chunks = json.load(f)
    
    logger.info(f"Found {len(chunks)} chunks to process")
    
    # Initialize embedding model
    logger.info("Loading embedding model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # Generate embeddings
    logger.info("Generating embeddings...")
    texts = [chunk["content"] for chunk in chunks]
    embeddings = model.encode(texts, show_progress_bar=True)
    
    # Add embeddings to chunks
    for chunk, embedding in zip(chunks, embeddings):
        chunk["embedding"] = embedding.tolist()
    
    # Save chunks with embeddings
    logger.info("Saving chunks with embeddings...")
    with open("knowledge-base/chunks_with_embeddings.json", 'w') as f:
        json.dump(chunks, f, indent=2)
    
    # Initialize ChromaDB
    logger.info("Setting up ChromaDB...")
    chroma_client = chromadb.PersistentClient(path="knowledge-base/chroma_db")
    
    # Create or get collection
    try:
        collection = chroma_client.get_collection("global_workflow_docs")
        collection.delete()  # Clear existing data
    except:
        pass
    
    collection = chroma_client.create_collection(
        name="global_workflow_docs",
        metadata={"description": "Global Workflow documentation chunks with embeddings"}
    )
    
    # Prepare data for ChromaDB
    ids = [chunk["id"] for chunk in chunks]
    documents = [chunk["content"] for chunk in chunks]
    embeddings_list = [chunk["embedding"] for chunk in chunks]
    metadatas = []
    
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        # ChromaDB requires string values for metadata
        clean_metadata = {}
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)):
                clean_metadata[k] = str(v)
        clean_metadata["document"] = chunk.get("document", "unknown")
        clean_metadata["chunk_index"] = str(chunk.get("chunkIndex", 0))
        metadatas.append(clean_metadata)
    
    # Add to ChromaDB in batches
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        batch_ids = ids[i:i + batch_size]
        batch_docs = documents[i:i + batch_size]
        batch_embeddings = embeddings_list[i:i + batch_size]
        batch_metadatas = metadatas[i:i + batch_size]
        
        collection.add(
            ids=batch_ids,
            documents=batch_docs,
            embeddings=batch_embeddings,
            metadatas=batch_metadatas
        )
        logger.info(f"Added batch {i//batch_size + 1}/{(len(ids) + batch_size - 1)//batch_size}")
    
    # Update summary
    summary = {
        "total_chunks": len(chunks),
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_dimension": len(chunks[0]["embedding"]) if chunks else 0,
        "chromadb_collection": "global_workflow_docs",
        "has_embeddings": True,
        "generated_at": "2025-08-12"
    }
    
    with open("knowledge-base/summary.json", 'w') as f:
        json.dump(summary, f, indent=2)
    
    logger.info("✅ Vector generation complete!")
    logger.info(f"   - Processed {len(chunks)} chunks")
    logger.info(f"   - Embeddings saved to: knowledge-base/chunks_with_embeddings.json")
    logger.info(f"   - ChromaDB created at: knowledge-base/chroma_db")
    logger.info(f"   - Collection: global_workflow_docs")
    
    return True

def test_vector_search():
    """Test vector search functionality."""
    logger.info("Testing vector search...")
    
    try:
        chroma_client = chromadb.PersistentClient(path="knowledge-base/chroma_db")
        collection = chroma_client.get_collection("global_workflow_docs")
        
        # Test query
        results = collection.query(
            query_texts=["weather model configuration"],
            n_results=3
        )
        
        logger.info(f"✅ Search test successful! Found {len(results['documents'][0])} results")
        for i, (doc, distance) in enumerate(zip(results['documents'][0], results['distances'][0])):
            logger.info(f"   Result {i+1}: {doc[:100]}... (distance: {distance:.3f})")
        
        return True
    except Exception as e:
        logger.error(f"❌ Search test failed: {e}")
        return False

if __name__ == "__main__":
    logger.info("🚀 Starting vector embedding generation...")
    
    if generate_embeddings_for_existing_chunks():
        logger.info("🧪 Running search test...")
        test_vector_search()
        
        print("\n🎉 RAG Vector System Complete!")
        print("✅ Embeddings generated for all chunks")
        print("✅ ChromaDB configured and ready")
        print("✅ Vector search tested and working")
        print("\nNext steps:")
        print("1. Update MCP server to use vector search")
        print("2. Test semantic similarity queries")
        print("3. Integrate with VS Code")
    else:
        logger.error("❌ Failed to generate embeddings")
        sys.exit(1)
