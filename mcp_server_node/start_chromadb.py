#!/usr/bin/env python3
"""
Simple ChromaDB server startup script
"""
import os
import sys
from chromadb.config import Settings
from chromadb.server.fastapi import FastAPI
import uvicorn

def start_chromadb_server():
    """Start ChromaDB server on localhost:8000"""
    
    # Set the path to the ChromaDB database
    db_path = "./knowledge-base/chroma_db"
    
    # Ensure the directory exists
    os.makedirs(db_path, exist_ok=True)
    
    print(f"Starting ChromaDB server...")
    print(f"Database path: {os.path.abspath(db_path)}")
    print(f"Server will run on: http://0.0.0.0:8000")
    
    # Configure ChromaDB settings
    settings = Settings(
        chroma_server_host="0.0.0.0",
        chroma_server_http_port=8000,
        persist_directory=db_path,
        chroma_server_cors_allow_origins=["*"]
    )
    
    try:
        # Start the server
        uvicorn.run(
            "chromadb.app:app",
            host="0.0.0.0",
            port=8000,
            log_level="info"
        )
    except Exception as e:
        print(f"Error starting ChromaDB server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    start_chromadb_server()