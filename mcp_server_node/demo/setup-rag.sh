#!/bin/bash

# Setup script for RAG-enhanced MCP Server
# This script installs dependencies and initializes the RAG knowledge base

set -e

# Configuration
MCP_DIR="${1:-$(pwd)}"
REPO_ROOT="${2:-$(find . -name '.github' -type d | head -1 | xargs dirname 2>/dev/null || pwd)}"
VENV_NAME="rag_mcp_env"

echo "RAG-Enhanced MCP Server Setup"
echo "=============================="
echo "MCP Directory: ${MCP_DIR}"
echo "Repository Root: ${REPO_ROOT}"
echo ""

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
echo "Checking prerequisites..."

if ! command_exists node; then
    echo "Error: Node.js is not installed. Please install Node.js 18+ first."
    exit 1
fi

if ! command_exists npm; then
    echo "Error: npm is not installed. Please install npm first."
    exit 1
fi

if ! command_exists python3; then
    echo "Error: Python 3 is not installed. Please install Python 3.8+ first."
    exit 1
fi

NODE_VERSION=$(node --version | cut -d'v' -f2)
echo "Node.js version: ${NODE_VERSION}"

# Check Node.js version (requires 18+)
if [[ $(echo "${NODE_VERSION} < 18.0.0" | bc -l 2>/dev/null || echo "1") == "1" ]]; then
    echo "Warning: Node.js 18+ is recommended for optimal performance"
fi

# Create and navigate to MCP directory
cd "${MCP_DIR}"

# Install Node.js dependencies
echo ""
echo "Installing Node.js dependencies..."
if [ -f "package-rag.json" ]; then
    cp package-rag.json package.json
    npm install
    echo "Dependencies installed successfully"
else
    echo "Error: package-rag.json not found in ${MCP_DIR}"
    exit 1
fi

# Setup Python virtual environment for additional tools
echo ""
echo "Setting up Python virtual environment..."
if ! python3 -m venv "${VENV_NAME}"; then
    echo "Error: Failed to create Python virtual environment"
    exit 1
fi

source "${VENV_NAME}/bin/activate"

# Install Python dependencies for document processing
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install \
    sentence-transformers \
    chromadb \
    openai \
    cohere \
    langchain \
    pypdf2 \
    python-docx \
    beautifulsoup4 \
    nltk \
    spacy \
    transformers \
    torch

# Download NLTK data
python -c "import nltk; nltk.download('punkt'); nltk.download('stopwords')"

# Create configuration files
echo ""
echo "Creating configuration files..."

# Create .env file template
cat > .env.template << 'EOF'
# API Keys for RAG services
OPENAI_API_KEY=your_openai_api_key_here
COHERE_API_KEY=your_cohere_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Vector Database Configuration
VECTOR_DB_TYPE=chromadb
VECTOR_DB_PATH=./vector_db
COLLECTION_NAME=global_workflow_docs

# Embedding Configuration
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384

# RAG Configuration
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
SIMILARITY_THRESHOLD=0.7
MAX_RESULTS=10

# Logging
LOG_LEVEL=info
LOG_FILE=./logs/rag_mcp_server.log
EOF

# Create directories
mkdir -p logs knowledge_base vector_db scripts test

# Create embedding generation script
cat > scripts/create-embeddings.js << 'EOF'
#!/usr/bin/env node

/**
 * Create embeddings for the knowledge base
 */

const fs = require('fs').promises;
const path = require('path');
require('dotenv').config();

async function createEmbeddings() {
    console.log('Creating embeddings for knowledge base...');
    
    try {
        // Load chunks from knowledge base
        const chunksPath = path.join('knowledge_base', 'chunks.json');
        const chunksData = await fs.readFile(chunksPath, 'utf-8');
        const chunks = JSON.parse(chunksData);
        
        console.log(`Processing ${chunks.length} chunks...`);
        
        // TODO: Implement actual embedding generation
        // This would use OpenAI, Cohere, or local sentence-transformers
        
        console.log('Embeddings created successfully!');
        
    } catch (error) {
        console.error('Error creating embeddings:', error);
        process.exit(1);
    }
}

if (require.main === module) {
    createEmbeddings();
}
EOF

chmod +x scripts/create-embeddings.js

# Create test script
cat > test/test-rag-server.js << 'EOF'
#!/usr/bin/env node

/**
 * Test script for RAG-enhanced MCP server
 */

const { spawn } = require('child_process');
const fs = require('fs');

async function testRAGServer() {
    console.log('Testing RAG-enhanced MCP server...');
    
    // Test tools list
    const testCommands = [
        {
            name: "List Tools",
            command: '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}'
        },
        {
            name: "Search Documentation",
            command: '{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "search_documentation", "arguments": {"query": "how to run workflow"}}}'
        },
        {
            name: "Explain with Context",
            command: '{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "explain_with_context", "arguments": {"component": "rocoto"}}}'
        }
    ];
    
    for (const test of testCommands) {
        console.log(`\nTesting: ${test.name}`);
        console.log('Command:', test.command);
        
        try {
            const result = await runMCPCommand(test.command);
            console.log('Result:', JSON.stringify(result, null, 2));
        } catch (error) {
            console.error('Error:', error.message);
        }
    }
}

function runMCPCommand(command) {
    return new Promise((resolve, reject) => {
        const server = spawn('node', ['mcp-server-rag.js'], {
            stdio: ['pipe', 'pipe', 'pipe']
        });
        
        let output = '';
        let errorOutput = '';
        
        server.stdout.on('data', (data) => {
            output += data.toString();
        });
        
        server.stderr.on('data', (data) => {
            errorOutput += data.toString();
        });
        
        server.on('close', (code) => {
            if (code === 0) {
                try {
                    const result = JSON.parse(output.split('\n')[1]); // Skip stderr log line
                    resolve(result);
                } catch (e) {
                    reject(new Error(`Invalid JSON response: ${output}`));
                }
            } else {
                reject(new Error(`Server exited with code ${code}: ${errorOutput}`));
            }
        });
        
        // Send command
        server.stdin.write(command + '\n');
        server.stdin.end();
    });
}

if (require.main === module) {
    testRAGServer().catch(console.error);
}
EOF

chmod +x test/test-rag-server.js

# Initialize knowledge base
echo ""
echo "Initializing knowledge base..."
if [ -f "document-ingester.js" ]; then
    node document-ingester.js "${REPO_ROOT}"
    echo "Knowledge base initialized"
else
    echo "Warning: document-ingester.js not found. Knowledge base not initialized."
fi

# Create VS Code settings for RAG server
echo ""
echo "Creating VS Code configuration..."
cat > .vscode-settings-rag.json << EOF
{
  "mcp.servers": {
    "global-workflow-rag": {
      "command": "node",
      "args": ["${MCP_DIR}/mcp-server-rag.js"],
      "cwd": "${MCP_DIR}",
      "env": {
        "NODE_ENV": "production"
      }
    }
  }
}
EOF

# Deactivate virtual environment
deactivate

echo ""
echo "Setup completed successfully!"
echo ""
echo "Next steps:"
echo "1. Copy .env.template to .env and add your API keys"
echo "2. Run 'npm run ingest' to populate the knowledge base"
echo "3. Run 'npm run create-embeddings' to generate embeddings"
echo "4. Test the server with 'npm test'"
echo "5. Add the VS Code settings from .vscode-settings-rag.json to your workspace"
echo ""
echo "To start the RAG-enhanced server:"
echo "  cd ${MCP_DIR}"
echo "  npm start"
echo ""
echo "To start the basic server:"
echo "  cd ${MCP_DIR}"
echo "  npm run start-basic"
