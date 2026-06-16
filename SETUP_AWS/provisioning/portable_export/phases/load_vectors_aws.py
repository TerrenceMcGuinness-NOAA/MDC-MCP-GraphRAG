"""Load_vectors_aws phase (Task 11).

Reads each Vector_Export part, verifies its SHA-256 against the manifest
(R13.3, R13.4), ensures the target OpenSearch index exists with a
``knn_vector`` mapping matching the Model_Profile dimension (R3.3), refuses on
an existing incompatible mapping (R3.5), and bulk-indexes the records with the
embedding written verbatim (R5.3). Completed parts are recorded in the
watermark. Tenant index prefixes are preserved because the target index is the
manifest's ``collection_name`` (R3.4).

Requirements: 3.1, 3.3, 3.4, 3.5, 5.3, 13.3, 13.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from portable_export.kms_writer import verify_sha256
from portable_export.manifest import ExportManifest
from portable_export.serialization import jsonl_gz_decode
from portable_export.watermarks import Watermarks, unit_key

PHASE = "load_vectors_aws"


@dataclass
class VectorReimportReport:
    indexed_per_index: dict[str, int] = field(default_factory=dict)

    @property
    def total_indexed(self) -> int:
        return sum(self.indexed_per_index.values())


def load_vectors_aws(
    fetch: Callable[[str], bytes],
    target,
    manifest: ExportManifest,
    watermarks: Optional[Watermarks] = None,
    *,
    verify_checksums: bool = True,
) -> VectorReimportReport:
    """Re-import every Vector_Export entry into OpenSearch.

    Raises :class:`MappingConflictError` (from the writer) if a target index
    exists with an incompatible mapping (R3.5).
    """
    report = VectorReimportReport()
    for entry in manifest.vector_exports:
        index = entry.collection_name
        # ensure_collection_or_index refuses on incompatible mapping (R3.5).
        target.ensure_collection_or_index(index, entry.model_profile)
        for idx, part_key in enumerate(entry.parts):
            unit = unit_key(phase=PHASE, tenant=entry.tenant_id, collection=index,
                            model_profile=entry.model_profile, part=idx)
            if watermarks is not None and watermarks.is_complete(unit):
                continue
            body = fetch(part_key)
            if verify_checksums and idx < len(entry.sha256_per_part):
                expected = entry.sha256_per_part[idx]
                if expected:
                    verify_sha256(body, expected)
            records = jsonl_gz_decode(body)
            n = target.bulk_insert_vectors(index, records)
            report.indexed_per_index[index] = (
                report.indexed_per_index.get(index, 0) + n
            )
            if watermarks is not None:
                watermarks.mark_complete(unit)
    return report


__all__ = ["load_vectors_aws", "VectorReimportReport", "PHASE"]
