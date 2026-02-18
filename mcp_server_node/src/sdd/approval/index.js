/**
 * DORMANT — Reserved for CLI/YOLO execution modality (Phase 4C USD)
 * Not imported by SDDWorkflowTools in IDE mode (Phase 31 session model).
 * Will be re-imported when Claude CLI / GitHub CLI autonomous execution is built.
 *
 * Approval Providers Index
 * 
 * Export all approval provider implementations for Phase 4B ISD
 * 
 * Version: 3.0.0
 * Phase: 4C - Verb+Noun Paradigm
 * Date: January 8, 2026
 * 
 * Providers:
 * - MCPApprovalProvider: Multi-turn MCP tool calls (VS Code Copilot, Claude Desktop)
 * - CLIApprovalProvider: Terminal readline prompts (Claude Code, SSH)
 * - ManifestApprovalProvider: Pre-approved patterns from YAML/JSON files (CI/CD)
 */

export { 
  ApprovalProvider, 
  ApprovalResult, 
  ExecutionMode,
  // V2.0 Verb-based exports
  SIDE_EFFECT_VERBS,
  READ_ONLY_VERBS,
  LEGACY_TYPE_MAP,
  getVerb,
  hasSideEffects,
  isReadOnly,
  // Legacy arrays (deprecated but still exported for backward compat)
  SIDE_EFFECT_TYPES,
  READ_ONLY_TYPES 
} from './ApprovalProvider.js';

export { MCPApprovalProvider } from './MCPApprovalProvider.js';
export { CLIApprovalProvider } from './CLIApprovalProvider.js';
export { ManifestApprovalProvider, createManifest } from './ManifestApprovalProvider.js';
export { ExecutionStateStore, getDefaultStore } from './ExecutionStateStore.js';
