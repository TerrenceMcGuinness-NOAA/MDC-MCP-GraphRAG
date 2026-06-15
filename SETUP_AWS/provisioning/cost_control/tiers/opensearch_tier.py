"""OpenSearch vector-DB tier (Task 9).

Primary path is **scale-down**: a manual snapshot is always taken first (a
safety net, R4.2), then ``update_domain_config`` shrinks the domain to a
single ``t3.small.search`` node; wake reverses to the production config. Both
transitions wait for ``Processing == false`` before returning. The
deep-sleep delete+restore path is stubbed behind a mode flag (documented, not
wired -- design Open Question 1).

The manual-snapshot step uses the injected ``OpenSearchSnapshotClient`` REST
protocol from ``snapshots`` (the ``_snapshot`` API is HTTP, not boto3). The
scale / describe calls use the boto3 ``opensearch`` client.

Requirements: 1.3, 3.2, 4.2.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from cost_control import snapshots
from cost_control.config import EnvironmentConfig
from cost_control.snapshots import OpenSearchSnapshotClient, make_snapshot_id
from cost_control.tiers import HIBERNATE, WAKE, PlannedAction, TierError, wait_until

#: The single-node Sleep_State cluster config (primary scale-down path).
SLEEP_CLUSTER_CONFIG: dict[str, Any] = {
    "InstanceType": "t3.small.search",
    "InstanceCount": 1,
    "DedicatedMasterEnabled": False,
    "ZoneAwarenessEnabled": False,
}

#: A representative production cluster config used when one is not supplied
#: (the orchestrator captures the live config into the manifest and passes it
#: back on wake).
DEFAULT_PRODUCTION_CLUSTER_CONFIG: dict[str, Any] = {
    "InstanceType": "r6g.large.search",
    "InstanceCount": 2,
    "DedicatedMasterEnabled": False,
    "ZoneAwarenessEnabled": True,
}

OPENSEARCH_PROCESSING_TIMEOUT_S: float = 3600.0
OPENSEARCH_POLL_INTERVAL_S: float = 30.0


class OpenSearchTier:
    """Sleep/wake control for the OpenSearch domain (scale-down primary)."""

    name = "opensearch"

    def __init__(
        self,
        config: EnvironmentConfig,
        opensearch_client: Any,
        *,
        snapshot_client: Optional[OpenSearchSnapshotClient] = None,
        repository: str = "",
        operation_id: str = "",
        audit: Any = None,
        production_cluster_config: Optional[dict[str, Any]] = None,
        sleep_cluster_config: Optional[dict[str, Any]] = None,
        doc_counts_fn: Optional[Callable[[], dict[str, int]]] = None,
        deep_sleep: bool = False,
        timeout_s: float = OPENSEARCH_PROCESSING_TIMEOUT_S,
        poll_interval_s: float = OPENSEARCH_POLL_INTERVAL_S,
        sleep_fn: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if not config.opensearch_domain_name:
            raise TierError("OpenSearchTier requires config.opensearch_domain_name")
        self._cfg = config
        self._os = opensearch_client
        self._snap = snapshot_client
        self._repository = repository
        self._op = operation_id
        self._audit = audit
        self._prod_cfg = production_cluster_config or DEFAULT_PRODUCTION_CLUSTER_CONFIG
        self._sleep_cfg = sleep_cluster_config or SLEEP_CLUSTER_CONFIG
        self._doc_counts_fn = doc_counts_fn
        self._deep_sleep = deep_sleep
        self._timeout_s = timeout_s
        self._poll_interval_s = poll_interval_s
        self._sleep = sleep_fn
        self._time = time_fn

    @property
    def domain_name(self) -> str:
        return self._cfg.opensearch_domain_name  # type: ignore[return-value]

    # -- helpers -----------------------------------------------------------

    def _domain_status(self) -> dict[str, Any]:
        resp = self._os.describe_domain(DomainName=self.domain_name)
        status = resp.get("DomainStatus")
        if not status:
            raise TierError(f"OpenSearch domain {self.domain_name} not found")
        return status

    def _cluster_config(self, status: dict[str, Any]) -> dict[str, Any]:
        return status.get("ClusterConfig", {})

    def _emit(self, event_type: str, **kwargs: Any) -> None:
        if self._audit is not None:
            self._audit.emit(event_type, tier=self.name, **kwargs)

    def _wait_not_processing(self) -> None:
        wait_until(
            poll=self._domain_status,
            predicate=lambda s: not s.get("Processing", False),
            what="opensearch domain processing",
            timeout_s=self._timeout_s,
            poll_interval_s=self._poll_interval_s,
            sleep_fn=self._sleep,
            time_fn=self._time,
        )

    # -- deep-sleep stub (NOT wired) ---------------------------------------

    def _deep_sleep_hibernate(self) -> list[PlannedAction]:
        """Deep-sleep delete+restore path -- deferred to a later wave."""
        raise NotImplementedError(
            "OpenSearch deep-sleep (delete + restore-from-snapshot) is "
            "deferred per design Open Question 1; use the scale-down path"
        )

    # -- Tier interface ----------------------------------------------------

    def is_asleep(self) -> bool:
        cfg = self._cluster_config(self._domain_status())
        return (
            cfg.get("InstanceType") == self._sleep_cfg["InstanceType"]
            and cfg.get("InstanceCount") == self._sleep_cfg["InstanceCount"]
        )

    def capture_manifest(self) -> dict[str, Any]:
        status = self._domain_status()
        return {
            "domain_name": self.domain_name,
            "cluster_config": self._cluster_config(status),
            "per_index_doc_counts": self._doc_counts_fn() if self._doc_counts_fn else {},
        }

    def plan(self, mode: str) -> list[PlannedAction]:
        if mode == HIBERNATE:
            return [
                PlannedAction(self.name, "create_snapshot",
                              "Manual OpenSearch snapshot (safety net)",
                              destructive=False, target=self.domain_name),
                PlannedAction(self.name, "update_domain_config",
                              "Scale down to single t3.small.search",
                              destructive=True, target=self.domain_name),
            ]
        return [
            PlannedAction(self.name, "update_domain_config",
                          "Scale up to production cluster config",
                          destructive=False, target=self.domain_name),
        ]

    def hibernate(self) -> list[PlannedAction]:
        if self._deep_sleep:
            return self._deep_sleep_hibernate()
        if self.is_asleep():
            self._emit("Tier_Skipped", state_before="scaled-down",
                       state_after="scaled-down")
            return []

        # Manual snapshot ALWAYS, and it MUST reach SUCCESS before scale-down.
        actions: list[PlannedAction] = []
        if self._snap is not None:
            snap_id = make_snapshot_id(self._cfg.environment_name, self._op, "os")
            resolved = snapshots.create_opensearch_snapshot(
                self._snap,
                repository=self._repository,
                snapshot_id=snap_id,
                sleep_fn=self._sleep,
                time_fn=self._time,
            )
            actions.append(PlannedAction(self.name, "create_snapshot",
                                         f"OpenSearch snapshot {resolved}",
                                         target=self.domain_name))
            self._emit("Snapshot_Created", snapshot_ids=[resolved],
                       aws_resource_arns=[self.domain_name])

        # Destructive scale-down.
        self._os.update_domain_config(
            DomainName=self.domain_name, ClusterConfig=self._sleep_cfg
        )
        self._emit("Resource_Scaled_Down", state_before="production",
                   state_after="sleep", aws_resource_arns=[self.domain_name])
        self._wait_not_processing()
        actions.append(PlannedAction(self.name, "update_domain_config",
                                     "Scaled down to single t3.small.search",
                                     destructive=True, target=self.domain_name))
        return actions

    def wake(self) -> list[PlannedAction]:
        if not self.is_asleep():
            self._emit("Tier_Skipped", state_before="production",
                       state_after="production")
            return []
        self._os.update_domain_config(
            DomainName=self.domain_name, ClusterConfig=self._prod_cfg
        )
        self._emit("Resource_Scaled_Up", state_before="sleep",
                   state_after="production", aws_resource_arns=[self.domain_name])
        self._wait_not_processing()
        return [
            PlannedAction(self.name, "update_domain_config",
                          "Scaled up to production cluster config",
                          target=self.domain_name),
        ]
