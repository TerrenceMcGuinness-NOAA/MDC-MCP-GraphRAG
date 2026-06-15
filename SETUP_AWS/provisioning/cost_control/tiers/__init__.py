"""Tier protocol and shared helpers for the Cost_Control_System (Task 6).

Each Compute-tier resource (EC2, Neptune, OpenSearch, AgentCore, NAT) is
modelled as a :class:`Tier`. The state machine (a later wave) iterates the
tiers in a fixed dependency order on hibernate and the reverse on wake; each
tier knows how to plan, hibernate, wake, report whether it is asleep, and
capture a manifest of the data it fronts.

A tier's ``hibernate()`` MUST take its pre-destruction snapshot (via the
``snapshots`` primitives) and confirm it reached a terminal success status
BEFORE issuing any destructive AWS call. Tiers fronting no data tier (NAT,
AgentCore) have no snapshot step.

ASCII-only console output per the repository convention.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, runtime_checkable

#: Mode tokens passed to :meth:`Tier.plan`.
HIBERNATE: str = "hibernate"
WAKE: str = "wake"


class TierError(Exception):
    """Base class for tier-level errors."""


class TierTimeout(TierError):
    """A tier wait predicate did not become true within the timeout."""

    def __init__(self, what: str, elapsed_seconds: float) -> None:
        self.what = what
        self.elapsed_seconds = elapsed_seconds
        super().__init__(f"{what} did not complete within {elapsed_seconds:.0f}s")


@dataclass(frozen=True)
class PlannedAction:
    """One step a tier would take (``plan``) or did take (``hibernate`` /
    ``wake``).

    ``destructive`` marks steps that stop / delete / scale-down a resource;
    the ``--dry-run`` plan renders these prominently and the audit trail flags
    them. ``target`` is the AWS resource id / ARN the action operates on.
    """

    tier: str
    action: str
    description: str
    destructive: bool = False
    target: Optional[str] = None


@runtime_checkable
class Tier(Protocol):
    """The interface every Compute-tier implementation satisfies."""

    name: str

    def plan(self, mode: str) -> list[PlannedAction]:
        """Return the ordered actions for ``mode`` without mutating anything."""
        ...

    def hibernate(self) -> list[PlannedAction]:
        """Stop / snapshot+destroy this tier; return the actions taken."""
        ...

    def wake(self) -> list[PlannedAction]:
        """Start / recreate this tier; return the actions taken."""
        ...

    def is_asleep(self) -> bool:
        """True when the tier is already in its Sleep_State shape."""
        ...

    def capture_manifest(self) -> dict[str, Any]:
        """Capture the tier's pre-sleep state for round-trip verification."""
        ...


def wait_until(
    *,
    poll: Callable[[], Any],
    predicate: Callable[[Any], bool],
    what: str,
    timeout_s: float,
    poll_interval_s: float,
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.monotonic,
    failure: Optional[Callable[[Any], bool]] = None,
) -> Any:
    """Poll ``poll`` until ``predicate`` is true, returning the last value.

    The first poll happens immediately. ``failure``, when supplied and true
    for a polled value, raises :class:`TierError` (terminal failure state).
    Raises :class:`TierTimeout` once the elapsed clock reaches ``timeout_s``.
    A deterministic ``time_fn`` / no-op ``sleep_fn`` make this testable.
    """
    start = time_fn()
    while True:
        value = poll()
        if predicate(value):
            return value
        if failure is not None and failure(value):
            raise TierError(f"{what} entered a terminal failure state: {value!r}")
        if time_fn() - start >= timeout_s:
            raise TierTimeout(what, time_fn() - start)
        sleep_fn(poll_interval_s)
