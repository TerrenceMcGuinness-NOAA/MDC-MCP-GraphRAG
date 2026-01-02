/**
 * ManifestApprovalProvider - Approval via pre-defined YAML/JSON manifests
 * 
 * For CI/CD pipelines, GitHub Actions, and batch operations:
 * - Reads approval rules from manifest file
 * - Supports glob patterns for step matching
 * - Enables unattended workflow execution with guardrails
 * 
 * Version: 1.0.0
 * Phase: 4B - Interactive Supervised Development
 * Date: January 2, 2026
 */

import fs from 'fs';
import path from 'path';
import { 
  ApprovalProvider, 
  ApprovalResult, 
  ExecutionMode,
  SIDE_EFFECT_TYPES
} from './ApprovalProvider.js';

/**
 * Manifest Approval Provider
 * Uses pre-defined rules for automated approval decisions
 */
export class ManifestApprovalProvider extends ApprovalProvider {
  constructor(options = {}) {
    super(options);
    this.manifestPath = options.manifestPath || null;
    this.manifest = options.manifest || null;
    this.defaultAction = options.defaultAction || 'skip'; // skip, approve, deny
    this.rules = [];
    
    // Load manifest if path provided
    if (this.manifestPath) {
      this.loadManifest(this.manifestPath);
    } else if (this.manifest) {
      this.parseManifest(this.manifest);
    }
  }

  /**
   * Check provider capabilities
   */
  getCapabilities() {
    return {
      interactive: false,
      multiTurn: false,
      richPreview: false,
      diffView: false,
      timeout: this.timeout
    };
  }

  /**
   * Check if provider is interactive
   */
  isInteractive() {
    return false;
  }

  /**
   * Load manifest from file
   * @param {string} manifestPath - Path to manifest file (JSON or YAML)
   */
  loadManifest(manifestPath) {
    try {
      if (!fs.existsSync(manifestPath)) {
        throw new Error(`Manifest file not found: ${manifestPath}`);
      }

      const content = fs.readFileSync(manifestPath, 'utf-8');
      const ext = path.extname(manifestPath).toLowerCase();

      if (ext === '.json') {
        this.parseManifest(JSON.parse(content));
      } else if (ext === '.yaml' || ext === '.yml') {
        // Simple YAML parsing for common patterns
        // For full YAML support, would need js-yaml package
        this.parseSimpleYAML(content);
      } else {
        // Try JSON first, then simple YAML
        try {
          this.parseManifest(JSON.parse(content));
        } catch {
          this.parseSimpleYAML(content);
        }
      }

      console.log(`[ManifestApprovalProvider] Loaded ${this.rules.length} rules from ${manifestPath}`);
    } catch (error) {
      console.error(`[ManifestApprovalProvider] Failed to load manifest: ${error.message}`);
      throw error;
    }
  }

  /**
   * Parse manifest object
   * @param {Object} manifest - Manifest configuration
   */
  parseManifest(manifest) {
    this.manifest = manifest;
    this.rules = [];

    // Global settings
    if (manifest.default_action) {
      this.defaultAction = manifest.default_action;
    }

    if (manifest.auto_approve_types) {
      this.autoApproveTypes = manifest.auto_approve_types;
    }

    if (manifest.deny_types) {
      this.denyTypes = manifest.deny_types;
    }

    // Parse rules
    if (manifest.rules && Array.isArray(manifest.rules)) {
      for (const rule of manifest.rules) {
        this.rules.push({
          pattern: rule.pattern || rule.step || '*',
          type: rule.type || null,
          action: rule.action || 'approve',
          condition: rule.condition || null,
          reason: rule.reason || 'Matched manifest rule'
        });
      }
    }

    // Parse workflow-specific rules
    if (manifest.workflows && typeof manifest.workflows === 'object') {
      for (const [workflowName, workflowRules] of Object.entries(manifest.workflows)) {
        if (workflowRules.rules) {
          for (const rule of workflowRules.rules) {
            this.rules.push({
              workflow: workflowName,
              pattern: rule.pattern || rule.step || '*',
              type: rule.type || null,
              action: rule.action || 'approve',
              condition: rule.condition || null,
              reason: rule.reason || `Matched workflow rule: ${workflowName}`
            });
          }
        }
      }
    }
  }

  /**
   * Simple YAML parser for basic manifests
   * @param {string} content - YAML content
   */
  parseSimpleYAML(content) {
    // Very basic YAML parsing - handles simple key: value and lists
    const manifest = {
      rules: [],
      auto_approve_types: [],
      deny_types: []
    };

    const lines = content.split('\n');
    let currentSection = null;
    let currentRule = null;

    for (const line of lines) {
      const trimmed = line.trim();
      
      // Skip comments and empty lines
      if (trimmed.startsWith('#') || trimmed === '') continue;

      // Section headers
      if (trimmed === 'rules:') {
        currentSection = 'rules';
        continue;
      }
      if (trimmed === 'auto_approve_types:') {
        currentSection = 'auto_approve_types';
        continue;
      }
      if (trimmed === 'deny_types:') {
        currentSection = 'deny_types';
        continue;
      }
      if (trimmed.match(/^default_action:\s*(.+)$/)) {
        manifest.default_action = trimmed.split(':')[1].trim();
        continue;
      }

      // List items
      if (trimmed.startsWith('- ')) {
        const value = trimmed.substring(2).trim();
        
        if (currentSection === 'auto_approve_types' || currentSection === 'deny_types') {
          manifest[currentSection].push(value);
        } else if (currentSection === 'rules') {
          // New rule
          if (currentRule) {
            manifest.rules.push(currentRule);
          }
          currentRule = { pattern: value };
        }
        continue;
      }

      // Rule properties (indented key: value)
      if (currentRule && trimmed.includes(':')) {
        const [key, ...valueParts] = trimmed.split(':');
        const keyTrimmed = key.trim();
        const valueTrimmed = valueParts.join(':').trim();
        
        if (['pattern', 'type', 'action', 'reason'].includes(keyTrimmed)) {
          currentRule[keyTrimmed] = valueTrimmed;
        }
      }
    }

    // Don't forget last rule
    if (currentRule) {
      manifest.rules.push(currentRule);
    }

    this.parseManifest(manifest);
  }

  /**
   * Match step against pattern
   * @param {string} stepName - Step name to match
   * @param {string} pattern - Glob-like pattern
   * @returns {boolean}
   */
  matchPattern(stepName, pattern) {
    if (pattern === '*') return true;
    if (pattern === stepName) return true;
    
    // Simple glob: * matches anything
    const regexPattern = pattern
      .replace(/[.+^${}()|[\]\\]/g, '\\$&') // Escape special chars
      .replace(/\*/g, '.*')                  // * -> .*
      .replace(/\?/g, '.');                  // ? -> .
    
    const regex = new RegExp(`^${regexPattern}$`, 'i');
    return regex.test(stepName);
  }

  /**
   * Find matching rule for step
   * @param {Object} step - Step metadata
   * @param {string} workflowName - Current workflow name
   * @returns {Object|null} Matching rule or null
   */
  findMatchingRule(step, workflowName = null) {
    for (const rule of this.rules) {
      // Check workflow constraint
      if (rule.workflow && rule.workflow !== workflowName) {
        continue;
      }

      // Check type constraint
      if (rule.type && rule.type !== step.type) {
        continue;
      }

      // Check pattern match
      if (this.matchPattern(step.name, rule.pattern)) {
        return rule;
      }
    }

    return null;
  }

  /**
   * Request approval via manifest rules
   * 
   * @param {Object} step - Step metadata
   * @param {Object} preview - Preview of what will happen
   * @returns {Promise<ApprovalResult>}
   */
  async requestApproval(step, preview) {
    // Check deny list first
    if (this.denyTypes.includes(step.type)) {
      this.logAudit(step, 'denied', 'Step type in deny list');
      console.log(`[ManifestApprovalProvider] DENIED: ${step.name} (type in deny list)`);
      return ApprovalResult.SKIPPED;
    }

    // Check auto-approve types
    if (this.autoApproveTypes.includes(step.type)) {
      this.logAudit(step, 'auto_approved', 'Step type in auto-approve list');
      console.log(`[ManifestApprovalProvider] AUTO-APPROVED: ${step.name} (type in auto-approve list)`);
      return ApprovalResult.APPROVED;
    }

    // Find matching rule
    const rule = this.findMatchingRule(step, this.manifest?.workflow_name);

    if (rule) {
      const action = rule.action.toLowerCase();
      
      switch (action) {
        case 'approve':
        case 'approved':
        case 'yes':
          this.logAudit(step, 'approved', rule.reason);
          console.log(`[ManifestApprovalProvider] APPROVED: ${step.name} (${rule.reason})`);
          return ApprovalResult.APPROVED;

        case 'skip':
        case 'skipped':
        case 'no':
          this.logAudit(step, 'skipped', rule.reason);
          console.log(`[ManifestApprovalProvider] SKIPPED: ${step.name} (${rule.reason})`);
          return ApprovalResult.SKIPPED;

        case 'deny':
        case 'denied':
        case 'reject':
          this.logAudit(step, 'denied', rule.reason);
          console.log(`[ManifestApprovalProvider] DENIED: ${step.name} (${rule.reason})`);
          return ApprovalResult.QUIT;

        default:
          // Unknown action, use default
          break;
      }
    }

    // No matching rule - use default action
    const defaultResult = this.getDefaultResult();
    this.logAudit(step, defaultResult, `Default action: ${this.defaultAction}`);
    console.log(`[ManifestApprovalProvider] DEFAULT (${this.defaultAction}): ${step.name}`);
    
    return defaultResult;
  }

  /**
   * Get approval result for default action
   * @returns {ApprovalResult}
   */
  getDefaultResult() {
    switch (this.defaultAction) {
      case 'approve':
      case 'approved':
      case 'yes':
        return ApprovalResult.APPROVED;

      case 'deny':
      case 'denied':
      case 'quit':
      case 'abort':
        return ApprovalResult.QUIT;

      case 'skip':
      case 'skipped':
      case 'no':
      default:
        return ApprovalResult.SKIPPED;
    }
  }

  /**
   * Get manifest summary
   * @returns {Object}
   */
  getSummary() {
    return {
      manifestPath: this.manifestPath,
      defaultAction: this.defaultAction,
      ruleCount: this.rules.length,
      autoApproveTypes: this.autoApproveTypes,
      denyTypes: this.denyTypes,
      rules: this.rules.map(r => ({
        pattern: r.pattern,
        type: r.type,
        action: r.action,
        workflow: r.workflow
      }))
    };
  }
}

/**
 * Create manifest from common patterns
 */
export function createManifest(options = {}) {
  const {
    defaultAction = 'skip',
    autoApproveTypes = ['health_check', 'validation', 'data_query'],
    denyTypes = [],
    approvePatterns = [],
    skipPatterns = [],
    workflowName = null
  } = options;

  const manifest = {
    default_action: defaultAction,
    auto_approve_types: autoApproveTypes,
    deny_types: denyTypes,
    rules: []
  };

  // Add approve patterns
  for (const pattern of approvePatterns) {
    manifest.rules.push({
      pattern,
      action: 'approve',
      reason: 'Pre-approved pattern'
    });
  }

  // Add skip patterns
  for (const pattern of skipPatterns) {
    manifest.rules.push({
      pattern,
      action: 'skip',
      reason: 'Pre-skipped pattern'
    });
  }

  if (workflowName) {
    manifest.workflow_name = workflowName;
  }

  return manifest;
}

export default ManifestApprovalProvider;
