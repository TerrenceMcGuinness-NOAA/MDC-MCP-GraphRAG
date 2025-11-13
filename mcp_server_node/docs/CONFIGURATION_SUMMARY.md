# MCP Server Configuration Summary

## Overview

The Global Workflow MCP server now supports **configurable Hugging Face integration**. The system has been reorganized to separate core functionality from optional enhancements.

## Directory Structure

```
mcp_server_node/
├── start-mcp-server-node.sh           # Main startup script (configurable)
├── mcp-config.env                     # Configuration file
├── mcp-server.js                      # Basic MCP server
├── mcp-server-rag.js                  # Standard RAG server (default)
├── package.json                       # Core dependencies
├── vscode/
│   └── mcp.json                       # VS Code MCP configuration
└── hf_integration/                    # Optional HF integration
    ├── mcp-server-enhanced-rag.js     # HF-enhanced server
    ├── huggingface-mcp-bridge.js      # HF integration bridge
    ├── config/huggingface.json        # HF configuration
    ├── package.json                   # HF-specific dependencies
    ├── README.md                      # HF integration documentation
    ├── run-hf-integration.sh          # HF integration runner
    ├── verify-integration.sh          # HF integration verification
    └── test-*.js                      # HF integration tests
```

## Configuration Options

### Method 1: Environment Variable
```bash
# Enable HF integration
ENABLE_HF_INTEGRATION=true ./start-mcp-server-node.sh

# Use standard RAG only  
ENABLE_HF_INTEGRATION=false ./start-mcp-server-node.sh
```

### Method 2: Configuration File
Edit `mcp-config.env`:
```bash
# Set to 'true' to enable HF integration
ENABLE_HF_INTEGRATION=true
```

### Method 3: Default Behavior
- **Default**: Uses standard RAG server (`mcp-server-rag.js`)
- **No HF dependencies required** for basic operation
- **Optional enhancement** when needed

## Server Selection Logic

1. **HF Integration Disabled** (default):
   - Uses `mcp-server-rag.js` (standard RAG server)
   - Local ChromaDB + basic MCP tools
   - No external dependencies

2. **HF Integration Enabled**:
   - First looks for `hf_integration/mcp-server-enhanced-rag.js`
   - Falls back to `mcp-server-rag.js` if enhanced server not found
   - Provides HF model/paper/dataset discovery when available

## Benefits of This Architecture

### ✅ **Separation of Concerns**
- Core functionality separate from optional enhancements
- Clear distinction between basic and enhanced features
- Easier maintenance and testing

### ✅ **Optional Dependencies**
- HF integration is truly optional
- Basic system works without HF components
- No breaking changes for existing users

### ✅ **Configurable Behavior**
- Easy to enable/disable HF integration
- Environment variable or config file options
- Clear documentation of choices

### ✅ **Production Ready**
- Graceful fallbacks if components missing
- Comprehensive error handling
- Clear logging of configuration choices

## Usage Examples

### Basic Usage (Standard RAG)
```bash
./start-mcp-server-node.sh
# Uses mcp-server-rag.js with local ChromaDB
```

### Enhanced Usage (With HF Integration)
```bash
ENABLE_HF_INTEGRATION=true ./start-mcp-server-node.sh
# Uses enhanced server with HF capabilities
```

### Testing
```bash
# Test standard configuration
./start-mcp-server-node.sh test

# Test with HF integration
ENABLE_HF_INTEGRATION=true ./start-mcp-server-node.sh test
```

### HF Integration Development/Testing
```bash
cd hf_integration
./run-hf-integration.sh          # Interactive HF integration tests
./verify-integration.sh          # Comprehensive verification
npm run test                     # Basic HF tests
npm run test-complete            # Full test suite
```

## Key Changes Made

1. **Renamed** `demo/` → `hf_integration/` for clarity
2. **Removed** redundant files from main directory
3. **Added** configurable HF integration toggle
4. **Created** `mcp-config.env` for easy configuration
5. **Updated** start script with intelligent server selection
6. **Maintained** backward compatibility with existing setups

## Migration Path

- **Existing users**: No changes needed - continues using standard RAG server
- **HF integration users**: Set `ENABLE_HF_INTEGRATION=true` to access enhanced features
- **Developers**: Use `hf_integration/` directory for HF-related development

## Status

✅ **Ready for Production**
- Both standard and enhanced servers tested
- Configurable integration working
- Clear separation of optional components
- Comprehensive documentation
