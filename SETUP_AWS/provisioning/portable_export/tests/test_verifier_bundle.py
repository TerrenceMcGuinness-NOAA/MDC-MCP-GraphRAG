"""Verifier + bundle unit tests (Task 12.1).

Mismatched counts trigger a non-zero exit with enumerated mismatches; tolerance
applies per R10.1; bundle pack -> unpack yields byte-equivalent layout to
S3-native (R12.4).

Requirements: 10.2, 10.3, 12.4.
"""

from __future__ import annotations

import boto3
import pytest
from botocore.stub import Stubber

from portable_export.bundle import (
    BundleLayoutError,
    pack_objects,
    unpack_objects,
    pack_from_dir,
    unpack_to_dir,
)
from portable_export.manifest import ExportManifest, GraphExportEntry, VectorExportEntry
from portable_export.phases.count_parity import (
    compare_counts,
    run_parity_check,
    source_counts,
)


def _manifest():
    m = ExportManifest.new(manifest_id="m", tenants=["gw"])
    m.add_vector_export(VectorExportEntry(
        tenant_id="gw", collection_name="mdc-code-context-titan1024",
        model_profile="titan1024", record_count=100))
    m.add_graph_export(GraphExportEntry(
        tenant_id="gw", node_count=50, relationship_count=200))
    return m


# ── Count parity ──────────────────────────────────────────────────────────────


def test_parity_pass_when_all_match():
    m = _manifest()
    dst = source_counts(m)  # destination equals source
    report = compare_counts(source_counts(m), dst)
    assert report.passed is True
    assert report.exit_status == 0
    assert report.mismatches == []


def test_parity_fail_enumerates_mismatches():
    m = _manifest()
    src = source_counts(m)
    dst = source_counts(m)
    dst["collection"]["mdc-code-context-titan1024"] = 90  # short by 10
    report = compare_counts(src, dst)
    assert report.passed is False
    assert report.exit_status == 1
    keys = {(mm.dimension, mm.key) for mm in report.mismatches}
    assert ("collection", "mdc-code-context-titan1024") in keys
    bad = next(mm for mm in report.mismatches if mm.key == "mdc-code-context-titan1024"
               and mm.dimension == "collection")
    assert bad.source == 100 and bad.destination == 90


def test_parity_tolerance_allows_small_delta():
    m = _manifest()
    src = source_counts(m)
    dst = source_counts(m)
    dst["collection"]["mdc-code-context-titan1024"] = 99  # 1% short
    # 0 tolerance fails
    assert compare_counts(src, dst, tolerance=0.0).passed is False
    # 5% tolerance passes
    assert compare_counts(src, dst, tolerance=0.05).passed is True


def test_run_parity_writes_report_to_s3():
    m = _manifest()
    s3 = boto3.client("s3", region_name="us-east-1")
    stub = Stubber(s3)
    stub.add_response("put_object", {}, None)  # accept any put params
    with stub:
        report = run_parity_check(m, source_counts(m), s3_client=s3,
                                  bucket="b", prefix="pfx/")
    assert report.passed is True


# ── Bundle ────────────────────────────────────────────────────────────────────


def test_bundle_requires_manifest():
    with pytest.raises(BundleLayoutError):
        pack_objects({"vectors/gw/c/000.jsonl.gz": b"x"})


def test_bundle_pack_unpack_byte_equivalent():
    objects = {
        "manifest.json": b'{"schema_version":"1.0.0"}',
        "vectors/gw/c/000.jsonl.gz": b"\x1f\x8b vector bytes",
        "graph/gw/nodes/File-000.csv.gz": b"\x1f\x8b node bytes",
        "dedupe/gw/000.jsonl.gz": b"\x1f\x8b dedupe bytes",
    }
    bundle = pack_objects(objects)
    restored = unpack_objects(bundle)
    # byte-equivalent layout (R12.4)
    assert restored == objects


def test_bundle_unpack_missing_manifest_refused():
    # build a tarball without manifest by packing then... easier: craft directly
    import io, tarfile, gzip
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        data = b"x"
        info = tarfile.TarInfo(name="vectors/gw/c/000.jsonl.gz")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=0) as g:
        g.write(raw.getvalue())
    with pytest.raises(BundleLayoutError):
        unpack_objects(gz.getvalue())


def test_bundle_dir_roundtrip(tmp_path):
    src = tmp_path / "export"
    (src / "vectors" / "gw" / "c").mkdir(parents=True)
    (src / "manifest.json").write_bytes(b'{"schema_version":"1.0.0"}')
    (src / "vectors" / "gw" / "c" / "000.jsonl.gz").write_bytes(b"data")
    bundle = pack_from_dir(src)
    out = tmp_path / "restored"
    keys = unpack_to_dir(bundle, out)
    assert "manifest.json" in keys
    assert (out / "vectors" / "gw" / "c" / "000.jsonl.gz").read_bytes() == b"data"


def test_bundle_is_deterministic():
    objects = {"manifest.json": b"m", "a/b.gz": b"x"}
    assert pack_objects(objects) == pack_objects(objects)
