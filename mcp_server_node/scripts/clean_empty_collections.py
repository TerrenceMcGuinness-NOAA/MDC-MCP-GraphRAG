#!/usr/bin/env python3
"""
Clean Empty ChromaDB Collections

Identifies and removes collections with 0 documents (vestigial tables).
"""

import sys
import requests

CHROMADB_URL = "http://localhost:8080"

def list_collections():
    """List all collections via ChromaDB HTTP API"""
    try:
        # Use v1 list_collections endpoint (still works)
        response = requests.get(f"{CHROMADB_URL}/api/v1/collections")
        if response.status_code == 200:
            data = response.json()
            # Convert to list if it's not already
            if isinstance(data, list):
                return data
            return []
        
        print(f"Error: API returned {response.status_code}")
        print(f"Response: {response.text}")
        return None
    except Exception as e:
        print(f"Error listing collections: {e}")
        return None

def get_collection_count(collection_id):
    """Get document count for a collection"""
    try:
        response = requests.get(f"{CHROMADB_URL}/api/v2/collections/{collection_id}/count")
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"Error getting count: {e}")
        return None

def delete_collection(collection_id):
    """Delete a collection"""
    try:
        response = requests.delete(f"{CHROMADB_URL}/api/v2/collections/{collection_id}")
        return response.status_code in [200, 204]
    except Exception as e:
        print(f"Error deleting collection: {e}")
        return False

def main():
    """Main execution"""
    print("=" * 70)
    print("ChromaDB Collection Cleanup")
    print("=" * 70)
    
    # List collections
    collections = list_collections()
    if not collections:
        print("Could not retrieve collections")
        sys.exit(1)
    
    print(f"\nFound {len(collections)} collections:\n")
    
    empty_collections = []
    
    # Check each collection
    for col in collections:
        col_id = col.get('id')
        col_name = col.get('name')
        
        # Get count
        count_result = get_collection_count(col_id)
        if count_result is not None:
            count = count_result if isinstance(count_result, int) else count_result.get('count', 0)
        else:
            count = -1  # Unknown
        
        status = "EMPTY ❌" if count == 0 else ("OK ✓" if count > 0 else "UNKNOWN ?")
        print(f"{status:12} {col_name:45} {count:6} documents")
        
        if count == 0:
            empty_collections.append((col_id, col_name))
    
    # Offer to delete empty collections
    if empty_collections:
        print(f"\n\nFound {len(empty_collections)} empty collection(s):")
        for col_id, col_name in empty_collections:
            print(f"  - {col_name}")
        
        response = input("\nDelete empty collections? [y/N]: ")
        if response.lower() in ['y', 'yes']:
            print("\nDeleting empty collections...")
            for col_id, col_name in empty_collections:
                if delete_collection(col_id):
                    print(f"  ✓ Deleted: {col_name}")
                else:
                    print(f"  ✗ Failed to delete: {col_name}")
            print("\nCleanup complete!")
        else:
            print("\nNo collections deleted.")
    else:
        print("\n\nNo empty collections found. All collections contain data!")
    
    print("\n" + "=" * 70)

if __name__ == '__main__':
    main()
