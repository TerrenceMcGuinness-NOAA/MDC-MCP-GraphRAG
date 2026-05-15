#!/usr/bin/env python3
"""
test_embedding_registry_properties.py — Property tests for Tasks 1.2, 1.4, 1.6.

Properties:
  P1: get_profile(short_name) returns dimensions > 0 and provider in {"local","bedrock"}
  P2: get_profile(unknown) raises KeyError listing available profiles
  P3: provider.embed([text]) returns vector of length == profile.dimensions (LocalProvider only)
  P4: get_name() is deterministic and ends with -{profile.short_name}
  P5: is_legacy_name() returns True for names without model suffix

Run: python test_embedding_registry_properties.py
"""

import sys
import os

# Allow running from scripts/ directory
sys.path.insert(0, os.path.dirname(__file__))

from embedding_registry import EmbeddingModelRegistry, ModelProfile
from collection_namer import CollectionNamer


def test_p1_profile_invariants():
    """P1: Every registered profile has dimensions > 0 and valid provider."""
    reg = EmbeddingModelRegistry()
    for name in reg.list_profiles():
        p = reg.get_profile(name)
        assert p.dimensions > 0, f"P1 FAIL: {name}.dimensions={p.dimensions}"
        assert p.provider in {"local", "bedrock"}, f"P1 FAIL: {name}.provider={p.provider}"
    print("[OK] P1: all profiles have dimensions > 0 and valid provider")


def test_p2_unknown_raises_keyerror():
    """P2: get_profile(unknown) raises KeyError listing available profiles."""
    reg = EmbeddingModelRegistry()
    for unknown in ["nonexistent", "gpt4", "", "MPNET768"]:
        try:
            reg.get_profile(unknown)
            assert False, f"P2 FAIL: expected KeyError for '{unknown}'"
        except KeyError as e:
            msg = str(e)
            # Error message should mention available profiles
            for name in reg.list_profiles():
                assert name in msg, f"P2 FAIL: '{name}' not in error message: {msg}"
    print("[OK] P2: unknown short_name raises KeyError with available profiles listed")


def test_p3_embedding_dimension_consistency():
    """P3: LocalProvider.embed([text]) returns vector of length == profile.dimensions."""
    reg = EmbeddingModelRegistry()
    try:
        from embedding_provider import LocalProvider
        profile = reg.get_profile("mpnet768")
        provider = LocalProvider(profile)
        test_texts = [
            "hello world",
            "NOAA global workflow forecast system",
            "x",
        ]
        for text in test_texts:
            vecs = provider.embed([text])
            assert len(vecs) == 1, f"P3 FAIL: expected 1 vector, got {len(vecs)}"
            assert len(vecs[0]) == profile.dimensions, (
                f"P3 FAIL: expected {profile.dimensions} dims, got {len(vecs[0])}"
            )
        print(f"[OK] P3: LocalProvider produces {profile.dimensions}-dim vectors")
    except ImportError as e:
        print(f"[SKIP] P3: sentence-transformers not available ({e})")


def test_p4_naming_determinism():
    """P4: get_name() is deterministic and ends with -{profile.short_name}."""
    reg = EmbeddingModelRegistry()
    domains = ["code-with-context", "workflow-docs", "jjobs"]
    versions = ["v8-0-0", "v9-0-0"]
    for name in reg.list_profiles():
        profile = reg.get_profile(name)
        namer = CollectionNamer(profile)
        for domain in domains:
            for version in versions:
                result1 = namer.get_name(domain, version)
                result2 = namer.get_name(domain, version)
                assert result1 == result2, f"P4 FAIL: non-deterministic for {domain}/{version}"
                assert result1.endswith(f"-{profile.short_name}"), (
                    f"P4 FAIL: '{result1}' does not end with '-{profile.short_name}'"
                )
    print("[OK] P4: get_name() is deterministic and encodes model suffix")


def test_p5_legacy_name_detection():
    """P5: is_legacy_name() returns True for names without model suffix."""
    legacy_names = [
        "code-with-context-v8-0-0",
        "global-workflow-docs-v8-0-0",
        "jjobs-v8-0-0",
        "community-summaries",
        "ee2-standards-v5-0-0-enhanced",
    ]
    for name in legacy_names:
        assert CollectionNamer.is_legacy_name(name), f"P5 FAIL: '{name}' should be legacy"

    # Model-aware names should NOT be legacy
    reg = EmbeddingModelRegistry()
    for short_name in reg.list_profiles():
        model_aware = f"code-with-context-v8-0-0-{short_name}"
        assert not CollectionNamer.is_legacy_name(model_aware), (
            f"P5 FAIL: '{model_aware}' should NOT be legacy"
        )
    print("[OK] P5: is_legacy_name() correctly identifies legacy vs model-aware names")


def main():
    print("=" * 60)
    print("Property Tests: Embedding Registry, Provider, Collection Namer")
    print("=" * 60)
    test_p1_profile_invariants()
    test_p2_unknown_raises_keyerror()
    test_p3_embedding_dimension_consistency()
    test_p4_naming_determinism()
    test_p5_legacy_name_detection()
    print("\n[PASS] All property tests passed")


if __name__ == "__main__":
    main()
