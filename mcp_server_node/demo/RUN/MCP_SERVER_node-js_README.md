# Node.js MCP Server for Global Workflow

This directory contains a standalone Node.js implementation of the Model Context Protocol (MCP) server for the Global Workflow project.

## Overview

This is a separate Node.js MCP server system that provides enhanced context to GitHub Copilot and other AI tools. It complements the Python MCP server with additional features and Node.js-specific functionality.

## Files

- **`mcp-server.js`** - Main Node.js MCP server implementation
- **`package.json`** - Node.js dependencies and project configuration  
- **`package-lock.json`** - Locked dependency versions
- **`node_modules/`** - Installed Node.js dependencies
- **`start-mcp-server-node.sh`** - Startup and testing script

## Requirements

- Node.js 18.0+ (recommended: 22.0+)
- npm (Node Package Manager)

## Quick Start

1. **Test the server:**
   ```bash
   ./start-mcp-server-node.sh test
   ```

2. **Start the server:**
   ```bash
   ./start-mcp-server-node.sh start
   ```

3. **Get help:**
   ```bash
   ./start-mcp-server-node.sh help
   ```

## Available Tools

The Node.js MCP server provides these tools:

- **`get_workflow_structure`** - Get the structure and overview of the global workflow system
- **`list_job_scripts`** - List all available job scripts in the workflow  
- **`get_system_configs`** - Get configuration information for different HPC systems
- **`explain_workflow_component`** - Explain specific workflow components (enhanced feature)

## Testing the Server

You can test the MCP server manually:

```bash
# Test tools list
echo '{"method": "tools/list", "id": 1}' | node mcp-server.js

# Test workflow structure  
echo '{"method": "tools/call", "params": {"name": "get_workflow_structure", "arguments": {}}, "id": 2}' | node mcp-server.js
```

## VS Code Integration

To use this Node.js server with VS Code instead of the Python version:

1. Update `.vscode/settings.json` in your global-workflow repository:
   ```json
   {
     "mcpServers": {
       "global-workflow-node": {
         "command": "/path/to/mcp_server_node/start-mcp-server-node.sh",
         "args": ["start"],
         "cwd": "/path/to/mcp_server_node"
       }
     }
   }
   ```

2. Restart VS Code

## Development

This server is built using the official MCP SDK for Node.js and provides:

- Enhanced component explanations
- Detailed workflow structure information
- System-specific configuration details
- Extensible tool architecture

## Troubleshooting

- Ensure Node.js 18+ is installed
- Verify all dependencies are installed (`npm install` if needed)
- Check that the server starts without errors
- Ensure proper file permissions on scripts

## Comparison with Python Version

| Feature | Python MCP Server | Node.js MCP Server |
|---------|------------------|-------------------|
| Basic workflow info | ✅ | ✅ |
| Job script listing | ✅ | ✅ |
| System configs | ✅ | ✅ |
| Component explanations | ❌ | ✅ Enhanced |
| SDK Integration | Custom | Official MCP SDK |
| Performance | Fast startup | Rich features |

