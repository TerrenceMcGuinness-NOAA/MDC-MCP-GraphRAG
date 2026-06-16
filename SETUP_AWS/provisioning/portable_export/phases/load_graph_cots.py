"""Load_graph_cots phase (Task 10).

Reads each Graph_Export part from the Portable_Export, verifies its SHA-256
against the manifest before consuming it (R13.3, R13.4), reconstructs the
nodes / relationships, and loads them into Neo4j via the injected
:class:`Neo4jWriter` transactional path (the bulk ``neo4j-admin import`` path
is used for very large restores; both preserve tenant-prefixed labels, R2.3).

A ``fetch(key) -> bytes`` callable supplies part bytes so the same phase works
against S3 or an extracted Export_Bundle.

Requirements: 2.2, 2.3, 13.3, 13.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from portable_export.kms_writer import verify_sha256
from portable_export.manifest import ExportManifest
from portable_export.serialization import decode_nodes, decode_rels
from portable_export.watermarks import Watermarks, unit_key

PHASE = "load_graph_cots"


@dataclass
class GraphRestoreReport:
    """Aggregate outcome of a graph restore."""

    nodes_per_tenant: dict[str, int] = field(default_factory=dict)
    rels_per_tenant: dict[str, int] = field(default_factory=dict)


def load_graph_cots(
    fetch: Callable[[str], bytes],
    target,
    manifest: ExportManifest,
    watermarks: Optional[Watermarks] = None,
    *,
    verify_checksums: bool = True,
) -> GraphRestoreReport:
    """Restore every Graph_Export entry in ``manifest`` into Neo4j."""
    report = GraphRestoreReport()
    for entry in manifest.graph_exports:
        tenant = entry.tenant_id
        # SHA list is node_parts followed by rel_parts in write order.
        sha = list(entry.sha256_per_part)
        node_n = 0
        for i, part_key in enumerate(entry.node_parts):
            unit = unit_key(phase=PHASE, tenant=tenant,
                            collection=f"nodes:{part_key}", part=i)
            if watermarks is not None and watermarks.is_complete(unit):
                continue
            body = fetch(part_key)
            if verify_checksums and i < len(sha) and sha[i]:
                verify_sha256(body, sha[i])
            nodes = decode_nodes(body)
            node_n += target.write_nodes(nodes)
            if watermarks is not None:
                watermarks.mark_complete(unit)
        offset = len(entry.node_parts)
        rel_n = 0
        for j, part_key in enumerate(entry.rel_parts):
            unit = unit_key(phase=PHASE, tenant=tenant,
                            collection=f"rels:{part_key}", part=j)
            if watermarks is not None and watermarks.is_complete(unit):
                continue
            body = fetch(part_key)
            sha_idx = offset + j
            if verify_checksums and sha_idx < len(sha) and sha[sha_idx]:
                verify_sha256(body, sha[sha_idx])
            rels = decode_rels(body)
            rel_n += target.write_relationships(rels)
            if watermarks is not None:
                watermarks.mark_complete(unit)
        report.nodes_per_tenant[tenant] = node_n
        report.rels_per_tenant[tenant] = rel_n
    return report


__all__ = ["load_graph_cots", "GraphRestoreReport", "PHASE"]
