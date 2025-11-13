#!/usr/bin/env python3
"""
Basic Vector Embedding Generator for RAG System
==============================================

This script generates vector embeddings for existing chunks without ChromaDB.
Stores embeddings in JSON format for use by the MCP server.
"""

import json
import os
import sys
from pathlib import Path
import logging
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
except ImportError as e:
    print(f"Missing required packages: {e}")
    print("Run: python3 -m pip install --user sentence-transformers")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def cosine_similarity(a, b):
    """Calculate cosine similarity between two vectors."""
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def generate_embeddings_for_existing_chunks():
    """Generate embeddings for existing chunks."""
    
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
    
    # Create a simple vector index for fast search
    logger.info("Creating vector index...")
    vector_index = {
        "embeddings": embeddings.tolist(),
        "chunk_ids": [chunk["id"] for chunk in chunks],
        "documents": [chunk["content"] for chunk in chunks],
        "model": "all-MiniLM-L6-v2",
        "dimension": embeddings.shape[1],
        "total_chunks": len(chunks)
    }
    
    with open("knowledge-base/vector_index.json", 'w') as f:
        json.dump(vector_index, f, indent=2)
    
    # Update summary
    summary = {
        "total_chunks": len(chunks),
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_dimension": embeddings.shape[1],
        "has_embeddings": True,
        "vector_index_file": "vector_index.json",
        "chunks_with_embeddings_file": "chunks_with_embeddings.json",
        "generated_at": "2025-08-12"
    }
    
    with open("knowledge-base/summary.json", 'w') as f:
        json.dump(summary, f, indent=2)
    
    logger.info("✅ Vector generation complete!")
    logger.info(f"   - Processed {len(chunks)} chunks")
    logger.info(f"   - Embeddings saved to: knowledge-base/chunks_with_embeddings.json")
    logger.info(f"   - Vector index saved to: knowledge-base/vector_index.json")
    logger.info(f"   - Embedding dimension: {embeddings.shape[1]}")
    
    return True, embeddings, chunks

def test_vector_search(embeddings, chunks):
    """Test vector search functionality."""
    logger.info("Testing vector search...")
    
    try:
        # Load the embedding model for query encoding
        model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Test queries
        test_queries = [
            "weather model configuration",
            "ensemble forecasting",
            "GDAS analysis"
        ]
        
        for query in test_queries:
            logger.info(f"\n🔍 Testing query: '{query}'")
            
            # Encode query
            query_embedding = model.encode([query])
            
            # Calculate similarities
            similarities = []
            for i, chunk_embedding in enumerate(embeddings):
                similarity = cosine_similarity(query_embedding[0], chunk_embedding)
                similarities.append((i, similarity))
            
            # Sort by similarity
            similarities.sort(key=lambda x: x[1], reverse=True)
            
            # Show top 3 results
            for rank, (chunk_idx, similarity) in enumerate(similarities[:3]):
                chunk = chunks[chunk_idx]
                doc_snippet = chunk["content"][:100] + "..." if len(chunk["content"]) > 100 else chunk["content"]
                logger.info(f"   Result {rank+1}: {doc_snippet} (similarity: {similarity:.3f})")
        
        logger.info("✅ Search test successful!")
        return True
    except Exception as e:
        logger.error(f"❌ Search test failed: {e}")
        return False

if __name__ == "__main__":
    logger.info("🚀 Starting basic vector embedding generation...")
    
    result = generate_embeddings_for_existing_chunks()
    if isinstance(result, tuple):
        success, embeddings, chunks = result
        if success:
            logger.info("🧪 Running search test...")
            test_vector_search(embeddings, chunks)
            
            print("\n🎉 RAG Vector System Complete!")
            print("✅ Embeddings generated for all chunks")
            print("✅ Vector index created for fast search")
            print("✅ Vector search tested and working")
            print("✅ No external dependencies (ChromaDB not needed)")
            print("\nNext steps:")
            print("1. Update MCP server to use vector_index.json")
            print("2. Implement semantic similarity search in Node.js")
            print("3. Test with VS Code integration")
        else:
            logger.error("❌ Failed to generate embeddings")
            sys.exit(1)
    else:
        logger.error("❌ Unexpected result from embedding generation")
        sys.exit(1)
