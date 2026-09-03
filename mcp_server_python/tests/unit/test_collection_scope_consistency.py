"""Scope_Consistency_Check tests (Task 1.3).

shared-scope-query-routing Requirements: 1.6, 1.7, 1.9.

``test_no_scope_drift`` is the drift gate itself: it runs on every
suite invocation against the bundled ``unified_manifest.json`` and
fails, naming every finding, if the built-in table and the manifest
disagree. It is deliberately an ordinary pytest test rather than a
boot-time validation -- failing server startup over a manifest
classification the built-in table already answers correctly is the
wrong trade-off for a read-mostly analysis aid over a production
forecasting system (see design.md, "Scope_Consistency_Check placement").

The remaining tests exercise the four finding classes with synthetic
manifests, so each class is proven reachable independently of whether
the real manifest happens to trigger it today (finding 3 in design.md
notes it currently does not: all 67 sources map cleanly onto 5 targets
with no multi-scope target).
"""

from __future__ import annotations

import json
import socket

import pytest

from src.data import collection_scope as cs


# ---------------------------------------------------------------------------
# The drift gate itself (R1.9)
# ---------------------------------------------------------------------------


def test_no_scope_drift():
    """R1.6, R1.9: the built-in table agrees with the bundled manifest.

    Fails with every finding named if any of the four discrepancy
    classes is detected. This is the guard against the built-in table
    and ``unified_manifest.json`` drifting apart silently.
    """
    findings = cs.check_scope_consistency()
    assert findings == [], (
        "collection_scope drift detected against unified_manifest.json:\n"
        + "\n".join(f"  - {f}" for f in findings)
    )


def test_check_scope_consistency_issues_no_network_request(monkeypatch):
    """R1.7: the check must not touch the network."""

    def _raise(*args, **kwargs):
        raise AssertionError(
            "check_scope_consistency must not open a socket"
        )

    monkeypatch.setattr(socket.socket, "connect", _raise)
    findings = cs.check_scope_consistency()
    assert findings == []


# ---------------------------------------------------------------------------
# Synthetic-manifest cases, one per finding class (R1.6 a-d)
# ---------------------------------------------------------------------------


def _without_hybridity_drift_noise(findings):
    """Drop the built-in Hybrid_Domain's reverse-direction drift finding.

    Several synthetic manifests below declare only the source under
    test and omit ``global-workflow-rst`` (the repo-local source that
    makes ``global-workflow-docs-v8-0-0`` a Hybrid_Domain in the real
    manifest). Against such a manifest,
    :func:`check_scope_consistency` correctly reports that the built-in
    Hybrid_Domain has no enabled repo-local source -- a real, valid
    finding, just not the one these tests target. Filtering it out here
    keeps each test focused on the single finding class its name
    describes; the hybridity-drift direction itself is covered by
    ``test_finding_class_b_does_not_fire_for_hybrid_domain`` and the
    dedicated hybridity tests.
    """
    return [
        f
        for f in findings
        if "global-workflow-docs-v8-0-0' is classified as a Hybrid_Domain"
        not in f
    ]


def _write_manifest(tmp_path, sources):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "version": "0.0.0-test",
                "description": "synthetic",
                "sources": sources,
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def test_finding_class_a_classification_mismatch(tmp_path):
    """(a) built-in classification differs from the sources' declared scope.

    The built-in table classifies ``code-with-context-v8-0-0`` as
    ``tenant``; declaring it ``shared`` in the manifest must surface a
    mismatch finding naming the collection and both values.

    A synthetic single-source manifest also triggers the (separate)
    hybridity-drift finding for ``global-workflow-docs-v8-0-0``, because
    that target's repo-local source is not present in this synthetic
    manifest at all. That finding is a real, independently-covered case
    (see the hybridity-drift tests below) and is filtered out here so
    this test asserts precisely on the class-(a) finding under test.
    """
    manifest_path = _write_manifest(
        tmp_path,
        [
            {
                "name": "fake-code-source",
                "collection_target": "code-with-context-v8-0-0",
                "scope": "shared",
                "enabled": True,
                "source_type": "code_ast",
            }
        ],
    )
    findings = _without_hybridity_drift_noise(
        cs.check_scope_consistency(manifest_path)
    )
    assert len(findings) == 1
    assert "code-with-context-v8-0-0" in findings[0]
    assert "tenant" in findings[0]
    assert "shared" in findings[0]


def test_finding_class_b_multi_scope_non_hybrid_target(tmp_path):
    """(b) a non-Hybrid_Domain target whose enabled sources disagree.

    ``ee2-standards-v5-0-0-enhanced`` is not a Hybrid_Domain; declaring
    two enabled sources with different scopes for it must surface a
    finding naming both declared values.
    """
    manifest_path = _write_manifest(
        tmp_path,
        [
            {
                "name": "ee2-a",
                "collection_target": "ee2-standards-v5-0-0-enhanced",
                "scope": "shared",
                "enabled": True,
                "source_type": "url_crawl",
            },
            {
                "name": "ee2-b",
                "collection_target": "ee2-standards-v5-0-0-enhanced",
                "scope": "tenant",
                "enabled": True,
                "source_type": "url_crawl",
            },
        ],
    )
    findings = cs.check_scope_consistency(manifest_path)
    multi_scope_findings = [f for f in findings if "more than one" in f]
    assert len(multi_scope_findings) == 1
    assert "ee2-standards-v5-0-0-enhanced" in multi_scope_findings[0]


def test_finding_class_b_does_not_fire_for_hybrid_domain(tmp_path):
    """A Hybrid_Domain is allowed multiple scope-adjacent declarations
    without the multi-scope finding firing, as long as the classified
    scope itself is consistent. Only 'shared' is a valid declared value
    for the hybrid target's sources here, so this exercises that the
    check does not spuriously multi-scope-flag a hybrid target when the
    two sources happen to both declare 'shared' and one is repo-local.
    """
    manifest_path = _write_manifest(
        tmp_path,
        [
            {
                "name": "docs-a",
                "collection_target": "global-workflow-docs-v8-0-0",
                "scope": "shared",
                "enabled": True,
                "source_type": "url_crawl",
            },
            {
                "name": "global-workflow-rst",
                "collection_target": "global-workflow-docs-v8-0-0",
                "scope": "shared",
                "enabled": True,
                "source_type": "on_disk_submodule",
            },
        ],
    )
    findings = cs.check_scope_consistency(manifest_path)
    assert findings == []


def test_finding_class_c_missing_scope_value(tmp_path):
    """(c) a source whose scope is absent."""
    manifest_path = _write_manifest(
        tmp_path,
        [
            {
                "name": "no-scope-source",
                "collection_target": "jjobs-v8-0-0",
                "enabled": True,
                "source_type": "jjobs_header",
            }
        ],
    )
    findings = cs.check_scope_consistency(manifest_path)
    assert any("no-scope-source" in f for f in findings)
    assert any("None" in f or "scope" in f for f in findings)


def test_finding_class_c_out_of_range_scope_value(tmp_path):
    """(c) a source whose scope is outside {shared, tenant}."""
    manifest_path = _write_manifest(
        tmp_path,
        [
            {
                "name": "bad-scope-source",
                "collection_target": "jjobs-v8-0-0",
                "scope": "global",
                "enabled": True,
                "source_type": "jjobs_header",
            }
        ],
    )
    findings = cs.check_scope_consistency(manifest_path)
    assert any("bad-scope-source" in f and "global" in f for f in findings)


def test_finding_class_d_target_with_no_table_entry(tmp_path):
    """(d) a collection_target for which the Scope_Authority holds no entry."""
    manifest_path = _write_manifest(
        tmp_path,
        [
            {
                "name": "future-source",
                "collection_target": "future-domain-v1-0-0",
                "scope": "shared",
                "enabled": True,
                "source_type": "url_crawl",
            }
        ],
    )
    findings = cs.check_scope_consistency(manifest_path)
    assert any("future-domain-v1-0-0" in f for f in findings)


def test_hybridity_drift_forward_direction(tmp_path):
    """A shared target with an enabled repo-local source not classified
    as a Hybrid_Domain is reported (the forward direction of the
    hybridity-drift expectation).
    """
    manifest_path = _write_manifest(
        tmp_path,
        [
            {
                "name": "ee2-repo-local",
                "collection_target": "ee2-standards-v5-0-0-enhanced",
                "scope": "shared",
                "enabled": True,
                "source_type": "on_disk_submodule",
            }
        ],
    )
    findings = cs.check_scope_consistency(manifest_path)
    assert any(
        "ee2-standards-v5-0-0-enhanced" in f and "Hybrid_Domain" in f
        for f in findings
    )


def test_hybridity_drift_reverse_direction(tmp_path):
    """The built-in Hybrid_Domain with no enabled repo-local source in
    the manifest is reported (the reverse direction). This is the
    finding filtered out by ``_without_hybridity_drift_noise`` in the
    other synthetic-manifest tests above; asserted directly here.
    """
    manifest_path = _write_manifest(
        tmp_path,
        [
            {
                "name": "jjobs-source",
                "collection_target": "jjobs-v8-0-0",
                "scope": "tenant",
                "enabled": True,
                "source_type": "jjobs_header",
            }
        ],
    )
    findings = cs.check_scope_consistency(manifest_path)
    assert any(
        "global-workflow-docs-v8-0-0" in f and "Hybrid_Domain" in f
        for f in findings
    )


def test_disabled_sources_do_not_trigger_findings(tmp_path):
    """A disabled source with a conflicting scope must not raise a finding.

    Only enabled sources participate in the cross-check -- a disabled
    entry is not part of the "what the tenant actually reaches" answer.
    """
    manifest_path = _write_manifest(
        tmp_path,
        [
            {
                "name": "disabled-conflict",
                "collection_target": "code-with-context-v8-0-0",
                "scope": "shared",
                "enabled": False,
                "source_type": "code_ast",
            }
        ],
    )
    findings = _without_hybridity_drift_noise(
        cs.check_scope_consistency(manifest_path)
    )
    assert findings == []


def test_unreadable_manifest_is_a_finding_not_an_exception(tmp_path):
    """An unreadable manifest reports a finding rather than raising.

    This is the exact failure mode ``check_scope_consistency`` exists
    to catch and must never mask: reading through
    ``src.manifest.loader.load_manifest`` would silently fall back and
    report zero findings for a corrupt file.
    """
    missing_path = str(tmp_path / "does-not-exist.json")
    findings = cs.check_scope_consistency(missing_path)
    assert len(findings) == 1
    assert missing_path in findings[0]


def test_malformed_json_manifest_is_a_finding_not_an_exception(tmp_path):
    bad_path = tmp_path / "malformed.json"
    bad_path.write_text("{not valid json", encoding="utf-8")
    findings = cs.check_scope_consistency(str(bad_path))
    assert len(findings) == 1
    assert str(bad_path) in findings[0]


def test_non_object_manifest_is_a_finding(tmp_path):
    bad_path = tmp_path / "array.json"
    bad_path.write_text("[1, 2, 3]", encoding="utf-8")
    findings = cs.check_scope_consistency(str(bad_path))
    assert len(findings) == 1
    assert "JSON object" in findings[0]


def test_missing_sources_field_is_a_finding(tmp_path):
    bad_path = tmp_path / "no-sources.json"
    bad_path.write_text(json.dumps({"version": "0.0.0"}), encoding="utf-8")
    findings = cs.check_scope_consistency(str(bad_path))
    assert len(findings) == 1
    assert "sources" in findings[0]


def test_gate_failure_message_names_every_injected_finding(tmp_path):
    """R1.9: when check_scope_consistency reports findings, a test built
    the same way as test_no_scope_drift fails with every finding named
    in its output.
    """
    manifest_path = _write_manifest(
        tmp_path,
        [
            {
                "name": "bad-1",
                "collection_target": "jjobs-v8-0-0",
                "scope": "bogus",
                "enabled": True,
                "source_type": "jjobs_header",
            },
            {
                "name": "bad-2",
                "collection_target": "unknown-target-v1",
                "scope": "shared",
                "enabled": True,
                "source_type": "url_crawl",
            },
        ],
    )
    findings = cs.check_scope_consistency(manifest_path)
    assert len(findings) >= 2

    with pytest.raises(AssertionError) as excinfo:
        assert findings == [], (
            "collection_scope drift detected:\n"
            + "\n".join(f"  - {f}" for f in findings)
        )
    message = str(excinfo.value)
    for finding in findings:
        assert finding in message
