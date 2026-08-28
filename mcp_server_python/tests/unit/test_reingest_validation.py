"""Unit tests for reingest_validation.py — Phase 81 Task 4.3.

Mocks the HTTP transport via ``httpx.Client`` and asserts:
- The four MCP calls are made with the right ``tenant_id`` for tenant mode.
- The two shared-once probes are made without ``tenant_id`` for global mode.
- A zero-hit response fails the run (exit code 1).
- A connection error returns exit code 2.
- The payload file is written atomically to the correct path.
- Unknown tenant_id returns exit code 2.
- Dry-run mode does not call the gateway.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make the scripts directory importable.
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

import reingest_validation as rv


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_jsonrpc_response(content_text: str = "Some real results here with enough text to count as a hit") -> dict:
    """Create a minimal JSON-RPC success response."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [
                {"type": "text", "text": content_text}
            ]
        },
    }


def _make_jsonrpc_error_response(message: str = "Tool not found") -> dict:
    """Create a JSON-RPC error response."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32601, "message": message},
    }


def _make_zero_hit_response() -> dict:
    """Create a response with zero hits."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [
                {"type": "text", "text": "[INFO] No results found."}
            ]
        },
    }


class FakeResponse:
    """Minimal httpx.Response mock."""

    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code
        self.text = json.dumps(json_data)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                "error", request=MagicMock(), response=self
            )


# ---------------------------------------------------------------------------
# Tests: _extract_hit_count
# ---------------------------------------------------------------------------


class TestExtractHitCount:
    """Tests for the hit-count extraction heuristic."""

    def test_normal_response_counts_text_blocks(self):
        resp = _make_jsonrpc_response("Here is a real search result with useful content for the user")
        assert rv._extract_hit_count(resp) == 1

    def test_error_response_returns_zero(self):
        resp = _make_jsonrpc_error_response()
        assert rv._extract_hit_count(resp) == 0

    def test_zero_hit_marker_returns_zero(self):
        resp = _make_zero_hit_response()
        assert rv._extract_hit_count(resp) == 0

    def test_skip_block_marker_returns_zero(self):
        resp = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": "[INFO] Skip_Block — collection empty"}]},
        }
        assert rv._extract_hit_count(resp) == 0

    def test_empty_content_returns_zero(self):
        resp = {"jsonrpc": "2.0", "id": 1, "result": {"content": []}}
        assert rv._extract_hit_count(resp) == 0

    def test_no_result_key_returns_zero(self):
        resp = {"jsonrpc": "2.0", "id": 1}
        assert rv._extract_hit_count(resp) == 0

    def test_multiple_text_blocks_counted(self):
        resp = {
            "jsonrpc": "2.0", "id": 1,
            "result": {
                "content": [
                    {"type": "text", "text": "First result block with enough content for validation"},
                    {"type": "text", "text": "Second result block with enough content for validation"},
                ]
            },
        }
        assert rv._extract_hit_count(resp) == 2

    def test_short_text_not_counted(self):
        resp = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": "tiny"}]},
        }
        assert rv._extract_hit_count(resp) == 0


# ---------------------------------------------------------------------------
# Tests: _load_bearer_token
# ---------------------------------------------------------------------------


class TestLoadBearerToken:
    """Tests for bearer token loading."""

    def test_env_var_takes_precedence(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MCP_BEARER_TOKEN", "from-env")
        assert rv._load_bearer_token(str(tmp_path / "nonexist.env")) == "from-env"

    def test_secrets_file_parsed(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
        secrets = tmp_path / "secrets.env"
        secrets.write_text("export MCP_BEARER_TOKEN=my-secret-token\n")
        assert rv._load_bearer_token(str(secrets)) == "my-secret-token"

    def test_secrets_file_without_export(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
        secrets = tmp_path / "secrets.env"
        secrets.write_text("MCP_BEARER_TOKEN=plain-token\n")
        assert rv._load_bearer_token(str(secrets)) == "plain-token"

    def test_missing_file_returns_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
        assert rv._load_bearer_token(str(tmp_path / "nope.env")) == rv.DEFAULT_BEARER_TOKEN

    def test_comments_and_blanks_skipped(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
        secrets = tmp_path / "secrets.env"
        secrets.write_text("# comment\n\nexport GITHUB_TOKEN=ghp_xxx\nMCP_BEARER_TOKEN=found\n")
        assert rv._load_bearer_token(str(secrets)) == "found"


# ---------------------------------------------------------------------------
# Tests: _run_tenant_probes
# ---------------------------------------------------------------------------


class TestRunTenantProbes:
    """Tests for the per-tenant probe suite."""

    def test_four_probes_made_with_correct_tenant_id(self):
        """All four probes are called with the expected tenant_id."""
        responses = [_make_jsonrpc_response() for _ in range(4)]
        call_log = []

        def fake_post(url, json=None, headers=None, timeout=None):
            call_log.append(json)
            return FakeResponse(responses[len(call_log) - 1])

        client = MagicMock()
        client.post = fake_post

        probes = rv._run_tenant_probes(client, "http://test/mcp", "tok", "gw_v17")

        assert len(probes) == 4
        assert all(p["passed"] for p in probes)

        # Verify tool names
        assert probes[0]["tool_name"] == "search_documentation"
        assert probes[1]["tool_name"] == "search_ee2_standards"
        assert probes[2]["tool_name"] == "search_architecture"
        assert probes[3]["tool_name"] == "get_code_context"

        # Verify tenant_id in all calls
        for record in call_log:
            params = record["params"]
            args = params["arguments"]
            assert args.get("tenant_id") == "gw_v17"

    def test_zero_hit_probe_marked_failed(self):
        """A probe returning zero hits is marked as failed."""
        responses = [
            _make_jsonrpc_response(),  # search_documentation passes
            _make_zero_hit_response(),  # search_ee2_standards fails
            _make_jsonrpc_response(),  # search_architecture passes
            _make_jsonrpc_response(),  # get_code_context passes
        ]
        call_idx = [0]

        def fake_post(url, json=None, headers=None, timeout=None):
            resp = FakeResponse(responses[call_idx[0]])
            call_idx[0] += 1
            return resp

        client = MagicMock()
        client.post = fake_post

        probes = rv._run_tenant_probes(client, "http://test/mcp", "tok", "gw")

        assert probes[0]["passed"] is True
        assert probes[1]["passed"] is False
        assert probes[2]["passed"] is True
        assert probes[3]["passed"] is True

    def test_unknown_tenant_returns_error_probe(self):
        """An unknown tenant returns a single error probe record."""
        client = MagicMock()
        probes = rv._run_tenant_probes(client, "http://test/mcp", "tok", "unknown_tenant")

        assert len(probes) == 1
        assert probes[0]["passed"] is False
        assert "__error__" in probes[0]["tool_name"]

    def test_search_documentation_uses_ground_truth_phrase(self):
        """search_documentation uses the per-tenant ground-truth phrase."""
        call_log = []

        def fake_post(url, json=None, headers=None, timeout=None):
            call_log.append(json)
            return FakeResponse(_make_jsonrpc_response())

        client = MagicMock()
        client.post = fake_post

        rv._run_tenant_probes(client, "http://test/mcp", "tok", "gw_sfs")

        # First call should be search_documentation with the SFS phrase
        first_call = call_log[0]
        assert first_call["params"]["name"] == "search_documentation"
        assert first_call["params"]["arguments"]["query"] == "SFS ensemble driver"

    def test_get_code_context_uses_ground_truth_symbol(self):
        """get_code_context uses the per-tenant ground-truth symbol."""
        call_log = []

        def fake_post(url, json=None, headers=None, timeout=None):
            call_log.append(json)
            return FakeResponse(_make_jsonrpc_response())

        client = MagicMock()
        client.post = fake_post

        rv._run_tenant_probes(client, "http://test/mcp", "tok", "gw_gefs_v12")

        # Fourth call should be get_code_context
        fourth_call = call_log[3]
        assert fourth_call["params"]["name"] == "get_code_context"
        assert fourth_call["params"]["arguments"]["symbol"] == "gefs_forecast_v12"


# ---------------------------------------------------------------------------
# Tests: _run_global_probes
# ---------------------------------------------------------------------------


class TestRunGlobalProbes:
    """Tests for the shared-once (global) probe suite."""

    def test_two_probes_without_tenant_id(self):
        """Global probes do not include tenant_id."""
        call_log = []

        def fake_post(url, json=None, headers=None, timeout=None):
            call_log.append(json)
            return FakeResponse(_make_jsonrpc_response())

        client = MagicMock()
        client.post = fake_post

        probes = rv._run_global_probes(client, "http://test/mcp", "tok")

        assert len(probes) == 2
        assert probes[0]["tool_name"] == "search_ee2_standards"
        assert probes[1]["tool_name"] == "search_architecture"

        # No tenant_id in arguments
        for record in call_log:
            args = record["params"]["arguments"]
            assert "tenant_id" not in args

    def test_global_probe_uses_shared_queries(self):
        """Global probes use the SHARED_PROBES constants."""
        call_log = []

        def fake_post(url, json=None, headers=None, timeout=None):
            call_log.append(json)
            return FakeResponse(_make_jsonrpc_response())

        client = MagicMock()
        client.post = fake_post

        rv._run_global_probes(client, "http://test/mcp", "tok")

        assert call_log[0]["params"]["arguments"]["query"] == "err_chk err_exit"
        assert call_log[1]["params"]["arguments"]["query"] == "workflow driver"


# ---------------------------------------------------------------------------
# Tests: _write_result
# ---------------------------------------------------------------------------


class TestWriteResult:
    """Tests for the atomic result writer."""

    def test_writes_to_correct_path(self, tmp_path):
        """File lands at .reingest_state/<ver>/validation/<name>.json."""
        probes = [{"tool_name": "test", "arguments": {}, "response": {},
                   "hit_count": 1, "passed": True}]

        out = rv._write_result("v9-0-0", "gw.json", probes, str(tmp_path))

        expected = tmp_path / ".reingest_state" / "v9-0-0" / "validation" / "gw.json"
        assert out == expected
        assert expected.exists()

    def test_payload_structure(self, tmp_path):
        """Written JSON has the expected top-level keys."""
        probes = [{"tool_name": "t", "arguments": {"a": 1}, "response": {"r": 1},
                   "hit_count": 2, "passed": True}]

        rv._write_result("v9-0-0", "gw_v17.json", probes, str(tmp_path))

        out = tmp_path / ".reingest_state" / "v9-0-0" / "validation" / "gw_v17.json"
        data = json.loads(out.read_text())
        assert data["target_version"] == "v9-0-0"
        assert data["filename"] == "gw_v17.json"
        assert data["all_passed"] is True
        assert len(data["probes"]) == 1
        assert "timestamp" in data

    def test_all_passed_false_when_probe_fails(self, tmp_path):
        """all_passed is False if any probe has passed=False."""
        probes = [
            {"tool_name": "t1", "arguments": {}, "response": {}, "hit_count": 1, "passed": True},
            {"tool_name": "t2", "arguments": {}, "response": {}, "hit_count": 0, "passed": False},
        ]

        rv._write_result("v9-0-0", "gw.json", probes, str(tmp_path))

        out = tmp_path / ".reingest_state" / "v9-0-0" / "validation" / "gw.json"
        data = json.loads(out.read_text())
        assert data["all_passed"] is False

    def test_creates_directories(self, tmp_path):
        """Parent directories are created if missing."""
        probes = [{"tool_name": "t", "arguments": {}, "response": {},
                   "hit_count": 1, "passed": True}]

        subdir = tmp_path / "deep" / "nested"
        rv._write_result("v9-0-0", "x.json", probes, str(subdir))

        assert (subdir / ".reingest_state" / "v9-0-0" / "validation" / "x.json").exists()

    def test_atomic_overwrite(self, tmp_path):
        """A second write overwrites the first cleanly."""
        probes_1 = [{"tool_name": "t", "arguments": {}, "response": {},
                     "hit_count": 1, "passed": True}]
        probes_2 = [{"tool_name": "t2", "arguments": {}, "response": {},
                     "hit_count": 0, "passed": False}]

        rv._write_result("v9-0-0", "gw.json", probes_1, str(tmp_path))
        rv._write_result("v9-0-0", "gw.json", probes_2, str(tmp_path))

        out = tmp_path / ".reingest_state" / "v9-0-0" / "validation" / "gw.json"
        data = json.loads(out.read_text())
        assert data["probes"][0]["tool_name"] == "t2"


# ---------------------------------------------------------------------------
# Tests: main() integration
# ---------------------------------------------------------------------------


class TestMainIntegration:
    """Integration tests for the CLI entry point."""

    def test_unknown_tenant_exits_2(self, tmp_path, monkeypatch):
        """Unknown tenant_id causes exit code 2."""
        monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
        exit_code = rv.main([
            "--target-version", "v9-0-0",
            "--tenant", "nonexistent_tenant",
            "--state-root", str(tmp_path),
        ])
        assert exit_code == 2

    def test_dry_run_tenant_exits_0(self, capsys, monkeypatch):
        """Dry-run for a valid tenant prints plan and exits 0."""
        monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
        exit_code = rv.main([
            "--target-version", "v9-0-0",
            "--tenant", "gw",
            "--dry-run",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "[DRY-RUN]" in captured.out
        assert "search_documentation" in captured.out

    def test_dry_run_global_exits_0(self, capsys, monkeypatch):
        """Dry-run for global mode prints plan and exits 0."""
        monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
        exit_code = rv.main([
            "--target-version", "v9-0-0",
            "--global",
            "--dry-run",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "[DRY-RUN]" in captured.out
        assert "search_ee2_standards" in captured.out

    def test_connection_error_exits_2(self, tmp_path, monkeypatch):
        """A connection error returns exit code 2."""
        monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
        import httpx as _httpx

        def raise_connect_error(*a, **kw):
            raise _httpx.ConnectError("refused")

        with patch("reingest_validation.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post = raise_connect_error
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            exit_code = rv.main([
                "--target-version", "v9-0-0",
                "--tenant", "gw",
                "--state-root", str(tmp_path),
                "--endpoint", "http://localhost:99999/mcp",
            ])

        assert exit_code == 2

    def test_all_pass_exits_0(self, tmp_path, monkeypatch):
        """When all probes return hits, exit code is 0 and file is written."""
        monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)

        def fake_post(url, json=None, headers=None, timeout=None):
            return FakeResponse(_make_jsonrpc_response())

        with patch("reingest_validation.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post = fake_post
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            exit_code = rv.main([
                "--target-version", "v9-0-0",
                "--tenant", "gw",
                "--state-root", str(tmp_path),
                "--endpoint", "http://localhost:18888/mcp",
            ])

        assert exit_code == 0
        result_file = tmp_path / ".reingest_state" / "v9-0-0" / "validation" / "gw.json"
        assert result_file.exists()
        data = json.loads(result_file.read_text())
        assert data["all_passed"] is True

    def test_any_fail_exits_1(self, tmp_path, monkeypatch):
        """When any probe fails, exit code is 1."""
        monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)

        call_idx = [0]
        responses = [
            _make_jsonrpc_response(),
            _make_zero_hit_response(),  # This one fails
            _make_jsonrpc_response(),
            _make_jsonrpc_response(),
        ]

        def fake_post(url, json=None, headers=None, timeout=None):
            resp = FakeResponse(responses[call_idx[0]])
            call_idx[0] += 1
            return resp

        with patch("reingest_validation.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post = fake_post
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            exit_code = rv.main([
                "--target-version", "v9-0-0",
                "--tenant", "gw",
                "--state-root", str(tmp_path),
                "--endpoint", "http://localhost:18888/mcp",
            ])

        assert exit_code == 1
        # File still written (records the failure)
        result_file = tmp_path / ".reingest_state" / "v9-0-0" / "validation" / "gw.json"
        assert result_file.exists()
        data = json.loads(result_file.read_text())
        assert data["all_passed"] is False

    def test_global_mode_all_pass(self, tmp_path, monkeypatch):
        """Global mode writes _shared_once.json on all-pass."""
        monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)

        def fake_post(url, json=None, headers=None, timeout=None):
            return FakeResponse(_make_jsonrpc_response())

        with patch("reingest_validation.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post = fake_post
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            exit_code = rv.main([
                "--target-version", "v9-0-0",
                "--global",
                "--state-root", str(tmp_path),
                "--endpoint", "http://localhost:18888/mcp",
            ])

        assert exit_code == 0
        result_file = tmp_path / ".reingest_state" / "v9-0-0" / "validation" / "_shared_once.json"
        assert result_file.exists()

    def test_mutually_exclusive_tenant_and_global(self):
        """Cannot pass both --tenant and --global."""
        with pytest.raises(SystemExit) as exc_info:
            rv._parse_args(["--target-version", "v9-0-0", "--tenant", "gw", "--global"])
        assert exc_info.value.code != 0
