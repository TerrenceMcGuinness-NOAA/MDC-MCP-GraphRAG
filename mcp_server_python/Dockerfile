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
# Phase B10b deployment: boot with utility + semantic_search +
# code_analysis + graph_rag + ee2_compliance + operational +
# sdd_workflow + workflow_info modules registered (4 + 7 + 6 + 9 + 5
# + 4 + 9 + 3 = 47 tools). The workflow_info module is intentionally
# lightweight — pure-filesystem reads, no Neptune / OpenSearch
# dependency. Catalogue tools (get_workflow_structure /
# get_system_configs / describe_component) read the global-workflow
# tree at MCP_WORKFLOW_ROOT (or HOMEgfs, or
# supported_repos/global-workflow). On the AgentCore microVM where
# that tree is not bind-mounted, get_workflow_structure still works
# (the structure dict is fully static); the other two surface
# helpful "file not found" + content-parameter hints. sdd_workflow
# module retains the same data-access-free contract from B10a.
CMD ["python", "-m", "src.mcp_server", "--modules", "utility,semantic_search,code_analysis,graph_rag,ee2_compliance,operational,sdd_workflow,workflow_info"]
