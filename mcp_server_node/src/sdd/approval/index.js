/**
 * Approval Providers Index
 * 
 * Export all approval provider implementations
 * 
 * Version: 1.0.0
 * Phase: 4B - Interactive Supervised Execution
 */

export { 
  ApprovalProvider, 
  ApprovalResult, 
  ExecutionMode,
  SIDE_EFFECT_TYPES,
  READ_ONLY_TYPES 
} from './ApprovalProvider.js';

export { MCPApprovalProvider } from './MCPApprovalProvider.js';

// Future providers (stubs for now)
// export { CLIApprovalProvider } from './CLIApprovalProvider.js';
// export { ManifestApprovalProvider } from './ManifestApprovalProvider.js';
