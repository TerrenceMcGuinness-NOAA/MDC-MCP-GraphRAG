"""Unit tests for portable_export.audit (Task 2.1).

Covers Requirement 15.3 (ASCII-only console) plus the standard field set,
per-op S3 object written exactly once, and local fallback when no AWS client
is configured.
"""

from __future__ import annotations

import json

import boto3
import pytest
from botocore.stub import Stubber

from portable_export import audit
from portable_export.audit import AuditLogger, RECORD_FIELDS, build_record, render_console_line


def _logger(tmp_path, **kw):
    return AuditLogger(
        operation_id="op-123",
        caller_arn="arn:aws:sts::1:assumed-role/operator/terry",
        environment_name="dev",
        log_group="mdc-mcp-rag-portable-export-dev",
        direction="AWS_Export",
        local_dir=tmp_path,
        **kw,
    )


def test_record_has_standard_fields():
    rec = build_record(
        event_type="AWS_Export_Started",
        operation_id="op-1",
        caller_arn="arn:x",
        environment_name="dev",
    )
    for f in RECORD_FIELDS:
        assert f in rec


def test_console_line_is_ascii_only():
    rec = build_record(
        event_type="AWS_Export_Started",
        operation_id="op-1",
        caller_arn="arn:x",
        environment_name="dev",
        phase="export_vectors\u2705",  # embedded emoji must be stripped
    )
    line = render_console_line(rec)
    assert line == line.encode("ascii", "ignore").decode("ascii")
    line.encode("ascii")  # raises if any non-ascii survived


def test_console_prefix_mapping():
    assert render_console_line(build_record(
        event_type="AWS_Export_Completed", operation_id="o", caller_arn="a",
        environment_name="dev")).startswith("[OK]")
    assert render_console_line(build_record(
        event_type="Verifier_Failed", operation_id="o", caller_arn="a",
        environment_name="dev")).startswith("[ERROR]")
    assert render_console_line(build_record(
        event_type="Confirmation_Declined", operation_id="o", caller_arn="a",
        environment_name="dev")).startswith("[SKIP]")
    assert render_console_line(build_record(
        event_type="Query_Incompatible", operation_id="o", caller_arn="a",
        environment_name="dev")).startswith("[WARN]")
    # error overrides everything
    assert render_console_line(build_record(
        event_type="AWS_Export_Completed", operation_id="o", caller_arn="a",
        environment_name="dev", error={"code": "X", "message": "m"})).startswith("[ERROR]")


def test_local_fallback_written_without_s3(tmp_path):
    import io
    log = _logger(tmp_path, console_stream=io.StringIO())
    log.emit("AWS_Export_Started", phase="export_vectors")
    log.emit("AWS_Export_Completed", record_counts={"vectors": 2})
    assert log.flush() is None  # no s3 client -> None
    body = log.local_path.read_text(encoding="utf-8")
    lines = [l for l in body.splitlines() if l]
    assert len(lines) == 2
    assert json.loads(lines[0])["event_type"] == "AWS_Export_Started"
    assert json.loads(lines[1])["record_counts"] == {"vectors": 2}


def test_s3_object_written_exactly_once(tmp_path):
    import io
    s3 = boto3.client("s3", region_name="us-east-1")
    stub = Stubber(s3)
    log = _logger(tmp_path, audit_bucket="b", audit_prefix="portable-export/dev/op-123/",
                  s3_client=s3, console_stream=io.StringIO())
    log.emit("AWS_Export_Started")
    expected_key = "portable-export/dev/op-123/audit/op-123.jsonl"
    stub.add_response(
        "put_object",
        {},
        {"Bucket": "b", "Key": expected_key, "Body": log._serialize(),
         "ContentType": "application/x-ndjson"},
    )
    with stub:
        key = log.flush()
        assert key == expected_key
        # second flush is a no-op (no extra stubbed call -> would raise if called)
        assert log.flush() == expected_key
    stub.assert_no_pending_responses()


def test_cloudwatch_emit(tmp_path):
    import io
    logs = boto3.client("logs", region_name="us-east-1")
    stub = Stubber(logs)
    stub.add_response("create_log_group", {})
    stub.add_response("create_log_stream", {})
    stub.add_response("put_log_events", {"nextSequenceToken": "t"})
    log = _logger(tmp_path, logs_client=logs, console_stream=io.StringIO())
    with stub:
        log.emit("AWS_Export_Started")
    stub.assert_no_pending_responses()
