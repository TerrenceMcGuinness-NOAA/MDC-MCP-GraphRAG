# Phase 62 — CI Error-Log Distillation & MCP Tool

**Version**: 2.0.0 (Revised)
**Created**: 2026-06-26
**Status**: ready
**Estimated effort**: 1–2 days
**Depends on**: none

---

## 1. Executive Summary

Automating the diagnosis of NOAA Global Workflow CI failures has been a long-standing goal. Historically, operators manually copied massive raw logs (often tens of megabytes) into LLMs with detailed prompts. While capable models with massive context windows could eventually parse these giant files, this brute-force approach is fundamentally incompatible with automated, fast-iteration systems like the **Ralph Loop** or context-limited tools like the Gemini CLI, which immediately blow their context limits.

**The Pivot:** Instead of building a massive offline batch-processing pipeline for a 2GB corpus (as originally planned), we must focus on **immediate, on-demand distillation**. We need to lock down the error log preprocessing step into a deterministic library and expose it *immediately* as a new MCP tool. This tool will bridge the gap: allowing operators and the Ralph Loop to point at a massive log file and receive a highly compressed, distilled signal without blowing out the context window.

---

## 2. Scope

### 2.1 In Scope
- A reusable **distillation library** (`src/error_analysis/`) that strips out Bash noise and captures the actual error signal.
- A **stable normalized record schema** (the SPOT) for error representation.
- A foundational failure **taxonomy** grounded in known NOAA workflow failures.
- A dedicated MCP Tool (`extract_ci_error_signal`) designed *specifically for LLM consumption*. The tool performs mechanical distillation (dropping noise) to fit the context window, outputting a high-entropy, dense JSON/markdown payload that preserves the raw traceback and stack context so the LLM can perform the actual reasoning and root-cause analysis.
- **Tests** using small, checked-in fixture logs representing major failure classes.

### 2.2 Out of Scope
- **NO direct CI pipeline integration** (deferred due to AWS/FedRAMP governance).
- **NO batch corpus processing** (syncing and distilling the 2GB offline data lake is deferred; focus is on on-demand tool usage).
- No remediation/auto-fix suggestion logic inside the tool itself (the tool provides the *distilled signal*; the LLM provides the fix).

---

## 3. Acceptance Criteria

| # | Probe | Pass condition |
|---|-------|----------------|
| 1 | Extract hpss_fetch error | Taxonomy correctly identifies `hpss_fetch` from fixture. |
| 2 | Extract build error | Taxonomy correctly identifies `build` from fixture. |
| 3 | Extract python traceback | Traceback is fully captured within the 8KB limit. |
| 4 | Noise Filtering | Extracted signal drops `_ModuleTable*` blocks and environment dumps. |
| 5 | Output Size Constraints | The `diagnostic_signal` never exceeds the 8KB limit, truncating gracefully if needed. |
| 6 | MCP Tool Registration | `extract_ci_error_signal` appears in the list of available MCP tools. |
| 7 | Tool Execution | Passing a valid path to the tool returns a JSON payload matching the `ErrorRecord` schema. |
| 8 | Unit tests | `pytest tests/unit/test_error_analysis.py` stays green. |

---

## 4. Implementation Plan

### Step 1 — Define Schema & Taxonomy (Design)
- Implement `ErrorRecord` dataclass in `src/error_analysis/schema.py` to standardize the payload format.
- Define the ordered, first-match-wins failure taxonomy in `src/error_analysis/classifier.py` mapping classes (e.g., `oom`, `timeout`) to primary string signals.
- **Test**: Ensure the schema can serialize to JSON.

### Step 2 — Core Extractor Algorithm (Implement)
- Implement the noise filters in `src/error_analysis/extractor.py` (stripping environment dumps, base64 strings, module chatter).
- Implement the signal region capture logic to find tracebacks, `FATAL ERROR` banners, and trailing exit codes.
- Implement the 8KB windowing cap to bound the final excerpt.
- **Test**: Run against mocked log strings to verify noise is dropped and signal is kept.

### Step 3 — MCP Tool Interface (Implement)
- Create `src/tools/error_analysis.py`.
- Register the `extract_ci_error_signal` tool.
- Wire the tool to read a file path, pass it through the extractor and classifier, and return the `ErrorRecord`.
- **Test**: Call the tool programmatically and assert the structure of the returned payload.

### Step 4 — Unit Testing & Fixtures (Validate)
- Utilize the comprehensive log corpus located at `/mcp_rag_eib/ERROR_LOGS/ci/error_logs` to derive representative fixture logs covering all major taxonomy classes.
- Copy a representative subset of these logs to `tests/unit/fixtures/error_logs/` to act as permanent unit test fixtures.
- Write unit tests in `test_error_analysis.py` for the extractor, classifier, and tool wrapper.
- **Test**: `pytest tests/unit/test_error_analysis.py` passes 100%.

### Step 5 — Document & Changelog (Document)
- Update `CHANGELOG.md` with a dated entry detailing the new log distillation tool.
- **Test**: CHANGELOG entry present with dated header.

---

## 5. Design & Architecture

### 5.1 Distillation Strategy (The Core Algorithm)

Logs are largely bash `set -x` traces; failures surface near the **end**. The extractor must mechanically perform what the LLM used to do via brute force:

1. **Drop Noise**: Filter out environment dumps (`declare -rx`, `export FOO=`), base64 `_ModuleTable*` blocks, module-load chatter, and PS4-prefixed traces that carry no error tokens.
2. **Capture Signal Regions**:
   - Full Python `Traceback ... Error` blocks.
   - `err_exit.sh` `FATAL ERROR` banners.
   - Lines matching taxonomy markers.
   - The final `status=`/`exit`/`RETURN CODE`/`error code` tail.
3. **Window + Cap**: Keep a bounded excerpt (capped at **8 KB**) preferring the tail to ensure it safely fits into standard LLM context windows.

### 5.2 Failure Taxonomy v1

Ordered, first-match-wins classification in `src/error_analysis/classifier.py`:

| Class | Primary signals |
|-------|-----------------|
| `hpss_fetch` | `HTAR FAILED`, `Connection refused` + HPSS, `htar returned non-zero` |
| `build` | `cmake`/`make` errors, `undefined reference`, `Error 1` |
| `forecast_model` | UFS/`fcst` aborts, `MPI_ABORT`, `forrtl:`, model `FATAL` |
| `timeout` | `DUE TO TIME LIMIT`, `CANCELLED`, walltime exceeded |
| `oom` | `Out of memory`, `oom-kill`, `Killed` |
| `segfault` | `Segmentation fault`, signal 11 |
| `missing_file` | `No such file or directory`, `cannot stat` |
| `rocoto` | `rocotostat`/`rocoto` dryrun failures |
| `python_traceback` | generic `Traceback (most recent call last)` |
| `unknown` | fallback |

### 5.3 The MCP Tool Interface

**Tool**: `extract_ci_error_signal` *(Note: The tool extracts; the LLM analyzes)*
**Parameters**:
- `log_path` (string, required): Absolute path to the raw log file.
- `format` (string, optional, default "json"): Output format. JSON is preferred for programmatic LLM evaluation.

**Response Surface (LLM-Optimized)**: 
Instead of a human-readable summary, the tool returns a dense, structured payload designed to feed an LLM's reasoning engine. Crucially, this output is intended to be combined with GraphRAG discovery. The LLM consumes this signal and then autonomously iterates—using other MCP tools to trace the error backward across documentation, runbooks, and issue histories.
- `taxonomy_class`: The first-match classification (e.g., 'oom', 'segfault').
- `exit_code`: The captured exit status.
- `diagnostic_signal`: The raw, unaltered traceback, FATAL ERROR banner, or trailing lines (strictly capped at 8KB). 
- `omitted_bytes`: How much noise was stripped.
- `extracted_symbols`: (Optional) Potential function names/scripts detected.
- `recommended_next_steps`: (Optional) Suggested vectors for the LLM's next search.

---

## 6. Artifacts Produced

| Artifact | Path | Purpose |
|----------|------|---------|
| Schema | `src/error_analysis/schema.py` | Defines `ErrorRecord` dataclass |
| Extractor | `src/error_analysis/extractor.py` | Noise filters, signal-region capture, 8KB cap |
| Classifier | `src/error_analysis/classifier.py` | Ordered taxonomy table & `classify()` |
| MCP Tool | `src/tools/error_analysis.py` | `extract_ci_error_signal` LLM-optimized surface |
| Unit Tests & Fixtures | `tests/unit/fixtures/error_logs/` & `test_error_analysis.py` | Validate extraction and classification |
| Changelog | `CHANGELOG.md` | Version and feature documentation |

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Logs without recognizable error footprints | Keep the trailing 8KB tail even if taxonomy falls back to `unknown`. |
| Unusually dense noise regions bypassing filters | Iterate noise filter regexes based on observed fixture failures. |
| Context limit blown | Strictly enforce the 8KB maximum extraction size, truncating `diagnostic_signal` before returning. |
