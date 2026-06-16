"""Load_graph_aws phase (Task 11).

The Graph_Export parts are already S3-resident, so AWS_Reimport loads the graph
with the Neptune bulk loader pointed at ``<prefix>/graph/<tenant>/`` (R3.2).
One loader job per tenant; each is polled until ``LOAD_COMPLETED``. Completed
tenants are recorded in the watermark.

Requirements: 3.2, 13.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from portable_export.manifest import ExportManifest
from portable_export.watermarks import Watermarks, unit_key

PHASE = "load_graph_aws"


@dataclass
class GraphReimportReport:
    load_ids_per_tenant: dict[str, str] = field(default_factory=dict)


def _tenant_graph_source(bucket: str, prefix: str, tenant: str) -> str:
    return f"s3://{bucket}/{prefix.rstrip('/')}/graph/{tenant}/"


def load_graph_aws(
    loader,
    manifest: ExportManifest,
    watermarks: Optional[Watermarks] = None,
    *,
    bucket: str,
    prefix: str,
) -> GraphReimportReport:
    """Start + wait a Neptune bulk-loader job per tenant graph prefix."""
    report = GraphReimportReport()
    for entry in manifest.graph_exports:
        tenant = entry.tenant_id
        unit = unit_key(phase=PHASE, tenant=tenant, part=0)
        if watermarks is not None and watermarks.is_complete(unit):
            continue
        if entry.node_count == 0 and entry.relationship_count == 0:
            # nothing to load for this tenant
            if watermarks is not None:
                watermarks.mark_complete(unit)
            continue
        source = _tenant_graph_source(bucket, prefix, tenant)
        load_id = loader.start(source)
        loader.wait(load_id)
        report.load_ids_per_tenant[tenant] = load_id
        if watermarks is not None:
            watermarks.mark_complete(unit)
    return report


__all__ = ["load_graph_aws", "GraphReimportReport", "PHASE"]
