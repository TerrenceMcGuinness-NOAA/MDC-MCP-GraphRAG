"""Unit tests for cost_control.costs (Task 4.1) including Property 5.

Property 5 (cost-savings floor): while Sleep_State, the sum of Compute-tier
per-hour costs is at most 20% of the Active_Mode per-hour sum (>=80% savings).

Requirements: 5.1, 5.3, 5.4.
"""

from __future__ import annotations

import pytest

from cost_control.costs import (
    DEFAULT_COST_TABLE,
    SAVINGS_FLOOR,
    CostModel,
    ResourceCost,
)


def test_active_and_sleep_totals():
    m = CostModel()
    # 0.0832 + 0.348 + 0.80 + 0.045
    assert m.active_hourly_total() == pytest.approx(1.2762)
    # only opensearch residual
    assert m.sleep_hourly_total() == pytest.approx(0.036)


def test_property5_savings_floor_default_table():
    m = CostModel()
    # Sleep sum <= 20% of active sum.
    assert m.sleep_hourly_total() <= 0.20 * m.active_hourly_total()
    # Equivalent: savings fraction >= 80%.
    assert m.savings_fraction() >= SAVINGS_FLOOR
    assert m.meets_savings_floor() is True


def test_hourly_savings_and_rounding():
    m = CostModel()
    assert m.hourly_savings() == pytest.approx(1.2762 - 0.036)
    assert m.estimated_savings_usd_per_hour() == pytest.approx(1.24)


def test_zero_resource_edge_case_yields_zero():
    m = CostModel(table={})
    assert m.active_hourly_total() == 0.0
    assert m.sleep_hourly_total() == 0.0
    assert m.savings_fraction() == 0.0
    assert m.estimated_savings_usd_per_hour() == 0.0
    assert m.window_savings_usd(3600) == 0.0
    # Empty table does not meet the floor (no savings to claim).
    assert m.meets_savings_floor() is False


def test_window_savings_one_second_precision():
    m = CostModel()
    per_hour = m.hourly_savings()
    # One full hour.
    assert m.window_savings_usd(3600) == pytest.approx(round(per_hour, 2))
    # 1.5 hours.
    assert m.window_savings_usd(5400) == pytest.approx(round(per_hour * 1.5, 2))
    # One second resolves to a non-zero fraction (not floored to an hour).
    assert m.window_savings_usd(1) == pytest.approx(round(per_hour / 3600.0, 2))


def test_window_savings_nonpositive_duration():
    m = CostModel()
    assert m.window_savings_usd(0) == 0.0
    assert m.window_savings_usd(-100) == 0.0


def test_custom_table_below_floor_is_detected():
    # A table where sleep cost is 50% of active fails the floor.
    table = {
        "x": ResourceCost("x", active_usd_per_hour=1.0, sleep_usd_per_hour=0.5),
    }
    m = CostModel(table=table)
    assert m.savings_fraction() == pytest.approx(0.5)
    assert m.meets_savings_floor() is False


def test_default_table_is_not_mutated_by_instance():
    m = CostModel()
    m.table["ec2"] = ResourceCost("ec2", 9.9, 9.9)
    # Mutating the returned copy must not change the module-level default.
    assert DEFAULT_COST_TABLE["ec2"].active_usd_per_hour == pytest.approx(0.0832)
