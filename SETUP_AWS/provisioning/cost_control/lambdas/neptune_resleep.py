"""Neptune 7-day re-sleep guard Lambda (Task 8).

Neptune force-starts a stopped cluster after 7 days. This guard runs on a
daily EventBridge rule: if the State_File reports ``Sleep_State`` and the
cluster is found ``available`` (i.e. AWS auto-restarted it), it re-issues
``stop_db_cluster`` and emits a ``Resleep_Triggered`` audit record. In every
other case it is a no-op.

The handler builds its clients from environment variables wired by the CDK
Compute stack; the :func:`resleep` core is dependency-injected so it is unit
tested with botocore Stubbers and an in-memory audit logger.

Requirements: 3.1 (Neptune caveat), 9.4.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from cost_control.audit import AuditLogger
from cost_control.config import resolve_config
from cost_control.state_file import StateFile


def resleep(
    *,
    state_file: StateFile,
    neptune_client: Any,
    cluster_id: str,
    audit: AuditLogger,
) -> bool:
    """Re-stop the cluster iff asleep-in-state-file but found available.

    Returns ``True`` when a re-stop was issued, ``False`` for the no-op path.
    Missing/corrupt state files are treated as a no-op (the guard never
    creates state); the audit record carries the reason.
    """
    try:
        doc, _etag = state_file.read()
    except Exception as exc:  # MissingStateError / CorruptStateError
        audit.emit(
            "Resleep_Skipped",
            tier="neptune",
            error={"code": type(exc).__name__, "message": str(exc)},
        )
        return False

    current_state = doc.get("current_state")
    if current_state != "Sleep_State":
        audit.emit("Resleep_Skipped", tier="neptune",
                   state_before=current_state, state_after=current_state)
        return False

    resp = neptune_client.describe_db_clusters(DBClusterIdentifier=cluster_id)
    clusters = resp.get("DBClusters", [])
    status = clusters[0].get("Status") if clusters else "unknown"
    if status != "available":
        # Still stopped (or stopping) -- nothing to do.
        audit.emit("Resleep_Skipped", tier="neptune",
                   state_before="Sleep_State", state_after="Sleep_State")
        return False

    neptune_client.stop_db_cluster(DBClusterIdentifier=cluster_id)
    audit.emit(
        "Resleep_Triggered",
        tier="neptune",
        state_before="Sleep_State",
        state_after="Sleep_State",
        aws_resource_arns=[cluster_id],
    )
    return True


def handler(event: dict[str, Any] | None = None, context: Any = None) -> dict[str, Any]:
    """EventBridge entrypoint. Wires clients from env vars and calls resleep."""
    import boto3

    env_name = os.environ["COST_CONTROL_ENV"]
    config = resolve_config(env_name)
    cluster_id = config.neptune_cluster_id
    if not cluster_id:
        raise RuntimeError("neptune_cluster_id unresolved for re-sleep guard")

    session = boto3.Session(region_name=config.aws_region)
    s3 = session.client("s3")
    neptune = session.client("neptune")
    logs = session.client("logs")

    audit = AuditLogger(
        operation_id=f"resleep-{uuid.uuid4()}",
        caller_arn=os.environ.get("COST_CONTROL_INVOKER_ARN", "eventbridge-resleep"),
        environment_name=env_name,
        log_group=config.log_group,
        audit_bucket=config.audit_bucket,  # type: ignore[arg-type]
        audit_prefix=config.audit_prefix,
        logs_client=logs,
        s3_client=s3,
    )
    state_file = StateFile(s3, config.state_bucket, config.state_key)  # type: ignore[arg-type]
    try:
        restopped = resleep(
            state_file=state_file,
            neptune_client=neptune,
            cluster_id=cluster_id,
            audit=audit,
        )
    finally:
        audit.flush()
    return {"resleep_triggered": restopped}
