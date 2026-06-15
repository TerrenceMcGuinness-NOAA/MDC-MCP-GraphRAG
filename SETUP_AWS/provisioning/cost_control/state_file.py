"""Authoritative State_File with S3 optimistic locking (Task 5).

The State_File is a single S3-versioned JSON object that records the
platform's sleep/wake state, the last transition metadata, a monotonic
operation counter, and the per-tier snapshot/manifest data. Concurrency is
enforced with S3 conditional writes: a reader captures the object's ETag and
writes back with ``IfMatch=<etag>``; a racing writer whose ETag is stale gets
an HTTP 412 ``PreconditionFailed`` which maps to
:class:`ConcurrentOperationError` (Property 7 / R7.3, R7.4, R8.4).

Requirements: 8.1, 8.2, 8.3, 8.4.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from botocore.exceptions import ClientError

#: State_File JSON schema version.
SCHEMA_VERSION: str = "1.0.0"

#: The seven defined platform states (design state machine).
VALID_STATES: frozenset[str] = frozenset(
    {
        "Active_Mode",
        "Sleep_State",
        "Sleeping",
        "Waking",
        "Wake_State",
        "Active_Mode_Degraded",
        "Sleep_State_Degraded",
    }
)

#: Required top-level fields (R8.2).
REQUIRED_FIELDS: tuple[str, ...] = (
    "schema_version",
    "environment_name",
    "current_state",
    "previous_state",
    "last_transition_at",
    "last_caller_arn",
    "operation_counter",
    "latest_snapshots",
    "manifest",
)


class StateFileError(Exception):
    """Base class for State_File errors."""


class MissingStateError(StateFileError):
    """The State_File object does not exist in the bucket."""


class CorruptStateError(StateFileError):
    """The State_File object is unparseable or schema-invalid."""


class ConcurrentOperationError(StateFileError):
    """A conditional write failed because the ETag was stale (HTTP 412).

    Carries the conflicting state and prior caller ARN when known so the
    caller can emit a ``Concurrent_Operation_Refused`` audit record.
    """

    def __init__(
        self,
        message: str,
        *,
        conflicting_state: Optional[str] = None,
        last_caller_arn: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.conflicting_state = conflicting_state
        self.last_caller_arn = last_caller_arn


def new_initial_document(environment_name: str) -> dict[str, Any]:
    """Return a fresh ``Active_Mode`` State_File document (counter 0)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "environment_name": environment_name,
        "current_state": "Active_Mode",
        "previous_state": "Active_Mode",
        "last_transition_at": None,
        "last_caller_arn": None,
        "operation_counter": 0,
        "latest_snapshots": {},
        "manifest": {},
    }


def validate_document(doc: Any) -> dict[str, Any]:
    """Validate a parsed State_File document against the schema.

    Raises
    ------
    CorruptStateError
        If ``doc`` is not a dict, is missing a required field, has an unknown
        ``current_state``, or has a non-integer ``operation_counter``.
    """
    if not isinstance(doc, dict):
        raise CorruptStateError(
            f"State_File root must be a JSON object, got {type(doc).__name__}"
        )
    missing = [f for f in REQUIRED_FIELDS if f not in doc]
    if missing:
        raise CorruptStateError(
            f"State_File missing required field(s): {', '.join(missing)}"
        )
    if doc["current_state"] not in VALID_STATES:
        raise CorruptStateError(
            f"State_File current_state {doc['current_state']!r} is not a "
            f"defined state"
        )
    if not isinstance(doc["operation_counter"], int) or isinstance(
        doc["operation_counter"], bool
    ):
        raise CorruptStateError(
            "State_File operation_counter must be an integer"
        )
    return doc


def bump(doc: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with ``operation_counter`` incremented by 1.

    Per R8.3 the counter advances by exactly 1 on every write.
    """
    out = dict(doc)
    out["operation_counter"] = int(doc["operation_counter"]) + 1
    return out


class StateFile:
    """Read/write wrapper around the S3 State_File object.

    Parameters
    ----------
    s3_client
        A boto3 S3 client (tests inject a ``botocore`` Stubber-wrapped client).
    bucket, key
        Location of the State_File object.
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

    def read(self) -> tuple[dict[str, Any], str]:
        """Read and validate the State_File, returning ``(document, etag)``.

        Raises
        ------
        MissingStateError
            If the object does not exist (``NoSuchKey`` / 404).
        CorruptStateError
            If the body is not valid JSON or fails schema validation.
        """
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=self._key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            status = exc.response.get("ResponseMetadata", {}).get(
                "HTTPStatusCode"
            )
            if code in ("NoSuchKey", "404", "NotFound") or status == 404:
                raise MissingStateError(
                    f"State_File not found at s3://{self._bucket}/{self._key}"
                ) from exc
            raise
        raw = resp["Body"].read()
        etag = resp.get("ETag", "").strip('"')
        try:
            doc = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise CorruptStateError(
                f"State_File at s3://{self._bucket}/{self._key} is not valid "
                f"JSON: {exc}"
            ) from exc
        return validate_document(doc), etag

    def write(self, doc: dict[str, Any], etag: Optional[str]) -> str:
        """Write ``doc`` back conditionally, returning the new ETag.

        ``etag`` is the value captured by :meth:`read`; the write uses
        ``IfMatch=<etag>`` so a concurrent writer cannot clobber it. Passing
        ``etag=None`` performs a create-if-absent write (``IfNoneMatch="*"``).

        Raises
        ------
        ConcurrentOperationError
            On HTTP 412 ``PreconditionFailed`` (stale ETag / object already
            created by a racing writer).
        CorruptStateError
            If ``doc`` fails schema validation before the write.
        """
        validate_document(doc)
        body = json.dumps(doc, ensure_ascii=True, sort_keys=True).encode("utf-8")
        kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": self._key,
            "Body": body,
            "ContentType": "application/json",
        }
        if etag is None:
            kwargs["IfNoneMatch"] = "*"
        else:
            kwargs["IfMatch"] = etag
        try:
            resp = self._s3.put_object(**kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            status = exc.response.get("ResponseMetadata", {}).get(
                "HTTPStatusCode"
            )
            if code in ("PreconditionFailed", "412") or status == 412:
                raise ConcurrentOperationError(
                    "State_File write rejected: ETag precondition failed "
                    "(concurrent operation in progress)",
                    conflicting_state=doc.get("current_state"),
                    last_caller_arn=doc.get("last_caller_arn"),
                ) from exc
            raise
        return resp.get("ETag", "").strip('"')
