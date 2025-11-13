#!/usr/bin/env python3
"""
Test ChromaDB database and RAG embeddings accessibility
"""
import chromadb
from chromadb.config import Settings

def test_chromadb():
    """Test ChromaDB database access and collections"""
    
    print("Testing ChromaDB database access...")
    print(f"ChromaDB version: {chromadb.__version__}")
    print()
    
    # Connect to the persistent database
    db_path = "./knowledge-base/chroma_db"
    print(f"Database path: {db_path}")
    
    try:
        # Use PersistentClient for local database access
        client = chromadb.PersistentClient(path=db_path)
        print("✓ Successfully connected to ChromaDB database")
        print()
        
        # List all collections
        collections = client.list_collections()
        print(f"Found {len(collections)} collection(s):")
        
        for collection in collections:
            print(f"\n  Collection: {collection.name}")
            print(f"  ID: {collection.id}")
            
            # Get collection metadata and count
            count = collection.count()
            print(f"  Document count: {count}")
            
            if count > 0:
                # Get a sample of documents
                results = collection.peek(limit=3)
                print(f"  Sample documents:")
                
                if results and 'ids' in results:
                    for i, doc_id in enumerate(results['ids'][:3]):
                        print(f"    - ID: {doc_id}")
                        if 'metadatas' in results and results['metadatas'] and i < len(results['metadatas']):
                            metadata = results['metadatas'][i]
                            if metadata:
                                print(f"      Metadata keys: {list(metadata.keys())}")
                                # Show source if available
                                if 'source' in metadata:
                                    print(f"      Source: {metadata['source']}")
                        
                        if 'documents' in results and results['documents'] and i < len(results['documents']):
                            doc_text = results['documents'][i]
                            if doc_text:
                                preview = doc_text[:100] + "..." if len(doc_text) > 100 else doc_text
                                print(f"      Text preview: {preview}")
        
        print("\n" + "="*60)
        print("✓ ChromaDB database is accessible and contains RAG embeddings")
        print("="*60)
        
        return True
        
    except Exception as e:
        print(f"✗ Error accessing ChromaDB database: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_chromadb()
    exit(0 if success else 1)
