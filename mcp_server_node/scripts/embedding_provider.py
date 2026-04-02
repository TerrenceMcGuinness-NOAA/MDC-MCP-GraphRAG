"""
embedding_provider.py — Abstract and concrete embedding providers.

EmbeddingProvider ABC with LocalProvider (sentence-transformers) and
BedrockProvider (boto3 bedrock-runtime). Factory function create_provider().

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 12.1, 12.2, 12.3, 24.2, 24.3
"""

import os
import sys
from abc import ABC, abstractmethod
from typing import List

from embedding_registry import ModelProfile


class EmbeddingError(RuntimeError):
    """Raised when embedding generation fails."""


class EmbeddingProvider(ABC):
    """Abstract interface for embedding generation."""

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of text strings. Returns list of float vectors."""

    @abstractmethod
    def embed_image(self, image_bytes: bytes) -> List[float]:
        """Embed raw image bytes. Returns a single float vector."""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Dimensionality of produced vectors."""


class LocalProvider(EmbeddingProvider):
    """sentence-transformers on CPU/GPU."""

    def __init__(self, profile: ModelProfile) -> None:
        self._profile = profile
        cache_root = os.getenv("CACHE_ROOT", "/mdc-mcp-rag/cache")
        hf_cache = os.path.join(cache_root, "huggingface")
        os.makedirs(hf_cache, exist_ok=True)
        os.environ.setdefault("HF_HOME", hf_cache)
        os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(cache_root, "transformers"))

        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"

        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(
                profile.model_id,
                device=device,
                cache_folder=hf_cache,
            )
        except ImportError:
            print("[ERROR] sentence-transformers not installed", file=sys.stderr)
            raise

    def embed(self, texts: List[str]) -> List[List[float]]:
        vecs = self._model.encode(texts, convert_to_numpy=True)
        return [v.tolist() for v in vecs]

    def embed_image(self, image_bytes: bytes) -> List[float]:
        raise NotImplementedError("LocalProvider does not support image embedding")

    @property
    def dimensions(self) -> int:
        return self._profile.dimensions


class BedrockProvider(EmbeddingProvider):
    """AWS Bedrock API via boto3."""

    def __init__(self, profile: ModelProfile) -> None:
        self._profile = profile
        import boto3
        region = os.getenv("AWS_REGION", "us-east-1")
        self._client = boto3.Session().client("bedrock-runtime", region_name=region)

    def embed(self, texts: List[str]) -> List[List[float]]:
        import json as _json
        results = []
        for text in texts:
            body: dict = {"inputText": text}
            body.update(self._profile.provider_params)
            try:
                resp = self._client.invoke_model(
                    modelId=self._profile.model_id,
                    body=_json.dumps(body),
                    contentType="application/json",
                    accept="application/json",
                )
                data = _json.loads(resp["body"].read())
                results.append(data["embedding"])
            except Exception as exc:
                raise EmbeddingError(
                    f"Bedrock embed failed model={self._profile.model_id} "
                    f"input_len={len(text)}: {exc}"
                ) from exc
        return results

    def embed_image(self, image_bytes: bytes) -> List[float]:
        import json as _json
        import base64
        if not self._profile.supports_multimodal:
            raise NotImplementedError(
                f"Model {self._profile.short_name} does not support multimodal embedding"
            )
        body: dict = {
            "inputImage": base64.b64encode(image_bytes).decode(),
        }
        body.update(self._profile.provider_params)
        try:
            resp = self._client.invoke_model(
                modelId=self._profile.model_id,
                body=_json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            data = _json.loads(resp["body"].read())
            return data["embedding"]
        except Exception as exc:
            raise EmbeddingError(
                f"Bedrock image embed failed model={self._profile.model_id}: {exc}"
            ) from exc

    @property
    def dimensions(self) -> int:
        return self._profile.dimensions


def create_provider(profile: ModelProfile) -> EmbeddingProvider:
    """Factory: return the appropriate provider for a ModelProfile."""
    if profile.provider == "local":
        return LocalProvider(profile)
    if profile.provider == "bedrock":
        return BedrockProvider(profile)
    raise ValueError(f"Unknown provider '{profile.provider}' for model '{profile.short_name}'")
