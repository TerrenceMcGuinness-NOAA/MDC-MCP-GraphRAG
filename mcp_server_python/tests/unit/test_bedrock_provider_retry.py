"""Unit tests for ``BedrockProvider`` retry/backoff (Phase C-2c, Req 11.3).

Mocks ``time.sleep`` so the 1s/2s/4s schedule is verifiable without
actually sleeping; mocks ``boto3.client`` so transient errors can be
synthesized without hitting AWS.
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
    def __init__(self, payload: dict[str, Any]):
        self._payload = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._payload


def _success_response(dim: int = 1024) -> dict[str, Any]:
    return {"body": _FakeBody({"embedding": [0.5] * dim})}


def _client_error(code: str, status: int) -> Exception:
    """Build a ``ClientError``-shaped exception with both code and status."""
    exc = Exception(f"{code} ({status})")
    exc.response = {  # type: ignore[attr-defined]
        "Error": {"Code": code, "Message": f"{code} {status}"},
        "ResponseMetadata": {"HTTPStatusCode": status},
    }
    return exc


def _http_error(status: int) -> Exception:
    """Build a duck-typed HTTP error carrying ``status_code``."""
    exc = Exception(f"HTTP {status}")
    exc.status_code = status  # type: ignore[attr-defined]
    return exc


@pytest.fixture()
def registry() -> EmbeddingModelRegistry:
    return EmbeddingModelRegistry()


# ── retry schedule (Req 4.1, 4.2) ─────────────────────────────────────


def test_three_throttles_then_success_yields_1_2_4_sleep_schedule(
    registry: EmbeddingModelRegistry,
) -> None:
    """Three transient errors followed by success → exactly [1, 2, 4]
    seconds slept (Requirement 4.2)."""
    fake_client = MagicMock()
    fake_client.invoke_model.side_effect = [
        _client_error("ThrottlingException", 429),
        _client_error("ThrottlingException", 429),
        _client_error("ThrottlingException", 429),
        _success_response(),
    ]

    sleeps: list[float] = []
    with patch("boto3.client", return_value=fake_client):
        provider = BedrockProvider(registry.get_profile("titan1024"))
        with patch(
            "src.data.embedding_provider.time.sleep",
            side_effect=lambda s: sleeps.append(s),
        ):
            vectors = provider.embed(["x"])

    assert sleeps == [1.0, 2.0, 4.0]
    assert len(vectors) == 1
    assert fake_client.invoke_model.call_count == 4


@pytest.mark.parametrize(
    "code", ["ThrottlingException", "TooManyRequestsException", "ServiceUnavailableException", "InternalServerException"]
)
def test_each_retryable_code_is_retried(
    registry: EmbeddingModelRegistry, code: str
) -> None:
    """Every entry in ``_RETRYABLE_CODES`` triggers a retry."""
    fake_client = MagicMock()
    fake_client.invoke_model.side_effect = [
        _client_error(code, 500),
        _success_response(),
    ]
    with patch("boto3.client", return_value=fake_client):
        provider = BedrockProvider(registry.get_profile("titan1024"))
        with patch("src.data.embedding_provider.time.sleep"):
            provider.embed(["x"])

    assert fake_client.invoke_model.call_count == 2


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_each_retryable_http_status_is_retried(
    registry: EmbeddingModelRegistry, status: int
) -> None:
    """Every entry in ``_RETRYABLE_STATUS`` triggers a retry."""
    fake_client = MagicMock()
    fake_client.invoke_model.side_effect = [
        _http_error(status),
        _success_response(),
    ]
    with patch("boto3.client", return_value=fake_client):
        provider = BedrockProvider(registry.get_profile("titan1024"))
        with patch("src.data.embedding_provider.time.sleep"):
            provider.embed(["x"])

    assert fake_client.invoke_model.call_count == 2


# ── non-retryable errors (Req 4.4) ────────────────────────────────────


def test_validation_exception_is_not_retried(
    registry: EmbeddingModelRegistry,
) -> None:
    """HTTP 400 ``ValidationException`` surfaces immediately (Req 4.4)."""
    fake_client = MagicMock()
    fake_client.invoke_model.side_effect = _client_error("ValidationException", 400)

    sleeps: list[float] = []
    with patch("boto3.client", return_value=fake_client):
        provider = BedrockProvider(registry.get_profile("titan1024"))
        with patch(
            "src.data.embedding_provider.time.sleep",
            side_effect=lambda s: sleeps.append(s),
        ):
            with pytest.raises(EmbeddingError) as exc:
                provider.embed(["x"])

    assert sleeps == []
    assert fake_client.invoke_model.call_count == 1
    # The wrapped error message must surface model_id and the
    # underlying exception (Req 4.3 / 4.4).
    assert "amazon.titan-embed-text-v2:0" in str(exc.value)


def test_access_denied_is_not_retried(
    registry: EmbeddingModelRegistry,
) -> None:
    fake_client = MagicMock()
    fake_client.invoke_model.side_effect = _client_error("AccessDeniedException", 403)

    with patch("boto3.client", return_value=fake_client):
        provider = BedrockProvider(registry.get_profile("titan1024"))
        with patch("src.data.embedding_provider.time.sleep"):
            with pytest.raises(EmbeddingError):
                provider.embed(["x"])

    assert fake_client.invoke_model.call_count == 1


# ── retry exhaustion (Req 4.3) ────────────────────────────────────────


def test_four_failed_attempts_raise_single_embedding_error(
    registry: EmbeddingModelRegistry,
) -> None:
    """Four transient failures → single ``EmbeddingError`` carrying
    model_id and the last underlying error (Req 4.3)."""
    fake_client = MagicMock()
    last_exc = _client_error("ThrottlingException", 429)
    fake_client.invoke_model.side_effect = [
        _client_error("ThrottlingException", 429),
        _client_error("ThrottlingException", 429),
        _client_error("ThrottlingException", 429),
        last_exc,
    ]

    sleeps: list[float] = []
    with patch("boto3.client", return_value=fake_client):
        provider = BedrockProvider(registry.get_profile("titan1024"))
        with patch(
            "src.data.embedding_provider.time.sleep",
            side_effect=lambda s: sleeps.append(s),
        ):
            with pytest.raises(EmbeddingError) as exc:
                provider.embed(["x"])

    assert fake_client.invoke_model.call_count == 4
    assert sleeps == [1.0, 2.0, 4.0]
    msg = str(exc.value)
    assert "amazon.titan-embed-text-v2:0" in msg
    # The chained __cause__ should be the final boto3 exception.
    assert exc.value.__cause__ is last_exc
