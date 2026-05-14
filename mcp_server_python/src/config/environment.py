"""Environment configuration loader for the MCP server.

Single point of truth for environment variables consumed by the Python
MCP server. Mirrors ``mcp_server_node/src/config/environment.js`` but
adds the ``DB_BACKEND`` routing knob described in Requirement 1.8.

Phase C-2c (Bedrock-native embedding swap) adds the
``MCP_EMBEDDING_PROFILE`` env var (Requirement 7). The value is
validated against
:meth:`src.data.embedding_registry.EmbeddingModelRegistry.list_profiles`
and surfaces as :pyattr:`ServerConfig.embedding_profile`. Selecting
``mpnet768`` emits a one-shot ``[WARN]`` log line (Requirement 7.4)
calling out that the legacy parity-debug fallback is active and that
sentence-transformers is not installed in the runtime image.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from .aws_config import DEFAULT_AWS_REGION, DEFAULT_HOST, DEFAULT_PORT

log = logging.getLogger(__name__)

# Modules that can be selectively enabled via ``MCP_ENABLED_MODULES`` or the
# ``--modules`` CLI flag (Requirement 18.3). Kept here rather than in
# ``mcp_server.py`` so tests can introspect the canonical list without
# importing FastMCP.
KNOWN_MODULES: tuple[str, ...] = (
    "semantic_search",
    "code_analysis",
    "graph_rag",
    "ee2_compliance",
    "operational",
    "sdd_workflow",
    "workflow_info",
    "github_tools",
    "utility",
)

VALID_BACKENDS: tuple[str, ...] = ("aws", "legacy")


@dataclass(frozen=True)
class ServerConfig:
    """Immutable snapshot of MCP server environment configuration.

    Attributes
    ----------
    db_backend
        Either ``"aws"`` (Neptune + OpenSearch) or ``"legacy"``
        (Neo4j + ChromaDB). Routes to the appropriate adapter in
        ``src.data.backend_selector``.
    neptune_endpoint
        Neptune HTTPS / wss endpoint. Required when ``db_backend == "aws"``.
        Empty string is permitted in ``legacy`` mode.
    opensearch_endpoint
        OpenSearch HTTPS endpoint. Required when ``db_backend == "aws"``.
    aws_region
        AWS region used for SigV4 signing. Defaults to ``us-east-1``.
    embedding_profile
        Active embedding-model alias resolved from
        ``MCP_EMBEDDING_PROFILE`` (Requirement 7). Defaults to
        ``"titan1024"`` (the Phase 52 production target).
    github_token
        Optional token for the GitHubTools module (Requirement 11.4).
        ``None`` disables the module in degraded mode.
    sdd_state_dir
        Path to the SDD execution-state directory (Requirement 9.5).
    host / port
        Address for FastMCP's Streamable HTTP listener (Requirement 1.1).
    enabled_modules
        Whitelist of tool modules to register. Empty tuple means "all".
    neo4j_uri / neo4j_user / neo4j_password / chromadb_host / chromadb_port
        Legacy-backend connection parameters, only relevant when
        ``db_backend == "legacy"``.
    """

    db_backend: str = "aws"
    neptune_endpoint: str = ""
    opensearch_endpoint: str = ""
    aws_region: str = DEFAULT_AWS_REGION
    embedding_profile: str = "titan1024"
    github_token: str | None = None
    sdd_state_dir: str = "sdd_framework/execution_state"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    enabled_modules: tuple[str, ...] = field(default_factory=tuple)
    # Legacy-only (ignored in aws mode):
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    chromadb_host: str = "localhost"
    chromadb_port: int = 8080

    # ── helpers ────────────────────────────────────────────────────────────

    def is_aws(self) -> bool:
        """Return True when the AWS backend is selected."""
        return self.db_backend == "aws"

    def is_legacy(self) -> bool:
        """Return True when the legacy (Docker-based) backend is selected."""
        return self.db_backend == "legacy"

    def module_enabled(self, module_name: str) -> bool:
        """Return True if *module_name* should be registered.

        An empty ``enabled_modules`` tuple means "register everything",
        matching the Node.js default in ``UnifiedMCPServer.js``.
        """
        if not self.enabled_modules:
            return True
        return module_name in self.enabled_modules


class ConfigError(ValueError):
    """Raised when environment configuration is invalid."""


def _parse_port(raw: str | None, default: int) -> int:
    """Parse an integer port, raising ``ConfigError`` on bad input."""
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"PORT must be an integer, got {raw!r}") from exc
    if not 1 <= value <= 65535:
        raise ConfigError(f"PORT out of range: {value}")
    return value


def _parse_modules(raw: str | None) -> tuple[str, ...]:
    """Parse a comma-separated module list and validate against the allowlist.

    Empty / missing input returns an empty tuple (meaning "all modules").
    """
    if not raw:
        return ()
    names = tuple(name.strip() for name in raw.split(",") if name.strip())
    unknown = [n for n in names if n not in KNOWN_MODULES]
    if unknown:
        raise ConfigError(
            f"Unknown module(s) in MCP_ENABLED_MODULES: {unknown}. "
            f"Known: {list(KNOWN_MODULES)}"
        )
    return names


# ── MCP_EMBEDDING_PROFILE parsing (Requirement 7) ───────────────────────


# Module-level guard so the ``mpnet768`` warn line emits at most once
# per process even if ``load_config`` is called repeatedly (e.g. by
# tests that explicitly pass ``env=...``). Reset by tests via the
# ``_reset_embedding_warn`` helper below.
_MPNET_WARN_EMITTED: bool = False


def _reset_embedding_warn() -> None:
    """Reset the one-shot ``mpnet768`` warn guard.

    Test-only helper; production code never calls this.
    """
    global _MPNET_WARN_EMITTED
    _MPNET_WARN_EMITTED = False


def _parse_embedding_profile(raw: str | None) -> str:
    """Resolve ``MCP_EMBEDDING_PROFILE`` against the registry.

    Defaults to ``"titan1024"`` when unset; raises :class:`ConfigError`
    listing the six accepted profile names when set to anything not
    registered with :class:`EmbeddingModelRegistry` (Requirement 7.3).
    """
    # Late import keeps ``environment.py`` importable in test contexts
    # that don't want to pull in the registry (e.g. config-only tests).
    from src.data.embedding_registry import EmbeddingModelRegistry

    accepted = EmbeddingModelRegistry().list_profiles()
    if not raw:
        return "titan1024"
    value = raw.strip()
    if value not in accepted:
        raise ConfigError(
            f"MCP_EMBEDDING_PROFILE must be one of {accepted}, got {value!r}"
        )
    return value


def _maybe_emit_mpnet_warn(profile: str) -> None:
    """Emit the one-shot ``[WARN]`` log line on ``mpnet768``
    (Requirement 7.4).

    Guarded by :data:`_MPNET_WARN_EMITTED` so the line is emitted at
    most once per process — repeated ``load_config`` calls are safe.
    """
    global _MPNET_WARN_EMITTED
    if profile != "mpnet768" or _MPNET_WARN_EMITTED:
        return
    log.warning(
        "[WARN] MCP_EMBEDDING_PROFILE=mpnet768 — legacy parity-debug "
        "fallback active; sentence-transformers is not installed in "
        "this image"
    )
    _MPNET_WARN_EMITTED = True


def load_config(
    env: dict[str, str] | None = None,
    *,
    enabled_modules: tuple[str, ...] | None = None,
) -> ServerConfig:
    """Build a :class:`ServerConfig` from environment variables.

    Parameters
    ----------
    env
        Optional mapping used in place of ``os.environ``. Simplifies
        unit testing without mutating the real environment.
    enabled_modules
        Optional override for the module whitelist. When provided,
        takes precedence over the ``MCP_ENABLED_MODULES`` env var.
        Used by the ``--modules`` CLI flag.

    Raises
    ------
    ConfigError
        If ``DB_BACKEND`` is unknown, ``PORT`` is not parseable, or a
        ``MCP_ENABLED_MODULES`` entry is not in :data:`KNOWN_MODULES`.
    """
    source = env if env is not None else os.environ

    backend = (source.get("DB_BACKEND") or "aws").strip().lower()
    if backend not in VALID_BACKENDS:
        raise ConfigError(
            f"DB_BACKEND must be one of {VALID_BACKENDS}, got {backend!r}"
        )

    # Parse + validate the embedding profile *before* the warn line so a
    # ``ConfigError`` short-circuits the process before any warn fires
    # (Requirement 7.4 — guard against unrelated warn noise on bad input).
    embedding_profile = _parse_embedding_profile(source.get("MCP_EMBEDDING_PROFILE"))
    _maybe_emit_mpnet_warn(embedding_profile)

    modules = (
        enabled_modules
        if enabled_modules is not None
        else _parse_modules(source.get("MCP_ENABLED_MODULES"))
    )

    return ServerConfig(
        db_backend=backend,
        neptune_endpoint=source.get("NEPTUNE_ENDPOINT", "").strip(),
        opensearch_endpoint=source.get("OPENSEARCH_ENDPOINT", "").strip(),
        aws_region=source.get("AWS_REGION", DEFAULT_AWS_REGION).strip()
        or DEFAULT_AWS_REGION,
        embedding_profile=embedding_profile,
        github_token=(source.get("GITHUB_TOKEN") or None),
        sdd_state_dir=source.get("SDD_STATE_DIR", "sdd_framework/execution_state"),
        host=source.get("HOST", DEFAULT_HOST).strip() or DEFAULT_HOST,
        port=_parse_port(source.get("PORT"), DEFAULT_PORT),
        enabled_modules=modules,
        neo4j_uri=source.get("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=source.get("NEO4J_USER", "neo4j"),
        neo4j_password=source.get("NEO4J_PASSWORD", ""),
        chromadb_host=source.get("CHROMADB_HOST", "localhost"),
        chromadb_port=_parse_port(source.get("CHROMADB_PORT"), 8080),
    )
