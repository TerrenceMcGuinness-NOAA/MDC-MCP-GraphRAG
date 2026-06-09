"""Unit tests for _parallel_runner.py.

Validates: R1.1, R1.3, R1.4, R1.5, R1.6 of scalable-ingestion-pipeline.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from _parallel_runner import FileResult, ParallelConfig, ParallelStats, run_parallel_parse


# ── Synthetic parse functions (module-level, picklable) ──────────────

def _fast_parse(filepath: Path) -> dict:
    """Always succeeds instantly."""
    return {"name": filepath.name, "items": [1, 2, 3]}


def _slow_parse(filepath: Path) -> dict:
    """Sleeps 3 seconds (exceeds short timeout in tests)."""
    time.sleep(3)
    return {"name": filepath.name}


def _failing_parse(filepath: Path) -> dict:
    """Always raises."""
    raise ValueError(f"parse error on {filepath}")


def _none_parse(filepath: Path):
    """Returns None (simulates unparseable file)."""
    return None


def _mixed_parse(filepath: Path) -> dict | None:
    """Succeeds for .f90, fails for .bad, slow for .slow."""
    if filepath.suffix == ".bad":
        raise RuntimeError("bad file")
    if filepath.suffix == ".slow":
        time.sleep(3)
    return {"name": filepath.name}


# ── Helpers ──────────────────────────────────────────────────────────

def _collect_results(gen):
    """Exhaust a generator and collect all batches into a flat list."""
    results = []
    try:
        while True:
            batch = next(gen)
            results.extend(batch)
    except StopIteration:
        pass
    return results


# ── Tests ────────────────────────────────────────────────────────────

class TestParallelConfig:
    def test_defaults(self):
        cfg = ParallelConfig()
        assert cfg.workers >= 1
        assert cfg.timeout == 120
        assert cfg.progress_interval == 50
        assert cfg.batch_size == 50

    def test_custom(self):
        cfg = ParallelConfig(workers=2, timeout=30, progress_interval=10, batch_size=5)
        assert cfg.workers == 2
        assert cfg.timeout == 30


class TestRunParallelParseSerial:
    """Tests with workers=1 (serial fallback)."""

    def test_empty_file_list(self):
        cfg = ParallelConfig(workers=1)
        gen = run_parallel_parse([], _fast_parse, cfg)
        results = _collect_results(gen)
        assert results == []

    def test_all_succeed(self, tmp_path):
        files = [tmp_path / f"file{i}.f90" for i in range(5)]
        for f in files:
            f.touch()
        cfg = ParallelConfig(workers=1, batch_size=10)
        gen = run_parallel_parse(files, _fast_parse, cfg)
        results = _collect_results(gen)
        assert len(results) == 5
        assert all(r.success for r in results)
        assert all(r.result is not None for r in results)

    def test_all_fail(self, tmp_path):
        files = [tmp_path / f"file{i}.f90" for i in range(3)]
        for f in files:
            f.touch()
        cfg = ParallelConfig(workers=1, batch_size=10)
        gen = run_parallel_parse(files, _failing_parse, cfg)
        results = _collect_results(gen)
        assert len(results) == 3
        assert all(not r.success for r in results)
        assert all("parse error" in r.error for r in results)

    def test_none_result_counts_as_failure(self, tmp_path):
        files = [tmp_path / "file.f90"]
        files[0].touch()
        cfg = ParallelConfig(workers=1, batch_size=10)
        gen = run_parallel_parse(files, _none_parse, cfg)
        results = _collect_results(gen)
        assert len(results) == 1
        assert not results[0].success
        assert "None" in results[0].error

    def test_batching(self, tmp_path):
        files = [tmp_path / f"file{i}.f90" for i in range(12)]
        for f in files:
            f.touch()
        cfg = ParallelConfig(workers=1, batch_size=5)
        gen = run_parallel_parse(files, _fast_parse, cfg)
        batches = []
        try:
            while True:
                batches.append(next(gen))
        except StopIteration:
            pass
        # 12 files / batch_size=5 → 3 batches (5, 5, 2)
        assert len(batches) == 3
        assert len(batches[0]) == 5
        assert len(batches[1]) == 5
        assert len(batches[2]) == 2

    def test_elapsed_tracked(self, tmp_path):
        files = [tmp_path / "file.f90"]
        files[0].touch()
        cfg = ParallelConfig(workers=1, batch_size=10)
        gen = run_parallel_parse(files, _fast_parse, cfg)
        results = _collect_results(gen)
        assert results[0].elapsed >= 0.0


class TestRunParallelParseParallel:
    """Tests with workers > 1."""

    def test_all_succeed_parallel(self, tmp_path):
        files = [tmp_path / f"file{i}.f90" for i in range(8)]
        for f in files:
            f.touch()
        cfg = ParallelConfig(workers=2, timeout=10, batch_size=10)
        gen = run_parallel_parse(files, _fast_parse, cfg)
        results = _collect_results(gen)
        assert len(results) == 8
        assert all(r.success for r in results)

    def test_timeout_marks_failure(self, tmp_path):
        files = [tmp_path / f"file{i}.f90" for i in range(3)]
        for f in files:
            f.touch()
        # timeout=1 but _slow_parse sleeps 3s
        cfg = ParallelConfig(workers=2, timeout=1, batch_size=10)
        gen = run_parallel_parse(files, _slow_parse, cfg)
        results = _collect_results(gen)
        assert len(results) == 3
        assert all(not r.success for r in results)
        assert all(r.error == "timeout" for r in results)

    def test_fast_files_succeed_despite_slow(self, tmp_path):
        """Fast files succeed even when other files timeout."""
        fast = [tmp_path / f"fast{i}.f90" for i in range(3)]
        slow = [tmp_path / "slow0.slow"]
        for f in fast + slow:
            f.touch()
        cfg = ParallelConfig(workers=2, timeout=1, batch_size=10)
        gen = run_parallel_parse(fast + slow, _mixed_parse, cfg)
        results = _collect_results(gen)
        fast_results = [r for r in results if ".f90" in r.path]
        slow_results = [r for r in results if ".slow" in r.path]
        assert all(r.success for r in fast_results)
        assert all(not r.success for r in slow_results)

    def test_exception_marks_failure(self, tmp_path):
        files = [tmp_path / f"file{i}.bad" for i in range(3)]
        for f in files:
            f.touch()
        cfg = ParallelConfig(workers=2, timeout=10, batch_size=10)
        gen = run_parallel_parse(files, _mixed_parse, cfg)
        results = _collect_results(gen)
        assert all(not r.success for r in results)
        assert all("bad file" in r.error for r in results)


class TestParallelismCorrectness:
    """Workers=1 and workers=N produce the same set of results (P1)."""

    def test_same_results_serial_vs_parallel(self, tmp_path):
        files = [tmp_path / f"file{i}.f90" for i in range(10)]
        for f in files:
            f.touch()

        cfg1 = ParallelConfig(workers=1, timeout=10, batch_size=20)
        cfg2 = ParallelConfig(workers=3, timeout=10, batch_size=20)

        results1 = _collect_results(run_parallel_parse(files, _fast_parse, cfg1))
        results2 = _collect_results(run_parallel_parse(files, _fast_parse, cfg2))

        # Same number of results
        assert len(results1) == len(results2)
        # Same paths and success status
        set1 = {(r.path, r.success) for r in results1}
        set2 = {(r.path, r.success) for r in results2}
        assert set1 == set2


class TestProgressOutput:
    """Progress lines emitted at the configured interval."""

    def test_progress_printed(self, tmp_path, capsys):
        files = [tmp_path / f"file{i}.f90" for i in range(100)]
        for f in files:
            f.touch()
        cfg = ParallelConfig(workers=1, progress_interval=25, batch_size=200)
        gen = run_parallel_parse(files, _fast_parse, cfg, label="test")
        _collect_results(gen)
        captured = capsys.readouterr()
        # Should have progress at 25, 50, 75, 100
        assert captured.out.count("[test]") == 4
