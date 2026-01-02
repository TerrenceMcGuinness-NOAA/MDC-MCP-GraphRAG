/**
 * Approval Providers Index
 * 
 * Export all approval provider implementations for Phase 4B ISD
 * 
 * Version: 2.0.0
 * Phase: 4B - Interactive Supervised Development
 * Date: January 2, 2026
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
  SIDE_EFFECT_TYPES,
  READ_ONLY_TYPES 
} from './ApprovalProvider.js';

export { MCPApprovalProvider } from './MCPApprovalProvider.js';
export { CLIApprovalProvider } from './CLIApprovalProvider.js';
export { ManifestApprovalProvider, createManifest } from './ManifestApprovalProvider.js';
export { ExecutionStateStore, getDefaultStore } from './ExecutionStateStore.js';
