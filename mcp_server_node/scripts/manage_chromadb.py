#!/usr/bin/env python3
"""
ChromaDB Collection Management Utility

Provides operations for managing ChromaDB collections:
- List all collections with document counts
- Delete specific collections
- Clear collection contents
- Show collection metadata
"""

import sys
import argparse
from datetime import datetime
import chromadb
from chromadb.config import Settings


def connect_chromadb(host='localhost', port=8080):
    """Connect to ChromaDB"""
    try:
        client = chromadb.HttpClient(host=host, port=port)
        # Test connection
        client.heartbeat()
        return client
    except Exception as e:
        print(f"[ERROR] Failed to connect to ChromaDB at {host}:{port}")
        print(f"        {e}")
        sys.exit(1)


def list_collections(client):
    """List all collections with statistics"""
    collections = client.list_collections()
    
    if not collections:
        print("No collections found")
        return
    
    print(f"\nChromaDB Collections ({len(collections)} total)")
    print("="*70)
    
    for coll in sorted(collections, key=lambda c: c.name):
        count = coll.count()
        
        # Try to get sample metadata
        try:
            if count > 0:
                result = coll.peek(limit=1)
                if result['metadatas']:
                    metadata = result['metadatas'][0]
                    version = metadata.get('version', 'unknown')
                    source = metadata.get('source', 'unknown')
                    print(f"\n  {coll.name}")
                    print(f"    Documents: {count}")
                    print(f"    Version: {version}")
                    print(f"    Sample source: {source}")
                else:
                    print(f"\n  {coll.name}")
                    print(f"    Documents: {count}")
            else:
                print(f"\n  {coll.name}")
                print(f"    Documents: 0 (empty)")
        except:
            print(f"\n  {coll.name}")
            print(f"    Documents: {count}")
    
    print("\n" + "="*70)


def delete_collection(client, name):
    """Delete a collection"""
    try:
        # Check if exists
        collections = client.list_collections()
        if not any(c.name == name for c in collections):
            print(f"[ERROR] Collection '{name}' does not exist")
            return False
        
        # Confirm deletion
        print(f"[WARN] About to delete collection: {name}")
        response = input("Type 'yes' to confirm deletion: ")
        
        if response.lower() != 'yes':
            print("[INFO] Deletion cancelled")
            return False
        
        client.delete_collection(name)
        print(f"[OK] Deleted collection: {name}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Failed to delete collection: {e}")
        return False


def clear_collection(client, name):
    """Clear all documents from a collection (keeps collection)"""
    try:
        collection = client.get_collection(name)
        count = collection.count()
        
        if count == 0:
            print(f"[INFO] Collection '{name}' is already empty")
            return True
        
        print(f"[WARN] About to clear {count} documents from: {name}")
        response = input("Type 'yes' to confirm: ")
        
        if response.lower() != 'yes':
            print("[INFO] Clear cancelled")
            return False
        
        # Get all IDs and delete
        result = collection.get(limit=count)
        if result['ids']:
            collection.delete(ids=result['ids'])
            print(f"[OK] Cleared {len(result['ids'])} documents from: {name}")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Failed to clear collection: {e}")
        return False


def show_collection_info(client, name):
    """Show detailed information about a collection"""
    try:
        collection = client.get_collection(name)
        count = collection.count()
        
        print(f"\nCollection: {name}")
        print("="*70)
        print(f"Total documents: {count}")
        
        if count == 0:
            print("(empty collection)")
            return
        
        # Get sample documents
        result = collection.peek(limit=5)
        
        print(f"\nSample metadata (first 5 docs):")
        print("-"*70)
        
        for i, metadata in enumerate(result['metadatas'][:5], 1):
            print(f"\n  Document {i}:")
            for key, value in sorted(metadata.items()):
                if isinstance(value, str) and len(value) > 60:
                    value = value[:60] + "..."
                print(f"    {key}: {value}")
        
        # Analyze metadata fields
        all_keys = set()
        for metadata in result['metadatas']:
            all_keys.update(metadata.keys())
        
        print(f"\n\nMetadata fields present:")
        print("-"*70)
        for key in sorted(all_keys):
            print(f"  - {key}")
        
        print("\n" + "="*70)
        
    except Exception as e:
        print(f"[ERROR] Failed to get collection info: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Manage ChromaDB collections',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all collections
  python3 manage_chromadb.py list

  # Show detailed info for a collection
  python3 manage_chromadb.py info global-workflow-docs-v4-2-0-unified

  # Delete a collection
  python3 manage_chromadb.py delete global-workflow-docs-v4-1-0-enhanced

  # Clear collection contents (keep collection)
  python3 manage_chromadb.py clear global-workflow-docs-v4-1-0-enhanced
        """
    )
    
    parser.add_argument(
        'action',
        choices=['list', 'delete', 'clear', 'info'],
        help='Action to perform'
    )
    parser.add_argument(
        'collection',
        nargs='?',
        help='Collection name (required for delete, clear, info)'
    )
    parser.add_argument(
        '--host',
        default='localhost',
        help='ChromaDB host (default: localhost)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8080,
        help='ChromaDB port (default: 8080)'
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.action in ['delete', 'clear', 'info'] and not args.collection:
        parser.error(f"'{args.action}' requires a collection name")
    
    # Connect to ChromaDB
    print(f"[INFO] Connecting to ChromaDB at {args.host}:{args.port}...")
    client = connect_chromadb(args.host, args.port)
    print("[OK] Connected\n")
    
    # Perform action
    if args.action == 'list':
        list_collections(client)
    elif args.action == 'delete':
        delete_collection(client, args.collection)
    elif args.action == 'clear':
        clear_collection(client, args.collection)
    elif args.action == 'info':
        show_collection_info(client, args.collection)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
