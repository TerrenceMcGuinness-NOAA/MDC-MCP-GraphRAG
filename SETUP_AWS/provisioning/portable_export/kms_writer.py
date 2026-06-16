"""SSE-KMS S3 writer with streaming SHA-256 (Task 4).

Every Portable_Export object is written with server-side encryption. When a
KMS key ARN is configured the object is written ``SSE-KMS``; otherwise the
account/bucket default encryption is relied upon. A defensive guard
(:func:`assert_bucket_encrypted`) refuses to write to a bucket that has no
default encryption configured, so a misconfigured target cannot silently
stage plaintext.

The per-object SHA-256 is computed during the write (streaming over the body
chunks) and returned so the caller records it in the Export_Manifest
(R13.2). Restore later re-reads each object and re-computes the digest to
verify it against the manifest before consuming the object (R13.3, R13.4) --
see :func:`compute_sha256` / :func:`verify_sha256`.

Requirements: 13.1, 13.2.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Optional

from botocore.exceptions import ClientError


class BucketEncryptionError(Exception):
    """The target bucket has no default encryption configured."""


class ChecksumMismatch(Exception):
    """A re-read object's SHA-256 does not match the manifest (R13.4)."""


def compute_sha256(data: bytes | Iterable[bytes]) -> str:
    """Return the hex SHA-256 of ``data`` (bytes or an iterable of chunks)."""
    h = hashlib.sha256()
    if isinstance(data, (bytes, bytearray)):
        h.update(data)
    else:
        for chunk in data:
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(data: bytes, expected_hex: str) -> None:
    """Raise :class:`ChecksumMismatch` if ``data`` does not hash to expected."""
    actual = compute_sha256(data)
    if actual != expected_hex:
        raise ChecksumMismatch(
            f"object SHA-256 mismatch: expected {expected_hex}, got {actual}"
        )


def bucket_default_encryption(s3_client: Any, bucket: str) -> Optional[str]:
    """Return the bucket's default SSE algorithm, or ``None`` if unconfigured.

    Returns ``"aws:kms"``, ``"AES256"``, or ``None``.
    """
    try:
        resp = s3_client.get_bucket_encryption(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in (
            "ServerSideEncryptionConfigurationNotFoundError",
            "NoSuchBucket",
        ):
            return None
        raise
    rules = resp.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
    for rule in rules:
        algo = (
            rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
        )
        if algo:
            return algo
    return None


def assert_bucket_encrypted(s3_client: Any, bucket: str) -> str:
    """Guard: raise unless ``bucket`` has default encryption configured.

    Returns the configured SSE algorithm on success.

    Raises
    ------
    BucketEncryptionError
        If the bucket has no default encryption.
    """
    algo = bucket_default_encryption(s3_client, bucket)
    if algo is None:
        raise BucketEncryptionError(
            f"bucket {bucket!r} has no default encryption configured; "
            f"refusing to stage a Portable_Export in plaintext"
        )
    return algo


class KmsWriter:
    """Writes Portable_Export objects SSE-KMS and tracks per-object SHA-256.

    Parameters
    ----------
    s3_client
        boto3 S3 client (tests inject a ``botocore`` Stubber-wrapped client).
    bucket
        Target bucket.
    kms_key_arn
        KMS key for SSE-KMS. When ``None``, objects are written relying on the
        bucket default encryption (still guarded by
        :func:`assert_bucket_encrypted` when ``guard_encryption`` is set).
    guard_encryption
        When ``True`` (default) the bucket's default encryption is verified
        once on first write.
    """

    def __init__(
        self,
        s3_client: Any,
        bucket: str,
        *,
        kms_key_arn: Optional[str] = None,
        guard_encryption: bool = True,
    ) -> None:
        self._s3 = s3_client
        self._bucket = bucket
        self._kms_key_arn = kms_key_arn
        self._guard = guard_encryption
        self._guard_checked = False

    @property
    def bucket(self) -> str:
        return self._bucket

    def _ensure_guard(self) -> None:
        if self._guard and not self._guard_checked:
            assert_bucket_encrypted(self._s3, self._bucket)
            self._guard_checked = True

    def put(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Write ``body`` to ``key`` SSE-KMS and return its SHA-256 hex.

        The digest is computed during the write so the caller records it in
        the Export_Manifest (R13.2).
        """
        self._ensure_guard()
        digest = compute_sha256(body)
        kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": body,
            "ContentType": content_type,
        }
        if self._kms_key_arn:
            kwargs["ServerSideEncryption"] = "aws:kms"
            kwargs["SSEKMSKeyId"] = self._kms_key_arn
        self._s3.put_object(**kwargs)
        return digest


__all__ = [
    "KmsWriter",
    "BucketEncryptionError",
    "ChecksumMismatch",
    "compute_sha256",
    "verify_sha256",
    "bucket_default_encryption",
    "assert_bucket_encrypted",
]
