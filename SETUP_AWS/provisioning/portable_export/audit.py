"""Structured audit trail for the Cross_Platform_Data_Persistence_System (Task 2).

Every transfer step (export / restore / reimport phase) emits an
``Audit_Log_Record`` -- a single JSON object on a single line carrying the
standard field set. Records are mirrored to:

* the operator console as ASCII-only ``[OK]`` / ``[ERROR]`` / ``[WARN]`` /
  ``[INFO]`` / ``[SKIP]`` lines (emoji break MCP stdio),
* a CloudWatch log group ``mdc-mcp-rag-portable-export-{env}`` when an AWS
  logs client is configured,
* a per-operation S3 object ``<prefix>/audit/<operation_id>.jsonl`` flushed
  exactly once on completion or failure, and
* a local fallback ``~/.mdc-mcp-rag/portable_export/<operation_id>.jsonl`` so
  an offline / un-credentialed run (COTS host) still records its trail.

Requirements: 15.3 (ASCII-only console), 15.5 (record change in change log).
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - botocore is a runtime dependency
    class ClientError(Exception):  # type: ignore[no-redef]
        response: dict = {}


#: Standard Audit_Log_Record fields, in stable order.
RECORD_FIELDS: tuple[str, ...] = (
    "timestamp",
    "event_type",
    "operation_id",
    "caller_arn",
    "environment_name",
    "direction",
    "phase",
    "aws_resource_arns",
    "bundle_keys",
    "record_counts",
    "elapsed_seconds",
    "error",
)

_COMPLETED_EVENTS = frozenset(
    {
        "AWS_Export_Completed",
        "COTS_Restore_Completed",
        "AWS_Reimport_Completed",
        "Verifier_Passed",
    }
)
_SKIP_EVENTS = frozenset(
    {"Confirmation_Declined", "Phase_NoOp", "Unit_Skipped"}
)
_WARN_EVENTS = frozenset({"Query_Incompatible", "Stale_Lock_Broken"})


def _utc_now_iso() -> str:
    """ISO 8601 UTC timestamp with a trailing Z, second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_local_dir() -> Path:
    """Local fallback directory for audit objects."""
    return Path(os.path.expanduser("~")) / ".mdc-mcp-rag" / "portable_export"


def build_record(
    *,
    event_type: str,
    operation_id: str,
    caller_arn: str,
    environment_name: str,
    direction: Optional[str] = None,
    phase: Optional[str] = None,
    aws_resource_arns: Optional[list[str]] = None,
    bundle_keys: Optional[list[str]] = None,
    record_counts: Optional[dict[str, Any]] = None,
    elapsed_seconds: Optional[float] = None,
    error: Optional[dict[str, str]] = None,
    timestamp: Optional[str] = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a fully-populated Audit_Log_Record dict.

    Every standard field is present (``None`` when not applicable) so the
    record schema is stable across event types. ``error`` is an object with
    ``code`` and ``message`` keys, present only on failure events. Additional
    keyword arguments are merged in verbatim (e.g. ``query_compatibility``).
    """
    record = {
        "timestamp": timestamp or _utc_now_iso(),
        "event_type": event_type,
        "operation_id": operation_id,
        "caller_arn": caller_arn,
        "environment_name": environment_name,
        "direction": direction,
        "phase": phase,
        "aws_resource_arns": list(aws_resource_arns) if aws_resource_arns else None,
        "bundle_keys": list(bundle_keys) if bundle_keys else None,
        "record_counts": dict(record_counts) if record_counts else None,
        "elapsed_seconds": elapsed_seconds,
        "error": error,
    }
    record.update(extra)
    return record


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
    if event.endswith(("_Failed", "_Timeout", "_Refused", "_Mismatch", "_Invalid",
                        "_Unsupported", "_Conflict")):
        return "[ERROR]"
    return "[INFO]"


def render_console_line(record: dict[str, Any]) -> str:
    """Render an ASCII-only one-line console mirror of a record.

    Non-ASCII characters in any field are stripped so the line is safe for
    MCP stdio. The line is human-readable, not the JSON payload.
    """
    prefix = _console_prefix(record)
    parts = [prefix, record.get("event_type", "?")]
    if record.get("direction"):
        parts.append(str(record["direction"]))
    if record.get("phase"):
        parts.append(f"phase={record['phase']}")
    if record.get("record_counts"):
        parts.append(f"counts={record['record_counts']}")
    if record.get("error"):
        err = record["error"]
        parts.append(f"error={err.get('code')}:{err.get('message')}")
    line = " ".join(str(p) for p in parts)
    # Hard ASCII guarantee.
    return line.encode("ascii", "ignore").decode("ascii")


class AuditLogger:
    """Emits Audit_Log_Records for a single operation.

    Buffers every record and, on :meth:`flush`, writes them as one ``.jsonl``
    object to S3 (keyed by ``operation_id``) -- written exactly once -- and
    always to the local fallback file. Each :meth:`emit` also appends to
    CloudWatch Logs when a client is configured and mirrors an ASCII line to
    the console.

    AWS clients are injected so tests use ``botocore`` Stubbers. When a client
    is ``None`` the corresponding sink is skipped (console + local always run),
    which keeps ``--dry-run`` and offline COTS restores free of network calls.
    """

    def __init__(
        self,
        *,
        operation_id: str,
        caller_arn: str,
        environment_name: str,
        log_group: str,
        audit_bucket: Optional[str] = None,
        audit_prefix: str = "",
        direction: Optional[str] = None,
        logs_client: Any = None,
        s3_client: Any = None,
        console_stream: Any = None,
        local_dir: Optional[Path] = None,
    ) -> None:
        self.operation_id = operation_id
        self.caller_arn = caller_arn
        self.environment_name = environment_name
        self.log_group = log_group
        self.audit_bucket = audit_bucket
        self.audit_prefix = (audit_prefix.rstrip("/") + "/") if audit_prefix else ""
        self.direction = direction
        self._logs = logs_client
        self._s3 = s3_client
        self._console = console_stream or sys.stdout
        self._local_dir = local_dir if local_dir is not None else default_local_dir()
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
        """The per-operation audit object key."""
        return f"{self.audit_prefix}audit/{self.operation_id}.jsonl"

    @property
    def local_path(self) -> Path:
        """The local fallback path for this operation."""
        return self._local_dir / f"{self.operation_id}.jsonl"

    def emit(self, event_type: str, **kwargs: Any) -> dict[str, Any]:
        """Build, buffer, mirror, and ship one Audit_Log_Record."""
        kwargs.setdefault("direction", self.direction)
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
            if _err_code(exc) != "ResourceAlreadyExistsException":
                raise
        try:
            self._logs.create_log_stream(
                logGroupName=self.log_group,
                logStreamName=self._log_stream_name,
            )
        except ClientError as exc:
            if _err_code(exc) != "ResourceAlreadyExistsException":
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

    def _serialize(self) -> bytes:
        return (
            "\n".join(
                json.dumps(r, ensure_ascii=True, sort_keys=True)
                for r in self._records
            )
            + "\n"
        ).encode("utf-8")

    def flush(self) -> Optional[str]:
        """Write all buffered records to S3 + local fallback, exactly once.

        Idempotent: a second call is a no-op. Returns the S3 key written, or
        ``None`` when no S3 client is configured (local fallback still
        written). The local fallback always receives the records so an
        offline run keeps an auditable trail.
        """
        if self._flushed:
            return self.s3_key if self._s3 is not None else None
        self._flushed = True
        body = self._serialize()

        # Local fallback first -- never fails on credentials.
        try:
            self._local_dir.mkdir(parents=True, exist_ok=True)
            self.local_path.write_bytes(body)
        except OSError as exc:  # pragma: no cover - defensive
            print(
                f"[WARN] could not write local audit fallback: {exc}",
                file=self._console,
            )

        if self._s3 is None or self.audit_bucket is None:
            return None
        self._s3.put_object(
            Bucket=self.audit_bucket,
            Key=self.s3_key,
            Body=body,
            ContentType="application/x-ndjson",
        )
        return self.s3_key


def _err_code(exc: ClientError) -> str:
    """Extract the AWS error code from a ClientError, defensively."""
    try:
        return exc.response.get("Error", {}).get("Code", "")  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive
        return ""


__all__ = [
    "RECORD_FIELDS",
    "AuditLogger",
    "build_record",
    "render_console_line",
    "default_local_dir",
]
