"""Bug-fix tests for the ``workflow_info`` smoke probe missing-mount bug.

Spec: ``.kiro/specs/health-check-bugfixes/`` — Bug 2.

Covers Requirements 3.1–3.3 (``_smoke_workflow_info`` degrades to a
Skip_Result when the EFS workflow mount is absent or empty, and still
passes when populated) and the mandatory bug-condition exploration test
(R6.3, R6.4): a single test that raises ``RuntimeError`` on the unfixed
code and returns a SKIP (via :class:`SkipProbe`) without raising on the
fixed code.

The SKIP mechanism reused here is the existing ``github_tools`` path:
a probe raises :class:`SkipProbe`, which :pymeth:`SmokeQueryRegistry.
_run_single` translates into a ``ModuleResult(status="skip")``.

Uses real ``tmp_path`` directories (pyfakefs is not installed in this
environment; filesystem probes need real ``Path.exists``/``is_dir``
semantics, which ``tmp_path`` provides). No live AWS calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tools.smoke_queries import SkipProbe, _smoke_workflow_info

pytestmark = pytest.mark.unit


# ── populated mount → PASS (R3.3) ───────────────────────────────────────


async def test_workflow_info_pass_when_jobs_dir_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.3: a workflow_root with ``jobs/`` passes exactly as before."""
    (tmp_path / "jobs").mkdir()
    monkeypatch.setenv("MCP_WORKFLOW_ROOT", str(tmp_path))
    assert await _smoke_workflow_info(None, None) is True


async def test_workflow_info_pass_when_dev_jobs_dir_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.3: a workflow_root with ``dev/jobs/`` passes (fallback path)."""
    (tmp_path / "dev" / "jobs").mkdir(parents=True)
    monkeypatch.setenv("MCP_WORKFLOW_ROOT", str(tmp_path))
    assert await _smoke_workflow_info(None, None) is True


# ── absent / empty mount → SKIP (R3.1, R3.2) ────────────────────────────


async def test_workflow_info_skip_when_path_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.1: a non-existent workflow_root skips with a 'not mounted' reason."""
    missing = tmp_path / "does_not_exist"
    monkeypatch.setenv("MCP_WORKFLOW_ROOT", str(missing))
    with pytest.raises(SkipProbe) as exc:
        await _smoke_workflow_info(None, None)
    assert "not mounted" in str(exc.value)
    assert str(missing) in str(exc.value)


async def test_workflow_info_skip_when_empty_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.2: an existing-but-empty workflow_root skips with the documented
    'contains neither jobs/ nor dev/jobs/' reason."""
    monkeypatch.setenv("MCP_WORKFLOW_ROOT", str(tmp_path))
    with pytest.raises(SkipProbe) as exc:
        await _smoke_workflow_info(None, None)
    assert "contains neither jobs/ nor dev/jobs/" in str(exc.value)


# ── bug-condition exploration test (R6.3, R6.4) ─────────────────────────


async def test_bug2_exploration_missing_mount_skips_not_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug-condition exploration (Bug 2).

    On the UNFIXED code, ``_smoke_workflow_info`` raises ``RuntimeError``
    for a missing mount (the harness then reports FAIL). On the FIXED
    code it raises :class:`SkipProbe` (the harness reports SKIP).

    Asserting ``pytest.raises(SkipProbe)`` fails on the unfixed code —
    ``RuntimeError`` is not a ``SkipProbe`` — and passes on the fixed
    code. Both directions were demonstrated before commit (see CHANGELOG
    [8.36.1]).
    """
    missing = tmp_path / "mnt" / "workflow"
    monkeypatch.setenv("MCP_WORKFLOW_ROOT", str(missing))
    # On the unfixed code this raises RuntimeError, which is NOT a
    # SkipProbe, so pytest.raises(SkipProbe) fails there. On the fixed
    # code the probe raises SkipProbe and this passes.
    with pytest.raises(SkipProbe):
        await _smoke_workflow_info(None, None)
