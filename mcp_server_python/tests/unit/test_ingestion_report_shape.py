"""Unit test for end-to-end ingestion report shape.

Feature: omd-tenants-2-v17-pilot, Requirements 3.7, 5.1, 5.2, 5.4
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from _ingest_cost_model import IngestionReportWriter


class TestEndToEndReportShape:
    """Drive a synthetic 5-file ingestion and verify the JSON report."""

    def test_report_has_all_required_keys(self, tmp_path):
        """Produced JSON has every key from design §4 schema."""
        w = IngestionReportWriter("gw_v17", "dev/gfs.v17", "full")
        w.REPORTS_DIR = tmp_path

        # Simulate 5 files: 3 new, 2 deduped
        for i in range(5):
            w.increment("total_files_processed")
            if i < 3:
                w.increment("bedrock_invocations")
                w.increment("estimated_tokens", 1200)
                w.increment("docs:gw_v17_mdc-workflow-docs-titan1024")
                w.increment("nodes:GW_V17_File")
                w.increment("relationships_created", 3)
            else:
                w.increment("documents_deduped")

        path = w.finalize()
        report = json.loads(path.read_text())

        # All required top-level keys
        required_keys = [
            "schema_version", "tenant_id", "branch", "mode",
            "started_at", "elapsed_seconds", "total_files_processed",
            "documents_created", "documents_deduped", "embedding_calls",
            "graph", "dedupe_efficiency_pct", "warnings",
            "comparison_to_phase_54_baseline",
        ]
        for key in required_keys:
            assert key in report, f"missing key: {key}"

        # Schema version
        assert report["schema_version"] == 1
        assert report["tenant_id"] == "gw_v17"
        assert report["branch"] == "dev/gfs.v17"
        assert report["mode"] == "full"

        # Counts
        assert report["total_files_processed"] == 5
        assert report["documents_deduped"] == 2
        assert report["dedupe_efficiency_pct"] == 40.0  # 2/5 * 100

        # Embedding calls sub-structure
        assert report["embedding_calls"]["bedrock_invocations"] == 3
        assert report["embedding_calls"]["estimated_tokens"] == 3600
        assert report["embedding_calls"]["model"] == "amazon.titan-embed-text-v2:0"

        # Graph sub-structure
        assert "nodes_created_by_label" in report["graph"]
        assert report["graph"]["nodes_created_by_label"]["GW_V17_File"] == 3
        assert report["graph"]["relationships_created"] == 9

        # Comparison block
        comp = report["comparison_to_phase_54_baseline"]
        assert "expected_dedupe_efficiency_pct_range" in comp
        assert "expected_documents_created_total_range" in comp
        assert "expected_estimated_tokens_range" in comp
        assert "drift_flags" in comp

    def test_chunk_ceiling_warning_emitted(self, tmp_path):
        """[WARN] emitted when docs/files > 3.0."""
        w = IngestionReportWriter("gw_v17", "dev/gfs.v17", "full")
        w.REPORTS_DIR = tmp_path

        # 2 files, 7 docs → 3.5 > 3.0
        w.increment("total_files_processed", 2)
        w.increment("docs:gw_v17_mdc-workflow-docs-titan1024", 7)

        path = w.finalize()
        report = json.loads(path.read_text())
        assert any("[WARN]" in warning for warning in report["warnings"])
        assert "documents_created_per_file" in report["warnings"][0]

    def test_dedupe_efficiency_formula(self, tmp_path):
        """dedupe_efficiency_pct = round(deduped / total * 100, 1)."""
        w = IngestionReportWriter("gw_v17", "dev/gfs.v17", "full")
        w.REPORTS_DIR = tmp_path

        w.increment("total_files_processed", 7)
        w.increment("documents_deduped", 3)
        w.increment("docs:gw_v17_mdc-workflow-docs-titan1024", 4)

        path = w.finalize()
        report = json.loads(path.read_text())
        # 3/7 * 100 = 42.857... → round to 42.9
        assert report["dedupe_efficiency_pct"] == 42.9
