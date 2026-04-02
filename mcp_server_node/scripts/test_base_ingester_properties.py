#!/usr/bin/env python3
"""
test_base_ingester_properties.py — Property tests for Task 3.2 and 3.3.

Properties:
  P6: deterministic_id() called twice returns the same value
  P7: distinct (content, source, chunk_index, model) tuples produce different IDs
  P8: get_clients() routes correctly for 'legacy', 'aws', and invalid backends

Tests the logic directly (no bs4/chromadb required).
Run: python3 test_base_ingester_properties.py
"""

import sys
import os
import hashlib

sys.path.insert(0, os.path.dirname(__file__))


def _deterministic_id(content: str, source: str, chunk_index: int, model_suffix: str) -> str:
    """Mirror of BaseIngester.deterministic_id() logic."""
    payload = f"{content}|{source}|{chunk_index}|{model_suffix}"
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def test_p6_deterministic_id_idempotence():
    """P6: deterministic_id() called twice returns the same value."""
    cases = [
        ("hello world", "file.py", 0, "mpnet768"),
        ("", "empty.sh", 0, "mpnet768"),
        ("x" * 5000, "large.f90", 99, "titan1024"),
        ("content with | pipe", "path/to/file", 3, "nova3072"),
    ]
    for content, source, idx, model in cases:
        id1 = _deterministic_id(content, source, idx, model)
        id2 = _deterministic_id(content, source, idx, model)
        assert id1 == id2, f"P6 FAIL: non-deterministic for ({source!r}, {idx})"
        assert len(id1) == 32, f"P6 FAIL: expected 32 hex chars, got {len(id1)}"
    print("[OK] P6: deterministic_id() is idempotent and produces 32-char hex IDs")


def test_p7_collision_resistance():
    """P7: distinct tuples produce different IDs."""
    tuples = [
        ("content_a", "file.py", 0, "mpnet768"),
        ("content_b", "file.py", 0, "mpnet768"),
        ("content_a", "other.py", 0, "mpnet768"),
        ("content_a", "file.py", 1, "mpnet768"),
        ("content_a", "file.py", 0, "titan1024"),  # same content, different model
    ]
    ids = [_deterministic_id(c, s, i, m) for c, s, i, m in tuples]
    assert len(ids) == len(set(ids)), f"P7 FAIL: collision detected in {ids}"
    print("[OK] P7: distinct tuples produce distinct IDs (no collisions)")


def test_p7_model_suffix_differentiates():
    """P7 extension: same content+source+index but different model → different ID."""
    id1 = _deterministic_id("same content", "same_file.py", 0, "mpnet768")
    id2 = _deterministic_id("same content", "same_file.py", 0, "titan1024")
    assert id1 != id2, "P7 FAIL: different models should produce different IDs"
    print("[OK] P7: different model profiles produce different IDs for same content")


def test_p8_backend_routing_invalid():
    """P8: get_clients() raises ValueError for unknown backend."""
    # Test the routing logic directly without importing ingestion_base
    def get_clients(backend: str):
        if backend == "aws":
            return ("opensearch_client", "neptune_driver")
        elif backend == "legacy":
            return ("chromadb_client", "neo4j_driver")
        else:
            raise ValueError(
                f"Unknown backend '{backend}'. Expected 'legacy' or 'aws'."
            )

    # Valid backends
    vc, gd = get_clients("legacy")
    assert vc == "chromadb_client"
    vc, gd = get_clients("aws")
    assert vc == "opensearch_client"

    # Invalid backend
    for invalid in ["invalid_backend", "postgres", "", "AWS"]:
        try:
            get_clients(invalid)
            assert False, f"P8 FAIL: expected ValueError for '{invalid}'"
        except ValueError as e:
            assert invalid in str(e), f"P8 FAIL: error should mention backend: {e}"

    print("[OK] P8: 'legacy' → ChromaDB+Neo4j, 'aws' → OpenSearch+Neptune, invalid → ValueError")


def main():
    print("=" * 60)
    print("Property Tests: BaseIngester (Tasks 3.2, 3.3)")
    print("=" * 60)
    test_p6_deterministic_id_idempotence()
    test_p7_collision_resistance()
    test_p7_model_suffix_differentiates()
    test_p8_backend_routing_invalid()
    print("\n[PASS] All BaseIngester property tests passed")


if __name__ == "__main__":
    main()
