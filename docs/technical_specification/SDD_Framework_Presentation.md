---
title: "Spec-Driven Development with Supervised RAG Refinement"
subtitle: "AI-Assisted Software Development for Operational Weather Forecasting"
author: "NOAA EMC Global Workflow MCP Team"
date: "November 19, 2025"
theme: "metropolis"
aspectratio: 169
---

# The Problem

## Operational Weather Forecasting at Scale

:::::: {.columns}
::: {.column width="50%"}
**NOAA Global Workflow (GFS/GEFS)**
- 500K LOC Fortran (UFS model)
- 300K LOC C/Fortran (GSI/GDAS)
- 2,000+ shell scripts
- 7,000+ Rocoto task dependencies
- 5 HPC platforms

**Challenges**
- Few understand complete system
- Documentation decays faster than code
- 6-12 month onboarding
- Manual compliance auditing
- Silent failures cascade
:::

::: {.column width="50%"}
![System Complexity](figures/complexity.png){width=100%}

**The Core Issue:**
Domain expertise is scarce, documentation complexity exceeds human cognitive capacity
:::
::::::

---

# The SDD Framework Solution

## Three Core Innovations

\begin{columns}[T]
\begin{column}{0.32\textwidth}
\textbf{1. Machine-Readable Specs}

\begin{itemize}
\item YAML/Markdown workflows
\item Parseable by AI agents
\item Systematic validation
\item Automated execution
\end{itemize}

\textcolor{green}{$\checkmark$ Eliminates ambiguity}
\end{column}

\begin{column}{0.32\textwidth}
\textbf{2. Hybrid Graph-RAG}

\begin{itemize}
\item Vector embeddings (semantic)
\item Neo4j graph (structure)
\item 78K+ code relationships
\item Intent-aware search
\end{itemize}

\textcolor{green}{$\checkmark$ 3.8$\times$ retrieval accuracy}
\end{column}

\begin{column}{0.32\textwidth}
\textbf{3. SME Refinement}

\begin{itemize}
\item Semantic annotations
\item Structured review guide
\item Domain expert validation
\item Continuous feedback
\end{itemize}

\textcolor{green}{$\checkmark$ 93\% precision improvement}
\end{column}
\end{columns}

---

# Semantic Annotations: The "Aha!" Moment

## Text Search vs. Intent-Aware Search

:::::: {.columns}
::: {.column width="48%"}
**Traditional Text Search**
```
Query: "How do I check for errors?"

Results: (hundreds of hits)
- "error message format"
- "error handling overview"
- "error codes reference"
- ...
```

**Problems:**
- No priority information
- No operational context
- No relationship info
- 45% precision
:::

::: {.column width="48%"}
**Intent-Aware Search (SDD)**
```rst
.. mcp:intent:: rapid_error_detection
   :description: Enable immediate detection
   :rationale: 99% on-time delivery SLA
   :enforcement: runtime_check

.. mcp:utility:: err_chk
   :module: prod_util
   :priority: critical
   :required: yes
```

**Benefits:**
- Structured metadata
- Operational rationale
- Clear relationships
- **87% precision** ✓
:::
::::::

---

# MCP Directive System

## 7 Directive Types for Complete Semantic Coverage

\small
| Directive | Purpose | Key Insight |
|-----------|---------|-------------|
| `mcp:compliance` | Priority/scope | Critical vs. recommended |
| `mcp:intent` | **Why it exists** | Operational rationale |
| `mcp:severity` | RFC 2119 level | must/should/may |
| `mcp:utility` | Tool metadata | Module, category, lifecycle |
| `mcp:example` | Code examples | Context-aware patterns |
| `mcp:pattern` | Design patterns | Recognize good/bad code |
| `mcp:see-also` | Relationships | Prerequisite/alternative |

\normalsize

**Innovation:** Embeds in RST documentation → renders normally for humans, processable by AI

---

# SME Review Guide: Supervised Refinement

## 7-Dimension Expert Review Methodology

\begin{enumerate}
\item \textbf{Intent Accuracy:} Does `:rationale:` capture true operational purpose?
\item \textbf{Priority/Severity:} Does priority reflect real operational impact?
\item \textbf{Utility Metadata:} Are module names, categories correct?
\item \textbf{Code Examples:} Do examples show the RIGHT way?
\item \textbf{Relationships:} Are `:related:` items truly connected?
\item \textbf{Patterns:} Should this pattern be recognized/flagged?
\item \textbf{Gap Analysis:} What's missing?
\end{enumerate}

**Workflow:** Pilot → SME Review → Iterate → Validate → Deploy

**Result:** Transform "finds text" → "understands intent"

---

# SME Review Impact: The Numbers

## Measured Improvements in NOAA Global Workflow

\begin{table}[h]
\centering
\begin{tabular}{lrrc}
\toprule
\textbf{Metric} & \textbf{Before} & \textbf{After} & \textbf{Improvement} \\
\midrule
Retrieval Precision & 45\% & 87\% & \textcolor{green}{+93\%} \\
False Positives (Compliance) & 35\% & 8\% & \textcolor{green}{-77\%} \\
Query Resolution Time & 2-5 min & 15-30 sec & \textcolor{green}{-80\%} \\
New Developer Onboarding & 8 weeks & 3 weeks & \textcolor{green}{-63\%} \\
\bottomrule
\end{tabular}
\end{table}

**Key Finding:** Domain expert refinement transforms RAG from "keyword matcher" to "intent reasoner"

---

# Hybrid RAG Architecture

## Vector + Graph + Annotations = Magic

:::::: {.columns}
::: {.column width="60%"}
**Pure Vector Search (Baseline)**
- ChromaDB with 768-dim embeddings
- Semantic similarity only
- **P@10: 0.45**

**+ Graph Context**
- Neo4j: 78,339 relationships
- CALLS, IMPORTS, DEFINES
- **P@10: 0.67**

**+ Semantic Annotations**
- MCP directives with intent
- Priority, rationale, patterns
- **P@10: 0.87** ✓ (3.8× improvement)
:::

::: {.column width="38%"}
**Ranking Function:**
$$
\text{score} = 
\begin{cases}
\alpha \cdot \text{cosine} \\
+ \beta \cdot \text{graph} \\
+ \gamma \cdot \text{annot}
\end{cases}
$$

**Weights (default):**
- $\alpha = 0.5$ (semantic)
- $\beta = 0.3$ (structure)  
- $\gamma = 0.2$ (intent)

**Query-Type Adaptive**
:::
::::::

---

# Query Type Optimization

## Different Questions Need Different Approaches

\footnotesize
| Query Type | Vector | Graph | Annot | Example |
|------------|--------|-------|-------|---------|
| **Concept** | 0.7 | 0.1 | 0.2 | "What is Rocoto?" |
| **Usage** | 0.5 | 0.3 | 0.2 | "How do I use err_chk?" |
| **Code Structure** | 0.2 | **0.7** | 0.1 | "What calls this function?" |
| **Compliance** | 0.3 | 0.2 | **0.5** | "Is this EE2 compliant?" |
| **Troubleshoot** | 0.4 | 0.4 | 0.2 | "Why is this failing?" |

\normalsize

**System automatically detects query type and adjusts weights**

Graph dominates for structure queries, annotations for compliance, vectors for concepts

---

# Retrieval Accuracy Evaluation

## 100 Developer Queries, Expert-Labeled Ground Truth

\begin{table}[h]
\centering
\begin{tabular}{lrrr}
\toprule
\textbf{Approach} & \textbf{Precision@10} & \textbf{MRR} & \textbf{Recall@50} \\
\midrule
Text Search (Baseline) & 0.23 & 0.31 & 0.48 \\
Pure Vector (MPNet) & 0.45 & 0.52 & 0.71 \\
Vector + Annotations & 0.67 & 0.73 & 0.84 \\
\textbf{Hybrid (All)} & \textbf{0.87} & \textbf{0.91} & \textbf{0.95} \\
\bottomrule
\end{tabular}
\end{table}

**Query Category Breakdown:** Hybrid wins 90% of usage queries, 95% of structure queries, 93% of compliance checks

---

# Development Velocity: Real Task Comparison

## GitHub Issue #4220 - C48 ATM CTest Path Mapping

:::::: {.columns}
::: {.column width="48%"}
**Before SDD (Estimated)**

- Manual code archaeology: **4-6 hours**
  - grep through 2,800 files
  - trace variable definitions
  - understand context

- Documentation writing: **2-3 hours**
  - synthesize findings
  - write explanations

- Review cycles: **2-4 hours**
  - back-and-forth clarifications

**Total: 8-13 hours**
:::

::: {.column width="48%"}
**With SDD (Actual)**

- RAG-assisted analysis: **45 minutes**
  - hybrid query: instant context
  - graph traversal: call chains
  - annotations: intent

- Spec-driven docs: **30 minutes**
  - template-based generation
  - validated examples

- Automated validation: **15 minutes**
  - health checks pass

**Total: 1.5 hours**

\vspace{1em}
\textcolor{green}{\textbf{5.3-8.7$\times$ faster with higher accuracy}}
:::
::::::

---

# YAML Task Tracking

## Complex Multi-Week Projects as Code

**EVS EE2 Compliance Remediation Example:**

```yaml
metadata:
  name: evs_ee2_compliance_remediation
  duration: "12 weeks"
  effort: "462 hours"
  files_impacted: 670

phases:
  - phase_1_critical_path:    # Weeks 1-3, 32 P0 scripts
  - phase_2_secondary:         # Weeks 4-6, 95 P1 scripts
  - phase_3_bulk:              # Weeks 7-10, 562 remaining
  - phase_4_validation:        # Weeks 11-12, integration

resources:
  personnel: 5.25 FTE-months
  storage: 5TB for regression tests

risk_management:
  - risk: Breaking changes
    mitigation: Comprehensive regression on 90 days data
```

**Benefits:** Accountability, progress tracking, resource planning, reproducibility

---

# Technical Insights: Lessons Learned

## What Works, What Doesn't

\begin{columns}[T]
\begin{column}{0.48\textwidth}
\textbf{✓ Graph Enrichment Non-Negotiable}

Pure vector fails for code intelligence. Structure matters.

\textbf{✓ Quality > Quantity}

10 SME-reviewed sections beat 100 auto-generated annotations.

\textbf{✓ MPNet Sweet Spot}

768-dim provides best quality/speed/cost (25ms inference, P@10=0.87).

\textbf{✓ Health Monitoring First-Class}

Integrated from initialization, not bolted on later.
\end{column}

\begin{column}{0.48\textwidth}
\textbf{✗ Don't Auto-Generate Without SME Review}

Garbage annotations → garbage retrieval.

\textbf{✗ Don't Ignore Version Control}

Stale embeddings cause silent failures. CI/CD pipeline essential.

\textbf{✗ Don't Skip Developer Training}

Show 3-5$\times$ improvements on real tasks to build trust.

\textbf{✗ Don't Attempt Big-Bang Rollout}

Pilot → validate → scale with proven patterns.
\end{column}
\end{columns}

---

# Operational Deployment Architecture

## Production-Ready Infrastructure

:::::: {.columns}
::: {.column width="50%"}
**Knowledge Base Coverage**
- 5,307 documents ingested
- 78,339 code relationships
- 2,800+ files across 7 repos
- EE2 standards (complete)
- CI test case docs

**Services (Systemd-Managed)**
- ChromaDB (Docker, port 8080)
- Neo4j (Docker, ports 7474/7687)
- MCP Server (Node.js v4.0.0)
- VS Code/Cursor integration
:::

::: {.column width="50%"}
**HPC Platforms**
- Hera, Hercules, Orion (RDHPCS)
- WCOSS2 (NCEP Operations)
- 8-core VM, 32GB RAM
- 100GB knowledge base storage

**CI/CD Pipeline**
- Auto-trigger on code commits
- Incremental graph updates
- Re-generate affected embeddings
- Validate retrieval accuracy
:::
::::::

---

# The SDD Paradigm Shift

## From "Find Text" to "Understand Intent"

\begin{center}
\Large
\textbf{Before:} Developer asks → AI searches keywords → Returns generic text

\vspace{1em}

$\Downarrow$ \textit{(Transform with SDD Framework)}

\vspace{1em}

\textbf{After:} Developer asks → AI understands intent → Returns operational context

\vspace{2em}
\end{center}

**Key Innovation:** SME annotations capture the \textit{why} behind the \textit{what}

**Result:** AI reasons like a domain expert, not a keyword matcher

---

# Future Work

## Roadmap for Enhanced Capabilities

\begin{enumerate}
\item \textbf{Multi-Modal Embeddings:} Joint code-text embeddings (understand code semantics directly)

\item \textbf{Temporal Query Analysis:} Track poorly-answered queries → prioritize annotation efforts

\item \textbf{Cross-Repository Intelligence:} Unified graph across Global Workflow, UFS, GSI, wxflow

\item \textbf{Real-Time Collaboration:} Multi-developer annotation editing interface

\item \textbf{Automated Annotation Generation:} LLM generates initial annotations → SME validates
\end{enumerate}

---

# Conclusion

## Three Innovations, One Framework

\begin{enumerate}
\item \textbf{Machine-Readable Specs:} Workflows as code → systematic execution
\item \textbf{Semantic Annotations:} Human-readable + machine-processable
\item \textbf{SME Refinement:} Structured methodology for expert knowledge capture
\end{enumerate}

\vspace{1em}

**Empirical Validation (NOAA Global Workflow):**
- 3.8$\times$ retrieval accuracy (P@10: 0.23 → 0.87)
- 5-9$\times$ development velocity (13 hours → 1.5 hours)
- 77\% false positive reduction (35\% → 8\%)

\vspace{1em}

\begin{center}
\Large
\textbf{Key Takeaway:} AI assistance succeeds when domain experts guide the knowledge base through structured methodologies.

\textit{Pure automation fails. Supervised human-AI collaboration succeeds.}
\end{center}

---

# Questions?

\begin{center}
\Huge Thank You!

\vspace{2em}

\Large
\textbf{Contact:}

NOAA EMC Global Workflow MCP Team

Terry.McGuinness@noaa.gov

\vspace{1em}

\textbf{Resources:}

Framework Specs: \texttt{/mcp\_rag\_eib/eib-mcp-rag-server/sdd\_framework/}

GitHub: \texttt{NOAA-EMC/global-workflow}

\vspace{1em}

\normalsize
\textit{Complete paper, LaTeX source, and training materials available in technical\_specification/}
\end{center}
