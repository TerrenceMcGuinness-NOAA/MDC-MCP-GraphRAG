"""Export_vectors phase (Task 9).

Per (tenant, collection): scroll the source index, accumulate records into
gzipped JSONL parts, write each part SSE-KMS with a streaming SHA-256, and
record the completed unit in the watermark. The embedding is carried bitwise
(R5.1, R5.2, R5.3) -- this phase never recomputes a vector.

A tenant/collection with zero data yields a zero-count VectorExportEntry and
no error (R7.5).

Requirements: 1.1, 1.3, 1.5, 5.1, 5.2, 5.3, 7.5, 13.1, 13.2.
"""

from __future__ import annotations

from typing import Iterable, Optional

from portable_export.config import infer_model_profile
from portable_export.kms_writer import KmsWriter, compute_sha256
from portable_export.manifest import ExportManifest, VectorExportEntry
from portable_export.serialization import jsonl_gz_encode
from portable_export.watermarks import Watermarks, unit_key

PHASE = "export_vectors"

#: Default records-per-part. Approximates the design's <=64 MB compressed
#: target while keeping watermark units small and SHA-256 verification fast.
DEFAULT_PART_MAX_RECORDS: int = 1000


def _part_key(prefix: str, tenant: str, collection: str, idx: int) -> str:
    return f"{prefix.rstrip('/')}/vectors/{tenant}/{collection}/{idx:03d}.jsonl.gz"


def export_collection(
    reader,
    kms_writer: KmsWriter,
    watermarks: Optional[Watermarks],
    *,
    prefix: str,
    tenant: str,
    collection: str,
    model_profile: Optional[str] = None,
    batch: int = 500,
    part_max_records: int = DEFAULT_PART_MAX_RECORDS,
) -> VectorExportEntry:
    """Export one (tenant, collection) to gzipped JSONL parts.

    Returns a populated :class:`VectorExportEntry` for the manifest.
    """
    mp = model_profile or infer_model_profile(collection) or "unknown"
    entry = VectorExportEntry(
        tenant_id=tenant, collection_name=collection, model_profile=mp
    )

    buffer: list[dict] = []
    part_idx = 0

    def flush() -> None:
        nonlocal buffer, part_idx
        if not buffer:
            return
        unit = unit_key(phase=PHASE, tenant=tenant, collection=collection,
                        model_profile=mp, part=part_idx)
        key = _part_key(prefix, tenant, collection, part_idx)
        body = jsonl_gz_encode(buffer)
        if watermarks is not None and watermarks.is_complete(unit):
            # Already written on a prior run -- skip the S3 write (R9.2, R9.3)
            # but recompute the deterministic SHA (gzip mtime=0) so the resumed
            # manifest is byte-equal to an uninterrupted run.
            entry.parts.append(key)
            entry.record_count += len(buffer)
            entry.sha256_per_part.append(compute_sha256(body))
            buffer = []
            part_idx += 1
            return
        sha = kms_writer.put(key, body, content_type="application/gzip")
        entry.parts.append(key)
        entry.sha256_per_part.append(sha)
        entry.record_count += len(buffer)
        if watermarks is not None:
            watermarks.mark_complete(unit)
        buffer = []
        part_idx += 1

    for record_batch in reader.scroll_records(collection, batch):
        for rec in record_batch:
            buffer.append(rec)
            if len(buffer) >= part_max_records:
                flush()
    flush()  # final partial part (and the zero-data no-op)
    return entry


def export_vectors(
    reader,
    kms_writer: KmsWriter,
    watermarks: Optional[Watermarks],
    manifest: ExportManifest,
    *,
    prefix: str,
    units: Iterable[tuple[str, str, Optional[str]]],
    batch: int = 500,
    part_max_records: int = DEFAULT_PART_MAX_RECORDS,
) -> list[VectorExportEntry]:
    """Export every (tenant, collection, model_profile) unit.

    ``units`` is an iterable of ``(tenant_id, collection, model_profile|None)``.
    Each resulting :class:`VectorExportEntry` is appended to ``manifest``.
    """
    entries: list[VectorExportEntry] = []
    for tenant, collection, mp in units:
        entry = export_collection(
            reader, kms_writer, watermarks,
            prefix=prefix, tenant=tenant, collection=collection,
            model_profile=mp, batch=batch, part_max_records=part_max_records,
        )
        manifest.add_vector_export(entry)
        entries.append(entry)
    return entries


__all__ = ["export_vectors", "export_collection", "PHASE", "DEFAULT_PART_MAX_RECORDS"]
