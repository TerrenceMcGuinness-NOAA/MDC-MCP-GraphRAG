"""Unit tests for cost_control.state_file (Task 3.1) including Property 7.

Property 7 (concurrency refusal): two racing writers read the same ETag; at
most one write succeeds, the other receives an S3 PreconditionFailed (412)
mapped to ConcurrentOperationError.

Requirements: 8.3, 8.4, 7.3, 7.4.
"""

from __future__ import annotations

import io
import json

import boto3
import pytest
from botocore.stub import Stubber

from cost_control import state_file as sf
from cost_control.state_file import (
    ConcurrentOperationError,
    CorruptStateError,
    MissingStateError,
    StateFile,
    bump,
    new_initial_document,
    validate_document,
)

BUCKET = "mdc-mcp-rag-cost-control-state-dev"
KEY = "cost-control/dev/state.json"


def _s3():
    # Region-pinned client; Stubber intercepts all calls (no network).
    return boto3.client("s3", region_name="us-east-1")


def _body(doc):
    return io.BytesIO(json.dumps(doc).encode("utf-8"))


def _doc(**overrides):
    d = new_initial_document("dev")
    d.update(overrides)
    return d


# ── schema ─────────────────────────────────────────────────────────────────

def test_new_initial_document_is_valid_and_active():
    d = new_initial_document("dev")
    assert validate_document(d) is d
    assert d["current_state"] == "Active_Mode"
    assert d["operation_counter"] == 0
    assert d["schema_version"] == sf.SCHEMA_VERSION


def test_validate_rejects_non_dict():
    with pytest.raises(CorruptStateError):
        validate_document(["not", "a", "dict"])


def test_validate_rejects_missing_field():
    d = new_initial_document("dev")
    del d["operation_counter"]
    with pytest.raises(CorruptStateError):
        validate_document(d)


def test_validate_rejects_unknown_state():
    with pytest.raises(CorruptStateError):
        validate_document(_doc(current_state="Hibernating"))


def test_validate_rejects_bool_counter():
    # bool is an int subclass; must be rejected explicitly.
    with pytest.raises(CorruptStateError):
        validate_document(_doc(operation_counter=True))


def test_bump_increments_by_exactly_one():
    d = _doc(operation_counter=41)
    out = bump(d)
    assert out["operation_counter"] == 42
    # original untouched (shallow copy)
    assert d["operation_counter"] == 41


# ── read ─────────────────────────────────────────────────────────────────

def test_read_success_returns_doc_and_etag():
    client = _s3()
    doc = _doc(operation_counter=7)
    with Stubber(client) as stub:
        stub.add_response(
            "get_object",
            {"Body": _body(doc), "ETag": '"abc123"'},
            {"Bucket": BUCKET, "Key": KEY},
        )
        got, etag = StateFile(client, BUCKET, KEY).read()
    assert got["operation_counter"] == 7
    assert etag == "abc123"


def test_read_missing_object_raises_missing():
    client = _s3()
    with Stubber(client) as stub:
        stub.add_client_error(
            "get_object",
            service_error_code="NoSuchKey",
            http_status_code=404,
        )
        with pytest.raises(MissingStateError):
            StateFile(client, BUCKET, KEY).read()


def test_read_corrupt_json_raises_corrupt():
    client = _s3()
    with Stubber(client) as stub:
        stub.add_response(
            "get_object",
            {"Body": io.BytesIO(b"{not json"), "ETag": '"e"'},
            {"Bucket": BUCKET, "Key": KEY},
        )
        with pytest.raises(CorruptStateError):
            StateFile(client, BUCKET, KEY).read()


def test_read_schema_invalid_raises_corrupt():
    client = _s3()
    bad = {"current_state": "Active_Mode"}  # missing most fields
    with Stubber(client) as stub:
        stub.add_response(
            "get_object",
            {"Body": _body(bad), "ETag": '"e"'},
            {"Bucket": BUCKET, "Key": KEY},
        )
        with pytest.raises(CorruptStateError):
            StateFile(client, BUCKET, KEY).read()


# ── write ──────────────────────────────────────────────────────────────────

def test_write_with_etag_uses_ifmatch_and_returns_new_etag():
    client = _s3()
    doc = bump(_doc(current_state="Sleeping"))
    with Stubber(client) as stub:
        # Expect IfMatch on the conditional write.
        stub.add_response(
            "put_object",
            {"ETag": '"newetag"'},
            {
                "Bucket": BUCKET,
                "Key": KEY,
                "Body": json.dumps(doc, ensure_ascii=True, sort_keys=True).encode("utf-8"),
                "ContentType": "application/json",
                "IfMatch": "oldetag",
            },
        )
        new_etag = StateFile(client, BUCKET, KEY).write(doc, "oldetag")
    assert new_etag == "newetag"


def test_write_create_if_absent_uses_ifnonematch():
    client = _s3()
    doc = _doc()
    with Stubber(client) as stub:
        stub.add_response(
            "put_object",
            {"ETag": '"created"'},
            {
                "Bucket": BUCKET,
                "Key": KEY,
                "Body": json.dumps(doc, ensure_ascii=True, sort_keys=True).encode("utf-8"),
                "ContentType": "application/json",
                "IfNoneMatch": "*",
            },
        )
        new_etag = StateFile(client, BUCKET, KEY).write(doc, None)
    assert new_etag == "created"


def test_write_stale_etag_raises_concurrent():
    client = _s3()
    doc = bump(_doc(current_state="Sleeping", last_caller_arn="arn:aws:sts::1:assumed-role/op/a"))
    with Stubber(client) as stub:
        stub.add_client_error(
            "put_object",
            service_error_code="PreconditionFailed",
            http_status_code=412,
        )
        with pytest.raises(ConcurrentOperationError) as exc:
            StateFile(client, BUCKET, KEY).write(doc, "staleetag")
    assert exc.value.conflicting_state == "Sleeping"
    assert exc.value.last_caller_arn == "arn:aws:sts::1:assumed-role/op/a"


def test_property7_two_racing_writers_one_wins():
    """Two writers read the same ETag; the second write is refused (412)."""
    # Writer A: succeeds with IfMatch=shared.
    client_a = _s3()
    doc_a = bump(_doc(current_state="Sleeping"))
    with Stubber(client_a) as stub_a:
        stub_a.add_response(
            "put_object",
            {"ETag": '"etag-after-a"'},
            {
                "Bucket": BUCKET,
                "Key": KEY,
                "Body": json.dumps(doc_a, ensure_ascii=True, sort_keys=True).encode("utf-8"),
                "ContentType": "application/json",
                "IfMatch": "shared-etag",
            },
        )
        etag_a = StateFile(client_a, BUCKET, KEY).write(doc_a, "shared-etag")
    assert etag_a == "etag-after-a"

    # Writer B: same starting ETag, now stale -> 412 -> refusal.
    client_b = _s3()
    doc_b = bump(_doc(current_state="Waking"))
    with Stubber(client_b) as stub_b:
        stub_b.add_client_error(
            "put_object",
            service_error_code="PreconditionFailed",
            http_status_code=412,
        )
        with pytest.raises(ConcurrentOperationError):
            StateFile(client_b, BUCKET, KEY).write(doc_b, "shared-etag")
