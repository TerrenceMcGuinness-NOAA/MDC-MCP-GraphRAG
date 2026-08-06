"""Unit tests for _ingest_provenance.build_provenance.

Feature: disk-priority-ingest, Requirement 3 (provenance stamping).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add scripts/ to path for direct import
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from _ingest_provenance import build_provenance

EXPECTED_KEYS = {
    "source_name",
    "source_kind",
    "resolved_path",
    "commit_sha",
    "dirty",
    "embedding_profile",
    "dimension",
}


class TestBuildProvenance:
    def test_returns_every_additive_key(self):
        prov = build_provenance(
            source_name="gsi-user-guide",
            source_kind="disk",
            resolved_path="/w/sorc/gsi_enkf.fd/README.md",
            commit_sha="abc123",
            dirty=False,
            profile="titan1024",
            dimension=1024,
        )
        assert set(prov.keys()) == EXPECTED_KEYS

    def test_source_name_is_recorded(self):
        """The owning manifest source is stamped, not inferred from the path."""
        prov = build_provenance(
            source_name="cice",
            source_kind="disk",
            resolved_path="/w/sorc/ufs_model.fd/CICE-interface/CICE/doc/index.rst",
            commit_sha="abc123",
            dirty=False,
            profile="titan1024",
            dimension=1024,
        )
        assert prov["source_name"] == "cice"

    def test_omits_nothing_no_none_key_dropped(self):
        """Even when values are None/falsey, the keys are still present."""
        prov = build_provenance(
            source_name="global-workflow-rst",
            source_kind="disk",
            resolved_path=None,
            commit_sha=None,
            dirty=False,
            profile="mpnet768",
            dimension=768,
        )
        assert set(prov.keys()) == EXPECTED_KEYS
        assert prov["resolved_path"] is None
        assert prov["commit_sha"] is None
        assert prov["source_name"] == "global-workflow-rst"

    def test_changes_no_existing_meta_key(self):
        """Merging provenance into an existing doc_meta leaves originals intact."""
        doc_meta = {
            "tenant_id": "gw",
            "source": "/w/docs/index.rst",
            "content_sha256": "deadbeef",
        }
        original = dict(doc_meta)
        prov = build_provenance(
            source_name="global-workflow-rst",
            source_kind="disk",
            resolved_path="/w/docs/index.rst",
            commit_sha="abc123",
            dirty=True,
            profile="titan1024",
            dimension=1024,
        )
        merged = {**doc_meta, **prov}
        # No pre-existing key was overwritten or removed.
        for k, v in original.items():
            assert merged[k] == v
        # The three original keys plus the provenance keys, no collisions.
        assert EXPECTED_KEYS.isdisjoint(original.keys())
        assert set(merged.keys()) == set(original.keys()) | EXPECTED_KEYS

    def test_source_name_is_required_keyword(self):
        """source_name is mandatory — a caller cannot silently omit it."""
        with pytest.raises(TypeError):
            build_provenance(  # type: ignore[call-arg]
                source_kind="disk",
                resolved_path="/w/x",
                commit_sha="c0ffee",
                dirty=False,
                profile="titan1024",
                dimension=1024,
            )

    def test_resolved_path_is_stringified(self):
        prov = build_provenance(
            source_name="ufs-utils",
            source_kind="disk",
            resolved_path=Path("/w/docs/a.md"),
            commit_sha="c0ffee",
            dirty=False,
            profile="titan1024",
            dimension=1024,
        )
        assert prov["resolved_path"] == "/w/docs/a.md"
        assert isinstance(prov["resolved_path"], str)

    def test_dirty_coerced_to_bool(self):
        prov = build_provenance(
            source_name="ufs-utils",
            source_kind="disk",
            resolved_path="/w/x",
            commit_sha="c0ffee",
            dirty=1,  # truthy non-bool
            profile="titan1024",
            dimension=1024,
        )
        assert prov["dirty"] is True
