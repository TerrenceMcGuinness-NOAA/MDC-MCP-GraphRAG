#!/usr/bin/env python3
"""
Load knowledge base data into ChromaDB
"""

import json
import chromadb
import sys
from tqdm import tqdm

def load_data_to_chromadb():
    try:
        # Connect to ChromaDB server
        client = chromadb.HttpClient(host='localhost', port=8000)
        print('✅ Connected to ChromaDB server')
        
        # Get or create collection
        collection = client.get_or_create_collection('global-workflow-docs')
        print(f'📚 Collection created/accessed: {collection.name}')
        
        # Load chunks with embeddings
        print('📖 Loading chunks with embeddings...')
        with open('chunks_with_embeddings.json', 'r') as f:
            chunks_data = json.load(f)
        
        print(f'📊 Found {len(chunks_data)} chunks to load')
        
        # Prepare data for ChromaDB
        documents = []
        embeddings = []
        metadatas = []
        ids = []
        
        for i, chunk in enumerate(tqdm(chunks_data, desc="Processing chunks")):
            if chunk.get('embedding') and len(chunk['embedding']) > 0:
                documents.append(chunk['content'])
                embeddings.append(chunk['embedding'])
                metadatas.append({
                    'source': chunk.get('metadata', {}).get('source', 'unknown'),
                    'type': chunk.get('metadata', {}).get('type', 'unknown'),
                    'extension': chunk.get('metadata', {}).get('extension', 'unknown'),
                    'chunk_index': i
                })
                ids.append(f'chunk_{i}')
        
        print(f'🎯 Prepared {len(documents)} valid chunks for upload')
        
        # Batch upload to ChromaDB (ChromaDB has a limit on batch size)
        batch_size = 100
        total_batches = (len(documents) + batch_size - 1) // batch_size
        
        for i in tqdm(range(0, len(documents), batch_size), desc="Uploading batches", total=total_batches):
            end_idx = min(i + batch_size, len(documents))
            
            batch_docs = documents[i:end_idx]
            batch_embeddings = embeddings[i:end_idx]
            batch_metadatas = metadatas[i:end_idx]
            batch_ids = ids[i:end_idx]
            
            try:
                collection.add(
                    documents=batch_docs,
                    embeddings=batch_embeddings,
                    metadatas=batch_metadatas,
                    ids=batch_ids
                )
            except Exception as e:
                print(f'⚠️ Error uploading batch {i//batch_size + 1}: {e}')
                continue
        
        # Verify upload
        final_count = collection.count()
        print(f'✅ Upload complete! Collection now has {final_count} documents')
        
        # Test a sample query
        print('🔍 Testing sample query...')
        results = collection.query(
            query_texts=["workflow configuration"],
            n_results=3
        )
        
        print(f'📋 Sample query returned {len(results["documents"][0])} results')
        for i, doc in enumerate(results["documents"][0]):
            print(f'  {i+1}. {doc[:100]}...')
        
        return True
        
    except Exception as e:
        print(f'❌ Error loading data to ChromaDB: {e}')
        return False

if __name__ == "__main__":
    success = load_data_to_chromadb()
    sys.exit(0 if success else 1)
