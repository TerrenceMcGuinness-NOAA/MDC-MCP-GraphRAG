"""
embedding_registry.py — Central registry of embedding model profiles.

Provides ModelProfile dataclass and EmbeddingModelRegistry singleton.
All ingestion scripts resolve model configuration through this module.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 24.1, 24.5
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ModelProfile:
    """Immutable descriptor for an embedding model."""
    short_name: str           # e.g. "mpnet768", "titan1024"
    provider: str             # "local" | "bedrock"
    model_id: str             # HuggingFace name or Bedrock model ID
    dimensions: int           # Vector dimension count
    supports_matryoshka: bool = False
    supports_multimodal: bool = False
    provider_params: dict = field(default_factory=dict)


class EmbeddingModelRegistry:
    """Singleton registry of available embedding model profiles."""

    _instance: Optional["EmbeddingModelRegistry"] = None

    def __new__(cls) -> "EmbeddingModelRegistry":
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._profiles: Dict[str, ModelProfile] = {}
            inst._default: str = "mpnet768"
            inst._register_builtins()
            cls._instance = inst
        return cls._instance

    def _register_builtins(self) -> None:
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
        for p in builtins:
            self._profiles[p.short_name] = p

    def get_profile(self, short_name: str) -> ModelProfile:
        """Return profile by short_name; raise KeyError if not found."""
        if short_name not in self._profiles:
            available = list(self._profiles.keys())
            raise KeyError(
                f"Unknown model '{short_name}'. Available: {available}"
            )
        return self._profiles[short_name]

    def get_default(self) -> ModelProfile:
        """Return the default model profile (mpnet768)."""
        return self._profiles[self._default]

    def list_profiles(self) -> List[str]:
        """Return list of registered short_names."""
        return list(self._profiles.keys())

    def register(self, profile: ModelProfile) -> None:
        """Register a custom or fine-tuned model profile."""
        self._profiles[profile.short_name] = profile
