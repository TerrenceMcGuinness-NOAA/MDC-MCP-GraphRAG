"""Unit tests for cost_control.wake_probe (Task 12.1).

Mocked all-tenant responses via a fake ProbeClient: pass path; each fail mode
(wrong attribution, zero counts, unreachable) routes to WakeProbeError; the
non-default-zero-pre-sleep tenant is skipped; retry 5x30s behaviour.

Requirements: 12.2, 12.3, 12.4.
"""

from __future__ import annotations

import pytest

from cost_control.wake_probe import (
    ProbeUnreachable,
    TenantSpec,
    WakeProbeError,
    run_wake_probe,
)

TENANTS = [
    TenantSpec("gw", "develop"),
    TenantSpec("gw_v17", "dev/gfs.v17"),
]
PRE_SLEEP = {
    "gw": {"nodes": 148976, "rels": 4555408},
    "gw_v17": {"nodes": 80996, "rels": 1278331},
}


class _FakeProbe:
    """Configurable fake ProbeClient.

    ``health`` maps tenant -> status string; ``kb`` maps tenant -> kb dict.
    ``unreachable_for`` is a count of leading attempts that raise.
    """

    def __init__(self, health, kb, unreachable_times=0):
        self._health = health
        self._kb = kb
        self._unreachable = unreachable_times
        self.calls = 0

    def health_check(self, tenant_id):
        if self._unreachable > 0:
            self._unreachable -= 1
            raise ProbeUnreachable("endpoint warming up")
        self.calls += 1
        return {"status": self._health[tenant_id]}

    def kb_status(self, tenant_id):
        return self._kb[tenant_id]


def _kb(tenant, branch, nodes=1, docs=1):
    return {"tenant": tenant, "branch": branch,
            "neptune_node_count": nodes, "opensearch_doc_count": docs}


class _NoSleep:
    def __init__(self):
        self.count = 0

    def __call__(self, s):
        self.count += 1


def test_pass_path_all_tenants_healthy():
    client = _FakeProbe(
        health={"gw": "HEALTHY", "gw_v17": "HEALTHY"},
        kb={"gw": _kb("gw", "develop", 148976, 252000),
            "gw_v17": _kb("gw_v17", "dev/gfs.v17", 80996, 57000)},
    )
    result = run_wake_probe(client, TENANTS, pre_sleep_counts=PRE_SLEEP,
                            sleep_fn=_NoSleep())
    assert result.passed is True
    assert result.failures == []
    assert result.attempts == 1


def test_zero_counts_for_gw_fails():
    client = _FakeProbe(
        health={"gw": "HEALTHY", "gw_v17": "HEALTHY"},
        kb={"gw": _kb("gw", "develop", 0, 0),
            "gw_v17": _kb("gw_v17", "dev/gfs.v17", 1, 1)},
    )
    with pytest.raises(WakeProbeError) as exc:
        run_wake_probe(client, TENANTS, pre_sleep_counts=PRE_SLEEP,
                       max_attempts=2, sleep_fn=_NoSleep())
    assert any("gw" in f and "non-zero" in f for f in exc.value.failures)


def test_wrong_branch_attribution_fails():
    client = _FakeProbe(
        health={"gw": "HEALTHY", "gw_v17": "HEALTHY"},
        kb={"gw": _kb("gw", "develop", 1, 1),
            "gw_v17": _kb("gw_v17", "WRONG", 1, 1)},
    )
    with pytest.raises(WakeProbeError) as exc:
        run_wake_probe(client, TENANTS, pre_sleep_counts=PRE_SLEEP,
                       max_attempts=1, sleep_fn=_NoSleep())
    assert any("branch" in f for f in exc.value.failures)


def test_unhealthy_status_fails():
    client = _FakeProbe(
        health={"gw": "DEGRADED", "gw_v17": "HEALTHY"},
        kb={"gw": _kb("gw", "develop", 1, 1),
            "gw_v17": _kb("gw_v17", "dev/gfs.v17", 1, 1)},
    )
    with pytest.raises(WakeProbeError) as exc:
        run_wake_probe(client, TENANTS, pre_sleep_counts=PRE_SLEEP,
                       max_attempts=1, sleep_fn=_NoSleep())
    assert any("status" in f for f in exc.value.failures)


def test_nondefault_tenant_with_zero_presleep_is_skipped():
    # gw_v17 had zero pre-sleep counts -> not asserted on even if it reports
    # zero now. Only gw is checked and it passes.
    client = _FakeProbe(
        health={"gw": "HEALTHY"},
        kb={"gw": _kb("gw", "develop", 1, 1),
            "gw_v17": _kb("gw_v17", "dev/gfs.v17", 0, 0)},
    )
    pre = {"gw": {"nodes": 1}, "gw_v17": {"nodes": 0, "rels": 0}}
    result = run_wake_probe(client, TENANTS, pre_sleep_counts=pre,
                            sleep_fn=_NoSleep())
    assert result.passed is True


def test_unreachable_then_recovers_within_retries():
    client = _FakeProbe(
        health={"gw": "HEALTHY", "gw_v17": "HEALTHY"},
        kb={"gw": _kb("gw", "develop", 1, 1),
            "gw_v17": _kb("gw_v17", "dev/gfs.v17", 1, 1)},
        unreachable_times=2,  # first two health_check calls raise
    )
    sleeper = _NoSleep()
    result = run_wake_probe(client, TENANTS, pre_sleep_counts=PRE_SLEEP,
                            max_attempts=5, retry_delay_s=30, sleep_fn=sleeper)
    assert result.passed is True
    assert result.attempts >= 2
    assert sleeper.count >= 1  # waited between attempts


def test_unreachable_exhausts_retries():
    client = _FakeProbe(
        health={"gw": "HEALTHY"}, kb={"gw": _kb("gw", "develop", 1, 1)},
        unreachable_times=99,
    )
    sleeper = _NoSleep()
    with pytest.raises(WakeProbeError):
        run_wake_probe(client, [TenantSpec("gw", "develop")],
                       pre_sleep_counts={"gw": {"nodes": 1}},
                       max_attempts=5, retry_delay_s=30, sleep_fn=sleeper)
    # 5 attempts -> 4 inter-attempt sleeps.
    assert sleeper.count == 4
