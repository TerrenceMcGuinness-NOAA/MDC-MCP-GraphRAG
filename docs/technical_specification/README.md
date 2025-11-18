# LaTeX Technical Specification - Compilation Guide

## Document Information

**Title:** Graph-Enriched Retrieval-Augmented Generation for Operational Weather Forecasting Code Intelligence

**File:** `docs/technical_specification/main.tex`

**Length:** ~35 pages (estimated when compiled)

**Format:** Professional academic LaTeX document

## Prerequisites

### Required LaTeX Packages

```bash
# On Ubuntu/Debian
sudo apt-get install texlive-full

# On Rocky Linux/RHEL
sudo yum install texlive-scheme-full

# Or minimal installation
sudo yum install texlive-latex texlive-latex-extra texlive-algorithms
```

### Required Packages (included in document)
- `amsmath, amssymb` - Mathematical notation
- `algorithm, algorithmic` - Algorithm pseudocode
- `listings` - Code syntax highlighting
- `hyperref` - PDF hyperlinks and metadata
- `booktabs` - Professional tables
- `graphicx` - Figure support (for future diagrams)
- `fancyhdr` - Custom headers/footers

## Compilation

### Option 1: Standard pdflatex (Recommended)

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/docs/technical_specification

# Compile (run 2-3 times for references)
pdflatex main.tex
pdflatex main.tex
pdflatex main.tex

# Output: main.pdf
```

### Option 2: Using latexmk (automated)

```bash
latexmk -pdf main.tex

# Clean auxiliary files
latexmk -c
```

### Option 3: XeLaTeX (for Unicode support)

```bash
xelatex main.tex
xelatex main.tex
```

## Document Structure

### Sections (Page Count Estimates)

1. **Title Page & Abstract** (1 page)
2. **Table of Contents** (1 page)
3. **Introduction** (2-3 pages)
   - Motivation and problem context
   - Approach overview
   - Contributions
4. **System Architecture** (4-5 pages)
   - High-level design
   - Component specifications
   - Data flow diagrams
5. **Graph Enrichment Pipeline** (6-8 pages)
   - Code parsing algorithms
   - Neo4j graph construction
   - Metadata enrichment (THE MAGIC)
   - Performance metrics
6. **Hybrid Search Algorithms** (4-5 pages)
   - Problem formulation
   - Pure vector vs. hybrid approaches
   - Scoring functions
   - Query strategies
7. **Implementation Details** (3-4 pages)
   - Technology stack
   - Deployment architecture
   - MCP tool interface
8. **Performance Evaluation** (4-5 pages)
   - Methodology
   - Empirical results
   - Query type breakdown
9. **Operational Deployment** (2-3 pages)
   - Infrastructure
   - Monitoring
   - Backup/recovery
10. **Lessons Learned** (2-3 pages)
    - Technical insights
    - Operational insights
11. **Future Work** (2 pages)
    - Technical enhancements
    - Evaluation extensions
12. **Conclusion** (1 page)
13. **Bibliography** (1-2 pages)
14. **Appendices** (3-4 pages)
    - Complete algorithm specifications
    - Configuration reference
    - Sample queries and results

**Total:** ~35-40 pages

## Key Features

### Academic Quality Elements

✅ **Formal Structure**
- Abstract with keywords
- Numbered sections and subsections
- Cross-references (Section~\ref{}, Figure~\ref{}, Table~\ref{})
- Professional typography

✅ **Mathematical Rigor**
- Problem formulation with equations
- Algorithm pseudocode (Algorithm 1, 2, 3)
- Performance metrics with statistical notation

✅ **Empirical Validation**
- Performance tables with actual metrics
- Comparative evaluation (baseline vs. hybrid)
- Query type breakdown analysis

✅ **Code Examples**
- Syntax-highlighted listings
- Python, JavaScript, Cypher, SQL examples
- Docker Compose configurations

✅ **Professional Formatting**
- Two-column optional (commented out - can enable)
- IEEE/ACM style tables with booktabs
- Hyperlinked table of contents
- Custom headers/footers

### Content Highlights

**Novel Contributions:**
1. Graph context folding into vector metadata (Section 3.3)
2. Hybrid search algorithms with dynamic weighting (Section 4)
3. Production deployment on operational infrastructure (Section 6)
4. Empirical evaluation showing 3-5x improvement (Section 5)

**Reproducibility:**
- Complete algorithm specifications in appendices
- Configuration files and environment variables
- Sample queries with detailed results
- Technology stack with version numbers

## Customization Options

### Enable Two-Column Format

Uncomment in preamble:
```latex
\documentclass[11pt,letterpaper,twocolumn]{article}
```

### Add Figures

Place figures in `docs/technical_specification/figures/` and reference:
```latex
\begin{figure}[h]
\centering
\includegraphics[width=0.8\linewidth]{figures/architecture.pdf}
\caption{System architecture diagram}
\label{fig:architecture}
\end{figure}
```

### Adjust Page Count

- **Shorter (20-25 pages):** Remove Appendix C, condense Section 7
- **Longer (40-50 pages):** Add case studies, expand evaluation, add more code listings

## Viewing and Distribution

### View PDF

```bash
# Linux with PDF viewer
evince main.pdf

# Mac
open main.pdf

# Windows
start main.pdf
```

### Generate HTML Version

```bash
# Using tex4ht
htlatex main.tex

# Or pandoc
pandoc main.tex -o main.html
```

### Generate Word Document (for collaboration)

```bash
pandoc main.tex -o main.docx --bibliography=references.bib
```

## Metadata

The PDF includes embedded metadata:
- **Author:** NOAA EMC Global Workflow MCP Team
- **Title:** Graph-Enriched RAG for Operational Weather Forecasting Code Intelligence
- **Keywords:** Retrieval-Augmented Generation, Graph Database, Code Intelligence
- **Creation Date:** November 17, 2025

## Publication Venues (Potential)

This technical specification is suitable for:

### Journals
- **JOSS** (Journal of Open Source Software)
- **SoftwareX** (Elsevier)
- **ACM Transactions on Software Engineering and Methodology**

### Conferences (with condensation to 6-8 pages)
- **MLSys** (Machine Learning and Systems)
- **ICLR** (Workshop track)
- **ICSE** (Software Engineering - Tool demo track)
- **SC** (Supercomputing - Tech paper track)

### Technical Reports
- **NOAA Technical Memorandum**
- **arXiv preprint** (cs.SE or cs.AI)

## Next Steps

1. **Compile the document** to verify LaTeX installation
2. **Review content** for technical accuracy
3. **Add figures** (optional) - system architecture diagram, performance plots
4. **Get feedback** from operational staff and domain experts
5. **Revise** based on feedback
6. **Publish** as NOAA technical report or submit to journal

## Contact

For questions about this specification:
- **Author:** NOAA EMC Global Workflow MCP Team
- **Email:** Terry.McGuinness@noaa.gov
- **Repository:** /mcp_rag_eib/eib-mcp-rag-server

---

**Status:** Complete LaTeX technical specification ready for compilation and review
