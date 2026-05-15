"""Unit tests for ``BedrockProvider`` request body shape (Phase C-2c, Req 11.2).

Mocks the ``bedrock-runtime`` client at the boto3 layer so we can
inspect the JSON body, ``modelId``, and ``contentType`` /  ``accept``
headers that hit Bedrock without any network access.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.data.embedding_provider import BedrockProvider, EmbeddingError
from src.data.embedding_registry import EmbeddingModelRegistry


# ── helpers ───────────────────────────────────────────────────────────


class _FakeBody:
    """Minimal stand-in for ``response['body']`` that supports ``read()``."""

    def __init__(self, payload: dict[str, Any]):
        self._payload = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._payload


def _titan_response(dim: int = 1024) -> dict[str, Any]:
    """Shape the Titan Embed Text V2 response."""
    return {"body": _FakeBody({"embedding": [0.5] * dim})}


def _nova_response(dim: int) -> dict[str, Any]:
    """Shape the Nova multimodal embed response."""
    return {"body": _FakeBody({"embeddings": [{"embedding": [0.25] * dim}]})}


@pytest.fixture()
def registry() -> EmbeddingModelRegistry:
    return EmbeddingModelRegistry()


# ── construction ──────────────────────────────────────────────────────


def test_construction_uses_aws_region_env_var(
    monkeypatch: pytest.MonkeyPatch, registry: EmbeddingModelRegistry
) -> None:
    """``BedrockProvider`` honors ``AWS_REGION`` (Requirement 3.7)."""
    fake_client = MagicMock()
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    with patch("boto3.client", return_value=fake_client) as mock_factory:
        BedrockProvider(registry.get_profile("titan1024"))

    mock_factory.assert_called_once()
    args, kwargs = mock_factory.call_args
    assert args == ("bedrock-runtime",)
    assert kwargs == {"region_name": "us-west-2"}


def test_construction_defaults_region_to_us_east_1(
    monkeypatch: pytest.MonkeyPatch, registry: EmbeddingModelRegistry
) -> None:
    """Unset ``AWS_REGION`` falls back to ``us-east-1`` (Req 3.7)."""
    monkeypatch.delenv("AWS_REGION", raising=False)
    with patch("boto3.client", return_value=MagicMock()) as mock_factory:
        BedrockProvider(registry.get_profile("titan1024"))
    _, kwargs = mock_factory.call_args
    assert kwargs == {"region_name": "us-east-1"}


# ── Titan request body (Requirement 3.2, 3.5) ─────────────────────────


def test_titan_body_carries_input_text_and_provider_params(
    registry: EmbeddingModelRegistry,
) -> None:
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = _titan_response(dim=1024)

    with patch("boto3.client", return_value=fake_client):
        provider = BedrockProvider(registry.get_profile("titan1024"))

    vectors = provider.embed(["hello world"])

    assert len(vectors) == 1
    assert len(vectors[0]) == 1024  # Req 3.5
    fake_client.invoke_model.assert_called_once()
    kwargs = fake_client.invoke_model.call_args.kwargs
    assert kwargs["modelId"] == "amazon.titan-embed-text-v2:0"  # Req 3.1
    assert kwargs["contentType"] == "application/json"
    assert kwargs["accept"] == "application/json"

    body = json.loads(kwargs["body"])
    assert body["inputText"] == "hello world"  # Req 3.2
    # provider_params={"dimensions": 1024} must be merged in.
    assert body["dimensions"] == 1024


# ── Nova request body (Requirement 3.3, 3.5) ──────────────────────────


@pytest.mark.parametrize(
    "short_name, expected_dim",
    [("nova256", 256), ("nova512", 512), ("nova1024", 1024), ("nova3072", 3072)],
)
def test_nova_body_uses_multimodal_schema(
    registry: EmbeddingModelRegistry, short_name: str, expected_dim: int
) -> None:
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = _nova_response(dim=expected_dim)

    with patch("boto3.client", return_value=fake_client):
        provider = BedrockProvider(registry.get_profile(short_name))

    vectors = provider.embed(["a sentence"])

    assert len(vectors[0]) == expected_dim  # Req 3.5
    body = json.loads(fake_client.invoke_model.call_args.kwargs["body"])
    assert body["schemaVersion"] == "nova-multimodal-embed-v1"
    assert body["taskType"] == "SINGLE_EMBEDDING"
    params = body["singleEmbeddingParams"]
    assert params["embeddingDimension"] == expected_dim  # Req 3.3
    assert params["text"]["value"] == "a sentence"
    assert params["embeddingPurpose"] == "TEXT_RETRIEVAL"


# ── one invoke_model call per text (Requirement 3.1) ──────────────────


def test_one_invoke_model_call_per_input_text(
    registry: EmbeddingModelRegistry,
) -> None:
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = _titan_response(dim=1024)

    with patch("boto3.client", return_value=fake_client):
        provider = BedrockProvider(registry.get_profile("titan1024"))
        provider.embed(["a", "b", "c"])

    assert fake_client.invoke_model.call_count == 3


# ── response parsing (Requirement 3.4) ────────────────────────────────


def test_titan_response_parse_returns_embedding_field(
    registry: EmbeddingModelRegistry,
) -> None:
    expected = [0.1] * 1024
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = {
        "body": _FakeBody({"embedding": expected})
    }

    with patch("boto3.client", return_value=fake_client):
        provider = BedrockProvider(registry.get_profile("titan1024"))
        vectors = provider.embed(["x"])

    assert vectors[0] == expected


def test_nova_response_parse_returns_embeddings_zero_embedding(
    registry: EmbeddingModelRegistry,
) -> None:
    expected = [0.7] * 1024
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = {
        "body": _FakeBody({"embeddings": [{"embedding": expected}]})
    }

    with patch("boto3.client", return_value=fake_client):
        provider = BedrockProvider(registry.get_profile("nova1024"))
        vectors = provider.embed(["x"])

    assert vectors[0] == expected


# ── dimensions property ───────────────────────────────────────────────


def test_dimensions_property_matches_profile(
    registry: EmbeddingModelRegistry,
) -> None:
    with patch("boto3.client", return_value=MagicMock()):
        provider = BedrockProvider(registry.get_profile("nova512"))
    assert provider.dimensions == 512


# ── dimension mismatch surfaces as EmbeddingError ─────────────────────


def test_dimension_mismatch_raises_embedding_error(
    registry: EmbeddingModelRegistry,
) -> None:
    """If Bedrock returns a vector of unexpected length, surface a clean
    ``EmbeddingError`` rather than letting the bad shape escape (Req 3.5)."""
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = {
        "body": _FakeBody({"embedding": [0.0] * 999})  # wrong size
    }

    with patch("boto3.client", return_value=fake_client):
        provider = BedrockProvider(registry.get_profile("titan1024"))
        with pytest.raises(EmbeddingError, match="length 999"):
            provider.embed(["x"])
