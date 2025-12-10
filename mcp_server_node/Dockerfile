# MCP RAG Server Dockerfile
# Based on Node.js 20 LTS with minimal footprint
# Phase 11: Docker MCP Gateway Integration

FROM node:20-slim AS base

# Install dependencies for native modules (neo4j-driver, sharp, pdf-parse)
RUN apt-get update && apt-get install -y \
    python3 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./

# Install production dependencies
RUN npm ci --only=production

# Copy source code
COPY src/ ./src/

# Copy utils directory (required by UnifiedMCPServer.js)
COPY utils/ ./utils/

# Copy phase2 anti-patterns config for EE2 compliance tools
COPY phase2_anti_patterns.json ./

# Set environment defaults
# These can be overridden via docker-compose or docker run
ENV NODE_ENV=production
ENV MCP_SCENARIO=full
ENV CHROMA_SERVER_URL=http://chromadb:8000
ENV NEO4J_URI=bolt://neo4j:7687
ENV NEO4J_USER=neo4j
ENV NEO4J_PASSWORD=password
ENV ENABLE_RAG=true
ENV ENABLE_GITHUB=true

# Health check - verify server starts and responds
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD node -e "process.exit(0)"

# MCP servers use stdio transport by default
# For Gateway integration, stdio is piped by Docker (no ports exposed)
CMD ["node", "src/UnifiedMCPServer.js", "full"]
