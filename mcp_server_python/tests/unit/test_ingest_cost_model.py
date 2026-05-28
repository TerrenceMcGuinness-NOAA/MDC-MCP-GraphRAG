"""Unit tests for _ingest_cost_model.py.

Feature: omd-tenants-2-v17-pilot, Requirements 3.7, 5.2, 5.3
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from _ingest_cost_model import (
    IngestionReportWriter,
    default_baseline_ranges,
    evaluate_drift,
)


class TestEvaluateDrift:
    """Drift-flag detection: metrics outside range → flag populated."""

    def test_all_within_range_no_flags(self):
        observed = {
            "dedupe_efficiency_pct": 35.0,
            "documents_created_total": 1800,
            "estimated_tokens": 2000000,
        }
        flags = evaluate_drift(observed, default_baseline_ranges())
        assert flags == []

    def test_dedupe_below_range(self):
        observed = {
            "dedupe_efficiency_pct": 10.0,
            "documents_created_total": 1800,
            "estimated_tokens": 2000000,
        }
        flags = evaluate_drift(observed, default_baseline_ranges())
        assert "dedupe_efficiency_pct" in flags

    def test_dedupe_above_range(self):
        observed = {
            "dedupe_efficiency_pct": 60.0,
            "documents_created_total": 1800,
            "estimated_tokens": 2000000,
        }
        flags = evaluate_drift(observed, default_baseline_ranges())
        assert "dedupe_efficiency_pct" in flags

    def test_tokens_above_range(self):
        observed = {
            "dedupe_efficiency_pct": 35.0,
            "documents_created_total": 1800,
            "estimated_tokens": 3000000,
        }
        flags = evaluate_drift(observed, default_baseline_ranges())
        assert "estimated_tokens" in flags

    def test_multiple_flags(self):
        observed = {
            "dedupe_efficiency_pct": 5.0,
            "documents_created_total": 5000,
            "estimated_tokens": 100,
        }
        flags = evaluate_drift(observed, default_baseline_ranges())
        assert len(flags) == 3


class TestIngestionReportWriter:
    """Report writer produces correct JSON shape."""

    def test_chunk_ceiling_warning(self, tmp_path):
        """Chunk-ceiling [WARN] triggers when docs/files > 3.0."""
        w = IngestionReportWriter("gw_v17", "dev/gfs.v17", "full")
        w.REPORTS_DIR = tmp_path
        # 2 files, 7 docs → 3.5 > 3.0 → warning
        w.increment("total_files_processed", 2)
        w.increment("docs:gw_v17_mdc-workflow-docs-titan1024", 7)
        path = w.finalize()
        report = json.loads(path.read_text())
        assert any("[WARN]" in w for w in report["warnings"])

    def test_no_warning_below_ceiling(self, tmp_path):
        """No warning when docs/files <= 3.0."""
        w = IngestionReportWriter("gw_v17", "dev/gfs.v17", "full")
        w.REPORTS_DIR = tmp_path
        w.increment("total_files_processed", 10)
        w.increment("docs:gw_v17_mdc-workflow-docs-titan1024", 25)
        path = w.finalize()
        report = json.loads(path.read_text())
        assert report["warnings"] == []

    def test_report_roundtrips_json(self, tmp_path):
        """JSON report round-trips without losing comparison block."""
        w = IngestionReportWriter("gw_v17", "dev/gfs.v17", "full")
        w.REPORTS_DIR = tmp_path
        w.increment("total_files_processed", 100)
        w.increment("documents_deduped", 30)
        w.increment("bedrock_invocations", 70)
        w.increment("estimated_tokens", 2000000)
        w.increment("docs:gw_v17_mdc-workflow-docs-titan1024", 70)
        w.increment("nodes:GW_V17_File", 100)
        w.increment("relationships_created", 500)
        path = w.finalize()

        report = json.loads(path.read_text())
        assert report["schema_version"] == 1
        assert report["tenant_id"] == "gw_v17"
        assert report["branch"] == "dev/gfs.v17"
        assert report["mode"] == "full"
        assert report["total_files_processed"] == 100
        assert report["documents_deduped"] == 30
        assert report["dedupe_efficiency_pct"] == 30.0
        assert report["embedding_calls"]["bedrock_invocations"] == 70
        assert report["embedding_calls"]["estimated_tokens"] == 2000000
        assert report["graph"]["nodes_created_by_label"]["GW_V17_File"] == 100
        assert report["graph"]["relationships_created"] == 500
        assert "comparison_to_phase_54_baseline" in report
        assert "drift_flags" in report["comparison_to_phase_54_baseline"]
