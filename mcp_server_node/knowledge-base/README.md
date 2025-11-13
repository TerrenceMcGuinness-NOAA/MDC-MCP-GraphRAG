# MCP Knowledge Base Directory

This directory contains the knowledge base data for the MCP (Model Context Protocol) RAG (Retrieval Augmented Generation) system.

## What Gets Committed to Git

**ONLY** small configuration files should be committed:
- `documents.json` - Document references (<10KB)
- `summary.json` - Knowledge base summary (<1KB)  
- `usage_examples.json` - Usage examples (<10KB)
- `load_chromadb.py` - Database loading script
- This `README.md` file

## What is Ignored by Git

**Large generated files** (automatically ignored by `.gitignore`):
- `chunks*.json` - Document chunks (can be >1MB)
- `*enhanced*.json` - Enhanced knowledge base files (can be >50MB)
- `external_*.json` - External documentation chunks (can be >10MB)
- `ingestion_*.json` - Ingestion processing logs (can be >20MB)
- `final_report_*.json` - Processing reports
- `url_validation_*.json` - URL validation reports

**Database and cache directories**:
- `cache/` - Cached web content (can contain 100s of MB)
- `chroma_db/` - Vector database files (binary data, can be >100MB)
- All `*.bin`, `*.pickle`, `*.sqlite3` files

## Regenerating the Knowledge Base

The knowledge base can be regenerated from the source URLs and documentation references using the MCP ingestion scripts. The large files are generated content and should not be committed to version control.

## Usage

The MCP server automatically uses the files in this directory when running. The vector database and cached content will be regenerated as needed.