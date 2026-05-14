"""Unit tests for ``OpenSearchAdapter._generate_embedding`` after the
Phase C-2c Bedrock-native embedding swap (Req 5, 6, 9, 11.6).

Covers:

* ``_generate_embedding`` returns the first vector from
  ``provider.embed`` (Req 5.3).
* ``EmbeddingError`` raised by the provider becomes
  ``OpenSearchQueryError(status=None)`` (Req 9.3).
* ``MCP_EMBEDDING_PROFILE=titan1024`` selects a Bedrock-shaped provider
  via the :func:`bedrock_provider_factory` fixture and the resulting
  vector length matches ``profile.dimensions`` (Req 6.4, 6.5).
* ``MCP_EMBEDDING_PROFILE=mpnet768`` triggers a ``LocalProvider`` whose
  construction error propagates as ``OpenSearchQueryError`` from the
  first query (Req 9).
* The adapter no longer imports ``sentence_transformers`` at module
  load (Req 6.1, 6.3).

The :func:`bedrock_provider_factory` fixture monkey-patches
:func:`src.data.opensearch_adapter.create_provider` so the real
Bedrock client is never constructed — every test in this file runs
without network access.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import pytest

from src.data.embedding_provider import EmbeddingError
from src.data.embedding_registry import EmbeddingModelRegistry
from src.data.opensearch_adapter import (
    OpenSearchAdapter,
    OpenSearchQueryError,
)


# ── module load contract (Req 6.1, 6.3) ───────────────────────────────


def test_module_does_not_import_sentence_transformers_at_load() -> None:
    """The adapter module must never load ``sentence_transformers``
    or carry the prior ``_default_mpnet_embedding`` /  ``_mpnet_model``
    helpers (Requirement 6.1, 6.3)."""
    import src.data.opensearch_adapter as mod

    # Module attributes the prior helpers used to expose are gone.
    assert not hasattr(mod, "_default_mpnet_embedding")
    assert not hasattr(mod, "_mpnet_model")
    assert not hasattr(mod, "_MPNET")
    # The prior implementation pulled ``SentenceTransformer`` into the
    # module namespace via ``from sentence_transformers import ...``.
    # That symbol must not exist on the module.
    assert not hasattr(mod, "SentenceTransformer")


# ── titan1024 path via the mock provider factory (Req 6.4, 6.5) ───────


@pytest.mark.asyncio
async def test_generate_embedding_returns_first_vector_from_provider(
    monkeypatch: pytest.MonkeyPatch, bedrock_provider_factory
) -> None:
    """``_generate_embedding`` returns ``provider.embed([q])[0]``
    (Req 5.3)."""
    monkeypatch.setenv("MCP_EMBEDDING_PROFILE", "titan1024")
    adapter = OpenSearchAdapter(endpoint="https://os.example", region="us-east-1")
    vec = await adapter._generate_embedding("hello world")

    # Active profile is titan1024 → vectors are 1024-dim zeros.
    assert len(vec) == 1024
    assert vec == [0.0] * 1024
    # Exactly one provider was constructed at adapter init time.
    assert len(bedrock_provider_factory) == 1
    provider = bedrock_provider_factory[0]
    assert provider.calls == [["hello world"]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile_name, dim",
    [
        ("titan1024", 1024),
        ("nova256", 256),
        ("nova512", 512),
        ("nova1024", 1024),
        ("nova3072", 3072),
    ],
)
async def test_active_profile_drives_vector_length(
    monkeypatch: pytest.MonkeyPatch,
    bedrock_provider_factory,
    profile_name: str,
    dim: int,
) -> None:
    monkeypatch.setenv("MCP_EMBEDDING_PROFILE", profile_name)
    adapter = OpenSearchAdapter(endpoint="https://os.example")
    vec = await adapter._generate_embedding("q")
    assert len(vec) == dim


# ── EmbeddingError → OpenSearchQueryError(status=None) (Req 9.3) ──────


@pytest.mark.asyncio
async def test_embedding_error_from_provider_becomes_opensearch_query_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_EMBEDDING_PROFILE", "titan1024")

    class _BoomProvider:
        def __init__(self, profile: Any) -> None:
            self._profile = profile

        def embed(self, texts: list[str]) -> list[list[float]]:
            raise EmbeddingError("simulated Bedrock failure")

        @property
        def dimensions(self) -> int:
            return self._profile.dimensions

    monkeypatch.setattr(
        "src.data.opensearch_adapter.create_provider", _BoomProvider
    )

    adapter = OpenSearchAdapter(endpoint="https://os.example")
    with pytest.raises(OpenSearchQueryError) as exc:
        await adapter._generate_embedding("q")
    assert exc.value.status is None
    assert "simulated Bedrock failure" in str(exc.value)


# ── mpnet768 LocalProvider error path (Req 9.1, 9.3) ──────────────────


@pytest.mark.asyncio
async def test_mpnet768_local_provider_error_surfaces_on_first_embed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MCP_EMBEDDING_PROFILE=mpnet768`` constructs ``LocalProvider``
    which raises ``EmbeddingError`` immediately. The adapter captures
    that at ``__init__`` and surfaces it as ``OpenSearchQueryError``
    on the first ``_generate_embedding`` call (Req 9.3)."""
    monkeypatch.setenv("MCP_EMBEDDING_PROFILE", "mpnet768")
    # Mask sentence_transformers so the LocalProvider's import fails.
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)
    real_import = (
        __builtins__["__import__"]
        if isinstance(__builtins__, dict)
        else __builtins__.__import__
    )

    def _block(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("No module named 'sentence_transformers'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _block)

    # Adapter construction succeeds — the EmbeddingError from
    # LocalProvider is captured on `self._provider_error`.
    adapter = OpenSearchAdapter(endpoint="https://os.example")
    assert adapter._provider is None
    assert adapter._provider_error is not None

    with pytest.raises(OpenSearchQueryError) as exc:
        await adapter._generate_embedding("q")
    assert exc.value.status is None
    assert "sentence-transformers is not installed" in str(exc.value)


# ── explicit embedding_function override (Req 5.2) ────────────────────


@pytest.mark.asyncio
async def test_explicit_embedding_function_skips_provider_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit ``embedding_function`` arg short-circuits provider
    construction (Req 5.2)."""

    def fake_embed(texts: list[str]) -> list[list[float]]:
        return [[0.5] * 4 for _ in texts]

    # We patch ``create_provider`` to a sentinel that would error if
    # called — and assert it is *not* called.
    def _should_not_be_called(profile: Any) -> Any:  # pragma: no cover
        raise AssertionError(
            "create_provider must not run when embedding_function is provided"
        )

    monkeypatch.setenv("MCP_EMBEDDING_PROFILE", "titan1024")
    monkeypatch.setattr(
        "src.data.opensearch_adapter.create_provider", _should_not_be_called
    )

    adapter = OpenSearchAdapter(
        endpoint="https://os.example",
        embedding_function=fake_embed,
    )
    assert adapter._provider is None
    assert adapter._provider_error is None

    vec = await adapter._generate_embedding("q")
    assert vec == [0.5, 0.5, 0.5, 0.5]


# ── default profile selection (Req 7.1) ───────────────────────────────


@pytest.mark.asyncio
async def test_unset_profile_defaults_to_titan1024(
    monkeypatch: pytest.MonkeyPatch, bedrock_provider_factory
) -> None:
    monkeypatch.delenv("MCP_EMBEDDING_PROFILE", raising=False)
    adapter = OpenSearchAdapter(endpoint="https://os.example")
    assert adapter._profile.short_name == "titan1024"
    vec = await adapter._generate_embedding("q")
    assert len(vec) == 1024


# ── profile drives index resolution in query (Req 8.1, design 5.3) ───


@pytest.mark.asyncio
async def test_query_passes_active_profile_to_resolve_index(
    monkeypatch: pytest.MonkeyPatch, bedrock_provider_factory
) -> None:
    """The adapter passes ``self._profile.short_name`` to
    ``resolve_index`` so the query vector and the indexed vectors
    share a dimensionality (Req 8.1)."""
    captured: dict[str, Any] = {}

    def _fake_resolve(collection: str, profile_short_name: str = "titan1024") -> str:
        captured["collection"] = collection
        captured["profile"] = profile_short_name
        return f"resolved-{profile_short_name}-{collection}"

    monkeypatch.setattr(
        "src.data.opensearch_adapter.resolve_index", _fake_resolve
    )
    monkeypatch.setenv("MCP_EMBEDDING_PROFILE", "titan1024")

    adapter = OpenSearchAdapter(endpoint="https://os.example")

    # Stub the search/connect chain so query() reaches resolve_index
    # without needing a real OpenSearch client.
    async def _fake_connect() -> None:
        adapter._connected = True

    async def _fake_search(*, index: str, body: dict[str, Any]) -> dict[str, Any]:
        captured["index_used"] = index
        return {"hits": {"hits": []}}

    monkeypatch.setattr(adapter, "connect", _fake_connect)
    monkeypatch.setattr(adapter, "_search_with_retry", _fake_search)

    await adapter.query("code-with-context-v8-0-0", "test query")

    assert captured["collection"] == "code-with-context-v8-0-0"
    assert captured["profile"] == "titan1024"
    assert captured["index_used"] == "resolved-titan1024-code-with-context-v8-0-0"
