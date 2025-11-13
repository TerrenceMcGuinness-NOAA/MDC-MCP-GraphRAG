# RAG-Enhanced MCP Server for Global Workflow

This directory contains the Retrieval-Augmented Generation (RAG) enhanced Model Context Protocol (MCP) server for the Global Workflow project. The RAG system enables semantic search and intelligent explanations of workflow documentation and code.

## Overview

The RAG system provides two implementations:

1. **Simple RAG Server** (`simple-rag-server.js`) - Basic text search without vector embeddings
2. **Full RAG Server** (`mcp-server-rag.js`) - Advanced vector-based semantic search (requires ChromaDB)

## Quick Start

### 1. Install Dependencies

```bash
npm install
```

### 2. Create Knowledge Base

Run the simple document processor to create a basic knowledge base:

```bash
node simple-processor.js
```

This will:
- Scan the Global Workflow repository
- Process up to 50 documents for testing
- Create chunks of documentation and code
- Save the knowledge base to `./simple-knowledge-base/`

### 3. Start the RAG Server

```bash
node simple-rag-server.js
```

The server will load the knowledge base and start listening for MCP requests.

## Available Tools

### search_documentation
Search through Global Workflow documentation and code using keyword matching.

**Parameters:**
- `query` (string, required): Search query
- `max_results` (number, default: 5): Maximum results to return

**Example:**
```json
{
  "query": "workflow job configuration",
  "max_results": 3
}
```

### explain_component
Get detailed explanation of a workflow component with examples.

**Parameters:**
- `component` (string, required): Component name to explain
- `include_examples` (boolean, default: true): Include code examples

**Example:**
```json
{
  "component": "rocoto",
  "include_examples": true
}
```

### list_workflow_jobs
List available workflow jobs and scripts.

**Parameters:**
- `filter_type` (enum): "all", "jobs", "scripts", "configs" (default: "all")

### get_knowledge_stats
Get statistics about the loaded knowledge base.

### get_documentation_references
Get reference URLs for external documentation and resources.

**Parameters:**
- `category` (enum): "all", "internal", "external", "ufs", "rocoto", "gsi", "hpc_systems", "noaa_tools", "standards" (default: "all")
- `format` (enum): "detailed", "urls_only", "structured" (default: "detailed")

**Example:**
```json
{
  "category": "ufs",
  "format": "detailed"
}
```

## Architecture

### Simple RAG Implementation

The simple RAG server uses basic text search and keyword matching:

1. **Document Processing**: Scans repository for supported file types
2. **Chunking**: Splits large documents into manageable chunks
3. **Indexing**: Creates JSON-based index for fast lookup
4. **Search**: Uses keyword matching with scoring

### Full RAG Implementation (Advanced)

The full RAG server includes vector-based semantic search:

1. **Embedding Generation**: Uses sentence-transformers for text embeddings
2. **Vector Database**: ChromaDB for similarity search
3. **Semantic Search**: Finds semantically similar content
4. **Context-Aware Responses**: Enhanced explanations with retrieved context

## File Structure

```
mcp_server_node/
├── package.json                     # Dependencies and configuration
├── documentation-references.json    # Reference URLs for external docs
├── simple-processor.js              # Basic document processor
├── simple-rag-server.js             # Simple RAG MCP server
├── document-ingester.js             # Advanced document processor (WIP)
├── mcp-server-rag.js               # Full RAG MCP server (WIP)
├── test-rag.js                     # Test script
└── simple-knowledge-base/           # Generated knowledge base
    ├── chunks.json                  # Document chunks
    ├── documents.json               # Document metadata
    └── summary.json                 # Knowledge base statistics
```

## Configuration

### Document Processing Configuration

The processors can be configured by modifying the `config` object:

```javascript
this.config = {
  supportedExtensions: ['.md', '.txt', '.py', '.sh', '.yml', '.yaml', '.json', '.xml', '.cmake', '.rst'],
  excludePatterns: ['node_modules', '.git', '__pycache__', '.vscode', 'build', 'dist'],
  chunkSize: 1000,
  maxFiles: 50  // For testing; remove for full processing
};
```

### Documentation References Configuration

Reference URLs for external documentation are stored in `documentation-references.json`:

```json
{
  "documentation_references": {
    "internal": {
      "global_workflow": {
        "base_url": "https://github.com/TerrenceMcGuinness-NOAA/global-workflow",
        "docs_path": "/docs/source",
        "wiki_url": "https://github.com/TerrenceMcGuinness-NOAA/global-workflow/wiki"
      }
    },
    "external": {
      "ufs": {
        "documentation": "https://ufs-weather-model.readthedocs.io/",
        "github": "https://github.com/ufs-community/ufs-weather-model",
        "user_guide": "https://ufs-weather-model.readthedocs.io/en/latest/"
      },
      "rocoto": {
        "documentation": "https://christopherwharrop-noaa.github.io/rocoto/",
        "github": "https://github.com/christopherwharrop-NOAA/rocoto"
      }
    },
    "standards_and_policies": {
      "environmental_equivalence": {
        "ee2_standards": "https://nws-hpc-standards.readthedocs.io/en/latest/index.html",
      }
    }
  }
}
```

**Categories Available:**
- **internal**: Global Workflow project documentation
- **external.ufs**: UFS Weather Model documentation
- **external.rocoto**: Rocoto workflow manager documentation
- **external.gsi**: GSI data assimilation system documentation
- **external.hpc_systems**: NOAA HPC system documentation (Hera, Orion, Hercules, WCOSS2)
- **external.noaa_tools**: NOAA libraries and tools (NCEPLIBS, UPP, wgrib2)
- **standards_and_policies**: NOAA coding standards and operational procedures including EE2 compliance report

**Managing References:**
- Edit `documentation-references.json` to add/update URLs
- Use the `get_documentation_references` tool to retrieve URLs programmatically
- URLs are validated periodically (configurable in metadata section)
- Priority scoring available for search ranking

### Vector Database Configuration (Advanced)

For the full RAG implementation:

```javascript
// ChromaDB configuration
this.chromaClient = new ChromaClient({
  host: process.env.CHROMA_HOST || 'localhost',
  port: process.env.CHROMA_PORT || 8000
});
```

## Development Status

### ✅ Completed
- [x] Basic document processing pipeline
- [x] Simple text-based search
- [x] MCP server integration
- [x] Knowledge base generation
- [x] Basic RAG tools (search, explain, list, stats)

### 🔄 In Progress
- [ ] Vector embedding generation
- [ ] ChromaDB integration
- [ ] Semantic similarity search
- [ ] Advanced context-aware explanations

### 📋 Planned
- [ ] Full repository ingestion (remove file limits)
- [ ] Improved chunking strategies
- [ ] Code-specific search tools
- [ ] Dependency analysis tools
- [ ] Operational guidance tools

## Testing

### Basic Test

```bash
node test-rag.js
```

### Manual Testing

1. Start the server: `node simple-rag-server.js`
2. Use an MCP client to send tool requests
3. Test with queries like:
   - "rocoto workflow"
   - "job configuration"
   - "python scripts"

### Knowledge Base Verification

Check the generated knowledge base:

```bash
# View summary
cat simple-knowledge-base/summary.json

# Check chunk count
jq '.length' simple-knowledge-base/chunks.json

# View document types
jq 'group_by(.type) | map({type: .[0].type, count: length})' simple-knowledge-base/documents.json
```

## Advanced Setup (Vector Database)

To use the full RAG implementation with vector search:

### 1. Install ChromaDB

```bash
pip install chromadb
# Start ChromaDB server
chroma run --host localhost --port 8000
```

### 2. Generate Full Knowledge Base

```bash
# Process entire repository (may take several minutes)
node document-ingester.js
```

### 3. Start Full RAG Server

```bash
node mcp-server-rag.js
```

## Troubleshooting

### Common Issues

1. **"Knowledge base not loaded"**
   - Run `node simple-processor.js` first
   - Check that `simple-knowledge-base/` directory exists

2. **"Module not found" errors**
   - Run `npm install` to install dependencies
   - Ensure Node.js version 18+ is installed

3. **Vector database connection errors**
   - Start ChromaDB server: `chroma run --host localhost --port 8000`
   - Check network connectivity
   - Verify ChromaDB installation

4. **Embedding model download fails**
   - Ensure internet connectivity
   - Check HuggingFace model availability
   - Consider using local models

### Performance Notes

- The simple processor limits to 50 files for testing
- Full repository processing may take 10-30 minutes
- Vector embedding generation requires significant CPU/memory
- Consider processing subsets for development

## Integration with Copilot

This RAG server can be integrated with GitHub Copilot through the MCP protocol to provide:

- Intelligent code suggestions based on Global Workflow patterns
- Context-aware explanations of workflow components
- Smart search across documentation and configurations
- Automated discovery of related code and documentation

## Contributing

To extend the RAG functionality:

1. Add new tools to the `setupTools()` method
2. Implement corresponding handlers in `setupHandlers()`
3. Test with the provided test scripts
4. Update documentation

For vector database features:
1. Implement embedding generation in `document-ingester.js`
2. Add semantic search capabilities
3. Enhance context retrieval and ranking
4. Test with ChromaDB integration

## License

This RAG enhancement follows the same license as the Global Workflow project.
