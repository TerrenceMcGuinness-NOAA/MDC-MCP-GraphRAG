# Dockerfile.agentcore — MDC MCP RAG Server for Bedrock AgentCore Runtime
# ARM64 container for AgentCore MCP protocol deployment.
#
# Build:  docker build -t mdc-mcp-rag:agentcore -f Dockerfile.agentcore .
# Test:   docker run -p 8000:8000 mdc-mcp-rag:agentcore
# Health: curl http://localhost:8000/ping

FROM node:20-slim

# sharp native module needs build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 make g++ && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install production dependencies (sharp needs scripts to build native bindings)
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

# Copy server source
COPY src/ ./src/
COPY utils/ ./utils/
COPY config/ ./config/

# Runtime environment
ENV NODE_ENV=production \
    DB_BACKEND=aws \
    AWS_REGION=us-east-1 \
    MCP_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD node -e "fetch('http://localhost:8000/ping').then(r=>r.ok?process.exit(0):process.exit(1)).catch(()=>process.exit(1))"

CMD ["node", "src/mcp-agentcore-entrypoint.js"]
