# MCP Server Setup for Global Workflow

This repository now includes Model Context Protocol (MCP) server configurations to provide enhanced context to GitHub Copilot and other AI tools.

## Available MCP Servers

### 1. Python MCP Server
- **File**: `mcp-server.py`
- **Requirements**: Python 3.8+
- **Usage**: Provides workflow structure, job listing, and configuration information

### 2. Node.js MCP Server  
- **File**: `mcp-server.js`
- **Requirements**: Node.js 18+, npm
- **Usage**: Enhanced workflow context with detailed component explanations

## Setup Instructions

### For Python MCP Server

1. Ensure Python 3.8+ is installed
2. The server is ready to run: `python3 mcp-server.py`

### For Node.js MCP Server

1. Install Node.js 18+ and npm
2. Install dependencies:
   ```bash
   npm install
   ```
3. Start the server:
   ```bash
   npm start
   ```

## VS Code Integration

The MCP server configuration is included in `.vscode/settings.json`. To enable MCP integration:

1. Install the MCP extension for VS Code (if available)
2. Restart VS Code
3. The server should automatically connect and provide enhanced context

## Available Tools

Both servers provide these tools:

- **get_workflow_info/get_workflow_structure**: Overview of the global workflow system
- **list_job_scripts**: List all available job scripts
- **get_config_info/get_system_configs**: System-specific configuration information
- **explain_workflow_component**: Detailed component explanations (Node.js version)

## Usage with GitHub Copilot

Once configured, the MCP server will provide GitHub Copilot with contextual information about:

- Workflow job scripts and their purposes
- System configurations for different HPC platforms
- Component relationships and dependencies
- Best practices for global workflow development

## Testing the Server

You can test the MCP server manually:

```bash
# Python version
echo '{"method": "tools/list", "id": 1}' | python3 mcp-server.py

# Node.js version  
echo '{"method": "tools/list", "id": 1}' | node mcp-server.js
```

## Troubleshooting

- Ensure proper file permissions (scripts should be executable)
- Check that required runtime (Python 3.8+ or Node.js 18+) is installed
- Verify VS Code MCP extension is properly configured
- Check VS Code output panel for MCP server logs
