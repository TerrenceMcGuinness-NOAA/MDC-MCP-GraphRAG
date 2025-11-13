# MCP Server Software Catalog

## Core Requirements

### System Level Components
- Node.js >= 18.0.0
- Python >= 3.11.0
- pip >= 23.0.0
- gcc/g++ (for native addon compilation)

### Node.js Dependencies
- @modelcontextprotocol/sdk ^1.17.2
- @octokit/rest ^22.0.0
- @xenova/transformers ^2.15.0
- chromadb ^1.8.1

#### Optional Node.js Dependencies
- cheerio ^1.0.0-rc.12
- gray-matter ^4.0.3
- pdf-parse ^1.1.1
- sharp ^0.34.3

### Python Dependencies (RAG Components)
- sentence-transformers >= 2.2.2
- chromadb >= 0.4.0
- numpy >= 1.21.0
- nltk >= 3.8.0
- beautifulsoup4 >= 4.12.0
- aiohttp >= 3.8.0
- requests >= 2.28.0
- torch >= 2.0.0
- transformers >= 4.30.0

## Infrastructure Components

### Database
- ChromaDB Server (Vector Database)
  - Default configuration:
    - Host: localhost
    - Port: 8000

### Environment Configuration
- NODE_ENV: production
- MCP_KNOWLEDGE_BASE: /path/to/knowledge-base
- MCP_WORKFLOW_ROOT: /path/to/workflow

## Development Tools
- npm >= 8.0.0
- git (latest stable)
- curl or wget (for downloads)

## Optional Components
- Hugging Face Integration Support
  - Requires additional Python packages
  - Controlled via ENABLE_HF_INTEGRATION flag

## Hardware Requirements
- Minimum 16GB RAM (32GB recommended for full RAG functionality)
- 4+ CPU cores
- 50GB+ available disk space for knowledge base and embeddings

## Automated Provisioning

The MCP Server environment can be automatically provisioned using the `provision_mcp_server.sh` script located in `dev/ci/scripts/utils/`. This script handles the complete setup of all required components:

### System Setup
- Updates system packages
- Installs required system dependencies (gcc-c++, make, curl, git)
- Configures Node.js 20 environment
- Loads Python 3.11 module

### Python Environment
- Installs core Python packages with specific version constraints:
  - sentence-transformers >= 2.2.2
  - numpy >= 1.21.0
  - nltk >= 3.8.0
  - beautifulsoup4 >= 4.12.0
  - aiohttp >= 3.8.0
  - requests >= 2.28.0
  - torch >= 2.0.0
  - transformers >= 4.30.0

### ChromaDB Configuration
- Creates dedicated Python virtual environment (/opt/chromadb-env)
- Installs ChromaDB 0.4.15 with specific dependency constraints:
  - fastapi < 0.100.0
  - uvicorn < 0.24.0
  - pydantic < 2.0.0
  - typing-extensions < 4.8.0
- Configures systemd service with:
  - Localhost binding (127.0.0.1:8000)
  - Persistent storage in /opt/chroma-data
  - Telemetry disabled
  - Automatic restart on failure

### Node.js Setup
- Installs core dependencies:
  - @modelcontextprotocol/sdk ^1.17.2
  - @octokit/rest ^22.0.0
  - @xenova/transformers ^2.15.0
  - chromadb ^1.8.1
- Optional dependencies:
  - cheerio ^1.0.0-rc.12
  - gray-matter ^4.0.3
  - pdf-parse ^1.1.1
  - sharp ^0.34.3

### Directory Structure
Creates and configures:
```
/contrib/Terry.McGuinness/opt/mcp-server/
├── knowledge-base/     # Knowledge base storage
├── database/          # ChromaDB storage
├── src/              # Source code
└── cache/            # Cache storage
```

### Environment Configuration
Sets up system-wide environment variables:
- NODE_ENV=production
- MCP_ROOT=/contrib/Terry.McGuinness/opt/mcp-server
- MCP_KNOWLEDGE_BASE=/contrib/Terry.McGuinness/opt/mcp-server/knowledge-base
- CHROMA_ROOT=/contrib/Terry.McGuinness/opt/mcp-server/database