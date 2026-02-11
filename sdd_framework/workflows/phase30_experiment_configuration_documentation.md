# Phase 30: Global Workflow Experiment Configuration Documentation
**Version**: 1.0
**Date**: February 11, 2026
**Status**: IN PROGRESS
**Execution Mode**: ISD (Interactive Supervised Development)

---

## Problem Statement

The NOAA Global Workflow experiment configuration system is complex with multiple layers of:
- Application factory patterns
- YAML case file specifications
- Jinja2 template rendering
- Platform-specific resource configuration
- Runtime bash config sourcing

No comprehensive documentation exists that explains the complete flow from experiment definition to runtime execution.

## Objectives

1. Create a comprehensive LaTeX document explaining the full experiment configuration lifecycle
2. Include architectural diagrams, code examples, and data flow illustrations
3. Publish as a technical paper in the papers portfolio
4. Make the document suitable for developers, operators, and stakeholders

---

## Roadmap Alignment

| Vision Reference | Implementation |
|------------------|----------------|
| Global Workflow Developer Documentation | Primary deliverable |
| EIB Knowledge Management | Supports onboarding and training |
| SDD Framework Documentation Standards | Follows established patterns |

**Upstream Dependencies**: Phase 29 (tool usability), global-workflow codebase analysis
**Downstream Consumers**: Developers, operators, new team members

---

## Implementation Steps

### Step 1: Create SDD Workflow Specification ⬜ IN PROGRESS
**Action**: Document the plan before implementation

### Step 2: Gather Additional Architectural Details ⬜ PENDING
**Action**: Use MCP tools to extract:
- Complete application factory registration
- Full config file inventory
- Task dependency examples
- Platform resource matrices

### Step 3: Install LaTeX Dependencies ⬜ PENDING
**Action**: Ensure all required LaTeX packages are available
- texlive-full or equivalent
- tikz, pgfplots for diagrams
- listings for code
- booktabs for tables

### Step 4: Create LaTeX Document ⬜ PENDING
**Action**: Write comprehensive document with:
- Executive summary
- Architecture overview
- Application factory pattern
- YAML case file specification
- Template rendering process
- Resource configuration layers
- Runtime config sourcing
- Complete code examples

### Step 5: Compile to PDF ⬜ PENDING
**Action**: Run pdflatex/xelatex to generate PDF

### Step 6: Commit to Repository ⬜ PENDING
**Action**: git add, commit, push

---

## Document Outline

1. **Introduction**
   - Purpose and scope
   - Target audience
   - Document conventions

2. **System Architecture Overview**
   - High-level component diagram
   - Data flow from definition to execution

3. **Application Factory Pattern**
   - AppConfig base class
   - Registered applications (6 types)
   - Task name generation

4. **Experiment Definition**
   - CLI-based setup (setup_expt.py)
   - YAML case files (CI configurations)
   - Key parameters (NET, MODE, CASE, APP)

5. **Configuration File System**
   - Template files (.j2)
   - Plain config files
   - Hierarchical config structure

6. **Platform Resource Configuration**
   - config.resources architecture
   - Platform-specific overrides
   - CASE × Task resource matrices

7. **Experiment Directory Population**
   - create_experiment.py workflow
   - Jinja2 rendering process
   - EXPDIR structure

8. **Rocoto Workflow Generation**
   - Task definition (gfs_tasks.py)
   - Dependency specification
   - XML generation

9. **Runtime Configuration Sourcing**
   - jjob_header.sh mechanism
   - Config inheritance pattern
   - Machine environment loading

10. **Complete Worked Example**
    - C384 S2SW experiment on Hera
    - Full trace from YAML to execution

11. **Appendices**
    - Complete config file inventory
    - Platform resource reference
    - Glossary

---

## Success Criteria

1. PDF document successfully compiles
2. All sections complete with diagrams and code examples
3. Document is self-contained and comprehensive
4. Suitable for technical reference and training

---

## ISD Approval Gates

- [x] **Gate 1**: SDD workflow specification approved
- [ ] **Gate 2**: Document outline approved
- [ ] **Gate 3**: Final document review
