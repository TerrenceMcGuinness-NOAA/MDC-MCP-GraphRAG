"""Adapter protocols + row types for the Portable_Export pipeline (Task 6).

The phase modules are direction-agnostic: they call ``source.scroll_records()``
and ``target.bulk_insert_vectors()`` and never branch on which engine is on
either side. The :class:`SourceReader` and :class:`TargetWriter` protocols
below define that contract.

Property 5 (source immutability) is enforced structurally: ``SourceReader``
exposes only read methods. The contract test in ``test_aws_readers.py``
asserts no create / delete / replace / modify call lands on the source data
plane during any export run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, runtime_checkable


@dataclass
class NodeRow:
    """A graph node: stable id, label, and properties."""

    id: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class RelRow:
    """A graph relationship: type, endpoint ids, and properties."""

    id: str
    type: str
    start: str
    end: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class DedupeRow:
    """A Dedupe_Registry entry keyed by ``(collection, sha)`` per tenant."""

    tenant_id: str
    collection: str
    sha: str


@runtime_checkable
class SourceReader(Protocol):
    """Read-only side. Strict invariant: no source mutation, ever."""

    def list_index_families(self, tenants: list[str]) -> list[str]: ...

    def scroll_records(self, index: str, batch: int) -> Iterator[list[dict]]: ...

    def list_graph_label_families(self, tenants: list[str]) -> list[str]: ...

    def stream_nodes(self, tenant: str) -> Iterator[NodeRow]: ...

    def stream_relationships(self, tenant: str) -> Iterator[RelRow]: ...

    def read_dedupe_registry(self) -> Iterator[DedupeRow]: ...


@runtime_checkable
class TargetWriter(Protocol):
    """Write side. Pre-write probe + confirmation gate handled outside."""

    def probe_non_empty(self) -> dict: ...

    def ensure_collection_or_index(self, name: str, model_profile: str) -> Any: ...

    def bulk_insert_vectors(self, collection: str, records) -> Any: ...

    def load_graph_bundle(self, tenant: str, nodes_uris, rels_uris) -> Any: ...

    def rebuild_dedupe(self) -> int: ...

    def count_collection(self, collection: str) -> int: ...

    def count_graph(self, tenant: str) -> tuple[int, int]: ...


__all__ = [
    "NodeRow",
    "RelRow",
    "DedupeRow",
    "SourceReader",
    "TargetWriter",
]
