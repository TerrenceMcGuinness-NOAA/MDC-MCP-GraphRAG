"""Wake validation probe (Task 12).

After every compute resource reports available, the probe confirms the
platform actually serves queries for every tenant in the catalog before wake
is declared successful. For each tenant it calls ``mcp_health_check`` and
``get_knowledge_base_status`` (via an injected client that fronts the live
AgentCore endpoint) and asserts:

* the default ``gw`` tenant reports branch ``develop`` with non-zero Neptune
  node and OpenSearch document counts (R12.2);
* every non-default tenant whose pre-sleep counts were non-zero reports its
  matching branch with non-zero counts (R12.3).

Transient failures (unreachable endpoint) are retried up to 5 times with a
30 s delay, inside the wake budget; assertion failures after the final attempt
route to ``Wake_Failed`` via :class:`WakeProbeError` (R12.4).

Requirements: 12.1, 12.2, 12.3, 12.4.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

DEFAULT_TENANT_ID: str = "gw"
DEFAULT_MAX_ATTEMPTS: int = 5
DEFAULT_RETRY_DELAY_S: float = 30.0


class ProbeClient(Protocol):
    """Client surface the probe drives against the AgentCore endpoint."""

    def health_check(self, tenant_id: str) -> dict[str, Any]:
        """Return ``mcp_health_check`` result for ``tenant_id``."""
        ...

    def kb_status(self, tenant_id: str) -> dict[str, Any]:
        """Return ``get_knowledge_base_status`` result for ``tenant_id``."""
        ...


class ProbeUnreachable(Exception):
    """Raised by a ProbeClient when the endpoint cannot be reached."""


class WakeProbeError(Exception):
    """The probe failed its assertions after all retries (-> Wake_Failed)."""

    def __init__(self, failures: list[str]) -> None:
        self.failures = list(failures)
        super().__init__("; ".join(failures) if failures else "wake probe failed")


@dataclass(frozen=True)
class TenantSpec:
    """A tenant the probe checks: id + expected branch."""

    tenant_id: str
    branch: str


@dataclass
class ProbeResult:
    """Outcome of one wake-probe run."""

    passed: bool
    failures: list[str] = field(default_factory=list)
    attempts: int = 1


def _counts_nonzero(kb: dict[str, Any]) -> bool:
    node_count = kb.get("neptune_node_count", kb.get("node_count", 0)) or 0
    doc_count = kb.get("opensearch_doc_count", kb.get("doc_count", 0)) or 0
    return node_count > 0 and doc_count > 0


def _assert_tenant(
    spec: TenantSpec,
    *,
    is_default: bool,
    pre_sleep_nonzero: bool,
    client: ProbeClient,
) -> list[str]:
    """Return a list of failure strings for one tenant (empty == pass).

    May raise :class:`ProbeUnreachable` (transient -> retried by the caller).
    """
    failures: list[str] = []

    # Non-default tenants whose pre-sleep counts were zero are not asserted
    # on (R12.3 only covers tenants that had data before sleep).
    if not is_default and not pre_sleep_nonzero:
        return failures

    health = client.health_check(spec.tenant_id)
    status = str(health.get("status", "")).upper()
    if status != "HEALTHY":
        failures.append(f"{spec.tenant_id}: health_check status={status or 'UNKNOWN'}")

    kb = client.kb_status(spec.tenant_id)
    reported_tenant = kb.get("tenant")
    reported_branch = kb.get("branch")
    if reported_tenant != spec.tenant_id:
        failures.append(
            f"{spec.tenant_id}: attribution tenant={reported_tenant!r} "
            f"(expected {spec.tenant_id!r})")
    if reported_branch != spec.branch:
        failures.append(
            f"{spec.tenant_id}: attribution branch={reported_branch!r} "
            f"(expected {spec.branch!r})")
    if not _counts_nonzero(kb):
        failures.append(f"{spec.tenant_id}: counts not both non-zero ({kb})")

    return failures


def run_wake_probe(
    client: ProbeClient,
    tenants: list[TenantSpec],
    *,
    pre_sleep_counts: Optional[dict[str, Any]] = None,
    default_tenant_id: str = DEFAULT_TENANT_ID,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
    sleep_fn: Callable[[float], None] = time.sleep,
    audit: Any = None,
) -> ProbeResult:
    """Run the per-tenant wake probe with retries.

    ``pre_sleep_counts`` maps ``tenant_id -> {"nodes": n, ...}`` from the
    Sleep_Started manifest; a non-default tenant is only asserted on when its
    pre-sleep counts were non-zero. Raises :class:`WakeProbeError` if the
    assertions still fail after ``max_attempts``.
    """
    pre_sleep_counts = pre_sleep_counts or {}

    def _pre_nonzero(tid: str) -> bool:
        counts = pre_sleep_counts.get(tid) or {}
        return any(bool(v) for v in counts.values())

    last_failures: list[str] = []
    for attempt in range(1, max_attempts + 1):
        try:
            failures: list[str] = []
            for spec in tenants:
                is_default = spec.tenant_id == default_tenant_id
                failures.extend(_assert_tenant(
                    spec,
                    is_default=is_default,
                    pre_sleep_nonzero=_pre_nonzero(spec.tenant_id),
                    client=client,
                ))
            if not failures:
                if audit is not None:
                    audit.emit("Wake_Probe_Passed", state_after="Wake_State")
                return ProbeResult(passed=True, failures=[], attempts=attempt)
            last_failures = failures
        except ProbeUnreachable as exc:
            last_failures = [f"probe unreachable: {exc}"]

        if attempt < max_attempts:
            sleep_fn(retry_delay_s)

    if audit is not None:
        audit.emit(
            "Wake_Failed",
            state_after="Sleep_State_Degraded",
            error={"code": "WakeProbeFailed", "message": "; ".join(last_failures)},
        )
    raise WakeProbeError(last_failures)
