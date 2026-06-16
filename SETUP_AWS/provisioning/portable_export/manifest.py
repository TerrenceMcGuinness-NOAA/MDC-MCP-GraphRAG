"""Export_Manifest model + reader/writer (Task 4).

The Export_Manifest is the contract every transfer direction reads or writes.
It records source endpoints, timestamp, per-collection / per-tenant counts,
Model_Profiles + embedding dimensions, the tenant list, the scope of a
selective export, schema version, tool version, and per-object SHA-256
checksums (R11.1, R11.4, R13.2).

Compatibility (R11.2, R11.3): a restore reads the manifest and validates the
schema version before writing data. A manifest whose MAJOR version exceeds the
tool's supported MAJOR is refused with :class:`ManifestSchemaUnsupported`
(audit ``Manifest_Schema_Unsupported``).

Requirements: 11.1, 11.2, 11.3, 11.4, 13.2.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from portable_export import SCHEMA_VERSION, __version__


class ManifestError(Exception):
    """Base class for manifest errors."""


class ManifestSchemaUnsupported(ManifestError):
    """The manifest schema MAJOR version exceeds the tool's supported MAJOR."""


class ManifestInvalid(ManifestError):
    """The manifest is structurally invalid (missing required fields)."""


#: Required top-level fields for a well-formed manifest.
REQUIRED_FIELDS: tuple[str, ...] = (
    "schema_version",
    "manifest_id",
    "produced_at",
    "tool_version",
    "tenants",
    "scope",
    "model_profiles",
    "totals",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _major(version: str) -> int:
    return int(str(version).split(".", 1)[0])


@dataclass
class VectorExportEntry:
    """One (tenant, collection) Vector_Export descriptor."""

    tenant_id: str
    collection_name: str
    model_profile: str
    record_count: int = 0
    parts: list[str] = field(default_factory=list)
    sha256_per_part: list[str] = field(default_factory=list)


@dataclass
class GraphExportEntry:
    """One tenant Graph_Export descriptor."""

    tenant_id: str
    node_count: int = 0
    relationship_count: int = 0
    node_parts: list[str] = field(default_factory=list)
    rel_parts: list[str] = field(default_factory=list)
    sha256_per_part: list[str] = field(default_factory=list)


@dataclass
class ExportManifest:
    """The Export_Manifest (design data model).

    Construct via :meth:`new` for a fresh export, or :meth:`from_dict` when
    reading one back for a restore.
    """

    manifest_id: str
    schema_version: str = SCHEMA_VERSION
    produced_at: str = field(default_factory=_utc_now_iso)
    produced_by: Optional[str] = None
    tool_version: str = f"portable_export {__version__}"
    source_endpoints: dict[str, Any] = field(default_factory=dict)
    tenants: list[str] = field(default_factory=list)
    scope: dict[str, Any] = field(
        default_factory=lambda: {
            "vectors": True,
            "graph": True,
            "dedupe": True,
            "selected_collections": None,
        }
    )
    model_profiles: dict[str, Any] = field(default_factory=dict)
    vector_exports: list[VectorExportEntry] = field(default_factory=list)
    graph_exports: list[GraphExportEntry] = field(default_factory=list)
    dedupe_export: Optional[dict[str, Any]] = None
    totals: dict[str, int] = field(default_factory=dict)
    preflight_counts: dict[str, Any] = field(default_factory=dict)

    # ── construction ──────────────────────────────────────────────────

    @classmethod
    def new(
        cls,
        *,
        manifest_id: str,
        tenants: list[str],
        produced_by: Optional[str] = None,
        source_endpoints: Optional[dict[str, Any]] = None,
        scope: Optional[dict[str, Any]] = None,
    ) -> "ExportManifest":
        """Create a fresh manifest skeleton for an AWS_Export."""
        m = cls(
            manifest_id=manifest_id,
            tenants=list(tenants),
            produced_by=produced_by,
            source_endpoints=source_endpoints or {},
        )
        if scope:
            m.scope.update(scope)
        return m

    # ── mutation helpers ──────────────────────────────────────────────

    def add_model_profile(self, short_name: str, *, dimensions: int,
                          provider: str, model_id: str) -> None:
        """Record a Model_Profile + embedding dimension (R4.2)."""
        self.model_profiles[short_name] = {
            "dimensions": dimensions,
            "provider": provider,
            "model_id": model_id,
        }

    def add_vector_export(self, entry: VectorExportEntry) -> None:
        self.vector_exports.append(entry)

    def add_graph_export(self, entry: GraphExportEntry) -> None:
        self.graph_exports.append(entry)

    def recompute_totals(self) -> dict[str, int]:
        """Recompute the ``totals`` block from the entry lists."""
        self.totals = {
            "vector_records": sum(v.record_count for v in self.vector_exports),
            "graph_nodes": sum(g.node_count for g in self.graph_exports),
            "graph_relationships": sum(
                g.relationship_count for g in self.graph_exports
            ),
            "dedupe_entries": (
                int(self.dedupe_export.get("entry_count", 0))
                if self.dedupe_export
                else 0
            ),
        }
        return self.totals

    # ── serialization ─────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def to_json(self) -> bytes:
        return json.dumps(
            self.to_dict(), ensure_ascii=True, sort_keys=True, indent=2
        ).encode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExportManifest":
        """Build an ExportManifest from a parsed dict, validating structure."""
        validate_structure(data)
        ve = [VectorExportEntry(**v) for v in data.get("vector_exports", [])]
        ge = [GraphExportEntry(**g) for g in data.get("graph_exports", [])]
        known = {f for f in (
            "manifest_id", "schema_version", "produced_at", "produced_by",
            "tool_version", "source_endpoints", "tenants", "scope",
            "model_profiles", "dedupe_export", "totals", "preflight_counts",
        )}
        kwargs = {k: data[k] for k in known if k in data}
        m = cls(**kwargs)
        m.vector_exports = ve
        m.graph_exports = ge
        return m

    @classmethod
    def from_json(cls, raw: bytes | str) -> "ExportManifest":
        return cls.from_dict(json.loads(raw))


def validate_structure(data: Any) -> dict[str, Any]:
    """Validate a parsed manifest dict has all required fields.

    Raises
    ------
    ManifestInvalid
        If ``data`` is not a dict or is missing a required field.
    """
    if not isinstance(data, dict):
        raise ManifestInvalid(
            f"manifest root must be a JSON object, got {type(data).__name__}"
        )
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise ManifestInvalid(
            f"manifest missing required field(s): {', '.join(missing)}"
        )
    return data


def validate_compatibility(
    data: dict[str, Any], *, supported_schema_version: str = SCHEMA_VERSION
) -> None:
    """Refuse a manifest whose MAJOR schema version exceeds the tool's (R11.3).

    Raises
    ------
    ManifestSchemaUnsupported
        When ``data["schema_version"]`` MAJOR > supported MAJOR.
    ManifestInvalid
        When the schema_version is missing or unparseable.
    """
    raw = data.get("schema_version")
    if raw is None:
        raise ManifestInvalid("manifest has no schema_version")
    try:
        manifest_major = _major(raw)
    except (ValueError, TypeError) as exc:
        raise ManifestInvalid(f"unparseable schema_version {raw!r}") from exc
    if manifest_major > _major(supported_schema_version):
        raise ManifestSchemaUnsupported(
            f"manifest schema_version {raw} (major {manifest_major}) exceeds "
            f"tool-supported major {_major(supported_schema_version)}"
        )


# ── S3 read/write helpers ───────────────────────────────────────────────────


def manifest_key(prefix: str) -> str:
    """The S3 key of the manifest object for a Portable_Export prefix."""
    return f"{prefix.rstrip('/')}/manifest.json"


def write_manifest(s3_client: Any, bucket: str, prefix: str,
                   manifest: ExportManifest) -> str:
    """Write the manifest JSON to ``<prefix>/manifest.json``. Returns the key."""
    key = manifest_key(prefix)
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=manifest.to_json(),
        ContentType="application/json",
    )
    return key


def read_manifest(
    s3_client: Any,
    bucket: str,
    prefix: str,
    *,
    supported_schema_version: str = SCHEMA_VERSION,
) -> ExportManifest:
    """Read + validate the manifest before a restore (R11.2, R11.3).

    Validates structure and refuses an unsupported MAJOR schema version
    before returning the parsed :class:`ExportManifest`.
    """
    key = manifest_key(prefix)
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    data = json.loads(resp["Body"].read())
    validate_structure(data)
    validate_compatibility(data, supported_schema_version=supported_schema_version)
    return ExportManifest.from_dict(data)


__all__ = [
    "ExportManifest",
    "VectorExportEntry",
    "GraphExportEntry",
    "ManifestError",
    "ManifestSchemaUnsupported",
    "ManifestInvalid",
    "validate_structure",
    "validate_compatibility",
    "manifest_key",
    "write_manifest",
    "read_manifest",
    "REQUIRED_FIELDS",
]
