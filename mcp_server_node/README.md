# MCP Server Node.js - Organized Directory Structure

This directory contains the Model Context Protocol (MCP) server for the NOAA Global Workflow system with RAG-enhanced capabilities.

## 📁 Directory Organization

### **Root Directory (Essential Files Only)**
- `mcp-server.js` - Basic MCP server implementation
- `mcp-server-rag.js` - RAG-enhanced MCP server (main server)
- `start-mcp-server-node.sh` - Main startup script
- `package.json` - Node.js dependencies
- `package-lock.json` - Dependency lock file
- `package-rag.json` - RAG-specific dependencies
- `mcp-config.env` - Server configuration

### **📂 demo/** - Demonstration and Example Files
- `demo-*.js` - Various demonstration scripts
- `simulate-cursor-usage.js` - Cursor MCP integration demo
- `debug-json.js` - JSON communication debugging
- `list-all-refs.js` - List documentation references
- `show-all-urls.js` - URL listing utilities
- `simple-*.js` - Simple utility scripts
- `document-ingester.js` - Document processing utilities
- `embedding-options-analysis.js` - Embedding analysis
- `*.py` - Python utilities and scripts
- `setup-rag.sh` - RAG setup script
- `install_MCP_node.sh` - Installation script
- `requirements-rag-vectors.txt` - Python requirements
- `*.json` - Data files and configurations
- `RUN/` - Runtime examples

### **📂 test/** - Testing and Validation Files
- `inspect-tools.js` - Tool inspection utility
- `test-*.js` - Test scripts
- `health-check-mcp.sh` - Health check script
- `run-tests.sh` - Test runner
- `validate-urls.js` - URL validation
- `verify-vector-db.js` - Vector database verification
- `tests/` - Test suite directory
- `validation/` - Validation utilities

### **📂 docs/** - Documentation
- `*.md` - All documentation files
- `vscode/` - VSCode configuration files

### **📂 hf_integration/** - Hugging Face Integration
- Hugging Face MCP bridge implementation
- Enhanced RAG server with HF capabilities
- Integration testing and setup

### **📂 knowledge-base/** - Knowledge Base Data
- Vector database files
- Document chunks and embeddings
- Knowledge base summaries

### **📂 simple-knowledge-base/** - Simple Knowledge Base
- Simplified knowledge base implementation
- Basic document processing

## 🚀 Quick Start

### **Start the MCP Server**
```bash
./start-mcp-server-node.sh
```

### **Test the Server**
```bash
cd test
./health-check-mcp.sh
node inspect-tools.js
```

### **Run Demos**
```bash
cd demo
node demo-workflow-structure-complete.js
node simulate-cursor-usage.js
```

## 🔧 Development

### **Adding New Tools**
1. Add tool definition to `mcp-server-rag.js`
2. Implement tool function
3. Add test in `test/` directory
4. Create demo in `demo/` directory

### **Testing**
```bash
cd test
./run-tests.sh
```

### **Documentation**
- Update relevant files in `docs/`
- Add examples to `demo/`

## 📋 Available Tools

### **Core Tools (4)**
- `get_workflow_structure` - System architecture overview
- `list_job_scripts` - Job script inventory
- `get_system_configs` - HPC system configurations
- `explain_component` - Component explanations

### **RAG Tools (5)**
- `search_documentation` - Semantic search
- `explain_with_context` - Contextual explanations
- `find_similar_code` - Code pattern matching
- `get_operational_guidance` - Operational procedures
- `analyze_dependencies` - Dependency analysis

## 🔗 Integration

### **Cursor MCP Integration**
- Server configured in `~/.cursor/mcp.json`
- Automatic startup when tools needed
- Seamless integration with Cursor AI

### **Configuration**
- Main config: `mcp-config.env`
- Server config: `~/.cursor/mcp.json`
- Package config: `package.json`

This organization makes it easy to find what you need and keeps the root directory clean for essential server files only.
