# Execution State Directory

This directory contains persistent state files for multi-turn workflow executions.

## File Format

Each execution state is stored as `<execution_id>.json` with the following structure:

```json
{
  "executionId": "exec_1735848000_abc123",
  "workflowName": "bootstrap_capability_demo",
  "currentStepIndex": 3,
  "totalSteps": 8,
  "results": { ... },
  "startTime": 1735848000000,
  "savedAt": 1735848100000,
  "expiresAt": 1735848400000
}
```

## TTL (Time-To-Live)

- Default TTL: 5 minutes (300,000ms)
- States are automatically cleaned up when expired
- Maximum states retained: 100

## Managed By

- `ExecutionStateStore.js` - File-based persistence layer
- `MCPApprovalProvider.js` - Uses store for multi-turn MCP flows

## Do Not Edit Manually

These files are managed programmatically. Manual edits may corrupt workflow state.
