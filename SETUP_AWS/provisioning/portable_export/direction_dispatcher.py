"""Direction dispatcher (Task 13).

Maps each transfer direction to its source readers, target writers, and
defaults, and resolves the selective scope (``--vectors-only`` /
``--graph-only`` / ``--collections`` / ``--tenants``). It also owns the
operator confirmation gate (Property 7): no destination write is issued before
the operator confirmation completes (interactive phrase or ``--yes``).

The gated :func:`execute_restore` is the single place where COTS_Restore and
AWS_Reimport actually write, so the confirmation invariant is enforced in one
auditable spot.

Requirements: 1, 2, 3, 14.1-14.5, 15.1, 15.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from portable_export.manifest import ExportManifest
from portable_export.query_embedder_check import CompatibilityResult, check_compatibility

# ── Directions ────────────────────────────────────────────────────────────────

AWS_EXPORT = "AWS_Export"
COTS_RESTORE = "COTS_Restore"
AWS_REIMPORT = "AWS_Reimport"

VALID_DIRECTIONS: tuple[str, ...] = (AWS_EXPORT, COTS_RESTORE, AWS_REIMPORT)


class DispatchError(ValueError):
    """Raised for an unknown direction or an invalid scope combination."""


@dataclass(frozen=True)
class DirectionSpec:
    """Adapter wiring + defaults for one direction."""

    direction: str
    source_adapters: tuple[str, ...]
    target_adapters: tuple[str, ...]
    reads_s3: bool
    writes_s3: bool
    target_kind: Optional[str]  # "cots" | "aws" | None (export)


DIRECTION_SPECS: dict[str, DirectionSpec] = {
    AWS_EXPORT: DirectionSpec(
        direction=AWS_EXPORT,
        source_adapters=("opensearch_reader", "neptune_reader"),
        target_adapters=(),
        reads_s3=False,
        writes_s3=True,
        target_kind=None,
    ),
    COTS_RESTORE: DirectionSpec(
        direction=COTS_RESTORE,
        source_adapters=(),
        target_adapters=("chromadb_writer", "neo4j_writer"),
        reads_s3=True,
        writes_s3=False,
        target_kind="cots",
    ),
    AWS_REIMPORT: DirectionSpec(
        direction=AWS_REIMPORT,
        source_adapters=(),
        target_adapters=("opensearch_writer", "neptune_loader"),
        reads_s3=True,
        writes_s3=False,
        target_kind="aws",
    ),
}


def resolve_direction(direction: str) -> DirectionSpec:
    """Return the :class:`DirectionSpec` for ``direction`` or raise."""
    spec = DIRECTION_SPECS.get(direction)
    if spec is None:
        raise DispatchError(
            f"unknown direction {direction!r}; valid: {VALID_DIRECTIONS}"
        )
    return spec


# ── Scope ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Scope:
    """The selected scope of a transfer (R14)."""

    vectors: bool = True
    graph: bool = True
    dedupe: bool = True
    tenants: Optional[tuple[str, ...]] = None
    collections: Optional[tuple[str, ...]] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "vectors": self.vectors,
            "graph": self.graph,
            "dedupe": self.dedupe,
            "selected_collections": list(self.collections) if self.collections else None,
            "selected_tenants": list(self.tenants) if self.tenants else None,
        }


def build_scope(
    *,
    vectors_only: bool = False,
    graph_only: bool = False,
    dedupe: bool = True,
    tenants: Optional[list[str]] = None,
    collections: Optional[list[str]] = None,
) -> Scope:
    """Build a :class:`Scope`, refusing contradictory flags (R14.3, R14.4)."""
    if vectors_only and graph_only:
        raise DispatchError("--vectors-only and --graph-only are mutually exclusive")
    vectors = not graph_only
    graph = not vectors_only
    # dedupe only meaningful when graph/vectors export is full; a vectors/graph
    # -only or collection-scoped selection drops the dedupe registry export.
    eff_dedupe = dedupe and vectors and graph and not collections
    return Scope(
        vectors=vectors,
        graph=graph,
        dedupe=eff_dedupe,
        tenants=tuple(tenants) if tenants else None,
        collections=tuple(collections) if collections else None,
    )


# ── Confirmation gate (Property 7) ──────────────────────────────────────────


def needs_confirmation(probe_result: dict) -> bool:
    """A destructive write needs confirmation when the target is non-empty."""
    return bool(probe_result)


def confirmation_satisfied(
    *, yes: bool, provided_phrase: Optional[str], expected_phrase: str
) -> bool:
    """Return ``True`` when ``--yes`` was passed or the exact phrase matched."""
    if yes:
        return True
    return provided_phrase is not None and provided_phrase == expected_phrase


# ── Gated restore execution ─────────────────────────────────────────────────


@dataclass
class RestoreOutcome:
    """Result of a (gated) restore / reimport."""

    performed: bool
    direction: str
    query_compatibility: Optional[CompatibilityResult] = None
    vector_report: Any = None
    graph_report: Any = None
    dedupe_rows: Any = None
    reason: str = ""


def _profiles_in_manifest(manifest: ExportManifest) -> list[str]:
    profiles = list(manifest.model_profiles.keys())
    if profiles:
        return profiles
    return sorted({ve.model_profile for ve in manifest.vector_exports})


def execute_restore(
    direction: str,
    *,
    manifest: ExportManifest,
    fetch,
    vector_target=None,
    graph_target=None,
    probe_result: Optional[dict] = None,
    confirmed: bool = False,
    scope: Optional[Scope] = None,
    has_bedrock: bool = False,
    audit=None,
    watermarks=None,
    loader=None,
    bucket: Optional[str] = None,
    prefix: Optional[str] = None,
    dedupe_write_fn=None,
) -> RestoreOutcome:
    """Run a restore / reimport behind the confirmation gate (Property 7).

    No write method on any target is invoked until ``confirmed`` is true (or the
    target is empty). When the target is non-empty and unconfirmed the function
    emits ``Confirmation_Declined`` and returns ``performed=False`` without any
    destination write.
    """
    spec = resolve_direction(direction)
    if spec.target_kind is None:
        raise DispatchError(f"{direction} is not a restore/reimport direction")
    scope = scope or Scope()
    probe_result = probe_result or {}

    target_kind = spec.target_kind
    compat = check_compatibility(
        _profiles_in_manifest(manifest),
        target=target_kind,
        has_bedrock=has_bedrock,
    )
    if audit is not None and not compat.all_compatible:
        audit.emit("Query_Incompatible",
                   record_counts={"incompatible": len(compat.incompatible_profiles)},
                   query_compatibility=compat.per_profile)

    # ── confirmation gate -- BEFORE any write ──
    if needs_confirmation(probe_result) and not confirmed:
        if audit is not None:
            audit.emit("Confirmation_Declined", phase="confirmation_gate",
                       record_counts={"non_empty_targets": len(probe_result)})
        return RestoreOutcome(
            performed=False, direction=direction,
            query_compatibility=compat,
            reason="confirmation required for non-empty target",
        )

    # Lazy imports avoid a heavy import graph when only resolving directions.
    from portable_export.phases import (
        load_graph_aws,
        load_graph_cots,
        load_vectors_aws,
        load_vectors_cots,
        rebuild_dedupe_aws,
    )

    outcome = RestoreOutcome(performed=True, direction=direction,
                             query_compatibility=compat)

    if scope.vectors and vector_target is not None:
        if target_kind == "cots":
            outcome.vector_report = load_vectors_cots.load_vectors_cots(
                fetch, vector_target, manifest, watermarks)
        else:
            outcome.vector_report = load_vectors_aws.load_vectors_aws(
                fetch, vector_target, manifest, watermarks)

    if scope.graph and graph_target is not None and target_kind == "cots":
        outcome.graph_report = load_graph_cots.load_graph_cots(
            fetch, graph_target, manifest, watermarks)
    elif scope.graph and target_kind == "aws" and loader is not None:
        outcome.graph_report = load_graph_aws.load_graph_aws(
            loader, manifest, watermarks, bucket=bucket or "", prefix=prefix or "")

    if target_kind == "aws" and scope.dedupe:
        outcome.dedupe_rows = rebuild_dedupe_aws.rebuild_dedupe(
            fetch, manifest, write_fn=dedupe_write_fn)

    if audit is not None:
        event = ("COTS_Restore_Completed" if target_kind == "cots"
                 else "AWS_Reimport_Completed")
        audit.emit(event, query_compatibility=compat.per_profile)

    return outcome


__all__ = [
    "AWS_EXPORT",
    "COTS_RESTORE",
    "AWS_REIMPORT",
    "VALID_DIRECTIONS",
    "DirectionSpec",
    "DIRECTION_SPECS",
    "resolve_direction",
    "Scope",
    "build_scope",
    "needs_confirmation",
    "confirmation_satisfied",
    "execute_restore",
    "RestoreOutcome",
    "DispatchError",
]
