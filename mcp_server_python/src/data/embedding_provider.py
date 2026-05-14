"""Embedding provider abstraction (Phase C-2c, Requirements 2/3/4/9).

Provider-abstraction layer with a Bedrock-default factory. Mirrors the
Node.js port at ``mcp_server_node/scripts/embedding_provider.py`` with
two scope reductions:

1. Image embedding (``embed_image``) is dropped — the Python MCP
   runtime is text-only, the Node.js side ships its own image path
   for ingestion.
2. ``LocalProvider.embed`` is left as a stub that raises — the
   constructor errors first because ``sentence-transformers`` is not
   installed in the runtime image (Requirement 9). The class exists
   for parity with the Node.js port and so a future runtime image
   that does ship the dependency can re-enable the path with no
   structural change.

Public surface
--------------

* :class:`EmbeddingError` — raised on every embedding failure.
* :class:`EmbeddingProvider` — abstract interface.
* :class:`BedrockProvider` — concrete boto3 ``bedrock-runtime`` impl
  with 4-attempt retry on transient errors (Requirement 4).
* :class:`LocalProvider` — sentence-transformers shell that errors at
  construction time in this runtime image (Requirement 9).
* :func:`create_provider` — dispatches on ``profile.provider``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from abc import ABC, abstractmethod
from typing import Any

from src.data.embedding_registry import ModelProfile

log = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Raised when embedding generation fails.

    Wraps the underlying boto3 / import / parse error in a single
    type so callers can ``except EmbeddingError`` without depending on
    botocore. The :class:`OpenSearchAdapter` translates this into
    ``OpenSearchQueryError(status=None)`` so MCP tool handlers surface
    a structured error (Requirement 9.3).
    """


class EmbeddingProvider(ABC):
    """Abstract embedding provider interface (Requirement 2.1, 2.2)."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of text strings.

        Returns a list of float vectors, one per input. Vector length
        matches :pyattr:`dimensions`.
        """

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Vector length produced by this provider."""


# ── BedrockProvider (Requirements 3, 4) ───────────────────────────────


class BedrockProvider(EmbeddingProvider):
    """AWS Bedrock-Runtime-backed embedding provider.

    Lazy-imports ``boto3`` at construction so test environments that
    don't ship boto3 can still load this module. The ``bedrock-runtime``
    client is process-scoped — subsequent ``embed`` calls reuse it
    (Requirement 3.8).

    The retry contract mirrors the Node.js port: 4 total attempts,
    sleeps of 1s / 2s / 4s before attempts 2, 3, 4 (Requirement 4.1,
    4.2). Retries fire on Bedrock-Runtime ``ClientError`` whose code is
    in :data:`_RETRYABLE_CODES` or whose HTTP status is in
    :data:`_RETRYABLE_STATUS`. Anything else surfaces immediately as
    :class:`EmbeddingError` (Requirement 4.4).
    """

    # Mirrors the Node.js BedrockProvider tunables.
    _MAX_RETRIES: int = 3
    _BACKOFF_S: tuple[float, float, float] = (1.0, 2.0, 4.0)
    _RETRYABLE_CODES: frozenset[str] = frozenset(
        {
            "ThrottlingException",
            "TooManyRequestsException",
            "ServiceUnavailableException",
            "InternalServerException",
        }
    )
    _RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    def __init__(self, profile: ModelProfile) -> None:
        self._profile = profile
        # Lazy import keeps test environments without boto3 functional
        # for non-Bedrock unit tests.
        import boto3  # type: ignore[import-not-found]

        region = os.getenv("AWS_REGION", "us-east-1")
        self._client = boto3.client("bedrock-runtime", region_name=region)

    # ── public API ─────────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` via Bedrock, one ``invoke_model`` call per text.

        Per Requirement 3.1 each input string gets its own call. Titan
        and Nova use different request bodies (Requirements 3.2, 3.3);
        the response parsing branches on the same family
        (Requirement 3.4). Vector length is asserted to match
        ``profile.dimensions`` (Requirement 3.5).
        """
        return [self._embed_one(text) for text in texts]

    @property
    def dimensions(self) -> int:
        return self._profile.dimensions

    # ── internals ──────────────────────────────────────────────────────

    def _embed_one(self, text: str) -> list[float]:
        """Run one ``invoke_model`` with retry/backoff."""
        body = self._build_body(text)

        last_exc: BaseException | None = None
        for attempt in range(self._MAX_RETRIES + 1):  # 0..3 → 4 attempts
            try:
                response = self._client.invoke_model(
                    modelId=self._profile.model_id,
                    body=json.dumps(body),
                    contentType="application/json",
                    accept="application/json",
                )
                vector = self._parse_response(response)
                if len(vector) != self._profile.dimensions:
                    raise EmbeddingError(
                        f"Bedrock embed returned vector of length "
                        f"{len(vector)} but profile {self._profile.short_name} "
                        f"expects {self._profile.dimensions}"
                    )
                return vector
            except EmbeddingError:
                # Already a final embedding error (e.g. dimension
                # mismatch) — don't wrap or retry, just propagate.
                raise
            except Exception as exc:  # noqa: BLE001 — we wrap below
                last_exc = exc
                if not self._is_retryable(exc) or attempt >= self._MAX_RETRIES:
                    raise EmbeddingError(
                        f"Bedrock embed failed model={self._profile.model_id} "
                        f"input_len={len(text)}: {exc}"
                    ) from exc
                # Sleep before the *next* attempt (1s before attempt 2,
                # 2s before 3, 4s before 4) — see Requirement 4.2.
                time.sleep(self._BACKOFF_S[attempt])

        # Defense-in-depth: the loop above either returns or raises.
        raise EmbeddingError(  # pragma: no cover
            f"Bedrock embed failed model={self._profile.model_id} "
            f"input_len={len(text)}: {last_exc}"
        )

    def _build_body(self, text: str) -> dict[str, Any]:
        """Construct the request body for the active profile.

        Titan: ``{"inputText": text, **provider_params}`` (R3.2).
        Nova: the ``nova-multimodal-embed-v1`` schema (R3.3) — note
        the ``embeddingDimension`` is taken from
        :pyattr:`ModelProfile.dimensions` rather than from
        ``provider_params`` so the request body always agrees with
        the dimension assertion in :meth:`_embed_one`.
        """
        if "nova" in self._profile.model_id:
            return {
                "schemaVersion": "nova-multimodal-embed-v1",
                "taskType": "SINGLE_EMBEDDING",
                "singleEmbeddingParams": {
                    "embeddingPurpose": self._profile.provider_params.get(
                        "embeddingPurpose", "TEXT_RETRIEVAL"
                    ),
                    "embeddingDimension": self._profile.dimensions,
                    "text": {"truncationMode": "END", "value": text},
                },
            }
        # Titan family — merge any provider_params into the body.
        body: dict[str, Any] = {"inputText": text}
        body.update(self._profile.provider_params)
        return body

    @staticmethod
    def _parse_response(response: Any) -> list[float]:
        """Pull the embedding vector out of a Bedrock response.

        Titan returns ``{"embedding": [...]}``; Nova returns
        ``{"embeddings": [{"embedding": [...]}]}`` (R3.4).
        """
        body = response["body"].read()
        data = json.loads(body)
        if "embeddings" in data:
            return list(data["embeddings"][0]["embedding"])
        return list(data["embedding"])

    def _is_retryable(self, exc: BaseException) -> bool:
        """Return True iff ``exc`` is a transient Bedrock error.

        Inspects ``response["Error"]["Code"]`` and
        ``response["ResponseMetadata"]["HTTPStatusCode"]`` on
        ``ClientError``-shaped exceptions; falls back to a duck-typed
        ``status_code`` / ``status`` attribute for plain HTTP errors.
        """
        # botocore.exceptions.ClientError carries the structured
        # ``response`` dict.
        response = getattr(exc, "response", None)
        if isinstance(response, dict):
            error = response.get("Error") or {}
            code = error.get("Code")
            if code in self._RETRYABLE_CODES:
                return True
            metadata = response.get("ResponseMetadata") or {}
            status = metadata.get("HTTPStatusCode")
            if isinstance(status, int) and status in self._RETRYABLE_STATUS:
                return True
            return False
        # Duck-typed plain HTTP error (e.g. urllib3 errors, custom
        # transports).
        for attr in ("status_code", "status"):
            value = getattr(exc, attr, None)
            if isinstance(value, int) and value in self._RETRYABLE_STATUS:
                return True
        return False


# ── LocalProvider (Requirement 9) ─────────────────────────────────────


class LocalProvider(EmbeddingProvider):
    """sentence-transformers-backed provider — non-functional in this image.

    The Node.js port uses sentence-transformers as the local default;
    the Python runtime image deliberately excludes ``torch`` /
    ``transformers`` / ``sentence-transformers`` (Requirement 10), so
    ``LocalProvider.__init__`` emits an ``[ERROR]`` log line and
    raises :class:`EmbeddingError` (Requirements 9.1, 9.2).

    The class still exists so:

    * The :func:`create_provider` factory can dispatch to it without a
      conditional import at the module level.
    * A future runtime image that ships sentence-transformers can
      drop in a working implementation by replacing the body of
      :pymeth:`embed` and removing the import-fail check.
    """

    def __init__(self, profile: ModelProfile) -> None:
        self._profile = profile
        try:
            # ``sys.modules`` check is honored too so test masks via
            # ``sys.modules["sentence_transformers"] = None`` propagate.
            import sentence_transformers  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as exc:
            log.error(
                "[ERROR] LocalProvider unavailable for profile %s: "
                "sentence-transformers is not installed in the runtime image",
                profile.short_name,
            )
            # Mirror the [ERROR] line on stderr too so it surfaces
            # in container logs even when logging is unconfigured.
            print(
                f"[ERROR] LocalProvider unavailable for profile "
                f"{profile.short_name}: sentence-transformers is not "
                f"installed in the runtime image",
                file=sys.stderr,
            )
            raise EmbeddingError(
                "sentence-transformers is not installed in the runtime "
                "image; mpnet768 is parity-debug-only on this runtime"
            ) from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Stub for parity with the Node.js port — unreachable here.

        The constructor errors first when sentence-transformers is
        absent, so this body only runs in a hypothetical future image
        that ships the dependency. Keep it as a safe-by-default
        ``EmbeddingError`` rather than wiring the real model — the
        future image is responsible for replacing this stub.
        """
        raise EmbeddingError(
            "LocalProvider.embed is unimplemented in this runtime image"
        )

    @property
    def dimensions(self) -> int:
        return self._profile.dimensions


# ── factory (Requirement 2.3 – 2.5) ───────────────────────────────────


def create_provider(profile: ModelProfile) -> EmbeddingProvider:
    """Build the right :class:`EmbeddingProvider` for ``profile``.

    Dispatches on ``profile.provider``:

    * ``"bedrock"`` → :class:`BedrockProvider` (Requirement 2.3).
    * ``"local"``   → :class:`LocalProvider` (Requirement 2.4).
    * anything else → :class:`ValueError` (Requirement 2.5).

    Note this factory does not catch the :class:`EmbeddingError` that
    :class:`LocalProvider` may raise at construction time — the caller
    (in practice :class:`OpenSearchAdapter.__init__`) is responsible
    for catching that and re-surfacing it on first query so the error
    arrives at the MCP tool handler with the correct shape.
    """
    if profile.provider == "bedrock":
        return BedrockProvider(profile)
    if profile.provider == "local":
        return LocalProvider(profile)
    raise ValueError(
        f"Unknown provider {profile.provider!r} for profile "
        f"{profile.short_name!r}"
    )


__all__ = [
    "EmbeddingError",
    "EmbeddingProvider",
    "BedrockProvider",
    "LocalProvider",
    "create_provider",
]
