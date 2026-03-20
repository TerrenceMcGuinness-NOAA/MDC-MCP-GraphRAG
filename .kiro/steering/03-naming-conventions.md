---
inclusion: auto
---

# Naming Conventions — EIB → MDC Transition

## Institutional Rename

EIB (Environmental Information Branch) has been renamed to MDC (Modeling Development Center)
as part of an institutional reorganization. This affects naming throughout the project.

## Current State of Names

| Context | Current Name | Target Name | Status |
|---------|-------------|-------------|--------|
| MCP server key (Kiro config) | `eib-mcp-gateway` | `mdc-mcp-rag` | Keep as-is (points to legacy) |
| MCP auth token | `eib-mcp-gateway-token-2025` | `mdc-mcp-rag-token-2025` | Keep as-is (legacy auth) |
| Repository name | `eib-mcp-rag-server` | TBD (repo rename pending) | No change yet |
| Docker image names | `eib-mcp-rag:latest` | N/A on AWS | Legacy only |
| Persistent mount | `/mcp_rag_eib` | `/mdc-mcp-rag` | Done on AWS instance |
| Docker registry path | `.../emc/eib/eib-mcp-rag-server/...` | TBD | Legacy only |
| Container names | `chromadb-*`, `neo4j-*`, `mcp-server-*` | AWS service names | Porting in progress |

## Rules for New Code

- New AWS infrastructure code should use `mdc-mcp-rag` naming
- Do not rename legacy references in existing Docker/provisioning scripts — they are reference material
- SDD phase specs can use either name but should note the transition
- The `PERSISTENT_ROOT` env var default changes from `/mcp_rag_eib` to `/mdc-mcp-rag` on AWS
- When the AWS system is self-hosting, the MCP config will switch from `eib-mcp-gateway` to `mdc-mcp-rag`

## Domain Glossary

| Term | Meaning |
|------|---------|
| EIB | Environmental Information Branch (legacy name) |
| MDC | Modeling Development Center (current name) |
| EE2 | EMC Environment 2.0 — NCO production coding standards |
| GFS/GEFS | Global Forecast System / Ensemble version |
| HPC | Hera, WCOSS2, Orion, Hercules, Gaea compute platforms |
| GGSR | Graph-Guided Semantic Retrieval (hybrid Neo4j+ChromaDB) |
| SDD | Spec-Driven Development methodology |
