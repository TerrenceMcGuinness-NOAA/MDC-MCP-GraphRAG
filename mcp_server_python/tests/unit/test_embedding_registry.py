"""Unit tests for :mod:`src.data.embedding_registry` (Phase C-2c, Req 1.x).

The registry is small (~200 LOC, no I/O) so the test surface is
small too: profile lookup happy path, profile lookup miss, default
profile, list, register round-trip, and a sanity check that the
six built-in field values match the Node.js registry the design
explicitly ports from.
"""

from __future__ import annotations

import pytest

from src.data.embedding_registry import EmbeddingModelRegistry, ModelProfile


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def registry() -> EmbeddingModelRegistry:
    """Return the registry singleton.

    The fixture is intentionally not `autouse` and does not mutate
    the singleton — `register()` round-trip tests below clean up
    after themselves so the singleton stays in built-in shape for
    the rest of the suite.
    """
    return EmbeddingModelRegistry()


# ── built-in profile lookup (Req 1.2, 1.4) ────────────────────────────


@pytest.mark.parametrize(
    "short_name, expected_provider, expected_dimensions, expected_model_id",
    [
        ("mpnet768", "local", 768, "all-mpnet-base-v2"),
        ("titan1024", "bedrock", 1024, "amazon.titan-embed-text-v2:0"),
        ("nova256", "bedrock", 256, "amazon.nova-2-multimodal-embeddings-v1:0"),
        ("nova512", "bedrock", 512, "amazon.nova-2-multimodal-embeddings-v1:0"),
        ("nova1024", "bedrock", 1024, "amazon.nova-2-multimodal-embeddings-v1:0"),
        ("nova3072", "bedrock", 3072, "amazon.nova-2-multimodal-embeddings-v1:0"),
    ],
)
def test_get_profile_returns_each_builtin(
    registry: EmbeddingModelRegistry,
    short_name: str,
    expected_provider: str,
    expected_dimensions: int,
    expected_model_id: str,
) -> None:
    profile = registry.get_profile(short_name)
    assert isinstance(profile, ModelProfile)
    assert profile.short_name == short_name
    assert profile.provider == expected_provider
    assert profile.dimensions == expected_dimensions
    assert profile.model_id == expected_model_id


def test_titan1024_provider_params_carry_dimensions_field(
    registry: EmbeddingModelRegistry,
) -> None:
    """Titan body merges ``provider_params`` into the request — the
    Node.js side expects ``{"dimensions": 1024}`` to ride along."""
    profile = registry.get_profile("titan1024")
    assert profile.provider_params == {"dimensions": 1024}


@pytest.mark.parametrize(
    "short_name, expected_dim",
    [("nova256", 256), ("nova512", 512), ("nova1024", 1024), ("nova3072", 3072)],
)
def test_nova_provider_params_carry_output_dimension(
    registry: EmbeddingModelRegistry, short_name: str, expected_dim: int
) -> None:
    profile = registry.get_profile(short_name)
    assert profile.supports_matryoshka is True
    assert profile.supports_multimodal is True
    assert profile.provider_params == {
        "embeddingConfig": {"outputEmbeddingLength": expected_dim}
    }


# ── miss path (Req 1.5) ───────────────────────────────────────────────


def test_get_profile_unknown_raises_keyerror_listing_all_names(
    registry: EmbeddingModelRegistry,
) -> None:
    with pytest.raises(KeyError) as exc:
        registry.get_profile("does_not_exist")
    # The KeyError message should name every registered profile so
    # the user sees the full menu in the diagnostic.
    message = str(exc.value)
    for name in (
        "mpnet768",
        "titan1024",
        "nova256",
        "nova512",
        "nova1024",
        "nova3072",
    ):
        assert name in message
    assert "does_not_exist" in message


# ── default profile (Req 1.3) ─────────────────────────────────────────


def test_get_default_returns_titan1024(registry: EmbeddingModelRegistry) -> None:
    default = registry.get_default()
    assert default.short_name == "titan1024"
    assert default.provider == "bedrock"
    assert default.dimensions == 1024


# ── list_profiles ─────────────────────────────────────────────────────


def test_list_profiles_returns_six_builtins(
    registry: EmbeddingModelRegistry,
) -> None:
    names = registry.list_profiles()
    assert set(names) == {
        "mpnet768",
        "titan1024",
        "nova256",
        "nova512",
        "nova1024",
        "nova3072",
    }


# ── register round-trip (Req 1.6) ─────────────────────────────────────


def test_register_round_trip_for_a_custom_profile(
    registry: EmbeddingModelRegistry,
) -> None:
    custom = ModelProfile(
        short_name="custom-test-only",
        provider="bedrock",
        model_id="amazon.custom",
        dimensions=42,
    )
    registry.register(custom)
    try:
        assert registry.get_profile("custom-test-only") is custom
        assert "custom-test-only" in registry.list_profiles()
    finally:
        # Clean up so we leave the singleton in built-in shape for
        # the rest of the test suite.
        registry._profiles.pop("custom-test-only", None)


def test_singleton_returns_same_instance() -> None:
    a = EmbeddingModelRegistry()
    b = EmbeddingModelRegistry()
    assert a is b


def test_modelprofile_is_frozen() -> None:
    profile = ModelProfile(
        short_name="x", provider="bedrock", model_id="m", dimensions=4
    )
    with pytest.raises(Exception):
        # Frozen dataclass — assignment should fail.
        profile.dimensions = 8  # type: ignore[misc]
