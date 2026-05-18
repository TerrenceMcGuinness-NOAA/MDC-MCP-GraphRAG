"""Integration test for ``BedrockProvider`` (Phase C-2c, Req 11.7, 12.4).

Gated on ``RUN_INTEGRATION=1`` — skips entirely without it so the
default ``pytest tests/`` run never touches AWS. When enabled, builds
the ``titan1024`` profile, constructs a real :class:`BedrockProvider`
(real boto3, real credentials), runs ``provider.embed(["hello world"])``
five times, asserts each returned vector has length 1024, and prints
p50/p95 latency stats for the phase report.

Uses the AWS region from the boto3 default chain
(``AWS_REGION`` or ``us-east-1`` fallback). Requires:

* AWS credentials available to boto3 (env, profile, or IMDS).
* IAM permission ``bedrock:InvokeModel`` on
  ``amazon.titan-embed-text-v2:0``.

Run example::

    cd mcp_server_python
    RUN_INTEGRATION=1 python3.12 -m pytest \\
        tests/integration/test_bedrock_embedding.py -s
"""

from __future__ import annotations

import os
import time

import pytest

from src.data.embedding_provider import BedrockProvider
from src.data.embedding_registry import EmbeddingModelRegistry


_RUN_INTEGRATION = os.getenv("RUN_INTEGRATION") == "1"

pytestmark = pytest.mark.skipif(
    not _RUN_INTEGRATION,
    reason="integration test skipped — set RUN_INTEGRATION=1 to enable",
)


# ── latency helper (re-usable from the phase report) ──────────────────


def latency_stats(samples_s: list[float]) -> dict[str, float]:
    """Return p50 / p95 / mean / min / max from a list of seconds."""
    if not samples_s:
        return {"p50": 0.0, "p95": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0}
    sorted_s = sorted(samples_s)
    n = len(sorted_s)

    def pct(p: float) -> float:
        # Linear interpolation on the sorted list — small N so this is
        # plenty accurate for a smoke-test latency capture.
        idx = (n - 1) * p
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        return sorted_s[lo] + (sorted_s[hi] - sorted_s[lo]) * (idx - lo)

    return {
        "p50": pct(0.50),
        "p95": pct(0.95),
        "mean": sum(sorted_s) / n,
        "min": sorted_s[0],
        "max": sorted_s[-1],
    }


# ── the test ──────────────────────────────────────────────────────────


def test_titan1024_embed_hello_world(capsys: pytest.CaptureFixture) -> None:
    """One real Bedrock call against ``titan1024``, plus latency stats."""
    profile = EmbeddingModelRegistry().get_profile("titan1024")
    provider = BedrockProvider(profile)

    latencies_s: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        vectors = provider.embed(["hello world"])
        latencies_s.append(time.perf_counter() - t0)
        assert len(vectors) == 1
        assert len(vectors[0]) == 1024

    stats = latency_stats(latencies_s)
    # ``-s`` exposes the print to the operator; the same output is
    # captured by the phase report's latency-row builder.
    print(
        "\n[bedrock-embed-titan1024] "
        f"n=5 "
        f"p50={stats['p50']*1000:.1f}ms "
        f"p95={stats['p95']*1000:.1f}ms "
        f"mean={stats['mean']*1000:.1f}ms "
        f"min={stats['min']*1000:.1f}ms "
        f"max={stats['max']*1000:.1f}ms"
    )
