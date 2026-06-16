"""ChromaDB target writer (COTS restore, Task 8).

Loads Vector_Export records into ChromaDB via
``collection.add(ids, documents, embeddings, metadatas)`` with the embedding
passed through bitwise -- no recompute (R2.1, R2.5). Collection names
(including any tenant prefix) are preserved verbatim (R2.3).

The adapter operates on an injected ChromaDB-like client so unit tests use an
in-memory fake; production wires a version-pinned ``chromadb.HttpClient``. A
client whose version falls outside the supported range is refused
(design Open Question 2).

Records missing a required field of ``(id, content, embedding,
model_profile)`` are recorded as errors and skipped while the remaining
records continue to load (R2.4).

Requirements: 2.1, 2.3, 2.4, 2.5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

#: Supported ChromaDB version range (inclusive lower, exclusive upper).
SUPPORTED_CHROMADB_MIN = (0, 4, 0)
SUPPORTED_CHROMADB_MAX = (0, 6, 0)

#: Required fields for a loadable Vector_Export record (R2.4).
REQUIRED_RECORD_FIELDS: tuple[str, ...] = ("id", "content", "embedding", "model_profile")


class ChromaVersionError(Exception):
    """The ChromaDB client version is outside the supported range."""


@dataclass
class LoadResult:
    """Outcome of a vector load into one collection."""

    collection: str
    loaded: int = 0
    errors: list[str] = field(default_factory=list)


def _parse_version(v: str) -> tuple[int, int, int]:
    parts = (v.split("+", 1)[0].split("-", 1)[0]).split(".")
    nums = [int(p) for p in parts[:3] if p.isdigit()]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])  # type: ignore[return-value]


def assert_supported_version(version: str) -> None:
    """Refuse a ChromaDB version outside the supported range."""
    parsed = _parse_version(version)
    if not (SUPPORTED_CHROMADB_MIN <= parsed < SUPPORTED_CHROMADB_MAX):
        raise ChromaVersionError(
            f"ChromaDB version {version} outside supported range "
            f"[{'.'.join(map(str, SUPPORTED_CHROMADB_MIN))}, "
            f"{'.'.join(map(str, SUPPORTED_CHROMADB_MAX))})"
        )


def missing_required_fields(record: dict) -> list[str]:
    """Return the required fields absent/empty in ``record`` (R2.4)."""
    missing = []
    for f in REQUIRED_RECORD_FIELDS:
        val = record.get(f)
        if val is None or (isinstance(val, (str, list)) and len(val) == 0):
            missing.append(f)
    return missing


class ChromaDBWriter:
    """ChromaDB COTS writer with bitwise embedding pass-through.

    Parameters
    ----------
    client
        ChromaDB-like client exposing ``get_or_create_collection(name)`` whose
        collection exposes ``add(ids, documents, embeddings, metadatas)`` and
        ``count()``. Injected for tests.
    version
        Reported client version; validated against the supported range.
    """

    def __init__(self, client: Any, *, version: str = "0.5.0",
                 validate_version: bool = True) -> None:
        if validate_version:
            assert_supported_version(version)
        self._client = client
        self._version = version

    def ensure_collection_or_index(self, name: str, model_profile: str) -> Any:
        """Create / fetch the collection ``name`` (prefix preserved, R2.3)."""
        return self._client.get_or_create_collection(name)

    def bulk_insert_vectors(
        self, collection: str, records: Iterable[dict]
    ) -> LoadResult:
        """Load ``records`` into ``collection`` bitwise; skip+record bad ones.

        Missing-required-field records are recorded as errors and skipped
        (R2.4); valid records are loaded with embeddings unchanged (R2.5).
        """
        result = LoadResult(collection=collection)
        coll = self._client.get_or_create_collection(collection)
        ids: list[str] = []
        documents: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict] = []
        for rec in records:
            missing = missing_required_fields(rec)
            if missing:
                result.errors.append(
                    f"{rec.get('id', '<no-id>')}: missing {','.join(missing)}"
                )
                continue
            ids.append(rec["id"])
            documents.append(rec["content"])
            embeddings.append(rec["embedding"])  # bitwise pass-through
            md = dict(rec.get("metadata", {}))
            md.setdefault("model_profile", rec["model_profile"])
            metadatas.append(md)
            result.loaded += 1
        if ids:
            coll.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )
        return result

    def count_collection(self, collection: str) -> int:
        return int(self._client.get_or_create_collection(collection).count())

    def probe_non_empty(self) -> dict:
        """Return ``{collection: count}`` for non-empty collections."""
        out: dict[str, int] = {}
        for name in self._client.list_collections():
            n = int(self._client.get_or_create_collection(name).count())
            if n > 0:
                out[name] = n
        return out


__all__ = [
    "ChromaDBWriter",
    "ChromaVersionError",
    "LoadResult",
    "assert_supported_version",
    "missing_required_fields",
    "REQUIRED_RECORD_FIELDS",
]
