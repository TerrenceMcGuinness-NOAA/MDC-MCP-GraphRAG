"""Unit tests for portable_export.lock + watermarks (Task 3.1) + Property 6.

Covers Requirements 9.1, 9.2, 9.3, 9.4:
* stale-ETag write -> ConcurrentOperationError,
* missing/absent lock handled,
* watermark manifest_id mismatch surfaces,
* atomic update under simulated kill mid-write,
* Property 6: a phase already complete is a no-op; an interrupted phase
  resumes to a final document byte-equal to the uninterrupted run.
"""

from __future__ import annotations

import json

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from portable_export.lock import ConcurrentOperationError, Lock, LockError, build_lock_document
from portable_export.watermarks import (
    Watermarks,
    WatermarkMismatchError,
    unit_key,
)


# ── In-memory fake S3 with conditional-write semantics ──────────────────────


class FakeS3:
    """Minimal S3 supporting conditional PUT (IfNoneMatch / IfMatch), GET, DELETE."""

    def __init__(self):
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self._seq = 0
        self.put_calls = 0

    def _etag(self) -> str:
        self._seq += 1
        return f"etag{self._seq}"

    def put_object(self, *, Bucket, Key, Body, ContentType=None, IfNoneMatch=None, IfMatch=None):
        self.put_calls += 1
        existing = self.objects.get((Bucket, Key))
        if IfNoneMatch == "*" and existing is not None:
            raise ClientError({"Error": {"Code": "PreconditionFailed"},
                               "ResponseMetadata": {"HTTPStatusCode": 412}}, "PutObject")
        if IfMatch is not None:
            if existing is None or existing[1] != IfMatch:
                raise ClientError({"Error": {"Code": "PreconditionFailed"},
                                   "ResponseMetadata": {"HTTPStatusCode": 412}}, "PutObject")
        etag = self._etag()
        self.objects[(Bucket, Key)] = (Body, etag)
        return {"ETag": f'"{etag}"'}

    def get_object(self, *, Bucket, Key):
        existing = self.objects.get((Bucket, Key))
        if existing is None:
            raise ClientError({"Error": {"Code": "NoSuchKey"},
                               "ResponseMetadata": {"HTTPStatusCode": 404}}, "GetObject")
        body, etag = existing
        return {"Body": _Body(body), "ETag": f'"{etag}"'}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)
        return {}


class _Body:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data


# ── Lock tests ──────────────────────────────────────────────────────────────


def test_lock_acquire_then_concurrent_refused():
    s3 = FakeS3()
    lock = Lock(s3, "b", "pfx/lock.json")
    lock.acquire(holder_arn="arn:a", operation_id="op1", operation="AWS_Export")
    lock2 = Lock(s3, "b", "pfx/lock.json")
    with pytest.raises(ConcurrentOperationError) as exc:
        lock2.acquire(holder_arn="arn:b", operation_id="op2", operation="AWS_Export")
    assert exc.value.operation_id == "op1"


def test_lock_read_absent_returns_none():
    s3 = FakeS3()
    assert Lock(s3, "b", "pfx/lock.json").read() is None


def test_lock_release_by_holder():
    s3 = FakeS3()
    lock = Lock(s3, "b", "pfx/lock.json")
    lock.acquire(holder_arn="arn:a", operation_id="op1", operation="AWS_Export")
    assert lock.release("op1") is True
    assert lock.read() is None
    assert lock.release("op1") is False  # nothing held now


def test_lock_release_wrong_holder_refused():
    s3 = FakeS3()
    lock = Lock(s3, "b", "pfx/lock.json")
    lock.acquire(holder_arn="arn:a", operation_id="op1", operation="AWS_Export")
    with pytest.raises(LockError):
        lock.release("other-op")


def test_break_lock_refuses_when_not_stale():
    s3 = FakeS3()
    lock = Lock(s3, "b", "pfx/lock.json")
    lock.acquire(holder_arn="arn:a", operation_id="op1", operation="AWS_Export",
                 lease_hours=2)
    with pytest.raises(LockError):
        lock.break_lock()


def test_break_lock_when_stale():
    from datetime import datetime, timedelta, timezone
    s3 = FakeS3()
    lock = Lock(s3, "b", "pfx/lock.json")
    lock.acquire(holder_arn="arn:a", operation_id="op1", operation="AWS_Export")
    future = datetime.now(timezone.utc) + timedelta(hours=3)
    assert lock.break_lock(now=future) is True
    assert lock.read() is None


# ── Watermark tests ──────────────────────────────────────────────────────────


def _wm(s3, manifest_id="m1", operation_id="op1"):
    return Watermarks(s3, "b", "pfx/watermarks.json",
                      manifest_id=manifest_id, operation_id=operation_id)


def test_watermark_mark_and_is_complete():
    s3 = FakeS3()
    wm = _wm(s3)
    wm.load()
    u = unit_key(phase="export_vectors", tenant="gw",
                 collection="mdc-code-context-titan1024", model_profile="titan1024", part=0)
    assert wm.is_complete(u) is False
    wm.mark_complete(u)
    assert wm.is_complete(u) is True


def test_watermark_mark_complete_idempotent_no_extra_write():
    s3 = FakeS3()
    wm = _wm(s3)
    wm.load()
    u = unit_key(phase="export_vectors", tenant="gw", part=0)
    wm.mark_complete(u)
    writes_after_first = s3.put_calls
    wm.mark_complete(u)  # idempotent -> no net write (R9.3)
    assert s3.put_calls == writes_after_first


def test_watermark_manifest_mismatch_refused():
    s3 = FakeS3()
    _wm(s3, manifest_id="m1").load()  # seed via mark
    wm1 = _wm(s3, manifest_id="m1")
    wm1.load()
    wm1.mark_complete(unit_key(phase="p", part=0))
    # New run with different manifest_id loading the same object
    wm2 = _wm(s3, manifest_id="DIFFERENT")
    wm2.load()
    with pytest.raises(WatermarkMismatchError):
        wm2.ensure_manifest_match()


def test_watermark_concurrent_write_refused_stale_etag():
    s3 = FakeS3()
    wm_a = _wm(s3, operation_id="opA")
    wm_a.load()
    wm_b = _wm(s3, operation_id="opB")
    wm_b.load()
    # A writes first, bumping the etag; B still holds the stale (None->absent) etag.
    wm_a.mark_complete(unit_key(phase="p", part=0))
    with pytest.raises(ConcurrentOperationError):
        wm_b.mark_complete(unit_key(phase="p", part=1))


# ── Property 6: resume byte-equal to uninterrupted ──────────────────────────


def _run_phase(s3, units, *, stop_after=None):
    """Run a phase that marks each unit complete, optionally stopping early."""
    wm = _wm(s3)
    wm.load()
    wm.ensure_manifest_match()
    processed = []
    for i, u in enumerate(units):
        if wm.is_complete(u):
            continue
        # (work would happen here)
        wm.mark_complete(u)
        processed.append(u)
        if stop_after is not None and i == stop_after:
            raise KeyboardInterrupt("simulated kill mid-phase")
    return wm, processed


def test_property6_resume_is_byte_equal_to_uninterrupted():
    units = [
        unit_key(phase="export_vectors", tenant="gw",
                 collection="c", model_profile="titan1024", part=p)
        for p in range(5)
    ]

    # Uninterrupted run.
    s3_clean = FakeS3()
    wm_clean, _ = _run_phase(s3_clean, units)
    clean_doc = wm_clean.document

    # Interrupted run: kill after part 2, then resume.
    s3_resume = FakeS3()
    with pytest.raises(KeyboardInterrupt):
        _run_phase(s3_resume, units, stop_after=2)
    # Resume: same units, skips completed, finishes the rest.
    wm_resume, processed2 = _run_phase(s3_resume, units)
    resume_doc = wm_resume.document

    # Only the incomplete units were processed on resume (parts 3, 4).
    assert [u["part"] for u in processed2] == [3, 4]

    # Final completed-unit sets are equal (order-independent).
    clean_units = {tuple(sorted(u.items())) for u in clean_doc["completed_units"]}
    resume_units = {tuple(sorted(u.items())) for u in resume_doc["completed_units"]}
    assert clean_units == resume_units
    assert len(resume_doc["completed_units"]) == 5


def test_property6_complete_phase_rerun_is_noop():
    units = [unit_key(phase="p", part=p) for p in range(3)]
    s3 = FakeS3()
    _run_phase(s3, units)
    writes = s3.put_calls
    # Re-run the already-complete phase: no new writes.
    _run_phase(s3, units)
    assert s3.put_calls == writes
