"""Unit tests for src/auth/audit.py — audit log writer.

Validates Requirements R6.1 (every invocation produces an audit entry),
R6.2 (source_ip from Lambda client context, tolerating absence), and
R6.4 (no raw tokens or full claim sets in the audit log).
"""
from __future__ import annotations

import json
import logging

import pytest

from src.auth.audit import AuditEntry, build_audit_entry, emit_audit_entry
from src.auth.middleware import PrincipalContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ci_ctx(broker_id: str = "broker-abc-123") -> PrincipalContext:
    return PrincipalContext(
        principal="ci-readonly",
        scope="mcp/ci-readonly",
        broker_request_id=broker_id,
    )


def _hpc_ctx(broker_id: str = "broker-xyz-789") -> PrincipalContext:
    return PrincipalContext(
        principal="hpc-user",
        scope="mcp/hpc-user",
        broker_request_id=broker_id,
    )


def _dev_ctx() -> PrincipalContext:
    return PrincipalContext(
        principal="developer-sigv4",
        scope="developer-sigv4",
        broker_request_id=None,
    )


# ---------------------------------------------------------------------------
# build_audit_entry — all fields present
# ---------------------------------------------------------------------------


class TestBuildAuditEntryAllFields:
    """build_audit_entry with all fields populated."""

    def test_ci_all_fields(self):
        entry = build_audit_entry(
            ctx=_ci_ctx(),
            tool_name="search_documentation",
            outcome="success",
            request_id="req-001",
            source_ip="198.51.100.42",
        )
        assert entry.caller_sub == "ci-readonly"
        assert entry.scope == "mcp/ci-readonly"
        assert entry.tool == "search_documentation"
        assert entry.outcome == "success"
        assert entry.request_id == "req-001"
        assert entry.broker_request_id == "broker-abc-123"
        assert entry.source_ip == "198.51.100.42"
        assert entry.ts  # non-empty ISO timestamp

    def test_hpc_all_fields(self):
        entry = build_audit_entry(
            ctx=_hpc_ctx(),
            tool_name="search_issues",
            outcome="success",
            request_id="req-002",
            source_ip="203.0.113.7",
        )
        assert entry.caller_sub == "hpc-user"
        assert entry.scope == "mcp/hpc-user"
        assert entry.tool == "search_issues"
        assert entry.broker_request_id == "broker-xyz-789"
        assert entry.source_ip == "203.0.113.7"


# ---------------------------------------------------------------------------
# build_audit_entry — developer path (broker_request_id=None)
# ---------------------------------------------------------------------------


class TestBuildAuditEntryDeveloperPath:
    """Developer SigV4 path: no broker_request_id."""

    def test_developer_no_broker_id(self):
        entry = build_audit_entry(
            ctx=_dev_ctx(),
            tool_name="get_server_info",
            outcome="success",
            request_id="req-dev-1",
        )
        assert entry.caller_sub == "developer-sigv4"
        assert entry.scope == "developer-sigv4"
        assert entry.broker_request_id is None
        assert entry.source_ip is None

    def test_developer_with_source_ip(self):
        entry = build_audit_entry(
            ctx=_dev_ctx(),
            tool_name="mcp_health_check",
            outcome="success",
            request_id="req-dev-2",
            source_ip="10.0.0.1",
        )
        assert entry.broker_request_id is None
        assert entry.source_ip == "10.0.0.1"


# ---------------------------------------------------------------------------
# build_audit_entry — source_ip=None (R6.2 tolerance)
# ---------------------------------------------------------------------------


class TestBuildAuditEntryNoSourceIp:
    """source_ip absent — tolerated per R6.2."""

    def test_ci_no_source_ip(self):
        entry = build_audit_entry(
            ctx=_ci_ctx(),
            tool_name="analyze_code_structure",
            outcome="success",
            request_id="req-003",
        )
        assert entry.source_ip is None
        assert entry.broker_request_id == "broker-abc-123"

    def test_explicit_none_source_ip(self):
        entry = build_audit_entry(
            ctx=_hpc_ctx(),
            tool_name="find_callers_callees",
            outcome="success",
            request_id="req-004",
            source_ip=None,
        )
        assert entry.source_ip is None


# ---------------------------------------------------------------------------
# emit_audit_entry — valid JSON to audit logger
# ---------------------------------------------------------------------------


class TestEmitAuditEntry:
    """emit_audit_entry writes valid compact JSON to the mdc-mcp-audit logger."""

    def test_emits_valid_json(self, caplog):
        entry = build_audit_entry(
            ctx=_ci_ctx(),
            tool_name="search_documentation",
            outcome="success",
            request_id="req-010",
            source_ip="198.51.100.42",
        )
        with caplog.at_level(logging.INFO, logger="mdc-mcp-audit"):
            emit_audit_entry(entry)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        parsed = json.loads(record.message)
        assert parsed["caller_sub"] == "ci-readonly"
        assert parsed["scope"] == "mcp/ci-readonly"
        assert parsed["tool"] == "search_documentation"
        assert parsed["outcome"] == "success"
        assert parsed["request_id"] == "req-010"
        assert parsed["broker_request_id"] == "broker-abc-123"
        assert parsed["source_ip"] == "198.51.100.42"
        assert "ts" in parsed

    def test_json_is_compact(self, caplog):
        """Output uses compact separators — no spaces after : or ,."""
        entry = build_audit_entry(
            ctx=_ci_ctx(),
            tool_name="get_server_info",
            outcome="success",
            request_id="req-011",
        )
        with caplog.at_level(logging.INFO, logger="mdc-mcp-audit"):
            emit_audit_entry(entry)

        msg = caplog.records[0].message
        # Compact JSON: no space after colon or comma.
        assert ": " not in msg or msg.count(": ") == 0
        assert ", " not in msg


# ---------------------------------------------------------------------------
# No token / authorization fields in the audit log (R6.4)
# ---------------------------------------------------------------------------


class TestNoTokenInAuditLog:
    """The emitted JSON must never contain raw token values or claim sets (R6.4)."""

    _FORBIDDEN_KEYS = {"authorization", "token", "jwt", "claims", "access_token"}

    def test_no_forbidden_keys_ci(self, caplog):
        entry = build_audit_entry(
            ctx=_ci_ctx(),
            tool_name="search_documentation",
            outcome="success",
            request_id="req-020",
        )
        with caplog.at_level(logging.INFO, logger="mdc-mcp-audit"):
            emit_audit_entry(entry)

        parsed = json.loads(caplog.records[0].message)
        assert self._FORBIDDEN_KEYS.isdisjoint(set(parsed.keys())), (
            f"Forbidden keys found: {self._FORBIDDEN_KEYS & set(parsed.keys())}"
        )

    def test_no_forbidden_keys_hpc(self, caplog):
        entry = build_audit_entry(
            ctx=_hpc_ctx(),
            tool_name="search_issues",
            outcome="success",
            request_id="req-020-hpc",
            source_ip="203.0.113.7",
        )
        with caplog.at_level(logging.INFO, logger="mdc-mcp-audit"):
            emit_audit_entry(entry)

        parsed = json.loads(caplog.records[0].message)
        assert self._FORBIDDEN_KEYS.isdisjoint(set(parsed.keys())), (
            f"Forbidden keys found: {self._FORBIDDEN_KEYS & set(parsed.keys())}"
        )

    def test_no_forbidden_keys_developer(self, caplog):
        entry = build_audit_entry(
            ctx=_dev_ctx(),
            tool_name="get_server_info",
            outcome="success",
            request_id="req-020-dev",
        )
        with caplog.at_level(logging.INFO, logger="mdc-mcp-audit"):
            emit_audit_entry(entry)

        parsed = json.loads(caplog.records[0].message)
        assert self._FORBIDDEN_KEYS.isdisjoint(set(parsed.keys())), (
            f"Forbidden keys found: {self._FORBIDDEN_KEYS & set(parsed.keys())}"
        )

    def test_dataclass_fields_are_safe(self):
        """AuditEntry has exactly the expected fields — no token field."""
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(AuditEntry)}
        expected = {
            "ts", "request_id", "caller_sub", "scope", "tool", "outcome",
            "broker_request_id", "source_ip",
        }
        assert field_names == expected

    def test_source_code_has_no_token_field_definitions(self):
        """audit.py source must not define any field that could carry a raw token (R6.4).

        Static check: reads the source text and verifies no dataclass field
        is named after a token or credential concept.
        """
        import inspect
        import re

        source = inspect.getsource(__import__("src.auth.audit", fromlist=["audit"]))
        # Match Python dataclass field definitions like `token: str` or `jwt: str | None`
        field_pattern = re.compile(
            r"^\s+("
            r"authorization|token|jwt|claims|access_token|"
            r"bearer_token|id_token|refresh_token|credential"
            r")\s*:", re.MULTILINE,
        )
        matches = field_pattern.findall(source)
        assert not matches, (
            f"audit.py defines token-related field(s): {matches}"
        )


# ---------------------------------------------------------------------------
# None fields omitted from JSON output
# ---------------------------------------------------------------------------


class TestNoneFieldsOmitted:
    """None-valued fields are omitted rather than emitted as null."""

    def test_developer_path_omits_broker_and_source_ip(self, caplog):
        entry = build_audit_entry(
            ctx=_dev_ctx(),
            tool_name="get_server_info",
            outcome="success",
            request_id="req-030",
        )
        with caplog.at_level(logging.INFO, logger="mdc-mcp-audit"):
            emit_audit_entry(entry)

        parsed = json.loads(caplog.records[0].message)
        assert "broker_request_id" not in parsed
        assert "source_ip" not in parsed

    def test_ci_with_source_ip_but_no_null_fields(self, caplog):
        entry = build_audit_entry(
            ctx=_ci_ctx(),
            tool_name="find_dependencies",
            outcome="success",
            request_id="req-031",
            source_ip="10.0.0.1",
        )
        with caplog.at_level(logging.INFO, logger="mdc-mcp-audit"):
            emit_audit_entry(entry)

        parsed = json.loads(caplog.records[0].message)
        # All present fields have real values, no null.
        for val in parsed.values():
            assert val is not None

    def test_ci_without_source_ip_omits_it(self, caplog):
        entry = build_audit_entry(
            ctx=_ci_ctx(),
            tool_name="find_dependencies",
            outcome="success",
            request_id="req-032",
        )
        with caplog.at_level(logging.INFO, logger="mdc-mcp-audit"):
            emit_audit_entry(entry)

        parsed = json.loads(caplog.records[0].message)
        assert "source_ip" not in parsed
        assert "broker_request_id" in parsed  # CI has broker_request_id


# ---------------------------------------------------------------------------
# Outcome values
# ---------------------------------------------------------------------------


class TestOutcomeValues:
    """Verify all three outcome values produce valid entries."""

    @pytest.mark.parametrize("outcome", ["success", "authorization_denied", "execution_error"])
    def test_outcome_roundtrips(self, outcome, caplog):
        entry = build_audit_entry(
            ctx=_ci_ctx(),
            tool_name="search_documentation",
            outcome=outcome,
            request_id=f"req-{outcome}",
        )
        with caplog.at_level(logging.INFO, logger="mdc-mcp-audit"):
            emit_audit_entry(entry)

        parsed = json.loads(caplog.records[0].message)
        assert parsed["outcome"] == outcome


# ---------------------------------------------------------------------------
# Non-blocking: emit_audit_entry catches exceptions (R6.1)
# ---------------------------------------------------------------------------


class TestEmitNonBlocking:
    """emit_audit_entry must never raise — it catches and logs errors."""

    def test_catches_serialization_error(self, caplog, monkeypatch):
        """If JSON serialization somehow fails, the exception is caught."""
        entry = build_audit_entry(
            ctx=_ci_ctx(),
            tool_name="search_documentation",
            outcome="success",
            request_id="req-err",
        )
        # Force json.dumps to raise.
        monkeypatch.setattr(
            "src.auth.audit.json.dumps",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        with caplog.at_level(logging.ERROR, logger="mdc-mcp-audit"):
            emit_audit_entry(entry)  # Must NOT raise.

        # Should have logged the error instead.
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(error_records) == 1
        assert "audit_write_failed" in error_records[0].message

    def test_catches_logger_error(self, caplog, monkeypatch):
        """If the logger itself raises, the outer try/except still catches."""
        entry = build_audit_entry(
            ctx=_dev_ctx(),
            tool_name="get_server_info",
            outcome="success",
            request_id="req-err2",
        )

        original_info = logging.getLogger("mdc-mcp-audit").info

        def _failing_info(msg, *a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr(
            "src.auth.audit._audit_logger.info", _failing_info,
        )

        # The outer except catches the OSError and logs it.
        # But since _audit_logger.error is not monkeypatched, this should
        # produce an error record. Let's be precise: the except block calls
        # _audit_logger.error which should still work.
        with caplog.at_level(logging.ERROR, logger="mdc-mcp-audit"):
            emit_audit_entry(entry)  # Must NOT raise.


# ---------------------------------------------------------------------------
# AuditEntry is immutable
# ---------------------------------------------------------------------------


class TestAuditEntryImmutability:
    """AuditEntry is a frozen dataclass — fields cannot be mutated."""

    def test_frozen(self):
        entry = AuditEntry(
            ts="2026-09-05T12:00:00.000+00:00",
            request_id="req-1",
            caller_sub="ci-readonly",
            scope="mcp/ci-readonly",
            tool="search_documentation",
            outcome="success",
            broker_request_id="broker-1",
            source_ip="10.0.0.1",
        )
        with pytest.raises(AttributeError):
            entry.caller_sub = "hacked"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Timestamp format
# ---------------------------------------------------------------------------


class TestTimestampFormat:
    """build_audit_entry produces an ISO-8601 UTC timestamp."""

    def test_ts_is_iso_format(self):
        entry = build_audit_entry(
            ctx=_ci_ctx(),
            tool_name="search_documentation",
            outcome="success",
            request_id="req-ts",
        )
        # Must end with +00:00 (UTC offset) and contain a T separator.
        assert "T" in entry.ts
        assert entry.ts.endswith("+00:00")

    def test_ts_has_millisecond_precision(self):
        entry = build_audit_entry(
            ctx=_dev_ctx(),
            tool_name="get_server_info",
            outcome="success",
            request_id="req-ts2",
        )
        # Millisecond precision: fraction part has 3 digits.
        # Format: YYYY-MM-DDTHH:MM:SS.mmm+00:00
        fraction = entry.ts.split(".")[1].split("+")[0]
        assert len(fraction) == 3
