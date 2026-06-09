"""Unit tests for ``McpConfigWriter`` (Requirements 6, 7; Task 9.1)."""

from __future__ import annotations

import io
import json

from tests.unit._provision_loader import prov
from tests.unit._provision_fakes import RecordingPrivileged, make_target

PROXY = "/mdc-mcp-rag/eib-mcp-rag-server/tools/agentcore-kiro-proxy.py"
ARN = prov.DEFAULT_RUNTIME_ARN


def _logger():
    return prov.Logger(prov.SecretRedactor(), stream=io.StringIO())


def _cfg(region="us-east-1", proxy=PROXY, arn=ARN):
    return prov.Config(
        runtime_arn=arn,
        region=region,
        proxy_path=proxy,
        runtime_arn_source="default",
        region_source="default",
        proxy_path_source="default",
        mode="bulk",
        target_user=None,
        exclusions=frozenset(),
        verify=False,
        verbose=False,
        dry_run=False,
        output_format="table",
    )


def _path(t):
    return f"{t.home}/.kiro/settings/mcp.json"


def _writer(files=None):
    ops = RecordingPrivileged(files=files)
    return prov.McpConfigWriter(ops, _logger()), ops


def test_creates_file_with_managed_keys_and_correct_types():
    t = make_target("alice")
    w, ops = _writer(files={})
    fc = w.write(t, _cfg(), dry_run=False)
    assert fc.disposition == "created"
    obj = json.loads(ops.files[_path(t)].decode())
    entry = obj["mcpServers"]["agentcore-mcp-rag"]
    assert entry["command"] == "python3.12"
    assert entry["args"] == [PROXY, "--runtime-id", ARN]
    assert isinstance(entry["args"], list) and len(entry["args"]) == 3
    assert all(isinstance(x, str) for x in entry["args"])
    assert entry["env"]["AWS_REGION"] == "us-east-1"
    assert entry["env"]["AWS_PROFILE"] == "agentcore-rag"


def test_preserves_other_servers_and_top_level_keys_and_order():
    t = make_target("alice")
    old = {
        "powers": {"x": 1},
        "mcpServers": {
            "other-server": {"command": "node", "args": ["a.js"]},
            "agentcore-mcp-rag": {
                "type": "command",
                "command": "python3",
                "args": ["old"],
                "disabled": False,
                "autoApprove": ["get_server_info"],
                "disabledTools": ["foo"],
                "env": {"CUSTOM": "keep", "AWS_REGION": "us-west-2"},
            },
        },
        "trailing": [1, 2, 3],
    }
    old_text = json.dumps(old, indent=2) + "\n"
    w, ops = _writer(files={_path(t): old_text.encode()})
    fc = w.write(t, _cfg(), dry_run=False)
    assert fc.disposition == "updated"
    obj = json.loads(ops.files[_path(t)].decode())

    # Top-level key order preserved.
    assert list(obj.keys()) == ["powers", "mcpServers", "trailing"]
    assert obj["powers"] == {"x": 1}
    assert obj["trailing"] == [1, 2, 3]

    # Non-managed server preserved.
    assert obj["mcpServers"]["other-server"] == {"command": "node", "args": ["a.js"]}

    entry = obj["mcpServers"]["agentcore-mcp-rag"]
    # Non-managed members preserved by value and position.
    assert entry["type"] == "command"
    assert entry["disabled"] is False
    assert entry["autoApprove"] == ["get_server_info"]
    assert entry["disabledTools"] == ["foo"]
    assert entry["env"]["CUSTOM"] == "keep"
    # Managed keys applied.
    assert entry["command"] == "python3.12"
    assert entry["args"] == [PROXY, "--runtime-id", ARN]
    assert entry["env"]["AWS_REGION"] == "us-east-1"
    assert entry["env"]["AWS_PROFILE"] == "agentcore-rag"
    # command keeps its original position (it pre-existed).
    assert list(entry.keys())[:3] == ["type", "command", "args"]
    # Newly-added AWS_PROFILE appended after the pre-existing env keys.
    assert list(entry["env"].keys()) == ["CUSTOM", "AWS_REGION", "AWS_PROFILE"]


def test_invalid_json_is_failed_and_file_unchanged():
    t = make_target("alice")
    bad = b"{not valid json"
    w, ops = _writer(files={_path(t): bad})
    fc = w.write(t, _cfg(), dry_run=False)
    assert fc.disposition == "failed"
    assert ops.files[_path(t)] == bad  # unchanged
    assert not any(c[0] == "atomic_write" for c in ops.calls)


def test_already_target_state_is_skipped_and_reasserts():
    t = make_target("alice", uid=1001, gid=1002)
    obj = {
        "mcpServers": {
            "agentcore-mcp-rag": {
                "command": "python3.12",
                "args": [PROXY, "--runtime-id", ARN],
                "env": {"AWS_REGION": "us-east-1", "AWS_PROFILE": "agentcore-rag"},
            }
        }
    }
    text = json.dumps(obj, indent=2) + "\n"
    w, ops = _writer(files={_path(t): text.encode()})
    fc = w.write(t, _cfg(), dry_run=False)
    assert fc.disposition == "skipped"
    assert ops.files[_path(t)].decode() == text
    assert ("reassert", _path(t), 0o600, 1001, 1002) in ops.calls


def test_serialization_two_space_indent_and_trailing_newline():
    t = make_target("alice")
    w, ops = _writer(files={})
    w.write(t, _cfg(), dry_run=False)
    raw = ops.files[_path(t)].decode()
    assert raw.endswith("\n")
    assert '\n  "mcpServers"' in raw  # two-space indent at top level
