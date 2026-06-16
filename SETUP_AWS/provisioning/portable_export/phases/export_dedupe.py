"""Export_dedupe phase (Task 9).

Reads the Dedupe_Registry (``mdc-content-sha-registry``) and writes a
Dedupe_Registry_Export preserving the ``(collection, sha)`` composite keys per
tenant (R8.1, R8.2). Each tenant's entries are written as a gzipped JSONL part
SSE-KMS with a streaming SHA-256.

Requirements: 8.1, 8.2, 13.1, 13.2.
"""

from __future__ import annotations

from typing import Iterable, Optional

from portable_export.adapters import DedupeRow
from portable_export.kms_writer import KmsWriter, compute_sha256
from portable_export.serialization import jsonl_gz_encode
from portable_export.watermarks import Watermarks, unit_key

PHASE = "export_dedupe"


def _part_key(prefix: str, tenant: str, idx: int) -> str:
    return f"{prefix.rstrip('/')}/dedupe/{tenant}/{idx:03d}.jsonl.gz"


def export_dedupe(
    rows: Iterable[DedupeRow],
    kms_writer: KmsWriter,
    watermarks: Optional[Watermarks],
    *,
    prefix: str,
) -> dict:
    """Export dedupe rows grouped by tenant; return the manifest ``dedupe_export``.

    Returns a dict suitable for ``ExportManifest.dedupe_export`` with
    ``format='exported'``, the per-tenant parts, their SHA-256s, and the total
    entry count.
    """
    by_tenant: dict[str, list[dict]] = {}
    for row in rows:
        by_tenant.setdefault(row.tenant_id, []).append(
            {"collection": row.collection, "sha": row.sha}
        )
    parts: list[str] = []
    shas: list[str] = []
    total = 0
    for tenant in sorted(by_tenant):
        entries = by_tenant[tenant]
        key = _part_key(prefix, tenant, 0)
        unit = unit_key(phase=PHASE, tenant=tenant, part=0)
        total += len(entries)
        body = jsonl_gz_encode(entries)
        if watermarks is not None and watermarks.is_complete(unit):
            parts.append(key)
            shas.append(compute_sha256(body))
            continue
        sha = kms_writer.put(key, body, content_type="application/gzip")
        parts.append(key)
        shas.append(sha)
        if watermarks is not None:
            watermarks.mark_complete(unit)
    return {
        "format": "exported",
        "parts": parts,
        "sha256_per_part": shas,
        "entry_count": total,
    }


__all__ = ["export_dedupe", "PHASE"]
