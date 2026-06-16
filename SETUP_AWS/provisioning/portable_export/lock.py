"""S3 If-Match optimistic lock for the Portable_Export pipeline (Task 3).

A single S3 JSON object at ``<prefix>/lock.json`` serializes operations on one
Portable_Export prefix. Concurrency is enforced with S3 conditional writes:
the acquirer creates the object with ``IfNoneMatch="*"`` (create-if-absent);
a racing writer gets an HTTP 412 ``PreconditionFailed`` which maps to
:class:`ConcurrentOperationError`. Release deletes the object (guarded by the
captured ETag via ``IfMatch`` is not supported by ``delete_object``, so the
holder's ``operation_id`` is verified before delete). A stale lock past its
``expected_release_by`` is cleanable with :meth:`break_lock`.

Requirements: 9.1, 9.2 (the watermark partner lives in ``watermarks.py``);
design error-handling contract ``Concurrent_Operation_Refused``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from botocore.exceptions import ClientError

#: Lock JSON schema version.
LOCK_SCHEMA_VERSION: str = "1.0.0"

#: Default lock lifetime used to compute ``expected_release_by``.
DEFAULT_LEASE_HOURS: int = 2


class LockError(Exception):
    """Base class for lock errors."""


class ConcurrentOperationError(LockError):
    """A lock is already held by another operation (HTTP 412 on create)."""

    def __init__(
        self,
        message: str,
        *,
        holder_arn: Optional[str] = None,
        operation_id: Optional[str] = None,
        expected_release_by: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.holder_arn = holder_arn
        self.operation_id = operation_id
        self.expected_release_by = expected_release_by


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def build_lock_document(
    *,
    holder_arn: str,
    operation_id: str,
    operation: str,
    acquired_at: Optional[str] = None,
    lease_hours: int = DEFAULT_LEASE_HOURS,
) -> dict[str, Any]:
    """Build a lock document with a computed ``expected_release_by``."""
    now = _utc_now()
    acq = acquired_at or _iso(now)
    release_by = _iso(_parse_iso(acq) + timedelta(hours=lease_hours))
    return {
        "schema_version": LOCK_SCHEMA_VERSION,
        "holder_arn": holder_arn,
        "operation_id": operation_id,
        "operation": operation,
        "acquired_at": acq,
        "expected_release_by": release_by,
    }


def _err_code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "")


def _http_status(exc: ClientError) -> Any:
    return exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")


class Lock:
    """Read/acquire/release/break wrapper around the S3 ``lock.json`` object.

    Parameters
    ----------
    s3_client
        A boto3 S3 client (tests inject a ``botocore`` Stubber-wrapped client).
    bucket, key
        Location of the lock object (``key`` is ``<prefix>/lock.json``).
    """

    def __init__(self, s3_client: Any, bucket: str, key: str) -> None:
        self._s3 = s3_client
        self._bucket = bucket
        self._key = key

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def key(self) -> str:
        return self._key

    def read(self) -> Optional[tuple[dict[str, Any], str]]:
        """Return ``(document, etag)`` or ``None`` when no lock is held."""
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=self._key)
        except ClientError as exc:
            if _err_code(exc) in ("NoSuchKey", "404", "NotFound") or _http_status(exc) == 404:
                return None
            raise
        raw = resp["Body"].read()
        etag = resp.get("ETag", "").strip('"')
        return json.loads(raw), etag

    def acquire(
        self,
        *,
        holder_arn: str,
        operation_id: str,
        operation: str,
        lease_hours: int = DEFAULT_LEASE_HOURS,
    ) -> dict[str, Any]:
        """Acquire the lock via create-if-absent conditional PUT.

        Raises
        ------
        ConcurrentOperationError
            If a lock already exists (HTTP 412 ``PreconditionFailed``).
        """
        doc = build_lock_document(
            holder_arn=holder_arn,
            operation_id=operation_id,
            operation=operation,
            lease_hours=lease_hours,
        )
        body = json.dumps(doc, ensure_ascii=True, sort_keys=True).encode("utf-8")
        try:
            self._s3.put_object(
                Bucket=self._bucket,
                Key=self._key,
                Body=body,
                ContentType="application/json",
                IfNoneMatch="*",
            )
        except ClientError as exc:
            if _err_code(exc) in ("PreconditionFailed", "412") or _http_status(exc) == 412:
                existing = self.read()
                ex_doc = existing[0] if existing else {}
                raise ConcurrentOperationError(
                    "Portable_Export lock already held "
                    f"(operation_id={ex_doc.get('operation_id')!r})",
                    holder_arn=ex_doc.get("holder_arn"),
                    operation_id=ex_doc.get("operation_id"),
                    expected_release_by=ex_doc.get("expected_release_by"),
                ) from exc
            raise
        return doc

    def release(self, operation_id: str) -> bool:
        """Release the lock if held by ``operation_id``.

        Returns ``True`` when a matching lock was deleted, ``False`` when no
        lock was held. Raises :class:`LockError` if a lock is held by a
        different operation (refuse to delete another holder's lock).
        """
        existing = self.read()
        if existing is None:
            return False
        doc, _etag = existing
        if doc.get("operation_id") != operation_id:
            raise LockError(
                f"refusing to release lock held by a different operation "
                f"({doc.get('operation_id')!r} != {operation_id!r})"
            )
        self._s3.delete_object(Bucket=self._bucket, Key=self._key)
        return True

    def break_lock(self, *, now: Optional[datetime] = None) -> bool:
        """Forcibly delete a stale lock past its ``expected_release_by``.

        Returns ``True`` when a stale lock was broken, ``False`` when no lock
        was held. Raises :class:`LockError` when the lock is still within its
        lease (not yet stale).
        """
        existing = self.read()
        if existing is None:
            return False
        doc, _etag = existing
        now = now or _utc_now()
        release_by = doc.get("expected_release_by")
        if release_by and _parse_iso(release_by) > now:
            raise LockError(
                f"lock is not stale yet (expected_release_by={release_by}); "
                f"refusing to break"
            )
        self._s3.delete_object(Bucket=self._bucket, Key=self._key)
        return True


__all__ = [
    "Lock",
    "LockError",
    "ConcurrentOperationError",
    "build_lock_document",
    "LOCK_SCHEMA_VERSION",
    "DEFAULT_LEASE_HOURS",
]
