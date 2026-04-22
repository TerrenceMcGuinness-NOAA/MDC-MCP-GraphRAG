# MDC MCP RAG Server — ECS Fargate image
# Runs mcp-http-server.js (Streamable HTTP transport) on port 3000

FROM node:20-slim AS deps
WORKDIR /app
COPY mcp_server_node/package*.json ./
RUN npm ci --omit=dev

FROM node:20-slim
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY mcp_server_node/src ./src
COPY mcp_server_node/package.json ./

RUN groupadd -r mcp && useradd -r -g mcp mcp
USER mcp

ENV NODE_ENV=production \
    DB_BACKEND=aws \
    AWS_REGION=us-east-1

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD node -e "fetch('http://localhost:3000/health').then(r=>r.ok?process.exit(0):process.exit(1)).catch(()=>process.exit(1))"

CMD ["node", "src/mcp-http-server.js", "3000", "full"]
