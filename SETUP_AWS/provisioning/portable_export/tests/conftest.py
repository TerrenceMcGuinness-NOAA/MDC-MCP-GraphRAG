"""Pytest configuration for the portable_export test suite.

Ensures ``SETUP_AWS/provisioning`` (the parent of the ``portable_export``
package) is importable as a top-level package root regardless of the
operator's working directory, matching the documented invocation
``cd SETUP_AWS/provisioning && python3.12 -m pytest portable_export/tests/ -q``.

Also provides shared fixtures: a tenants.yaml fixture path, a botocore
S3 Stubber factory, and a small synthetic vector/graph corpus reused across
the format-roundtrip and phase tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tests/ -> portable_export/ -> provisioning/
_PROVISIONING_ROOT = Path(__file__).resolve().parents[2]
if str(_PROVISIONING_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROVISIONING_ROOT))

# repo root for locating the real tenants.yaml fixture
_REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def tenants_yaml_path() -> Path:
    """Path to the real tenant catalog used as a parse fixture."""
    return _REPO_ROOT / "mcp_server_python" / "src" / "config" / "tenants.yaml"


@pytest.fixture
def sample_vector_records() -> list[dict]:
    """A small synthetic Vector_Export batch with float embeddings.

    Embeddings deliberately include values whose JSON text round-trip is
    non-trivial (negative, small-magnitude, high-precision) so byte-equality
    assertions are meaningful.
    """
    return [
        {
            "id": "doc_0001",
            "content": "the quick brown fox",
            "embedding": [0.0123456789, -0.0456, 1.0, -1.0],
            "metadata": {"source_file": "a.py", "tenant_id": "gw"},
            "model_profile": "titan1024",
            "collection_name": "mdc-code-context-titan1024",
            "chunk_id": "chunk_0",
        },
        {
            "id": "doc_0002",
            "content": "lazy dog jumps",
            "embedding": [-0.9999999, 3.141592653589793, 0.0, 2.5e-08],
            "metadata": {"source_file": "b.py", "tenant_id": "gw"},
            "model_profile": "titan1024",
            "collection_name": "mdc-code-context-titan1024",
            "chunk_id": "chunk_1",
        },
    ]


@pytest.fixture
def sample_graph_nodes() -> list[dict]:
    """Synthetic graph nodes (label + properties)."""
    return [
        {"id": "n1", "label": "File", "properties": {"path": "a.py", "loc": 42}},
        {"id": "n2", "label": "File", "properties": {"path": "b.py", "loc": 7}},
        {
            "id": "n3",
            "label": "FortranSubroutine",
            "properties": {"name": "calc, sum", "lines": 13},
        },
    ]


@pytest.fixture
def sample_graph_rels() -> list[dict]:
    """Synthetic graph relationships (type + endpoints + properties)."""
    return [
        {"id": "r1", "type": "CALLS", "start": "n1", "end": "n2", "properties": {"count": 3}},
        {"id": "r2", "type": "USES", "start": "n1", "end": "n3", "properties": {}},
    ]
