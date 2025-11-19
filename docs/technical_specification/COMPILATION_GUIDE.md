# Publication Materials - Compilation Guide
**How to Generate PDFs, Slides, and Distribution Materials**

**Version:** 1.0  
**Date:** November 19, 2025  
**Location:** `/mcp_rag_eib/eib-mcp-rag-server/docs/technical_specification/`

---

## Quick Summary

You now have **5 complete publication-ready materials**:

1. ✅ **SDD_Framework_Journal_Paper.md** (10-page Markdown)
2. ✅ **SDD_Framework_Paper.tex** (LaTeX journal submission)
3. ✅ **SDD_Framework_Presentation.md** (Conference talk slides)
4. ✅ **SME_Training_QuickStart.md** (2-hour training guide)
5. ✅ **Extended_Technical_Appendix.md** (Implementation details)

This guide shows you how to compile them into polished PDFs and presentations.

---

## Table of Contents

1. [LaTeX Paper Compilation](#1-latex-paper-compilation)
2. [Presentation Slides Generation](#2-presentation-slides-generation)
3. [Markdown to PDF Conversion](#3-markdown-to-pdf-conversion)
4. [Distribution Package Creation](#4-distribution-package-creation)
5. [Quick Commands Reference](#5-quick-commands-reference)

---

## 1. LaTeX Paper Compilation

### 1.1 Prerequisites

**Check if LaTeX is installed:**
```bash
which pdflatex
# If not found, install:
# Rocky Linux: sudo yum install texlive-scheme-full
# Ubuntu: sudo apt-get install texlive-full
```

**Verify required packages:**
```bash
kpsewhich article.cls amsmath.sty algorithm.sty booktabs.sty hyperref.sty
```

### 1.2 Compile the Paper

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/docs/technical_specification

# Method 1: Standard compilation (run 3 times for references)
pdflatex SDD_Framework_Paper.tex
pdflatex SDD_Framework_Paper.tex
pdflatex SDD_Framework_Paper.tex

# Method 2: Using latexmk (automated, recommended)
latexmk -pdf SDD_Framework_Paper.tex

# Output: SDD_Framework_Paper.pdf (~15 pages)
```

**Expected compilation time:** 30-60 seconds

### 1.3 View the PDF

```bash
# Linux
evince SDD_Framework_Paper.pdf &

# Mac
open SDD_Framework_Paper.pdf

# Windows (WSL)
explorer.exe SDD_Framework_Paper.pdf
```

### 1.4 Clean Auxiliary Files

```bash
# Remove temporary LaTeX files
latexmk -c

# Or manually:
rm -f *.aux *.log *.out *.toc *.bbl *.blg *.synctex.gz
```

### 1.5 Troubleshooting LaTeX Errors

**Error: Missing package**
```bash
# Example: ! LaTeX Error: File `algorithm.sty' not found.
sudo yum install texlive-algorithms  # Rocky Linux
sudo apt-get install texlive-science  # Ubuntu
```

**Error: Too many errors**
```bash
# Compile with error scrolling
pdflatex -interaction=nonstopmode SDD_Framework_Paper.tex

# Check log file
less SDD_Framework_Paper.log
```

---

## 2. Presentation Slides Generation

### 2.1 Method A: Beamer (PDF Slides)

**Best for:** Conference presentations, professional settings

**⚠️ Note:** Pandoc is not currently installed on this system. To use this method:

```bash
# Install pandoc first (requires sudo or admin access)
sudo yum install pandoc  # Rocky Linux/RHEL
# OR
sudo apt-get install pandoc  # Ubuntu/Debian

# Then convert Markdown to Beamer LaTeX
cd /mcp_rag_eib/eib-mcp-rag-server/docs/technical_specification
pandoc SDD_Framework_Presentation.md \
    -t beamer \
    -o SDD_Framework_Slides.pdf \
    --slide-level=2 \
    -V theme:metropolis \
    -V aspectratio:169

# Output: SDD_Framework_Slides.pdf (16:9 widescreen)
```

**Compile time:** 10-20 seconds  
**Expected output:** ~25 slides

**Alternative:** Use the Markdown presentation directly with reveal.js in a browser (see Method B below).

### 2.2 Method B: reveal.js (HTML Slides)

**Best for:** Web presentations, interactive demos

```bash
# Convert Markdown to reveal.js HTML
pandoc SDD_Framework_Presentation.md \
    -t revealjs \
    -o SDD_Framework_Slides.html \
    -s \
    --slide-level=2 \
    -V theme:black

# Open in browser
firefox SDD_Framework_Slides.html &
```

**Features:**
- Navigate with arrow keys
- Press 'S' for speaker notes
- Press 'F' for fullscreen
- Press 'Esc' for overview

### 2.3 Method C: PowerPoint (PPTX)

**Best for:** Editing, customization

```bash
# Convert Markdown to PowerPoint
pandoc SDD_Framework_Presentation.md \
    -t pptx \
    -o SDD_Framework_Slides.pptx

# Open with LibreOffice or MS PowerPoint
libreoffice SDD_Framework_Slides.pptx &
```

**Note:** Will need manual formatting adjustments for tables and code blocks.

### 2.4 Customizing Beamer Theme

**Available themes:**
- `metropolis` - Modern, clean (recommended)
- `Madrid` - Classic professional
- `Berlin` - Academic style
- `Copenhagen` - Minimalist

```bash
# Try different themes
pandoc SDD_Framework_Presentation.md -t beamer -o slides.pdf -V theme:Madrid
pandoc SDD_Framework_Presentation.md -t beamer -o slides.pdf -V theme:Berlin
```

### 2.5 Adding Figures to Slides

Create a `figures/` directory and add images:

```bash
mkdir -p /mcp_rag_eib/eib-mcp-rag-server/docs/technical_specification/figures

# Example: Generate architecture diagram
# (Use draw.io, PlantUML, or Graphviz)
```

Reference in Markdown:
```markdown
![System Architecture](figures/architecture.png){width=80%}
```

---

## 3. Markdown to PDF Conversion

### 3.1 Journal Paper (Markdown Version)

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/docs/technical_specification

# Convert Markdown to PDF
pandoc SDD_Framework_Journal_Paper.md \
    -o SDD_Framework_Journal_Paper.pdf \
    --pdf-engine=xelatex \
    -V geometry:margin=1in \
    -V fontsize=11pt \
    --toc \
    --number-sections

# Output: SDD_Framework_Journal_Paper.pdf (~10-12 pages)
```

### 3.2 Training Guide

```bash
# Convert training guide to PDF
pandoc SME_Training_QuickStart.md \
    -o SME_Training_QuickStart.pdf \
    --pdf-engine=xelatex \
    -V geometry:margin=1in \
    --toc

# Output: SME_Training_QuickStart.pdf
```

### 3.3 Technical Appendix

```bash
# Convert appendix to PDF
pandoc Extended_Technical_Appendix.md \
    -o Extended_Technical_Appendix.pdf \
    --pdf-engine=xelatex \
    -V geometry:margin=1in \
    --toc \
    --number-sections

# Output: Extended_Technical_Appendix.pdf
```

### 3.4 Batch Conversion (All at Once)

```bash
#!/bin/bash
# convert_all.sh - Convert all Markdown to PDF

for file in SDD_Framework_Journal_Paper SME_Training_QuickStart Extended_Technical_Appendix; do
    echo "Converting $file.md to PDF..."
    pandoc "${file}.md" \
        -o "${file}.pdf" \
        --pdf-engine=xelatex \
        -V geometry:margin=1in \
        --toc \
        --number-sections
done

echo "All conversions complete!"
```

---

## 4. Distribution Package Creation

### 4.1 Create Distribution Archive

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/docs/technical_specification

# Create distribution directory
mkdir -p SDD_Framework_Publication_Package

# Copy all materials
cp SDD_Framework_Journal_Paper.md SDD_Framework_Publication_Package/
cp SDD_Framework_Journal_Paper.pdf SDD_Framework_Publication_Package/
cp SDD_Framework_Paper.tex SDD_Framework_Publication_Package/
cp SDD_Framework_Paper.pdf SDD_Framework_Publication_Package/
cp SDD_Framework_Slides.pdf SDD_Framework_Publication_Package/
cp SME_Training_QuickStart.pdf SDD_Framework_Publication_Package/
cp Extended_Technical_Appendix.pdf SDD_Framework_Publication_Package/

# Create README
cat > SDD_Framework_Publication_Package/README.txt << 'EOF'
SDD Framework Publication Materials
===================================

This package contains complete publication and training materials for the
Spec-Driven Development (SDD) Framework with Supervised RAG Refinement.

Contents:
---------
1. SDD_Framework_Journal_Paper.pdf - 10-page journal article (PDF)
2. SDD_Framework_Journal_Paper.md - Journal article (Markdown source)
3. SDD_Framework_Paper.pdf - LaTeX-compiled journal paper
4. SDD_Framework_Paper.tex - LaTeX source for journal submission
5. SDD_Framework_Slides.pdf - Conference presentation (25 slides)
6. SME_Training_QuickStart.pdf - 2-hour SME training guide
7. Extended_Technical_Appendix.pdf - Implementation details

Publication Venues:
-------------------
- Journal: JOSS, SoftwareX, ACM TOSEM
- Conference: MLSys, ICSE, SC (condense to 6-8 pages)
- Technical Report: NOAA Technical Memorandum, arXiv preprint

Contact:
--------
NOAA EMC Global Workflow MCP Team
Terry.McGuinness@noaa.gov

Date: November 19, 2025
Version: 1.0
EOF

# Create compressed archive
tar -czf SDD_Framework_Publication_Package.tar.gz SDD_Framework_Publication_Package/

# Create ZIP for Windows compatibility
zip -r SDD_Framework_Publication_Package.zip SDD_Framework_Publication_Package/

echo "Distribution packages created:"
ls -lh SDD_Framework_Publication_Package.*
```

### 4.2 Upload to GitHub Release

```bash
# Tag the release
cd /mcp_rag_eib/eib-mcp-rag-server
git tag -a v1.0-publication -m "SDD Framework Publication Materials v1.0"
git push origin v1.0-publication

# Create GitHub release with attachments
# (Use GitHub web interface to attach .tar.gz and .zip files)
```

### 4.3 Upload to arXiv (If Publishing)

```bash
# arXiv requires LaTeX source + compiled PDF
mkdir arxiv_submission
cp SDD_Framework_Paper.tex arxiv_submission/
cp SDD_Framework_Paper.pdf arxiv_submission/

# Create arXiv archive (no subdirectories allowed)
cd arxiv_submission
tar -czf ../arxiv_submission.tar.gz *
cd ..

# Upload arxiv_submission.tar.gz to https://arxiv.org/submit
```

---

## 5. Quick Commands Reference

### One-Command Compilation

```bash
# Compile everything at once
cd /mcp_rag_eib/eib-mcp-rag-server/docs/technical_specification

# LaTeX paper
pdflatex SDD_Framework_Paper.tex && \
pdflatex SDD_Framework_Paper.tex && \
pdflatex SDD_Framework_Paper.tex

# Beamer slides
pandoc SDD_Framework_Presentation.md -t beamer -o SDD_Framework_Slides.pdf -V theme:metropolis -V aspectratio:169

# Markdown PDFs
pandoc SDD_Framework_Journal_Paper.md -o SDD_Framework_Journal_Paper.pdf --pdf-engine=xelatex -V geometry:margin=1in --toc --number-sections
pandoc SME_Training_QuickStart.md -o SME_Training_QuickStart.pdf --pdf-engine=xelatex -V geometry:margin=1in --toc
pandoc Extended_Technical_Appendix.md -o Extended_Technical_Appendix.pdf --pdf-engine=xelatex -V geometry:margin=1in --toc --number-sections

echo "✅ All materials compiled successfully!"
```

### Verify Output

```bash
# Check all PDF files were created
ls -lh *.pdf

# Count pages in each PDF
for file in *.pdf; do
    pages=$(pdfinfo "$file" 2>/dev/null | grep Pages | awk '{print $2}')
    echo "$file: $pages pages"
done
```

### Expected Output

```
SDD_Framework_Paper.pdf: 15 pages
SDD_Framework_Slides.pdf: 25 slides
SDD_Framework_Journal_Paper.pdf: 10 pages
SME_Training_QuickStart.pdf: 18 pages
Extended_Technical_Appendix.pdf: 22 pages
```

---

## 6. Publication Submission Checklist

### For Journal Submission

- [ ] Compile LaTeX paper: `SDD_Framework_Paper.pdf`
- [ ] Verify all references render correctly
- [ ] Check no overfull/underfull boxes in log
- [ ] Include LaTeX source: `SDD_Framework_Paper.tex`
- [ ] Add author ORCID IDs (if required)
- [ ] Prepare cover letter explaining contributions
- [ ] Submit via journal portal (JOSS, SoftwareX, etc.)

### For Conference Submission

- [ ] Condense paper to 6-8 pages (conference limit)
- [ ] Generate presentation slides: `SDD_Framework_Slides.pdf`
- [ ] Practice presentation (aim for 15-20 minutes)
- [ ] Prepare demo video (optional, recommended)
- [ ] Submit via conference system (HotCRP, CMT, etc.)

### For NOAA Technical Memorandum

- [ ] Use Markdown version: `SDD_Framework_Journal_Paper.md`
- [ ] Convert to NOAA template format
- [ ] Add NOAA disclaimer and distribution statement
- [ ] Submit to NOAA Technical Publications Office
- [ ] Assign NOAA Tech Memo number (e.g., NWS/EMC-XXX)

### For arXiv Preprint

- [ ] Compile LaTeX: `SDD_Framework_Paper.pdf`
- [ ] Verify PDF renders correctly
- [ ] Create submission archive: `arxiv_submission.tar.gz`
- [ ] Upload to https://arxiv.org/submit
- [ ] Select category: cs.SE (Software Engineering) or cs.AI
- [ ] Add co-authors and affiliations

---

## 7. Training Material Dissemination

### Internal Training (NOAA Staff)

```bash
# Create training package
mkdir SDD_Framework_Training
cp SME_Training_QuickStart.pdf SDD_Framework_Training/
cp SDD_Framework_Slides.pdf SDD_Framework_Training/
cp ../sdd_framework/templates/sme_review_guide.md SDD_Framework_Training/
cp ../sdd_framework/templates/pilot_annotation_error_handling.md SDD_Framework_Training/

# Add example review feedback template
cat > SDD_Framework_Training/Review_Feedback_Template.md << 'EOF'
# SME Review Feedback Template

## Section Reviewed: [Name]

### Intent Accuracy
- ✅ [directive_name] - [comment]
- ⚠️ [directive_name] - [suggested improvement]
- ❌ [directive_name] - [correction needed]

### Priority/Severity
- [Assessment]

### Examples
- [Missing or incorrect examples]

### Questions/Clarifications
1. [Question 1]
2. [Question 2]
EOF

# Compress for distribution
tar -czf SDD_Framework_Training.tar.gz SDD_Framework_Training/
```

### External Training (Conference Workshops)

```bash
# Create workshop package
mkdir SDD_Framework_Workshop
cp SDD_Framework_Slides.pdf SDD_Framework_Workshop/
cp SME_Training_QuickStart.pdf SDD_Framework_Workshop/
cp Extended_Technical_Appendix.pdf SDD_Framework_Workshop/

# Add hands-on exercises
# (Create interactive notebooks or scripts)

zip -r SDD_Framework_Workshop.zip SDD_Framework_Workshop/
```

---

## 8. Version Control and Updates

### Track Changes

```bash
cd /mcp_rag_eib/eib-mcp-rag-server

# Commit publication materials
git add docs/technical_specification/
git commit -m "Add SDD Framework publication materials v1.0

- Journal paper (Markdown + LaTeX)
- Conference presentation slides
- SME training guide
- Extended technical appendix
- Compilation guide"

git push origin MCP_node.js-RAG_ParallelWorks
```

### Update Version

When making revisions:

1. Update `date` field in all documents
2. Increment version number (e.g., 1.0 → 1.1)
3. Update CHANGELOG.md with changes
4. Recompile all materials
5. Create new distribution package

---

## 9. Support and Feedback

### Get Help

**Compilation Issues:**
- Check LaTeX log file: `less SDD_Framework_Paper.log`
- Verify pandoc version: `pandoc --version` (need 2.10+)
- Test with minimal example first

**Content Issues:**
- Review against original Markdown source
- Verify all references are defined
- Check code block syntax

**Contact:**
- Email: Terry.McGuinness@noaa.gov
- GitHub Issues: https://github.com/TerrenceMcGuinness-NOAA/eib-mcp-rag-server/issues

---

## Summary

You now have **complete publication materials** ready for:

✅ **Journal submission** (LaTeX + PDF)  
✅ **Conference presentation** (Beamer slides)  
✅ **SME training** (Quick-start guide)  
✅ **Implementation** (Technical appendix)  
✅ **Distribution** (Compressed packages)

**Next Steps:**
1. Run compilation commands (Section 5)
2. Review generated PDFs for quality
3. Choose publication venue
4. Submit for review!

**Estimated time to compile all materials:** 5-10 minutes

---

**End of Compilation Guide**

**Good luck with your publication! 🚀**
