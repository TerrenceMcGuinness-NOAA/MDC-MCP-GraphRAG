"""EC2 compute-host tier (Task 6).

Native stop/start halts the EC2 compute hour while preserving the EBS root
volume and the EFS mount config -- no data movement. Per R4.3 a fresh EBS
root snapshot is taken before stopping only when the latest existing snapshot
is older than the configured max age; the stop is never issued before that
snapshot reaches ``completed``.

Requirements: 1.3, 3.4, 4.3.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from cost_control import snapshots
from cost_control.config import EnvironmentConfig
from cost_control.snapshots import DEFAULT_EBS_MAX_AGE_S, make_snapshot_id
from cost_control.tiers import HIBERNATE, WAKE, PlannedAction, TierError, wait_until

#: Wait budget for the instance to reach ``running`` on wake.
EC2_WAKE_TIMEOUT_S: float = 600.0
EC2_POLL_INTERVAL_S: float = 15.0


class EC2Tier:
    """Sleep/wake control for the EC2 compute host."""

    name = "ec2"

    def __init__(
        self,
        config: EnvironmentConfig,
        ec2_client: Any,
        *,
        operation_id: str = "",
        audit: Any = None,
        snapshot_max_age_s: float = DEFAULT_EBS_MAX_AGE_S,
        now_epoch: Optional[float] = None,
        wait_for_running: bool = False,
        timeout_s: float = EC2_WAKE_TIMEOUT_S,
        poll_interval_s: float = EC2_POLL_INTERVAL_S,
        sleep_fn: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if not config.ec2_instance_id:
            raise TierError("EC2Tier requires config.ec2_instance_id")
        self._cfg = config
        self._ec2 = ec2_client
        self._op = operation_id
        self._audit = audit
        self._max_age_s = snapshot_max_age_s
        self._now_epoch = now_epoch
        self._wait_for_running = wait_for_running
        self._timeout_s = timeout_s
        self._poll_interval_s = poll_interval_s
        self._sleep = sleep_fn
        self._time = time_fn

    @property
    def instance_id(self) -> str:
        return self._cfg.ec2_instance_id  # type: ignore[return-value]

    # -- helpers -----------------------------------------------------------

    def _describe_instance(self) -> dict[str, Any]:
        resp = self._ec2.describe_instances(InstanceIds=[self.instance_id])
        reservations = resp.get("Reservations", [])
        if not reservations or not reservations[0].get("Instances"):
            raise TierError(f"EC2 instance {self.instance_id} not found")
        return reservations[0]["Instances"][0]

    def _root_volume_id(self, instance: dict[str, Any]) -> Optional[str]:
        root_name = instance.get("RootDeviceName")
        for mapping in instance.get("BlockDeviceMappings", []):
            ebs = mapping.get("Ebs", {})
            if mapping.get("DeviceName") == root_name and ebs.get("VolumeId"):
                return ebs["VolumeId"]
        # Fall back to the first EBS mapping if the root name did not match.
        for mapping in instance.get("BlockDeviceMappings", []):
            ebs = mapping.get("Ebs", {})
            if ebs.get("VolumeId"):
                return ebs["VolumeId"]
        return None

    def _state(self, instance: dict[str, Any]) -> str:
        return instance.get("State", {}).get("Name", "unknown")

    def _emit(self, event_type: str, **kwargs: Any) -> None:
        if self._audit is not None:
            self._audit.emit(event_type, tier=self.name, **kwargs)

    # -- Tier interface ----------------------------------------------------

    def is_asleep(self) -> bool:
        return self._state(self._describe_instance()) == "stopped"

    def capture_manifest(self) -> dict[str, Any]:
        instance = self._describe_instance()
        return {
            "instance_id": self.instance_id,
            "root_volume_id": self._root_volume_id(instance),
            "state": self._state(instance),
        }

    def plan(self, mode: str) -> list[PlannedAction]:
        if mode == HIBERNATE:
            return [
                PlannedAction(self.name, "create_snapshot",
                              "Snapshot EC2 root volume if latest is stale",
                              destructive=False, target=self.instance_id),
                PlannedAction(self.name, "stop_instances",
                              "Stop the EC2 compute host (EBS + EFS preserved)",
                              destructive=True, target=self.instance_id),
            ]
        return [
            PlannedAction(self.name, "start_instances",
                          "Start the EC2 compute host",
                          destructive=False, target=self.instance_id),
        ]

    def hibernate(self) -> list[PlannedAction]:
        if self.is_asleep():
            self._emit("Tier_Skipped", state_before="stopped", state_after="stopped")
            return []
        instance = self._describe_instance()
        volume_id = self._root_volume_id(instance)
        actions: list[PlannedAction] = []

        # Pre-stop EBS snapshot (only created if the latest is stale). This
        # MUST reach 'completed' before the destructive stop is issued.
        if volume_id:
            snap_id = make_snapshot_id(self._cfg.environment_name, self._op, "ec2_root_ebs")
            resolved = snapshots.ensure_ec2_root_snapshot(
                self._ec2,
                volume_id=volume_id,
                snapshot_id=snap_id,
                environment_name=self._cfg.environment_name,
                max_age_s=self._max_age_s,
                now_epoch=self._now_epoch,
                sleep_fn=self._sleep,
                time_fn=self._time,
            )
            actions.append(PlannedAction(self.name, "create_snapshot",
                                         f"EBS root snapshot {resolved}",
                                         destructive=False, target=volume_id))
            self._emit("Snapshot_Created", snapshot_ids=[resolved],
                       aws_resource_arns=[volume_id])

        # Destructive step: stop the instance.
        self._ec2.stop_instances(InstanceIds=[self.instance_id])
        actions.append(PlannedAction(self.name, "stop_instances",
                                     "Stopped EC2 compute host",
                                     destructive=True, target=self.instance_id))
        self._emit("Resource_Stopped", state_before="running", state_after="stopping",
                   aws_resource_arns=[self.instance_id])
        return actions

    def wake(self) -> list[PlannedAction]:
        if self._state(self._describe_instance()) == "running":
            self._emit("Tier_Skipped", state_before="running", state_after="running")
            return []
        self._ec2.start_instances(InstanceIds=[self.instance_id])
        actions = [PlannedAction(self.name, "start_instances",
                                 "Started EC2 compute host",
                                 destructive=False, target=self.instance_id)]
        self._emit("Resource_Started", state_before="stopped", state_after="pending",
                   aws_resource_arns=[self.instance_id])
        if self._wait_for_running:
            wait_until(
                poll=self._describe_instance,
                predicate=lambda inst: self._state(inst) == "running",
                what="ec2 instance running",
                timeout_s=self._timeout_s,
                poll_interval_s=self._poll_interval_s,
                sleep_fn=self._sleep,
                time_fn=self._time,
            )
        return actions
