"""Property-based tests for omd-tenants-2-v17-pilot.

Feature: omd-tenants-2-v17-pilot
Tests: P4 (Attribution headers — tenant + branch)
"""
from __future__ import annotations

from dataclasses import dataclass

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Hypothesis settings profile
# ---------------------------------------------------------------------------
settings.register_profile(
    "v17",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("v17")

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_LIFECYCLES = ["experimental", "staging", "production", "merged", "stale"]


@st.composite
def tenant_with_branch_strategy(draw):
    """Generate a minimal Tenant-like object with a branch field."""
    tenant_id = draw(st.from_regex(r"[a-z][a-z0-9_]{1,15}", fullmatch=True))
    branch = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P")),
        min_size=1, max_size=40,
    ).filter(lambda s: "\n" not in s and "\r" not in s))
    lifecycle = draw(st.sampled_from(_LIFECYCLES))
    return _FakeTenant(tenant_id=tenant_id, branch=branch, lifecycle=lifecycle)


@st.composite
def tenant_with_empty_branch_strategy(draw):
    """Generate a Tenant-like object with an empty branch field."""
    tenant_id = draw(st.from_regex(r"[a-z][a-z0-9_]{1,15}", fullmatch=True))
    lifecycle = draw(st.sampled_from(_LIFECYCLES))
    return _FakeTenant(tenant_id=tenant_id, branch="", lifecycle=lifecycle)


@dataclass(frozen=True)
class _FakeTenant:
    tenant_id: str
    branch: str
    lifecycle: str


# ---------------------------------------------------------------------------
# Property 4: Attribution headers (tenant + branch)
# Feature: omd-tenants-2-v17-pilot, Property 4: Attribution headers (tenant + branch)
# ---------------------------------------------------------------------------


class TestP4AttributionHeaders:
    """Property 4: Attribution headers (tenant + branch).

    For any tenant T and any non-empty body b:
    - attribute(b, T) first line is *Tenant: <T.tenant_id>* (with [STALE] if stale)
    - When T.branch is non-empty, second line is *Branch: <T.branch>*
    - Then a blank line, then body b unchanged
    - When T.branch is empty, no *Branch:* line is emitted
    """

    @given(
        tenant=tenant_with_branch_strategy(),
        body=st.text(min_size=1, max_size=200),
    )
    def test_branch_line_present_when_branch_nonempty(self, tenant, body):
        """Non-empty branch → *Branch: <branch>* line between tenant and body."""
        from src.tools._attribution import attribute

        result = attribute(body, tenant)
        lines = result.split("\n")

        # First line: *Tenant: <id>* with optional [STALE]
        stale_suffix = " [STALE]" if tenant.lifecycle == "stale" else ""
        expected_tenant_line = f"*Tenant: {tenant.tenant_id}*{stale_suffix}"
        assert lines[0] == expected_tenant_line

        # Second line: *Branch: <branch>*
        expected_branch_line = f"*Branch: {tenant.branch}*"
        assert lines[1] == expected_branch_line

        # Third line: blank separator
        assert lines[2] == ""

        # Remainder: body unchanged
        remainder = "\n".join(lines[3:])
        assert remainder == body

    @given(
        tenant=tenant_with_empty_branch_strategy(),
        body=st.text(min_size=1, max_size=200),
    )
    def test_no_branch_line_when_branch_empty(self, tenant, body):
        """Empty branch → no *Branch:* line; just tenant + blank + body."""
        from src.tools._attribution import attribute

        result = attribute(body, tenant)
        lines = result.split("\n")

        stale_suffix = " [STALE]" if tenant.lifecycle == "stale" else ""
        expected_tenant_line = f"*Tenant: {tenant.tenant_id}*{stale_suffix}"
        assert lines[0] == expected_tenant_line

        # Second line: blank separator (no branch line)
        assert lines[1] == ""

        # Remainder: body unchanged
        remainder = "\n".join(lines[2:])
        assert remainder == body

        # No *Branch:* anywhere
        assert "*Branch:" not in result
