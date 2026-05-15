"""Validate ``unified_manifest.json`` against the schema and known indices.

Checks (Requirements 7.4 – 7.6):

1. **Common required fields** present on every entry.
2. **Type-specific required fields** present per ``source_type``
   (delegated to :class:`SourceEntry.from_dict`).
3. **Unique names** — no two entries share a ``name``.
4. **Embedding profile** registered in
   :class:`src.data.embedding_registry.EmbeddingModelRegistry`.
5. **Collection target** resolves to a known production OpenSearch
   index via :func:`src.config.aws_config.resolve_index`. Unresolved
   targets are reported as warnings (not errors) so future indices
   can be staged in the manifest before they exist in OpenSearch.

Exit codes:
    0 — all checks passed (warnings allowed)
    1 — at least one error
    2 — could not load the manifest at all
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Make ``src.*`` importable when executed as a script.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.manifest.loader import BUNDLED_MANIFEST_PATH
from src.manifest.models import SourceEntry, SourceType, UnifiedManifest

log = logging.getLogger("validate_manifest")


# ── validators ────────────────────────────────────────────────────────


def _validate_uniqueness(entries: list[SourceEntry]) -> list[str]:
    """Return error messages for duplicate ``name`` values (Requirement 7.6)."""
    counts = Counter(e.name for e in entries)
    return [
        f"duplicate name: {name!r} appears {count} times"
        for name, count in counts.items()
        if count > 1
    ]


def _validate_embedding_profiles(entries: list[SourceEntry]) -> list[str]:
    """Each ``embedding_profile`` must be a registered profile."""
    try:
        from src.data.embedding_registry import EmbeddingModelRegistry
    except Exception as exc:  # pragma: no cover - import guard
        return [f"could not import EmbeddingModelRegistry: {exc}"]

    registry = EmbeddingModelRegistry()
    known = set(registry.list_profiles())
    return [
        f"{e.name}: unknown embedding_profile {e.embedding_profile!r} "
        f"(known: {sorted(known)})"
        for e in entries
        if e.embedding_profile not in known
    ]


def _validate_collection_targets(entries: list[SourceEntry]) -> list[str]:
    """Warn for ``collection_target`` values that don't resolve to an index.

    This is a warning rather than an error because future indices can
    legitimately be staged in the manifest before they exist on the
    cluster (Requirement 7.6).
    """
    try:
        from src.config.aws_config import (
            PRODUCTION_INDICES_BY_PROFILE,
            resolve_index,
        )
    except Exception as exc:  # pragma: no cover - import guard
        return [f"could not import aws_config: {exc}"]

    warnings: list[str] = []
    for entry in entries:
        # ``resolve_index`` returns the input unchanged when the
        # collection isn't in the per-profile map. Detect that
        # explicitly so we can flag the entry.
        per_profile = PRODUCTION_INDICES_BY_PROFILE.get(
            entry.embedding_profile, {}
        )
        resolved = resolve_index(
            entry.collection_target, entry.embedding_profile
        )
        if entry.collection_target not in per_profile and resolved == entry.collection_target:
            warnings.append(
                f"{entry.name}: collection_target "
                f"{entry.collection_target!r} does not resolve to a known "
                f"OpenSearch index for profile {entry.embedding_profile!r}"
            )
    return warnings


def _load_manifest_or_exit(path: Path) -> UnifiedManifest:
    """Load and parse the manifest, exiting cleanly on failure."""
    if not path.is_file():
        log.error("[ERROR] manifest file not found: %s", path)
        sys.exit(2)
    try:
        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        log.error("[ERROR] %s is not valid JSON: %s", path, exc)
        sys.exit(2)
    try:
        return UnifiedManifest.from_dict(raw)
    except ValueError as exc:
        # Per-entry validation failed in from_dict — Requirement 7.5 /
        # 7.6 say to report the offending entry name + value, which
        # the from_dict messages already include.
        log.error("[ERROR] schema validation failed: %s", exc)
        sys.exit(1)


# ── CLI ──────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="validate_manifest",
        description=(
            "Validate unified_manifest.json against the schema and known "
            "OpenSearch indices. Reports errors and warnings, exits non-"
            "zero on errors."
        ),
    )
    p.add_argument(
        "--manifest",
        type=Path,
        default=BUNDLED_MANIFEST_PATH,
        help=f"Manifest path (default: {BUNDLED_MANIFEST_PATH})",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (exits non-zero on any issue)",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(name)s — %(message)s",
    )

    manifest = _load_manifest_or_exit(args.manifest)
    log.info(
        "loaded manifest version=%s sources=%d",
        manifest.version,
        len(manifest.sources),
    )

    errors: list[str] = []
    warnings: list[str] = []

    errors.extend(_validate_uniqueness(manifest.sources))
    errors.extend(_validate_embedding_profiles(manifest.sources))
    warnings.extend(_validate_collection_targets(manifest.sources))

    for msg in errors:
        log.error("[ERROR] %s", msg)
    for msg in warnings:
        log.warning("[WARN]  %s", msg)

    if errors:
        log.error(
            "[FAIL] manifest invalid: %d error(s), %d warning(s)",
            len(errors),
            len(warnings),
        )
        return 1
    if args.strict and warnings:
        log.error(
            "[FAIL] strict mode: %d warning(s) treated as errors",
            len(warnings),
        )
        return 1
    log.info(
        "[OK] manifest valid: %d source(s), %d warning(s)",
        len(manifest.sources),
        len(warnings),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
