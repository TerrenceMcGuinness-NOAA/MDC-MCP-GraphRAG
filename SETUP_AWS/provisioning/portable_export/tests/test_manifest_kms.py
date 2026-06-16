"""Unit tests for portable_export.manifest + kms_writer (Task 4.1).

Covers Requirements 11.3 (schema major-mismatch refusal) and 13.2 (streaming
SHA-256 correctness) plus the bucket-encryption guard.
"""

from __future__ import annotations

import hashlib
import json

import boto3
import pytest
from botocore.stub import Stubber

from portable_export.kms_writer import (
    BucketEncryptionError,
    ChecksumMismatch,
    KmsWriter,
    assert_bucket_encrypted,
    compute_sha256,
    verify_sha256,
)
from portable_export.manifest import (
    ExportManifest,
    GraphExportEntry,
    ManifestInvalid,
    ManifestSchemaUnsupported,
    VectorExportEntry,
    manifest_key,
    read_manifest,
    validate_compatibility,
)


# ── Manifest ────────────────────────────────────────────────────────────────


def test_manifest_roundtrip():
    m = ExportManifest.new(manifest_id="mid-1", tenants=["gw", "gw_v17"],
                           produced_by="arn:op")
    m.add_model_profile("titan1024", dimensions=1024, provider="bedrock",
                        model_id="amazon.titan-embed-text-v2:0")
    m.add_vector_export(VectorExportEntry(
        tenant_id="gw", collection_name="mdc-code-context-titan1024",
        model_profile="titan1024", record_count=3,
        parts=["vectors/gw/mdc-code-context-titan1024/000.jsonl.gz"],
        sha256_per_part=["ab12"]))
    m.add_graph_export(GraphExportEntry(
        tenant_id="gw", node_count=5, relationship_count=9))
    m.recompute_totals()
    assert m.totals["vector_records"] == 3
    assert m.totals["graph_nodes"] == 5
    assert m.totals["graph_relationships"] == 9

    raw = m.to_json()
    m2 = ExportManifest.from_json(raw)
    assert m2.manifest_id == "mid-1"
    assert m2.tenants == ["gw", "gw_v17"]
    assert m2.vector_exports[0].record_count == 3
    assert m2.graph_exports[0].relationship_count == 9
    assert m2.model_profiles["titan1024"]["dimensions"] == 1024


def test_validate_compatibility_accepts_equal_major():
    data = {"schema_version": "1.5.2"}
    validate_compatibility(data, supported_schema_version="1.0.0")  # no raise


def test_validate_compatibility_refuses_higher_major():
    data = {"schema_version": "2.0.0"}
    with pytest.raises(ManifestSchemaUnsupported):
        validate_compatibility(data, supported_schema_version="1.0.0")


def test_validate_compatibility_missing_version():
    with pytest.raises(ManifestInvalid):
        validate_compatibility({}, supported_schema_version="1.0.0")


def test_from_dict_missing_required_field():
    with pytest.raises(ManifestInvalid):
        ExportManifest.from_dict({"manifest_id": "x"})


def test_read_manifest_refuses_unsupported(monkeypatch):
    s3 = boto3.client("s3", region_name="us-east-1")
    stub = Stubber(s3)
    bad = json.dumps({
        "schema_version": "9.0.0", "manifest_id": "m", "produced_at": "t",
        "tool_version": "x", "tenants": [], "scope": {}, "model_profiles": {},
        "totals": {},
    }).encode("utf-8")
    stub.add_response(
        "get_object", {"Body": _streaming(bad)},
        {"Bucket": "b", "Key": manifest_key("pfx/")},
    )
    with stub:
        with pytest.raises(ManifestSchemaUnsupported):
            read_manifest(s3, "b", "pfx/")


def test_read_manifest_ok():
    s3 = boto3.client("s3", region_name="us-east-1")
    stub = Stubber(s3)
    m = ExportManifest.new(manifest_id="m", tenants=["gw"])
    stub.add_response(
        "get_object", {"Body": _streaming(m.to_json())},
        {"Bucket": "b", "Key": manifest_key("pfx/")},
    )
    with stub:
        got = read_manifest(s3, "b", "pfx/")
    assert got.manifest_id == "m"


def _streaming(data: bytes):
    from botocore.response import StreamingBody
    import io
    return StreamingBody(io.BytesIO(data), len(data))


# ── KMS writer ───────────────────────────────────────────────────────────────


def test_compute_and_verify_sha256():
    body = b"hello world"
    expected = hashlib.sha256(body).hexdigest()
    assert compute_sha256(body) == expected
    # streaming over chunks gives same digest
    assert compute_sha256([b"hello ", b"world"]) == expected
    verify_sha256(body, expected)
    with pytest.raises(ChecksumMismatch):
        verify_sha256(body, "deadbeef")


def test_assert_bucket_encrypted_ok():
    s3 = boto3.client("s3", region_name="us-east-1")
    stub = Stubber(s3)
    stub.add_response("get_bucket_encryption", {
        "ServerSideEncryptionConfiguration": {"Rules": [
            {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}
        ]}}, {"Bucket": "b"})
    with stub:
        assert assert_bucket_encrypted(s3, "b") == "aws:kms"


def test_assert_bucket_encrypted_refuses_unencrypted():
    s3 = boto3.client("s3", region_name="us-east-1")
    stub = Stubber(s3)
    stub.add_client_error(
        "get_bucket_encryption",
        service_error_code="ServerSideEncryptionConfigurationNotFoundError",
        expected_params={"Bucket": "b"},
    )
    with stub:
        with pytest.raises(BucketEncryptionError):
            assert_bucket_encrypted(s3, "b")


def test_kms_writer_put_returns_sha_and_sets_sse():
    s3 = boto3.client("s3", region_name="us-east-1")
    stub = Stubber(s3)
    body = b'{"id":"d1"}\n'
    expected = hashlib.sha256(body).hexdigest()
    # guard check
    stub.add_response("get_bucket_encryption", {
        "ServerSideEncryptionConfiguration": {"Rules": [
            {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}
        ]}}, {"Bucket": "b"})
    stub.add_response("put_object", {}, {
        "Bucket": "b", "Key": "k", "Body": body,
        "ContentType": "application/gzip",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": "arn:kms:key",
    })
    w = KmsWriter(s3, "b", kms_key_arn="arn:kms:key")
    with stub:
        digest = w.put("k", body, content_type="application/gzip")
    assert digest == expected
    stub.assert_no_pending_responses()
