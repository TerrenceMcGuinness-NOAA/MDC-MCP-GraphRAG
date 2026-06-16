"""Unit tests for portable_export.query_embedder_check (Task 5.1).

Table-driven: every (target, model_profile, has_bedrock) combination resolves
to Query_Compatible or Query_Incompatible per the design matrix.
Query_Incompatible does not block restore, only flags it (R4.3, R4.4, R4.5).
"""

from __future__ import annotations

import pytest

from portable_export.query_embedder_check import (
    QUERY_COMPATIBLE,
    QUERY_INCOMPATIBLE,
    check_compatibility,
    profile_compatibility,
)

ALL_PROFILES = ["mpnet768", "titan1024", "nova256", "nova512", "nova1024", "nova3072"]


@pytest.mark.parametrize("profile", ALL_PROFILES)
def test_aws_target_all_compatible(profile):
    # AWS reimport target: every profile Query_Compatible.
    assert profile_compatibility(profile, target="aws", has_bedrock=False) == QUERY_COMPATIBLE


@pytest.mark.parametrize("profile", ALL_PROFILES)
def test_cots_with_bedrock_all_compatible(profile):
    assert profile_compatibility(profile, target="cots", has_bedrock=True) == QUERY_COMPATIBLE


def test_cots_without_bedrock_only_mpnet_compatible():
    assert profile_compatibility("mpnet768", target="cots", has_bedrock=False) == QUERY_COMPATIBLE
    for p in ["titan1024", "nova256", "nova512", "nova1024", "nova3072"]:
        assert profile_compatibility(p, target="cots", has_bedrock=False) == QUERY_INCOMPATIBLE


def test_check_compatibility_cots_no_bedrock_flags_incompatible():
    res = check_compatibility(
        ["mpnet768", "titan1024", "nova1024"], target="cots", has_bedrock=False
    )
    assert res.all_compatible is False
    assert res.incompatible_profiles == ["nova1024", "titan1024"]
    assert res.per_profile["mpnet768"] == QUERY_COMPATIBLE


def test_check_compatibility_aws_all_ok():
    res = check_compatibility(ALL_PROFILES, target="aws", has_bedrock=False)
    assert res.all_compatible is True
    assert res.incompatible_profiles == []


def test_check_compatibility_dedups_profiles():
    res = check_compatibility(
        ["titan1024", "titan1024", "mpnet768"], target="cots", has_bedrock=True
    )
    assert set(res.per_profile) == {"titan1024", "mpnet768"}
