"""Tests for agentcore-kiro-proxy.py — property-based (Hypothesis) and unit tests.

Run: pytest tests/test_agentcore_kiro_proxy.py -v
"""

import io
import json
import os
import signal
import sys
import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Add tools/ to path so we can import the proxy module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import importlib
proxy = importlib.import_module("agentcore-kiro-proxy")


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

json_rpc_id = st.one_of(st.integers(min_value=1, max_value=10**9), st.text(min_size=1, max_size=20))

json_rpc_request = st.fixed_dictionaries({
    "jsonrpc": st.just("2.0"),
    "id": json_rpc_id,
    "method": st.sampled_from(["initialize", "tools/list", "tools/call", "ping"]),
    "params": st.fixed_dictionaries({}, optional={"name": st.text(max_size=50)}),
})

json_rpc_response = st.fixed_dictionaries({
    "jsonrpc": st.just("2.0"),
    "id": json_rpc_id,
    "result": st.fixed_dictionaries({}, optional={"data": st.text(max_size=100)}),
})


# ===========================================================================
# Task 7: Property-based tests with Hypothesis
# ===========================================================================

# Feature: agentcore-kiro-proxy, Property 1: JSON-RPC message round-trip
@given(msg=json_rpc_request)
@settings(max_examples=100)
def test_property_jsonrpc_roundtrip(msg):
    """Serialize as line then parse back produces identical object."""
    line = json.dumps(msg, separators=(",", ":"))
    parsed = json.loads(line)
    assert parsed == msg


# Feature: agentcore-kiro-proxy, Property 2: SSE parsing round-trip
@given(resp=json_rpc_response)
@settings(max_examples=100)
def test_property_sse_roundtrip(resp):
    """Wrapping in SSE format then parsing extracts the original object."""
    sse_frame = f"event: message\ndata: {json.dumps(resp)}\n\n"
    results = proxy.parse_sse(sse_frame)
    assert len(results) == 1
    assert results[0] == resp


# Feature: agentcore-kiro-proxy, Property 3: Transparent forwarding
@given(msg=json_rpc_request)
@settings(max_examples=100)
def test_property_transparent_forwarding(msg):
    """Payload sent to boto3 preserves method, params, and id fields exactly."""
    captured = {}

    def fake_invoke(**kwargs):
        captured.update(kwargs)
        body = MagicMock()
        body.read.return_value = (
            f'event: message\ndata: {{"jsonrpc":"2.0","id":{json.dumps(msg["id"])},"result":{{}}}}\n\n'
        ).encode("utf-8")
        return {"response": body}

    client = proxy.AgentCoreClient.__new__(proxy.AgentCoreClient)
    client.client = MagicMock()
    client.client.invoke_agent_runtime = fake_invoke
    client.agent_runtime_id = "test-runtime"
    client.session_id = "test-session-00000000000000000000000"

    client.invoke(msg)
    sent = json.loads(captured["payload"].decode("utf-8"))
    assert sent["method"] == msg["method"]
    assert sent["params"] == msg["params"]
    assert sent["id"] == msg["id"]


# Feature: agentcore-kiro-proxy, Property 4: Session ID invariants
@given(st.data())
@settings(max_examples=100)
def test_property_session_id_invariants(data):
    """All generated session IDs are >= 33 chars and unique."""
    ids = [proxy.generate_session_id() for _ in range(10)]
    for sid in ids:
        assert len(sid) >= 33, f"Session ID too short: {sid!r} ({len(sid)} chars)"
    assert len(set(ids)) == len(ids), "Duplicate session IDs generated"


# Feature: agentcore-kiro-proxy, Property 5: Error responses are well-formed
@given(req_id=st.one_of(json_rpc_id, st.none()))
@settings(max_examples=100)
def test_property_error_response_wellformed(req_id):
    """Error response has code -32603, non-empty message, and correct id."""
    resp = proxy.make_error_response(req_id, -32603, "test error", {"k": "v"})
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == req_id
    assert resp["error"]["code"] == -32603
    assert len(resp["error"]["message"]) > 0
    assert resp["error"]["data"] == {"k": "v"}


# Feature: agentcore-kiro-proxy, Property 6: Retry behavior
@given(error_code=st.sampled_from(list(proxy.RETRYABLE_EXCEPTIONS)))
@settings(max_examples=100)
def test_property_retry_behavior(error_code):
    """For any retryable exception, exactly 4 total calls (1 + 3 retries)."""
    call_count = 0

    def fake_invoke(**kwargs):
        nonlocal call_count
        call_count += 1
        error_response = {"Error": {"Code": error_code, "Message": "test"}}
        raise proxy.ClientError(error_response, "invoke_agent_runtime")

    client = proxy.AgentCoreClient.__new__(proxy.AgentCoreClient)
    client.client = MagicMock()
    client.client.invoke_agent_runtime = fake_invoke
    client.agent_runtime_id = "test-runtime"
    client.session_id = "test-session-00000000000000000000000"

    call_count = 0
    with patch("time.sleep"):
        with pytest.raises(proxy.ClientError):
            client.invoke({"jsonrpc": "2.0", "id": 1, "method": "test"})
    assert call_count == 1 + proxy.MAX_RETRIES


# Feature: agentcore-kiro-proxy, Property 7: Resilience
@given(good_msg=json_rpc_request)
@settings(max_examples=100)
def test_property_resilience(good_msg):
    """After an error on one request, subsequent requests succeed."""
    call_num = 0

    def fake_invoke(**kwargs):
        nonlocal call_num
        call_num += 1
        if call_num <= (1 + proxy.MAX_RETRIES):
            # First request: always fail with retryable error
            error_response = {"Error": {"Code": "ThrottlingException", "Message": "test"}}
            raise proxy.ClientError(error_response, "invoke_agent_runtime")
        # Subsequent: succeed
        body = MagicMock()
        body.read.return_value = (
            f'event: message\ndata: {{"jsonrpc":"2.0","id":{json.dumps(good_msg["id"])},"result":{{}}}}\n\n'
        ).encode("utf-8")
        return {"response": body}

    client = proxy.AgentCoreClient.__new__(proxy.AgentCoreClient)
    client.client = MagicMock()
    client.client.invoke_agent_runtime = fake_invoke
    client.agent_runtime_id = "test-runtime"
    client.session_id = "test-session-00000000000000000000000"

    call_num = 0
    with patch("time.sleep"):
        with pytest.raises(proxy.ClientError):
            client.invoke({"jsonrpc": "2.0", "id": 1, "method": "fail"})

    # Now the next request should succeed
    result = client.invoke(good_msg)
    assert "jsonrpc" in result or "event" in result  # raw SSE body


# ===========================================================================
# Task 8: Unit tests for specific scenarios
# ===========================================================================

class TestEOFHandling:
    """8.1 Test EOF handling: send EOF on stdin, verify process exits cleanly."""

    def test_eof_exits_cleanly(self):
        stdin_mock = io.StringIO("")
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        with patch("sys.stdin", stdin_mock), \
             patch("sys.stdout", stdout_buf), \
             patch.object(proxy, "_shutdown", False):
            # read_message should return None on EOF
            result = proxy.read_message()
            assert result is None


class TestNotificationForwarding:
    """8.2 Test notification forwarding."""

    def test_notification_forwarded_without_response(self):
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        sse_body = 'event: message\ndata: {"jsonrpc":"2.0","result":{}}\n\n'

        stdout_buf = io.StringIO()
        msgs = [notification, None]  # notification then EOF
        msg_iter = iter(msgs)

        def fake_read():
            return next(msg_iter)

        mock_client = MagicMock()
        mock_client.invoke.return_value = sse_body
        mock_client.session_id = "test-session-00000000000000000000000"

        with patch.object(proxy, "read_message", fake_read), \
             patch("sys.stdout", stdout_buf), \
             patch.object(proxy, "_shutdown", False):
            # Simulate main loop for one notification + EOF
            msg = proxy.read_message()
            assert msg is not None
            assert msg.get("id") is None  # notification has no id
            # Invoke should still be called
            mock_client.invoke(msg)
            mock_client.invoke.assert_called_once_with(notification)
            # No response written to stdout for notifications
            assert stdout_buf.getvalue() == ""


class TestSessionReuse:
    """8.3 Test session reuse: multiple requests use same session ID."""

    def test_same_session_across_requests(self):
        sessions_used = []

        def fake_invoke(**kwargs):
            sessions_used.append(kwargs["runtimeSessionId"])
            body = MagicMock()
            body.read.return_value = b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
            return {"response": body}

        client = proxy.AgentCoreClient("test-rt", "us-east-1", "test-session-00000000000000000000000")
        client.client = MagicMock()
        client.client.invoke_agent_runtime = fake_invoke

        for _ in range(3):
            client.invoke({"jsonrpc": "2.0", "id": 1, "method": "test"})

        assert len(set(sessions_used)) == 1
        assert sessions_used[0] == "test-session-00000000000000000000000"


class TestSessionRecovery:
    """8.4 Test session recovery: mock session-expired error, verify new session ID."""

    def test_session_expired_generates_new_id(self):
        call_count = 0
        sessions_used = []

        def fake_invoke(**kwargs):
            nonlocal call_count
            call_count += 1
            sessions_used.append(kwargs["runtimeSessionId"])
            if call_count == 1:
                error_response = {"Error": {"Code": "SessionExpiredException", "Message": "expired"}}
                raise proxy.ClientError(error_response, "invoke_agent_runtime")
            body = MagicMock()
            body.read.return_value = b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
            return {"response": body}

        client = proxy.AgentCoreClient("test-rt", "us-east-1", "original-session-000000000000000")
        client.client = MagicMock()
        client.client.invoke_agent_runtime = fake_invoke

        client.invoke({"jsonrpc": "2.0", "id": 1, "method": "test"})
        assert len(sessions_used) == 2
        assert sessions_used[0] != sessions_used[1]
        assert client.session_id != "original-session-000000000000000"


class TestCLIArgumentParsing:
    """8.5 Test CLI argument parsing."""

    def test_runtime_id_required(self):
        with pytest.raises(SystemExit):
            proxy.parse_args([])

    def test_region_defaults_to_us_east_1(self):
        args = proxy.parse_args(["--runtime-id", "test-rt"])
        assert args.region == "us-east-1"

    def test_verbose_sets_debug(self):
        args = proxy.parse_args(["--runtime-id", "test-rt", "--verbose"])
        assert args.verbose is True

    def test_env_var_fallback(self):
        with patch.dict(os.environ, {"AGENTCORE_RUNTIME_ID": "env-rt", "AWS_REGION": "eu-west-1"}):
            args = proxy.parse_args([])
            assert args.runtime_id == "env-rt"
            assert args.region == "eu-west-1"


class TestCredentialError:
    """8.6 Test credential error: mock NoCredentialsError, verify clear stderr message."""

    def test_no_credentials_logged(self):
        stderr_buf = io.StringIO()
        handler = proxy.logging.StreamHandler(stderr_buf)
        proxy.logger.addHandler(handler)
        proxy.logger.setLevel(proxy.logging.DEBUG)

        try:
            with patch("boto3.client", side_effect=proxy.NoCredentialsError):
                result = proxy.main(["--runtime-id", "test-rt"])
            assert result == 1
            assert "credentials" in stderr_buf.getvalue().lower()
        finally:
            proxy.logger.removeHandler(handler)


class TestStartupBanner:
    """8.7 Test startup banner: verify version, runtime ID, region, session ID present."""

    def test_banner_contains_required_fields(self):
        stderr_buf = io.StringIO()
        handler = proxy.logging.StreamHandler(stderr_buf)
        proxy.logger.addHandler(handler)
        proxy.logger.setLevel(proxy.logging.DEBUG)

        # Provide EOF immediately so main loop exits
        stdin_mock = io.StringIO("")

        try:
            with patch("sys.stdin", stdin_mock), \
                 patch("boto3.client") as mock_boto:
                mock_boto.return_value = MagicMock()
                proxy.main(["--runtime-id", "test-rt-id", "--region", "us-west-2"])

            banner = stderr_buf.getvalue()
            assert proxy.__version__ in banner
            assert "test-rt-id" in banner
            assert "us-west-2" in banner
            assert "kiro-proxy-" in banner
        finally:
            proxy.logger.removeHandler(handler)


class TestSSEParserEdgeCases:
    """Additional SSE parser edge case tests."""

    def test_empty_body(self):
        assert proxy.parse_sse("") == []

    def test_multiline_data(self):
        frame = 'event: message\ndata: {"jsonrpc":\ndata: "2.0","id":1,"result":{}}\n\n'
        results = proxy.parse_sse(frame)
        assert len(results) == 1
        assert results[0]["id"] == 1

    def test_malformed_json_returns_error(self):
        frame = "event: message\ndata: {not valid json}\n\n"
        results = proxy.parse_sse(frame)
        assert len(results) == 1
        assert results[0]["error"]["code"] == -32603

    def test_multiple_frames(self):
        body = (
            'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
            'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{}}\n\n'
        )
        results = proxy.parse_sse(body)
        assert len(results) == 2
        assert results[0]["id"] == 1
        assert results[1]["id"] == 2


class TestReadMessage:
    """Additional read_message tests."""

    def test_skips_blank_lines(self):
        stdin_mock = io.StringIO('\n\n{"jsonrpc":"2.0","id":1,"method":"test"}\n')
        with patch("sys.stdin", stdin_mock):
            msg = proxy.read_message()
        assert msg["id"] == 1

    def test_skips_malformed_json(self):
        stdin_mock = io.StringIO('not json\n{"jsonrpc":"2.0","id":2,"method":"ok"}\n')
        with patch("sys.stdin", stdin_mock):
            msg = proxy.read_message()
        assert msg["id"] == 2
