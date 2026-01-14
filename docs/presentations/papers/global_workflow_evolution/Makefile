# Makefile for building LaTeX papers
# Requires: pdflatex, bibtex (optional for separate .bib files)

PAPER = global_workflow_evolution_and_future_directions
LATEX = pdflatex
BIBTEX = bibtex

# Default target
all: $(PAPER).pdf

# Build PDF (run twice for references)
$(PAPER).pdf: $(PAPER).tex
	$(LATEX) $(PAPER).tex
	$(LATEX) $(PAPER).tex
	@echo "Build complete: $(PAPER).pdf"

# Full build with bibliography (if using .bib file)
full: $(PAPER).tex
	$(LATEX) $(PAPER).tex
	$(BIBTEX) $(PAPER) || true
	$(LATEX) $(PAPER).tex
	$(LATEX) $(PAPER).tex
	@echo "Full build complete: $(PAPER).pdf"

# Clean auxiliary files
clean:
	rm -f *.aux *.log *.out *.toc *.lof *.lot *.bbl *.blg *.nav *.snm *.vrb

# Clean everything including PDF
distclean: clean
	rm -f $(PAPER).pdf

# View the PDF (Linux)
view: $(PAPER).pdf
	xdg-open $(PAPER).pdf 2>/dev/null || evince $(PAPER).pdf 2>/dev/null || echo "No PDF viewer found"

# Quick build (single pass, faster but references may be wrong)
quick:
	$(LATEX) $(PAPER).tex

.PHONY: all full clean distclean view quick
