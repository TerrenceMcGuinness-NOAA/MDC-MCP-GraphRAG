# CLI Implementation Prompt for Phase 63b (v2 — post-retrospective)

**Role Context**: You are an expert DevOps/Python engineer contributing to the NOAA Global Workflow AI Assistant. Your task is to **execute end-to-end** Phase 63b (Python MCP Container Parity for Docker MCP Gateway), v2. A prior CLI attempt stalled at 2/5 steps; the spec has been revised with a defect register (D1–D5) and hard verification gates. You are expected to **do the work and verify it**, not merely emit code blocks.

**Authoritative Specification** (read it first, in full):
`sdd_framework/workflows/phase63b_python_container_gateway_parity.md` (v2.0.0)

The spec is self-contained: §1.1 documents the v1 retrospective and the five defects (D1 missing `MCP_WORKFLOW_MOUNT`, D2 dangling host symlink farm, D3 `MCP_TRANSPORT=stdio` contradiction, D4 stale-catalog gateway launch, D5 missing `GITHUB_TOKEN`), §3 lists 11 acceptance criteria, and §4 gives the 5-step implementation plan with per-step hard gates.

**Retained v1 artifacts — rework in place, do NOT recreate from scratch**:
- `SETUP/dockerfiles/Dockerfile.mcp-python` (exists; apply D1/D2/D3 fixes per spec Step 1)
- `SETUP/docker-mcp/catalogs/eib-local.yaml` (v1 edits present; apply D1/D2/D5 fixes per spec Step 2)

**SDD Session Discipline (mandatory)**:
1. `start_sdd_session(phase="phase63b_python_container_gateway_parity", total_steps=5)` — the v1 session is already abandoned; start fresh.
2. After each spec step passes its **hard gate**, call `record_sdd_step(step=N, name=..., tag=...)` with the tag from the spec. Never record an unverified step.
3. Step 4 (Verify parity) passes only when the gateway health check reports HEALTHY (4/4), 11/11 functional (github_tools **pass**, not SKIP), and all 5 tenants reachable — matching `eib-mcp-rag-full` output.
4. Finish with Step 5 (CHANGELOG `[Unreleased]` entry + `.github/copilot-instructions.md` gateway section rewrite), then `complete_sdd_session(summary=...)`.

**Key constraints**:
- Console output ASCII only (`[OK]`/`[ERROR]`/`[WARN]`), 2-space indent, quoted bash variables.
- The canonical catalog is the absolute repo path — never launch the gateway from the `~/.docker/mcp/` copy (D4).
- Never bind-mount the host `.pw_workflow_mount` into the container; the entrypoint wrapper regenerates the farm in-container (D2).
- `git add` changed files for review; do NOT `git commit` or `git push`.