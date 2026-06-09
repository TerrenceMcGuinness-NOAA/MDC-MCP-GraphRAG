"""Property-based tests for provision-agentcore-creds.py (Requirement 17, Task 15).

The five universally-quantified properties:

* P1 Idempotency (R17.1) -- two identical runs produce byte-equal files.
* P2 Preservation (R17.2) -- non-managed mcp.json content is structurally
  unchanged.
* P3 No-leak (R17.3) -- the loaded keys never appear in stdout/stderr/logs.
  (Scoped to diagnostic output per R12; the credentials file is the secret's
  intended destination and is therefore excluded -- see the module note in the
  implementation report.)
* P4 Cross-file profile-name match (R17.4).
* P5 Single-user isolation (R17.5).

Filesystem-touching properties use a real sandbox via ``LocalPrivileged`` (the
host lacks pyfakefs); ``/home/<name>`` is remapped under a per-example
temporary directory.
"""

from __future__ import annotations

import io
import json
import os
import string
import tempfile
from collections import namedtuple
from unittest import mock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.unit._provision_loader import prov
from tests.unit._provision_fakes import LocalPrivileged, RecordingPrivileged

PW = namedtuple("PW", "pw_name pw_uid pw_gid pw_dir pw_shell")
PROXY = "/p/proxy.py"
ARN = prov.DEFAULT_RUNTIME_ARN
AKID = "AKIAIOSFODNN7EXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

_NAME_CHARS = string.ascii_letters + string.digits
names_strategy = st.lists(
    st.text(alphabet=_NAME_CHARS, min_size=1, max_size=12).filter(
        lambda s: s not in ("ec2-user", "root")
    ),
    min_size=1,
    max_size=6,
    unique=True,
)


def _pw_ec2():
    return PW("ec2-user", 1000, 1000, "/home/ec2-user", "/bin/bash")


def _world(tmp, names):
    sandbox = os.path.join(tmp, "sandbox")
    for n in names:
        os.makedirs(os.path.join(sandbox, "home", n), exist_ok=True)
    src = os.path.join(tmp, "creds")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write(f"[default]\naws_access_key_id = {AKID}\naws_secret_access_key = {SECRET}\n")
    proxy = os.path.join(tmp, "proxy.py")
    with open(proxy, "w", encoding="utf-8") as fh:
        fh.write("# proxy\n")
    entries = [PW(n, os.getuid(), os.getgid(), f"/home/{n}", "/bin/bash") for n in names]
    return sandbox, src, proxy, entries


def _main(argv, sandbox, src, proxy, entries, getpwnam_map=None):
    out, err = io.StringIO(), io.StringIO()
    rc = prov.main(
        argv + ["--proxy-path", proxy],
        ops=LocalPrivileged(sandbox),
        stdout=out,
        stderr=err,
        environ={},
        geteuid=lambda: 1000,
        getpwuid=lambda u: _pw_ec2(),
        getpwall=lambda: entries,
        getpwnam=(lambda n: getpwnam_map[n]) if getpwnam_map else None,
        source_path=src,
    )
    return rc, out.getvalue(), err.getvalue()


def _cred(sandbox, n):
    return os.path.join(sandbox, "home", n, ".aws", "credentials")


def _mcp(sandbox, n):
    return os.path.join(sandbox, "home", n, ".kiro", "settings", "mcp.json")


# --- P1 Idempotency (R17.1) ------------------------------------------------

@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(names=names_strategy)
def test_property_idempotency(names):
    with tempfile.TemporaryDirectory() as tmp:
        sandbox, src, proxy, entries = _world(tmp, names)
        assert _main(["--all"], sandbox, src, proxy, entries)[0] == 0
        snap1 = {
            n: (open(_cred(sandbox, n), "rb").read(), open(_mcp(sandbox, n), "rb").read())
            for n in names
        }
        rc2, out2, _ = _main(["--all"], sandbox, src, proxy, entries)
        assert rc2 == 0
        snap2 = {
            n: (open(_cred(sandbox, n), "rb").read(), open(_mcp(sandbox, n), "rb").read())
            for n in names
        }
        assert snap1 == snap2
        assert f"skipped={len(names)}" in out2


# --- P2 Preservation (R17.2) -----------------------------------------------

_json_scalar = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-1000, max_value=1000)
    | st.text(alphabet=string.printable, max_size=10)
)
_json_value = st.recursive(
    _json_scalar,
    lambda children: st.lists(children, max_size=3)
    | st.dictionaries(st.text(alphabet=_NAME_CHARS, min_size=1, max_size=6), children, max_size=3),
    max_leaves=8,
)

_MANAGED_ENTRY_KEYS = {"command", "args", "env"}


def _cfg():
    return prov.Config(
        runtime_arn=ARN, region="us-east-1", proxy_path=PROXY,
        runtime_arn_source="default", region_source="default", proxy_path_source="default",
        mode="bulk", target_user=None, exclusions=frozenset(),
        verify=False, verbose=False, dry_run=False, output_format="table",
    )


@settings(max_examples=60, deadline=None)
@given(
    top_extra=st.dictionaries(
        st.text(alphabet=_NAME_CHARS, min_size=1, max_size=6).filter(lambda k: k != "mcpServers"),
        _json_value, max_size=3,
    ),
    other_servers=st.dictionaries(
        st.text(alphabet=_NAME_CHARS, min_size=1, max_size=8).filter(lambda k: k != "agentcore-mcp-rag"),
        _json_value, max_size=3,
    ),
    entry_extra=st.dictionaries(
        st.text(alphabet=_NAME_CHARS, min_size=1, max_size=6).filter(lambda k: k not in _MANAGED_ENTRY_KEYS),
        _json_value, max_size=3,
    ),
    env_extra=st.dictionaries(
        st.text(alphabet=_NAME_CHARS, min_size=1, max_size=6).filter(lambda k: k not in ("AWS_REGION", "AWS_PROFILE")),
        st.text(max_size=10), max_size=3,
    ),
)
def test_property_preservation(top_extra, other_servers, entry_extra, env_extra):
    entry = dict(entry_extra)
    entry["env"] = dict(env_extra)
    servers = dict(other_servers)
    servers["agentcore-mcp-rag"] = entry
    old_obj = dict(top_extra)
    old_obj["mcpServers"] = servers
    old_text = json.dumps(old_obj, indent=2) + "\n"

    path = "/home/alice/.kiro/settings/mcp.json"
    ops = RecordingPrivileged(files={path: old_text.encode()})
    target = prov.TargetUser("alice", os.getuid(), os.getgid(), "/home/alice", "/bin/bash")
    fc = prov.McpConfigWriter(ops, prov.Logger(prov.SecretRedactor(), stream=io.StringIO())).write(
        target, _cfg(), dry_run=False
    )
    assert fc.disposition in ("created", "updated", "skipped")
    new_obj = json.loads(ops.files[path].decode())

    # Top-level non-managed keys preserved.
    for k, v in top_extra.items():
        assert new_obj[k] == v
    # Other servers preserved.
    for k, v in other_servers.items():
        assert new_obj["mcpServers"][k] == v
    # Non-managed entry members preserved.
    new_entry = new_obj["mcpServers"]["agentcore-mcp-rag"]
    for k, v in entry_extra.items():
        assert new_entry[k] == v
    # Non-managed env vars preserved.
    for k, v in env_extra.items():
        assert new_entry["env"][k] == v


# --- P3 No-leak (R17.3, scoped to stdout/stderr per R12) -------------------

_secret_alphabet = string.ascii_letters + string.digits + '"\\\n\t/+=:; '

# A value that is itself a substring of a redaction marker would be
# "reintroduced" by the marker word "redacted" after scrubbing (e.g. a 1-char
# secret "r"). Such degenerate values are not real keys; exclude them. Real
# 16-128 char access ids and secrets never collide with the markers.
_MARKERS = ("<aws_access_key_id redacted>", "<aws_secret_access_key redacted>")


def _not_marker_substring(v: str) -> bool:
    return all(v not in m for m in _MARKERS)


@settings(max_examples=80, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    access=st.text(alphabet=string.ascii_letters + string.digits, min_size=16, max_size=128).filter(
        _not_marker_substring
    ),
    secret=st.text(alphabet=_secret_alphabet, min_size=1, max_size=256).filter(_not_marker_substring),
)
def test_property_no_leak(access, secret):
    def fake_load(redactor, logger, *, path=None, section="default"):
        redactor.register(access, "aws_access_key_id")
        redactor.register(secret, "aws_secret_access_key")
        return prov.IamCreds(access, secret, None)

    with tempfile.TemporaryDirectory() as tmp:
        sandbox, src, proxy, entries = _world(tmp, ["alice", "bob"])
        with mock.patch.object(prov.CredentialsLoader, "load", staticmethod(fake_load)):
            rc, out, err = _main(["--all", "--verbose"], sandbox, src, proxy, entries)
    assert rc == 0
    # The raw key/secret bytes must not appear in diagnostic output.
    assert access not in out and access not in err
    assert secret not in out and secret not in err


# --- P4 Cross-file profile-name match (R17.4) ------------------------------

@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(names=names_strategy)
def test_property_cross_file_profile_match(names):
    with tempfile.TemporaryDirectory() as tmp:
        sandbox, src, proxy, entries = _world(tmp, names)
        assert _main(["--all"], sandbox, src, proxy, entries)[0] == 0
        for n in names:
            creds_text = open(_cred(sandbox, n), "r", encoding="utf-8").read()
            headers = [
                line.strip()[1:-1]
                for line in creds_text.splitlines()
                if line.strip().startswith("[") and line.strip().endswith("]")
            ]
            mcp_obj = json.loads(open(_mcp(sandbox, n), "r", encoding="utf-8").read())
            aws_profile = mcp_obj["mcpServers"]["agentcore-mcp-rag"]["env"]["AWS_PROFILE"]
            assert aws_profile.strip() in headers
            assert aws_profile == "agentcore-rag"


# --- P5 Single-user isolation (R17.5) --------------------------------------

@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(names=names_strategy.filter(lambda ns: len(ns) >= 2))
def test_property_single_user_isolation(names):
    with tempfile.TemporaryDirectory() as tmp:
        sandbox, src, proxy, entries = _world(tmp, names)
        pmap = {e.pw_name: e for e in entries}
        target = names[0]
        others = names[1:]

        def snapshot():
            snap = {}
            for n in others:
                home = os.path.join(sandbox, "home", n)
                snap[n] = (
                    os.stat(home).st_mtime_ns,
                    sorted(os.listdir(home)),
                )
            return snap

        before = snapshot()
        rc, out, err = _main(["--user", target], sandbox, src, proxy, entries, getpwnam_map=pmap)
        assert rc == 0
        after = snapshot()
        assert before == after  # no sibling home dir mutated
        for n in others:
            assert os.listdir(os.path.join(sandbox, "home", n)) == []  # still empty
        # the target WAS provisioned
        assert os.path.isfile(_cred(sandbox, target))
