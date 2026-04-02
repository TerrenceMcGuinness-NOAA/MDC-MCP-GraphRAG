# MCP Server Installation Guide

This directory contains the complete MCP (Model Context Protocol) server package for global-workflow repositories.

## Quick Start

### Install MCP Server to a Repository
```bash
./install_MCP.sh install /path/to/your/global-workflow
```

### Remove MCP Server from a Repository
```bash
./install_MCP.sh remove /path/to/your/global-workflow
```

### Check Installation Status
```bash
./install_MCP.sh check /path/to/your/global-workflow
```

### List Available Files
```bash
./install_MCP.sh list
```

## What Gets Installed

- **mcp-server.py** - Python MCP server (lightweight)
- **mcp-server.js** - Node.js MCP server (full-featured)
- **package.json** - Node.js dependencies
- **start-mcp-server.sh** - Server startup script
- **MCP_SERVER_README.md** - Complete documentation
- **test-copilot-integration.py** - Integration test file
- **.vscode/settings.json** - VS Code configuration

## Features

- ✅ **Automatic Backup** - Existing files are backed up before installation
- ✅ **Path Correction** - VS Code settings are updated with correct repository path
- ✅ **Validation** - Checks for valid global-workflow repository structure
- ✅ **Clean Removal** - Complete uninstallation with no leftover files
- ✅ **Status Checking** - Verify what files are installed

## Usage Examples

```bash
# Install to your development repository
./install_MCP.sh install /home/user/global-workflow_dev

# Check what's installed
./install_MCP.sh check /home/user/global-workflow_dev

# Remove everything
./install_MCP.sh remove /home/user/global-workflow_dev

# List all managed files
./install_MCP.sh list
```

## After Installation

1. **Restart VS Code** in the target repository
2. **Test the server**: `cd /target/repo && ./start-mcp-server.sh test`
3. **Read documentation**: `cat MCP_SERVER_README.md`
4. **Test GitHub Copilot** integration with the test file

The MCP server will provide GitHub Copilot with contextual knowledge about:
- Global workflow job scripts and purposes
- System configurations (Hera, Orion, WCOSS2, etc.)
- Component relationships (GSI, UFS, MOM6, etc.)
- Best practices and workflow patterns
