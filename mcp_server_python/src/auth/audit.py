"""Audit log writer — Path C (design §9, R6.1, R6.2, R6.4).

Emits one JSON Lines audit entry per tool invocation to a dedicated
``mdc-mcp-audit`` logger.  CloudWatch Logs picks up the stdout output.

The entry includes ``broker_request_id`` (from the Gateway Request_Interceptor
via :class:`~src.auth.middleware.PrincipalContext`) and ``source_ip`` (from
Lambda client context), both tolerating absence.  ``None``-valued fields are
omitted from the JSON output rather than emitted as ``null``.

**Never logged (R6.4):** raw JWT tokens, full claim sets, ``Authorization``
header values, or tool arguments/output.

Implements Requirements R6.1, R6.2, R6.4.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .middleware import PrincipalContext

# Dedicated logger — keeps audit traffic out of the root logger stream.
_audit_logger = logging.getLogger("mdc-mcp-audit")

# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditEntry:
    """A single audit log record for one tool invocation.

    Attributes
    ----------
    ts : str
        ISO-8601 UTC timestamp (ms precision).
    request_id : str
        MCP request ID.
    caller_sub : str
        Principal name (``"ci-readonly"``, ``"hpc-user"``, ``"developer-sigv4"``).
    scope : str
        OAuth scope or the synthetic ``"developer-sigv4"`` scope.
    tool : str
        MCP tool name.
    outcome : str
        ``"success"``, ``"authorization_denied"``, or ``"execution_error"``.
    broker_request_id : str | None
        Token_Broker request ID for audit attribution; ``None`` for the
        developer SigV4 path.
    source_ip : str | None
        Caller IP from the Gateway's Lambda client context; ``None`` when
        unavailable.
    """

    ts: str
    request_id: str
    caller_sub: str
    scope: str
    tool: str
    outcome: str
    broker_request_id: str | None = None
    source_ip: str | None = None


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_audit_entry(
    ctx: PrincipalContext,
    tool_name: str,
    outcome: str,
    request_id: str,
    source_ip: str | None = None,
) -> AuditEntry:
    """Construct an :class:`AuditEntry` from a principal context and call metadata.

    Parameters
    ----------
    ctx : PrincipalContext
        The request-scoped principal identity.
    tool_name : str
        The MCP tool being invoked.
    outcome : str
        ``"success"``, ``"authorization_denied"``, or ``"execution_error"``.
    request_id : str
        The MCP request ID.
    source_ip : str | None
        Caller IP from Lambda client context; ``None`` when unavailable (R6.2).

    Returns
    -------
    AuditEntry
    """
    return AuditEntry(
        ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        request_id=request_id,
        caller_sub=ctx.principal,
        scope=ctx.scope,
        tool=tool_name,
        outcome=outcome,
        broker_request_id=ctx.broker_request_id,
        source_ip=source_ip,
    )


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


def emit_audit_entry(entry: AuditEntry) -> None:
    """Serialize *entry* to compact JSON and write it to the audit logger.

    * ``None``-valued fields are omitted (not emitted as ``null``).
    * Non-blocking: exceptions are caught and logged to the audit logger at
      ERROR level rather than propagated (R6.1 — audit must never block the
      caller).
    * **Never includes** raw token values or full JWT claim sets (R6.4).
    """
    try:
        record = {k: v for k, v in asdict(entry).items() if v is not None}
        _audit_logger.info(json.dumps(record, separators=(",", ":")))
    except Exception:
        # Non-blocking: log the failure, never propagate.
        _audit_logger.error("audit_write_failed", exc_info=True)
