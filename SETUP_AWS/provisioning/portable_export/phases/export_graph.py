"""Export_graph phase (Task 9).

Per tenant: stream nodes and relationships, group by label / type, write each
group as gzipped Neptune-loader CSV parts (one CSV per (label, part)), write
each part SSE-KMS with a streaming SHA-256, and record the completed unit in
the watermark. Tenant-prefixed labels are preserved verbatim (R7.3).

A tenant with zero graph data yields a zero-count GraphExportEntry and no
error (R7.5).

Requirements: 1.2, 1.3, 1.5, 7.3, 7.5, 13.1, 13.2.
"""

from __future__ import annotations

from typing import Iterable, Optional

from portable_export.kms_writer import KmsWriter, compute_sha256
from portable_export.manifest import ExportManifest, GraphExportEntry
from portable_export.serialization import nodes_csv_gz_encode, rels_csv_gz_encode
from portable_export.watermarks import Watermarks, unit_key

PHASE = "export_graph"


def _node_key(prefix: str, tenant: str, label: str, idx: int) -> str:
    return f"{prefix.rstrip('/')}/graph/{tenant}/nodes/{label}-{idx:03d}.csv.gz"


def _rel_key(prefix: str, tenant: str, rtype: str, idx: int) -> str:
    return f"{prefix.rstrip('/')}/graph/{tenant}/rels/{rtype}-{idx:03d}.csv.gz"


def export_graph_tenant(
    reader,
    kms_writer: KmsWriter,
    watermarks: Optional[Watermarks],
    *,
    prefix: str,
    tenant: str,
) -> GraphExportEntry:
    """Export one tenant's nodes + relationships to CSV.gz parts."""
    entry = GraphExportEntry(tenant_id=tenant)

    # Group nodes by label.
    nodes_by_label: dict[str, list] = {}
    for node in reader.stream_nodes(tenant):
        nodes_by_label.setdefault(node.label, []).append(node)
    for label in sorted(nodes_by_label):
        rows = nodes_by_label[label]
        key = _node_key(prefix, tenant, label, 0)
        unit = unit_key(phase=PHASE, tenant=tenant, collection=f"nodes/{label}", part=0)
        body = nodes_csv_gz_encode(label, rows)
        if watermarks is not None and watermarks.is_complete(unit):
            entry.node_parts.append(key)
            entry.node_count += len(rows)
            entry.sha256_per_part.append(compute_sha256(body))
            continue
        sha = kms_writer.put(key, body, content_type="application/gzip")
        entry.node_parts.append(key)
        entry.sha256_per_part.append(sha)
        entry.node_count += len(rows)
        if watermarks is not None:
            watermarks.mark_complete(unit)

    # Group relationships by type.
    rels_by_type: dict[str, list] = {}
    for rel in reader.stream_relationships(tenant):
        rels_by_type.setdefault(rel.type, []).append(rel)
    for rtype in sorted(rels_by_type):
        rows = rels_by_type[rtype]
        key = _rel_key(prefix, tenant, rtype, 0)
        unit = unit_key(phase=PHASE, tenant=tenant, collection=f"rels/{rtype}", part=0)
        body = rels_csv_gz_encode(rtype, rows)
        if watermarks is not None and watermarks.is_complete(unit):
            entry.rel_parts.append(key)
            entry.relationship_count += len(rows)
            entry.sha256_per_part.append(compute_sha256(body))
            continue
        sha = kms_writer.put(key, body, content_type="application/gzip")
        entry.rel_parts.append(key)
        entry.sha256_per_part.append(sha)
        entry.relationship_count += len(rows)
        if watermarks is not None:
            watermarks.mark_complete(unit)

    return entry


def export_graph(
    reader,
    kms_writer: KmsWriter,
    watermarks: Optional[Watermarks],
    manifest: ExportManifest,
    *,
    prefix: str,
    tenants: Iterable[str],
) -> list[GraphExportEntry]:
    """Export the graph for every tenant; append each entry to the manifest."""
    entries: list[GraphExportEntry] = []
    for tenant in tenants:
        entry = export_graph_tenant(
            reader, kms_writer, watermarks, prefix=prefix, tenant=tenant
        )
        manifest.add_graph_export(entry)
        entries.append(entry)
    return entries


__all__ = ["export_graph", "export_graph_tenant", "PHASE"]
