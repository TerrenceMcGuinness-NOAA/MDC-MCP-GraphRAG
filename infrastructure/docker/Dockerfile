# MDC MCP RAG Server — ECS Fargate image
# Runs UnifiedMCPServer.js in 'full' scenario mode (all 51 tools)

FROM node:20-alpine AS deps
WORKDIR /app
COPY mcp_server_node/package*.json ./
RUN npm ci --omit=dev

FROM node:20-alpine
WORKDIR /app

# Copy dependencies and source
COPY --from=deps /app/node_modules ./node_modules
COPY mcp_server_node/src ./src
COPY mcp_server_node/package.json ./

# Non-root user
RUN addgroup -S mcp && adduser -S mcp -G mcp
USER mcp

ENV NODE_ENV=production \
    DB_BACKEND=aws

EXPOSE 3000

# Health check — MCP server responds to a tools/list probe on stdio;
# for HTTP health we rely on the ALB target group health check path /health
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD node -e "process.exit(0)" || exit 1

ENTRYPOINT ["node", "src/UnifiedMCPServer.js", "full"]
