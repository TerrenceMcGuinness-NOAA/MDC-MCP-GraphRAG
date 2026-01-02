# SDD: Phase 4D - Multi-Tenant SDD Workspaces

**Description**: Architecture for scaling SDD workflow storage and execution across multiple users, teams, and projects using the MCP/RAG platform for GFS development.

**Status**: PLANNING  
**Priority**: High  
**Prerequisite**: Phase 4C ISD/USD Architecture  
**Date**: January 2, 2026

---

## 1. Problem Statement

### Current State

The `sdd_framework/` directory contains workflows for developing the MCP/RAG platform itself:

```
sdd_framework/
├── methodology/           # Core SDD methodology (shared)
├── workflows/             # Platform development workflows (meta-SDD)
│   ├── phase4b_...md
│   ├── phase4c_...md
│   └── phase12_...md
├── templates/             # Workflow templates (shared)
└── validation/            # Validation rules (shared)
```

### The Gap

When GFS developers use this platform, they need their own SDD workspaces:

```
User A (GFS Forecast Team):
  - Workflow: refactor_ufs_driver
  - Workflow: ee2_compliance_gfsv17
  - Execution history, approvals, context

User B (Data Assimilation Team):
  - Workflow: gsi_observation_ingestion
  - Workflow: gdas_cycling_optimization
  - Separate execution history

Team C (Verification):
  - Workflow: evs_metric_enhancement
  - Shared team workspace
```

### Requirements

1. **Isolation**: User A's workflows don't interfere with User B's
2. **Sharing**: Teams can share workflows within their group
3. **Templates**: All users access common methodology and templates
4. **Execution State**: Per-user ISD approval history and USD results
5. **Scalability**: Support dozens of concurrent users/teams
6. **Persistence**: Workflows survive session restarts
7. **Versioning**: Track workflow changes over time

---

## 2. Architecture Overview

### 2.1 Three-Tier SDD Hierarchy

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SDD WORKSPACE HIERARCHY                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  TIER 1: PLATFORM (Shared, Read-Only for Users)                         │
│  ════════════════════════════════════════════                           │
│  Location: sdd_framework/                                               │
│  Contents:                                                              │
│    • methodology/     - Core SDD/ISD/USD patterns                       │
│    • templates/       - Workflow templates                              │
│    • validation/      - Schema and validation rules                     │
│    • platform/        - Meta-SDD (platform development)                 │
│                                                                         │
│  Access: All users can READ, only platform maintainers WRITE            │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  TIER 2: ORGANIZATION / TEAM (Shared within group)                      │
│  ═════════════════════════════════════════════════                      │
│  Location: sdd_workspaces/<org_id>/                                     │
│  Contents:                                                              │
│    • workflows/       - Team workflow definitions                       │
│    • templates/       - Team-specific templates                         │
│    • shared_context/  - Common references, standards                    │
│    • execution_log/   - Team execution history                          │
│                                                                         │
│  Access: Team members can READ/WRITE, others cannot access              │
│                                                                         │
│  Examples:                                                              │
│    sdd_workspaces/gfs-forecast-team/                                    │
│    sdd_workspaces/data-assimilation/                                    │
│    sdd_workspaces/verification-evs/                                     │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  TIER 3: USER (Personal workspace)                                      │
│  ═════════════════════════════════                                      │
│  Location: sdd_workspaces/<org_id>/users/<user_id>/                     │
│           OR ~/.sdd/<project>/  (local development)                     │
│  Contents:                                                              │
│    • workflows/       - Personal workflow drafts                        │
│    • executions/      - ISD approval history, USD results               │
│    • context/         - User-specific context files                     │
│    • preferences/     - Default settings, auto-approve rules            │
│                                                                         │
│  Access: Only the user can READ/WRITE                                   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Workflow Resolution Order

When a user references a workflow, resolve in order:

```
1. User workspace     → sdd_workspaces/<org>/users/<user>/workflows/<name>.md
2. Team workspace     → sdd_workspaces/<org>/workflows/<name>.md
3. Platform templates → sdd_framework/templates/<name>.md
4. Platform workflows → sdd_framework/workflows/<name>.md (meta-SDD only)
```

This allows users to override team workflows, and teams to override platform templates.

---

## 3. Directory Structure

### 3.1 Platform Directory (Reorganized)

```
sdd_framework/
├── methodology/
│   ├── spec_driven_design_core.md      # Core SDD concepts
│   ├── isd_usd_execution_modes.md      # ISD/USD patterns
│   └── historical_manifest.md          # Evolution history
│
├── templates/                          # Starter templates for users
│   ├── feature_development.md          # Generic feature workflow
│   ├── ee2_compliance_audit.md         # EE2 scanning template
│   ├── code_refactoring.md             # Refactoring pattern
│   ├── documentation_update.md         # Doc workflow
│   └── bug_investigation.md            # Debugging workflow
│
├── validation/
│   ├── workflow_schema.json            # JSON Schema for workflows
│   ├── step_types.json                 # Valid step type definitions
│   └── validators/                     # Validation scripts
│
├── platform/                           # Meta-SDD (platform development)
│   ├── phase4b_isd_approval_gates.md
│   ├── phase4c_isd_usd_architecture.md
│   ├── phase4d_multi_tenant_workspaces.md
│   ├── phase11e_n8n_workflow.md
│   └── phase12_devops_gitflow.md
│
└── PRIORITY_ROADMAP.md                 # Platform roadmap (SPOT)
```

### 3.2 Workspace Directory Structure

```
sdd_workspaces/
├── .workspace_registry.json            # Index of all workspaces
│
├── gfs-forecast-team/                  # Organization/Team workspace
│   ├── .workspace.json                 # Workspace metadata
│   ├── workflows/
│   │   ├── gfsv17_ufs_upgrade.md
│   │   ├── forecast_post_optimization.md
│   │   └── ee2_fcst_compliance.md
│   ├── templates/                      # Team-specific templates
│   │   └── gfs_module_template.md
│   ├── shared_context/
│   │   ├── gfs_architecture_overview.md
│   │   └── team_coding_standards.md
│   ├── execution_log/                  # Team-visible execution history
│   │   └── 2026-01/
│   │       ├── exec_abc123.json
│   │       └── exec_def456.json
│   │
│   └── users/
│       ├── terrence.h/                 # User workspace
│       │   ├── .user_preferences.json
│       │   ├── workflows/
│       │   │   └── draft_ufs_refactor.md
│       │   ├── executions/
│       │   │   ├── active/             # In-progress ISD sessions
│       │   │   │   └── exec_xyz789.json
│       │   │   └── completed/
│       │   │       └── exec_xyz788.json
│       │   └── context/
│       │       └── my_notes.md
│       │
│       └── developer.b/
│           └── ...
│
├── data-assimilation/
│   └── ...
│
└── verification-evs/
    └── ...
```

### 3.3 Local Development Mode

For developers working locally (not on shared infrastructure):

```
~/.sdd/
├── config.json                         # Global SDD configuration
├── credentials/                        # API tokens (gitignored)
│
└── projects/
    ├── global-workflow/                # Project-specific workspace
    │   ├── .sdd_project.json           # Links to remote workspace
    │   ├── workflows/
    │   ├── executions/
    │   └── context/
    │
    └── ufs-weather-model/
        └── ...
```

---

## 4. Workspace Configuration

### 4.1 Workspace Registry

```json
// sdd_workspaces/.workspace_registry.json
{
  "version": "1.0",
  "workspaces": [
    {
      "id": "gfs-forecast-team",
      "name": "GFS Forecast Development Team",
      "type": "team",
      "created": "2026-01-02T00:00:00Z",
      "owner": "terrence.h",
      "members": ["terrence.h", "developer.b", "developer.c"],
      "repositories": ["NOAA-EMC/global-workflow"],
      "default_context": {
        "include_ee2_standards": true,
        "target_hpc": ["hera", "wcoss2"]
      }
    },
    {
      "id": "data-assimilation",
      "name": "Data Assimilation Team",
      "type": "team",
      "owner": "da_lead",
      "members": ["da_lead", "da_dev1", "da_dev2"],
      "repositories": ["NOAA-EMC/GDASApp", "NOAA-EMC/GSI"]
    }
  ]
}
```

### 4.2 Workspace Metadata

```json
// sdd_workspaces/gfs-forecast-team/.workspace.json
{
  "id": "gfs-forecast-team",
  "version": "1.0",
  "name": "GFS Forecast Development Team",
  "description": "SDD workspace for GFS forecast model development",
  
  "settings": {
    "default_execution_mode": "isd",
    "allow_usd": true,
    "max_usd_timeout": 600000,
    "require_approval_for": ["code_modification", "command", "ingestion"],
    "auto_approve": ["health_check", "validation", "data_query"]
  },
  
  "context_defaults": {
    "repositories": [
      "supported_repos/global-workflow",
      "supported_repos/ufs-weather-model"
    ],
    "ee2_standards": true,
    "hpc_platforms": ["hera", "wcoss2", "orion"]
  },
  
  "integrations": {
    "github": {
      "repository": "NOAA-EMC/global-workflow",
      "issue_labels": ["sdd-workflow", "ai-assisted"]
    },
    "slack": {
      "channel": "#gfs-dev-notifications"
    }
  },
  
  "retention": {
    "execution_logs_days": 90,
    "completed_workflows_days": 365
  }
}
```

### 4.3 User Preferences

```json
// sdd_workspaces/gfs-forecast-team/users/terrence.h/.user_preferences.json
{
  "user_id": "terrence.h",
  "display_name": "Terrence Harding",
  
  "defaults": {
    "execution_mode": "isd",
    "preferred_form_factor": "vscode",
    "usd_agent": "claude_cli",
    "auto_approve_patterns": [
      { "step_type": "health_check" },
      { "step_type": "validation" },
      { "step_type": "command", "pattern": "node --check.*" }
    ]
  },
  
  "notifications": {
    "on_usd_complete": true,
    "on_approval_timeout": true,
    "channel": "vscode"
  },
  
  "context": {
    "signature": "# Author: Terrence Harding\n# Generated by SDD Framework",
    "default_branch": "develop"
  }
}
```

---

## 5. Execution State Management

### 5.1 Execution Record Schema

```json
// sdd_workspaces/<org>/users/<user>/executions/active/exec_<id>.json
{
  "execution_id": "exec_1767371234567_abc123",
  "workflow": {
    "name": "gfsv17_ufs_upgrade",
    "version": "1.0.0",
    "source": "team",  // "platform", "team", or "user"
    "path": "sdd_workspaces/gfs-forecast-team/workflows/gfsv17_ufs_upgrade.md"
  },
  
  "user": {
    "id": "terrence.h",
    "workspace": "gfs-forecast-team"
  },
  
  "mode": "isd",
  "status": "awaiting_approval",  // "running", "awaiting_approval", "completed", "failed", "aborted"
  
  "started_at": "2026-01-02T10:30:00Z",
  "updated_at": "2026-01-02T10:35:22Z",
  
  "steps": [
    {
      "name": "verify_system_health",
      "type": "health_check",
      "status": "completed",
      "started_at": "2026-01-02T10:30:01Z",
      "completed_at": "2026-01-02T10:30:03Z",
      "result": { "chromadb": "healthy", "neo4j": "healthy" }
    },
    {
      "name": "analyze_current_state",
      "type": "mcp_tool",
      "status": "completed",
      "result": { "files_analyzed": 47, "functions": 231 }
    },
    {
      "name": "generate_upgrade_plan",
      "type": "sub_agent",
      "status": "awaiting_approval",
      "approval_request": {
        "requested_at": "2026-01-02T10:35:22Z",
        "timeout_at": "2026-01-02T10:40:22Z",
        "preview": {
          "objective": "Generate UFS upgrade plan",
          "form_factor": "claude_cli",
          "constraints": { "timeout": 300000, "sandbox": true }
        }
      }
    }
  ],
  
  "context": {
    "variables": { "target_version": "v17.1" },
    "accumulated_results": {}
  },
  
  "usd_sessions": [
    {
      "step": "generate_upgrade_plan",
      "agent": "claude_cli",
      "instruction_file": ".claude/exec_abc123_step3.md",
      "started_at": null,
      "result": null
    }
  ]
}
```

### 5.2 Execution History Index

```json
// sdd_workspaces/<org>/execution_log/index.json
{
  "total_executions": 127,
  "by_status": {
    "completed": 98,
    "failed": 12,
    "aborted": 17
  },
  "by_workflow": {
    "gfsv17_ufs_upgrade": 23,
    "ee2_fcst_compliance": 45,
    "forecast_post_optimization": 59
  },
  "by_user": {
    "terrence.h": 67,
    "developer.b": 42,
    "developer.c": 18
  },
  "recent": [
    {
      "id": "exec_1767371234567_abc123",
      "workflow": "gfsv17_ufs_upgrade",
      "user": "terrence.h",
      "status": "completed",
      "completed_at": "2026-01-02T10:45:00Z"
    }
  ]
}
```

---

## 6. API Design

### 6.1 Workspace Management Tools

```javascript
// New MCP tools for workspace management

{
  name: 'list_sdd_workspaces',
  description: 'List available SDD workspaces for the current user',
  inputSchema: {
    type: 'object',
    properties: {
      include_details: { type: 'boolean', default: false }
    }
  }
}

{
  name: 'get_workspace_info',
  description: 'Get detailed information about an SDD workspace',
  inputSchema: {
    type: 'object',
    properties: {
      workspace_id: { type: 'string', description: 'Workspace ID or "current"' }
    },
    required: ['workspace_id']
  }
}

{
  name: 'set_active_workspace',
  description: 'Set the active workspace for subsequent SDD operations',
  inputSchema: {
    type: 'object',
    properties: {
      workspace_id: { type: 'string' }
    },
    required: ['workspace_id']
  }
}

{
  name: 'create_workspace',
  description: 'Create a new team or personal SDD workspace',
  inputSchema: {
    type: 'object',
    properties: {
      name: { type: 'string' },
      type: { enum: ['team', 'personal'] },
      parent_org: { type: 'string', description: 'Parent organization for team workspaces' },
      repositories: { type: 'array', items: { type: 'string' } }
    },
    required: ['name', 'type']
  }
}
```

### 6.2 Workflow Management in Workspace Context

```javascript
{
  name: 'list_workflows',
  description: 'List workflows in the current workspace (includes inherited from team/platform)',
  inputSchema: {
    type: 'object',
    properties: {
      scope: { 
        enum: ['all', 'user', 'team', 'platform'],
        default: 'all',
        description: 'Filter by workflow scope'
      },
      status: {
        enum: ['all', 'draft', 'active', 'archived'],
        default: 'active'
      }
    }
  }
}

{
  name: 'create_workflow',
  description: 'Create a new workflow in the current workspace',
  inputSchema: {
    type: 'object',
    properties: {
      name: { type: 'string' },
      template: { type: 'string', description: 'Base template to use' },
      scope: { enum: ['user', 'team'], default: 'user' },
      description: { type: 'string' }
    },
    required: ['name']
  }
}

{
  name: 'get_execution_history',
  description: 'Get execution history for workflows in current workspace',
  inputSchema: {
    type: 'object',
    properties: {
      workflow_name: { type: 'string', description: 'Filter by workflow' },
      user_id: { type: 'string', description: 'Filter by user' },
      status: { enum: ['all', 'completed', 'failed', 'aborted'] },
      limit: { type: 'number', default: 20 }
    }
  }
}
```

---

## 7. User Flow Examples

### 7.1 New User Onboarding

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     NEW USER ONBOARDING FLOW                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. User connects to MCP/RAG system                                     │
│     └── System detects user identity (from env, git config, or prompt)  │
│                                                                         │
│  2. System checks workspace membership                                  │
│     └── list_sdd_workspaces() returns available workspaces              │
│                                                                         │
│  3. If no workspace: prompt to join or create                           │
│     ┌─────────────────────────────────────────────────────────────┐    │
│     │ "You're not a member of any SDD workspace.                  │    │
│     │                                                             │    │
│     │  Options:                                                   │    │
│     │  1. Join existing team: gfs-forecast-team (request access)  │    │
│     │  2. Create personal workspace                               │    │
│     │  3. Browse platform templates"                              │    │
│     └─────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  4. User creates or joins workspace                                     │
│     └── Personal workspace auto-created under their org                 │
│                                                                         │
│  5. System initializes user preferences with sensible defaults          │
│                                                                         │
│  6. User can now:                                                       │
│     • Create workflows from templates                                   │
│     • Execute workflows in ISD/USD mode                                 │
│     • View team workflows (if in team workspace)                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Creating and Executing a Workflow

```
User: "I need to refactor the UFS driver for EE2 compliance"

AI: I'll help you create an SDD workflow for that. Let me check your workspace.

    [Calls: get_workspace_info({ workspace_id: "current" })]
    
    You're in the gfs-forecast-team workspace.
    
    I found a template that matches your goal:
    - ee2_compliance_audit (platform template)
    
    Would you like me to:
    1. Create a new workflow from this template
    2. Start from scratch
    3. Use an existing team workflow

User: "1 - use the template"

AI: [Calls: create_workflow({
      name: "ufs_driver_ee2_refactor",
      template: "ee2_compliance_audit",
      scope: "user",
      description: "EE2 compliance refactoring for UFS driver module"
    })]
    
    Created workflow: ufs_driver_ee2_refactor
    Location: sdd_workspaces/gfs-forecast-team/users/terrence.h/workflows/
    
    The workflow has these steps:
    1. Health check (auto)
    2. Scan current compliance (auto)
    3. Generate refactoring plan (USD - requires approval)
    4. Apply changes (USD - requires approval)
    5. Validate compliance (auto)
    
    Ready to execute in ISD mode?

User: "Yes, run it"

AI: [Calls: execute_sdd_workflow_supervised({
      workflow_name: "ufs_driver_ee2_refactor",
      mode: "isd",
      params: { target: "sorc/ufs_model.fd/driver/" }
    })]
    
    [Execution proceeds with approval gates...]
```

### 7.3 Team Workflow Sharing

```
User: "My refactoring workflow worked well. Share it with the team."

AI: [Calls: promote_workflow({
      workflow_name: "ufs_driver_ee2_refactor",
      from_scope: "user",
      to_scope: "team",
      new_name: "ee2_ufs_driver_compliance"  // Optional rename
    })]
    
    Workflow promoted to team level.
    
    New location: sdd_workspaces/gfs-forecast-team/workflows/ee2_ufs_driver_compliance.md
    
    Team members can now use this workflow:
    - terrence.h (owner)
    - developer.b
    - developer.c
```

---

## 8. Storage Backend Options

### 8.1 Filesystem (Default)

```
Pros:
- Simple, no additional dependencies
- Git-compatible for versioning
- Works offline

Cons:
- Requires shared filesystem for team workspaces
- No built-in access control

Use for: Local development, single-user scenarios
```

### 8.2 Git Repository

```
Pros:
- Built-in versioning and history
- Pull request workflow for team templates
- Works with existing GitHub/GitLab infrastructure

Cons:
- Latency for read/write operations
- Merge conflicts possible

Use for: Team workspaces with async collaboration
```

### 8.3 Database (Future)

```
Pros:
- Fine-grained access control
- Real-time collaboration
- Better query performance for large histories

Cons:
- Additional infrastructure
- More complex setup

Use for: Enterprise deployment with many concurrent users
```

### 8.4 Hybrid Approach (Recommended)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      HYBRID STORAGE STRATEGY                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Platform (sdd_framework/)                                              │
│    └── Git repository (versioned, PR workflow)                          │
│                                                                         │
│  Team Workspaces (sdd_workspaces/<org>/)                                │
│    └── Git repository per team (GitHub/GitLab)                          │
│    └── Execution logs in local filesystem (ephemeral)                   │
│                                                                         │
│  User Workspaces                                                        │
│    └── Local filesystem (~/.sdd/ or workspace subdir)                   │
│    └── Sync to team repo for sharing                                    │
│                                                                         │
│  Execution State                                                        │
│    └── Local filesystem (fast access)                                   │
│    └── Optional: Redis for distributed execution (future)               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Access Control Model

### 9.1 Permission Levels

| Level | Can Read | Can Execute | Can Write | Can Admin |
|-------|----------|-------------|-----------|-----------|
| **Guest** | Platform templates | No | No | No |
| **Member** | Team + own workflows | Own workflows | Own workspace | No |
| **Contributor** | Team workflows | Team workflows | Team workflows | No |
| **Admin** | All in org | All in org | All in org | Workspace settings |
| **Platform** | Everything | Everything | Platform only | Platform config |

### 9.2 Permission Matrix

```yaml
# Example: Team workspace permissions
workspace: gfs-forecast-team
permissions:
  # Platform templates - everyone can read
  "sdd_framework/templates/*":
    guest: [read]
    member: [read]
    contributor: [read]
    admin: [read]
  
  # Team workflows - members can read, contributors can write
  "sdd_workspaces/gfs-forecast-team/workflows/*":
    member: [read, execute]
    contributor: [read, write, execute]
    admin: [read, write, execute, delete]
  
  # User workspaces - only owner has access
  "sdd_workspaces/gfs-forecast-team/users/{user}/*":
    owner: [read, write, execute, delete]
    admin: [read]  # For support purposes
  
  # Execution logs - team can view
  "sdd_workspaces/gfs-forecast-team/execution_log/*":
    member: [read]
    contributor: [read]
    admin: [read, delete]
```

---

## 10. Implementation Steps

### Phase 4D-1: Workspace Infrastructure (~10 hours)

| Step | Type | Description |
|------|------|-------------|
| 1.1 | code_generation | Create `WorkspaceManager.js` - workspace CRUD operations |
| 1.2 | code_generation | Create `WorkspaceResolver.js` - workflow path resolution |
| 1.3 | code_modification | Reorganize `sdd_framework/` into platform/ subdirectory |
| 1.4 | code_generation | Create workspace schema and validation |

### Phase 4D-2: Execution State Management (~8 hours)

| Step | Type | Description |
|------|------|-------------|
| 2.1 | code_generation | Create `ExecutionStateStore.js` - per-user execution tracking |
| 2.2 | code_modification | Update `WorkflowExecutor.js` to use workspace-aware paths |
| 2.3 | code_generation | Create execution history indexing and query |

### Phase 4D-3: MCP Tool Integration (~6 hours)

| Step | Type | Description |
|------|------|-------------|
| 3.1 | code_generation | Add workspace management MCP tools |
| 3.2 | code_modification | Update existing SDD tools for workspace context |
| 3.3 | code_generation | Add user preference management tools |

### Phase 4D-4: User Experience (~6 hours)

| Step | Type | Description |
|------|------|-------------|
| 4.1 | code_generation | Create onboarding flow for new users |
| 4.2 | code_generation | Create workflow promotion (user → team) |
| 4.3 | documentation | User guide for workspace management |

---

## 11. Migration Path

### From Current State

```
Current:
  sdd_framework/workflows/phase4*.md  → Platform development workflows

After Phase 4D:
  sdd_framework/
    ├── platform/                     → Platform workflows (moved)
    │   └── phase4*.md
    ├── methodology/                  → Unchanged
    ├── templates/                    → User-facing templates
    └── validation/                   → Unchanged
  
  sdd_workspaces/                     → New directory for user/team workspaces
    ├── .workspace_registry.json
    └── <org>/
        └── users/<user>/
```

### Migration Script

```bash
#!/bin/bash
# migrate_to_workspaces.sh

# 1. Create new directory structure
mkdir -p sdd_framework/platform
mkdir -p sdd_workspaces

# 2. Move platform workflows
mv sdd_framework/workflows/phase*.md sdd_framework/platform/

# 3. Create user-facing templates directory
mkdir -p sdd_framework/templates

# 4. Initialize workspace registry
echo '{"version":"1.0","workspaces":[]}' > sdd_workspaces/.workspace_registry.json

# 5. Create default workspace for current user
# (handled by WorkspaceManager on first access)
```

---

## 12. Validation Criteria

### Acceptance Tests

- [ ] User can create personal workspace
- [ ] Team admin can create team workspace and add members
- [ ] Workflow resolution follows tier hierarchy (user → team → platform)
- [ ] Execution state persists across sessions
- [ ] User A cannot access User B's workflows
- [ ] Team members can share workflows within team
- [ ] Platform templates are read-only for users
- [ ] Execution history is queryable by workflow/user/status

### Performance Requirements

- Workspace lookup < 100ms
- Workflow resolution < 200ms
- Execution state write < 50ms
- History query (1000 records) < 500ms

---

## 13. Dependencies

- Phase 4C: ISD/USD Architecture (required for execution)
- Filesystem access for default storage backend
- Optional: Git CLI for repository-backed workspaces
- Optional: GitHub/GitLab API for team repository integration

---

## 14. Estimated Effort

| Component | Hours |
|-----------|-------|
| Workspace infrastructure | 10 |
| Execution state management | 8 |
| MCP tool integration | 6 |
| User experience & migration | 6 |
| **Total** | **30 hours** |

---

## 15. Future Extensions

- **Real-time collaboration**: Multiple users editing same workflow
- **Workflow marketplace**: Share workflows across organizations
- **Usage analytics**: Track which workflows are most used/effective
- **Workflow versioning**: Semantic versions with changelog
- **Approval delegation**: Team leads can pre-approve for members
- **Cost attribution**: Track LLM costs per user/team/workflow

---

## 16. Security Considerations

1. **Path traversal**: Validate all workspace/workflow paths
2. **Privilege escalation**: Enforce permission checks at API level
3. **Execution isolation**: USD sub-agents run in user's context only
4. **Secrets management**: User API keys stored securely (not in workflow files)
5. **Audit logging**: All workspace operations logged with user identity

---

*"The platform develops itself. Users develop their projects. Workspaces keep them cleanly separated."*
