# ChromaDB 1.3.4 Compatible Image
# Purpose: Match the Python chromadb==1.3.4 version used for data ingestion
# This ensures the Docker container can read existing SQLite data
#
# Build:
#   docker build -t chromadb:1.3.4-compat ./docker/chromadb
#
# Push to GitLab Registry:
#   docker tag chromadb:1.3.4-compat registry.gitlab-licensed.vlab.noaa.gov/nws/operations/ncep/emc/eib/eib-mcp-rag-server/chromadb:1.3.4-compat
#   docker push registry.gitlab-licensed.vlab.noaa.gov/nws/operations/ncep/emc/eib/eib-mcp-rag-server/chromadb:1.3.4-compat

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install exact chromadb version to match ingested data
RUN pip install --no-cache-dir \
    chromadb==1.3.4 \
    uvicorn[standard] \
    fastapi \
    opentelemetry-instrumentation-fastapi \
    opentelemetry-sdk \
    opentelemetry-api

# Create data directory
RUN mkdir -p /data
WORKDIR /data

# Environment variables matching Python chromadb_server.py
ENV CHROMA_SERVER_HOST=0.0.0.0
ENV CHROMA_SERVER_HTTP_PORT=8000
ENV PERSIST_DIRECTORY=/data
ENV IS_PERSISTENT=TRUE
ENV ANONYMIZED_TELEMETRY=FALSE
ENV CHROMA_SERVER_CORS_ALLOW_ORIGINS='["*"]'

# Expose the ChromaDB port
EXPOSE 8000

# Health check using v2 API
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v2/heartbeat || exit 1

# Start ChromaDB server using uvicorn (matches chromadb_server.py approach)
CMD ["python", "-c", "\
import os; \
import uvicorn; \
os.environ['CHROMA_SERVER_HOST'] = '0.0.0.0'; \
os.environ['CHROMA_SERVER_HTTP_PORT'] = '8000'; \
os.environ['PERSIST_DIRECTORY'] = '/data'; \
os.environ['IS_PERSISTENT'] = 'TRUE'; \
uvicorn.run('chromadb.app:app', host='0.0.0.0', port=8000, log_level='info')"]
