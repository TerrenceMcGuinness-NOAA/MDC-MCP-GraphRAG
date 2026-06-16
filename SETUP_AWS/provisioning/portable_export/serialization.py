"""Engine-neutral serialization for Portable_Export parts.

Two on-the-wire formats, chosen so both engines load the same files unchanged
(Property 1):

* **Vector_Export** -- gzipped JSONL, one JSON object per line. Parseable by
  any tool with ``gzip`` + ``json`` (no OpenSearch dependency). Embedding
  arrays are written verbatim (R5.1, R5.2); JSON's double-precision text
  representation round-trips Python floats exactly.
* **Graph_Export** -- gzipped CSV in Neptune-loader property-graph format
  (``~id`` / ``~label`` for nodes, ``~id`` / ``~from`` / ``~to`` / ``~label``
  for relationships). Neptune's bulk-loader CSV is a superset of
  ``neo4j-admin import``'s CSV, so the same part loads on both engines.

All gzip output uses ``mtime=0`` so a re-run produces byte-identical parts --
the resume and bundle byte-equality properties depend on it.

Requirements: 1.1, 1.2, 5.1, 5.2, 13.1.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from typing import Any, Iterable, Sequence

from portable_export.adapters import NodeRow, RelRow

#: Neptune-loader reserved node columns.
NODE_RESERVED = ("~id", "~label")
#: Neptune-loader reserved relationship columns.
REL_RESERVED = ("~id", "~from", "~to", "~label")


def _gzip(data: bytes) -> bytes:
    """Deterministic gzip (mtime=0) so re-runs are byte-identical."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(data)
    return buf.getvalue()


def _gunzip(data: bytes) -> bytes:
    return gzip.decompress(data)


# ── Vector_Export (JSONL.gz) ────────────────────────────────────────────────


def jsonl_encode(records: Iterable[dict]) -> bytes:
    """Encode records as JSONL (uncompressed) bytes, one object per line."""
    lines = [
        json.dumps(r, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        for r in records
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def jsonl_gz_encode(records: Iterable[dict]) -> bytes:
    """Encode records as a gzipped JSONL part (R13.1)."""
    return _gzip(jsonl_encode(list(records)))


def jsonl_gz_decode(data: bytes) -> list[dict]:
    """Decode a gzipped JSONL part back to a list of records."""
    raw = _gunzip(data).decode("utf-8")
    return [json.loads(line) for line in raw.splitlines() if line]


# ── Graph_Export (CSV.gz, Neptune-loader format) ────────────────────────────


def _prop_columns(rows: Sequence[dict]) -> list[str]:
    keys: set[str] = set()
    for r in rows:
        keys.update((r.get("properties") or {}).keys())
    return sorted(keys)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return str(value)


def nodes_csv_encode(label: str, nodes: Sequence[NodeRow]) -> bytes:
    """Encode nodes of one ``label`` as Neptune-loader CSV (uncompressed)."""
    prop_cols = _prop_columns(
        [{"properties": n.properties} for n in nodes]
    )
    header = list(NODE_RESERVED) + prop_cols
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    for n in nodes:
        row = [n.id, label] + [_stringify(n.properties.get(c)) for c in prop_cols]
        writer.writerow(row)
    return out.getvalue().encode("utf-8")


def nodes_csv_gz_encode(label: str, nodes: Sequence[NodeRow]) -> bytes:
    return _gzip(nodes_csv_encode(label, nodes))


def rels_csv_encode(rtype: str, rels: Sequence[RelRow]) -> bytes:
    """Encode relationships of one ``type`` as Neptune-loader CSV."""
    prop_cols = _prop_columns([{"properties": r.properties} for r in rels])
    header = list(REL_RESERVED) + prop_cols
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    for r in rels:
        row = [r.id, r.start, r.end, rtype] + [
            _stringify(r.properties.get(c)) for c in prop_cols
        ]
        writer.writerow(row)
    return out.getvalue().encode("utf-8")


def rels_csv_gz_encode(rtype: str, rels: Sequence[RelRow]) -> bytes:
    return _gzip(rels_csv_encode(rtype, rels))


def csv_gz_decode(data: bytes) -> list[dict]:
    """Decode a gzipped Neptune-loader CSV part to a list of row dicts."""
    raw = _gunzip(data).decode("utf-8")
    reader = csv.DictReader(io.StringIO(raw))
    return [dict(row) for row in reader]


def _props_from_row(row: dict, reserved: Sequence[str]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in reserved and v != ""}


def decode_nodes(data: bytes) -> list[NodeRow]:
    """Reconstruct :class:`NodeRow` objects from a gzipped node CSV part."""
    out: list[NodeRow] = []
    for row in csv_gz_decode(data):
        out.append(
            NodeRow(
                id=row.get("~id", ""),
                label=row.get("~label", ""),
                properties=_props_from_row(row, NODE_RESERVED),
            )
        )
    return out


def decode_rels(data: bytes) -> list[RelRow]:
    """Reconstruct :class:`RelRow` objects from a gzipped relationship CSV part."""
    out: list[RelRow] = []
    for row in csv_gz_decode(data):
        out.append(
            RelRow(
                id=row.get("~id", ""),
                type=row.get("~label", ""),
                start=row.get("~from", ""),
                end=row.get("~to", ""),
                properties=_props_from_row(row, REL_RESERVED),
            )
        )
    return out


__all__ = [
    "jsonl_encode",
    "jsonl_gz_encode",
    "jsonl_gz_decode",
    "nodes_csv_encode",
    "nodes_csv_gz_encode",
    "rels_csv_encode",
    "rels_csv_gz_encode",
    "csv_gz_decode",
    "decode_nodes",
    "decode_rels",
    "NODE_RESERVED",
    "REL_RESERVED",
]
