# SDD Execution Modes: Plan vs Execute

**Key Insight**: SDD's `dry_run` mode is like `terraform plan` — it parses specifications and reports *intentions*, not results. It is **spec parsing, not sandboxed execution**.

---

## The Mental Model

| Analogy | What Happens |
|---------|--------------|
| **Terraform Plan** | Reads config → Reports "will create X, modify Y" → Stops |
| **SDD Dry Run** | Parses workflow spec → Reports "would execute step A, B, C" → Stops |
| **Recipe Reading** | Read ingredients and steps → Understand what to cook → Don't actually cook |

**Dry run answers**: "What steps are defined and what would they do?"  
**Dry run does NOT answer**: "Will this code work when executed?"

---

## Execution Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| `dry_run` | Parse workflow, report step intentions | Preview before committing |
| `supervised` | Execute steps, pause for human approval on side-effects | Development, first-time runs |
| `auto_approved` | Execute steps, auto-approve from pre-defined list | CI/CD with known-safe patterns |
| `autonomous` | Execute all steps without approval | **DISABLED** (safety-critical systems) |

---

## What Dry Run Actually Does

```
Workflow YAML → Parse → For each step:
                          ├─ Has side effects? → Report "REQUIRES APPROVAL"
                          └─ Read-only? → Report "AUTO-EXECUTE"
                        → Return preview report
                        → Stop (nothing executed)
```

### Side-Effect Classification

**Require Approval** (mutate state):
- `code_generation` — Creates files
- `code_modification` — Edits files  
- `command` — Shell commands
- `ingestion` — Database writes
- `file_delete` — Removes files
- `git_operation` — Commits, pushes

**Read-Only** (no approval needed):
- `health_check` — Queries system status
- `data_query` — Reads data
- `validation` — Checks conditions
- `analysis` — Computes metrics

---

## What Dry Run Is NOT

| Common Assumption | Reality |
|-------------------|---------|
| "Simulates execution in sandbox" | No — just parses spec metadata |
| "Runs code in isolated environment" | No — no code executes |
| "Creates feature branch to test" | No — no git operations |
| "Validates generated code will work" | No — no syntax/runtime checks |

---

## The Gap: Plan vs Proof

Dry run proves the **specification is valid**.  
Dry run does NOT prove the **execution will succeed**.

### What Would Close This Gap?

| Approach | Description | Status |
|----------|-------------|--------|
| **Sandboxed Execution** | Run in temp directory, discard after | Not implemented |
| **Feature Branch Mode** | Execute on branch, verify, merge or delete | Not implemented |
| **Container Isolation** | Spin up container, execute, destroy | Partial (MCP gateway) |
| **Copy-on-Write FS** | Overlay filesystem, discard changes | Not implemented |

---

## Practical Implications

### When to Use Each Mode

```
First time running a workflow?
  └─► dry_run → Review the plan
        └─► supervised → Execute with approval gates
        
Workflow previously validated?
  └─► auto_approved → Execute with manifest-based approvals

Production CI/CD?
  └─► auto_approved + ManifestApprovalProvider
```

### Trust Model

| Mode | Trust Level | Who Decides |
|------|-------------|-------------|
| `dry_run` | Zero trust | Human reviews plan |
| `supervised` | Step-by-step trust | Human approves each side-effect |
| `auto_approved` | Pattern trust | Manifest pre-approves known patterns |
| `autonomous` | Full trust | **Disabled** — no human in loop |

---

## Summary

> **SDD dry_run = "Show me the recipe" not "Cook in a test kitchen"**

The value is in **explicit planning** before execution:
1. See every step before it runs
2. Identify side-effects requiring approval
3. Understand the workflow structure
4. Make informed decisions about execution mode

True sandboxed execution remains a future capability. The current system prioritizes **transparency and human oversight** over automated validation.

---

*Document created: January 6, 2026*  
*Context: Clarifying SDD execution semantics for stakeholder communication*
