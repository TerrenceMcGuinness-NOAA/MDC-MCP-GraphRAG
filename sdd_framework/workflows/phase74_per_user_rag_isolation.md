# Phase 74 — Per-User RAG Isolation for Feature-Branch Development

**Version**: 0.1.0
**Created**: 2026-07-20
**Status**: draft (requirement captured; not scheduled)
**Estimated effort**: TBD (incremental; 4 waves from ~1 day to ~1 week each)
**Depends on**: Phase 8.35.0 (`agentcore-creds-provisioning` + per-user clone
provisioning via `user-provisioning-drift-remediation`); Phase 61
(`configurable_workflow_mount_base`); Phase 68 (`rag-data-plane-gap-closure`
for `resolve_collection_name` + tenant catalog model)
**Kiro spec**: _(to be authored — `.kiro/specs/per-user-rag-isolation/`)_
**Owner**: Terry McGuinness (OMD CAT)

---

## 1. Executive Summary

Each user on the shared Parallel Works host now has a personal clone of the
MCP repo at `${SCRATCH_ROOT}/<user>/eib-mcp-rag-server` (provisioned by
`00-users.sh` → `clone_mcp_rag_repo`). The GitLab workflow intent is clear:
users create **feature branches** in their scratch clone, push them upstream
to the `NWS/Operations/NCEP/EMC/EIB/eib-mcp-rag-server` GitLab repo, and
merge to `develop` after review.

The unsolved question: **How does a user on a feature branch see the effect
of their changes in the RAG/Graph knowledge base — specifically in the EE2
semantic embedding system — without disturbing the shared `gw` tenant data
that all other users (and the Docker MCP Gateway) are reading from?**

Three change-classes need different isolation strategies:

| Class | What the user changes | Requires new vectors/nodes? | Isolation strategy |
|-------|----------------------|-----------------------------|--------------------|
| A | Tool/query code (behavior) | No | Read-only shared DB access from user's stdio server |
| B | Ingestion pipeline, chunking, EE2 embedding rules | **Yes** | **Personal tenant** (label_prefix + index_prefix on shared DBs) |
| C | Adapter code, embedding model, graph schema | **Yes (shape changes)** | Per-user Docker Compose stack (dedicated DBs) |

The **EE2 semantic embedding iteration** scenario you called out is Class B:
the user modifies how EE2 standards are chunked, embedded, or scored, then
re-ingests into a personal-prefixed collection, and compares their
`search_ee2_standards --tenant personal-<user>` results against the shared
baseline `gw` tenant. The 34-document EE2 corpus re-embeds in seconds.

## 2. Scope

### 2.1 In Scope — Wave 1: Read-Only Guard (Class A enabler, ~1 day)

- Add `MCP_READ_ONLY=true` env var support to the ChromaDB and Neo4j
  adapters in `mcp_server_python/src/data/`.
- When set, all write operations (`collection.add/update/delete`,
  `graph.query("… CREATE|MERGE|DELETE …")`) raise `ReadOnlyError`.
- Document usage: user runs `MCP_READ_ONLY=true python -m
  mcp_server_python.main --scenario full` from their scratch clone, pointed
  at the shared DBs (`bolt://localhost:7687`, `http://localhost:8080`).
- Update each user's `.vscode/mcp.json` template (in the provisioning
  system) to include a `eib-mcp-rag-full-local` entry with `MCP_READ_ONLY`.

### 2.2 In Scope — Wave 2: Personal Tenants (Class B enabler, ~2-3 days)

- Extend `tenants.yaml` schema with `lifecycle: personal` and `owner: str`.
- Convention: `tenant_id: personal-<username>`, `label_prefix: P_<USER>_`,
  `index_prefix: p_<user>_`.
- Add a CLI command: `python -m mcp_server_python.scripts.create_personal_tenant <user>`.
  Auto-generates the tenant entry, creates the Neo4j constraint indexes for
  the new label prefix, and validates ChromaDB accessibility.
- All existing ingestion scripts already respect `--tenant` — verify this for
  `ingest_ee2_standards.py`, `ingest_code_v8.py`, `ingest_shell_graph_v8.py`.
- Implement `--diff-tenant` flag on `search_ee2_standards` and
  `search_documentation` tools: runs the same query against two tenants
  side-by-side and returns a comparison table (shared baseline vs personal).
- User workflow:
  1. Create feature branch: `cd ~/eib-mcp-rag-server && git checkout -b feature/ee2-chunk-reform`
  2. Edit chunking logic in `scripts/ingest_ee2_standards.py`
  3. Re-ingest into personal tenant:
     `python scripts/ingest_ee2_standards.py --tenant personal-anna`
  4. Compare: `search_ee2_standards --query "header comment block" --tenant personal-anna`
     vs `--tenant gw` (or `--diff-tenant gw,personal-anna`)
  5. Satisfied → push branch → MR → merge to `develop`
  6. CI re-ingests into `gw` (Wave 5) — user's personal tenant can be pruned.

### 2.3 In Scope — Wave 3: Personal-Tenant Cleanup Timer (~half day)

- systemd `mcp-personal-tenant-cleanup.timer` (weekly at 03:00 UTC Sunday).
- Lists all `personal-*` tenants; if no ingestion activity in 30 days,
  deletes their Neo4j labels and ChromaDB collections.
- Sends a structured log event; future n8n alert workflow can notify the
  user before deletion.

### 2.4 In Scope — Wave 4: Per-User Compose Stack (Class C enabler, ~1 week)

- `docker-compose.user.yaml` template with:
  - Port offsets: `8080 + (uid % 100)` for ChromaDB,
    `7687 + (uid % 100)` / `7474 + (uid % 100)` for Neo4j.
  - Data dirs: `/mcp_rag_eib/data/personal/<user>/chromadb`,
    `/mcp_rag_eib/data/personal/<user>/neo4j`.
  - `USER=<user> docker compose -f docker-compose.user.yaml up -d`.
- Seed script: copies a reduced corpus (EE2 standards + community summaries
  only, ~2 K docs) from the shared store into the user's private DBs for a
  fast initial working set.
- `.vscode/mcp.json` template updated to add a `eib-mcp-rag-personal`
  server entry with the user's port offsets.
- Resource budget: ~5 G disk + 1 GB RAM per active user on reduced corpus;
  ~10 G + 2 GB for a full clone. Only realistic for 3-5 concurrent Class C
  users.

### 2.5 Deferred — Wave 5: CI-Driven Re-Ingest on Merge

- GitLab CI `.gitlab-ci.yml` job triggered on merge to `develop`:
  runs the shared ingestion pipeline into the `gw` tenant, updating the
  baseline everyone reads from.
- Out of scope for this phase — requires GitLab Runner on this host or a
  remote executor. Documented as a follow-up.

### 2.6 Out of Scope

- AWS AgentCore per-user isolation (handled by microVM + separate Neptune
  tenant namespacing on the AWS side).
- Per-user SDD session state (Phase 33 — separate, orthogonal).
- n8n workflow-level isolation (n8n is single-instance, shared).
- Ownership-hardening of the existing per-user clones (that is the
  in-progress `user-provisioning-drift-remediation` spec, Task 8
  follow-ups).

## 3. Success Criteria

### Wave 1
1. A user running `MCP_READ_ONLY=true python -m mcp_server_python.main`
   from their scratch clone can query all 53 tools against the shared DBs.
2. Any write operation (ingestion, `mark_as_modified`, `checkpoint_state`)
   raises `ReadOnlyError` with a clear message.
3. No performance degradation for read paths (< 5 ms overhead per query).

### Wave 2
4. `create_personal_tenant anna` appends a valid entry to `tenants.yaml`
   and the server recognizes it on next startup.
5. `ingest_ee2_standards.py --tenant personal-anna` writes documents to
   `p_anna_ee2-standards-v5-0-0-enhanced` in ChromaDB and
   `P_ANNA_EE2Standard` labels in Neo4j — without touching `gw` data.
6. `search_ee2_standards --tenant personal-anna` returns results only from
   the personal collection.
7. `search_ee2_standards --diff-tenant gw,personal-anna --query "…"`
   returns a two-column comparison with rank, score, and snippet for each.
8. The shared `gw` tenant node/document counts are unchanged after personal
   ingestion (regression assertion in the ingestion script).

### Wave 3
9. After 30 days of inactivity, `mcp-personal-tenant-cleanup.timer`
   removes all `personal-anna_*` collections and `P_ANNA_*` Neo4j nodes.
10. A structured log event is emitted before deletion.

### Wave 4
11. `USER=anton docker compose -f docker-compose.user.yaml up -d` starts
    isolated ChromaDB + Neo4j on unique ports.
12. The user's `.vscode/mcp.json` `eib-mcp-rag-personal` server entry
    connects to the user-specific ports and passes all 53-tool health checks.
13. The seed script populates EE2 + community summaries in < 60 seconds.

## 4. EE2 Semantic Embedding System — Detailed Walkthrough

The EE2 corpus consists of 34 standards documents in
`ee2-standards-v5-0-0-enhanced` (ChromaDB collection). Each document is
embedded using the local `sentence-transformers/all-mpnet-base-v2` model
(768-dim, `mpnet768` profile). Relevant tools:

- `search_ee2_standards(query, category?, max_results=8)` — semantic
  vector search against the EE2 collection, anchored with "EE2 compliance".
- `analyze_ee2_compliance(content, analysis_type)` — pattern-matched
  analysis against retrieved standards.
- `generate_compliance_report(file_path)` — full report combining vector
  retrieval + graph context.
- `scan_repository_compliance(path, scope)` — batch scanner.

**User iteration loop** (Wave 2):

```
1. User edits chunking (e.g. splits standards by subsection instead of whole-doc)
2. Re-embed: python scripts/ingest_ee2_standards.py --tenant personal-anna
   → writes to p_anna_ee2-standards-v5-0-0-enhanced (new 768-dim embeddings)
3. Test query: search_ee2_standards --query "module header comment format"
      --tenant personal-anna
   → sees improved recall from finer chunks
4. Compare baseline: search_ee2_standards --diff-tenant gw,personal-anna
      --query "module header comment format"
   → side-by-side: gw returns 3 relevant / 8 total; personal-anna returns 6 / 8
5. Satisfied → commit, push, MR to develop
6. After merge: CI re-ingests into gw with the new chunking → all users benefit
```

This works because:
- `resolve_collection_name("ee2-standards-v5-0-0-enhanced", tenant="personal-anna")`
  → `p_anna_ee2-standards-v5-0-0-enhanced` (Phase 68 machinery, already tenant-aware).
- Neo4j label isolation: any EE2-related graph nodes (if added in future
  phases) get `P_ANNA_` prefix.
- The mpnet768 model is deterministic and loaded from the host's HuggingFace
  cache (read-only mount) — so embedding results are reproducible between the
  user's personal ingest and the eventual shared ingest.

## 5. Open Questions

1. **Should personal tenants be declared in `tenants.yaml` (requires server
   restart to pick up) or in a separate `personal_tenants.yaml` that
   hot-reloads?** First cut: append to `tenants.yaml` and restart the user's
   stdio server (the gateway serves the shared tenants and doesn't need the
   personal ones).

2. **Disk quota per personal tenant?** The EE2 corpus is 34 docs × ~1 KB
   each (trivial). A full code ingest could be 60 K docs × 3 KB = ~180 MB
   of vectors. Proposal: 500 MB soft limit per personal tenant, operator
   override via `PERSONAL_TENANT_QUOTA_MB`.

3. **Should `--diff-tenant` be a tool parameter or a separate meta-tool?**
   Proposal: parameter on existing tools to minimize tool-surface inflation.

4. **How to handle the case where a user's branch diverges significantly
   from `develop` and their personal-tenant data goes stale?** Proposal:
   the ingestion script records the branch commit SHA in collection metadata;
   `check_knowledge_integrity` surfaces a WARN when the personal tenant's
   SHA diverges > 100 commits from `develop`.

5. **GitLab remote inconsistency**: Anna, Brian, and Georgios's clones point
   at `gitlab-licensed` while Terry's points at `gitlab-community`. Both
   resolve to the same repo (community is a mirror). Should provisioning
   normalize to one? The `gitlab-licensed` URL requires VPN; `community`
   doesn't. Users off-VPN would fail to push. Resolution: normalize to
   `gitlab-community` for all new clones; retrofit existing ones via the
   drift-remediation spec.

## 6. Risks

- **Personal tenants accumulate if cleanup timer is delayed.** Mitigation:
  the EE2 corpus is tiny (34 docs); even 10 personal tenants add < 10 MB.
  Full code-context personal tenants are the risk; the quota limit (OQ2) caps
  this.
- **`MCP_READ_ONLY` bypass via raw Cypher/ChromaDB API calls from
  scripts.** Mitigation: the guard is on the adapter layer, not the wire;
  scripts that import `neo4j.Session` directly bypass it. Document that
  personal-tenant ingestion scripts must use the adapter, not raw drivers.
  Enforcement: a lint rule checking for raw `session.run("CREATE…")` outside
  of `src/data/`.
- **Port-offset collisions in Wave 4** if `uid % 100` aliases. Mitigation:
  on this host there are 6 users; collision is not realistic. Add a
  registration file at `/mcp_rag_eib/data/personal/.port_registry.json` for
  deterministic conflict detection.
- **Git merge of `tenants.yaml` conflicts** when multiple personal tenants
  are added concurrently. Mitigation: personal tenants are appended at the
  end in a `# --- personal tenants (auto-generated) ---` section; merges
  are trivial appends.

## 7. Architecture Diagram

```
┌───────────────────────────────────────────────────────────────────┐
│  Shared Infrastructure (single-instance, runs as today)           │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐   │
│  │ chromadb-    │  │ neo4j-devops │  │ mcp-gateway.service    │   │
│  │ devops :8080 │  │ :7474/:7687  │  │ :18888 (shared tools)  │   │
│  │              │  │              │  │ tenant: gw (default)   │   │
│  │ Collections: │  │ Labels:      │  │                        │   │
│  │ gw_*         │  │ Function     │  └────────────────────────┘   │
│  │ p_anna_*     │  │ P_ANNA_*     │                               │
│  │ p_anton_*    │  │ P_ANTON_*    │                               │
│  └──────────────┘  └──────────────┘                               │
└───────────────────────────────────────────────────────────────────┘
         ▲ read+write (personal)      ▲ read-only (shared gw)
         │                            │
┌────────┼────────────────────────────┼──────────────────────────────┐
│  User: Anna.Smoot                   │                              │
│  Scratch: /mcp_rag_eib/SCRATCH_SPACE/Anna.Smoot/eib-mcp-rag-server │
│  Branch: feature/ee2-chunk-reform   │                              │
│                                     │                              │
│  ┌──────────────────────────────────┴───────────────────────┐      │
│  │ MCP stdio server (from scratch clone)                    │      │
│  │ MCP_READ_ONLY=true (for gw queries)                      │      │
│  │ tenant=personal-anna (for personal ingestion/queries)    │      │
│  │ Points at: bolt://localhost:7687, http://localhost:8080  │      │
│  └──────────────────────────────────────────────────────────┘      │
│                                                                    │
│  VS Code Remote Tunnel → .vscode/mcp.json (eib-mcp-rag-full-local) │
└────────────────────────────────────────────────────────────────────┘
```

## 8. References

- Gap Analysis wiki: `supported_repos/global-workflow.wiki/Docker-MCP-Gateway-COTS-Gap-Analysis-2026-07-20.md`
- User provisioning specs:
  - `.kiro/specs/user-provisioning-ownership-hardening/`
  - `.kiro/specs/user-provisioning-drift-remediation/`
- Multi-user gateway architecture: `mcp_architecture/docs/DOCKER_MCP_GATEWAY_MULTIUSER_ARCHITECTURE.md`
- Phase 33 (per-user SDD state): `sdd_framework/workflows/phase33_per_user_sdd_state_database.md`
- Phase 4D (multi-tenant SDD workspaces): `sdd_framework/workflows/phase4d_multi_tenant_sdd_workspaces.md`
- Phase 23 (static-mode multi-user gateway): `sdd_framework/workflows/phase23_static_mode_multiuser_gateway_executable.md`
- Tenant catalog: `mcp_server_python/src/config/tenants.yaml`
- EE2 ingestion: `mcp_server_node/scripts/ingest_ee2_standards.py` (if exists) or EE2ComplianceTools port in Phase B8
- Dynamic MCP Self-Provisioning wiki: `supported_repos/global-workflow.wiki/Dynamic_MCP_Server_Self_Provisioning.md`
- CHANGELOG entries: `[8.35.0]` (agentcore-creds-provisioning), `[8.17.0]` (EE2ComplianceTools port)
- `SETUP/provisioning/user_config.sh` SPOT: `SCRATCH_ROOT`, `UPSTREAM_REPO_URL`, `PROVISION_CLONE_EXEMPT_USERS`
