"""
collection_namer.py — Model-aware collection/index name generation.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
"""

from embedding_registry import EmbeddingModelRegistry, ModelProfile


class CollectionNamer:
    """Generates model-aware collection/index names."""

    def __init__(self, profile: ModelProfile) -> None:
        self.profile = profile

    def get_name(self, domain: str, version: str) -> str:
        """e.g. get_name('code-with-context', 'v8-0-0') -> 'code-with-context-v8-0-0-mpnet768'"""
        return f"{domain}-{version}-{self.profile.short_name}"

    def get_legacy_name(self, domain: str, version: str) -> str:
        """Return legacy name without model suffix for backward compat."""
        return f"{domain}-{version}"

    @staticmethod
    def is_legacy_name(name: str) -> bool:
        """True if name lacks any known model suffix (legacy format)."""
        registry = EmbeddingModelRegistry()
        return not any(name.endswith(f"-{s}") for s in registry.list_profiles())
