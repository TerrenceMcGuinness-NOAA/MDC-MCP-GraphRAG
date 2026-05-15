"""Embedding model registry (Phase C-2c, Requirement 1).

Single source of truth for embedding model descriptors used by the
Python MCP server. Mirrors
``mcp_server_node/scripts/embedding_registry.py`` field-for-field —
the on-disk index naming and Phase 52 ingestion already depend on
these exact ``model_id`` / ``provider`` / ``dimensions`` /
``provider_params`` values.

Only one runtime difference from the Node.js port: the **default**
profile is :data:`titan1024` (Bedrock Titan Embed Text V2) rather than
:data:`mpnet768`. The Node.js side does its own embedding for
ingestion and may legitimately default to the local model; the Python
runtime image ships without ``sentence-transformers`` so a Bedrock
default is the only safe choice (Requirement 1.3).

Public surface
--------------

* :class:`ModelProfile` — frozen dataclass describing one model.
* :class:`EmbeddingModelRegistry` — singleton holding the six
  built-in profiles plus any registered at runtime.

Both are imported directly by
:mod:`src.data.embedding_provider`,
:mod:`src.config.environment`, and
:mod:`src.data.opensearch_adapter`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelProfile:
    """Immutable descriptor for a single embedding model.

    Field semantics match
    ``mcp_server_node/scripts/embedding_registry.py``. The dataclass
    is frozen so a registered profile cannot be mutated after the
    fact — callers that need to extend a profile should construct a
    new one and call :pymeth:`EmbeddingModelRegistry.register`.

    Attributes
    ----------
    short_name
        Profile alias used by callers (e.g. ``"titan1024"``).
    provider
        ``"local"`` for sentence-transformers, ``"bedrock"`` for
        AWS Bedrock-Runtime. Consumed by
        :func:`src.data.embedding_provider.create_provider`.
    model_id
        HuggingFace model name (local) or Bedrock ``modelId``
        (bedrock).
    dimensions
        Vector length produced by the model.
    supports_matryoshka
        ``True`` when the model supports configurable output
        dimension via Matryoshka embeddings (the Nova family).
    supports_multimodal
        ``True`` when the model accepts image bytes in addition to
        text.
    provider_params
        Provider-specific request parameters merged into the
        Bedrock body or passed to the local model. Stored as a
        plain dict so frozen-ness is shallow — callers MUST treat
        it as read-only.
    """

    short_name: str
    provider: str
    model_id: str
    dimensions: int
    supports_matryoshka: bool = False
    supports_multimodal: bool = False
    provider_params: dict[str, Any] = field(default_factory=dict)


class EmbeddingModelRegistry:
    """Singleton registry of available embedding model profiles.

    Mirrors the Node.js singleton so the Python runtime resolves
    every embedding model through the same six built-in names. The
    only runtime difference is :data:`_default` which is set to
    ``"titan1024"`` here (Requirement 1.3).

    Notes
    -----
    The singleton is constructed via ``__new__`` so repeated
    ``EmbeddingModelRegistry()`` calls in different modules return
    the same instance — this keeps any runtime-registered profile
    visible everywhere it is needed (Requirement 1.6).
    """

    _instance: "EmbeddingModelRegistry | None" = None

    def __new__(cls) -> "EmbeddingModelRegistry":
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._profiles = {}  # type: ignore[attr-defined]
            inst._default = "titan1024"  # type: ignore[attr-defined]
            inst._register_builtins()  # type: ignore[attr-defined]
            cls._instance = inst
        return cls._instance

    # ── built-ins ──────────────────────────────────────────────────────

    def _register_builtins(self) -> None:
        """Register the six built-in profiles (Requirement 1.2).

        Field values are copied verbatim from the Node.js registry so
        the Python and Node.js runtimes resolve identical Bedrock
        ``modelId`` strings, identical vector lengths, and identical
        request bodies. Do not edit a built-in here without making
        the matching edit in
        ``mcp_server_node/scripts/embedding_registry.py``.
        """
        builtins = [
            ModelProfile(
                short_name="mpnet768",
                provider="local",
                model_id="all-mpnet-base-v2",
                dimensions=768,
            ),
            ModelProfile(
                short_name="titan1024",
                provider="bedrock",
                model_id="amazon.titan-embed-text-v2:0",
                dimensions=1024,
                provider_params={"dimensions": 1024},
            ),
            ModelProfile(
                short_name="nova256",
                provider="bedrock",
                model_id="amazon.nova-2-multimodal-embeddings-v1:0",
                dimensions=256,
                supports_matryoshka=True,
                supports_multimodal=True,
                provider_params={"embeddingConfig": {"outputEmbeddingLength": 256}},
            ),
            ModelProfile(
                short_name="nova512",
                provider="bedrock",
                model_id="amazon.nova-2-multimodal-embeddings-v1:0",
                dimensions=512,
                supports_matryoshka=True,
                supports_multimodal=True,
                provider_params={"embeddingConfig": {"outputEmbeddingLength": 512}},
            ),
            ModelProfile(
                short_name="nova1024",
                provider="bedrock",
                model_id="amazon.nova-2-multimodal-embeddings-v1:0",
                dimensions=1024,
                supports_matryoshka=True,
                supports_multimodal=True,
                provider_params={"embeddingConfig": {"outputEmbeddingLength": 1024}},
            ),
            ModelProfile(
                short_name="nova3072",
                provider="bedrock",
                model_id="amazon.nova-2-multimodal-embeddings-v1:0",
                dimensions=3072,
                supports_matryoshka=True,
                supports_multimodal=True,
                provider_params={"embeddingConfig": {"outputEmbeddingLength": 3072}},
            ),
        ]
        for profile in builtins:
            self._profiles[profile.short_name] = profile

    # ── public API ─────────────────────────────────────────────────────

    def get_profile(self, short_name: str) -> ModelProfile:
        """Return the profile named ``short_name`` (Requirement 1.4).

        Raises
        ------
        KeyError
            If ``short_name`` is not registered. The message lists
            every registered ``short_name`` so callers (and the
            ``ConfigError`` path in :mod:`src.config.environment`)
            can surface a helpful diagnostic.
        """
        if short_name not in self._profiles:
            available = list(self._profiles.keys())
            raise KeyError(
                f"Unknown model profile {short_name!r}. "
                f"Registered profiles: {available}"
            )
        return self._profiles[short_name]

    def get_default(self) -> ModelProfile:
        """Return the default profile, currently ``titan1024``."""
        return self._profiles[self._default]

    def list_profiles(self) -> list[str]:
        """Return the registered ``short_name`` values."""
        return list(self._profiles.keys())

    def register(self, profile: ModelProfile) -> None:
        """Add or replace a profile by ``short_name`` (Requirement 1.6)."""
        self._profiles[profile.short_name] = profile


__all__ = ["ModelProfile", "EmbeddingModelRegistry"]
