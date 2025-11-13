#!/bin/bash

# MCP Server Provisioning Script
# Version: 1.0.0
# This script installs all required components for the MCP server with RAG capabilities

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    log_error "Please run as root"
    exit 1
fi

# Step 1: Update system
log_info "Updating system packages..."
dnf update -y

# Step 2: Install system dependencies
log_info "Installing system dependencies..."
dnf install -y \
    gcc-c++ \
    make \
    curl \
    git \
    nodejs \
    npm

# Step 3: Setup Node.js environment
log_info "Setting up Node.js environment..."
# Reset any existing nodejs module
dnf module reset nodejs -y
# Enable and install nodejs 20
dnf module enable nodejs:20 -y
dnf module install nodejs:20 -y
npm install -g npm@latest
hash -r  # Refresh shell PATH

# Step 4: Load Python 3.11 module
log_info "Loading Python 3.11 module..."
# Initialize module system
source /usr/share/Modules/init/bash
# Add the modules path
module use /apps/modules/modulefiles
module load python/3.11

# Step 5: Install Python packages
log_info "Installing Python packages..."
python3.11 -m pip install --upgrade pip
python3.11 -m pip install \
    'sentence-transformers>=2.2.2' \
    'chromadb>=0.4.0' \
    'numpy>=1.21.0' \
    'nltk>=3.8.0' \
    'beautifulsoup4>=4.12.0' \
    'aiohttp>=3.8.0' \
    'requests>=2.28.0' \
    'torch>=2.0.0' \
    'transformers>=4.30.0' \
    'fastapi>=0.100.0' \
    'opentelemetry-instrumentation-fastapi>=0.58b0'

# Step 6: Setup MCP server directory in persistent storage
log_info "Setting up MCP server directory in persistent storage..."
MCP_ROOT="/contrib/Terry.McGuinness/opt/mcp-server"
mkdir -p "${MCP_ROOT}"
mkdir -p "${MCP_ROOT}/knowledge-base"
mkdir -p "${MCP_ROOT}/database"  # Dedicated directory for ChromaDB storage

# Step 7: Configure environment
log_info "Configuring environment..."
cat > /etc/profile.d/mcp-env.sh << 'EOF'
export NODE_ENV=production
export MCP_ROOT=/contrib/Terry.McGuinness/opt/mcp-server
export MCP_KNOWLEDGE_BASE=/contrib/Terry.McGuinness/opt/mcp-server/knowledge-base
export CHROMA_ROOT=/contrib/Terry.McGuinness/opt/mcp-server/database
source /usr/share/Modules/init/bash
module use /apps/modules/modulefiles
module load python/3.11
EOF

# Step 8: Copy MCP server files
log_info "Copying MCP server files..."
cp -r /contrib/Terry.McGuinness/global-workflow_MCP_node.js-RAG/dev/ci/scripts/utils/Copilot/mcp_server_node/* "${MCP_ROOT}/"
chmod +x "${MCP_ROOT}/start-unified-server.sh"

# Step 9: Setup Node.js environment
log_info "Setting up Node.js environment..."
cd "${MCP_ROOT}"

# Create required directories
mkdir -p "${MCP_ROOT}/src"
mkdir -p "${MCP_ROOT}/database"
mkdir -p "${MCP_ROOT}/knowledge-base"
mkdir -p "${MCP_ROOT}/cache"

# Install core dependencies
log_info "Installing core dependencies..."
npm install \
    @modelcontextprotocol/sdk@^1.17.2 \
    @octokit/rest@^22.0.0 \
    @xenova/transformers@^2.15.0 \
    chromadb@^1.8.1

# Install optional dependencies
log_info "Installing optional dependencies..."
npm install \
    cheerio@^1.0.0-rc.12 \
    gray-matter@^4.0.3 \
    pdf-parse@^1.1.1 \
    sharp@^0.34.3

# Install dependencies
npm install \
    @modelcontextprotocol/sdk@^1.17.2 \
    @octokit/rest@^22.0.0 \
    @xenova/transformers@^2.15.0 \
    chromadb@^1.8.1 \
    cheerio@^1.0.0-rc.12 \
    gray-matter@^4.0.3 \
    pdf-parse@^1.1.1 \
    sharp@^0.34.3

# Step 9: Setup ChromaDB
log_info "Setting up ChromaDB..."

# Create Python virtual environment for ChromaDB
python3.11 -m venv /opt/chromadb-env

# Install ChromaDB and dependencies
source /opt/chromadb-env/bin/activate
pip install "chromadb==0.4.15" "fastapi<0.100.0" "uvicorn<0.24.0" "pydantic<2.0.0" "typing-extensions<4.8.0"

# Create data directory
mkdir -p /opt/chroma-data
chown -R Terry.McGuinness:Terry.McGuinness /opt/chroma-data

# Setup ChromaDB service
log_info "Setting up ChromaDB service..."
cat > /etc/systemd/system/chromadb.service << 'EOF'
[Unit]
Description=ChromaDB Service
After=network.target

[Service]
Type=simple
User=Terry.McGuinness
Group=Terry.McGuinness
Environment=TELEMETRY_DISABLED=1
Environment=OTEL_PYTHON_DISABLED=1
Environment=OTEL_SDK_DISABLED=1
Environment=CHROMA_SERVER_HTTP_PORT=8000
Environment=CHROMA_SERVER_HOST=127.0.0.1
Environment=PERSIST_DIRECTORY=/opt/chroma-data
Environment=PATH=/opt/chromadb-env/bin:${PATH}
ExecStart=/opt/chromadb-env/bin/uvicorn chromadb.app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=1

[Install]
WantedBy=multi-user.target
EOF

# Enable and start ChromaDB service
systemctl daemon-reload
systemctl enable chromadb
systemctl start chromadb

# Wait for ChromaDB to start
sleep 5
log_info "Testing ChromaDB connection..."
if curl -s http://127.0.0.1:8000/api/v1/heartbeat > /dev/null; then
    log_success "ChromaDB is running and responding"
else
    log_error "ChromaDB is not responding"
    exit 1
fi
[Unit]
Description=ChromaDB Vector Database Server
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
Environment=PYTHONPATH=/apps/python/3.11/miniforge3/envs/noaa_py3.11/lib/python3.11/site-packages
Environment=PATH=/apps/python/3.11/miniforge3/envs/noaa_py3.11/bin:$PATH
Environment=CHROMA_ROOT=/contrib/Terry.McGuinness/opt/mcp-server/database
Environment=HOME=/contrib/Terry.McGuinness/opt/mcp-server
User=Terry.McGuinness
Group=Terry.McGuinness
WorkingDirectory=/contrib/Terry.McGuinness/opt/mcp-server/database
ExecStart=/apps/python/3.11/miniforge3/envs/noaa_py3.11/bin/python3.11 -m chromadb.app --host 0.0.0.0 --port 8000 --path /contrib/Terry.McGuinness/opt/mcp-server/database
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Step 10: Enable and start ChromaDB service
log_info "Starting ChromaDB service..."
systemctl daemon-reload
systemctl enable chromadb
systemctl start chromadb

# Step 11: Setup MCP server service
log_info "Setting up MCP server service..."
cat > /etc/systemd/system/mcp-server.service << 'EOF'
[Unit]
Description=MCP Server with RAG capabilities
After=network.target chromadb.service

[Service]
Type=simple
User=root
WorkingDirectory=/contrib/Terry.McGuinness/opt/mcp-server
Environment=NODE_ENV=production
Environment=MCP_ROOT=/contrib/Terry.McGuinness/opt/mcp-server
Environment=MCP_KNOWLEDGE_BASE=/contrib/Terry.McGuinness/opt/mcp-server/knowledge-base
Environment=MCP_WORKFLOW_ROOT=/contrib/Terry.McGuinness/global-workflow_MCP_node.js-RAG
Environment=CHROMA_ROOT=/contrib/Terry.McGuinness/opt/mcp-server/database
Environment=TRANSFORMERS_CACHE=/contrib/Terry.McGuinness/opt/mcp-server/cache
Environment=NPM_CONFIG_CACHE=/contrib/Terry.McGuinness/opt/mcp-server/cache/npm
Environment=MCP_HOST=0.0.0.0
Environment=MCP_PORT=3000
Environment=NODE_PATH=/contrib/Terry.McGuinness/opt/mcp-server/node_modules
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/contrib/Terry.McGuinness/opt/mcp-server/node_modules/.bin
ExecStart=/bin/bash /contrib/Terry.McGuinness/opt/mcp-server/start-unified-server.sh --quiet full
WorkingDirectory=/contrib/Terry.McGuinness/opt/mcp-server
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Step 12: Final system setup
log_info "Performing final system setup..."
systemctl daemon-reload
systemctl enable mcp-server

# Step 13: Installation verification
log_info "Verifying installation..."
echo "Node.js version: $(node --version)"
echo "npm version: $(npm --version)"
echo "Python version: $(python3.11 --version)"
echo "pip version: $(pip --version)"

log_success "Installation complete!"
log_info "Please check the following services are running:"
echo "- ChromaDB: systemctl status chromadb"
echo "- MCP Server: systemctl status mcp-server"

log_info "To complete setup:"
echo "1. Copy your MCP server configuration to ${MCP_ROOT}"
echo "2. Initialize your knowledge base in ${MCP_ROOT}/knowledge-base"
echo "3. Start the MCP server: systemctl start mcp-server"
echo "4. Check logs: journalctl -u mcp-server -f"