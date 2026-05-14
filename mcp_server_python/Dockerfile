# syntax=docker/dockerfile:1.7
#
# Dockerfile — MDC MCP/RAG Python Server (AgentCore Runtime, ARM64)
#
# Multi-stage build keeps the final image minimal. Listens on 0.0.0.0:8000
# per Requirement 1.1 (Streamable HTTP MCP endpoint).

ARG PYTHON_VERSION=3.12

# ── Stage 1: build dependencies ─────────────────────────────────────────────
FROM --platform=linux/arm64 python:${PYTHON_VERSION}-slim AS builder

WORKDIR /build

# Install build tools required by optional C extensions
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip wheel \
 && pip wheel --no-cache-dir --wheel-dir /wheels .


# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM --platform=linux/arm64 python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0

WORKDIR /app

# Non-root user per AgentCore guidance
RUN groupadd --system --gid 1000 app \
 && useradd  --system --uid 1000 --gid app --home /app app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl \
 && rm -rf /wheels

COPY --chown=app:app src ./src
COPY --chown=app:app pyproject.toml ./

USER app
EXPOSE 8000

# Streamable HTTP entrypoint (Requirement 1.1).
# Phase B10 deployment: boot with utility + semantic_search + code_analysis
# + graph_rag + ee2_compliance + operational + sdd_workflow modules
# registered (4 + 7 + 6 + 9 + 5 + 4 + 9 = 44 tools). The sdd_workflow
# module is data-access-free — its session lifecycle tools delegate to
# the file-backed SessionManager (state under sdd_framework/execution_state)
# and validate_sdd_compliance is pure-content. The workflow catalogue
# tools (list_sdd_workflows / get_sdd_workflow) read from
# sdd_framework/workflows/ on disk; on the AgentCore microVM where that
# tree is not bind-mounted they degrade with an [INFO] block. Operational
# module retains the same content-abstraction contract from B9.
CMD ["python", "-m", "src.mcp_server", "--modules", "utility,semantic_search,code_analysis,graph_rag,ee2_compliance,operational,sdd_workflow"]
