"""Cost_Control_System orchestrator package.

The imperative Python orchestrator for the ``nih-sandbox-cost-control``
feature. Sequences the stop / start / snapshot / scale / delete / restore
AWS API calls that hibernate the MDC MCP-RAG platform to ``Sleep_State`` and
restore it to ``Wake_State`` while preserving every byte of ingested data.

This package ships the shared primitives (config, audit, state file, cost
model, snapshot manager) first; the per-tier sleep/wake logic, drift
detection, wake probe, and state-machine CLI land in later implementation
waves. See ``.kiro/specs/nih-sandbox-cost-control/`` for the spec.

ASCII-only console output (``[OK]`` / ``[ERROR]`` / ``[WARN]`` / ``[INFO]`` /
``[SKIP]``) per the repository convention; emoji break MCP stdio.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
