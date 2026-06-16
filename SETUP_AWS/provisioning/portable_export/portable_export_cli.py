"""Operator CLI for the Cross_Platform_Data_Persistence_System (Task 13).

``portable_export_cli.py {export|restore|reimport|verify|status}``

* ``export``   -- AWS_Export: read OpenSearch + Neptune, stage a Portable_Export.
* ``restore``  -- COTS_Restore: load a Portable_Export into ChromaDB + Neo4j.
* ``reimport`` -- AWS_Reimport: load a Portable_Export into OpenSearch + Neptune.
* ``verify``   -- run a Count_Parity_Check against a target.
* ``status``   -- read manifest + watermarks + lock WITHOUT acquiring the lock.

``--dry-run`` prints the full plan with zero mutation (available from this
wave, so the first invocation in any env can be reviewed before writing).
Destructive restores require an exact confirmation phrase or ``--yes`` before
any destination write (R15.1, R15.2). All console output is ASCII-only
(``[OK]`` / ``[ERROR]`` / ``[WARN]`` / ``[INFO]`` / ``[SKIP]``) per R15.3.

Requirements: 1, 2, 3, 9.4, 11.2, 14.1-14.5, 15.1, 15.2, 15.3.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from portable_export import __version__
from portable_export.direction_dispatcher import (
    AWS_EXPORT,
    AWS_REIMPORT,
    COTS_RESTORE,
    DispatchError,
    Scope,
    build_scope,
    resolve_direction,
)


def _split_csv(value: Optional[str]) -> Optional[list[str]]:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the five subcommands."""
    p = argparse.ArgumentParser(
        prog="portable_export_cli",
        description="Cross-platform Knowledge_Base export / restore / reimport.",
    )
    p.add_argument("--version", action="version", version=f"portable_export {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    # export
    pe = sub.add_parser("export", help="AWS_Export to S3 Portable_Export")
    pe.add_argument("--env", required=True)
    pe.add_argument("--tenants")
    pe.add_argument("--collections")
    g = pe.add_mutually_exclusive_group()
    g.add_argument("--vectors-only", action="store_true")
    g.add_argument("--graph-only", action="store_true")
    pe.add_argument("--prefix")
    pe.add_argument("--bundle", action="store_true")
    pe.add_argument("--resume", action="store_true")
    pe.add_argument("--dry-run", action="store_true")

    # restore
    pr = sub.add_parser("restore", help="COTS_Restore into ChromaDB + Neo4j")
    pr.add_argument("--artefact", required=True)
    pr.add_argument("--target", default="cots", choices=["cots"])
    pr.add_argument("--chromadb-url")
    pr.add_argument("--neo4j-uri")
    pr.add_argument("--tenants")
    pr.add_argument("--collections")
    pr.add_argument("--has-bedrock", action="store_true")
    pr.add_argument("--yes", action="store_true")
    pr.add_argument("--confirm")
    pr.add_argument("--break-lock", action="store_true")
    pr.add_argument("--resume", action="store_true")
    pr.add_argument("--dry-run", action="store_true")

    # reimport
    pi = sub.add_parser("reimport", help="AWS_Reimport into OpenSearch + Neptune")
    pi.add_argument("--artefact", required=True)
    pi.add_argument("--env", required=True)
    pi.add_argument("--tenants")
    pi.add_argument("--collections")
    pi.add_argument("--yes", action="store_true")
    pi.add_argument("--confirm")
    pi.add_argument("--resume", action="store_true")
    pi.add_argument("--dry-run", action="store_true")

    # verify
    pv = sub.add_parser("verify", help="Count_Parity_Check")
    pv.add_argument("--artefact", required=True)
    pv.add_argument("--target", choices=["aws", "cots"])
    pv.add_argument("--env")
    pv.add_argument("--tolerance", type=float, default=0.0)

    # status
    ps = sub.add_parser("status", help="read manifest + watermarks + lock (no lock)")
    ps.add_argument("--artefact", required=True)

    return p


def scope_from_args(args) -> Scope:
    """Build a :class:`Scope` from parsed args (R14)."""
    return build_scope(
        vectors_only=getattr(args, "vectors_only", False),
        graph_only=getattr(args, "graph_only", False),
        tenants=_split_csv(getattr(args, "tenants", None)),
        collections=_split_csv(getattr(args, "collections", None)),
    )


def expected_confirmation_phrase(direction: str, *, env: Optional[str] = None,
                                 artefact: Optional[str] = None) -> str:
    """Return the exact phrase the operator must type to confirm a write.

    For AWS_Reimport the phrase is the destination environment name; for
    COTS_Restore it is the literal ``restore-cots``.
    """
    if direction == AWS_REIMPORT:
        return env or "reimport"
    return "restore-cots"


def render_plan(direction: str, scope: Scope, *, env: Optional[str] = None,
                artefact: Optional[str] = None, prefix: Optional[str] = None,
                bundle: bool = False) -> list[str]:
    """Render the ASCII plan lines for ``--dry-run`` (zero mutation)."""
    spec = resolve_direction(direction)
    lines = [
        f"[INFO] direction={direction} (DRY-RUN, no mutation)",
        f"[INFO] sources={list(spec.source_adapters) or '-'} "
        f"targets={list(spec.target_adapters) or '-'}",
        f"[INFO] scope vectors={scope.vectors} graph={scope.graph} "
        f"dedupe={scope.dedupe}",
        f"[INFO] tenants={list(scope.tenants) if scope.tenants else 'ALL'}",
        f"[INFO] collections="
        f"{list(scope.collections) if scope.collections else 'ALL'}",
    ]
    if env:
        lines.append(f"[INFO] env={env}")
    if artefact:
        lines.append(f"[INFO] artefact={artefact}")
    if prefix:
        lines.append(f"[INFO] prefix={prefix}")
    if bundle:
        lines.append("[INFO] bundle=yes (Export_Bundle tarball will be produced)")
    if spec.target_kind is not None:
        lines.append(
            f"[WARN] {direction} writes to a {spec.target_kind} target; "
            f"confirmation phrase or --yes required for a non-empty target"
        )
    return lines


def _emit(lines: Sequence[str], stream) -> None:
    for line in lines:
        print(line.encode("ascii", "ignore").decode("ascii"), file=stream)


def cmd_export(args, *, out=sys.stdout) -> int:
    scope = scope_from_args(args)
    if args.dry_run:
        _emit(render_plan(AWS_EXPORT, scope, env=args.env, prefix=args.prefix,
                          bundle=args.bundle), out)
        return 0
    print("[ERROR] live AWS_Export execution is gated to the operator wave "
          "(use --dry-run here); wire credentials and run the live procedure",
          file=out)
    return 2


def cmd_restore(args, *, out=sys.stdout) -> int:
    scope = scope_from_args(args)
    if args.dry_run:
        _emit(render_plan(COTS_RESTORE, scope, artefact=args.artefact), out)
        return 0
    print("[ERROR] live COTS_Restore execution is gated to the operator wave "
          "(use --dry-run here)", file=out)
    return 2


def cmd_reimport(args, *, out=sys.stdout) -> int:
    scope = scope_from_args(args)
    if args.dry_run:
        _emit(render_plan(AWS_REIMPORT, scope, env=args.env, artefact=args.artefact),
              out)
        return 0
    print("[ERROR] live AWS_Reimport execution is gated to the operator wave "
          "(use --dry-run here)", file=out)
    return 2


def cmd_verify(args, *, out=sys.stdout) -> int:
    print(f"[INFO] verify artefact={args.artefact} target={args.target} "
          f"tolerance={args.tolerance}", file=out)
    print("[ERROR] live Count_Parity_Check is gated to the operator wave "
          "(reads live destination counts)", file=out)
    return 2


def cmd_status(args, *, out=sys.stdout) -> int:
    # status is read-only and never acquires the lock; live read is gated.
    print(f"[INFO] status artefact={args.artefact} (read-only; no lock acquired)",
          file=out)
    print("[ERROR] live status read is gated to the operator wave", file=out)
    return 2


_HANDLERS = {
    "export": cmd_export,
    "restore": cmd_restore,
    "reimport": cmd_reimport,
    "verify": cmd_verify,
    "status": cmd_status,
}


def main(argv: Optional[Sequence[str]] = None, *, out=sys.stdout) -> int:
    """Parse ``argv`` and dispatch. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        handler = _HANDLERS[args.command]
    except KeyError:  # pragma: no cover - argparse enforces a valid command
        parser.error(f"unknown command {args.command!r}")
        return 2
    try:
        return handler(args, out=out)
    except DispatchError as exc:
        print(f"[ERROR] {exc}", file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
