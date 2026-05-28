"""Cost & storage telemetry for tenant-aware ingestion.

Produces JSON reports under scripts/ingestion_reports/ with drift
detection against Phase 54 baseline ranges.

Implements: Requirements 3.7, 5.1, 5.2, 5.3, 5.4 of omd-tenants-2-v17-pilot.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def default_baseline_ranges() -> dict:
    """Phase 54 baseline expected ranges for drift detection."""
    return {
        "expected_dedupe_efficiency_pct_range": [20.0, 50.0],
        "expected_documents_created_total_range": [1500, 2200],
        "expected_estimated_tokens_range": [1500000, 2500000],
    }


def evaluate_drift(observed: dict, ranges: dict) -> list[str]:
    """Return list of metric names that fall outside their expected range."""
    flags = []
    mapping = {
        "dedupe_efficiency_pct": "expected_dedupe_efficiency_pct_range",
        "documents_created_total": "expected_documents_created_total_range",
        "estimated_tokens": "expected_estimated_tokens_range",
    }
    for metric, range_key in mapping.items():
        if metric not in observed or range_key not in ranges:
            continue
        lo, hi = ranges[range_key]
        val = observed[metric]
        if val < lo or val > hi:
            flags.append(metric)
    return flags


class IngestionReportWriter:
    """Accumulates ingestion metrics and writes a JSON report at finalize."""

    REPORTS_DIR = Path(__file__).parent / "ingestion_reports"

    def __init__(self, tenant_id: str, branch: str, mode: str):
        self.tenant_id = tenant_id
        self.branch = branch
        self.mode = mode
        self.started_at = datetime.now(timezone.utc)
        self._counters: dict[str, int | float] = {
            "total_files_processed": 0,
            "documents_deduped": 0,
            "bedrock_invocations": 0,
            "estimated_tokens": 0,
            "relationships_created": 0,
        }
        self._documents_created: dict[str, int] = {}
        self._nodes_created: dict[str, int] = {}
        self._warnings: list[str] = []

    def increment(self, metric: str, value: int | float = 1) -> None:
        """Increment a named counter."""
        if metric.startswith("docs:"):
            index = metric[5:]
            self._documents_created[index] = self._documents_created.get(index, 0) + int(value)
        elif metric.startswith("nodes:"):
            label = metric[6:]
            self._nodes_created[label] = self._nodes_created.get(label, 0) + int(value)
        else:
            self._counters[metric] = self._counters.get(metric, 0) + value

    def finalize(self, *, model: str = "amazon.titan-embed-text-v2:0") -> Path:
        """Write the JSON report and return its path."""
        elapsed = (datetime.now(timezone.utc) - self.started_at).total_seconds()
        total_files = self._counters["total_files_processed"]
        docs_deduped = self._counters["documents_deduped"]
        docs_total = sum(self._documents_created.values())

        dedupe_pct = round(docs_deduped / total_files * 100, 1) if total_files > 0 else 0.0

        # Chunk-ceiling warning (R5.2)
        if total_files > 0 and docs_total / total_files > 3.0:
            msg = f"[WARN] documents_created_per_file={docs_total / total_files:.2f}"
            self._warnings.append(msg)
            print(msg, file=sys.stderr)

        # Drift detection
        observed = {
            "dedupe_efficiency_pct": dedupe_pct,
            "documents_created_total": docs_total,
            "estimated_tokens": self._counters["estimated_tokens"],
        }
        ranges = default_baseline_ranges()
        drift_flags = evaluate_drift(observed, ranges)

        report = {
            "schema_version": 1,
            "tenant_id": self.tenant_id,
            "branch": self.branch,
            "mode": self.mode,
            "started_at": self.started_at.isoformat(),
            "elapsed_seconds": round(elapsed, 1),
            "total_files_processed": total_files,
            "documents_created": self._documents_created,
            "documents_deduped": int(docs_deduped),
            "embedding_calls": {
                "bedrock_invocations": int(self._counters["bedrock_invocations"]),
                "estimated_tokens": int(self._counters["estimated_tokens"]),
                "model": model,
            },
            "graph": {
                "nodes_created_by_label": self._nodes_created,
                "relationships_created": int(self._counters["relationships_created"]),
            },
            "dedupe_efficiency_pct": dedupe_pct,
            "warnings": self._warnings,
            "comparison_to_phase_54_baseline": {
                **ranges,
                "drift_flags": drift_flags,
            },
        }

        self.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = self.started_at.strftime("%Y%m%dT%H%M%S")
        path = self.REPORTS_DIR / f"{self.tenant_id}_{ts}.json"
        path.write_text(json.dumps(report, indent=2) + "\n")
        return path
