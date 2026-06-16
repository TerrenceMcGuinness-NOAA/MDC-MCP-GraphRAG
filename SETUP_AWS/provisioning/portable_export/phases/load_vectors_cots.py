"""Load_vectors_cots phase (Task 10).

Reads each Vector_Export part from the Portable_Export, verifies its SHA-256
against the manifest before consuming it (R13.3, R13.4), and loads the records
into ChromaDB via the injected :class:`ChromaDBWriter` with the embedding
passed through bitwise (R2.1, R2.5). Records missing a required field are
recorded as errors and skipped (R2.4). Completed parts are recorded in the
watermark for resumable restore.

A ``fetch(key) -> bytes`` callable supplies part bytes so the same phase works
against S3 or an extracted Export_Bundle.

Requirements: 2.1, 2.4, 2.5, 13.3, 13.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from portable_export.kms_writer import verify_sha256
from portable_export.manifest import ExportManifest
from portable_export.serialization import jsonl_gz_decode
from portable_export.watermarks import Watermarks, unit_key

PHASE = "load_vectors_cots"


@dataclass
class VectorRestoreReport:
    """Aggregate outcome of a vector restore."""

    loaded_per_collection: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def total_loaded(self) -> int:
        return sum(self.loaded_per_collection.values())


def load_vectors_cots(
    fetch: Callable[[str], bytes],
    target,
    manifest: ExportManifest,
    watermarks: Optional[Watermarks] = None,
    *,
    verify_checksums: bool = True,
) -> VectorRestoreReport:
    """Restore every Vector_Export entry in ``manifest`` into the target."""
    report = VectorRestoreReport()
    for entry in manifest.vector_exports:
        target.ensure_collection_or_index(entry.collection_name, entry.model_profile)
        for idx, part_key in enumerate(entry.parts):
            unit = unit_key(phase=PHASE, tenant=entry.tenant_id,
                            collection=entry.collection_name,
                            model_profile=entry.model_profile, part=idx)
            if watermarks is not None and watermarks.is_complete(unit):
                continue
            body = fetch(part_key)
            if verify_checksums and idx < len(entry.sha256_per_part):
                expected = entry.sha256_per_part[idx]
                if expected:
                    verify_sha256(body, expected)
            records = jsonl_gz_decode(body)
            result = target.bulk_insert_vectors(entry.collection_name, records)
            report.loaded_per_collection[entry.collection_name] = (
                report.loaded_per_collection.get(entry.collection_name, 0)
                + getattr(result, "loaded", len(records))
            )
            report.errors.extend(getattr(result, "errors", []))
            if watermarks is not None:
                watermarks.mark_complete(unit)
    return report


__all__ = ["load_vectors_cots", "VectorRestoreReport", "PHASE"]
