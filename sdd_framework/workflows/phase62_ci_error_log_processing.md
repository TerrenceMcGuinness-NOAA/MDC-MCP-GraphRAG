# Phase 62 — CI Error-Log Distillation & MCP Tool

**Version**: 2.0.0 (Revised)
**Created**: 2026-06-26
**Status**: ready
**Estimated effort**: 1–2 days
**Depends on**: none

---

## Problem Statement & Historical Context

Automating the diagnosis of NOAA Global Workflow CI failures has been a long-standing goal. Historically, operators manually copied massive raw logs (often tens of megabytes) into GitHub Gists and fed them into LLMs (like Claude Opus) with detailed prompts to generate markdown summaries for PRs. While models with massive context windows and internal reasoning/bisecting capabilities could eventually chew through these giant gists, this approach is fundamentally incompatible with automated, fast-iteration systems like the **Ralph Loop**. When attempting to feed these raw logs into standard context windows (e.g., via the Gemini CLI), the context limit is immediately blown.

Furthermore, integrating an MCP endpoint directly into the live CI pipeline to catch these errors in real-time is currently blocked by heavy FedRAMP and AWS Bedrock governance requirements. 

**The Pivot:**
Instead of building a massive offline batch-processing pipeline for a 2GB corpus (as originally planned), we must focus on **immediate, on-demand distillation**. We need to lock down the error log preprocessing step into a deterministic library and expose it *immediately* as a new MCP tool. This tool will bridge the gap: allowing operators and the Ralph Loop to point at a massive log file and receive a highly compressed, distilled signal without blowing out the context window.

---

## Goals / Non-Goals

### Goals
- A reusable **distillation library** (`src/error_analysis/`) that strips out Bash noise and captures the actual error signal.
- A **stable normalized record schema** (the SPOT) for error representation.
- A foundational failure **taxonomy** grounded in known NOAA workflow failures.
- A dedicated MCP Tool (`extract_ci_error_signal`) designed *specifically for LLM consumption*. The tool performs mechanical distillation (dropping noise) to fit the context window, outputting a high-entropy, dense JSON/markdown payload that preserves the raw traceback and stack context so the LLM can perform the actual reasoning and root-cause analysis.
- **Tests** using small, checked-in fixture logs representing major failure classes.

### Non-Goals (explicit)
- **NO direct CI pipeline integration** (deferred due to AWS/FedRAMP governance).
- **NO batch corpus processing** (syncing and distilling the 2GB offline data lake is deferred; focus is on on-demand tool usage).
- No remediation/auto-fix suggestion logic (the tool provides the *distilled signal*; the LLM provides the fix).

---

## Design

### Distillation Strategy (The Core Algorithm)

Logs are largely bash `set -x` traces; failures surface near the **end**. The extractor must mechanically perform what the LLM used to do via brute force:

1. **Drop Noise**: Filter out environment dumps (`declare -rx`, `export FOO=`), base64 `_ModuleTable*` blocks, module-load chatter, and PS4-prefixed traces that carry no error tokens.
2. **Capture Signal Regions**:
   - Full Python `Traceback ... Error` blocks.
   - `err_exit.sh` `FATAL ERROR` banners.
   - Lines matching taxonomy markers.
   - The final `status=`/`exit`/`RETURN CODE`/`error code` tail.
3. **Window + Cap**: Keep a bounded excerpt (capped at **8 KB**) preferring the tail to ensure it safely fits into standard LLM context windows.

### Failure Taxonomy v1

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

### The MCP Tool Interface

**Tool**: `extract_ci_error_signal` *(Note: The tool extracts; the LLM analyzes)*
**Parameters**:
- `log_path` (string, required): Absolute path to the raw log file.
- `format` (string, optional, default "json"): Output format. JSON is preferred for programmatic LLM evaluation (e.g., Ralph Loop).

**Response Surface (LLM-Optimized)**: 
Instead of a human-readable summary, the tool returns a dense, structured payload designed to feed an LLM's reasoning engine. Crucially, this output is intended to be combined with GraphRAG discovery. The LLM consumes this signal and then autonomously iterates—using other MCP tools (like `analyze_code_structure` or `search_documentation`) to trace the error backward not just into the codebase, but across documentation, runbooks, and issue histories to gain the additional insight required to accurately focus its attention for root-cause analysis.
- `taxonomy_class`: The first-match classification (e.g., 'oom', 'segfault').
- `exit_code`: The captured exit status.
- `diagnostic_signal`: The raw, unaltered traceback, FATAL ERROR banner, or trailing lines (strictly capped at 8KB). 
- `omitted_bytes`: How much noise was stripped (provides confidence to the LLM on truncation).
- `extracted_symbols`: (Optional/Heuristic) A list of potential function names, scripts, or module paths detected within the traceback, explicitly designed to serve as immediate search keys for GraphRAG tools.
- `recommended_next_steps`: (Optional/Heuristic) A suggested vector for the LLM's next search (e.g., "Scan the original error log's surrounding bytes," "Query EE2 standards for error-handling compliance," or "Use Code Awareness tools to map the failing module's callers").

**Behaviour**: Mechanically strips low-entropy noise (base64, env dumps) to defeat context limits, preserving the high-entropy diagnostic signal for backend LLM reasoning.

---

## Deliverables Catalogue

| # | File | Deliverable | Effort |
|---|------|-------------|--------|
| D1 | `src/error_analysis/schema.py` | `ErrorRecord` dataclass | 1 h |
| D2 | `src/error_analysis/extractor.py` | Noise filters, signal-region capture, 8KB windowing cap | 3 h |
| D3 | `src/error_analysis/classifier.py` | Ordered taxonomy table (SPOT) + `classify()` | 1 h |
| D4 | `src/tools/error_analysis.py` | MCP Tool module: `extract_ci_error_signal` (LLM-optimized response surface) | 2 h |
| D5 | `tests/unit/fixtures/error_logs/` + `test_error_analysis.py` | Fixture logs (hpss_fetch, build, forecast, traceback) + unit tests | 3 h |
| D6 | `CHANGELOG.md` | Dated entry | 15 m |

---
