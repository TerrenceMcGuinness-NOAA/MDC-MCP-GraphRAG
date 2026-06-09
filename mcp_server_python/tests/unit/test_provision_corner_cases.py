"""Fixed corner-case corpus for provision-agentcore-creds.py (R17.6, Task 16).

Required fixed inputs: empty credentials file, malformed JSON mcp.json,
max-length OS user name, a secret with JSON-significant characters, an absent
credentials file, an absent mcp.json, and an mcp.json already in target state.
"""

from __future__ import annotations

import io
import json
import os
from collections import namedtuple

from tests.unit._provision_loader import prov
from tests.unit._provision_fakes import LocalPrivileged, RecordingPrivileged, make_target

PW = namedtuple("PW", "pw_name pw_uid pw_gid pw_dir pw_shell")
PROXY = "/p/proxy.py"
ARN = prov.DEFAULT_RUNTIME_ARN
AKID = "AKIAIOSFODNN7EXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def _logger():
    return prov.Logger(prov.SecretRedactor(), stream=io.StringIO())


def _cfg():
    return prov.Config(
        runtime_arn=ARN, region="us-east-1", proxy_path=PROXY,
        runtime_arn_source="default", region_source="default", proxy_path_source="default",
        mode="bulk", target_user=None, exclusions=frozenset(),
        verify=False, verbose=False, dry_run=False, output_format="table",
    )


def _creds(access=AKID, secret=SECRET):
    return prov.IamCreds(access, secret, None)


def _cpath(t):
    return f"{t.home}/.aws/credentials"


def _mpath(t):
    return f"{t.home}/.kiro/settings/mcp.json"


# 1. Empty credentials file -------------------------------------------------

def test_empty_credentials_file_is_updated():
    t = make_target("alice")
    ops = RecordingPrivileged(files={_cpath(t): b""})
    fc = prov.AwsCredsWriter(ops, _logger()).write(t, _creds(), dry_run=False)
    assert fc.disposition == "updated"
    assert ops.files[_cpath(t)].decode() == (
        "[agentcore-rag]\n"
        f"aws_access_key_id = {AKID}\n"
        f"aws_secret_access_key = {SECRET}\n"
    )


# 2. Malformed JSON mcp.json ------------------------------------------------

def test_malformed_json_mcp_is_failed_and_unchanged():
    t = make_target("alice")
    bad = b'{"mcpServers": {  oops'
    ops = RecordingPrivileged(files={_mpath(t): bad})
    fc = prov.McpConfigWriter(ops, _logger()).write(t, _cfg(), dry_run=False)
    assert fc.disposition == "failed"
    assert ops.files[_mpath(t)] == bad


# 3. Max-length OS user name (32) ------------------------------------------

def test_max_length_user_name(tmp_path):
    name = "a" * 32
    sandbox = tmp_path / "sandbox"
    (sandbox / "home" / name).mkdir(parents=True)
    src = tmp_path / "creds"
    src.write_text(f"[default]\naws_access_key_id = {AKID}\naws_secret_access_key = {SECRET}\n")
    proxy = tmp_path / "proxy.py"
    proxy.write_text("# proxy\n")
    entry = PW(name, os.getuid(), os.getgid(), f"/home/{name}", "/bin/bash")
    out, err = io.StringIO(), io.StringIO()
    rc = prov.main(
        ["--user", name, "--proxy-path", str(proxy)],
        ops=LocalPrivileged(str(sandbox)), stdout=out, stderr=err, environ={},
        geteuid=lambda: 1000, getpwuid=lambda u: PW("ec2-user", 1000, 1000, "/home/ec2-user", "/bin/bash"),
        getpwnam=lambda n: entry, source_path=str(src),
    )
    assert rc == 0
    assert (sandbox / "home" / name / ".aws" / "credentials").is_file()


# 4. Secret with JSON-significant characters -------------------------------

def test_secret_with_json_significant_chars_written_verbatim_in_creds():
    t = make_target("alice")
    nasty = 'aa"bb\\cc\ndd\tee'
    ops = RecordingPrivileged(files={})
    fc = prov.AwsCredsWriter(ops, _logger()).write(t, _creds(secret=nasty), dry_run=False)
    assert fc.disposition == "created"
    written = ops.files[_cpath(t)].decode()
    assert f"aws_secret_access_key = {nasty}\n" in written


def test_secret_with_json_significant_chars_is_redacted_in_logs():
    nasty = 'aa"bb\\cc\ndd\tee'
    r = prov.SecretRedactor()
    r.register(nasty, "aws_secret_access_key")
    assert nasty not in r.scrub(f"diagnostic referencing {nasty} value")


# 5. Absent credentials file ------------------------------------------------

def test_absent_credentials_file_is_created():
    t = make_target("alice")
    ops = RecordingPrivileged(files={})
    fc = prov.AwsCredsWriter(ops, _logger()).write(t, _creds(), dry_run=False)
    assert fc.disposition == "created"
    assert _cpath(t) in ops.files


# 6. Absent mcp.json --------------------------------------------------------

def test_absent_mcp_file_is_created():
    t = make_target("alice")
    ops = RecordingPrivileged(files={})
    fc = prov.McpConfigWriter(ops, _logger()).write(t, _cfg(), dry_run=False)
    assert fc.disposition == "created"
    obj = json.loads(ops.files[_mpath(t)].decode())
    assert obj["mcpServers"]["agentcore-mcp-rag"]["env"]["AWS_PROFILE"] == "agentcore-rag"


# 7. mcp.json already in target state --------------------------------------

def test_mcp_already_target_state_is_skipped():
    t = make_target("alice")
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
    ops = RecordingPrivileged(files={_mpath(t): text.encode()})
    fc = prov.McpConfigWriter(ops, _logger()).write(t, _cfg(), dry_run=False)
    assert fc.disposition == "skipped"
    assert ops.files[_mpath(t)].decode() == text
