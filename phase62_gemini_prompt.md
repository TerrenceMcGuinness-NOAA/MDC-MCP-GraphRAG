# Gemini CLI Implementation Prompt for Phase 62

**Role Context**: You are an expert Python developer contributing to the NOAA Global Workflow AI Assistant (an MCP server). Your current task is to implement the code for **Phase 62 (CI Error-Log Distillation & MCP Tool)** strictly adhering to the SDD methodology.

**Input Context**:
Please read the specification located at: `sdd_framework/workflows/phase62_ci_error_log_processing.md`.
This specification outlines the goals, constraints, and architecture for a new error log distillation library and MCP tool.

**Task Requirements**:
Please generate the complete Python code to satisfy the Deliverables for Phase 62. Ensure your code is production-ready, uses type hints (`typing`), includes numpy-style docstrings, and handles missing files/errors gracefully.

Please create or update the following 5 files:

1. **`mcp_server_python/src/error_analysis/schema.py`**
   - Create a Python `dataclass` named `ErrorRecord`.
   - Include fields corresponding to the LLM-optimized response surface: `taxonomy_class` (str), `exit_code` (str/int, optional), `diagnostic_signal` (str), `omitted_bytes` (int), `extracted_symbols` (list[str], optional), and `recommended_next_steps` (list[str], optional).

2. **`mcp_server_python/src/error_analysis/classifier.py`**
   - Implement the ordered failure taxonomy mapping as defined in the spec.
   - Provide a `classify(log_text: str) -> str` function that scans the text and returns the first matching taxonomy class (e.g., 'hpss_fetch', 'oom', 'build') or 'unknown' as a fallback.

3. **`mcp_server_python/src/error_analysis/extractor.py`**
   - Implement `extract_signal(log_text: str) -> dict`.
   - **Noise Filtering**: Use regex to strip low-entropy lines (e.g., `declare -rx`, `export FOO=`, base64 `_ModuleTable*` blocks).
   - **Signal Capture**: Locate high-entropy regions like Python tracebacks, `FATAL ERROR` banners, and trailing exit codes.
   - **8KB Cap Constraint**: Strictly limit the final `diagnostic_signal` to a maximum of 8192 bytes. Truncate from the top/middle if necessary to ensure the tail (where the actual crash usually is) is preserved. Track how many bytes were dropped in `omitted_bytes`.

4. **`mcp_server_python/src/tools/error_analysis.py`**
   - Expose the distillation logic as an MCP tool named `extract_ci_error_signal`.
   - It must accept `log_path` (str) as an argument.
   - Read the log file, process it through the extractor and classifier, instantiate an `ErrorRecord`, and return its JSON representation.

5. **`mcp_server_python/tests/unit/test_error_analysis.py`**
   - Write unit tests covering the `classifier`, `extractor`, and the MCP tool logic.
   - Assume there are sample log files available in `mcp_server_python/tests/unit/fixtures/error_logs/` and write tests that load these files to validate extraction constraints (e.g., testing that the output never exceeds 8KB and correctly drops base64 noise).

**Output constraints**:
Provide the raw Python code for each file inside standard markdown code blocks, clearly labeled with the target filepath.