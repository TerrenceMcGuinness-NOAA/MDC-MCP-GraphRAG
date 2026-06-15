"""NAT Gateway tier (Task 10).

NAT has no stop and costs a flat hourly rate plus per-GB processing. On
hibernate the NAT Gateway is deleted and its Elastic IP allocations released
(safe because every private-subnet resource is also stopped and needs no
egress). Wake is a no-op here: the CDK Compute deploy recreates the NAT
Gateway (it is declared in the Compute stack). The manifest records the NAT id,
subnet, and EIP allocation ids so drift detection and the CDK recreate can
correlate.

NAT fronts no data tier, so there is no snapshot step.

Requirements: 1.3, 3.x.
"""

from __future__ import annotations

from typing import Any, Optional

from cost_control.config import EnvironmentConfig
from cost_control.tiers import PlannedAction, TierError

#: NAT gateway states that mean "already gone" for idempotency.
_GONE_STATES = frozenset({"deleted", "deleting"})


class NatTier:
    """Sleep/wake control for the NAT Gateway (delete on sleep)."""

    name = "nat"

    def __init__(
        self,
        config: EnvironmentConfig,
        ec2_client: Any,
        *,
        operation_id: str = "",
        audit: Any = None,
    ) -> None:
        self._cfg = config
        self._ec2 = ec2_client
        self._op = operation_id
        self._audit = audit

    @property
    def nat_gateway_id(self) -> Optional[str]:
        return self._cfg.nat_gateway_id

    # -- helpers -----------------------------------------------------------

    def _describe(self) -> Optional[dict[str, Any]]:
        """Return the NAT gateway dict, or None if absent/deleted."""
        if not self.nat_gateway_id:
            return None
        resp = self._ec2.describe_nat_gateways(
            NatGatewayIds=[self.nat_gateway_id]
        )
        gateways = resp.get("NatGateways", [])
        return gateways[0] if gateways else None

    def _allocation_ids(self, gateway: dict[str, Any]) -> list[str]:
        return [
            addr["AllocationId"]
            for addr in gateway.get("NatGatewayAddresses", [])
            if addr.get("AllocationId")
        ]

    def _emit(self, event_type: str, **kwargs: Any) -> None:
        if self._audit is not None:
            self._audit.emit(event_type, tier=self.name, **kwargs)

    # -- Tier interface ----------------------------------------------------

    def is_asleep(self) -> bool:
        gateway = self._describe()
        if gateway is None:
            return True
        return gateway.get("State") in _GONE_STATES

    def capture_manifest(self) -> dict[str, Any]:
        gateway = self._describe()
        if gateway is None:
            return {
                "nat_gateway_id": self.nat_gateway_id,
                "subnet_id": None,
                "allocation_ids": [],
                "state": "deleted",
            }
        return {
            "nat_gateway_id": gateway.get("NatGatewayId", self.nat_gateway_id),
            "subnet_id": gateway.get("SubnetId"),
            "allocation_ids": self._allocation_ids(gateway),
            "state": gateway.get("State"),
        }

    def plan(self, mode: str) -> list[PlannedAction]:
        if mode == "hibernate":
            return [
                PlannedAction(self.name, "delete_nat_gateway",
                              "Delete the NAT Gateway", destructive=True,
                              target=self.nat_gateway_id),
                PlannedAction(self.name, "release_address",
                              "Release the NAT Elastic IP allocation(s)",
                              destructive=True, target=self.nat_gateway_id),
            ]
        return [
            PlannedAction(self.name, "noop",
                          "NAT Gateway is recreated by the CDK Compute deploy",
                          destructive=False, target=self.nat_gateway_id),
        ]

    def hibernate(self) -> list[PlannedAction]:
        gateway = self._describe()
        if gateway is None or gateway.get("State") in _GONE_STATES:
            self._emit("Tier_Skipped", state_before="deleted", state_after="deleted")
            return []

        nat_id = gateway["NatGatewayId"]
        allocation_ids = self._allocation_ids(gateway)
        actions: list[PlannedAction] = []

        self._ec2.delete_nat_gateway(NatGatewayId=nat_id)
        self._emit("Resource_Deleted", aws_resource_arns=[nat_id])
        actions.append(PlannedAction(self.name, "delete_nat_gateway",
                                     f"Deleted NAT Gateway {nat_id}",
                                     destructive=True, target=nat_id))

        for alloc in allocation_ids:
            self._ec2.release_address(AllocationId=alloc)
            self._emit("Resource_Deleted", aws_resource_arns=[alloc])
            actions.append(PlannedAction(self.name, "release_address",
                                         f"Released EIP {alloc}",
                                         destructive=True, target=alloc))
        return actions

    def wake(self) -> list[PlannedAction]:
        # No-op: the CDK Compute deploy recreates the NAT Gateway.
        self._emit("Tier_Skipped", state_before="recreated-by-cdk",
                   state_after="recreated-by-cdk")
        return []
