"""Unit tests for cost_control.drift (Task 11.1).

Table-driven: added ECR tag / new index -> preserving; missing snapshot /
deleted referenced image / changed bucket retention / disappeared index ->
destructive; plus the --force-drift override path.

Requirements: 10.2, 10.3.
"""

from __future__ import annotations

import pytest

from cost_control.drift import (
    DESTRUCTIVE,
    PRESERVING,
    classify_drift,
    evaluate,
)


def test_no_drift_is_empty():
    prev = {"ecr_image_tags": ["v1"], "opensearch_indices": ["idx"]}
    cur = {"ecr_image_tags": ["v1"], "opensearch_indices": ["idx"]}
    result = classify_drift(prev, cur)
    assert result.deltas == []
    assert result.has_destructive is False


def test_added_ecr_tag_is_preserving():
    prev = {"ecr_image_tags": ["v1"]}
    cur = {"ecr_image_tags": ["v1", "v2"]}
    result = classify_drift(prev, cur)
    assert len(result.preserving) == 1
    assert result.preserving[0].category == "ecr_image"
    assert not result.has_destructive


def test_new_index_is_preserving():
    prev = {"opensearch_indices": ["a"]}
    cur = {"opensearch_indices": ["a", "b"]}
    result = classify_drift(prev, cur)
    assert result.preserving[0].category == "opensearch_index"
    assert not result.has_destructive


def test_disappeared_index_is_destructive():
    prev = {"opensearch_indices": ["a", "b"]}
    cur = {"opensearch_indices": ["a"]}
    result = classify_drift(prev, cur)
    assert result.has_destructive
    assert result.destructive[0].detail["index"] == "b"


def test_deleted_referenced_image_is_destructive():
    prev = {"ecr_image_tags": ["v1", "v2"]}
    cur = {"ecr_image_tags": ["v1"], "referenced_image_tags": ["v2"]}
    result = classify_drift(prev, cur)
    assert result.has_destructive
    assert result.destructive[0].detail["tag"] == "v2"


def test_deleted_unreferenced_image_is_preserving():
    prev = {"ecr_image_tags": ["v1", "old"]}
    cur = {"ecr_image_tags": ["v1"], "referenced_image_tags": ["v1"]}
    result = classify_drift(prev, cur)
    assert not result.has_destructive
    assert any(d.detail["tag"] == "old" for d in result.preserving)


def test_missing_required_snapshot_is_destructive():
    prev = {"required_snapshots": {"neptune": "cc-dev-x-neptune"}}
    cur = {"available_snapshots": []}
    result = classify_drift(prev, cur)
    assert result.has_destructive
    assert result.destructive[0].category == "snapshot"


def test_present_required_snapshot_is_clean():
    prev = {"required_snapshots": {"neptune": "snap-1"}}
    cur = {"available_snapshots": ["snap-1"]}
    result = classify_drift(prev, cur)
    assert not result.has_destructive


def test_changed_bucket_retention_is_destructive():
    prev = {"bucket_retention": {"snapshots": "30d"}}
    cur = {"bucket_retention": {"snapshots": "1d"}}
    result = classify_drift(prev, cur)
    assert result.has_destructive
    assert result.destructive[0].category == "bucket_retention"


def test_evaluate_refuses_on_destructive_without_force():
    prev = {"opensearch_indices": ["a", "b"]}
    cur = {"opensearch_indices": ["a"]}
    proceed, result = evaluate(prev, cur, force_drift=False)
    assert proceed is False
    assert result.has_destructive


def test_evaluate_proceeds_on_destructive_with_force():
    prev = {"opensearch_indices": ["a", "b"]}
    cur = {"opensearch_indices": ["a"]}
    proceed, result = evaluate(prev, cur, force_drift=True)
    assert proceed is True
    assert result.has_destructive  # still reported, just overridden


def test_evaluate_proceeds_on_preserving_only():
    prev = {"ecr_image_tags": ["v1"]}
    cur = {"ecr_image_tags": ["v1", "v2"]}
    proceed, result = evaluate(prev, cur)
    assert proceed is True
    assert not result.has_destructive
    assert result.preserving
