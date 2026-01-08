# SDD Workflow Step Type Reference: Verb + Noun Paradigm

**Purpose**: Define a unified step type vocabulary using verb+noun semantics that eliminates the artificial split between "planning" and "executable" documents.

**Design Principle**: A single workflow document serves both planning AND execution. The verb determines approval requirements; the noun clarifies the target.

**Related Files**:
- `mcp_server_node/src/sdd/approval/ApprovalProvider.js` - Approval policy by verb
- `mcp_server_node/src/sdd/WorkflowExecutor.js` - Parses and executes workflows

---

## The Problem with Noun-Centric Types

The original type vocabulary mixed **where** (destination) with **how** (content source):

| Old Type | Noun Focus | Actually Described |
|----------|------------|-------------------|
| `file_creation` | The **container** (file) | Where bytes land |
| `code_generation` | The **content** (code) | What gets produced |

These are **orthogonal axes** being treated as alternatives, leading to:
- Confusing 1:1 mappings (`file_creation` → `code_generation`)
- Separate "planning" vs "executable" documents
- Arbitrary vocabulary that doesn't express intent

---

## Verb + Noun Paradigm

### The Verb = HOW (Determines Approval)

| Verb | Meaning | Approval | Why |
|------|---------|----------|-----|
| `generate` | LLM synthesizes content | ✅ Required | Non-deterministic output |
| `write` | Literal content copied | ⚡ Context | Content is shown, may auto-approve |
| `execute` | Run command/script | ✅ Required | Side effects on system |
| `delete` | Remove artifact | ✅ Required | Destructive operation |
| `read` | Query/inspect | ❌ Auto | No state change |
| `validate` | Verify condition | ❌ Auto | No state change |

### The Noun = WHAT/WHERE (Clarifies Target)

| Noun | Target Type | Examples |
|------|-------------|----------|
| `file` | File on disk | config, script, service unit |
| `command` | Shell execution | systemctl, docker, git |
| `query` | Data retrieval | ChromaDB search, Neo4j query |
| `service` | System service | start, stop, restart |
| `container` | Docker container | run, stop, remove |

### Combined Step Types

```
<verb>_<noun>

generate_file     → LLM creates file content (approval required)
write_file        → Copy literal content to file (content shown)
execute_command   → Run shell command (approval required)
delete_file       → Remove file (approval required)
read_query        → Retrieve data (auto-execute)
validate_service  → Check service status (auto-execute)
```

---

## Modality: The Key Distinction

The **verb** encodes whether content already exists or must be synthesized:

```
                    CONTENT SOURCE
                    ┌─────────────────────────┐
                    │  literal    generate    │
         ┌──────────┼────────────────────────┤
TARGET   │  file    │  write_file  generate_file  │
         │  command │  (n/a)       execute_command │
         │  query   │  read_query  (n/a)           │
         └──────────┴─────────────────────────────┘
```

### Literal (write_*) - Content is Determined

```markdown
### Step 1: Create systemd service
**Type**: write_file
**Target**: /etc/systemd/system/mcp-gateway.service
**Content**: literal

```ini
[Unit]
Description=MCP Gateway Service
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
ExecStart=/usr/bin/docker mcp gateway run --static
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
```

**Executor behavior**: Copy the code block exactly to the target path.
**Approval**: May auto-approve since content is fully visible.

### Generative (generate_*) - Content Must Be Synthesized

```markdown
### Step 1: Create systemd service
**Type**: generate_file  
**Target**: /etc/systemd/system/mcp-gateway.service
**Intent**: Create a systemd unit file that:
  - Starts after Docker service is available
  - Runs the MCP gateway in static mode
  - Restarts automatically on failure
  - Runs as the mcp-rag user
**Reference**:
```ini
[Unit]
Description=...  # Example structure only
```
```

**Executor behavior**: LLM generates content based on intent, presents for approval.
**Approval**: Always required - output is non-deterministic.

---

## Unified Markdown Format

```markdown
### Step N: <Human-Readable Title>
**Type**: <verb>_<noun>
**Target**: <path or identifier>
**Mode**: literal | generate     ← Optional, inferred from Type if unambiguous
**Intent**: <what this step accomplishes>   ← Required for generate_*
**Content**: literal | reference            ← Clarifies code block role

```<language>
<code block - either THE content or a reference example>
```
```

---

## Approval Policy by Verb

### Verbs Requiring Approval (Side Effects)

| Type Pattern | Why Approval Needed |
|--------------|---------------------|
| `generate_*` | Non-deterministic output - must review |
| `execute_*` | System side effects |
| `delete_*` | Destructive |
| `write_file` | Creates/modifies state (may auto-approve if literal) |

### Verbs Auto-Executing (Read-Only)

| Type Pattern | Why Auto-Execute |
|--------------|------------------|
| `read_*` | No state change |
| `validate_*` | Inspection only |
| `check_*` | Status query |

---

## Concrete Examples

### Example 1: Literal File Write

```markdown
### Step 1: Create Docker Compose Override
**Type**: write_file
**Target**: docker-compose.override.yaml
**Intent**: Add static mode configuration for gateway

```yaml
services:
  mcp-gateway:
    command: ["--static", "--port", "8888"]
    restart: unless-stopped
```
```

**Execution**: Content is literal → copy to file → optional approval (content visible).

### Example 2: Generated Configuration

```markdown
### Step 2: Generate Environment Configuration  
**Type**: generate_file
**Target**: SETUP/mcp-env.sh
**Intent**: Create environment setup script that:
  - Loads required Spack modules (gcc, python, neo4j)
  - Sets CHROMADB_HOST and NEO4J_URI
  - Configures PATH for local pip packages
  - Works on both HERA and WCOSS2
**Reference**:
```bash
#!/bin/bash
# Structure reference - actual content generated based on platform
module load gcc/11.5.0
module load python/3.11
...
```
```

**Execution**: LLM generates content → present for approval → write if approved.

### Example 3: Command Execution

```markdown
### Step 3: Start Gateway Service
**Type**: execute_command
**Intent**: Enable and start the MCP gateway systemd service

```bash
sudo systemctl daemon-reload && \
sudo systemctl enable mcp-gateway && \
sudo systemctl start mcp-gateway
```
```

**Execution**: Present command → approval required → execute if approved.

### Example 4: Validation (Auto-Execute)

```markdown
### Step 4: Verify Services Running
**Type**: validate_service
**Target**: mcp-gateway, mcp-rag
**Intent**: Confirm both services started successfully

```bash
systemctl is-active mcp-gateway && systemctl is-active mcp-rag
```
```

**Execution**: Auto-execute (read-only) → report result.

---

## Migration from Legacy Types

| Legacy Type | New Type | Notes |
|-------------|----------|-------|
| `code_generation` | `generate_file` | Verb clarifies synthesis |
| `code_modification` | `generate_patch` or `write_patch` | Depends on modality |
| `file_creation` | `write_file` or `generate_file` | Depends on modality |
| `file_modification` | `write_patch` or `generate_patch` | Depends on modality |
| `command` | `execute_command` | Explicit verb |
| `ingestion` | `execute_ingest` | Clarifies it's an action |
| `file_delete` | `delete_file` | Consistent verb_noun |
| `git_operation` | `execute_git` | Explicit verb |
| `health_check` | `check_health` | Verb first |
| `data_query` | `read_query` | Verb first |
| `validation` | `validate_*` | Add noun for target |
| `analysis` | `read_analysis` | Clarifies read-only |

---

## Workflow Execution Modes

### Dry Run (`mode: "dry_run"`)

- Parses all steps, shows plan
- No execution, no approvals
- Use to verify workflow structure

### Supervised (`mode: "supervised"`)

- Pauses at side-effect verbs (`generate_*`, `execute_*`, `delete_*`, `write_*`)
- Auto-executes read-only verbs (`read_*`, `validate_*`, `check_*`)
- Approval options: `approve` | `skip` | `quit` | `approve_all`

### Auto-Approved (`mode: "auto_approved"`)

- Specify verbs/types to auto-approve
- Example: auto-approve `write_file` when content is literal

```javascript
execute_sdd_workflow_supervised({
  workflow_name: "phase23_...",
  mode: "auto_approved",
  auto_approve: ["write_file", "validate_service"]
})
```

---

## One Document, Two Modes

**No more separate planning vs executable documents.**

The same workflow markdown serves both purposes:

| When Reading (Planning) | When Executing |
|------------------------|----------------|
| Human understands intent from titles + descriptions | Executor parses `Type` field |
| Code blocks show expected outcomes | Verb determines approval policy |
| `Intent` field explains rationale | `Target` specifies destination |

The **conversation with the LLM during authoring IS the iteration**. When ready to execute, launch the workflow - the system evaluates each step's verb and applies appropriate approval gates.

---

## Best Practices

### 1. Choose the Right Verb

| If the content is... | Use Verb | Example |
|---------------------|----------|---------|
| Already written in the code block | `write_` | `write_file` |
| Described by intent, LLM fills in | `generate_` | `generate_file` |
| A shell command to run | `execute_` | `execute_command` |
| A read/check operation | `read_` or `validate_` | `validate_service` |

### 2. Be Explicit About Modality

When ambiguous, add the `**Content**` field:

```markdown
**Content**: literal    ← This code block IS the file content
**Content**: reference  ← This code block shows structure/example only
```

### 3. Use Intent for Generative Steps

```markdown
**Intent**: Create a systemd unit that starts after Docker,
           runs as mcp-rag user, and restarts on failure
```

The Intent field is what the LLM uses to generate content.

### 4. Chain Related Commands

```bash
# Good: Single step with chained commands
sudo systemctl daemon-reload && \
sudo systemctl enable mcp-gateway && \
sudo systemctl start mcp-gateway
```

### 5. End with Validation

```markdown
### Step N: Verify Deployment
**Type**: validate_service
**Target**: mcp-gateway, mcp-rag

```bash
systemctl is-active mcp-gateway && systemctl is-active mcp-rag
```
```

---

## Implementation: Updating ApprovalProvider.js

To implement this paradigm, update the approval logic to be verb-based:

```javascript
// mcp_server_node/src/sdd/approval/ApprovalProvider.js

// Verbs that require approval (modify state)
export const SIDE_EFFECT_VERBS = [
  'generate',   // Non-deterministic content creation
  'write',      // File system modification  
  'execute',    // Command execution
  'delete',     // Destructive operations
];

// Verbs that auto-execute (read-only)
export const READ_ONLY_VERBS = [
  'read',       // Data queries
  'validate',   // Condition checks
  'check',      // Status inspection
];

// Extract verb from type: "generate_file" → "generate"
function getVerb(stepType) {
  return stepType.split('_')[0];
}

// Determine if approval required
function requiresApproval(stepType) {
  const verb = getVerb(stepType);
  return SIDE_EFFECT_VERBS.includes(verb);
}
```

---

## File Organization

With unified documents, the workflow directory becomes simpler:

```
sdd_framework/workflows/
├── phase23_static_mode_multiuser_gateway.md   ← Single document (plan + execute)
├── phase24_something_else.md                  ← Single document
├── _sdd_step_type_reference.md                ← This guide
└── _templates/
    └── workflow_template.md                   ← Starter template
```

No more `*_executable.md` duplicates needed.
