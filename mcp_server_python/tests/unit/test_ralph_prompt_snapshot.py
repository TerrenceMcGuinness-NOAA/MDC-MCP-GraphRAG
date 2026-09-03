"""test_ralph_prompt_snapshot.py — Snapshot tests for ralph_reingest_prompt.md.

Asserts the Phase 81 Iteration_Prompt contains:
  - Shared_Once_Rule preamble section
  - Hybrid_Fan_Out preamble section
  - Tenancy precheck in step 3
  - reingest_validation.py invocation in step 5

Spec: .kiro/specs/mpnet768-tenant-reingest-aug2026/ (Task 5.2).
"""
from __future__ import annotations

from pathlib import Path

import pytest

# The prompt lives at <repo>/scripts/ralph_reingest_prompt.md
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROMPT_PATH = _REPO_ROOT / "scripts" / "ralph_reingest_prompt.md"


@pytest.fixture
def prompt_text() -> str:
    """Load the prompt text."""
    assert _PROMPT_PATH.is_file(), (
        f"Prompt file not found: {_PROMPT_PATH}"
    )
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Preamble section tests
# ---------------------------------------------------------------------------


class TestSharedOnceRulePreamble:
    """The prompt contains a Shared_Once_Rule section with required content."""

    def test_heading_exists(self, prompt_text: str) -> None:
        assert "## Shared_Once_Rule" in prompt_text

    def test_contains_unset_requirement(self, prompt_text: str) -> None:
        """Shared-once units require MCP_DEFAULT_TENANT unset."""
        assert "MCP_DEFAULT_TENANT" in prompt_text
        assert "unset" in prompt_text.lower()

    def test_contains_correct_example(self, prompt_text: str) -> None:
        """At least one correct shared-once invocation example."""
        assert "unset MCP_DEFAULT_TENANT" in prompt_text
        assert "ee2-standards-mpnet768-v9-0-0" in prompt_text

    def test_contains_wrong_example(self, prompt_text: str) -> None:
        """At least one WRONG example showing the violation."""
        assert "# WRONG" in prompt_text
        assert "gw_v17_ee2-standards-mpnet768-v9-0-0" in prompt_text

    def test_contains_tenant_contrast_example(self, prompt_text: str) -> None:
        """At least one correct tenant-scope example for contrast."""
        assert "MCP_DEFAULT_TENANT=gw_v17" in prompt_text
        assert "--tenant gw_v17" in prompt_text


class TestHybridFanOutPreamble:
    """The prompt contains a Hybrid_Fan_Out section with required content."""

    def test_heading_exists(self, prompt_text: str) -> None:
        assert "## Hybrid_Fan_Out" in prompt_text

    def test_documents_workflow_docs_split(self, prompt_text: str) -> None:
        """The fan-out table lists workflow_docs external and local sub-stages."""
        assert "workflow_docs_external" in prompt_text
        assert "workflow_docs_local" in prompt_text

    def test_documents_code_with_context_split(self, prompt_text: str) -> None:
        """The fan-out table lists code_with_context_local."""
        assert "code_with_context_local" in prompt_text

    def test_contains_correct_external_example(self, prompt_text: str) -> None:
        """Correct hybrid external example (shared-once, unprefixed)."""
        assert "workflow-docs-external-mpnet768-v9-0-0" in prompt_text

    def test_contains_correct_local_example(self, prompt_text: str) -> None:
        """Correct hybrid local example (per-tenant, prefixed)."""
        assert "gw_v17_workflow-docs-local-mpnet768-v9-0-0" in prompt_text

    def test_contains_wrong_hybrid_example(self, prompt_text: str) -> None:
        """At least one WRONG example showing the hybrid violation."""
        # The prompt should show what happens if local content is written without prefix
        assert "overwrite each other" in prompt_text.lower() or \
               "WRONG" in prompt_text


# ---------------------------------------------------------------------------
# Step 3 — Tenancy precheck
# ---------------------------------------------------------------------------


class TestStep3TenancyPrecheck:
    """Step 3 contains the tenancy precheck logic."""

    def test_step3_heading_mentions_tenancy(self, prompt_text: str) -> None:
        """Step 3 heading includes tenancy precheck."""
        assert "Tenancy precheck" in prompt_text

    def test_checks_shared_once_condition(self, prompt_text: str) -> None:
        """Step 3a checks unit.shared_once and unit.scope."""
        assert "unit.shared_once" in prompt_text
        assert "unit.scope" in prompt_text

    def test_checks_shared_once_unset(self, prompt_text: str) -> None:
        """Shared-once units require MCP_DEFAULT_TENANT unset."""
        # The check should echo MCP_DEFAULT_TENANT and look for UNSET
        assert "UNSET" in prompt_text

    def test_checks_tenant_match(self, prompt_text: str) -> None:
        """Tenant-scope units require MCP_DEFAULT_TENANT == tenant_id."""
        assert "unit.tenant_id" in prompt_text

    def test_tenancy_violation_failure_recorded(self, prompt_text: str) -> None:
        """A tenancy violation results in SM fail with tenancy_violation."""
        assert "tenancy_violation" in prompt_text

    def test_hybrid_external_treated_as_shared(self, prompt_text: str) -> None:
        """hybrid_external is grouped with shared-once for the precheck."""
        assert "hybrid_external" in prompt_text

    def test_hybrid_local_treated_as_tenant(self, prompt_text: str) -> None:
        """hybrid_local is grouped with tenant-scope for the precheck."""
        assert "hybrid_local" in prompt_text


# ---------------------------------------------------------------------------
# Step 5 — Validation_Probe invocation
# ---------------------------------------------------------------------------


class TestStep5ValidationProbe:
    """Step 5 invokes reingest_validation.py for validate-kind units."""

    def test_invokes_reingest_validation_py(self, prompt_text: str) -> None:
        """Step 5 calls reingest_validation.py."""
        assert "reingest_validation.py" in prompt_text

    def test_tenant_probe_invocation(self, prompt_text: str) -> None:
        """Per-tenant probe uses --tenant flag."""
        assert "--tenant <unit.tenant_id>" in prompt_text or \
               "--tenant" in prompt_text

    def test_global_probe_invocation(self, prompt_text: str) -> None:
        """Global probe uses --global flag."""
        assert "--global" in prompt_text

    def test_target_version_threaded(self, prompt_text: str) -> None:
        """The --target-version flag is threaded through."""
        assert "--target-version" in prompt_text
        assert "REINGEST_COLLECTION_VERSION" in prompt_text

    def test_writes_validation_json(self, prompt_text: str) -> None:
        """Output goes to .reingest_state/<ver>/validation/."""
        assert "validation/" in prompt_text
        assert ".json" in prompt_text

    def test_nonzero_exit_recorded_as_failure(self, prompt_text: str) -> None:
        """Non-zero exit from the probe is recorded as a failure."""
        assert "validation_probe_failed" in prompt_text


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


class TestStructuralInvariants:
    """The prompt's structure and terminal-state contract are preserved."""

    def test_one_unit_per_iteration_rule(self, prompt_text: str) -> None:
        """The one-unit-per-iteration directive is present."""
        assert "ONE unit per iteration" in prompt_text
        assert "Do exactly ONE unit of work" in prompt_text

    def test_seven_steps_preserved(self, prompt_text: str) -> None:
        """All 7 procedure steps exist."""
        assert "1. **Claim one unit.**" in prompt_text
        assert "2. **Mark it running.**" in prompt_text
        assert "3. **Tenancy precheck" in prompt_text
        assert "4. **Execute the unit" in prompt_text
        assert "5. **Validate**" in prompt_text
        assert "6. **Record the outcome:**" in prompt_text
        assert "7. **STOP.**" in prompt_text

    def test_hard_rules_section_exists(self, prompt_text: str) -> None:
        """Hard rules section still present."""
        assert "## Hard rules" in prompt_text

    def test_hard_rules_include_shared_once(self, prompt_text: str) -> None:
        """Hard rules now include the Shared_Once_Rule enforcement."""
        # Find the hard rules section
        hr_idx = prompt_text.index("## Hard rules")
        hard_rules = prompt_text[hr_idx:]
        assert "Shared_Once_Rule" in hard_rules

    def test_hard_rules_include_hybrid_fan_out(self, prompt_text: str) -> None:
        """Hard rules now include the Hybrid_Fan_Out enforcement."""
        hr_idx = prompt_text.index("## Hard rules")
        hard_rules = prompt_text[hr_idx:]
        assert "Hybrid_Fan_Out" in hard_rules

    def test_sm_shorthand_defined(self, prompt_text: str) -> None:
        """SM shorthand is still defined at the top."""
        assert "`SM` below is shorthand for:" in prompt_text

    def test_no_second_unit_directive(self, prompt_text: str) -> None:
        """The stop directive remains."""
        assert "Do NOT run `SM next` again" in prompt_text
        assert "Do NOT process another unit" in prompt_text
