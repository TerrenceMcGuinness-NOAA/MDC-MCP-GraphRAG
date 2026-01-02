/**
 * CLIApprovalProvider - Approval via terminal readline prompts
 * 
 * For Claude Code, SSH sessions, and terminal-based workflows:
 * - Uses Node.js readline for interactive prompts
 * - Synchronous approval flow (blocks until user responds)
 * - Color-coded output for better visibility
 * 
 * Version: 1.0.0
 * Phase: 4B - Interactive Supervised Development
 * Date: January 2, 2026
 */

import readline from 'readline';
import { 
  ApprovalProvider, 
  ApprovalResult, 
  ExecutionMode,
  SIDE_EFFECT_TYPES
} from './ApprovalProvider.js';

/**
 * ANSI color codes for terminal output
 */
const COLORS = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  white: '\x1b[37m',
  bgRed: '\x1b[41m',
  bgYellow: '\x1b[43m'
};

/**
 * CLI Approval Provider
 * Uses terminal readline for interactive approval prompts
 */
export class CLIApprovalProvider extends ApprovalProvider {
  constructor(options = {}) {
    super(options);
    this.useColors = options.useColors !== false;
    this.inputStream = options.inputStream || process.stdin;
    this.outputStream = options.outputStream || process.stdout;
    this.rl = null;
  }

  /**
   * Check provider capabilities
   */
  getCapabilities() {
    return {
      interactive: true,
      multiTurn: false, // Synchronous, blocks until response
      richPreview: true,
      diffView: false,
      timeout: this.timeout
    };
  }

  /**
   * Check if provider is interactive
   */
  isInteractive() {
    return true;
  }

  /**
   * Color helper
   */
  color(text, ...codes) {
    if (!this.useColors) return text;
    const colorCodes = codes.map(c => COLORS[c] || '').join('');
    return `${colorCodes}${text}${COLORS.reset}`;
  }

  /**
   * Print to output stream
   */
  print(text) {
    this.outputStream.write(text + '\n');
  }

  /**
   * Print separator line
   */
  printSeparator(char = '─', width = 65) {
    this.print(this.color(char.repeat(width), 'dim'));
  }

  /**
   * Format preview for CLI display with colors
   */
  formatPreviewCLI(preview) {
    const lines = [];
    
    lines.push('');
    lines.push(this.color('┌' + '─'.repeat(63) + '┐', 'cyan'));
    lines.push(this.color('│', 'cyan') + this.color(' APPROVAL REQUIRED', 'bold', 'yellow') + ' '.repeat(44) + this.color('│', 'cyan'));
    lines.push(this.color('├' + '─'.repeat(63) + '┤', 'cyan'));
    
    lines.push(this.color('│', 'cyan') + ` Step:   ${this.color(preview.stepName, 'bold')}`.padEnd(72) + this.color('│', 'cyan'));
    lines.push(this.color('│', 'cyan') + ` Type:   ${preview.stepType}`.padEnd(72) + this.color('│', 'cyan'));
    lines.push(this.color('│', 'cyan') + ` Action: ${this.color(preview.action, 'magenta')}`.padEnd(80) + this.color('│', 'cyan'));

    if (preview.target) {
      lines.push(this.color('│', 'cyan') + ` Target: ${preview.target}`.padEnd(72) + this.color('│', 'cyan'));
    }

    if (preview.command) {
      lines.push(this.color('│', 'cyan') + ` Command: ${this.color(preview.command, 'yellow')}`.padEnd(80) + this.color('│', 'cyan'));
    }

    if (preview.riskLevel) {
      const riskColor = preview.riskLevel === 'high' ? 'red' : 
                        preview.riskLevel === 'medium' ? 'yellow' : 'green';
      const riskIcon = preview.riskLevel === 'high' ? '[!]' : 
                       preview.riskLevel === 'medium' ? '[~]' : '[.]';
      lines.push(this.color('│', 'cyan') + ` Risk:   ${this.color(riskIcon + ' ' + preview.riskLevel.toUpperCase(), riskColor)}`.padEnd(80) + this.color('│', 'cyan'));
    }

    if (preview.contentPreview) {
      lines.push(this.color('├' + '─'.repeat(63) + '┤', 'cyan'));
      lines.push(this.color('│', 'cyan') + this.color(' Content Preview:', 'dim') + ' '.repeat(46) + this.color('│', 'cyan'));
      
      const contentLines = preview.contentPreview.split('\n').slice(0, 8);
      for (const line of contentLines) {
        const truncated = line.substring(0, 60);
        lines.push(this.color('│', 'cyan') + `   ${this.color(truncated, 'dim')}`.padEnd(72) + this.color('│', 'cyan'));
      }
      
      if (preview.truncated) {
        lines.push(this.color('│', 'cyan') + this.color(`   ... (${preview.contentLength} total characters)`, 'dim').padEnd(72) + this.color('│', 'cyan'));
      }
    }

    lines.push(this.color('├' + '─'.repeat(63) + '┤', 'cyan'));
    lines.push(this.color('│', 'cyan') + ' Options:' + ' '.repeat(54) + this.color('│', 'cyan'));
    lines.push(this.color('│', 'cyan') + `   ${this.color('y/yes/a', 'green')}     - Execute this step` + ' '.repeat(29) + this.color('│', 'cyan'));
    lines.push(this.color('│', 'cyan') + `   ${this.color('n/no/s', 'yellow')}      - Skip this step, continue workflow` + ' '.repeat(13) + this.color('│', 'cyan'));
    lines.push(this.color('│', 'cyan') + `   ${this.color('q/quit', 'red')}      - Abort entire workflow` + ' '.repeat(23) + this.color('│', 'cyan'));
    lines.push(this.color('│', 'cyan') + `   ${this.color('all', 'magenta')}         - Approve all remaining steps` + ' '.repeat(17) + this.color('│', 'cyan'));
    lines.push(this.color('└' + '─'.repeat(63) + '┘', 'cyan'));
    lines.push('');

    return lines.join('\n');
  }

  /**
   * Create readline interface
   */
  createReadline() {
    if (this.rl) return this.rl;
    
    this.rl = readline.createInterface({
      input: this.inputStream,
      output: this.outputStream
    });

    return this.rl;
  }

  /**
   * Close readline interface
   */
  closeReadline() {
    if (this.rl) {
      this.rl.close();
      this.rl = null;
    }
  }

  /**
   * Prompt user for input
   * @param {string} prompt - Prompt text
   * @returns {Promise<string>} User input
   */
  async prompt(promptText) {
    return new Promise((resolve, reject) => {
      const rl = this.createReadline();
      
      // Set timeout
      const timer = setTimeout(() => {
        this.print(this.color('\n[TIMEOUT] No response received, skipping step.', 'yellow'));
        resolve('skip');
      }, this.timeout);

      rl.question(promptText, (answer) => {
        clearTimeout(timer);
        resolve(answer.trim().toLowerCase());
      });
    });
  }

  /**
   * Request approval via CLI prompt
   * 
   * @param {Object} step - Step metadata
   * @param {Object} preview - Preview of what will happen
   * @returns {Promise<ApprovalResult>}
   */
  async requestApproval(step, preview) {
    // Check deny list first
    if (this.denyTypes.includes(step.type)) {
      this.print(this.color(`[DENIED] Step type "${step.type}" is in deny list.`, 'red'));
      this.logAudit(step, 'denied', 'Step type in deny list');
      return ApprovalResult.SKIPPED;
    }

    // Display preview
    this.print(this.formatPreviewCLI(preview));

    // Prompt for approval
    const promptText = this.color('Approve? [y/n/q/all]: ', 'bold', 'cyan');
    const answer = await this.prompt(promptText);

    // Process answer
    switch (answer) {
      case 'y':
      case 'yes':
      case 'a':
      case 'approve':
      case 'approved':
        this.print(this.color('[OK] Step approved.', 'green'));
        this.logAudit(step, 'approved', 'User approved via CLI');
        return ApprovalResult.APPROVED;

      case 'n':
      case 'no':
      case 's':
      case 'skip':
      case 'skipped':
        this.print(this.color('[--] Step skipped.', 'yellow'));
        this.logAudit(step, 'skipped', 'User skipped via CLI');
        return ApprovalResult.SKIPPED;

      case 'q':
      case 'quit':
      case 'abort':
      case 'cancel':
        this.print(this.color('[!!] Workflow aborted.', 'red'));
        this.logAudit(step, 'quit', 'User aborted via CLI');
        return ApprovalResult.QUIT;

      case 'all':
      case 'aa':
      case 'approve_all':
      case 'approveall':
        this.print(this.color('[OK] Approved all remaining steps.', 'green', 'bold'));
        this.approvedAll = true;
        this.logAudit(step, 'approve_all', 'User approved all via CLI');
        return ApprovalResult.APPROVE_ALL;

      default:
        this.print(this.color(`[?] Unrecognized input: "${answer}". Skipping for safety.`, 'yellow'));
        this.logAudit(step, 'skipped', `Unrecognized input: ${answer}`);
        return ApprovalResult.SKIPPED;
    }
  }

  /**
   * Print workflow start banner
   */
  printWorkflowStart(workflowName, stepCount) {
    this.print('');
    this.print(this.color('╔' + '═'.repeat(63) + '╗', 'blue'));
    this.print(this.color('║', 'blue') + this.color(` WORKFLOW: ${workflowName}`, 'bold').padEnd(72) + this.color('║', 'blue'));
    this.print(this.color('║', 'blue') + ` Steps: ${stepCount}`.padEnd(63) + this.color('║', 'blue'));
    this.print(this.color('╚' + '═'.repeat(63) + '╝', 'blue'));
    this.print('');
  }

  /**
   * Print workflow completion summary
   */
  printWorkflowComplete(results) {
    this.print('');
    this.print(this.color('╔' + '═'.repeat(63) + '╗', 'green'));
    this.print(this.color('║', 'green') + this.color(' WORKFLOW COMPLETE', 'bold', 'green') + ' '.repeat(45) + this.color('║', 'green'));
    this.print(this.color('╠' + '═'.repeat(63) + '╣', 'green'));
    
    const approved = results.filter(r => r.status === 'success').length;
    const skipped = results.filter(r => r.status === 'skipped').length;
    const failed = results.filter(r => r.status === 'failed').length;
    
    this.print(this.color('║', 'green') + ` Approved: ${this.color(approved.toString(), 'green')}`.padEnd(72) + this.color('║', 'green'));
    this.print(this.color('║', 'green') + ` Skipped:  ${this.color(skipped.toString(), 'yellow')}`.padEnd(72) + this.color('║', 'green'));
    this.print(this.color('║', 'green') + ` Failed:   ${this.color(failed.toString(), 'red')}`.padEnd(72) + this.color('║', 'green'));
    this.print(this.color('╚' + '═'.repeat(63) + '╝', 'green'));
    this.print('');
  }

  /**
   * Print step execution result
   */
  printStepResult(step, result) {
    const icon = result.status === 'success' ? this.color('[OK]', 'green') :
                 result.status === 'skipped' ? this.color('[--]', 'yellow') :
                 result.status === 'dry_run' ? this.color('[~~]', 'cyan') :
                 this.color('[!!]', 'red');
    
    this.print(`${icon} ${step.name} (${result.duration || 0}ms)`);
    
    if (result.error) {
      this.print(this.color(`    Error: ${result.error}`, 'red'));
    }
  }
}

export default CLIApprovalProvider;
