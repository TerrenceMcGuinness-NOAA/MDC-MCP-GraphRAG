# CI Error Log Reporting Policy (MCP Toolset Guidelines)

**Directive**: When tasked with analyzing CI error logs, the AI Agent should **primarily** utilize the `agentcore-mcp-rag` toolset and output a formal Markdown report mimicking the high-quality format defined in the NOAA Global Workflow knowledge base.

## 1. Tool Usage Guidelines

You should **prefer** using the MCP tools over `run_in_terminal` to investigate error logs or the codebase. Your first line of investigation should leverage the following:

1. **Signal Extraction**: Use the `extract_ci_error_signal` MCP tool to instantly distill the 8KB high-entropy signal from the massive raw log file and correctly classify the taxonomy.
2. **Context Retrieval**: Use the `search_issues`, `get_pull_requests`, or `search_documentation` tools to pull contextual background related to the error (using PR numbers, issue hashes, or error strings).
3. **Code Awareness**: If deeper code tracing is needed based on the signal, prioritize the GraphRAG and Code Analysis MCP tools (e.g., `analyze_code_structure`, `find_dependencies`, `trace_execution_path`, `find_env_dependencies`).

**Fallback Permitted**: We recognize there can be drift in the GraphRAG indices or that further on-the-fly insights may require direct codebase inspection. If the MCP tools are insufficient, out of sync, or you need to inspect the absolute current ground-truth, you are permitted to use `run_in_terminal` to explore the multi-tenant codebase on disk (e.g., via the `.pw_workflow_mount/<tenant>/` mappings).

Every analysis task must end with a formal tally evaluating the effectiveness of the MCP tools utilized during the session.

---

## 2. Report Output Requirements

The final output must be saved as a `.md` file inside `/mcp_rag_eib/ERROR_LOGS/reports/`.
The filename must include field identifiers for reference (e.g., `report_PR<NUMBER>_<TAXONOMY>_<SCRIPT_NAME>.md`).

### Required Report Structure

The generated report must rigidly adhere to the following Markdown structure, modeled after Claude's high-quality analysis:

```markdown
# [JOB_NAME or PR_NAME] [Taxonomy Class] — Failure Analysis and Best Practices

**Date**: [Current Date]
**Failed Job**: [Job/PR Identifier]
**Source Log**: [Path to log]
**Tooling Used**: `agentcore-mcp-rag` MCP server

## Executive Summary
A concise summary (3-4 sentences) explaining exactly what job failed, the core infrastructure or code reason it failed, and what step the failure occurred on. If there were cascading issues (e.g., deleted directories making triage harder), mention them here.

## What Happened
### Sequence of Events
A timeline of the failure, tracking what the workflow was doing immediately prior to the crash.

### The Failing Line
Include the exact snippet from the `diagnostic_signal` that represents the crash.
` ` `bash
[Insert the exact crash output from the extractor tool]
` ` `

## Root Cause Analysis
Explain *why* the failure occurred based on the extracted signal and GitHub Issue/PR context. If it was a system flake (like an HPSS timeout or Lustre ESTALE) vs a hard code error (like a missing module or syntax error), explicitly distinguish that here.

## Code-Level Tracing (GraphRAG Insights)
When analyzing code or build failures, do not stop at the bash traceback. **YOU are the autonomous agent.** You MUST execute the GraphRAG tools (`find_callers_callees`, `find_env_dependencies`, `analyze_code_structure`, etc.) during the creation of the report. 

Do NOT write placeholders like "An agent should execute X". You must actually run the tool, analyze the output, and document the *actual* root cause, the direct computational neighbors, and the architectural relationships that failed. The report must contain the final, synthesized conclusions of your code tracing.

## Suggested Fix / Best Practices That Prevent This
Concrete recommendations on how to remediate the issue.
- If it's a code fix, provide the exact lines to change.
- If it's an infrastructure flake, provide best practices (e.g., bounded retries, `KEEPDATA_ON_FAILURE` flags, or increasing Wallclock time limits).

## MCP Tool Effectiveness Tally
A Markdown table explicitly logging the MCP tools you used to derive this report, and your assessment of their value, including accuracy, for the specific run.

| Tool Invoked | Parameters | Accuracy & Effectiveness Rating | Notes & Recommendations |
| :--- | :--- | :--- | :--- |
| `extract_ci_error_signal` | `log_path: ...` | ... | ... |
| `search_issues` | `query: ...` | ... | ... |
```