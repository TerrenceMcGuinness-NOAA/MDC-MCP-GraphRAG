"""Integration test: full Work_Matrix dry-run walk.

Exercises the complete Work_Matrix lifecycle (init → next → start → done/skip)
without touching ChromaDB, Neo4j, or any embedding service. Validates:

1. Every stage is visited exactly the expected number of times:
   - shared-once stages: exactly 1 unit (regardless of tenant count).
   - tenant-scope stages: exactly 5 units (one per tenant in the catalog).
   - hybrid_local stages: exactly 5 units.
   - hybrid_external stages: exactly 1 unit.

2. Ordering constraints:
   - ``neo4j_drop_indexes`` is visited before any per-tenant graph stage.
   - ``neo4j_rebuild_indexes`` is visited after every per-tenant graph stage.
   - Per-tenant ``validate`` is visited last for each tenant.

3. Dependency gating:
   - ``neo4j_rebuild_indexes`` becomes actionable only when all per-tenant
     graph stages (fortran_graph, shell_graph, bridge, rocoto, expdir) are
     terminal for every tenant.

4. Terminal state:
   - After the walk, ``is-complete`` returns True.
   - Total unit count matches the expected 67 (60 tenant + 7 shared).

This test uses the real ``tenants.yaml`` and ``reingest_stages.yaml`` from
the repo (not mocks), making it a lightweight integration test of the stage
catalog + State_Manager interaction. Marked ``@pytest.mark.integration``
to exclude from fast unit test runs.

Run::

    cd mcp_server_python
    python3 -m pytest tests/integration/test_reingest_dry_run_walk.py -v

Spec: .kiro/specs/mpnet768-tenant-reingest-aug2026/ (Task 8.2).
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup (same pattern as sibling tests)
# ---------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).resolve().parent
_SERVER_ROOT = _TESTS_DIR.parents[1]
_SCRIPTS_DIR = _SERVER_ROOT / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SERVER_ROOT))

import reingest_state as rs  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_REPO_ROOT = _SERVER_ROOT.parent
_CATALOG_PATH = _SERVER_ROOT / "src" / "config" / "tenants.yaml"
_STAGES_PATH = _SCRIPTS_DIR / "reingest_stages.yaml"

# Expected tenant count from the current tenants.yaml (5 tenants).
EXPECTED_TENANTS = 5

# Per-tenant stages that appear once per tenant (12 stages × 5 tenants = 60).
PER_TENANT_STAGES = {
    "worktree", "reset", "workflow_docs_local", "code_with_context_local",
    "jjobs", "config", "shell_graph", "fortran_graph", "expdir", "rocoto",
    "bridge", "validate",
}

# Shared-once stages (7 total: one unit each).
SHARED_ONCE_STAGES = {
    "neo4j_drop_indexes", "workflow_docs_external", "pdf_sources",
    "ee2_standards", "community_summaries", "ci_test_cases",
    "neo4j_rebuild_indexes",
}

# Graph stages per tenant (gated by neo4j_rebuild_indexes).
GRAPH_STAGES = {"fortran_graph", "shell_graph", "bridge", "rocoto", "expdir"}

EXPECTED_TOTAL_UNITS = (len(PER_TENANT_STAGES) * EXPECTED_TENANTS) + len(SHARED_ONCE_STAGES)


@pytest.fixture
def state_root(tmp_path):
    """Provide a clean temporary state root."""
    return tmp_path


@pytest.fixture
def init_state(state_root):
    """Initialize the Work_Matrix and return the StateStore."""
    argv = [
        "--state-root", str(state_root),
        "--collection-version", "v9-0-0",
        "init",
        "--catalog", str(_CATALOG_PATH),
        "--stages", str(_STAGES_PATH),
        "--attempt-cap", "3",
        "--backend", "cots",
        "--embedding-profile", "mpnet768",
        "--mode-override", "full",
    ]
    rc = rs.main(argv)
    assert rc == 0, f"init failed with rc={rc}"

    store = rs.StateStore(
        state_root / ".reingest_state" / "v9-0-0"
    )
    assert store.exists()
    return store


# ---------------------------------------------------------------------------
# Test: full dry-run walk
# ---------------------------------------------------------------------------


class TestDryRunWalk:
    """Walk the entire Work_Matrix next→start→done and validate invariants."""

    def _walk(self, state_root: Path) -> list[dict]:
        """Walk the state machine until is-complete, recording visited units.

        Simulates the Ralph loop's one-unit-at-a-time execution without
        invoking any real scripts. Units with optional=true and no script
        (community_summaries) are skipped; everything else is marked done.

        Returns the ordered list of units as visited.
        """
        visited: list[dict] = []
        max_iters = 200  # safety bound

        for _ in range(max_iters):
            # Check completion.
            rc = rs.main([
                "--state-root", str(state_root),
                "--collection-version", "v9-0-0",
                "is-complete",
            ])
            if rc == 0:
                break

            # Get next unit.
            import io
            import contextlib
            stdout_capture = io.StringIO()
            with contextlib.redirect_stdout(stdout_capture):
                rs.main([
                    "--state-root", str(state_root),
                    "--collection-version", "v9-0-0",
                    "next", "--pretty",
                ])
            output = stdout_capture.getvalue()
            data = json.loads(output)
            unit = data.get("unit")

            if unit is None:
                # No actionable work — this shouldn't happen if the matrix is
                # well-formed and all deps are satisfiable.
                pytest.fail("next returned null but is-complete is not 0 — "
                            f"deadlock? visited {len(visited)} units so far")

            unit_id = unit["id"]

            # Start it.
            rc = rs.main([
                "--state-root", str(state_root),
                "--collection-version", "v9-0-0",
                "start", "--id", unit_id,
            ])
            assert rc == 0, f"start failed for {unit_id}"

            # Decide outcome: skip optional+no-script units, done everything else.
            if unit.get("optional") and unit.get("script") is None:
                rc = rs.main([
                    "--state-root", str(state_root),
                    "--collection-version", "v9-0-0",
                    "skip", "--id", unit_id,
                    "--reason", "dry-run: optional stage with no script",
                ])
                assert rc == 0, f"skip failed for {unit_id}"
            else:
                rc = rs.main([
                    "--state-root", str(state_root),
                    "--collection-version", "v9-0-0",
                    "done", "--id", unit_id,
                    "--metrics", json.dumps({"docs": 0, "nodes": 0, "probe": "dry_run"}),
                    "--manifest", str(state_root / "fake_manifest.json"),
                ])
                assert rc == 0, f"done failed for {unit_id}"

            visited.append(unit)
        else:
            pytest.fail(f"Walk did not complete after {max_iters} iterations; "
                        f"visited {len(visited)} units")

        return visited

    def test_full_walk_completes(self, init_state, state_root):
        """The walk reaches is-complete with all units terminal."""
        visited = self._walk(state_root)
        assert init_state.is_complete()

    def test_total_unit_count(self, init_state, state_root):
        """The Work_Matrix has exactly the expected number of units."""
        units = init_state.units()
        assert len(units) == EXPECTED_TOTAL_UNITS, (
            f"Expected {EXPECTED_TOTAL_UNITS} units, got {len(units)}"
        )

    def test_shared_once_visited_exactly_once(self, init_state, state_root):
        """Each shared-once stage produces exactly one unit in the walk."""
        visited = self._walk(state_root)
        stage_counts = Counter(u["stage"] for u in visited)

        for stage in SHARED_ONCE_STAGES:
            assert stage_counts[stage] == 1, (
                f"Shared-once stage '{stage}' visited {stage_counts[stage]} times, expected 1"
            )

    def test_per_tenant_visited_five_times(self, init_state, state_root):
        """Each per-tenant stage produces exactly 5 units (one per tenant)."""
        visited = self._walk(state_root)
        stage_counts = Counter(u["stage"] for u in visited)

        for stage in PER_TENANT_STAGES:
            assert stage_counts[stage] == EXPECTED_TENANTS, (
                f"Per-tenant stage '{stage}' visited {stage_counts[stage]} times, "
                f"expected {EXPECTED_TENANTS}"
            )

    def test_neo4j_drop_before_graph_stages(self, init_state, state_root):
        """neo4j_drop_indexes is visited before any per-tenant graph stage."""
        visited = self._walk(state_root)

        # Find the index of neo4j_drop_indexes.
        drop_idx = None
        for i, u in enumerate(visited):
            if u["stage"] == "neo4j_drop_indexes":
                drop_idx = i
                break
        assert drop_idx is not None, "neo4j_drop_indexes not found in walk"

        # All graph stages must come after.
        for i, u in enumerate(visited):
            if u["stage"] in GRAPH_STAGES:
                assert i > drop_idx, (
                    f"Graph stage '{u['stage']}' (unit {u['id']}) at index {i} "
                    f"came before neo4j_drop_indexes at index {drop_idx}"
                )

    def test_neo4j_rebuild_after_all_graph_stages(self, init_state, state_root):
        """neo4j_rebuild_indexes is visited after every per-tenant graph stage."""
        visited = self._walk(state_root)

        # Find the index of neo4j_rebuild_indexes.
        rebuild_idx = None
        for i, u in enumerate(visited):
            if u["stage"] == "neo4j_rebuild_indexes":
                rebuild_idx = i
                break
        assert rebuild_idx is not None, "neo4j_rebuild_indexes not found in walk"

        # All graph stages for every tenant must come before.
        for i, u in enumerate(visited):
            if u["stage"] in GRAPH_STAGES:
                assert i < rebuild_idx, (
                    f"Graph stage '{u['stage']}' (unit {u['id']}) at index {i} "
                    f"came after neo4j_rebuild_indexes at index {rebuild_idx}"
                )

    def test_validate_is_last_per_tenant(self, init_state, state_root):
        """The validate stage is the last stage visited for each tenant."""
        visited = self._walk(state_root)

        # Group by tenant.
        by_tenant: dict[str, list[tuple[int, dict]]] = {}
        for i, u in enumerate(visited):
            tid = u["tenant_id"]
            by_tenant.setdefault(tid, []).append((i, u))

        for tid, units in by_tenant.items():
            if tid == rs.GLOBAL_TENANT:
                continue  # global units don't have a validate stage
            # Find the validate unit for this tenant.
            validate_entries = [(i, u) for i, u in units if u["stage"] == "validate"]
            assert len(validate_entries) == 1, (
                f"Tenant '{tid}' has {len(validate_entries)} validate entries"
            )
            validate_idx = validate_entries[0][0]
            # All other stages for this tenant must come before.
            for idx, u in units:
                if u["stage"] != "validate":
                    assert idx < validate_idx, (
                        f"Tenant '{tid}': stage '{u['stage']}' at index {idx} "
                        f"came after validate at index {validate_idx}"
                    )

    def test_scope_fields_correct(self, init_state, state_root):
        """Verify scope/shared_once fields are set correctly on units."""
        units = init_state.units()

        for u in units:
            stage = u["stage"]
            if stage in SHARED_ONCE_STAGES:
                assert u["shared_once"] is True, (
                    f"Unit '{u['id']}' (shared-once stage) has shared_once=False"
                )
                assert u["scope"] in ("shared", "hybrid_external"), (
                    f"Unit '{u['id']}' scope={u['scope']}, expected shared/hybrid_external"
                )
                assert u["tenant_id"] == rs.GLOBAL_TENANT, (
                    f"Unit '{u['id']}' tenant_id={u['tenant_id']}, expected {rs.GLOBAL_TENANT}"
                )
            elif stage in PER_TENANT_STAGES:
                assert u["shared_once"] is False, (
                    f"Unit '{u['id']}' (per-tenant stage) has shared_once=True"
                )
                assert u["tenant_id"] != rs.GLOBAL_TENANT, (
                    f"Unit '{u['id']}' should have a real tenant_id, not {rs.GLOBAL_TENANT}"
                )

    def test_tenancy_precheck_fields(self, init_state, state_root):
        """Verify tenancy_precheck is populated correctly."""
        units = init_state.units()

        for u in units:
            precheck = u.get("tenancy_precheck")
            assert precheck is not None, f"Unit '{u['id']}' has no tenancy_precheck"

            if u["scope"] in ("shared", "hybrid_external") or u["tenant_id"] == rs.GLOBAL_TENANT:
                # Shared-once: expected_prefix="" and expected_tenant=None.
                assert precheck["expected_prefix"] == "", (
                    f"Unit '{u['id']}' (shared) has non-empty expected_prefix"
                )
                assert precheck["expected_tenant"] is None, (
                    f"Unit '{u['id']}' (shared) has non-None expected_tenant"
                )
            else:
                # Tenant-scope: expected_tenant matches unit's tenant_id.
                assert precheck["expected_tenant"] == u["tenant_id"], (
                    f"Unit '{u['id']}' expected_tenant={precheck['expected_tenant']}, "
                    f"but tenant_id={u['tenant_id']}"
                )

    def test_depends_on_all_tenants_gating(self, init_state, state_root):
        """neo4j_rebuild_indexes has depends_on_all_tenants=True."""
        units = init_state.units()
        rebuild_units = [u for u in units if u["stage"] == "neo4j_rebuild_indexes"]
        assert len(rebuild_units) == 1
        assert rebuild_units[0]["depends_on_all_tenants"] is True

    def test_no_deadlock_with_optional_skip(self, init_state, state_root):
        """The walk completes even when community_summaries is skipped.

        community_summaries is optional=true and has no script (Gap J).
        Skipping it must not block downstream stages.
        """
        visited = self._walk(state_root)
        skipped = [u for u in visited
                   if u["stage"] == "community_summaries"]
        # It should appear once (shared-once) and the walk should complete.
        assert len(skipped) == 1
        assert init_state.is_complete()
