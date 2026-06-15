"""Unit tests for cost_control.audit (Task 2.1).

Covers R9.1 (all required fields; failure records carry error), R9.3 (per-op
S3 object written exactly once), and the ASCII-only console mirror.
"""

from __future__ import annotations

import io
import json

import boto3
import pytest
from botocore.stub import Stubber

from cost_control.audit import (
    RECORD_FIELDS,
    AuditLogger,
    build_record,
    render_console_line,
)

OP_ID = "8f3a1c2e-0000-0000-0000-000000000000"
CALLER = "arn:aws:sts::903050880929:assumed-role/operator/terry"
LOG_GROUP = "mdc-mcp-rag-cost-control-dev"
AUDIT_BUCKET = "mdc-mcp-rag-cost-control-audit-dev"
AUDIT_PREFIX = "cost-control/dev/"


def _logger(*, s3_client=None, logs_client=None, console=None):
    return AuditLogger(
        operation_id=OP_ID,
        caller_arn=CALLER,
        environment_name="dev",
        log_group=LOG_GROUP,
        audit_bucket=AUDIT_BUCKET,
        audit_prefix=AUDIT_PREFIX,
        logs_client=logs_client,
        s3_client=s3_client,
        console_stream=console,
    )


# ── record schema ────────────────────────────────────────────────────────

def test_build_record_has_all_required_fields():
    rec = build_record(
        event_type="Sleep_Started",
        operation_id=OP_ID,
        caller_arn=CALLER,
        environment_name="dev",
        state_before="Active_Mode",
        state_after="Sleeping",
    )
    for field in RECORD_FIELDS:
        assert field in rec
    assert set(rec.keys()) == set(RECORD_FIELDS)
    assert rec["error"] is None
    assert rec["timestamp"].endswith("Z")


def test_failure_record_carries_error_object():
    log = _logger(console=io.StringIO())
    rec = log.emit(
        "Sleep_Failed",
        state_before="Sleeping",
        state_after="Active_Mode_Degraded",
        tier="neptune",
        error={"code": "ThrottlingException", "message": "rate exceeded"},
    )
    assert rec["error"] == {"code": "ThrottlingException", "message": "rate exceeded"}


def test_resource_and_snapshot_lists_passed_through():
    log = _logger(console=io.StringIO())
    rec = log.emit(
        "Sleep_Completed",
        state_before="Sleeping",
        state_after="Sleep_State",
        aws_resource_arns=["arn:aws:ec2:us-east-1:1:instance/i-0"],
        snapshot_ids=["cc-dev-op8f3a-20260615T201201-neptune"],
        elapsed_seconds=1320,
        estimated_savings_usd_per_hour=1.24,
    )
    assert rec["aws_resource_arns"] == ["arn:aws:ec2:us-east-1:1:instance/i-0"]
    assert rec["snapshot_ids"] == ["cc-dev-op8f3a-20260615T201201-neptune"]
    assert rec["estimated_savings_usd_per_hour"] == 1.24


# ── console mirror (ASCII-only) ──────────────────────────────────────────

def test_console_prefix_selection():
    assert render_console_line(build_record(
        event_type="Sleep_Completed", operation_id=OP_ID, caller_arn=CALLER,
        environment_name="dev")).startswith("[OK]")
    assert render_console_line(build_record(
        event_type="Sleep_Failed", operation_id=OP_ID, caller_arn=CALLER,
        environment_name="dev",
        error={"code": "E", "message": "m"})).startswith("[ERROR]")
    assert render_console_line(build_record(
        event_type="Concurrent_Operation_Refused", operation_id=OP_ID,
        caller_arn=CALLER, environment_name="dev")).startswith("[ERROR]")
    assert render_console_line(build_record(
        event_type="Sleep_NoOp", operation_id=OP_ID, caller_arn=CALLER,
        environment_name="dev")).startswith("[SKIP]")
    assert render_console_line(build_record(
        event_type="Sleep_Started", operation_id=OP_ID, caller_arn=CALLER,
        environment_name="dev")).startswith("[INFO]")


def test_console_output_is_ascii_only():
    out = io.StringIO()
    log = _logger(console=out)
    # Inject a non-ASCII tier label; the mirror must strip it.
    log.emit("Sleep_Started", tier="neptune\u2014\u2705", state_before="Active_Mode",
             state_after="Sleeping")
    text = out.getvalue()
    assert text  # something was printed
    text.encode("ascii")  # raises if any non-ASCII slipped through


def test_emit_buffers_records():
    log = _logger(console=io.StringIO())
    log.emit("Sleep_Started", state_before="Active_Mode", state_after="Sleeping")
    log.emit("Sleep_Completed", state_before="Sleeping", state_after="Sleep_State")
    assert len(log.records) == 2


# ── per-op S3 object (exactly once) ───────────────────────────────────────

def test_flush_writes_exactly_once():
    client = boto3.client("s3", region_name="us-east-1")
    log = _logger(s3_client=client, console=io.StringIO())
    log.emit("Sleep_Started", state_before="Active_Mode", state_after="Sleeping")

    expected_body = (
        json.dumps(log.records[0], ensure_ascii=True, sort_keys=True) + "\n"
    ).encode("utf-8")

    with Stubber(client) as stub:
        # Only ONE put_object is queued; a second flush must not consume one.
        stub.add_response(
            "put_object",
            {"ETag": '"x"'},
            {
                "Bucket": AUDIT_BUCKET,
                "Key": f"{AUDIT_PREFIX}{OP_ID}.jsonl",
                "Body": expected_body,
                "ContentType": "application/x-ndjson",
            },
        )
        key1 = log.flush()
        key2 = log.flush()  # no-op, must not raise (no second stubbed call)
        stub.assert_no_pending_responses()

    assert key1 == f"{AUDIT_PREFIX}{OP_ID}.jsonl"
    assert key2 == key1


def test_flush_without_s3_returns_none():
    log = _logger(console=io.StringIO())
    log.emit("Sleep_Started", state_before="Active_Mode", state_after="Sleeping")
    assert log.flush() is None


def test_cloudwatch_emit_creates_group_stream_and_puts():
    logs = boto3.client("logs", region_name="us-east-1")
    log = _logger(logs_client=logs, console=io.StringIO())
    with Stubber(logs) as stub:
        stub.add_response("create_log_group", {}, {"logGroupName": LOG_GROUP})
        stub.add_response(
            "create_log_stream", {},
            {"logGroupName": LOG_GROUP, "logStreamName": OP_ID},
        )
        stub.add_response("put_log_events", {"nextSequenceToken": "1"})
        log.emit("Sleep_Started", state_before="Active_Mode", state_after="Sleeping")
        stub.assert_no_pending_responses()
