"""Unit tests for ``main()`` orchestration and ``RunSummary`` (Task 14.1).

Validates Requirements 9.2, 10.1, 10.6, 10.7, 11.4, 11.5.
"""

from __future__ import annotations

import io
import json
import os
import stat
from collections import namedtuple

import pytest

from tests.unit._provision_loader import prov
from tests.unit._provision_fakes import LocalPrivileged

PW = namedtuple("PW", "pw_name pw_uid pw_gid pw_dir pw_shell")
AKID = "AKIAIOSFODNN7EXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def _pw_ec2():
    return PW("ec2-user", 1000, 1000, "/home/ec2-user", "/bin/bash")


def _setup(tmp_path, names, make_homes=None):
    """Build a sandbox, source creds, proxy file, and passwd entries."""
    make_homes = names if make_homes is None else make_homes
    sandbox = tmp_path / "sandbox"
    for n in make_homes:
        (sandbox / "home" / n).mkdir(parents=True, exist_ok=True)
    src = tmp_path / "src_creds"
    src.write_text(f"[default]\naws_access_key_id = {AKID}\naws_secret_access_key = {SECRET}\n")
    proxy = tmp_path / "proxy.py"
    proxy.write_text("# proxy\n")
    entries = [PW(n, os.getuid(), os.getgid(), f"/home/{n}", "/bin/bash") for n in names]
    return sandbox, src, proxy, entries


def _run(argv, sandbox, src, proxy, entries, *, getpwnam_map=None):
    out, err = io.StringIO(), io.StringIO()
    ops = LocalPrivileged(str(sandbox))
    rc = prov.main(
        argv + ["--proxy-path", str(proxy)],
        ops=ops,
        stdout=out,
        stderr=err,
        environ={},
        geteuid=lambda: 1000,
        getpwuid=lambda u: _pw_ec2(),
        getpwall=lambda: entries,
        getpwnam=(lambda n: getpwnam_map[n]) if getpwnam_map else None,
        source_path=str(src),
    )
    return rc, out.getvalue(), err.getvalue(), ops


def _cred_path(sandbox, name):
    return sandbox / "home" / name / ".aws" / "credentials"


def _mcp_path(sandbox, name):
    return sandbox / "home" / name / ".kiro" / "settings" / "mcp.json"


# --- bulk ------------------------------------------------------------------

def test_bulk_all_creates_each_user_once(tmp_path):
    sandbox, src, proxy, entries = _setup(tmp_path, ["alice", "bob"])
    rc, out, err, ops = _run(["--all"], sandbox, src, proxy, entries)
    assert rc == 0
    assert "alice" in out and "bob" in out
    assert out.count("created") >= 2
    for n in ("alice", "bob"):
        assert _cred_path(sandbox, n).is_file()
        assert _mcp_path(sandbox, n).is_file()
        assert stat.S_IMODE(os.stat(_cred_path(sandbox, n)).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(_mcp_path(sandbox, n)).st_mode) == 0o600


def test_bulk_is_idempotent_second_run_all_skipped(tmp_path):
    sandbox, src, proxy, entries = _setup(tmp_path, ["alice", "bob"])
    _run(["--all"], sandbox, src, proxy, entries)
    before = {n: (_cred_path(sandbox, n).read_bytes(), _mcp_path(sandbox, n).read_bytes()) for n in ("alice", "bob")}
    rc, out, err, ops = _run(["--all"], sandbox, src, proxy, entries)
    assert rc == 0
    assert "aggregate: created=0 updated=0 skipped=2 failed=0" in out
    after = {n: (_cred_path(sandbox, n).read_bytes(), _mcp_path(sandbox, n).read_bytes()) for n in ("alice", "bob")}
    assert before == after  # byte-equal across runs


def test_bulk_continues_past_failed_user_and_exits_6(tmp_path):
    # carol has no home dir in the sandbox -> failed; alice still provisioned.
    sandbox, src, proxy, entries = _setup(tmp_path, ["alice", "carol"], make_homes=["alice"])
    rc, out, err, ops = _run(["--all"], sandbox, src, proxy, entries)
    assert rc == prov.EXIT_FAILED
    assert "failed" in out
    assert _cred_path(sandbox, "alice").is_file()  # alice still done
    assert not _cred_path(sandbox, "carol").exists()


def test_empty_eligible_set_exits_0(tmp_path):
    sandbox, src, proxy, _ = _setup(tmp_path, [])
    rc, out, err, ops = _run(["--all"], sandbox, src, proxy, [])
    assert rc == 0
    assert "aggregate: created=0 updated=0 skipped=0 failed=0" in out


# --- single ----------------------------------------------------------------

def test_single_user_provisions_only_named(tmp_path):
    sandbox, src, proxy, entries = _setup(tmp_path, ["alice", "bob"])
    pmap = {e.pw_name: e for e in entries}
    rc, out, err, ops = _run(["--user", "alice"], sandbox, src, proxy, entries, getpwnam_map=pmap)
    assert rc == 0
    assert _cred_path(sandbox, "alice").is_file()
    assert not _cred_path(sandbox, "bob").exists()  # bob untouched


def test_single_user_ineligible_validated_before_side_effect(tmp_path):
    sandbox, src, proxy, _ = _setup(tmp_path, ["svc"])
    bad = PW("svc", 500, 500, "/home/svc", "/bin/bash")  # uid < 1000
    rc, out, err, ops = _run(["--user", "svc"], sandbox, src, proxy, [], getpwnam_map={"svc": bad})
    assert rc == prov.EXIT_ARG
    assert not _cred_path(sandbox, "svc").exists()


# --- dry-run ---------------------------------------------------------------

def test_dry_run_makes_no_filesystem_changes(tmp_path):
    sandbox, src, proxy, entries = _setup(tmp_path, ["alice", "bob"])
    rc, out, err, ops = _run(["--all", "--dry-run"], sandbox, src, proxy, entries)
    assert rc == 0
    assert out.count("created") >= 2  # dispositions planned
    for n in ("alice", "bob"):
        assert not _cred_path(sandbox, n).exists()
        assert not _mcp_path(sandbox, n).exists()


def test_dry_run_json_format(tmp_path):
    sandbox, src, proxy, entries = _setup(tmp_path, ["alice"])
    rc, out, err, ops = _run(["--all", "--dry-run", "--format", "json"], sandbox, src, proxy, entries)
    assert rc == 0
    obj = json.loads(out)
    assert obj["version"] == 1
    assert obj["users"][0]["name"] == "alice"
    assert set(obj["aggregate"]) == {"created", "updated", "skipped", "failed"}
    assert "exit_code" in obj


# --- argument / identity exit codes ---------------------------------------

def test_all_and_user_conflict_exits_2(tmp_path):
    sandbox, src, proxy, entries = _setup(tmp_path, ["alice"])
    rc, out, err, ops = _run(["--all", "--user", "alice"], sandbox, src, proxy, entries)
    assert rc == prov.EXIT_ARG


def test_missing_source_creds_exits_4(tmp_path):
    sandbox, src, proxy, entries = _setup(tmp_path, ["alice"])
    out, err = io.StringIO(), io.StringIO()
    rc = prov.main(
        ["--all", "--proxy-path", str(proxy)],
        ops=LocalPrivileged(str(sandbox)),
        stdout=out, stderr=err, environ={},
        geteuid=lambda: 1000, getpwuid=lambda u: _pw_ec2(),
        getpwall=lambda: entries, source_path="/no/such/creds",
    )
    assert rc == prov.EXIT_CREDS


# --- RunSummary ------------------------------------------------------------

def test_run_summary_truncates_reason_to_200():
    long = "x" * 250
    rs = prov.RunSummary([prov.RunRecord("alice", "failed", long)], "json")
    obj = json.loads(rs.render())
    reason = obj["users"][0]["reason"]
    assert len(reason) == 200 and reason.endswith("...")


def test_run_summary_aggregate_and_exit_code():
    recs = [
        prov.RunRecord("a", "created"),
        prov.RunRecord("b", "updated"),
        prov.RunRecord("c", "skipped"),
        prov.RunRecord("d", "failed", "boom"),
    ]
    rs = prov.RunSummary(recs, "table")
    assert rs.aggregate() == {"created": 1, "updated": 1, "skipped": 1, "failed": 1}
    assert rs.exit_code() == prov.EXIT_FAILED
    table = rs.render()
    assert "aggregate: created=1 updated=1 skipped=1 failed=1" in table
    assert "exit: 6" in table


def test_run_summary_all_non_failed_exit_0():
    rs = prov.RunSummary([prov.RunRecord("a", "created"), prov.RunRecord("b", "skipped")], "table")
    assert rs.exit_code() == prov.EXIT_OK
