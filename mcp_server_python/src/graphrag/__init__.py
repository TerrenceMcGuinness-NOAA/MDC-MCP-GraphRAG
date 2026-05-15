"""Graph-guided retrieval package.

Public API surface for tool modules and tests. Everything here is
re-exported from the two submodules so downstream code can write::

    from src.graphrag import GGSRTraversal, GraphGuidedRetrieval
"""

from __future__ import annotations

from .ggsr_traversal import (
    BRIDGE_DECAY_OVERRIDE,
    DEFAULT_TOKEN_BUDGET,
    DEFAULT_WEIGHT,
    HOP_DECAY,
    WEIGHT_MATRIX,
    GGSRScoredResult,
    GGSRTraversal,
    estimate_row_tokens,
    estimate_tokens,
)
from .graph_guided_retrieval import GraphGuidedRetrieval, GGSRRetrievalResult

__all__ = [
    "GGSRTraversal",
    "GGSRScoredResult",
    "WEIGHT_MATRIX",
    "HOP_DECAY",
    "BRIDGE_DECAY_OVERRIDE",
    "DEFAULT_WEIGHT",
    "DEFAULT_TOKEN_BUDGET",
    "estimate_tokens",
    "estimate_row_tokens",
    "GraphGuidedRetrieval",
    "GGSRRetrievalResult",
]
