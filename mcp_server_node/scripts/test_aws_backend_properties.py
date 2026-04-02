#!/usr/bin/env python3
"""
test_aws_backend_properties.py — Property tests for Task 6.2.

Properties:
  P9:  Legacy collection names map to the same index as COLLECTION_TO_INDEX
  P10: Model-aware collection names map to an index that includes the model suffix

Run: python3 test_aws_backend_properties.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

# Import _to_index and COLLECTION_TO_INDEX directly (no AWS credentials needed)
from aws_backend import _to_index, COLLECTION_TO_INDEX


def test_p9_legacy_mapping_preserved():
    """P9: Legacy collection names map to the same index as COLLECTION_TO_INDEX."""
    for col, expected_index in COLLECTION_TO_INDEX.items():
        result = _to_index(col)
        assert result == expected_index, (
            f"P9 FAIL: _to_index('{col}') = '{result}', expected '{expected_index}'"
        )
    print("[OK] P9: all legacy collection names map to correct base indices")


def test_p10_model_aware_includes_suffix():
    """P10: Model-aware collection names map to an index that includes the model suffix."""
    model_aware_cases = [
        ("code-with-context-v8-0-0-mpnet768",      "mdc-code-context-mpnet768"),
        ("code-with-context-v8-0-0-titan1024",     "mdc-code-context-titan1024"),
        ("global-workflow-docs-v8-0-0-nova3072",   "mdc-workflow-docs-nova3072"),
        ("jjobs-v8-0-0-mpnet768",                  "mdc-jjobs-mpnet768"),
        ("community-summaries-nova1024",            "mdc-community-summaries-nova1024"),
        ("ee2-standards-v5-0-0-enhanced-mpnet768", "mdc-ee2-standards-mpnet768"),
    ]
    for col, expected in model_aware_cases:
        result = _to_index(col)
        # Extract the model suffix from the collection name
        suffix = col.rsplit("-", 1)[-1]
        assert suffix in result, (
            f"P10 FAIL: model suffix '{suffix}' not in index '{result}' for '{col}'"
        )
        assert result == expected, (
            f"P10 FAIL: _to_index('{col}') = '{result}', expected '{expected}'"
        )
    print("[OK] P10: model-aware collection names map to indices with model suffix")


def test_p10_legacy_names_not_affected():
    """P10 complement: legacy names are NOT affected by model-aware routing."""
    for col in COLLECTION_TO_INDEX:
        result = _to_index(col)
        # Should not have any model suffix appended
        for suffix in ["mpnet768", "titan1024", "nova256", "nova512", "nova1024", "nova3072"]:
            assert not result.endswith(f"-{suffix}"), (
                f"P10 FAIL: legacy '{col}' should not get model suffix, got '{result}'"
            )
    print("[OK] P10: legacy collection names are not modified by model-aware routing")


def main():
    print("=" * 60)
    print("Property Tests: aws_backend._to_index() (Task 6.2)")
    print("=" * 60)
    test_p9_legacy_mapping_preserved()
    test_p10_model_aware_includes_suffix()
    test_p10_legacy_names_not_affected()
    print("\n[PASS] All aws_backend property tests passed")


if __name__ == "__main__":
    main()
