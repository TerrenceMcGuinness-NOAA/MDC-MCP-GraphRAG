# Contributing to EIB MCP-RAG Server

Thank you for your interest in contributing to the EIB MCP-RAG Server project. This document outlines our development workflow, branch strategy, and contribution guidelines.

## Table of Contents

- [Development Environment](#development-environment)
- [GitFlow Branch Strategy](#gitflow-branch-strategy)
- [Making Changes](#making-changes)
- [Pull Request Process](#pull-request-process)
- [Code Style Guidelines](#code-style-guidelines)
- [SDD-First Development](#sdd-first-development)
- [Testing Requirements](#testing-requirements)

---

## Development Environment

### Prerequisites

- Docker and Docker Compose
- Node.js 18+ (or use Spack modules on HPC)
- Git with submodule support
- Access to GitLab Container Registry (for production images)

### Quick Setup

```bash
# Clone with submodules
git clone --recursive git@gitlab-licensed.vlab.noaa.gov:NWS/Operations/NCEP/EMC/EIB/eib-mcp-rag-server.git
cd eib-mcp-rag-server

# Start databases
docker compose -f docker-compose.devops.yaml up -d chromadb neo4j

# Install dependencies and start MCP server
cd mcp_server_node
npm install
node src/UnifiedMCPServer.js full
```

### Environment Configuration

Source the environment script for proper path configuration:

```bash
source SETUP/mcp-env.sh
```

---

## GitFlow Branch Strategy

We use a modified GitFlow workflow with environment-specific branches for DevOps automation.

### Branch Structure

```
main (protected - production releases only)
│
├── develop (integration branch)
│   └── feature/* (feature branches)
│   └── fix/* (bug fix branches)
│
├── env/dev-ops (container validation)
├── env/staging (pre-production)
└── env/production (live deployment)
│
├── release/* (release candidates)
└── hotfix/* (emergency production fixes)
```

### Branch Purposes

| Branch | Purpose | Database Access | Who Can Merge |
|--------|---------|-----------------|---------------|
| `feature/*` | New features, experimentation | Local/Dev DBs only | Developers |
| `fix/*` | Bug fixes | Local/Dev DBs only | Developers |
| `develop` | Integration branch | Local/Dev DBs only | Developers (via MR) |
| `env/dev-ops` | Container validation | Containerized DBs | CI/CD Pipeline |
| `env/staging` | Pre-production testing | Staging DBs (read-only) | CI/CD Pipeline |
| `env/production` | Live deployment | Production DBs | CI/CD Pipeline only |
| `main` | Stable reference | N/A | Protected (tags only) |
| `release/*` | Release preparation | Staging DBs | Release Manager |
| `hotfix/*` | Emergency fixes | Staging → Production | Senior Devs + Approval |

### Branch Protection Rules

- **develop**: Requires 1 approval, no force push
- **env/dev-ops**: Requires 1 approval, CI must pass
- **env/staging**: Requires 2 approvals, CI + security scan must pass
- **env/production**: Requires 2 approvals + CODEOWNER, CI/CD only deployment
- **main**: Protected, only accepts merges from production

---

## Making Changes

### 1. Create a Feature Branch

Always branch from `develop`:

```bash
git checkout develop
git pull origin develop
git checkout -b feature/my-feature-name
```

Use descriptive branch names:
- `feature/ee2-compliance-tools` - New feature
- `fix/chromadb-connection-timeout` - Bug fix
- `docs/update-readme` - Documentation updates

### 2. Development Mode

Set environment for local development:

```bash
export MCP_ENV=development
```

This uses:
- `PersistentClient` for ChromaDB (direct SQLite access)
- Local Docker containers for databases
- Full write access for experimentation

### 3. Commit Guidelines

Write clear, descriptive commit messages:

```
feat(tools): add EE2 COM/COMOUT compliance checker

- Implement COM directory validation against EE2 standards
- Add configurable output format (json, markdown, summary)
- Include severity levels (CRITICAL, WARNING, ADVISORY)

Refs: #123
```

**Commit Prefixes:**
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

### 4. Keep Branch Updated

Regularly rebase on develop to avoid merge conflicts:

```bash
git fetch origin
git rebase origin/develop
```

---

## Pull Request Process

### 1. Before Submitting

- [ ] Run tests locally: `npm test`
- [ ] Check for lint errors: `npm run lint`
- [ ] Update documentation if needed
- [ ] Verify MCP health check passes
- [ ] Create/update SDD workflow if adding new features

### 2. Create Merge Request

Push your branch and create MR to `develop`:

```bash
git push origin feature/my-feature-name
```

In GitLab:
1. Create Merge Request from your branch to `develop`
2. Fill out the MR template
3. Assign reviewers
4. Link related issues

### 3. MR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] New feature
- [ ] Bug fix
- [ ] Documentation update
- [ ] Refactoring

## Testing Done
- [ ] Unit tests pass
- [ ] Integration tests pass (if applicable)
- [ ] Manual testing completed

## SDD Reference
Link to SDD workflow if applicable: `sdd_framework/workflows/phase_xxx.md`

## Checklist
- [ ] Code follows project style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No new warnings introduced
```

### 4. Review Process

1. At least 1 approval required for `develop`
2. CI pipeline must pass
3. Address all review comments
4. Squash commits if requested

### 5. After Merge

Delete your feature branch:

```bash
git checkout develop
git pull origin develop
git branch -d feature/my-feature-name
git push origin --delete feature/my-feature-name
```

---

## Code Style Guidelines

### JavaScript/Node.js

- **Indentation**: 2 spaces
- **Console output**: ASCII prefixes only (`[OK]`, `[ERROR]`, `[WARN]`) - NO emoji (breaks MCP stdio)
- **Semicolons**: Required
- **Quotes**: Single quotes for strings

```javascript
// Good
console.log('[OK] Server started successfully');

// Bad - emoji breaks MCP stdio protocol
console.log('✅ Server started successfully');
```

### Python

- **Style**: PEP 8
- **Indentation**: 4 spaces
- **Docstrings**: NumPy style
- **Max line length**: 120 characters

```python
def analyze_compliance(file_path: str, standards: list) -> dict:
    """
    Analyze file for EE2 compliance.

    Parameters
    ----------
    file_path : str
        Path to the file to analyze
    standards : list
        List of EE2 standards to check against

    Returns
    -------
    dict
        Compliance results with violations and recommendations
    """
    pass
```

### Bash

- **Variables**: Always quote - `"${variable}"`
- **Shebang**: `#!/bin/bash`
- **Error handling**: Use `set -e` for critical scripts

```bash
#!/bin/bash
set -e

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[OK] Script directory: ${SCRIPT_DIR}"
```

---

## SDD-First Development

**Rule**: "If it's not in the SDD, it doesn't get coded."

For new features or significant changes:

### 1. Create SDD Workflow

Before coding, create a workflow plan in `sdd_framework/workflows/`:

```bash
# Create new SDD workflow
cp sdd_framework/templates/workflow_template.md \
   sdd_framework/workflows/phase_XX_my_feature.md
```

### 2. SDD Structure

```markdown
# Phase XX: Feature Name

**Description**: What this feature does
**Priority**: HIGH/MEDIUM/LOW
**Timeline**: Estimated duration
**Status**: PLANNING/IN_PROGRESS/COMPLETE

## Problem Statement
Why is this needed?

## Architecture
How will it be implemented?

## Implementation Steps
Step-by-step plan

## Validation
How to verify it works
```

### 3. Reference SDD in MR

Link your SDD workflow in the merge request.

---

## Testing Requirements

### Unit Tests

Required for all new tools and utilities:

```bash
cd mcp_server_node
npm test
```

### Integration Tests

Required for database interactions:

```bash
npm run test:integration
```

### MCP Health Check

Verify all tools are working:

```javascript
// Use MCP tool
mcp_health_check({ detailed: true, deep: true })
```

### Manual Testing Checklist

- [ ] MCP server starts without errors
- [ ] All tools appear in `docker mcp tools ls`
- [ ] Sample queries return expected results
- [ ] No regressions in existing functionality

---

## Environment-Specific Guidelines

### Development (feature/*, develop)

- Free to experiment
- Can create/delete test collections
- Use `MCP_ENV=development`

### DevOps (env/dev-ops)

- Container-based testing only
- CI/CD validates builds
- Use `MCP_ENV=devops`

### Staging/Production

- **Never run scripts directly**
- All changes via CI/CD pipeline
- Requires approvals

---

## Getting Help

- **Documentation**: See `docs/` directory
- **SDD Workflows**: See `sdd_framework/workflows/`
- **Phase 12 DevOps**: [phase12_devops_gitflow_containerization.md](sdd_framework/workflows/phase12_devops_gitflow_containerization.md)
- **Project Lead**: Terrence McGuinness

---

## License

This project is developed by NOAA Environmental Modeling Center / Enterprise Infrastructure Branch for internal use.

---

**Last Updated**: December 23, 2025
