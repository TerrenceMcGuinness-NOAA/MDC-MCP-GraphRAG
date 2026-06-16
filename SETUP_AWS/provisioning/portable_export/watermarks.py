"""Watermark store for idempotent, resumable transfers (Task 3).

A single S3 JSON object at ``<prefix>/watermarks.json`` records the completed
units of a transfer at the R9.1 granularity ``(phase, tenant, collection,
model_profile, part)``. Updates are atomic: read object + ETag, append the
just-completed unit, write back with ``IfMatch=<etag>`` (create-if-absent on
first write). A racing writer's stale ETag yields HTTP 412 which maps to
:class:`ConcurrentOperationError` (reused from :mod:`portable_export.lock`).

Resume semantics (Property 6):

* :meth:`is_complete` returns ``True`` for any unit already recorded, so a
  phase skips finished units and re-executes only incomplete ones.
* :meth:`mark_complete` is idempotent -- recording a unit twice leaves the
  document unchanged, so a fully-complete phase performs no net write.
* :meth:`ensure_manifest_match` refuses a ``--resume`` against a watermark
  written for a different ``manifest_id`` (``Watermark_Mismatch``).

Requirements: 9.1, 9.2, 9.3, 9.4.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from botocore.exceptions import ClientError

from portable_export.lock import ConcurrentOperationError

#: Watermark JSON schema version.
WATERMARK_SCHEMA_VERSION: str = "1.0.0"

#: Stable ordering of the unit key fields (R9.1).
UNIT_FIELDS: tuple[str, ...] = ("phase", "tenant", "collection", "model_profile", "part")


class WatermarkMismatchError(Exception):
    """A ``--resume`` was attempted against a watermark for a different run."""


def unit_key(
    *,
    phase: str,
    tenant: Optional[str] = None,
    collection: Optional[str] = None,
    model_profile: Optional[str] = None,
    part: Optional[int] = None,
) -> dict[str, Any]:
    """Build a normalized completed-unit dict (R9.1 granularity)."""
    return {
        "phase": phase,
        "tenant": tenant,
        "collection": collection,
        "model_profile": model_profile,
        "part": part,
    }


def _canonical(unit: dict[str, Any]) -> tuple:
    """Hashable canonical form of a unit for set membership."""
    return tuple(unit.get(f) for f in UNIT_FIELDS)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_watermark_document(*, manifest_id: str, operation_id: str) -> dict[str, Any]:
    """Return a fresh, empty watermark document."""
    return {
        "schema_version": WATERMARK_SCHEMA_VERSION,
        "manifest_id": manifest_id,
        "operation_id": operation_id,
        "completed_units": [],
        "in_flight_unit": None,
        "updated_at": _utc_now_iso(),
    }


def _err_code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "")


def _http_status(exc: ClientError) -> Any:
    return exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")


class Watermarks:
    """Atomic S3-backed watermark store.

    Parameters
    ----------
    s3_client
        boto3 S3 client (tests inject a ``botocore`` Stubber-wrapped client).
    bucket, key
        Location of ``<prefix>/watermarks.json``.
    manifest_id, operation_id
        Identity of the current run; used to seed a new document and to guard
        resume against a mismatched prior run.
    """

    def __init__(
        self,
        s3_client: Any,
        bucket: str,
        key: str,
        *,
        manifest_id: str,
        operation_id: str,
    ) -> None:
        self._s3 = s3_client
        self._bucket = bucket
        self._key = key
        self._manifest_id = manifest_id
        self._operation_id = operation_id
        self._doc: dict[str, Any] = new_watermark_document(
            manifest_id=manifest_id, operation_id=operation_id
        )
        self._etag: Optional[str] = None
        self._completed: set[tuple] = set()

    @property
    def document(self) -> dict[str, Any]:
        return dict(self._doc)

    def load(self) -> dict[str, Any]:
        """Read the watermark object from S3 (or seed a fresh one).

        Populates the in-memory completed-unit set. Returns the document.
        """
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=self._key)
        except ClientError as exc:
            if _err_code(exc) in ("NoSuchKey", "404", "NotFound") or _http_status(exc) == 404:
                self._doc = new_watermark_document(
                    manifest_id=self._manifest_id, operation_id=self._operation_id
                )
                self._etag = None
                self._completed = set()
                return dict(self._doc)
            raise
        self._doc = json.loads(resp["Body"].read())
        self._etag = resp.get("ETag", "").strip('"')
        self._completed = {_canonical(u) for u in self._doc.get("completed_units", [])}
        return dict(self._doc)

    def ensure_manifest_match(self) -> None:
        """Refuse resume when the loaded watermark targets a different run.

        Raises
        ------
        WatermarkMismatchError
            If the loaded document's ``manifest_id`` differs from this run's.
        """
        existing = self._doc.get("manifest_id")
        if existing and existing != self._manifest_id:
            raise WatermarkMismatchError(
                f"watermark manifest_id {existing!r} != current "
                f"{self._manifest_id!r}; refusing --resume"
            )

    def is_complete(self, unit: dict[str, Any]) -> bool:
        """Return ``True`` when ``unit`` has already been recorded (R9.2)."""
        return _canonical(unit) in self._completed

    def mark_complete(self, unit: dict[str, Any]) -> dict[str, Any]:
        """Append ``unit`` and atomically swap the S3 object (R9.1).

        Idempotent: if the unit is already recorded the in-memory set and the
        object are left unchanged (no net write), so re-running a complete
        phase performs no writes (R9.3).
        """
        canon = _canonical(unit)
        if canon in self._completed:
            return dict(self._doc)
        self._completed.add(canon)
        self._doc["completed_units"].append({f: unit.get(f) for f in UNIT_FIELDS})
        self._doc["in_flight_unit"] = None
        self._doc["updated_at"] = _utc_now_iso()
        self._doc["manifest_id"] = self._manifest_id
        self._doc["operation_id"] = self._operation_id
        self._write()
        return dict(self._doc)

    def set_in_flight(self, unit: Optional[dict[str, Any]]) -> None:
        """Record the in-flight unit and atomically swap the object."""
        self._doc["in_flight_unit"] = (
            {f: unit.get(f) for f in UNIT_FIELDS} if unit else None
        )
        self._doc["updated_at"] = _utc_now_iso()
        self._write()

    def _write(self) -> None:
        body = json.dumps(self._doc, ensure_ascii=True, sort_keys=True).encode("utf-8")
        kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": self._key,
            "Body": body,
            "ContentType": "application/json",
        }
        if self._etag is None:
            kwargs["IfNoneMatch"] = "*"
        else:
            kwargs["IfMatch"] = self._etag
        try:
            resp = self._s3.put_object(**kwargs)
        except ClientError as exc:
            if _err_code(exc) in ("PreconditionFailed", "412") or _http_status(exc) == 412:
                raise ConcurrentOperationError(
                    "watermark write rejected: ETag precondition failed "
                    "(concurrent operation in progress)",
                    operation_id=self._doc.get("operation_id"),
                ) from exc
            raise
        self._etag = resp.get("ETag", "").strip('"')


__all__ = [
    "Watermarks",
    "WatermarkMismatchError",
    "unit_key",
    "new_watermark_document",
    "UNIT_FIELDS",
    "WATERMARK_SCHEMA_VERSION",
]
