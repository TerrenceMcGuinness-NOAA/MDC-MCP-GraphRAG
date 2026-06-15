"""Structured audit trail for the Cost_Control_System (Task 2).

Every Hibernate_Operation and Wake_Operation step emits an
``Audit_Log_Record`` -- a single JSON object on a single line carrying the
Requirement 9 field set. Records are mirrored to:

* the operator console as ASCII-only ``[OK]`` / ``[ERROR]`` / ``[WARN]`` /
  ``[INFO]`` / ``[SKIP]`` lines (emoji break MCP stdio),
* a CloudWatch log group ``mdc-mcp-rag-cost-control-{env}`` (R9.2), and
* a single consolidated S3 object ``cost-control/{env}/{operation_id}.jsonl``
  flushed exactly once on operation completion or failure (R9.3).

Requirements: 9.1, 9.2, 9.3, 9.4.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

from botocore.exceptions import ClientError

#: R9.1 required record fields, in stable order.
RECORD_FIELDS: tuple[str, ...] = (
    "timestamp",
    "event_type",
    "operation_id",
    "caller_arn",
    "environment_name",
    "state_before",
    "state_after",
    "tier",
    "aws_resource_arns",
    "snapshot_ids",
    "elapsed_seconds",
    "estimated_savings_usd_per_hour",
    "error",
)

# Event-type -> console prefix. Anything not listed (and without an error)
# defaults to [INFO]; any record carrying an error renders as [ERROR].
_COMPLETED_EVENTS = frozenset(
    {"Sleep_Completed", "Wake_Completed", "Drift_Reconciled"}
)
_SKIP_EVENTS = frozenset(
    {"Sleep_NoOp", "Wake_NoOp", "Confirmation_Declined"}
)
_WARN_EVENTS = frozenset({"Resleep_Triggered"})


def _utc_now_iso() -> str:
    """ISO 8601 UTC timestamp with a trailing Z, second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_record(
    *,
    event_type: str,
    operation_id: str,
    caller_arn: str,
    environment_name: str,
    state_before: Optional[str] = None,
    state_after: Optional[str] = None,
    tier: Optional[str] = None,
    aws_resource_arns: Optional[list[str]] = None,
    snapshot_ids: Optional[list[str]] = None,
    elapsed_seconds: Optional[float] = None,
    estimated_savings_usd_per_hour: Optional[float] = None,
    error: Optional[dict[str, str]] = None,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Build a fully-populated Audit_Log_Record dict (R9.1).

    Every required field is present (``None`` when not applicable) so the
    record schema is stable across event types. ``error`` is an object with
    ``code`` and ``message`` keys, present only on failure events.
    """
    return {
        "timestamp": timestamp or _utc_now_iso(),
        "event_type": event_type,
        "operation_id": operation_id,
        "caller_arn": caller_arn,
        "environment_name": environment_name,
        "state_before": state_before,
        "state_after": state_after,
        "tier": tier,
        "aws_resource_arns": list(aws_resource_arns) if aws_resource_arns else None,
        "snapshot_ids": list(snapshot_ids) if snapshot_ids else None,
        "elapsed_seconds": elapsed_seconds,
        "estimated_savings_usd_per_hour": estimated_savings_usd_per_hour,
        "error": error,
    }


def _console_prefix(record: dict[str, Any]) -> str:
    """Map a record to its ASCII console prefix."""
    if record.get("error"):
        return "[ERROR]"
    event = record.get("event_type", "")
    if event in _COMPLETED_EVENTS:
        return "[OK]"
    if event in _SKIP_EVENTS:
        return "[SKIP]"
    if event in _WARN_EVENTS:
        return "[WARN]"
    if event.endswith(("_Failed", "_Timeout", "_Refused", "_Detected")):
        return "[ERROR]"
    return "[INFO]"


def render_console_line(record: dict[str, Any]) -> str:
    """Render an ASCII-only one-line console mirror of a record.

    Non-ASCII characters in any field are stripped so the line is safe for
    MCP stdio. The line is human-readable, not the JSON payload.
    """
    prefix = _console_prefix(record)
    parts = [prefix, record.get("event_type", "?")]
    if record.get("tier"):
        parts.append(f"tier={record['tier']}")
    if record.get("state_before") or record.get("state_after"):
        parts.append(f"{record.get('state_before')}->{record.get('state_after')}")
    if record.get("error"):
        err = record["error"]
        parts.append(f"error={err.get('code')}:{err.get('message')}")
    line = " ".join(str(p) for p in parts)
    # Hard ASCII guarantee.
    return line.encode("ascii", "ignore").decode("ascii")


class AuditLogger:
    """Emits Audit_Log_Records for a single operation.

    Buffers every record for the operation and, on :meth:`flush`, writes them
    as one S3 ``.jsonl`` object keyed by ``operation_id`` -- written exactly
    once (R9.3). Each :meth:`emit` also appends to CloudWatch Logs (R9.2) and
    mirrors an ASCII line to the console.

    AWS clients are injected so tests use ``botocore`` Stubbers. When a client
    is ``None`` the corresponding sink is skipped (console mirror always runs),
    which keeps ``--dry-run`` and unit tests free of network calls.
    """

    def __init__(
        self,
        *,
        operation_id: str,
        caller_arn: str,
        environment_name: str,
        log_group: str,
        audit_bucket: str,
        audit_prefix: str,
        logs_client: Any = None,
        s3_client: Any = None,
        console_stream: Any = None,
    ) -> None:
        self.operation_id = operation_id
        self.caller_arn = caller_arn
        self.environment_name = environment_name
        self.log_group = log_group
        self.audit_bucket = audit_bucket
        self.audit_prefix = audit_prefix.rstrip("/") + "/" if audit_prefix else ""
        self._logs = logs_client
        self._s3 = s3_client
        self._console = console_stream or sys.stdout
        self._records: list[dict[str, Any]] = []
        self._flushed = False
        self._log_stream_ready = False
        self._log_stream_name = operation_id

    @property
    def records(self) -> list[dict[str, Any]]:
        """The records emitted so far (a copy)."""
        return list(self._records)

    @property
    def s3_key(self) -> str:
        """The per-operation audit object key (R9.3)."""
        return f"{self.audit_prefix}{self.operation_id}.jsonl"

    def emit(self, event_type: str, **kwargs: Any) -> dict[str, Any]:
        """Build, buffer, mirror, and ship one Audit_Log_Record.

        ``kwargs`` are forwarded to :func:`build_record` (the operation /
        caller / environment fields are filled from the logger). Returns the
        record so callers can assert on it.
        """
        record = build_record(
            event_type=event_type,
            operation_id=self.operation_id,
            caller_arn=self.caller_arn,
            environment_name=self.environment_name,
            **kwargs,
        )
        self._records.append(record)
        self._write_console(record)
        self._write_cloudwatch(record)
        return record

    def _write_console(self, record: dict[str, Any]) -> None:
        print(render_console_line(record), file=self._console)

    def _ensure_log_stream(self) -> None:
        if self._log_stream_ready or self._logs is None:
            return
        try:
            self._logs.create_log_group(logGroupName=self.log_group)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ResourceAlreadyExistsException":
                raise
        try:
            self._logs.create_log_stream(
                logGroupName=self.log_group,
                logStreamName=self._log_stream_name,
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ResourceAlreadyExistsException":
                raise
        self._log_stream_ready = True

    def _write_cloudwatch(self, record: dict[str, Any]) -> None:
        if self._logs is None:
            return
        self._ensure_log_stream()
        self._logs.put_log_events(
            logGroupName=self.log_group,
            logStreamName=self._log_stream_name,
            logEvents=[
                {
                    "timestamp": int(time.time() * 1000),
                    "message": json.dumps(record, ensure_ascii=True, sort_keys=True),
                }
            ],
        )

    def flush(self) -> Optional[str]:
        """Write all buffered records to the per-operation S3 object once.

        Idempotent: a second call is a no-op (R9.3 "exactly once"). Returns the
        S3 key written, or ``None`` when no S3 client is configured.
        """
        if self._flushed:
            return self.s3_key if self._s3 is not None else None
        self._flushed = True
        if self._s3 is None:
            return None
        body = (
            "\n".join(
                json.dumps(r, ensure_ascii=True, sort_keys=True)
                for r in self._records
            )
            + "\n"
        ).encode("utf-8")
        self._s3.put_object(
            Bucket=self.audit_bucket,
            Key=self.s3_key,
            Body=body,
            ContentType="application/x-ndjson",
        )
        return self.s3_key
