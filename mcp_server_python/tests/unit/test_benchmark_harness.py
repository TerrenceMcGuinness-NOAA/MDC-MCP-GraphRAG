"""Unit tests for the corpus, selection, and per-case failure tables
(Task 3.6).

Feature: default-tenant-freeze-retirement.

Fixed inputs, no generators -- the properties in
``test_benchmark_scoring.py`` and ``test_benchmark_hermetic.py`` already
cover the input space; this file pins the specific failure-table rows the
design's Error Handling section enumerates, and the observable exit
behaviour of each CLI mode.

Runs with no AWS credential and no reachable MCP server: every case that
touches ``run_benchmark``/``main`` supplies an injected data-access facade
(:func:`tests.baselines.capture.build_benchmark_data_access`) so
``create_data_access`` is never reached.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.run_benchmark as run_benchmark_module
from scripts.run_benchmark import (
    CATEGORY_NAMES,
    BenchmarkCase,
    Corpus,
    CorpusError,
    load_corpus,
    main,
    run_benchmark,
)
from src.config.tenants import load_catalog
from src.tenancy.exceptions import UnknownTenantError
from tests.baselines.capture import build_benchmark_data_access
from tests.properties.conftest import _TENANTS_YAML

pytestmark = pytest.mark.unit

_REAL_CATALOG = load_catalog(_TENANTS_YAML)

_REQUIRED_FIELDS = (
    "id",
    "question",
    "tool",
    "tool_args",
    "expected_results",
    "expected_min_results",
    "category",
    "notes",
)


def _minimal_case(case_id: str = "c1", **overrides) -> dict:
    base = {
        "id": case_id,
        "question": "q",
        "tool": "search_documentation",
        "tool_args": {"query": "q"},
        "expected_results": ["hit"],
        "expected_min_results": 1,
        "category": "operational",
        "notes": "",
    }
    base.update(overrides)
    return base


def _write_corpus(tmp_path: Path, obj: dict) -> str:
    path = tmp_path / "ground_truth.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def _minimal_corpus_obj(tenant_categories: dict | None = None) -> dict:
    obj = {
        "version": "1.1.0",
        "metrics_config": {"k": 5},
        "categories": {
            name: [] for name in CATEGORY_NAMES
        },
    }
    obj["categories"]["operational"] = [_minimal_case("c1")]
    if tenant_categories is not None:
        obj["tenant_categories"] = tenant_categories
    return obj


# ---------------------------------------------------------------------------
# Corpus and selection failures
# ---------------------------------------------------------------------------


class TestCorpusFailures:
    def test_corpus_file_absent_raises_file_not_found(self, tmp_path):
        missing = str(tmp_path / "does_not_exist.json")
        with pytest.raises(FileNotFoundError):
            load_corpus(missing)

    def test_corpus_not_valid_json_raises_with_position(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError) as excinfo:
            load_corpus(str(path))
        # The decoder's own line/column are what the CLI (3.3) reports;
        # confirm they are present and sane.
        assert excinfo.value.lineno >= 1
        assert excinfo.value.colno >= 1

    def test_categories_absent_is_an_error(self, tmp_path):
        obj = {"version": "1.1.0", "metrics_config": {}}
        path = _write_corpus(tmp_path, obj)
        with pytest.raises(CorpusError, match="categories"):
            load_corpus(path)

    def test_categories_not_an_object_is_an_error(self, tmp_path):
        obj = {"version": "1.1.0", "metrics_config": {}, "categories": []}
        path = _write_corpus(tmp_path, obj)
        with pytest.raises(CorpusError):
            load_corpus(path)

    def test_tenant_categories_absent_is_not_an_error(self, tmp_path):
        """A corpus predating this feature (no ``tenant_categories``) must
        still load and run, scoring Default_Tenant cases only.
        """
        obj = _minimal_corpus_obj(tenant_categories=None)
        assert "tenant_categories" not in obj
        path = _write_corpus(tmp_path, obj)

        corpus = load_corpus(path)

        assert len(corpus.cases) == 1
        assert corpus.cases[0].tenant_scoped is False

    def test_case_missing_a_required_field_errors_naming_case_and_field(
        self, tmp_path
    ):
        case = _minimal_case("c_broken")
        del case["expected_results"]
        obj = _minimal_corpus_obj()
        obj["categories"]["operational"] = [case]
        path = _write_corpus(tmp_path, obj)

        with pytest.raises(CorpusError) as excinfo:
            load_corpus(path)
        message = str(excinfo.value)
        assert "c_broken" in message
        assert "expected_results" in message

    def test_malformed_tool_args_errors_naming_case(self, tmp_path):
        case = _minimal_case("c_bad_args", tool_args="not-an-object")
        obj = _minimal_corpus_obj()
        obj["categories"]["operational"] = [case]
        path = _write_corpus(tmp_path, obj)

        with pytest.raises(CorpusError) as excinfo:
            load_corpus(path)
        assert "c_bad_args" in str(excinfo.value)

    def test_tenant_categories_not_an_object_is_an_error(self, tmp_path):
        obj = _minimal_corpus_obj()
        obj["tenant_categories"] = []
        path = _write_corpus(tmp_path, obj)

        with pytest.raises(CorpusError):
            load_corpus(path)


# ---------------------------------------------------------------------------
# CLI mode observables
# ---------------------------------------------------------------------------


def _fake_build_tool_map_for(
    responses: dict[str, str], raising: frozenset[str] = frozenset()
):
    def _closure_for(case_id):
        async def _closure(**kwargs):
            if case_id in raising:
                raise RuntimeError(f"synthetic failure: {case_id}")
            return responses.get(case_id, "")
        return _closure

    def _fake(data, catalog, *, tool_names, state_dir):
        return {name: _closure_for(name) for name in tool_names}

    return _fake


class TestCLIModes:
    def test_dry_run_writes_nothing_and_invokes_nothing(
        self, tmp_path, capsys
    ):
        obj = _minimal_corpus_obj()
        path = _write_corpus(tmp_path, obj)
        results_dir = tmp_path / "results"

        called = {"count": 0}

        def _fail_if_called(*args, **kwargs):
            called["count"] += 1
            raise AssertionError("dry-run must not build a tool map")

        with patch.object(
            run_benchmark_module, "build_tool_map", _fail_if_called
        ):
            rc = main([
                "--corpus", path,
                "--dry-run",
                "--results-dir", str(results_dir),
            ])

        assert rc == 0
        assert called["count"] == 0
        assert not results_dir.exists()
        out = capsys.readouterr().out
        assert "[OK]" in out
        for name in CATEGORY_NAMES:
            assert name in out

    def test_unknown_category_lists_all_six_and_exits_1(self, tmp_path):
        obj = _minimal_corpus_obj()
        path = _write_corpus(tmp_path, obj)

        rc = main(["--corpus", path, "--category", "not_a_real_category"])

        assert rc == 1

    def test_unknown_category_message_names_all_six(self, tmp_path, capsys):
        obj = _minimal_corpus_obj()
        path = _write_corpus(tmp_path, obj)

        main(["--corpus", path, "--category", "bogus"])

        err = capsys.readouterr().err
        for name in CATEGORY_NAMES:
            assert name in err

    def test_valid_but_empty_category_warns_and_writes_zero_coverage(
        self, tmp_path
    ):
        obj = _minimal_corpus_obj()
        # "architecture" carries zero cases in this minimal corpus.
        path = _write_corpus(tmp_path, obj)
        results_dir = tmp_path / "results"

        rc = main([
            "--corpus", path,
            "--category", "architecture",
            "--results-dir", str(results_dir),
        ])

        assert rc == 0
        files = list(results_dir.glob("*.json"))
        assert len(files) == 1
        record = json.loads(files[0].read_text())
        assert record["overall"]["coverage"] == 0.0
        assert record["total_queries"] == 0

    def test_all_errored_path_writes_a_record_and_exits_1(self, tmp_path):
        obj = _minimal_corpus_obj()
        path = _write_corpus(tmp_path, obj)
        results_dir = tmp_path / "results"

        with patch.object(
            run_benchmark_module, "build_tool_map",
            lambda data, catalog, *, tool_names, state_dir: {},
        ):
            rc = main([
                "--corpus", path,
                "--results-dir", str(results_dir),
            ])

        assert rc == 1
        files = list(results_dir.glob("*.json"))
        assert len(files) == 1
        record = json.loads(files[0].read_text())
        assert record["overall"]["coverage"] == 0.0

    def test_scored_run_with_a_poor_score_exits_0(self, tmp_path):
        obj = _minimal_corpus_obj()
        path = _write_corpus(tmp_path, obj)
        results_dir = tmp_path / "results"

        # The one case's closure returns text that matches nothing --
        # coverage 0 -- but the run itself is not "all errored" (no case
        # carries an `error` field), which must exit 0.
        with patch.object(
            run_benchmark_module, "build_tool_map",
            lambda data, catalog, *, tool_names, state_dir: {
                name: (lambda **kw: _ok_but_unmatched()) for name in tool_names
            },
        ):
            rc = main([
                "--corpus", path,
                "--results-dir", str(results_dir),
            ])

        assert rc == 0


async def _ok_but_unmatched() -> str:
    return "nothing relevant here"


# ---------------------------------------------------------------------------
# Per-case failure shapes
# ---------------------------------------------------------------------------


class TestPerCaseFailureShapes:
    def _run_with_map(self, corpus: Corpus, fake_map):
        with patch.object(
            run_benchmark_module, "build_tool_map", fake_map
        ), tempfile.TemporaryDirectory() as d:
            return run_benchmark(
                corpus, data=object(), catalog=_REAL_CATALOG, results_dir=d
            )

    def _one_case_corpus(self, **overrides) -> Corpus:
        case = BenchmarkCase(
            id="c1",
            question="q",
            tool="c1",
            tool_args=overrides.get("tool_args", {}),
            expected_results=["TOKEN"],
            expected_min_results=1,
            category="operational",
            notes="",
            tenant_scoped="tenant_id" in overrides.get("tool_args", {}),
        )
        return Corpus(
            version="1.1.0", metrics_config={"k": 5}, cases=(case,),
            origins={"c1": "categories"},
        )

    def test_tool_name_absent_from_map_records_naming_error(self):
        corpus = self._one_case_corpus()
        run = self._run_with_map(
            corpus, lambda data, catalog, *, tool_names, state_dir: {}
        )
        result = run.results[0]
        assert result.error is not None
        assert "c1" in result.error
        assert result.precision == 0.0
        assert result.covered is False

    def test_closure_raises_records_exception_message(self):
        corpus = self._one_case_corpus()

        async def _raiser(**kwargs):
            raise RuntimeError("boom")

        run = self._run_with_map(
            corpus,
            lambda data, catalog, *, tool_names, state_dir: {"c1": _raiser},
        )
        result = run.results[0]
        assert result.error == "boom"
        assert result.mrr == 0.0

    def test_closure_returns_non_str_records_type_error(self):
        corpus = self._one_case_corpus()

        async def _returns_dict(**kwargs):
            return {"not": "a string"}

        run = self._run_with_map(
            corpus,
            lambda data, catalog, *, tool_names, state_dir: {
                "c1": _returns_dict
            },
        )
        result = run.results[0]
        assert result.error is not None
        assert "dict" in result.error

    def test_unknown_tenant_id_surfaces_as_one_bad_case(self):
        """A misspelled ``tenant_id`` in a case's ``tool_args`` must fail
        that one case, not the whole run.
        """
        corpus = self._one_case_corpus(
            tool_args={"tenant_id": "no_such_tenant"}
        )

        async def _raises_unknown_tenant(**kwargs):
            raise UnknownTenantError("no_such_tenant")

        run = self._run_with_map(
            corpus,
            lambda data, catalog, *, tool_names, state_dir: {
                "c1": _raises_unknown_tenant
            },
        )
        assert len(run.results) == 1
        result = run.results[0]
        assert result.error is not None
        assert result.covered is False
        # The run as a whole is not aborted -- it completed normally with
        # one bad case, which is exactly the accounting Property 10 pins.
        assert run.all_errored is True  # the only case present errored


# ---------------------------------------------------------------------------
# No credentials, nothing reachable
# ---------------------------------------------------------------------------


class TestHermeticOperation:
    def test_run_benchmark_with_injected_facade_needs_no_credentials(self):
        """A run with an injected facade and a real catalog completes with
        no AWS credential and no reachable MCP server -- the corpus's one
        case here uses a synthetic tool map so no real ``src.tools.*``
        closure (and therefore no real backend call) is reached.
        """
        obj = _minimal_corpus_obj()
        corpus = Corpus(
            version=obj["version"],
            metrics_config=obj["metrics_config"],
            cases=(
                BenchmarkCase(
                    id="c1", question="q", tool="c1", tool_args={},
                    expected_results=["hit"], expected_min_results=1,
                    category="operational", notes="", tenant_scoped=False,
                ),
            ),
            origins={"c1": "categories"},
        )

        async def _closure(**kwargs):
            return "a response containing hit"

        with patch.object(
            run_benchmark_module, "build_tool_map",
            lambda data, catalog, *, tool_names, state_dir: {"c1": _closure},
        ), tempfile.TemporaryDirectory() as d:
            run = run_benchmark(
                corpus, data=build_benchmark_data_access(),
                catalog=_REAL_CATALOG, results_dir=d,
            )

        assert run.record["overall"]["coverage"] == 1.0
        assert run.all_errored is False
