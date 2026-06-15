"""Neptune graph-DB tier (Task 7).

Native stop/start preserves the full graph with zero data movement. On
hibernate a cluster snapshot is taken and confirmed ``available`` BEFORE the
``stop_db_cluster`` call (R4.1); on wake the cluster is started and waited to
``available``. The manifest captures per-tenant node/relationship counts so
the round-trip property (R3.1) can be verified after wake.

Requirements: 1.3, 3.1, 4.1.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from cost_control import snapshots
from cost_control.config import EnvironmentConfig
from cost_control.snapshots import make_snapshot_id
from cost_control.tiers import HIBERNATE, WAKE, PlannedAction, TierError, wait_until

#: Wait budget for the cluster to reach ``available`` on wake.
NEPTUNE_WAKE_TIMEOUT_S: float = 1800.0
NEPTUNE_POLL_INTERVAL_S: float = 30.0


class NeptuneTier:
    """Sleep/wake control for the Neptune cluster."""

    name = "neptune"

    def __init__(
        self,
        config: EnvironmentConfig,
        neptune_client: Any,
        *,
        operation_id: str = "",
        audit: Any = None,
        graph_counts_fn: Optional[Callable[[], dict[str, Any]]] = None,
        timeout_s: float = NEPTUNE_WAKE_TIMEOUT_S,
        poll_interval_s: float = NEPTUNE_POLL_INTERVAL_S,
        sleep_fn: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if not config.neptune_cluster_id:
            raise TierError("NeptuneTier requires config.neptune_cluster_id")
        self._cfg = config
        self._neptune = neptune_client
        self._op = operation_id
        self._audit = audit
        self._graph_counts_fn = graph_counts_fn
        self._timeout_s = timeout_s
        self._poll_interval_s = poll_interval_s
        self._sleep = sleep_fn
        self._time = time_fn

    @property
    def cluster_id(self) -> str:
        return self._cfg.neptune_cluster_id  # type: ignore[return-value]

    # -- helpers -----------------------------------------------------------

    def _status(self) -> str:
        resp = self._neptune.describe_db_clusters(DBClusterIdentifier=self.cluster_id)
        clusters = resp.get("DBClusters", [])
        if not clusters:
            raise TierError(f"Neptune cluster {self.cluster_id} not found")
        return clusters[0].get("Status", "unknown")

    def _emit(self, event_type: str, **kwargs: Any) -> None:
        if self._audit is not None:
            self._audit.emit(event_type, tier=self.name, **kwargs)

    # -- Tier interface ----------------------------------------------------

    def is_asleep(self) -> bool:
        return self._status() == "stopped"

    def capture_manifest(self) -> dict[str, Any]:
        counts = self._graph_counts_fn() if self._graph_counts_fn else {}
        return {
            "cluster_id": self.cluster_id,
            "status": self._status(),
            "per_tenant_counts": counts,
        }

    def plan(self, mode: str) -> list[PlannedAction]:
        if mode == HIBERNATE:
            return [
                PlannedAction(self.name, "create_db_cluster_snapshot",
                              "Snapshot Neptune cluster and wait available",
                              destructive=False, target=self.cluster_id),
                PlannedAction(self.name, "stop_db_cluster",
                              "Stop the Neptune cluster (graph preserved)",
                              destructive=True, target=self.cluster_id),
            ]
        return [
            PlannedAction(self.name, "start_db_cluster",
                          "Start the Neptune cluster and wait available",
                          destructive=False, target=self.cluster_id),
        ]

    def hibernate(self) -> list[PlannedAction]:
        if self.is_asleep():
            self._emit("Tier_Skipped", state_before="stopped", state_after="stopped")
            return []

        # Snapshot MUST reach 'available' before the destructive stop.
        snap_id = make_snapshot_id(self._cfg.environment_name, self._op, "neptune")
        resolved = snapshots.create_neptune_snapshot(
            self._neptune,
            cluster_id=self.cluster_id,
            snapshot_id=snap_id,
            environment_name=self._cfg.environment_name,
            sleep_fn=self._sleep,
            time_fn=self._time,
        )
        self._emit("Snapshot_Created", snapshot_ids=[resolved],
                   aws_resource_arns=[self.cluster_id])

        self._neptune.stop_db_cluster(DBClusterIdentifier=self.cluster_id)
        self._emit("Resource_Stopped", state_before="available",
                   state_after="stopping", aws_resource_arns=[self.cluster_id])
        return [
            PlannedAction(self.name, "create_db_cluster_snapshot",
                          f"Neptune snapshot {resolved}", target=self.cluster_id),
            PlannedAction(self.name, "stop_db_cluster",
                          "Stopped Neptune cluster", destructive=True,
                          target=self.cluster_id),
        ]

    def wake(self) -> list[PlannedAction]:
        if self._status() == "available":
            self._emit("Tier_Skipped", state_before="available", state_after="available")
            return []
        self._neptune.start_db_cluster(DBClusterIdentifier=self.cluster_id)
        self._emit("Resource_Started", state_before="stopped",
                   state_after="starting", aws_resource_arns=[self.cluster_id])
        wait_until(
            poll=self._status,
            predicate=lambda s: s == "available",
            what="neptune cluster available",
            timeout_s=self._timeout_s,
            poll_interval_s=self._poll_interval_s,
            sleep_fn=self._sleep,
            time_fn=self._time,
        )
        return [
            PlannedAction(self.name, "start_db_cluster",
                          "Started Neptune cluster", target=self.cluster_id),
        ]
