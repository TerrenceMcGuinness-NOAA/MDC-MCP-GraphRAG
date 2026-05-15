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

# Non-root user per AgentCore guidance.
#
# Phase C-1 hot-fix (Issue B from
# docs/reports/2026-05-14-phase-c1-parity-assessment.md):
# `WORKDIR /app` (above) creates `/app` owned by root. The runtime user
# `app` then cannot write to `/app` itself — only to files copied with
# `--chown=app:app`. That blocks `SessionManager._ensure_state_dir()`
# from creating `/app/sdd_framework/execution_state/`, which causes
# `graph_rag` and `sdd_workflow` register() calls to raise
# PermissionError and surface as failed module registration on the
# AgentCore container. The `chown -R app:app /app` line below makes
# the WORKDIR fully writable for the runtime user, so all 9 modules
# register cleanly. See `[8.22.1]` in CHANGELOG.md and the
# Post-Fix Status section of the C-1 assessment.
RUN groupadd --system --gid 1000 app \
 && useradd  --system --uid 1000 --gid app --home /app app \
 && chown -R app:app /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl \
 && rm -rf /wheels

COPY --chown=app:app src ./src
COPY --chown=app:app pyproject.toml ./

USER app
EXPOSE 8000

# Streamable HTTP entrypoint (Requirement 1.1).
#
# Phase B11 deployment — feature-parity milestone. All 9 tool
# modules are now ported (51 tools total: 4 + 7 + 6 + 9 + 5 + 4 +
# 9 + 3 + 4 across utility, semantic_search, code_analysis,
# graph_rag, ee2_compliance, operational, sdd_workflow,
# workflow_info, and github_tools). Per-module degraded-mode
# behaviour:
#
#   * utility, sdd_workflow, workflow_info — fully data-access-free;
#     work with no Neptune/OpenSearch reachable.
#   * semantic_search, code_analysis, graph_rag, ee2_compliance,
#     operational — register successfully without the data layer
#     and return [ERROR] markdown at call time when the layer is
#     missing.
#   * github_tools — also data-access-free; needs GITHUB_TOKEN at
#     call time. Registration always succeeds; tool calls return
#     "GitHub integration not available - no API access" when the
#     token is unset.
#
# CMD lists all 9 modules explicitly so Docker history records the
# full surface area; --modules can still be overridden at run time
# for per-module deploy slices.
CMD ["python", "-m", "src.mcp_server", "--modules", "utility,semantic_search,code_analysis,graph_rag,ee2_compliance,operational,sdd_workflow,workflow_info,github_tools"]
