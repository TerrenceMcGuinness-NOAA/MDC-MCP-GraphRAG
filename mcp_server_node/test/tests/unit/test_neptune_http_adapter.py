"""Property-based tests for Neptune HTTP adapter (aws_backend.py)."""

import sys
import os
import json
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'scripts'))

from unittest.mock import patch, MagicMock

from hypothesis import given, settings
import hypothesis.strategies as st

from aws_backend import _normalize_endpoint, NeptuneResult, NeptuneSession


# ── Strategies ────────────────────────────────────────────────────────────────

# Generate parameter dicts with string/int/float/bool/None/list/nested-dict values
_param_values = st.one_of(
    st.none(), st.text(), st.integers(), st.floats(allow_nan=False),
    st.booleans(), st.lists(st.integers()),
    st.dictionaries(st.text(), st.text())
)
_param_dicts = st.dictionaries(st.text(min_size=1), _param_values)

# Generate lists of dicts with string keys and mixed-type values (Neptune response records)
_neptune_records = st.lists(st.dictionaries(
    st.text(min_size=1, alphabet=st.characters(whitelist_categories=('L',))),
    st.one_of(st.text(), st.integers(), st.floats(allow_nan=False), st.none())
))

# Generate realistic hostnames: letter followed by alphanumeric/hyphens, then a TLD
_hostname = st.from_regex(r'[a-z][a-z0-9\-]{1,20}\.[a-z]{2,6}', fullmatch=True)

# Randomly prepend one of the four endpoint formats
_endpoint = _hostname.flatmap(lambda h: st.sampled_from([
    f"wss://{h}:8182/opencypher",
    f"bolt+s://{h}:8182",
    f"https://{h}:8182",
    h,
]))


# ── Property 1 ────────────────────────────────────────────────────────────────
# Feature: neptune-python-sigv4-ingestion, Property 1: Parameter serialization preserves all values

@given(params=_param_dicts)
@settings(max_examples=100)
def test_param_serialization_preserves_values(params):
    """For any valid parameter dictionary containing strings, integers, floats,
    booleans, None, lists, and nested dicts, when session.run(query, **params)
    is called, the HTTP POST body SHALL contain a parameters field whose
    JSON-decoded value is equal to the original parameter dictionary.

    **Validates: Requirements 3.1, 3.4, 3.5**
    """
    # Create a mock urllib3 pool that returns a successful response
    mock_pool = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.data = json.dumps({"results": []}).encode("utf-8")
    mock_pool.request.return_value = mock_response

    # Mock boto3.Session to return fake credentials
    with patch("aws_backend.boto3.Session") as mock_boto_session:
        mock_creds = MagicMock()
        mock_creds.access_key = "AKIAIOSFODNN7EXAMPLE"
        mock_creds.secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        mock_creds.token = None
        mock_boto_session.return_value.get_credentials.return_value \
            .get_frozen_credentials.return_value = mock_creds

        session = NeptuneSession(
            endpoint="https://test-host:8182/opencypher",
            region="us-east-1",
            pool=mock_pool,
        )
        session.run("RETURN 1", **params)

    # Capture the POST body from the mock pool.request call
    call_args = mock_pool.request.call_args
    body = call_args[1].get("body") if "body" in (call_args[1] or {}) else call_args[0][2] if len(call_args[0]) > 2 else call_args[1]["body"]
    parsed = urllib.parse.parse_qs(body, keep_blank_values=True)

    if params:
        assert "parameters" in parsed, "POST body should contain 'parameters' field when params are provided"
        decoded_params = json.loads(parsed["parameters"][0])
        assert decoded_params == params, (
            f"Decoded parameters {decoded_params!r} != original {params!r}"
        )
    else:
        assert "parameters" not in parsed, "POST body should not contain 'parameters' field when no params"


# ── Property 2 ────────────────────────────────────────────────────────────────
# Feature: neptune-python-sigv4-ingestion, Property 2: Response parsing preserves all records and column access

@given(records=_neptune_records)
@settings(max_examples=100)
def test_response_parsing_preserves_records(records):
    """For any Neptune JSON response containing N result records (N >= 0),
    NeptuneResult yields exactly N records via iteration where each record
    supports column-name access returning the correct value, and single()
    returns the first record when N > 0 or None when N = 0.

    **Validates: Requirements 4.1, 4.2, 4.3, 4.5**
    """
    result = NeptuneResult(records)

    # single() returns first record or None
    if len(records) == 0:
        assert result.single() is None, "single() should return None for empty results"
    else:
        first = result.single()
        assert first is records[0], "single() should return the first record"

    # Iteration yields exactly N records
    iterated = list(result)
    assert len(iterated) == len(records), (
        f"Expected {len(records)} records, got {len(iterated)}"
    )

    # Each record supports column-name access with correct values
    for i, record in enumerate(iterated):
        for key, value in records[i].items():
            assert record[key] is value, (
                f"Record {i} column '{key}': expected {value!r}, got {record[key]!r}"
            )


# ── Property 3 ────────────────────────────────────────────────────────────────
# Feature: neptune-python-sigv4-ingestion, Property 3: Endpoint normalization produces valid HTTPS URL

@given(endpoint=_endpoint)
@settings(max_examples=100)
def test_endpoint_normalization_valid_url(endpoint):
    """For any Neptune endpoint with wss://, bolt+s://, https://, or bare hostname
    format, _normalize_endpoint produces a URL that starts with https://, contains
    the original hostname, and ends with /opencypher.

    **Validates: Requirements 7.2, 7.3, 7.4**
    """
    result = _normalize_endpoint(endpoint)

    # Extract the original hostname from the input
    hostname = endpoint
    for prefix in ("wss://", "bolt+s://", "https://"):
        if hostname.startswith(prefix):
            hostname = hostname[len(prefix):]
            break
    # Strip port and path to get bare hostname
    hostname = hostname.split(":")[0].split("/")[0]

    assert result.startswith("https://"), f"Expected https:// prefix, got: {result}"
    assert hostname in result, f"Hostname '{hostname}' not found in: {result}"
    assert result.endswith("/opencypher"), f"Expected /opencypher suffix, got: {result}"


# ══════════════════════════════════════════════════════════════════════════════
# Unit Tests — Tasks 6.1 – 6.4
# ══════════════════════════════════════════════════════════════════════════════

import time as _time_mod
import pytest

from aws_backend import (
    NeptuneHTTPAdapter,
    NeptuneQueryError,
    NeptuneConnectionError,
    get_graph_driver,
    _normalize_endpoint,
    NeptuneResult,
    NeptuneSession,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _neptune_json_response(results: list[dict]) -> bytes:
    """Build a mock Neptune JSON response body."""
    return json.dumps({"results": results}).encode("utf-8")


def _mock_boto3_session():
    """Return a MagicMock that behaves like boto3.Session with fake creds."""
    session = MagicMock()
    creds = MagicMock()
    creds.access_key = "AKIAIOSFODNN7EXAMPLE"
    creds.secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    creds.token = None
    session.return_value.get_credentials.return_value \
        .get_frozen_credentials.return_value = creds
    return session


def _make_session_with_mock_pool(pool_mock):
    """Create a NeptuneSession wired to a mock pool, with boto3 patched."""
    return NeptuneSession(
        endpoint="https://test-host:8182/opencypher",
        region="us-east-1",
        pool=pool_mock,
    )


def _ok_response(results=None):
    """Return a mock urllib3 response with status 200."""
    resp = MagicMock()
    resp.status = 200
    resp.data = _neptune_json_response(results or [])
    return resp


# ── 6.2  Factory and session unit tests ──────────────────────────────────────

class TestFactoryAndSession:

    @patch("aws_backend.urllib3.PoolManager")
    @patch("aws_backend.BACKEND", "aws")
    def test_get_graph_driver_returns_adapter(self, _pool_cls):
        with patch.dict(os.environ, {"NEPTUNE_ENDPOINT": "myhost.amazonaws.com"}):
            driver = get_graph_driver()
            assert isinstance(driver, NeptuneHTTPAdapter)

    @patch("aws_backend.BACKEND", "aws")
    def test_get_graph_driver_exits_without_endpoint(self):
        env = os.environ.copy()
        env.pop("NEPTUNE_ENDPOINT", None)
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                get_graph_driver()

    @patch("aws_backend.boto3.Session", new_callable=_mock_boto3_session)
    @patch("aws_backend.urllib3.PoolManager")
    def test_session_context_manager(self, pool_cls, _boto):
        pool_cls.return_value = MagicMock()
        adapter = NeptuneHTTPAdapter("myhost", "us-east-1")
        with adapter.session() as s:
            assert isinstance(s, NeptuneSession)

    @patch("aws_backend.boto3.Session", new_callable=_mock_boto3_session)
    def test_run_sends_post_to_opencypher(self, _boto):
        pool = MagicMock()
        pool.request.return_value = _ok_response()
        s = _make_session_with_mock_pool(pool)
        s.run("RETURN 1")
        args, kwargs = pool.request.call_args
        assert args[0] == "POST"
        assert args[1].endswith("/opencypher")

    @patch("aws_backend.boto3.Session", new_callable=_mock_boto3_session)
    def test_run_includes_sigv4_auth_header(self, _boto):
        pool = MagicMock()
        pool.request.return_value = _ok_response()
        s = _make_session_with_mock_pool(pool)
        s.run("RETURN 1")
        headers = pool.request.call_args[1]["headers"]
        assert "Authorization" in headers

    @patch("aws_backend.boto3.Session", new_callable=_mock_boto3_session)
    def test_content_type_header(self, _boto):
        pool = MagicMock()
        pool.request.return_value = _ok_response()
        s = _make_session_with_mock_pool(pool)
        s.run("RETURN 1")
        headers = pool.request.call_args[1]["headers"]
        assert headers["Content-Type"] == "application/x-www-form-urlencoded"

    @patch("aws_backend.boto3.Session", new_callable=_mock_boto3_session)
    def test_request_timeout_30s(self, _boto):
        pool = MagicMock()
        pool.request.return_value = _ok_response()
        s = _make_session_with_mock_pool(pool)
        s.run("RETURN 1")
        assert pool.request.call_args[1]["timeout"] == 30

    def test_credentials_refreshed_per_request(self):
        pool = MagicMock()
        pool.request.return_value = _ok_response()
        with patch("aws_backend.boto3.Session") as mock_session_cls:
            mock_session_cls.side_effect = lambda: _mock_boto3_session().return_value
            s = _make_session_with_mock_pool(pool)
            s.run("RETURN 1")
            s.run("RETURN 2")
            # boto3.Session() is called once per run → get_credentials called each time
            assert mock_session_cls.call_count == 2


# ── 6.3  Parameter and result unit tests ─────────────────────────────────────

class TestParametersAndResults:

    @patch("aws_backend.boto3.Session", new_callable=_mock_boto3_session)
    def test_run_with_params_includes_parameters_field(self, _boto):
        pool = MagicMock()
        pool.request.return_value = _ok_response()
        s = _make_session_with_mock_pool(pool)
        s.run("MERGE (n {name: $name})", name="Alice")
        body = pool.request.call_args[1]["body"]
        assert "parameters=" in body

    @patch("aws_backend.boto3.Session", new_callable=_mock_boto3_session)
    def test_run_without_params_omits_parameters_field(self, _boto):
        pool = MagicMock()
        pool.request.return_value = _ok_response()
        s = _make_session_with_mock_pool(pool)
        s.run("RETURN 1")
        body = pool.request.call_args[1]["body"]
        assert "parameters" not in body

    def test_result_iteration(self):
        records = [{"a": 1}, {"a": 2}, {"a": 3}]
        result = NeptuneResult(records)
        collected = list(result)
        assert len(collected) == 3
        assert [r["a"] for r in collected] == [1, 2, 3]

    def test_result_single_returns_first(self):
        result = NeptuneResult([{"x": 42}, {"x": 99}])
        assert result.single() == {"x": 42}

    def test_result_single_empty(self):
        result = NeptuneResult([])
        assert result.single() is None

    def test_result_column_access(self):
        result = NeptuneResult([{"col": "hello", "num": 7}])
        record = result.single()
        assert record["col"] == "hello"
        assert record["num"] == 7


# ── 6.4  Error handling and endpoint unit tests ──────────────────────────────

class TestErrorHandlingAndEndpoints:

    @patch("aws_backend.time.sleep")
    @patch("aws_backend.boto3.Session", new_callable=_mock_boto3_session)
    def test_retry_on_503(self, _boto, mock_sleep):
        pool = MagicMock()
        fail_resp = MagicMock()
        fail_resp.status = 503
        fail_resp.data = b'{"message":"Service Unavailable"}'
        ok = _ok_response([{"v": 1}])
        pool.request.side_effect = [fail_resp, fail_resp, fail_resp, ok]
        s = _make_session_with_mock_pool(pool)
        result = s.run("RETURN 1")
        assert result.single() == {"v": 1}
        assert pool.request.call_count == 4  # 3 failures + 1 success

    @patch("aws_backend.time.sleep")
    @patch("aws_backend.boto3.Session", new_callable=_mock_boto3_session)
    def test_retry_exhausted_raises(self, _boto, mock_sleep):
        pool = MagicMock()
        fail_resp = MagicMock()
        fail_resp.status = 503
        fail_resp.data = b'{"message":"Service Unavailable"}'
        pool.request.return_value = fail_resp
        s = _make_session_with_mock_pool(pool)
        with pytest.raises(NeptuneQueryError) as exc_info:
            s.run("RETURN 1")
        assert exc_info.value.status_code == 503

    @patch("aws_backend.boto3.Session", new_callable=_mock_boto3_session)
    def test_error_response_raises(self, _boto):
        pool = MagicMock()
        err_resp = MagicMock()
        err_resp.status = 400
        err_resp.data = b'{"message":"Syntax error"}'
        pool.request.return_value = err_resp
        s = _make_session_with_mock_pool(pool)
        with pytest.raises(NeptuneQueryError) as exc_info:
            s.run("BAD QUERY")
        assert exc_info.value.status_code == 400

    @patch("aws_backend.boto3.Session", new_callable=_mock_boto3_session)
    def test_timeout_raises(self, _boto):
        pool = MagicMock()
        pool.request.side_effect = Exception("Connection timed out")
        s = _make_session_with_mock_pool(pool)
        with pytest.raises(NeptuneConnectionError):
            s.run("RETURN 1")

    @patch("aws_backend.boto3.Session", new_callable=_mock_boto3_session)
    def test_verify_connectivity_sends_return_1(self, _boto):
        pool = MagicMock()
        pool.request.return_value = _ok_response()
        adapter = NeptuneHTTPAdapter.__new__(NeptuneHTTPAdapter)
        adapter._endpoint = "https://test-host:8182/opencypher"
        adapter._region = "us-east-1"
        adapter._pool = pool
        adapter.verify_connectivity()
        body = pool.request.call_args[1]["body"]
        parsed = urllib.parse.parse_qs(body)
        assert "RETURN 1" in parsed.get("query", [""])[0]

    @patch("aws_backend.boto3.Session", new_callable=_mock_boto3_session)
    def test_verify_connectivity_prints_ok(self, _boto, capsys=None):
        pool = MagicMock()
        pool.request.return_value = _ok_response()
        adapter = NeptuneHTTPAdapter.__new__(NeptuneHTTPAdapter)
        adapter._endpoint = "https://test-host:8182/opencypher"
        adapter._region = "us-east-1"
        adapter._pool = pool
        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        with redirect_stderr(buf):
            adapter.verify_connectivity()
        assert "[OK]" in buf.getvalue()

    def test_endpoint_normalization_wss(self):
        result = _normalize_endpoint("wss://myhost:8182/opencypher")
        assert result == "https://myhost:8182/opencypher"

    def test_endpoint_normalization_bolt(self):
        result = _normalize_endpoint("bolt+s://myhost:8182")
        assert result == "https://myhost:8182/opencypher"

    def test_endpoint_normalization_bare(self):
        result = _normalize_endpoint("myhost.region.neptune.amazonaws.com")
        assert result == "https://myhost.region.neptune.amazonaws.com:8182/opencypher"
