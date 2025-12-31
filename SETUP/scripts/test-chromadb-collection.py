#!/usr/bin/env python3
"""
Quick test to create Global-Workflow collection in ChromaDB 1.1.1
and add some sample documents for LangFlow testing

NOTE: ChromaDB 1.1.1 uses API v2 by default
      Client API is compatible with 0.4.x but has new features
"""

import chromadb
from chromadb.config import Settings

print("🔗 Connecting to ChromaDB 1.1.1...")

# Connect to ChromaDB (API v1/v2 auto-negotiation)
client = chromadb.HttpClient(
    host="localhost",
    port=8080,
    settings=Settings(anonymized_telemetry=False)
)

print(f"✅ Connected to ChromaDB")
print(f"   Version: {client.heartbeat()} (heartbeat timestamp)")
print(f"   Server: http://localhost:8080")

# Create or get collection
collection = client.get_or_create_collection(
    name="Global-Workflow",
    metadata={"description": "NOAA Global Workflow System Documentation"}
)

print(f"✅ Collection 'Global-Workflow' ready (count: {collection.count()})")

# Add sample documents if collection is empty
if collection.count() == 0:
    print("📝 Adding sample workflow documents...")
    
    sample_docs = [
        {
            "id": "doc1",
            "text": "The Global Forecast System (GFS) is a weather forecast model produced by NOAA. It provides deterministic forecasts out to 16 days with updates every 6 hours at 00Z, 06Z, 12Z, and 18Z.",
            "metadata": {"type": "system_overview", "component": "GFS"}
        },
        {
            "id": "doc2",
            "text": "The Global Data Assimilation System (GDAS) is responsible for ingesting observations from satellites, radiosondes, aircraft, and surface stations. It performs quality control and generates analysis fields.",
            "metadata": {"type": "system_overview", "component": "GDAS"}
        },
        {
            "id": "doc3",
            "text": "The workflow uses Rocoto as the workflow manager. Jobs are defined in jobs/ directory, execution scripts in scripts/, and utilities in ush/. The system supports multiple HPC platforms including WCOSS2, Hera, and Orion.",
            "metadata": {"type": "architecture", "component": "workflow"}
        },
        {
            "id": "doc4",
            "text": "ChromaDB is used as the vector database for the RAG system. It runs on port 8080 and stores embeddings for semantic search across workflow documentation.",
            "metadata": {"type": "infrastructure", "component": "RAG"}
        },
        {
            "id": "doc5",
            "text": "The MCP (Model Context Protocol) server provides 17 tools for workflow management, including tools for workflow structure queries, RAG semantic search, and GitHub repository integration.",
            "metadata": {"type": "infrastructure", "component": "MCP"}
        }
    ]
    
    collection.add(
        ids=[doc["id"] for doc in sample_docs],
        documents=[doc["text"] for doc in sample_docs],
        metadatas=[doc["metadata"] for doc in sample_docs]
    )
    
    print(f"✅ Added {len(sample_docs)} documents")
else:
    print(f"ℹ️  Collection already has {collection.count()} documents")

# Test query
print("\n🔍 Testing semantic search for 'weather forecast'...")
results = collection.query(
    query_texts=["weather forecast"],
    n_results=2
)

print(f"✅ Found {len(results['ids'][0])} results:")
for i, (doc_id, document, distance) in enumerate(zip(
    results['ids'][0],
    results['documents'][0],
    results['distances'][0]
), 1):
    print(f"\n{i}. ID: {doc_id} (distance: {distance:.3f})")
    print(f"   {document[:100]}...")

print("\n✅ ChromaDB is ready for LangFlow!")
print("   Collection: Global-Workflow")
print(f"   Documents: {collection.count()}")
print("   You can now use the Search Query in LangFlow")
