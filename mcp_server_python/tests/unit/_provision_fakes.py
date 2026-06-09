"""Shared privileged-ops test doubles for the provisioning tool.

* :class:`LocalPrivileged` -- a real-filesystem implementation that remaps
  ``/home/...`` paths into a sandbox directory, so full provisioning runs can
  be exercised without ``sudo`` or another user's home. Used by writer and
  property tests.
* :class:`RecordingPrivileged` -- an in-memory fake that returns canned
  ``inspect`` results and records mutation calls. Used by directory/writer unit
  tests that assert behavior without touching the disk.
"""

from __future__ import annotations

import os
import stat
import tempfile

from tests.unit._provision_loader import prov


class LocalPrivileged(prov.Privileged):
    """Privileged ops against a real sandbox; ``/home`` is remapped under it."""

    def __init__(self, sandbox: str) -> None:
        self.sandbox = sandbox
        self.run_as_results: dict = {}

    def _map(self, path: str) -> str:
        if path.startswith("/home/"):
            return os.path.join(self.sandbox, path.lstrip("/"))
        return path

    def inspect(self, path: str):
        p = self._map(path)
        try:
            ls = os.lstat(p)
        except FileNotFoundError:
            return prov.StatInfo("absent", -1, -1, -1, -1, -1, -1)
        if stat.S_ISLNK(ls.st_mode):
            kind = "symlink"
        elif stat.S_ISDIR(ls.st_mode):
            kind = "dir"
        elif stat.S_ISREG(ls.st_mode):
            kind = "file"
        else:
            kind = "other"
        try:
            s = os.stat(p)
            return prov.StatInfo(kind, s.st_uid, s.st_gid, s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        except OSError:
            return prov.StatInfo(kind, -1, -1, -1, -1, -1, -1)

    def read_bytes(self, path: str):
        p = self._map(path)
        try:
            with open(p, "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            return None

    def ensure_dir(self, path: str, mode: int, uid: int, gid: int) -> None:
        p = self._map(path)
        os.makedirs(p, exist_ok=True)
        os.chmod(p, mode)
        try:
            os.chown(p, uid, gid)
        except (PermissionError, OSError):
            pass

    def reassert(self, path: str, mode: int, uid: int, gid: int) -> None:
        p = self._map(path)
        os.chmod(p, mode)
        try:
            os.chown(p, uid, gid)
        except (PermissionError, OSError):
            pass

    def atomic_write(self, path: str, data: bytes, mode: int, uid: int, gid: int) -> None:
        p = self._map(path)
        d = os.path.dirname(p)
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d)
        try:
            os.write(fd, data)
            os.close(fd)
            os.chmod(tmp, mode)
            try:
                os.chown(tmp, uid, gid)
            except (PermissionError, OSError):
                pass
            os.rename(tmp, p)
            dfd = os.open(d, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def run_as(self, user: str, argv: list, env: dict, timeout: int):
        return self.run_as_results.get(user, prov.RunResult(0, False, "{}", ""))


class RecordingPrivileged(prov.Privileged):
    """In-memory fake: canned ``inspect`` results, recorded mutations."""

    def __init__(self, inspects: dict | None = None, files: dict | None = None) -> None:
        self.inspects = dict(inspects or {})
        self.files: dict = dict(files or {})
        self.calls: list = []
        self.run_as_results: dict = {}

    def inspect(self, path: str):
        if path in self.inspects:
            return self.inspects[path]
        if path in self.files:
            return prov.StatInfo("file", 0, 0, 1, 1, len(self.files[path]), 0)
        return prov.StatInfo("absent", -1, -1, -1, -1, -1, -1)

    def read_bytes(self, path: str):
        return self.files.get(path)

    def ensure_dir(self, path: str, mode: int, uid: int, gid: int) -> None:
        self.calls.append(("ensure_dir", path, mode, uid, gid))

    def reassert(self, path: str, mode: int, uid: int, gid: int) -> None:
        self.calls.append(("reassert", path, mode, uid, gid))

    def atomic_write(self, path: str, data: bytes, mode: int, uid: int, gid: int) -> None:
        self.calls.append(("atomic_write", path, mode, uid, gid))
        self.files[path] = data

    def run_as(self, user: str, argv: list, env: dict, timeout: int):
        return self.run_as_results.get(user, prov.RunResult(0, False, "{}", ""))


def make_target(name="alice", uid=1001, gid=1002, home=None, shell="/bin/bash"):
    return prov.TargetUser(name, uid, gid, home or f"/home/{name}", shell)
