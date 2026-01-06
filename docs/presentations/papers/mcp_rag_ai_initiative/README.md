# MCP/RAG AI Initiative — EIB Technical Documentation

**NOAA Environmental Modeling Center — Environmental Information Branch**

This directory contains the SPOT (Single Point of Truth) documentation for the AI Software Development Initiative supporting NOAA's flagship Global Forecast System (GFS).

## Document Inventory

| Document | Format | Pages | Status | Description |
|----------|--------|-------|--------|-------------|
| `MCP_RAG_System_Architecture.md` | Markdown | — | **SPOT** | Authoritative technical reference |
| `MCP_RAG_System_Architecture.tex` | LaTeX | 16 | ✅ Complete | Professional publication source |
| `MCP_RAG_System_Architecture.pdf` | PDF | 16 | ✅ Complete | Distribution-ready version (531KB) |

## Quick Links

- **Main Architecture Document**: [MCP_RAG_System_Architecture.md](MCP_RAG_System_Architecture.md)
- **Repository Root**: [eib-mcp-rag-server](https://vlab.noaa.gov/gitlab-licensed/NWS/Operations/NCEP/EMC/EIB/eib-mcp-rag-server)
- **Copilot Instructions**: [.github/copilot-instructions.md](../../../../.github/copilot-instructions.md)

## Scope

This document covers:

1. **Mission and Scope** — Problem statement and design principles
2. **System Architecture** — MCP Server, ChromaDB, Neo4j integration
3. **Knowledge Base Design** — Collections, graph schema, storage
4. **Hybrid Retrieval Algorithm** — Scoring function and query type detection
5. **Semantic Annotation System** — MCP directives for EE2 compliance
6. **MCP Tool Inventory** — 38 tools across 9 modules
7. **Configuration Reference** — Environment variables, VS Code, Docker
8. **Deployment Procedures** — Fresh install, gateway, updates
9. **Performance Specifications** — Response times, resource requirements
10. **Troubleshooting Guide** — Common issues and solutions
11. **Reproducibility Checklist** — Full system reproduction steps

## Related Documentation

| Topic | Location |
|-------|----------|
| SDD Framework (Workflow Orchestration) | `../sdd_framework/` |
| Docker MCP Gateway | `../docker_mcp_gateway/` |
| EE2 Compliance Reports | `../../EE2_compliance_reports/` |
| Semantic Annotations Overview | `../../MCP_SEMANTIC_ANNOTATIONS_OVERVIEW.md` |

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0.0 | January 6, 2026 | Elevated to SPOT; LaTeX/PDF versions with TikZ diagrams |
| 1.0.0 | November 19, 2025 | Initial Extended Technical Appendix |

---

**Contact:** Terry.McGuinness@noaa.gov
