"""Unified ingest manifest package (Requirements 1.1, 1.2, 1.10).

The :mod:`src.manifest` package implements the SPOT (Source of
Production Truth) protocol for the MDC MCP RAG knowledge base. It
extends the URL-only ``documentation_sources.json`` to a unified
manifest registering all seven source types (URL crawls, on-disk
submodule reads, code parses, config parses, EE2 standards, community
summaries, and J-Job docs).

Public surface:

* :class:`SourceType` — the seven valid source types.
* :class:`SourceEntry` — one source declaration in the manifest.
* :class:`UnifiedManifest` — top-level wrapper.
* :class:`ManifestRegistry` — in-memory registry the MCP server boots
  against and the tool layer queries.
* :class:`GapDetector` / :class:`GapReport` — declared-vs-actual
  coverage detection against OpenSearch.
* :func:`load_manifest` / :func:`resolve_manifest_path` — fallback-aware
  loader used at boot time.
"""

from __future__ import annotations

from .gap_detector import GapDetector, GapReport
from .loader import load_manifest, resolve_manifest_path
from .models import SourceEntry, SourceType, UnifiedManifest
from .registry import ManifestRegistry

__all__ = [
    "GapDetector",
    "GapReport",
    "ManifestRegistry",
    "SourceEntry",
    "SourceType",
    "UnifiedManifest",
    "load_manifest",
    "resolve_manifest_path",
]
