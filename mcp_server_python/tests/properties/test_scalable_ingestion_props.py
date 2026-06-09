"""Property tests P1 + P2 for scalable-ingestion-pipeline.

Property 1: Parallelism Correctness — same parse results regardless of worker count.
Property 2: Timeout Safety — timed-out files marked correctly, fast files succeed,
            no corrupt/partial results for timed-out files.

Validates: R1.3, R1.4, R1.5 of scalable-ingestion-pipeline.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from _parallel_runner import FileResult, ParallelConfig, run_parallel_parse


# ── Synthetic parse functions (module-level, picklable) ──────────────

def _deterministic_parse(filepath: Path) -> dict:
    """Returns a deterministic result based on the filename."""
    return {
        "name": filepath.name,
        "size": len(filepath.name),
        "items": list(range(len(filepath.name) % 5)),
    }


def _sometimes_fails(filepath: Path) -> dict | None:
    """Fails for files with 'bad' in the name, succeeds otherwise."""
    if "bad" in filepath.name:
        raise ValueError(f"simulated failure: {filepath.name}")
    return {"name": filepath.name}


def _configurable_delay_parse(filepath: Path) -> dict | None:
    """Sleeps proportionally to the numeric part of the filename."""
    # Extract number from name like "file_3.f90" → 3
    name = filepath.stem
    parts = name.split("_")
    delay = 0.0
    for p in parts:
        try:
            delay = int(p) * 0.5  # 0.5s per unit
            break
        except ValueError:
            continue
    time.sleep(delay)
    return {"name": filepath.name, "delay": delay}


# ── Helpers ──────────────────────────────────────────────────────────

def _collect(gen):
    results = []
    try:
        while True:
            results.extend(next(gen))
    except StopIteration:
        pass
    return results


def _make_files(tmp_path, names):
    """Create files in tmp_path and return Path list."""
    paths = []
    for name in names:
        p = tmp_path / name
        p.touch()
        paths.append(p)
    return paths


# ── Property 1: Parallelism Correctness ─────────────────────────────

class TestProperty1ParallelismCorrectness:
    """For any file set and worker count N >= 1, running with N workers
    produces the same set of parse results as running with 1 worker."""

    @given(
        num_files=st.integers(min_value=1, max_value=30),
        workers=st.integers(min_value=2, max_value=4),
    )
    @settings(max_examples=50, deadline=30000)
    def test_same_results_any_worker_count(self, tmp_path_factory, num_files, workers):
        tmp_path = tmp_path_factory.mktemp("p1")
        files = _make_files(tmp_path, [f"file_{i}.f90" for i in range(num_files)])

        cfg_serial = ParallelConfig(workers=1, timeout=10, batch_size=100)
        cfg_parallel = ParallelConfig(workers=workers, timeout=10, batch_size=100)

        results_serial = _collect(run_parallel_parse(files, _deterministic_parse, cfg_serial))
        results_parallel = _collect(run_parallel_parse(files, _deterministic_parse, cfg_parallel))

        # Same number of results
        assert len(results_serial) == len(results_parallel) == num_files

        # Same set of (path, success, result) tuples
        def result_key(r: FileResult):
            return (r.path, r.success, str(r.result))

        set_serial = {result_key(r) for r in results_serial}
        set_parallel = {result_key(r) for r in results_parallel}
        assert set_serial == set_parallel

    @given(
        num_good=st.integers(min_value=0, max_value=10),
        num_bad=st.integers(min_value=0, max_value=10),
        workers=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=50, deadline=30000)
    def test_failure_set_consistent(self, tmp_path_factory, num_good, num_bad, workers):
        """Files that fail in serial also fail in parallel, and vice versa."""
        if num_good + num_bad == 0:
            return  # skip empty input
        tmp_path = tmp_path_factory.mktemp("p1_fail")
        good = _make_files(tmp_path, [f"good_{i}.f90" for i in range(num_good)])
        bad = _make_files(tmp_path, [f"bad_{i}.f90" for i in range(num_bad)])

        cfg = ParallelConfig(workers=workers, timeout=10, batch_size=100)
        results = _collect(run_parallel_parse(good + bad, _sometimes_fails, cfg))

        good_results = [r for r in results if "bad" not in Path(r.path).name]
        bad_results = [r for r in results if "bad" in Path(r.path).name]

        assert all(r.success for r in good_results)
        assert all(not r.success for r in bad_results)


# ── Property 2: Timeout Safety ───────────────────────────────────────

class TestProperty2TimeoutSafety:
    """For any file set with slow files exceeding the timeout:
    (a) Timed-out files are marked success=False with error="timeout"
    (b) Fast files succeed regardless
    (c) No partial/corrupt results for timed-out files"""

    def test_timeout_marking(self, tmp_path):
        """Files that exceed timeout are marked failed with error='timeout'."""
        # file_0 → 0s delay (fast), file_3 → 1.5s delay (exceeds 1s timeout)
        fast = _make_files(tmp_path, ["file_0.f90"])
        slow = _make_files(tmp_path, ["file_3.f90"])

        cfg = ParallelConfig(workers=2, timeout=1, batch_size=100)
        results = _collect(run_parallel_parse(fast + slow, _configurable_delay_parse, cfg))

        fast_results = [r for r in results if "file_0" in r.path]
        slow_results = [r for r in results if "file_3" in r.path]

        # (a) Slow files marked as timeout
        assert len(slow_results) == 1
        assert not slow_results[0].success
        assert slow_results[0].error == "timeout"

        # (b) Fast files succeed
        assert len(fast_results) == 1
        assert fast_results[0].success

        # (c) No partial results for timed-out files
        assert slow_results[0].result is None

    @given(
        num_fast=st.integers(min_value=1, max_value=8),
    )
    @settings(max_examples=20, deadline=30000)
    def test_fast_files_always_succeed(self, tmp_path_factory, num_fast):
        """All fast files succeed regardless of presence of slow files."""
        tmp_path = tmp_path_factory.mktemp("p2_fast")
        fast = _make_files(tmp_path, [f"file_0_{i}.f90" for i in range(num_fast)])
        slow = _make_files(tmp_path, ["file_5.f90"])  # 2.5s delay

        cfg = ParallelConfig(workers=2, timeout=1, batch_size=100)
        results = _collect(run_parallel_parse(fast + slow, _configurable_delay_parse, cfg))

        fast_results = [r for r in results if "file_0" in r.path]
        assert len(fast_results) == num_fast
        assert all(r.success for r in fast_results)
        assert all(r.result is not None for r in fast_results)

    def test_no_corrupt_results_on_timeout(self, tmp_path):
        """Timed-out files never produce partial parse results."""
        slow = _make_files(tmp_path, [f"file_{i+2}.f90" for i in range(5)])

        cfg = ParallelConfig(workers=3, timeout=1, batch_size=100)
        results = _collect(run_parallel_parse(slow, _configurable_delay_parse, cfg))

        # All should timeout (delay >= 1s with timeout=1)
        timed = [r for r in results if r.error == "timeout"]
        # Timed-out results must have result=None
        for r in timed:
            assert r.result is None
            assert not r.success
