"""Parallel file-parsing runner for ingestion scripts.

Uses ProcessPoolExecutor to distribute file parsing across CPU cores.
Each worker gets its own parser instance (no shared mutable state),
solving fparser2 memory leaks — when a worker dies, all accumulated
AST state dies with it.

Yields batches of FileResult so callers can process results
incrementally without holding all parse output in memory at once.

Implements: R1.1, R1.3, R1.4, R1.5, R1.6 of scalable-ingestion-pipeline.
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Generator


@dataclass
class ParallelConfig:
    """Configuration for parallel parsing."""

    workers: int = max(1, (os.cpu_count() or 2) - 1)
    timeout: int = 120
    progress_interval: int = 50
    batch_size: int = 50


@dataclass
class FileResult:
    """Result of parsing a single file."""

    path: str
    success: bool
    result: Any | None = None
    elapsed: float = 0.0
    error: str | None = None


@dataclass
class ParallelStats:
    """Aggregate statistics for a parallel parse run."""

    total: int = 0
    parsed: int = 0
    failed: int = 0
    timed_out: int = 0
    total_elapsed: float = 0.0


def run_parallel_parse(
    files: list[Path],
    parse_fn: Callable,
    config: ParallelConfig,
    label: str = "parsing",
) -> Generator[list[FileResult], None, ParallelStats]:
    """Parse files in parallel, yielding batches of FileResult.

    Parameters
    ----------
    files : list[Path]
        Files to parse.
    parse_fn : Callable
        Module-level function (must be picklable). Receives a single Path
        argument and returns a parse result or None.
    config : ParallelConfig
        Worker count, timeout, progress interval, batch size.
    label : str
        Label for progress lines.

    Yields
    ------
    list[FileResult]
        Batches of results (batch_size items each, last batch may be smaller).

    Returns
    -------
    ParallelStats
        Final aggregate statistics (accessible via generator .value after
        StopIteration, but callers typically track their own counts).
    """
    stats = ParallelStats(total=len(files))
    t_start = time.time()

    if not files:
        return stats

    batch: list[FileResult] = []

    if config.workers <= 1:
        # Serial fallback — identical behavior to old code.
        for i, filepath in enumerate(files):
            t0 = time.time()
            try:
                result = parse_fn(filepath)
                elapsed = time.time() - t0
                if result is not None:
                    fr = FileResult(path=str(filepath), success=True,
                                    result=result, elapsed=elapsed)
                    stats.parsed += 1
                else:
                    fr = FileResult(path=str(filepath), success=False,
                                    elapsed=elapsed, error="parse returned None")
                    stats.failed += 1
            except Exception as e:
                elapsed = time.time() - t0
                fr = FileResult(path=str(filepath), success=False,
                                elapsed=elapsed, error=str(e))
                stats.failed += 1

            batch.append(fr)

            done = i + 1
            if done % config.progress_interval == 0:
                _print_progress(done, stats.total, stats.parsed,
                                stats.failed, t_start, label)

            if len(batch) >= config.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch

        stats.total_elapsed = time.time() - t_start
        return stats

    # Parallel mode — ProcessPoolExecutor.
    with ProcessPoolExecutor(max_workers=config.workers) as executor:
        # Submit all futures at once for maximum throughput.
        futures = [(filepath, executor.submit(parse_fn, filepath))
                   for filepath in files]

        for i, (filepath, future) in enumerate(futures):
            t0 = time.time()
            try:
                result = future.result(timeout=config.timeout)
                elapsed = time.time() - t0
                if result is not None:
                    fr = FileResult(path=str(filepath), success=True,
                                    result=result, elapsed=elapsed)
                    stats.parsed += 1
                else:
                    fr = FileResult(path=str(filepath), success=False,
                                    elapsed=elapsed, error="parse returned None")
                    stats.failed += 1
            except FuturesTimeout:
                elapsed = time.time() - t0
                fr = FileResult(path=str(filepath), success=False,
                                elapsed=elapsed, error="timeout")
                stats.timed_out += 1
                stats.failed += 1
                print(f"[WARN] {label}: timeout after {config.timeout}s "
                      f"on {filepath}", file=sys.stderr)
            except Exception as e:
                elapsed = time.time() - t0
                fr = FileResult(path=str(filepath), success=False,
                                elapsed=elapsed, error=str(e))
                stats.failed += 1

            batch.append(fr)

            done = i + 1
            if done % config.progress_interval == 0:
                _print_progress(done, stats.total, stats.parsed,
                                stats.failed, t_start, label)

            if len(batch) >= config.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch

    stats.total_elapsed = time.time() - t_start
    return stats


def _print_progress(done: int, total: int, parsed: int, failed: int,
                    t_start: float, label: str) -> None:
    elapsed = time.time() - t_start
    rate = done / elapsed if elapsed > 0 else 0.0
    remaining = (total - done) / rate if rate > 0 else 0.0
    pct = done / total * 100 if total else 0.0
    print(
        f"  [{label}] {done}/{total} ({pct:.0f}%) "
        f"[OK:{parsed} FAIL:{failed}] "
        f"Elapsed:{int(elapsed)}s ETA:{int(remaining)}s",
        flush=True,
    )
