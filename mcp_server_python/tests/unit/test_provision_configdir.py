"""Unit tests for ``AwsConfigDir`` (Requirements 4, 6.1)."""

from __future__ import annotations

import io
import os
import stat
import tempfile

from tests.unit._provision_loader import prov
from tests.unit._provision_fakes import LocalPrivileged, RecordingPrivileged, make_target


def _logger():
    return prov.Logger(prov.SecretRedactor(), stream=io.StringIO())


def test_check_home_absent():
    ops = RecordingPrivileged()  # everything absent
    cd = prov.AwsConfigDir(ops, _logger())
    reason = cd.check_home(make_target("alice"))
    assert reason and "does not exist" in reason


def test_check_home_not_a_directory():
    t = make_target("alice")
    ops = RecordingPrivileged(inspects={t.home: prov.StatInfo("file", t.uid, t.gid, 1, 1, 0, 0)})
    cd = prov.AwsConfigDir(ops, _logger())
    reason = cd.check_home(t)
    assert reason and "not a directory" in reason


def test_check_home_wrong_owner():
    t = make_target("alice", uid=1001)
    ops = RecordingPrivileged(inspects={t.home: prov.StatInfo("dir", 9999, 9999, 1, 1, 0, 0)})
    cd = prov.AwsConfigDir(ops, _logger())
    reason = cd.check_home(t)
    assert reason and "owned by uid 9999" in reason


def test_check_home_ok():
    t = make_target("alice", uid=1001)
    ops = RecordingPrivileged(inspects={t.home: prov.StatInfo("dir", 1001, 1002, 1, 1, 0, 0)})
    cd = prov.AwsConfigDir(ops, _logger())
    assert cd.check_home(t) is None


def test_ensure_rejects_symlink():
    t = make_target("alice")
    path = f"{t.home}/.aws"
    ops = RecordingPrivileged(inspects={path: prov.StatInfo("symlink", t.uid, t.gid, 1, 1, 0, 0)})
    cd = prov.AwsConfigDir(ops, _logger())
    reason = cd.ensure(t, path, dry_run=False)
    assert reason and "symlink" in reason
    assert not any(c[0] == "ensure_dir" for c in ops.calls)


def test_ensure_creates_with_recording_fake():
    t = make_target("alice")
    path = f"{t.home}/.aws"
    ops = RecordingPrivileged()  # absent -> will be created
    cd = prov.AwsConfigDir(ops, _logger())
    assert cd.ensure(t, path, dry_run=False) is None
    assert ("ensure_dir", path, 0o700, t.uid, t.gid) in ops.calls


def test_ensure_dry_run_makes_no_call():
    t = make_target("alice")
    path = f"{t.home}/.aws"
    ops = RecordingPrivileged()
    cd = prov.AwsConfigDir(ops, _logger())
    assert cd.ensure(t, path, dry_run=True) is None
    assert ops.calls == []


def test_ensure_creates_real_directory_mode_0700():
    with tempfile.TemporaryDirectory() as sandbox:
        t = make_target("alice", uid=os.getuid(), gid=os.getgid())
        os.makedirs(os.path.join(sandbox, "home", "alice"))
        ops = LocalPrivileged(sandbox)
        cd = prov.AwsConfigDir(ops, _logger())
        assert cd.check_home(t) is None
        path = f"{t.home}/.aws"
        assert cd.ensure(t, path, dry_run=False) is None
        real = os.path.join(sandbox, "home", "alice", ".aws")
        assert os.path.isdir(real)
        assert stat.S_IMODE(os.stat(real).st_mode) == 0o700
