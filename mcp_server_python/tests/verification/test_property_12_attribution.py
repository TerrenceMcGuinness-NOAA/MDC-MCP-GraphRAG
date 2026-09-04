"""Property 12 — Attribution completeness.

Every Gateway-admitted request produces exactly one audit entry whose
``broker_request_id`` joins a Token_Broker log entry, unless the principal is
``developer-sigv4`` (design §8, Property 12; requirements R6.1).

This test verifies the audit-attribution chain from principal context through
audit log emission, proving:

1. CI path produces an audit entry with ``broker_request_id`` present.
2. HPC path produces an audit entry with ``broker_request_id`` present.
3. Developer path produces an audit entry WITHOUT ``broker_request_id``
   (omitted from the JSON, not emitted as ``null``).
4. One invocation → exactly one JSON record in the log output.
5. The audit entry's ``broker_request_id`` matches what was in the
   ``PrincipalContext`` — proving joinability to the Token_Broker log.
6. Full chain: interceptor event → derive_principal → build_audit_entry →
   emit → parse — proving the chain from JWT claim to audit log.

Run::

    cd /mdc-mcp-rag/eib-mcp-rag-server
    python -m pytest mcp_server_python/tests/verification/test_property_12_attribution.py -v

Requirements: R6.1; Property 12.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap — the interceptor Lambda lives outside mcp_server_python
# ---------------------------------------------------------------------------

_INTERCEPTOR_DIR = os.path.join(
    os.path.dirname(__file__),
    os.pardir, os.pardir, os.pardir,
    "infrastructure", "cdk", "lambda", "gateway_interceptor",
)
_INTERCEPTOR_DIR = os.path.normpath(_INTERCEPTOR_DIR)
if _INTERCEPTOR_DIR not in sys.path:
    sys.path.insert(0, _INTERCEPTOR_DIR)

import index as interceptor  # noqa: E402

from src.auth.middleware import PrincipalContext, derive_principal  # noqa: E402
from src.auth.audit import build_audit_entry, emit_audit_entry  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jwt(claims: dict) -> str:
    """Create a structurally valid JWT (header.payload.signature) for testing.

    The interceptor performs unverified decode (the Gateway already validated the
    signature), so we only need a correctly base64url-encoded payload section.
    """
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


def _gateway_event(token: str, extra_headers: dict[str, str] | None = None) -> dict:
    """Build a Gateway REQUEST interceptor event."""
    headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
    if extra_headers:
        headers.update(extra_headers)
    body_json = json.dumps({"jsonrpc": "2.0", "method": "tools/call", "id": 1,
                            "params": {"name": "search_documentation"}})
    return {
        "http": {
            "gatewayRequest": {
                "path": "/mdc-mcp-rag/invocations",
                "method": "POST",
                "headers": headers,
                "body": base64.b64encode(body_json.encode()).decode(),
            }
        }
    }


class _LambdaCtx:
    """Minimal Lambda context stub."""
    function_name = "gateway_interceptor"
    aws_request_id = "req-prop12-001"


def _run_interceptor(jwt_claims: dict) -> dict[str, str]:
    """Run the interceptor and return its output headers."""
    token = _make_jwt(jwt_claims)
    event = _gateway_event(token)
    resp = interceptor.handler(event, _LambdaCtx())
    assert "transformedGatewayRequest" in resp.get("http", {}), (
        "Interceptor unexpectedly denied the request"
    )
    return resp["http"]["transformedGatewayRequest"]["headers"]


def _capture_audit_log(entry, caplog) -> list[dict]:
    """Emit an audit entry and return the parsed JSON records from the log.

    Parameters
    ----------
    entry : AuditEntry
        The entry to emit.
    caplog : pytest.LogCaptureFixture
        The pytest log capture fixture.

    Returns
    -------
    list[dict]
        All JSON records emitted to the ``mdc-mcp-audit`` logger.
    """
    with caplog.at_level(logging.INFO, logger="mdc-mcp-audit"):
        emit_audit_entry(entry)

    records = []
    for record in caplog.records:
        if record.name == "mdc-mcp-audit":
            try:
                records.append(json.loads(record.message))
            except json.JSONDecodeError:
                pass
    return records


# ---------------------------------------------------------------------------
# Test 1: CI path produces audit entry WITH broker_request_id
# ---------------------------------------------------------------------------


class TestCIPathAuditAttribution:
    """CI-scoped requests produce audit entries with broker_request_id,
    enabling the join to the Token_Broker log (R6.1, Property 12)."""

    def test_ci_audit_entry_has_broker_request_id(self, caplog):
        """Validates: R6.1, Property 12 — CI audit entry includes broker_request_id."""
        ctx = PrincipalContext(
            principal="ci-readonly",
            scope="mcp/ci-readonly",
            broker_request_id="ci-broker-abc-123",
        )
        entry = build_audit_entry(
            ctx=ctx,
            tool_name="search_documentation",
            outcome="success",
            request_id="mcp-req-001",
        )
        records = _capture_audit_log(entry, caplog)

        assert len(records) == 1
        record = records[0]
        assert record["broker_request_id"] == "ci-broker-abc-123"
        assert record["caller_sub"] == "ci-readonly"
        assert record["scope"] == "mcp/ci-readonly"
        assert record["tool"] == "search_documentation"
        assert record["outcome"] == "success"

    def test_ci_broker_id_is_joinable_string(self, caplog):
        """The broker_request_id is a non-empty string suitable as a join key."""
        ctx = PrincipalContext(
            principal="ci-readonly",
            scope="mcp/ci-readonly",
            broker_request_id="br-join-key-xyz",
        )
        entry = build_audit_entry(ctx=ctx, tool_name="get_server_info",
                                  outcome="success", request_id="mcp-req-002")
        records = _capture_audit_log(entry, caplog)

        assert len(records) == 1
        broker_id = records[0]["broker_request_id"]
        assert isinstance(broker_id, str)
        assert len(broker_id) > 0


# ---------------------------------------------------------------------------
# Test 2: HPC path produces audit entry WITH broker_request_id
# ---------------------------------------------------------------------------


class TestHPCPathAuditAttribution:
    """HPC-scoped requests produce audit entries with broker_request_id,
    enabling the join to the Token_Broker log (R6.1, Property 12)."""

    def test_hpc_audit_entry_has_broker_request_id(self, caplog):
        """Validates: R6.1, Property 12 — HPC audit entry includes broker_request_id."""
        ctx = PrincipalContext(
            principal="hpc-user",
            scope="mcp/hpc-user",
            broker_request_id="hpc-broker-def-456",
        )
        entry = build_audit_entry(
            ctx=ctx,
            tool_name="search_issues",
            outcome="success",
            request_id="mcp-req-003",
        )
        records = _capture_audit_log(entry, caplog)

        assert len(records) == 1
        record = records[0]
        assert record["broker_request_id"] == "hpc-broker-def-456"
        assert record["caller_sub"] == "hpc-user"
        assert record["scope"] == "mcp/hpc-user"
        assert record["tool"] == "search_issues"

    def test_hpc_with_source_ip(self, caplog):
        """HPC audit entry includes both broker_request_id and source_ip (R6.2)."""
        ctx = PrincipalContext(
            principal="hpc-user",
            scope="mcp/hpc-user",
            broker_request_id="hpc-broker-ghi-789",
        )
        entry = build_audit_entry(
            ctx=ctx,
            tool_name="get_operational_guidance",
            outcome="success",
            request_id="mcp-req-004",
            source_ip="10.0.1.42",
        )
        records = _capture_audit_log(entry, caplog)

        assert len(records) == 1
        record = records[0]
        assert record["broker_request_id"] == "hpc-broker-ghi-789"
        assert record["source_ip"] == "10.0.1.42"


# ---------------------------------------------------------------------------
# Test 3: Developer path produces audit entry WITHOUT broker_request_id
# ---------------------------------------------------------------------------


class TestDeveloperPathAuditAttribution:
    """Developer-sigv4 requests produce audit entries WITHOUT broker_request_id.
    The field is omitted from the JSON output, not emitted as null (R6.1)."""

    def test_developer_audit_entry_omits_broker_request_id(self, caplog):
        """Validates: R6.1, Property 12 — developer audit has no broker_request_id."""
        ctx = derive_principal({})  # No headers → developer-sigv4
        assert ctx.broker_request_id is None  # precondition

        entry = build_audit_entry(
            ctx=ctx,
            tool_name="get_code_context",
            outcome="success",
            request_id="mcp-req-005",
        )
        records = _capture_audit_log(entry, caplog)

        assert len(records) == 1
        record = records[0]
        # broker_request_id must be ABSENT (omitted), not present as null.
        assert "broker_request_id" not in record, (
            "Developer audit entry must omit broker_request_id, not emit it as null"
        )
        assert record["caller_sub"] == "developer-sigv4"
        assert record["scope"] == "developer-sigv4"

    def test_developer_audit_entry_omits_source_ip_when_absent(self, caplog):
        """source_ip is also omitted (not null) when unavailable."""
        ctx = derive_principal({})
        entry = build_audit_entry(
            ctx=ctx,
            tool_name="mcp_health_check",
            outcome="success",
            request_id="mcp-req-006",
            source_ip=None,
        )
        records = _capture_audit_log(entry, caplog)

        assert len(records) == 1
        record = records[0]
        assert "broker_request_id" not in record
        assert "source_ip" not in record


# ---------------------------------------------------------------------------
# Test 4: One request → exactly one audit entry
# ---------------------------------------------------------------------------


class TestExactlyOneAuditEntry:
    """A single invocation of emit_audit_entry produces exactly one JSON
    record in the log output — no more, no fewer."""

    def test_single_emit_produces_exactly_one_record(self, caplog):
        """Validates: Property 12 — one request → one audit entry."""
        ctx = PrincipalContext(
            principal="ci-readonly",
            scope="mcp/ci-readonly",
            broker_request_id="br-one-shot",
        )
        entry = build_audit_entry(
            ctx=ctx,
            tool_name="analyze_code_structure",
            outcome="success",
            request_id="mcp-req-007",
        )
        records = _capture_audit_log(entry, caplog)

        assert len(records) == 1, (
            f"Expected exactly 1 audit record, got {len(records)}"
        )

    def test_two_sequential_emits_produce_two_records(self, caplog):
        """Two separate emits → two separate records (not coalesced)."""
        ctx = PrincipalContext(
            principal="hpc-user",
            scope="mcp/hpc-user",
            broker_request_id="br-seq-1",
        )
        entry1 = build_audit_entry(ctx=ctx, tool_name="search_documentation",
                                   outcome="success", request_id="mcp-req-008a")
        entry2 = build_audit_entry(ctx=ctx, tool_name="get_server_info",
                                   outcome="success", request_id="mcp-req-008b")

        with caplog.at_level(logging.INFO, logger="mdc-mcp-audit"):
            emit_audit_entry(entry1)
            emit_audit_entry(entry2)

        audit_records = []
        for record in caplog.records:
            if record.name == "mdc-mcp-audit":
                try:
                    audit_records.append(json.loads(record.message))
                except json.JSONDecodeError:
                    pass

        assert len(audit_records) == 2
        # Verify they are distinct entries (different request_ids and tool names).
        request_ids = {r["request_id"] for r in audit_records}
        assert request_ids == {"mcp-req-008a", "mcp-req-008b"}
        tool_names = {r["tool"] for r in audit_records}
        assert tool_names == {"search_documentation", "get_server_info"}


# ---------------------------------------------------------------------------
# Test 5: broker_request_id is the join key — value match
# ---------------------------------------------------------------------------


class TestBrokerRequestIdJoinKey:
    """The audit entry's broker_request_id matches what was in the
    PrincipalContext, proving joinability to the Token_Broker log."""

    @pytest.mark.parametrize("broker_id", [
        "br-simple",
        "br-uuid-550e8400-e29b-41d4-a716-446655440000",
        "br-with-special-chars_123.456",
        "a",  # minimal non-empty
    ])
    def test_broker_id_roundtrips_through_audit(self, caplog, broker_id: str):
        """Validates: Property 12 — the join key is preserved exactly."""
        ctx = PrincipalContext(
            principal="ci-readonly",
            scope="mcp/ci-readonly",
            broker_request_id=broker_id,
        )
        entry = build_audit_entry(ctx=ctx, tool_name="get_server_info",
                                  outcome="success", request_id="mcp-req-join")
        records = _capture_audit_log(entry, caplog)

        assert len(records) == 1
        assert records[0]["broker_request_id"] == broker_id, (
            f"Audit broker_request_id {records[0].get('broker_request_id')!r} "
            f"does not match PrincipalContext value {broker_id!r}"
        )

    def test_broker_id_matches_across_principals(self, caplog):
        """Same broker_request_id value, different principals — both join correctly."""
        shared_broker_id = "br-shared-across-principals"

        ci_ctx = PrincipalContext(
            principal="ci-readonly", scope="mcp/ci-readonly",
            broker_request_id=shared_broker_id,
        )
        hpc_ctx = PrincipalContext(
            principal="hpc-user", scope="mcp/hpc-user",
            broker_request_id=shared_broker_id,
        )

        ci_entry = build_audit_entry(ctx=ci_ctx, tool_name="get_server_info",
                                     outcome="success", request_id="mcp-req-ci")
        hpc_entry = build_audit_entry(ctx=hpc_ctx, tool_name="search_issues",
                                      outcome="success", request_id="mcp-req-hpc")

        with caplog.at_level(logging.INFO, logger="mdc-mcp-audit"):
            emit_audit_entry(ci_entry)
            emit_audit_entry(hpc_entry)

        audit_records = []
        for record in caplog.records:
            if record.name == "mdc-mcp-audit":
                try:
                    audit_records.append(json.loads(record.message))
                except json.JSONDecodeError:
                    pass

        assert len(audit_records) == 2
        for rec in audit_records:
            assert rec["broker_request_id"] == shared_broker_id


# ---------------------------------------------------------------------------
# Test 6: Full chain — interceptor → derive_principal → audit → log
# ---------------------------------------------------------------------------


class TestFullChainAttribution:
    """End-to-end: interceptor event → derive_principal → build_audit_entry →
    emit → parse. Proves the chain from JWT claim to audit log record."""

    def test_ci_full_chain(self, caplog):
        """Validates: Property 12 — CI JWT claim flows to audit log entry."""
        broker_id = "ci-full-chain-broker-42"

        # Step 1: Interceptor processes the JWT
        out_headers = _run_interceptor({
            "scope": "mcp/ci-readonly",
            "broker_request_id": broker_id,
        })

        # Step 2: MCP_Server middleware derives the principal
        ctx = derive_principal(out_headers)
        assert ctx.principal == "ci-readonly"
        assert ctx.scope == "mcp/ci-readonly"
        assert ctx.broker_request_id == broker_id

        # Step 3: Build and emit the audit entry
        entry = build_audit_entry(
            ctx=ctx,
            tool_name="search_documentation",
            outcome="success",
            request_id="mcp-req-fullchain-ci",
        )
        records = _capture_audit_log(entry, caplog)

        # Step 4: Verify the audit log record
        assert len(records) == 1
        record = records[0]
        assert record["caller_sub"] == "ci-readonly"
        assert record["scope"] == "mcp/ci-readonly"
        assert record["broker_request_id"] == broker_id
        assert record["tool"] == "search_documentation"
        assert record["outcome"] == "success"
        assert record["request_id"] == "mcp-req-fullchain-ci"
        assert "ts" in record  # ISO-8601 timestamp present

    def test_hpc_full_chain(self, caplog):
        """Validates: Property 12 — HPC JWT claim flows to audit log entry."""
        broker_id = "hpc-full-chain-broker-99"

        out_headers = _run_interceptor({
            "scope": "mcp/hpc-user",
            "broker_request_id": broker_id,
        })

        ctx = derive_principal(out_headers)
        assert ctx.principal == "hpc-user"
        assert ctx.scope == "mcp/hpc-user"
        assert ctx.broker_request_id == broker_id

        entry = build_audit_entry(
            ctx=ctx,
            tool_name="search_issues",
            outcome="success",
            request_id="mcp-req-fullchain-hpc",
            source_ip="192.168.1.100",
        )
        records = _capture_audit_log(entry, caplog)

        assert len(records) == 1
        record = records[0]
        assert record["caller_sub"] == "hpc-user"
        assert record["scope"] == "mcp/hpc-user"
        assert record["broker_request_id"] == broker_id
        assert record["tool"] == "search_issues"
        assert record["source_ip"] == "192.168.1.100"

    def test_developer_full_chain_no_interceptor(self, caplog):
        """Validates: Property 12 — developer path has no broker_request_id.

        The developer path bypasses the Gateway entirely (SigV4 direct),
        so there is no interceptor step and no broker_request_id.
        """
        # Step 1: No interceptor — derive directly from empty headers
        ctx = derive_principal({})
        assert ctx.principal == "developer-sigv4"
        assert ctx.broker_request_id is None

        # Step 2: Build and emit
        entry = build_audit_entry(
            ctx=ctx,
            tool_name="get_code_context",
            outcome="success",
            request_id="mcp-req-fullchain-dev",
        )
        records = _capture_audit_log(entry, caplog)

        # Step 3: Verify
        assert len(records) == 1
        record = records[0]
        assert record["caller_sub"] == "developer-sigv4"
        assert record["scope"] == "developer-sigv4"
        assert "broker_request_id" not in record
        assert record["tool"] == "get_code_context"

    def test_authorization_denied_outcome_still_produces_audit_entry(self, caplog):
        """An authorization-denied outcome still produces an audit entry
        with the broker_request_id — proving attribution works for denials too."""
        broker_id = "br-denied-attempt"

        out_headers = _run_interceptor({
            "scope": "mcp/ci-readonly",
            "broker_request_id": broker_id,
        })

        ctx = derive_principal(out_headers)

        # Simulate a denied tool call (CI trying a mutation tool)
        entry = build_audit_entry(
            ctx=ctx,
            tool_name="start_sdd_session",
            outcome="authorization_denied",
            request_id="mcp-req-denied",
        )
        records = _capture_audit_log(entry, caplog)

        assert len(records) == 1
        record = records[0]
        assert record["broker_request_id"] == broker_id
        assert record["outcome"] == "authorization_denied"
        assert record["tool"] == "start_sdd_session"
        assert record["caller_sub"] == "ci-readonly"
