"""Operator CLI for the Cost_Control_System (Task 13).

``cost_control {hibernate|wake|status} [--env ENV] [--yes] [--dry-run]
[--resume] [--force-drift]``

* ``status``    prints the parsed State_File without acquiring the lock and
                without mutating any AWS resource (R8.5).
* ``--dry-run`` prints every tier's ``plan()`` for the requested transition
                with ZERO mutation; mandatory-safe first invocation.
* destructive   ``hibernate`` / ``wake`` display the resolved environment, the
                resources affected, and the snapshots involved, then require
                the exact confirmation phrase before any destructive AWS call
                (R15). ``--yes`` substitutes a recorded confirmation token for
                CI / scheduled use and is logged.

The command wiring is split into a thin :func:`main` (builds real boto3-backed
dependencies) and :func:`run` (pure orchestration over an injected
:class:`CliDeps`), so the CLI is unit tested without any live AWS.

ASCII-only console output.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Callable, Optional

from cost_control.state_machine import EXIT_OK, StateMachine


@dataclass
class CliDeps:
    """Everything :func:`run` needs, injected so tests avoid live AWS."""

    environment_name: str
    state_machine: StateMachine
    audit: Any
    plan_tiers: list[Any]
    input_fn: Callable[[str], str] = input
    output_fn: Callable[[str], None] = lambda line: print(line)


def build_parser() -> argparse.ArgumentParser:
    """Build the operator argparse parser."""
    p = argparse.ArgumentParser(
        prog="cost_control",
        description="Hibernate / wake the MDC MCP-RAG platform to preserve "
                    "NIH Sandbox funding.",
    )
    p.add_argument("command", choices=("hibernate", "wake", "status"),
                   help="operation to perform")
    p.add_argument("--env", dest="env", default=None,
                   help="Environment_Name (dev/staging/prod). Falls back to "
                        "COST_CONTROL_ENV.")
    p.add_argument("--yes", action="store_true",
                   help="non-interactive: substitute the recorded confirmation "
                        "token (CI / scheduled).")
    p.add_argument("--dry-run", action="store_true",
                   help="print the per-tier plan with zero mutation.")
    p.add_argument("--resume", action="store_true",
                   help="resume a transition from a degraded state.")
    p.add_argument("--force-drift", action="store_true",
                   help="proceed with wake despite detected destructive drift.")
    return p


def confirmation_phrase(command: str, environment_name: str) -> str:
    """The exact phrase the operator must type for a destructive command."""
    return f"{command} {environment_name}"


def confirm_gate(
    *,
    command: str,
    environment_name: str,
    yes: bool,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> bool:
    """Return True iff the operator confirmed (exact phrase) or ``--yes``.

    ``--yes`` substitutes a recorded token and returns True without prompting.
    """
    expected = confirmation_phrase(command, environment_name)
    if yes:
        output_fn(f"[INFO] --yes supplied; recorded confirmation token for "
                  f"'{expected}'")
        return True
    output_fn(f"[WARN] This will {command} environment '{environment_name}'.")
    output_fn(f"[WARN] Type exactly '{expected}' to proceed:")
    try:
        answer = input_fn("> ")
    except EOFError:
        answer = ""
    return answer.strip() == expected


def _print_plan(deps: CliDeps, mode: str) -> None:
    plans = deps.state_machine.plan_all(mode)
    deps.output_fn(f"[INFO] Dry-run plan for '{mode}' in env "
                   f"'{deps.environment_name}' (no mutation):")
    for action in plans:
        flag = "DESTRUCTIVE" if action.destructive else "safe"
        deps.output_fn(f"  [{flag}] {action.tier}: {action.action} -- "
                       f"{action.description}")


def run(args: argparse.Namespace, deps: CliDeps) -> int:
    """Execute the parsed command over the injected dependencies.

    Returns the process exit code. Never prompts or mutates for ``status`` or
    ``--dry-run``.
    """
    command = args.command

    if command == "status":
        doc = deps.state_machine.status()
        deps.output_fn(f"[INFO] Cost_Control state for env "
                       f"'{deps.environment_name}':")
        deps.output_fn(f"  current_state    : {doc.get('current_state')}")
        deps.output_fn(f"  previous_state   : {doc.get('previous_state')}")
        deps.output_fn(f"  last_transition  : {doc.get('last_transition_at')}")
        deps.output_fn(f"  last_caller_arn  : {doc.get('last_caller_arn')}")
        deps.output_fn(f"  operation_counter: {doc.get('operation_counter')}")
        deps.output_fn(f"  latest_snapshots : {doc.get('latest_snapshots')}")
        return EXIT_OK

    mode = command  # hibernate | wake

    if args.dry_run:
        _print_plan(deps, mode)
        return EXIT_OK

    # Confirmation gate precedes any destructive call (Property 6 / R15).
    confirmed = confirm_gate(
        command=command,
        environment_name=deps.environment_name,
        yes=args.yes,
        input_fn=deps.input_fn,
        output_fn=deps.output_fn,
    )

    if command == "hibernate":
        result = deps.state_machine.hibernate(resume=args.resume, confirmed=confirmed)
    else:
        result = deps.state_machine.wake(
            resume=args.resume, force_drift=args.force_drift, confirmed=confirmed
        )

    deps.output_fn(f"[{'OK' if result.success else 'ERROR'}] "
                   f"{result.message} (state={result.final_state})")
    # Persist the consolidated per-operation audit object exactly once.
    flush = getattr(deps.audit, "flush", None)
    if callable(flush):
        flush()
    return result.exit_code


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover - thin wiring
    """Build real boto3-backed dependencies and run the parsed command."""
    import os
    import uuid

    from cost_control import config as cc_config
    from cost_control.audit import AuditLogger
    from cost_control.costs import CostModel
    from cost_control.state_file import StateFile
    from cost_control.tiers.agentcore_tier import AgentCoreTier
    from cost_control.tiers.ec2_tier import EC2Tier
    from cost_control.tiers.nat_tier import NatTier
    from cost_control.tiers.neptune_tier import NeptuneTier
    from cost_control.tiers.opensearch_tier import OpenSearchTier

    args = build_parser().parse_args(argv)
    env_name = args.env or os.environ.get("COST_CONTROL_ENV")
    if not env_name:
        print("[ERROR] --env or COST_CONTROL_ENV is required", file=sys.stderr)
        return EXIT_ERROR
    cfg = cc_config.resolve_config(env_name)

    session = cc_config.build_session(region_name=cfg.aws_region)
    s3 = session.client("s3")
    operation_id = str(uuid.uuid4())

    try:
        caller_arn = session.client("sts").get_caller_identity().get("Arn", "unknown")
    except Exception:  # noqa: BLE001
        caller_arn = "unknown"

    audit = AuditLogger(
        operation_id=operation_id,
        caller_arn=caller_arn,
        environment_name=env_name,
        log_group=cfg.log_group,
        audit_bucket=cfg.audit_bucket,
        audit_prefix=cfg.audit_prefix,
        logs_client=session.client("logs"),
        s3_client=s3,
    )
    state_file = StateFile(s3, cfg.state_bucket, cfg.state_key)

    tiers = []
    if cfg.ec2_instance_id:
        tiers.append(EC2Tier(cfg, session.client("ec2"),
                             operation_id=operation_id, audit=audit))
    if cfg.neptune_cluster_id:
        tiers.append(NeptuneTier(cfg, session.client("neptune"),
                                 operation_id=operation_id, audit=audit))
    if cfg.opensearch_domain_name:
        tiers.append(OpenSearchTier(cfg, session.client("opensearch"),
                                    operation_id=operation_id, audit=audit))
    if cfg.agentcore_runtime_arn:
        tiers.append(AgentCoreTier(cfg, session.client("bedrock-agentcore-control"),
                                   ecr_client=session.client("ecr"),
                                   operation_id=operation_id, audit=audit))
    tiers.append(NatTier(cfg, session.client("ec2"),
                         operation_id=operation_id, audit=audit))

    sm = StateMachine(
        environment_name=env_name,
        state_file=state_file,
        audit=audit,
        tiers=tiers,
        cost_model=CostModel(),
        caller_arn=caller_arn,
        operation_id=operation_id,
    )
    deps = CliDeps(environment_name=env_name, state_machine=sm, audit=audit,
                   plan_tiers=tiers)
    return run(args, deps)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
