# Phase 62 — CI Error-Log Processing Pipeline (Corpus Distillation & Normalization)

**Version**: 1.0.0
**Created**: 2026-06-25
**Status**: ready
**Estimated effort**: 1–2 days
**Depends on**: none (standalone)
**Consumed by (downstream, out of scope here)**: Ralph-loop tool-refinement task; future real-time `analyze_error_log` MCP tool

---

## Problem Statement

NOAA Global Workflow CI failures are diagnosed today by hand: an operator
copies a raw job log into a gist and prompts an LLM for analysis. That does not
scale and is not reproducible. Two upcoming capabilities both need a
**deterministic error-log processing pipeline** as their foundation:

1. **Offline tool-refinement** (Ralph loop) — needs a frozen, classified corpus
   of historical failures to iterate against.
2. **Real-time error-log analysis** (future MCP tool) — needs to distill a
   single live job log into a compact, structured signal on demand.

This phase delivers that shared pipeline **independent of either consumer**. It
is explicitly *not* the Ralph loop and *not* the MCP tool — it is the library +
CLIs + schema both will call.

### Why a pipeline is mandatory (corpus evidence)

A one-time survey of the cloned corpus (`/mcp_rag_eib/ERROR_LOGS`, branch
`error_logs`, 646 dirs / 4,362 files / **2.0 GB**) shows raw logs are
overwhelmingly noise with a tiny signal:

| Metric | Value |
|--------|-------|
| Logs < 10 KB | 1,406 |
| Logs 10–100 KB | 806 |
| Logs 100 KB–1 MB | 1,698 |
| Logs **> 1 MB** | **406** (largest `gfswavepostpnt.log` = **41.8 MB**) |
| Dirs containing `FATAL ERROR` | 1,438 |
| Dirs containing `Traceback` | 564 |
| Dirs containing `HTAR FAILED` | 47 |
| Dirs containing `Connection refused` | 35 |
| Dirs containing `command not found` | 44 |
| Dirs containing `Segmentation` | 16 |

A representative log (`PR_4864_C96_gcafs_cycled/gcdas_fetch.log`) is hundreds of
KB of `set -x` bash trace, full environment dumps, `PYTHONPATH`/`LD_LIBRARY_PATH`
expansions, and base64 Lmod `_ModuleTable` blocks — with the **actual failure in
~15 lines at the very end**:

```
connect: Connection refused ... Unable to setup communication to HPSS...
###WARNING htar returned non-zero exit status. 71 = .../htar_v9.3-Gaea -x ...
wxflow.executable.ProcessError: Command exited with status 71
End JGLOBAL_FETCH ... + status=1 + exit 1
```

Feeding raw logs to a model wastes the context window and buries the signal.
**Distillation + normalization is the foundational capability.**

---

## Goals / Non-Goals

### Goals
- A reusable **library** (`src/error_analysis/`) that distills one log (file or
  in-memory string) into a compact, structured record.
- A **stable normalized record schema** (the SPOT) shared by batch and real-time
  callers.
- A failure **taxonomy** (v1) grounded in the corpus.
- **CLIs** for single-log extraction and whole-corpus batch building.
- A **frequency/aggregation report** that becomes the fitness signal for the
  Ralph loop.
- **Tests** using small, checked-in fixture logs (not the 2 GB corpus).

### Non-Goals (explicit)
- No Ralph loop, no `while` orchestration (separate spec).
- No MCP tool registration / `analyze_error_log` (a later spec; this phase only
  guarantees the library API can support it — single-log, string input).
- No remediation/auto-fix suggestion logic (a later, model-driven layer).
- No ingestion into ChromaDB/Neo4j (the records are pipeline output; whether/how
  they get embedded is a downstream decision).

---

## Design

### Corpus location (SPOT: env var)

The cloned corpus lives **outside the repo** at `/mcp_rag_eib/ERROR_LOGS` (not a
submodule, not committed). All tooling resolves it via **`CI_ERROR_LOGS_DIR`**,
default `/mcp_rag_eib/ERROR_LOGS/ci/error_logs`. A thin
`scripts/sync_error_logs.sh` (re)creates it with a shallow single-branch clone so
any node can rebuild the frozen corpus.

### Normalized record schema (SPOT)

One JSON object per processed log — the contract both consumers depend on.
Defined once in `src/error_analysis/schema.py` (dataclass + `schema_version`):

| Field | Type | Notes |
|-------|------|-------|
| `schema_version` | int | bump on any field change (SDD-gated) |
| `log_id` | str | stable id derived from corpus-relative path |
| `rel_path` | str | path under `CI_ERROR_LOGS_DIR` |
| `pr` | str/null | parsed from dir name (`PR_4864...` → `4864`) |
| `case` | str/null | config/case (`C96_gcafs_cycled`) |
| `machine` | str/null | HERA/ORION/HERCULES/GAEA/URSA/WCOSS2/null (heuristic) |
| `job` | str/null | from filename (`gcdas_fetch` → `fetch`) |
| `filename` | str | basename |
| `failure_class` | str | taxonomy value (see below) |
| `markers` | list[str] | matched signal pattern names |
| `exit_code` | int/null | parsed final `status`/`exit`/`RETURN CODE` |
| `signal` | str | distilled excerpt (capped, see strategy) |
| `byte_size` | int | raw log size |
| `line_count` | int | raw line count |
| `truncated` | bool | true if signal hit the cap |
| `source_url` | str/null | raw GitHub URL for traceability |
| `extracted_at` | str | ISO-8601 UTC |

Output formats: one record (`extract`) or JSONL (`build_error_corpus`).

### Failure taxonomy v1 (grounded in corpus)

Ordered, first-match-wins classification in `src/error_analysis/classifier.py`:

| Class | Primary signals |
|-------|-----------------|
| `hpss_fetch` | `HTAR FAILED`, `Connection refused` + HPSS, `htar returned non-zero`, status 71 |
| `build` | `cmake`/`make` errors, `undefined reference`, `Error 1` in `build_*.log` |
| `forecast_model` | UFS/`fcst` aborts, `MPI_ABORT`, `forrtl:`, model `FATAL` |
| `timeout` | `DUE TO TIME LIMIT`, `CANCELLED`, walltime exceeded |
| `oom` | `Out of memory`, `oom-kill`, `Killed` |
| `segfault` | `Segmentation fault`, signal 11 |
| `missing_file` | `No such file or directory`, `cannot stat` |
| `command_not_found` | `command not found` |
| `rocoto` | `rocotostat`/`rocoto` dryrun failures |
| `python_traceback` | generic `Traceback (most recent call last)` not matched above |
| `unknown` | fallback |

Taxonomy is data, kept as a single ordered table (SPOT) so contributors extend
it in one place.

### Distillation strategy (the core algorithm)

Logs are bash `set -x` traces; failures surface near the **end**. The extractor:

1. **Drop noise** lines: env dumps (`declare -rx`, `export FOO=`,
   `PYTHONPATH=`/`LD_LIBRARY_PATH=`/`PATH=` expansions), base64 `_ModuleTable*`,
   module-load chatter (`+++ ...`), and PS4-prefixed trace where it carries no
   error token.
2. **Capture signal regions**:
   - full Python `Traceback ... Error` blocks,
   - `err_exit.sh` `FATAL ERROR` banners (the `--- ... -- FATAL ERROR: ...`
     fenced block),
   - lines matching taxonomy markers,
   - the final `status=`/`exit`/`RETURN CODE`/`error code` tail.
3. **Window + cap**: keep a bounded excerpt (default **8 KB**, configurable
   `--max-bytes`) preferring the tail; set `truncated` when clipped.
4. Operate identically on a **file path or an in-memory string** (the real-time
   caller passes a string), and never raise on malformed input — emit
   `failure_class="unknown"` with whatever tail is available.

### Module / file layout

```
mcp_server_python/
  src/error_analysis/
    __init__.py
    schema.py        # ErrorRecord dataclass + schema_version (SPOT)
    extractor.py     # distill(text|path) -> ErrorRecord ; noise filters + windowing
    classifier.py    # taxonomy table (SPOT) + classify()
    metadata.py      # parse pr/case/machine/job from path+filename
  scripts/
    sync_error_logs.sh        # (re)clone corpus to CI_ERROR_LOGS_DIR
    extract_error_signal.py   # single log -> ErrorRecord JSON (stdout)
    build_error_corpus.py     # walk corpus -> corpus.jsonl + summary.md
  tests/unit/
    test_error_analysis.py    # fixtures-based
    fixtures/error_logs/      # ~6 small real excerpts (one per major class)
```

---

## Deliverables Catalogue

| # | File | Deliverable | Effort |
|---|------|-------------|--------|
| D1 | `src/error_analysis/schema.py` | `ErrorRecord` dataclass + `SCHEMA_VERSION` + `to_dict()`/JSON | 1 h |
| D2 | `src/error_analysis/metadata.py` | Parse `pr`/`case`/`machine`/`job` from path+filename | 2 h |
| D3 | `src/error_analysis/extractor.py` | Noise filters, signal-region capture, windowing/cap, file+string entrypoints | 4 h |
| D4 | `src/error_analysis/classifier.py` | Ordered taxonomy table (SPOT) + `classify(text, markers)` | 2 h |
| D5 | `scripts/extract_error_signal.py` | CLI: one log → ErrorRecord JSON | 1 h |
| D6 | `scripts/build_error_corpus.py` | Batch walk `CI_ERROR_LOGS_DIR` → `corpus.jsonl` + `summary.md` (class freq, machine freq, top jobs) | 3 h |
| D7 | `scripts/sync_error_logs.sh` | Idempotent shallow clone to `CI_ERROR_LOGS_DIR` | 1 h |
| D8 | `tests/unit/fixtures/error_logs/` + `test_error_analysis.py` | ~6 fixture logs (hpss_fetch, build, forecast_model, timeout, python_traceback, unknown) + unit tests | 4 h |
| D9 | `CHANGELOG.md` | Dated entry | 15 m |

---

## Steps

### Step 1 — Schema + metadata parsers (D1, D2)

Define `ErrorRecord` and the path/filename parsers. Machine inference is a
heuristic over dir/file/content tokens (`HERCULES`, `ORION`, `GAEA`/`GAEAC6`,
`URSA`, `WCOSS2`, `HERA`).

**Test**: `metadata.parse("PR_4864_C96_gcafs_cycled", "gcdas_fetch.log")` →
`pr=4864, case=C96_gcafs_cycled, job=fetch`.

### Step 2 — Extractor (D3)

Implement noise filters + signal-region capture + windowing on the `gcdas_fetch`
fixture. Must reduce a hundreds-of-KB log to ≤ 8 KB while retaining the HPSS /
`status 71` traceback.

**Test**: distilled `signal` contains `HTAR FAILED` and the `ProcessError ...
status 71` line; excludes `_ModuleTable`/`PYTHONPATH` noise; `truncated`
reflects the cap.

### Step 3 — Classifier (D4)

Wire the ordered taxonomy. First-match-wins; record matched `markers`.

**Test**: the `gcdas_fetch` fixture → `failure_class="hpss_fetch"`; a
`build_gdas` fixture → `build`; a bare Python exception → `python_traceback`;
empty/garbage → `unknown`.

### Step 4 — Single-log CLI (D5)

`extract_error_signal.py <path>` prints one ErrorRecord JSON. This is the exact
entrypoint the future real-time MCP tool will wrap (string-in variant covered by
the library API).

**Test**: CLI on a fixture emits valid JSON matching `SCHEMA_VERSION`.

### Step 5 — Corpus builder + report (D6, D7)

`sync_error_logs.sh` ensures the corpus; `build_error_corpus.py` walks it,
emits `corpus.jsonl` (one record/log) and `summary.md` (failure-class
frequencies, per-machine counts, top failing jobs). Must process all 4,362 logs
without loading any whole >1 MB log into memory unbounded (stream + cap).

**Test (smoke, not unit)**: run against `CI_ERROR_LOGS_DIR`; assert record count
≈ file count, JSONL parses, and `summary.md` class table is non-empty. Capture
the produced class distribution as the baseline fitness signal.

### Step 6 — Tests + fixtures (D8)

Add ~6 small real excerpts (trim the giant logs to a few KB each, preserving the
failure region) under `tests/unit/fixtures/error_logs/`. Cover extractor,
classifier, metadata, schema-version, and malformed-input paths.

**Test**: `python -m pytest tests/unit/test_error_analysis.py -q` green.

### Step 7 — Changelog (D9)

Add a dated `CHANGELOG.md` entry describing the pipeline, schema version, and the
`CI_ERROR_LOGS_DIR` SPOT.

---

## Acceptance Criteria

- `extract_error_signal.py` turns the 41.8 MB-class logs into ≤ 8 KB structured
  records without OOM, retaining the true failure region.
- `build_error_corpus.py` produces `corpus.jsonl` for the full corpus and a
  `summary.md` with a non-trivial failure-class distribution.
- Library API supports **both** a file path and an in-memory string (real-time
  readiness) and never raises on malformed input.
- `SCHEMA_VERSION` is the single source of truth for the record shape.
- Unit tests green; corpus smoke run documented.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Giant logs (40 MB) OOM the walker | Stream line-by-line; tail-window with a hard cap; never `read()` whole file |
| Over-aggressive noise filter drops the real error | Always retain the final N lines + any `Traceback`/`FATAL ERROR` region verbatim regardless of filters |
| Taxonomy drift across contributors | Single ordered table (SPOT); first-match-wins; new classes are one-line additions, SDD-gated on schema change |
| Corpus path hard-coded | `CI_ERROR_LOGS_DIR` env (SPOT) with documented default |
| Fixtures balloon repo size | Trim excerpts to a few KB; never commit raw multi-MB logs |

---

## Interfaces handed to downstream specs (not built here)

- **Ralph loop** consumes `corpus.jsonl` + `summary.md` as its work queue and
  fitness baseline.
- **Real-time `analyze_error_log` MCP tool** wraps
  `error_analysis.extractor.distill(text=...)` + `classifier.classify(...)` and
  returns the `ErrorRecord`. Library API shape is fixed here so that tool is a
  thin wrapper.
