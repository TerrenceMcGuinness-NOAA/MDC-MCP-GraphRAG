"""Unit tests for ``AwsCredsWriter`` and ``SudoPrivileged`` argv shape.

Validates Requirements 5.6, 5.7, 5.8, 5.9, 7.1, 7.5 (Task 8.1).
"""

from __future__ import annotations

import io

from tests.unit._provision_loader import prov
from tests.unit._provision_fakes import RecordingPrivileged, make_target

AKID = "AKIAIOSFODNN7EXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def _logger():
    return prov.Logger(prov.SecretRedactor(), stream=io.StringIO())


def _creds(access=AKID, secret=SECRET):
    return prov.IamCreds(access, secret, None)


def _writer(files=None):
    ops = RecordingPrivileged(files=files)
    return prov.AwsCredsWriter(ops, _logger()), ops


def _path(t):
    return f"{t.home}/.aws/credentials"


def test_preserves_other_sections_byte_for_byte():
    t = make_target("alice")
    old = (
        "[default]\n"
        "aws_access_key_id = OLDKEY\n"
        "aws_secret_access_key = OLDSEC\n"
        "\n"
        "# a comment line\n"
        "[other]\n"
        "foo = bar\n"
    )
    w, ops = _writer(files={_path(t): old.encode()})
    fc = w.write(t, _creds(), dry_run=False)
    assert fc.disposition == "updated"
    new = ops.files[_path(t)].decode()
    expected = old + (
        "[agentcore-rag]\n"
        f"aws_access_key_id = {AKID}\n"
        f"aws_secret_access_key = {SECRET}\n"
    )
    assert new == expected


def test_existing_agentcore_extras_are_discarded():
    t = make_target("alice")
    old = (
        "[agentcore-rag]\n"
        "aws_access_key_id = OLDKEY\n"
        "aws_secret_access_key = OLDSEC\n"
        "region = us-west-1\n"
        "[keep]\n"
        "x = y\n"
    )
    w, ops = _writer(files={_path(t): old.encode()})
    fc = w.write(t, _creds(), dry_run=False)
    assert fc.disposition == "updated"
    new = ops.files[_path(t)].decode()
    assert "region = us-west-1" not in new
    assert "[keep]\nx = y\n" in new
    assert f"aws_access_key_id = {AKID}\n" in new
    assert f"aws_secret_access_key = {SECRET}\n" in new


def test_satisfied_is_skipped_and_reasserts_mode_owner():
    t = make_target("alice", uid=1001, gid=1002)
    old = (
        "[agentcore-rag]\n"
        f"aws_access_key_id = {AKID}\n"
        f"aws_secret_access_key = {SECRET}\n"
        "[keep]\n"
        "x = y\n"
    )
    w, ops = _writer(files={_path(t): old.encode()})
    fc = w.write(t, _creds(), dry_run=False)
    assert fc.disposition == "skipped"
    assert ops.files[_path(t)].decode() == old  # bytes unchanged
    assert ("reassert", _path(t), 0o600, 1001, 1002) in ops.calls
    assert not any(c[0] == "atomic_write" for c in ops.calls)


def test_absent_file_is_created():
    t = make_target("alice")
    w, ops = _writer(files={})
    fc = w.write(t, _creds(), dry_run=False)
    assert fc.disposition == "created"
    new = ops.files[_path(t)].decode()
    assert new == (
        "[agentcore-rag]\n"
        f"aws_access_key_id = {AKID}\n"
        f"aws_secret_access_key = {SECRET}\n"
    )
    assert any(c[0] == "atomic_write" for c in ops.calls)


def test_dry_run_makes_no_mutation():
    t = make_target("alice")
    w, ops = _writer(files={})
    fc = w.write(t, _creds(), dry_run=True)
    assert fc.disposition == "created"
    assert ops.calls == []
    assert _path(t) not in ops.files


def test_profile_name_is_constant_on_result():
    t = make_target("alice")
    w, _ = _writer(files={})
    fc = w.write(t, _creds(), dry_run=True)
    assert fc.profile == prov.AWS_PROFILE_NAME == "agentcore-rag"


def test_concurrent_modification_detected():
    t = make_target("alice")
    path = _path(t)
    old = b"[default]\nx = y\n"

    class Flaky(RecordingPrivileged):
        def __init__(self):
            super().__init__(files={path: old})
            self._n = 0

        def inspect(self, p):
            # First inspect: original signature. Second inspect (pre-write):
            # a different mtime -> concurrent modification.
            if p == path:
                self._n += 1
                return prov.StatInfo("file", 0, 0, 1, 1, len(old), self._n)
            return super().inspect(p)

    ops = Flaky()
    w = prov.AwsCredsWriter(ops, _logger())
    fc = w.write(t, _creds(), dry_run=False)
    assert fc.disposition == "failed"
    assert "concurrent" in fc.reason


# --- SudoPrivileged argv shapes (Task 8.1: mock subprocess.run) ------------

class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_sudo_atomic_write_argv_shape(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _FakeProc(returncode=0)

    monkeypatch.setattr(prov.subprocess, "run", fake_run)
    sp = prov.SudoPrivileged(python_bin="/usr/bin/python3.12")
    target_file = str(tmp_path / "home" / "alice" / ".aws" / "credentials")
    sp.atomic_write(target_file, b"data", 0o600, 1001, 1002)

    # Two privileged calls: install (stage) then python rename.
    assert len(calls) == 2
    install = calls[0]
    assert install[0:2] == ["sudo", "-n"]
    assert prov.INSTALL_BIN in install
    assert "-m" in install and "0600" in install
    assert "-o" in install and "1001" in install
    assert "-g" in install and "1002" in install
    assert install[-1] == f"{target_file}.tmp.{__import__('os').getpid()}"

    rename = calls[1]
    assert rename[0:2] == ["sudo", "-n"]
    assert rename[2] == "/usr/bin/python3.12"
    assert rename[3] == "-c"
    assert rename[-1] == target_file


def test_sudo_ensure_dir_argv_shape(monkeypatch):
    calls = []
    monkeypatch.setattr(prov.subprocess, "run", lambda argv, **k: calls.append(argv) or _FakeProc(0))
    sp = prov.SudoPrivileged()
    sp.ensure_dir("/home/alice/.aws", 0o700, 1001, 1002)
    argv = calls[0]
    assert argv[0:2] == ["sudo", "-n"]
    assert prov.INSTALL_BIN in argv and "-d" in argv
    assert "0700" in argv and "1001" in argv and "1002" in argv
    assert argv[-1] == "/home/alice/.aws"
