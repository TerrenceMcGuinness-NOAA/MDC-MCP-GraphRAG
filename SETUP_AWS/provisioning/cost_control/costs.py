"""Cost model for the Cost_Control_System (Task 4).

A per-resource USD/hr table for ``Active_Mode`` versus ``Sleep_State`` and the
savings arithmetic the audit records consume. The numbers are the design's
reference figures for the ``prod`` footprint (see the runbook cost table that
justifies the >=80% target, R5.2); they are deliberately conservative and
exclude storage GB-month and one-time request charges, per R5.1.

The model underpins Property 5 (cost-savings floor): the sum of Sleep_State
per-hour costs is at most 20% of the Active_Mode per-hour sum.

Requirements: 5.1 (>=80% reduction), 5.3 (Sleep_Completed savings/hr), 5.4
(Wake_Completed window savings).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceCost:
    """Per-hour USD cost of one Compute-tier resource in each mode.

    ``active_usd_per_hour`` is the billable hourly rate while serving;
    ``sleep_usd_per_hour`` is the residual hourly rate in ``Sleep_State``
    (0.0 when the resource is stopped or destroyed, a small residual when it
    is merely scaled down, e.g. OpenSearch to a single ``t3.small.search``).
    """

    name: str
    active_usd_per_hour: float
    sleep_usd_per_hour: float


# Reference USD/hr table (us-east-1, on-demand, design figures). EC2, Neptune
# and NAT drop to 0 in Sleep_State (stopped / deleted); OpenSearch scales down
# to a single small node rather than being deleted (primary path), leaving a
# small residual that still clears the 80% floor because the active domain is
# the dominant line item.
DEFAULT_COST_TABLE: dict[str, ResourceCost] = {
    "ec2": ResourceCost("ec2", active_usd_per_hour=0.0832, sleep_usd_per_hour=0.0),
    "neptune": ResourceCost("neptune", active_usd_per_hour=0.348, sleep_usd_per_hour=0.0),
    "opensearch": ResourceCost("opensearch", active_usd_per_hour=0.80, sleep_usd_per_hour=0.036),
    "nat": ResourceCost("nat", active_usd_per_hour=0.045, sleep_usd_per_hour=0.0),
}

#: Required minimum fractional savings during Sleep_State (R5.1).
SAVINGS_FLOOR: float = 0.80

#: Seconds per hour, for window-savings arithmetic at 1-second precision.
_SECONDS_PER_HOUR: float = 3600.0


class CostModel:
    """Aggregates a :class:`ResourceCost` table into savings figures."""

    def __init__(self, table: dict[str, ResourceCost] | None = None) -> None:
        self._table = dict(DEFAULT_COST_TABLE if table is None else table)

    @property
    def table(self) -> dict[str, ResourceCost]:
        return dict(self._table)

    def active_hourly_total(self) -> float:
        """Sum of ``active_usd_per_hour`` across all resources."""
        return sum(r.active_usd_per_hour for r in self._table.values())

    def sleep_hourly_total(self) -> float:
        """Sum of ``sleep_usd_per_hour`` across all resources."""
        return sum(r.sleep_usd_per_hour for r in self._table.values())

    def hourly_savings(self) -> float:
        """Active minus sleep per-hour total (USD/hr saved while asleep)."""
        return self.active_hourly_total() - self.sleep_hourly_total()

    def savings_fraction(self) -> float:
        """Fractional reduction in per-hour spend during Sleep_State.

        Returns ``0.0`` for the zero-resource edge case (empty table or an
        all-zero active total) so callers never divide by zero.
        """
        active = self.active_hourly_total()
        if active <= 0.0:
            return 0.0
        return self.hourly_savings() / active

    def meets_savings_floor(self, floor: float = SAVINGS_FLOOR) -> bool:
        """True when the savings fraction clears ``floor`` (Property 5)."""
        return self.savings_fraction() >= floor

    def estimated_savings_usd_per_hour(self) -> float:
        """Hourly savings rounded to cents, for the Sleep_Completed record."""
        return round(self.hourly_savings(), 2)

    def window_savings_usd(self, elapsed_seconds: float) -> float:
        """Total USD saved over a sleep window of ``elapsed_seconds``.

        Uses fractional hours at 1-second precision: ``savings/hr *
        seconds/3600``. Negative or zero durations yield ``0.00``. Rounded to
        cents for the Wake_Completed record (R5.4).
        """
        if elapsed_seconds <= 0.0:
            return 0.0
        hours = elapsed_seconds / _SECONDS_PER_HOUR
        return round(self.hourly_savings() * hours, 2)
