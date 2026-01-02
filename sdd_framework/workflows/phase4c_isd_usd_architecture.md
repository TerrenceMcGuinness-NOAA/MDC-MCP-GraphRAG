# SDD: Phase 4C - ISD/USD Execution Architecture

**Description**: Define the dual-mode execution architecture for SDD workflows: Interactive Supervised Development (ISD) for human-in-the-loop orchestration, and Unsupervised Development (USD) for autonomous sub-agent dispatch.

**Status**: PLANNING  
**Priority**: High  
**Prerequisite**: Phase 4B ISD approval gates (in progress)  
**Date**: January 2, 2026

---

## 1. Terminology

| Acronym | Full Name | Description |
|---------|-----------|-------------|
| **SDD** | Spec-Driven Development | The methodology - plan first, then execute |
| **ISD** | Interactive Supervised Development | Human approves each side-effect step |
| **USD** | Unsupervised Development | Autonomous execution within approved scope |

### The Relationship

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SDD METHODOLOGY                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌─────────────────────────────┐                                       │
│   │      PLANNING PHASE         │  "The Spec"                           │
│   │                             │                                       │
│   │  • Workflow definitions     │  - What needs to be done              │
│   │  • Phase documents          │  - Why it matters                     │
│   │  • Architecture specs       │  - How it fits together               │
│   │  • Context & constraints    │  - Boundaries and scope               │
│   └──────────────┬──────────────┘                                       │
│                  │                                                      │
│                  ▼                                                      │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                    EXECUTION PHASE                               │  │
│   │                                                                  │  │
│   │   ┌─────────────────────┐      ┌─────────────────────┐          │  │
│   │   │        ISD          │      │        USD          │          │  │
│   │   │                     │      │                     │          │  │
│   │   │  Interactive        │      │  Unsupervised       │          │  │
│   │   │  Supervised         │ ───► │  Development        │          │  │
│   │   │  Development        │      │                     │          │  │
│   │   │                     │      │  (Sub-agent tasks)  │          │  │
│   │   │  • Approval gates   │      │  • Pre-approved     │          │  │
│   │   │  • Multi-turn       │      │  • Scoped execution │          │  │
│   │   │  • Human oversight  │      │  • Time-bounded     │          │  │
│   │   └─────────────────────┘      └─────────────────────┘          │  │
│   │                                                                  │  │
│   │   The "I" in ISD is the approval to launch USD sub-agents       │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Problem Statement

### Current State
- Phase 4B defines approval gates for side-effect steps
- No mechanism to dispatch work to external agents (Claude CLI, GitHub Actions, n8n)
- Context (specs, analysis results) isn't packaged for different execution environments

### Gap
We need:
1. **Sub-agent dispatch** - Launch USD tasks from ISD workflows
2. **Context packaging** - Adapt workflow context to different form factors
3. **Result capture** - Collect and validate USD outputs
4. **Error handling** - Graceful recovery from USD failures

---

## 3. Architecture Overview

### 3.1 Execution Mode Hierarchy

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     EXECUTION MODE HIERARCHY                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  dry_run ──────────────────────────────────────────────── (PREVIEW)     │
│    │   No execution, show what would happen                             │
│    │                                                                    │
│    ▼                                                                    │
│  ISD (Interactive Supervised Development) ─────────────── (CONTROLLED)  │
│    │   Human approves each side-effect step                             │
│    │   Can spawn USD sub-agents with approval                           │
│    │                                                                    │
│    ▼                                                                    │
│  USD (Unsupervised Development) ───────────────────────── (AUTONOMOUS)  │
│    │   Runs within approved scope/time                                  │
│    │   No further human interaction                                     │
│    │   Reports results back to ISD orchestrator                         │
│    │                                                                    │
│    ▼                                                                    │
│  batch ────────────────────────────────────────────────── (CI/CD)       │
│      Pre-approved via manifest, fully autonomous                        │
│      Used for scheduled/triggered workflows                             │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 ISD → USD Dispatch Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       ISD → USD DISPATCH FLOW                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ISD Orchestrator (VS Code Copilot, Claude CLI, n8n)                   │
│         │                                                               │
│         │  Step 1: health_check ✅ (auto)                               │
│         │  Step 2: analyze_code  ✅ (auto)                              │
│         │  Step 3: sub_agent     ⏸️ APPROVAL GATE                       │
│         │                                                               │
│         ▼                                                               │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                    APPROVAL PROMPT                               │  │
│   │                                                                  │  │
│   │  "Launch USD sub-agent to generate refactoring plan?"            │  │
│   │                                                                  │  │
│   │  • Agent: Claude CLI                                             │  │
│   │  • Objective: Generate EE2-compliant refactoring plan            │  │
│   │  • Scope: sorc/ufs_model.fd/**/*.F90                            │  │
│   │  • Timeout: 5 minutes                                            │  │
│   │  • Allowed tools: Read, Bash, MCP analyze tools                  │  │
│   │                                                                  │  │
│   │  [Approve] [Preview Context] [Edit Constraints] [Skip] [Quit]    │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│         │                                                               │
│         │ User: "Approve"                                               │
│         ▼                                                               │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                  CONTEXT PACKAGER                                │  │
│   │                                                                  │  │
│   │  Inputs:                                                         │  │
│   │    • workflow.context.spec                                       │  │
│   │    • workflow.context.references[]                               │  │
│   │    • previous_steps[].results                                    │  │
│   │    • step.constraints                                            │  │
│   │                                                                  │  │
│   │  Output (form-factor specific):                                  │  │
│   │    • Claude CLI → .claude/task_<id>.md + context files           │  │
│   │    • GitHub Actions → Issue body with embedded context           │  │
│   │    • VS Code subagent → Inline prompt string                     │  │
│   │    • n8n → Webhook payload with context                          │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│         │                                                               │
│         ▼                                                               │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                  USD SUB-AGENT EXECUTION                         │  │
│   │                                                                  │  │
│   │  claude --print --instruction .claude/task_abc123.md \           │  │
│   │         --allowedTools "Read,Bash" \                             │  │
│   │         --timeout 300                                            │  │
│   │                                                                  │  │
│   │  [Runs autonomously within approved constraints]                 │  │
│   │  [No further human interaction]                                  │  │
│   │  [Output captured to execution state]                            │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│         │                                                               │
│         ▼                                                               │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                  RESULT CAPTURE & VALIDATION                     │  │
│   │                                                                  │  │
│   │  • Parse USD output (stdout, files created, exit code)           │  │
│   │  • Validate against expected schema                              │  │
│   │  • Store in execution state for next steps                       │  │
│   │  • Report back to ISD orchestrator                               │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│         │                                                               │
│         ▼                                                               │
│   ISD Orchestrator continues...                                         │
│         │  Step 4: validate_output ✅ (auto)                            │
│         │  Step 5: code_generation ⏸️ APPROVAL GATE                     │
│         │  ...                                                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Workflow Definition Schema

### 4.1 Top-Level Workflow Structure

```yaml
# SDD Workflow Definition v2.0
# Supports ISD orchestration with USD sub-agent dispatch

workflow:
  name: string                    # Unique identifier
  version: string                 # Semantic version
  description: string             # Human-readable description
  
  # Execution mode constraints
  execution:
    default_mode: dry_run | isd | batch
    allow_usd: boolean            # Can this workflow spawn sub-agents?
    max_usd_depth: number         # Prevent infinite sub-agent recursion
    timeout: number               # Total workflow timeout (ms)
  
  # Planning artifacts (the "S" in SDD)
  context:
    spec: string                  # Path to primary SDD document
    references: string[]          # Supporting documentation
    scope:
      include: string[]           # Glob patterns for in-scope files
      exclude: string[]           # Glob patterns to exclude
    variables: object             # Workflow-level variables
  
  # Execution steps
  steps: Step[]
  
  # Error handling
  on_error:
    strategy: abort | continue | rollback
    notify: string[]              # Notification channels
```

### 4.2 Step Types

```yaml
# Step Definition Schema

Step:
  name: string                    # Step identifier
  type: StepType                  # See below
  description: string             # What this step does
  required: boolean               # Can workflow continue if this fails?
  depends_on: string[]            # Step names that must complete first
  
  # Conditional execution
  when:
    previous_status: success | failure | skipped
    condition: string             # JavaScript expression
  
  # Type-specific configuration
  # ... (varies by type)

StepType:
  # Read-only operations (auto-execute in ISD)
  - health_check                  # Verify system components
  - validation                    # Check conditions/assertions
  - data_query                    # Query databases/APIs
  - mcp_tool                      # Call MCP tool (read-only)
  
  # Side-effect operations (require ISD approval)
  - code_generation               # Create new files
  - code_modification             # Modify existing files
  - command                       # Run shell command
  - ingestion                     # Update knowledge base
  
  # Sub-agent dispatch (require ISD approval, run as USD)
  - sub_agent                     # Dispatch to external agent
  
  # Human tasks (ISD waits for external completion)
  - manual                        # Human performs action externally
  - approval                      # Explicit approval checkpoint
```

### 4.3 Sub-Agent Step Schema

```yaml
# Sub-Agent Step - Detailed Schema

- name: string
  type: sub_agent
  description: string
  
  # What the sub-agent should accomplish
  objective: string               # Natural language goal
  
  # Constraints on USD execution
  constraints:
    timeout: number               # Max execution time (ms), default 300000
    max_file_changes: number      # Limit write scope, default unlimited
    max_tokens: number            # Limit LLM token usage
    sandbox: boolean              # Read-only mode, default false
    allowed_tools: string[]       # Tool whitelist
    denied_tools: string[]        # Tool blacklist
    working_directory: string     # Restrict to subdirectory
  
  # Context to pass to sub-agent
  context_injection:
    include_spec: boolean         # Include workflow.context.spec
    include_references: boolean   # Include workflow.context.references
    include_previous_results: boolean  # Include prior step outputs
    additional_files: string[]    # Extra files to include
    variables: object             # Step-specific variables
  
  # Form-factor dispatch configurations
  dispatch:
    # Which form factor to use (auto-detect if not specified)
    prefer: auto | vscode | claude_cli | github_actions | n8n
    
    # VS Code Copilot (runSubagent)
    vscode:
      agent: string               # Agent name (e.g., "Plan")
      prompt_template: string     # Mustache template for prompt
    
    # Claude CLI (terminal)
    claude_cli:
      instruction_template: string  # Template for instruction file
      instruction_file: string      # Where to write instructions
      output_format: text | json | stream
      allowed_tools: string[]       # Claude CLI --allowedTools
      model: string                 # Optional model override
    
    # GitHub Actions (issue-driven)
    github_actions:
      action: create_issue | create_pr | dispatch_workflow
      repository: string
      title_template: string
      body_template: string
      labels: string[]
      assignees: string[]
      wait_for_completion: boolean
      completion_trigger: issue_closed | pr_merged | workflow_complete
    
    # n8n (webhook)
    n8n:
      workflow_id: string
      webhook_url: string
      payload_template: object
      wait_for_completion: boolean
      callback_url: string
  
  # Result handling
  output:
    capture: stdout | file | webhook_response | issue_body
    parse_as: text | json | markdown
    validate_schema: object       # JSON Schema for output validation
    store_as: string              # Variable name for use in later steps
```

---

## 5. Context Packaging

### 5.1 Context Packager Interface

```javascript
/**
 * ContextPackager - Adapts workflow context for different form factors
 */
class ContextPackager {
  /**
   * Package context for a specific form factor
   * @param {Object} workflow - Workflow definition
   * @param {Object} step - Current sub_agent step
   * @param {Object} executionState - Results from previous steps
   * @param {string} formFactor - Target: vscode, claude_cli, github_actions, n8n
   * @returns {Object} Form-factor-specific context package
   */
  async package(workflow, step, executionState, formFactor) {
    // Gather raw context
    const rawContext = await this.gatherContext(workflow, step, executionState);
    
    // Transform for form factor
    switch (formFactor) {
      case 'vscode':
        return this.packageForVSCode(rawContext, step);
      case 'claude_cli':
        return this.packageForClaudeCLI(rawContext, step);
      case 'github_actions':
        return this.packageForGitHub(rawContext, step);
      case 'n8n':
        return this.packageForN8N(rawContext, step);
      default:
        throw new Error(`Unknown form factor: ${formFactor}`);
    }
  }
  
  async gatherContext(workflow, step, executionState) {
    const context = {
      spec: null,
      references: [],
      previousResults: {},
      variables: {}
    };
    
    // Load spec if requested
    if (step.context_injection.include_spec) {
      context.spec = await fs.readFile(workflow.context.spec, 'utf-8');
    }
    
    // Load references if requested
    if (step.context_injection.include_references) {
      for (const ref of workflow.context.references) {
        context.references.push({
          path: ref,
          content: await fs.readFile(ref, 'utf-8')
        });
      }
    }
    
    // Include previous results if requested
    if (step.context_injection.include_previous_results) {
      context.previousResults = executionState.stepResults;
    }
    
    // Merge variables
    context.variables = {
      ...workflow.context.variables,
      ...step.context_injection.variables
    };
    
    return context;
  }
}
```

### 5.2 Form Factor: Claude CLI

```javascript
async packageForClaudeCLI(rawContext, step) {
  const config = step.dispatch.claude_cli;
  
  // Render instruction template
  const instruction = Mustache.render(config.instruction_template, {
    objective: step.objective,
    constraints: step.constraints,
    spec: rawContext.spec,
    references: rawContext.references,
    previous_results: JSON.stringify(rawContext.previousResults, null, 2),
    variables: rawContext.variables
  });
  
  // Write instruction file
  const instructionPath = config.instruction_file || `.claude/task_${generateId()}.md`;
  await fs.mkdir(path.dirname(instructionPath), { recursive: true });
  await fs.writeFile(instructionPath, instruction);
  
  // Write context files if large
  const contextFiles = [];
  for (const ref of rawContext.references) {
    if (ref.content.length > 10000) {
      const contextPath = `.claude/context/${path.basename(ref.path)}`;
      await fs.writeFile(contextPath, ref.content);
      contextFiles.push(contextPath);
    }
  }
  
  // Build command
  const args = [
    '--print',
    '--instruction', instructionPath,
    '--allowedTools', (config.allowed_tools || step.constraints.allowed_tools).join(','),
  ];
  
  if (config.output_format === 'json') {
    args.push('--output-format', 'json');
  }
  
  return {
    command: 'claude',
    args,
    instructionPath,
    contextFiles,
    cleanup: [instructionPath, ...contextFiles]
  };
}
```

### 5.3 Form Factor: GitHub Actions

```javascript
async packageForGitHub(rawContext, step) {
  const config = step.dispatch.github_actions;
  
  // Render issue/PR body
  const body = Mustache.render(config.body_template, {
    workflow_name: workflow.name,
    step_name: step.name,
    objective: step.objective,
    constraints: JSON.stringify(step.constraints, null, 2),
    spec: rawContext.spec,
    previous_results: JSON.stringify(rawContext.previousResults, null, 2),
    timestamp: new Date().toISOString()
  });
  
  // Truncate if too long for GitHub (65536 char limit)
  const truncatedBody = body.length > 60000 
    ? body.substring(0, 60000) + '\n\n... [truncated, see linked files]'
    : body;
  
  return {
    action: config.action,
    repository: config.repository,
    title: Mustache.render(config.title_template, { step_name: step.name }),
    body: truncatedBody,
    labels: config.labels,
    assignees: config.assignees,
    wait_for: config.wait_for_completion ? config.completion_trigger : null
  };
}
```

### 5.4 Form Factor: VS Code Subagent

```javascript
async packageForVSCode(rawContext, step) {
  const config = step.dispatch.vscode;
  
  // VS Code subagent gets inline prompt (no file I/O)
  const prompt = Mustache.render(config.prompt_template, {
    objective: step.objective,
    constraints: step.constraints,
    spec: rawContext.spec,
    references: rawContext.references.map(r => r.content).join('\n\n---\n\n'),
    previous_results: JSON.stringify(rawContext.previousResults, null, 2),
    variables: rawContext.variables
  });
  
  return {
    agent: config.agent,
    prompt,
    description: step.name
  };
}
```

---

## 6. USD Dispatcher

### 6.1 Dispatcher Interface

```javascript
/**
 * USDDispatcher - Executes sub-agents in USD mode
 */
class USDDispatcher {
  constructor(options = {}) {
    this.packager = new ContextPackager();
    this.timeout = options.defaultTimeout || 300000;
  }
  
  /**
   * Dispatch a sub-agent task
   * @param {Object} workflow - Workflow definition
   * @param {Object} step - Sub-agent step
   * @param {Object} executionState - Current execution state
   * @returns {Object} USD execution result
   */
  async dispatch(workflow, step, executionState) {
    // Determine form factor
    const formFactor = this.selectFormFactor(step);
    
    // Package context
    const package = await this.packager.package(
      workflow, step, executionState, formFactor
    );
    
    // Execute based on form factor
    const startTime = Date.now();
    let result;
    
    try {
      switch (formFactor) {
        case 'claude_cli':
          result = await this.executeClaudeCLI(package, step);
          break;
        case 'vscode':
          result = await this.executeVSCodeSubagent(package, step);
          break;
        case 'github_actions':
          result = await this.executeGitHubAction(package, step);
          break;
        case 'n8n':
          result = await this.executeN8NWorkflow(package, step);
          break;
      }
      
      return {
        status: 'success',
        formFactor,
        duration: Date.now() - startTime,
        output: result.output,
        artifacts: result.artifacts || []
      };
      
    } catch (error) {
      return {
        status: 'error',
        formFactor,
        duration: Date.now() - startTime,
        error: error.message,
        output: null
      };
      
    } finally {
      // Cleanup temporary files
      if (package.cleanup) {
        for (const file of package.cleanup) {
          await fs.unlink(file).catch(() => {});
        }
      }
    }
  }
  
  selectFormFactor(step) {
    const prefer = step.dispatch?.prefer || 'auto';
    
    if (prefer !== 'auto') return prefer;
    
    // Auto-detect based on environment
    if (process.env.VSCODE_PID) return 'vscode';
    if (process.env.GITHUB_ACTIONS) return 'github_actions';
    if (process.env.N8N_WORKFLOW_ID) return 'n8n';
    return 'claude_cli';  // Default fallback
  }
  
  async executeClaudeCLI(package, step) {
    const timeout = step.constraints?.timeout || this.timeout;
    
    const result = await execWithTimeout(
      package.command,
      package.args,
      { timeout, captureOutput: true }
    );
    
    // Parse output based on format
    let output = result.stdout;
    if (step.dispatch.claude_cli.output_format === 'json') {
      output = JSON.parse(result.stdout);
    }
    
    // Validate against schema if provided
    if (step.output?.validate_schema) {
      this.validateSchema(output, step.output.validate_schema);
    }
    
    return { output, exitCode: result.exitCode };
  }
}
```

---

## 7. Implementation Steps

### Phase 4C-1: Core Infrastructure (~8 hours)

| Step | Type | Description |
|------|------|-------------|
| 1.1 | code_generation | Create `ContextPackager.js` |
| 1.2 | code_generation | Create `USDDispatcher.js` |
| 1.3 | code_generation | Create form-factor adapters (claude_cli, vscode, github, n8n) |
| 1.4 | code_modification | Update workflow schema to v2.0 with sub_agent type |

### Phase 4C-2: Integration (~6 hours)

| Step | Type | Description |
|------|------|-------------|
| 2.1 | code_modification | Integrate USDDispatcher into WorkflowExecutor |
| 2.2 | code_modification | Update `execute_sdd_workflow_supervised` for sub_agent steps |
| 2.3 | code_generation | Create instruction file templates for common patterns |

### Phase 4C-3: Form Factor Implementations (~8 hours)

| Step | Type | Description |
|------|------|-------------|
| 3.1 | code_generation | Claude CLI executor with timeout and output capture |
| 3.2 | code_generation | VS Code runSubagent integration |
| 3.3 | code_generation | GitHub Issues/Actions dispatcher |
| 3.4 | code_generation | n8n webhook dispatcher |

### Phase 4C-4: Testing & Documentation (~4 hours)

| Step | Type | Description |
|------|------|-------------|
| 4.1 | code_generation | Unit tests for ContextPackager |
| 4.2 | code_generation | Integration tests for USD dispatch |
| 4.3 | code_generation | Example workflows demonstrating ISD→USD |
| 4.4 | documentation | Update methodology docs with ISD/USD terminology |

---

## 8. Example Workflow: ISD with USD Sub-Agent

```yaml
# Example: EE2 Compliance Refactoring Workflow
# Demonstrates ISD orchestration with USD sub-agent dispatch

workflow:
  name: ee2_compliance_refactor
  version: "1.0.0"
  description: Analyze module for EE2 compliance and generate refactoring plan
  
  execution:
    default_mode: isd
    allow_usd: true
    max_usd_depth: 2
    timeout: 1800000  # 30 minutes total
  
  context:
    spec: sdd_framework/workflows/ee2_refactoring_template.md
    references:
      - docs/EE2_compliance_reports/current_audit.md
      - supported_repos/nws-hpc-standards/docs/standards.rst
    scope:
      include:
        - "{{target_module}}/**/*.py"
        - "{{target_module}}/**/*.sh"
      exclude:
        - "**/test/**"
        - "**/__pycache__/**"
    variables:
      target_module: scripts/exglobal_forecast
      compliance_level: strict
  
  steps:
    # Step 1: Health check (auto in ISD)
    - name: verify_system_health
      type: health_check
      description: Ensure MCP server and knowledge base are operational
    
    # Step 2: Analyze current state (auto in ISD)
    - name: analyze_current_compliance
      type: mcp_tool
      tool: scan_repository_compliance
      params:
        repository_path: "{{scope.include[0]}}"
        standards: ee2
      output:
        store_as: compliance_scan
    
    # Step 3: USD sub-agent for deep analysis (requires ISD approval)
    - name: generate_refactoring_plan
      type: sub_agent
      description: Use Claude to generate detailed refactoring plan
      
      objective: |
        Analyze the compliance scan results and generate a detailed,
        actionable refactoring plan to bring the module to EE2 compliance.
      
      constraints:
        timeout: 300000  # 5 minutes
        sandbox: true    # Read-only, planning only
        allowed_tools:
          - Read
          - Bash(grep, find, wc)
          - mcp__eib-mcp-gateway__analyze_code_structure
          - mcp__eib-mcp-gateway__search_ee2_standards
      
      context_injection:
        include_spec: true
        include_references: true
        include_previous_results: true
        variables:
          focus_areas: "{{compliance_scan.violations}}"
      
      dispatch:
        prefer: auto
        
        claude_cli:
          instruction_template: |
            # EE2 Compliance Refactoring Analysis
            
            ## Objective
            {{objective}}
            
            ## Current Compliance Status
            ```json
            {{previous_results.compliance_scan}}
            ```
            
            ## EE2 Standards Reference
            {{references[1].content}}
            
            ## Your Task
            1. Analyze each violation in the compliance scan
            2. Propose specific code changes to fix each violation
            3. Prioritize changes by impact and effort
            4. Output a structured JSON refactoring plan
            
            ## Output Format
            ```json
            {
              "summary": "Brief summary of findings",
              "total_violations": <number>,
              "refactoring_steps": [
                {
                  "priority": 1-5,
                  "file": "path/to/file",
                  "violation": "description",
                  "fix": "proposed change",
                  "effort": "low|medium|high"
                }
              ],
              "estimated_total_effort": "X hours"
            }
            ```
          instruction_file: .claude/ee2_refactor_{{execution_id}}.md
          output_format: json
        
        github_actions:
          action: create_issue
          repository: NOAA-EMC/global-workflow
          title_template: "[EE2-Refactor] {{target_module}} Compliance Analysis"
          body_template: |
            ## Automated EE2 Compliance Analysis
            
            **Module**: `{{variables.target_module}}`
            **Compliance Level**: {{variables.compliance_level}}
            **Generated**: {{timestamp}}
            
            ### Current Violations
            ```json
            {{previous_results.compliance_scan}}
            ```
            
            ### Requested Action
            Please review and provide a refactoring plan in the comments.
            
            ### Checklist
            - [ ] Review violations
            - [ ] Propose fixes
            - [ ] Estimate effort
            - [ ] Close when complete
          labels:
            - ee2-compliance
            - ai-analysis
            - needs-review
      
      output:
        capture: stdout
        parse_as: json
        validate_schema:
          type: object
          required: [summary, refactoring_steps]
          properties:
            summary: { type: string }
            refactoring_steps: { type: array }
        store_as: refactoring_plan
    
    # Step 4: Validate plan (auto in ISD)
    - name: validate_plan
      type: validation
      description: Ensure refactoring plan is complete and actionable
      checks:
        - name: has_steps
          condition: "refactoring_plan.refactoring_steps.length > 0"
        - name: all_prioritized
          condition: "refactoring_plan.refactoring_steps.every(s => s.priority)"
    
    # Step 5: Present plan for approval (ISD checkpoint)
    - name: approve_refactoring_plan
      type: approval
      description: Review and approve the generated refactoring plan
      present:
        - refactoring_plan.summary
        - refactoring_plan.estimated_total_effort
        - "First 5 steps: {{refactoring_plan.refactoring_steps.slice(0,5)}}"
    
    # Step 6: Execute refactoring (USD, requires ISD approval)
    - name: execute_refactoring
      type: sub_agent
      description: Apply approved refactoring changes
      depends_on: [approve_refactoring_plan]
      
      objective: |
        Apply the approved refactoring plan to bring the module to EE2 compliance.
      
      constraints:
        timeout: 600000  # 10 minutes
        sandbox: false   # Can modify files
        max_file_changes: 20
        allowed_tools:
          - Read
          - Write
          - Bash(grep, sed, git diff)
      
      context_injection:
        include_previous_results: true
        variables:
          plan: "{{refactoring_plan}}"
      
      dispatch:
        prefer: claude_cli
        claude_cli:
          instruction_template: |
            # Execute EE2 Refactoring Plan
            
            ## Approved Plan
            ```json
            {{variables.plan}}
            ```
            
            ## Instructions
            1. Apply each refactoring step in priority order
            2. Create a git-compatible diff for each change
            3. Verify syntax after each change
            4. Report results as JSON
            
            ## Output Format
            ```json
            {
              "applied": [{"file": "...", "change": "..."}],
              "skipped": [{"file": "...", "reason": "..."}],
              "errors": []
            }
            ```
          output_format: json
      
      output:
        store_as: refactoring_result
    
    # Step 7: Final validation (auto in ISD)
    - name: verify_compliance
      type: mcp_tool
      tool: scan_repository_compliance
      params:
        repository_path: "{{scope.include[0]}}"
        standards: ee2
      output:
        store_as: final_compliance_scan
    
    # Step 8: Report
    - name: generate_report
      type: code_generation
      description: Generate compliance improvement report
      target: "docs/EE2_compliance_reports/{{target_module}}_{{date}}.md"
      template: ee2_compliance_report_template.md
      variables:
        before: "{{compliance_scan}}"
        after: "{{final_compliance_scan}}"
        changes: "{{refactoring_result}}"
```

---

## 9. Validation Criteria

### Acceptance Tests

- [ ] ISD workflow pauses at sub_agent steps for approval
- [ ] Context is correctly packaged for each form factor
- [ ] Claude CLI USD executes with timeout enforcement
- [ ] USD results are captured and validated against schema
- [ ] Subsequent steps can access USD output via store_as variable
- [ ] Errors in USD are handled gracefully (workflow can continue or abort)
- [ ] GitHub Actions form factor creates issues with correct formatting
- [ ] n8n webhook dispatch triggers and captures response

### Performance Requirements

- Context packaging < 1 second for typical workflows
- USD dispatch overhead < 500ms (excluding agent execution time)
- Form factor detection < 100ms

---

## 10. Dependencies

- Phase 4B: ISD approval gates (required)
- Claude CLI installed for claude_cli form factor
- GitHub token for github_actions form factor
- n8n instance for n8n form factor

---

## 11. Estimated Effort

| Component | Hours |
|-----------|-------|
| Core infrastructure | 8 |
| WorkflowExecutor integration | 6 |
| Form factor implementations | 8 |
| Testing and documentation | 4 |
| **Total** | **26 hours** |

---

## 12. Future Extensions

- **Agent chaining**: USD sub-agents can spawn their own USD tasks (with depth limit)
- **Parallel USD**: Multiple sub-agents running concurrently
- **Agent marketplace**: Registry of pre-configured agent templates
- **Cost tracking**: Monitor LLM token usage across USD executions
- **Replay/debug**: Re-run USD with same context for debugging

---

*"The 'I' in ISD is the human approval to launch USD. Once approved, the sub-agent runs autonomously within the approved scope."*
