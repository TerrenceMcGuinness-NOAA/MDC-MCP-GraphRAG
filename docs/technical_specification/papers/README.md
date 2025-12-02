# Technical Papers Collection

This directory contains the technical papers and white papers produced for the MCP-RAG project, organized by topic area.

## Directory Structure

```
papers/
├── sdd_framework/           # SDD Framework papers (Phase 1)
│   ├── main.tex             # Main technical specification (LaTeX)
│   ├── main.pdf             # Compiled PDF (~35 pages)
│   ├── SDD_Framework_Paper.tex      # SDD Framework core paper
│   ├── SDD_Framework_Paper.pdf      # Compiled PDF
│   ├── SDD_Framework_Journal_Paper.md    # Journal version (Markdown)
│   ├── SDD_Framework_Journal_Paper.pdf   # Journal PDF
│   ├── Extended_Technical_Appendix.md    # Technical appendix
│   ├── Extended_Technical_Appendix.pdf   # Appendix PDF
│   ├── SDD_Framework_Presentation.md     # Presentation slides
│   └── SDD_Framework_Slides.pdf          # Slides PDF
│
├── hybrid_annotations/      # Phase 2 Hybrid Semantic Annotations
│   ├── PHASE_2_HYBRID_ARCHITECTURE_SPECIFICATION.md   # Architecture spec
│   ├── SME_Training_QuickStart.md    # SME training guide
│   └── SME_Training_QuickStart.pdf   # Training guide PDF
│
└── fm_assisted_annotations/ # Phase 3 FM-Assisted Annotation Generation
    ├── FM_Assisted_Annotation_Generation.tex   # LaTeX source
    └── FM_Assisted_Annotation_Generation.pdf   # Compiled PDF (9 pages)
```

## Paper Summaries

### 1. SDD Framework Papers (`sdd_framework/`)

**Main Document: Graph-Enriched RAG for Operational Weather Forecasting**

The foundational technical specification describing:
- System architecture for MCP-RAG
- Graph enrichment pipeline (Neo4j + ChromaDB)
- Hybrid search algorithms
- Performance evaluation methodology
- Deployment architecture

**Target Venues:** NOAA Technical Memo, arXiv, JOSS, SoftwareX

---

### 2. Hybrid Semantic Annotations (`hybrid_annotations/`)

**Phase 2 Hybrid Architecture Specification**

Describes the dual-layer annotation system:
- RST directive-based SME corrections
- Phase 1 base directives + Phase 2 SME corrections
- Intent-aware metadata enrichment
- Context discrimination for compliance rules

**SME Training QuickStart**

Practical guide for Subject Matter Experts to:
- Write RST annotation files
- Use custom MCP directives
- Add anti-patterns and correct patterns
- Validate annotations

---

### 3. FM-Assisted Annotation Generation (`fm_assisted_annotations/`)

**Foundation Model-Assisted Annotation Generation** (NEW - December 2025)

Proposes a "Person-to-System Convolution" framework:
- Collects divergence data (AI vs Human decisions)
- Uses foundation models to synthesize RST annotations
- Maintains human oversight through SME review workflow
- Enables scaling from ~10 to 100+ annotations

**Key Innovation:** Shifts SME role from "author" to "reviewer"

---

## Compilation

### LaTeX Documents

```bash
cd papers/<directory>
pdflatex <document>.tex
pdflatex <document>.tex  # Run twice for references
```

### Markdown Documents

```bash
# Convert to PDF with pandoc
pandoc document.md -o document.pdf

# Or use VS Code markdown preview
```

## Version History

| Date | Paper | Version | Notes |
|------|-------|---------|-------|
| Nov 2025 | SDD Framework | 1.0 | Initial technical specification |
| Nov 2025 | Hybrid Annotations | 1.0 | Phase 2 architecture spec |
| Nov 2025 | SME Training | 1.0 | Quick start guide |
| Dec 2025 | FM-Assisted | 1.0 | New paper on scalable annotation |

## Contributing

When adding new papers:

1. Create a new subdirectory under `papers/`
2. Use consistent naming: `Topic_Paper.tex` or `Topic_Paper.md`
3. Include both source and compiled PDF
4. Update this README with paper summary

## Contact

- **Author:** NOAA EMC Global Workflow MCP Team
- **Email:** Terry.McGuinness@noaa.gov
- **Repository:** `/mcp_rag_eib/eib-mcp-rag-server`
