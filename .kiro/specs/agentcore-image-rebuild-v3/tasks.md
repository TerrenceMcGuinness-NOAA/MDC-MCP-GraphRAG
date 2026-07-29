# Implementation Plan: AgentCore Image Rebuild v3

## Overview

Rebuild the AgentCore runtime Docker image from current `develop` (carrying
Phases 67–73) and deploy to the live runtime. Routine operator procedure.

## Tasks

- [ ] 1. Build the image
  - [ ] 1.1 `docker build --platform linux/arm64` from `mcp_server_python/Dockerfile`; tag `python-tenants-v3` + git-SHA
    - _Requirements: 1.1, 1.2, 1.3_

- [ ] 2. Local smoke test
  - [ ] 2.1 Confirm the image starts and registers 52+ tools, 9 modules (optional — full verify is post-deploy)
    - _Requirements: 1.4_

- [ ] 3. Push to ECR
  - [ ] 3.1 `aws ecr get-login-password` + `docker push` both tags; confirm prior tags (`v1`, `v2`) still present
    - _Requirements: 2.1, 2.2_

- [ ] 4. Record rollback command
  - [ ] 4.1 Log the `update-agent-runtime` command with `python-tenants-v2` URI before deploying
    - _Requirements: 5.1, 5.2_

- [ ] 5. Update the runtime
  - [ ] 5.1 `update-agent-runtime` with new containerUri + full config payload
    - _Requirements: 3.1, 3.2, 3.3_
  - [ ] 5.2 Poll until READY (≤5 min)
    - _Requirements: 3.2_

- [ ] 6. Post-deploy verification
  - [ ] 6.1 `mcp_health_check --deep --detailed --functional` → HEALTHY 4/4, ≥9/10 pass
    - _Requirements: 4.1_
  - [ ] 6.2 `get_knowledge_base_status` → `Total Documents > 0`, `(tenant scope)` annotation
    - _Requirements: 4.2_
  - [ ] 6.3 `check_knowledge_integrity` → Coverage Gap `[OK] (graph-only)`, not `[SKIP]`
    - _Requirements: 4.3_
  - [ ] 6.4 `get_knowledge_base_status(all_tenants=True)` → whole-graph count
    - _Requirements: 4.4_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1", "4.1"] },
    { "id": 3, "tasks": ["5.1"] },
    { "id": 4, "tasks": ["5.2"] },
    { "id": 5, "tasks": ["6.1", "6.2", "6.3", "6.4"] }
  ]
}
```
