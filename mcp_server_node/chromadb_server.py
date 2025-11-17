#!/usr/bin/env python3
"""
Direct ChromaDB server startup using uvicorn
Bypasses the problematic CLI interface
"""
import os
import sys
import uvicorn
from chromadb.config import Settings

def start_server():
    """Start ChromaDB server directly with uvicorn"""
    
    # Set database path from environment or use default
    db_path = os.environ.get('PERSIST_DIRECTORY', '/mcp_rag_eib/data/chromadb')
    server_port = int(os.environ.get('CHROMA_SERVER_HTTP_PORT', '8080'))
    
    print(f"=" * 60)
    print("ChromaDB HTTP Server")
    print("=" * 60)
    print(f"Database path: {db_path}")
    print(f"Server: http://0.0.0.0:{server_port}")
    print(f"Press CTRL+C to stop")
    print("=" * 60)
    print()
    
    # Set environment variables for ChromaDB configuration
    os.environ['CHROMA_SERVER_HOST'] = '0.0.0.0'
    os.environ['CHROMA_SERVER_HTTP_PORT'] = str(server_port)
    os.environ['PERSIST_DIRECTORY'] = db_path
    os.environ['IS_PERSISTENT'] = 'TRUE'
    os.environ['CHROMA_SERVER_CORS_ALLOW_ORIGINS'] = '["*"]'
    
    try:
        # Start uvicorn with chromadb app
        uvicorn.run(
            "chromadb.app:app",
            host="0.0.0.0",
            port=server_port,
            log_level="info",
            access_log=True
        )
    except KeyboardInterrupt:
        print("\n\nServer stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nError starting server: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    start_server()
