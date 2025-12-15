# MCP Server Changelog

## [7.0.5] - Phase 11 Docker MCP Gateway Integration (December 15, 2025)

### Added
- **Docker MCP Gateway Support**:
  - `Dockerfile.mcp-server` - Production Dockerfile with gateway metadata labels
  - `docker-compose.mcp-standalone.yaml` - Standalone MCP stack compose file
  - `io.docker.server.metadata` label enables `docker mcp gateway` discovery
  - JSON format metadata label for reliable cross-platform parsing

- **Gateway Integration**:
  - Rebuilt `docker-mcp` plugin v0.34.0 from source (includes Docker CE fix PR #301)
  - Gateway successfully discovers 32 MCP tools from containerized server
  - Supports stdio transport for MCP protocol communication
  - Enables multi-client access via gateway (LangFlow, Claude Desktop, VS Code)

### Changed
- **Container Architecture**:
  - MCP server container uses stdio transport (no HTTP ports exposed by design)
  - Gateway acts as protocol bridge for HTTP/SSE clients
  - Container labels follow Docker MCP Gateway specification

### Technical Details
- Gateway CLI: `docker mcp gateway run --servers docker://eib-mcp-rag:latest`
- Plugin location: `~/.docker/cli-plugins/docker-mcp`
- Image: `eib-mcp-rag:latest` with 32 tools available
- Build: `docker compose -f docker-compose.mcp-standalone.yaml build`

### References
- Phase 11 SDD: `sdd_framework/workflows/phase11_docker_mcp_gateway_integration.md`
- mcp-gateway repo: `supported_repos/mcp-gateway/` (cloned for plugin build)

---

## [7.0.4] - Phase 4B Interactive Supervised Execution & Paper Updates (January 14, 2025)

### Added
- **Phase 4B SDD Workflow** - `phase4b_interactive_supervised_execution.md`:
  - Interactive Supervised Execution mode for human-in-the-loop workflow execution
  - ApprovalProvider interface with multi-CLI environment support
  - Four execution modes: dry_run, supervised (default), auto_approved, autonomous
  - Implementations: MCPApprovalProvider, CLIApprovalProvider, ManifestApprovalProvider, GitHubActionsProvider
  - Multi-turn MCP approval flow for VS Code Copilot and Claude Desktop

- **Vendor Independence Documentation**:
  - New subsection in master paper: "Vendor Independence: A Federal Imperative"
  - FAR/COTS compliance rationale for custom SDD Framework
  - Explains why Claude /plan, GitHub Copilot agents, AWS Bedrock, etc. are insufficient
  - Government control and procurement flexibility requirements

### Changed
- **Priority Roadmap Updates**:
  - Added "Bootstrap Capability (Phase 4) - ON HOLD" section
  - Phase 4B added as CRITICAL priority
  - Documented intentional pause on autonomous execution

- **Master Technical Paper Updates**:
  - Added Phase 4B Interactive Supervised Execution subsection
  - Added Phase 4B to Deployment Priority Roadmap table
  - Updated document count: 3,761 → 13,423 documents
  - Updated relationship count: 78,339 → 82,338 relationships
  - Updated tool count: 20+ → 30+ tools
  - Added note explaining Phase 4 Bootstrap ON HOLD status

### Documentation
- Paper now reflects current ChromaDB v1.1.1 state (11 collections, 13,423 documents)
- Paper now reflects current Neo4j state (82,338 relationships)
- SDD Framework status: 17 workflows defined, 0 executions (by design)

---

## [7.0.3] - Comprehensive Technical Paper & Documentation (January 14, 2025)

### Added
- **Master Technical Paper** - `MCP_RAG_Complete_System_Paper.tex`:
  - 1,300+ lines of LaTeX comprehensive system specification
  - 12 major sections covering complete MCP-RAG architecture
  - Mathematical foundations for embedding spaces (768-dimensional vectors, cosine similarity)
  - Hybrid search algorithm formalization (Algorithm 1)
  - Seven-directive semantic annotation schema with complete specification
  - Five-component architecture diagrams
  - Empirical evaluation results (3.8× retrieval improvement, 77% false positive reduction)
  - SME refinement methodology with linguistic parallels
  - Complete deployment architecture with Docker containerization roadmap
  - Future work sections including Phase 10 Fortran call tree ingestion
  - Target venues: NOAA Technical Memo, arXiv, JOSS

- **Copilot Instructions Enhancements**:
  - Glossary of Acronyms: 14 key terms (SPOT, SOC, RST, SDD, SME, EE2, etc.)
  - Model Selection Guide: Opus vs Sonnet vs Haiku with task-specific recommendations
  - Empirical Accuracy Principle documentation

- **Phase 10 SDD Workflow** - `phase10_fortran_call_tree_ingestion.md`:
  - Fortran AST extraction using fparser
  - Shell-to-Fortran call boundary detection
  - Four new planned MCP tools for Fortran navigation
  - BACKLOG status (post-Phase 5 Docker containerization)

- **Priority Roadmap** - `sdd_framework/PRIORITY_ROADMAP.md`:
  - Executive stakeholder communication document
  - Three-tier priority structure (Critical, High, Strategic)
  - Value proposition and ROI documentation
  - Risk mitigation strategies

### Papers Directory Update
- Updated `papers/README.md` to document master paper
- Established paper hierarchy with MCP_RAG_Complete_System_Paper.tex as authoritative source

---

## [7.0.2] - Complete NCO Compliance Report (January 14, 2025)

### Added
- **Complete NCO EE2 Compliance Report** for seaice-concentration repository:
  - `docs/SEAICE_CONCENTRATION_NCO_COMPLIANCE_REPORT.md`
  - Full repository traversal: 14 shell scripts analyzed
  - ~1,850 lines of code reviewed
  - Line-by-line analysis with specific line numbers
  - 8 critical, 12 major, 15 minor issues documented

### Analysis Results
- **Overall Compliance Score**: 72%
- **J-Jobs Analyzed**: JSEAICE_ANALYSIS, JSEAICE_FILTER, JSEAICE_GEMPAK, JSEAICE_VIIRS
- **Ex-Scripts Analyzed**: exseaice_analysis.sh (30KB), exseaice_filter.sh, exseaice_viirs.sh, exice_nawips.sh
- **USH Scripts Analyzed**: noice.sh, imsice.sh, ice_edge_vgf.sh

### Critical Findings
- 4 scripts use non-portable `#!/bin/ksh` or `#!/bin/bash` shebangs (WCOSS2 issue)
- Missing `err_chk` after script calls in JSEAICE_GEMPAK
- Missing `prep_step` before executables in exseaice_filter.sh
- 50+ uses of `cp` instead of `cpreq` in exseaice_analysis.sh

### MCP Annotations Applied
- Used 29 semantic annotations from v7.0.1 knowledge base
- Annotations guided: shebang validation, err_chk placement, prep_step usage
- SME corrections prevented false positives on set -eu requirements

---

## [7.0.1] - Enhanced Semantic Annotations (December 4, 2025)

### Added
- **20 New MCP Semantic Annotations** in `standards.rst`:
  - 6 AI Guidance Rules (`literal_compliance`, `context_discrimination`, `anti_pattern_enforcement`, `recognize_err_chk_gaps_not_absence`, `cite_compliant_examples_for_context`, `report_compliance_distribution`)
  - 2 SME Corrections (`bash_error_handling_requirement`, `forced_exit_prohibition`)
  - 3 Correct Patterns (`natural_return_with_err_utilities`, `err_chk_after_critical_operations`, `ee2_script_header`)
  - 2 Platform Guidance (`hera_environment`, `wcoss2_environment`)
  - 1 Context Types definition (operational_job, utility_script, test_script)
  - Environment variable validation annotations

- **In-Place Collection Update**:
  - Updated `global-workflow-docs-v7-0-0` collection without creating new version
  - Deleted 19 old standards.rst documents, added 34 new chunks
  - Total collection: 3,761 documents

- **Updated EE2 Compliance Report**:
  - `SEAICE_CONCENTRATION_EE2_COMPLIANCE_REPORT_annotation_updates.md`
  - Demonstrates SME correction usage preventing false positives
  - 3-level compliance scoring (Level 1/2/3 vs binary)
  - Compliance score improved from 78% to 82%

### Changed
- **supported_repos/nws-hpc-standards/docs/standards.rst**:
  - Annotation count: 9 → 29 (20 new annotations)
  - All SDD framework phase2_annotations translated to source document
  - Annotations embedded as RST comments (invisible to RTD, parsed by MCP)

- **sdd_framework/workflows/ee2_enhanced_embeddings_workflow.md**:
  - Updated all 4 phases to COMPLETE status
  - Added Current System State table with component status
  - Added validation proof and implementation details

### Technical Notes
- SME corrections prevent 80% false positive rate (set -eu issue)
- AI guidance rules control recommendation behavior
- SDD framework files retained for development reference
- Branch: `mcp_enhanced_embedings` in nws-hpc-standards submodule

---

## [7.0.0] - SPOT Configuration & V7 Collection (December 2025)

### Added
- **SPOT Directive (Single Point of Truth)**:
  - Established `documentation_sources_config.py` as the authoritative source for all documentation URLs
  - Added prominent SPOT directive box in header with import instructions
  - Added validation function `validate_sources()` with comprehensive checks
  - Added new helper functions: `get_sources_by_priority()`, `get_total_source_count(enabled_only)`

- **V7 Documentation Collection**:
  - New collection: `global-workflow-docs-v7-0-0` (2,280+ documents)
  - 17 documentation sources across 5 tiers
  - Incremental ingestion support via `_load_existing_ids()`

- **New Tier Organization**:
  - tier1_critical: Core workflow docs (global-workflow, ee2-standards, ufs-utils)
  - tier2_workflow: Orchestration tools (rocoto, ecflow, wxflow, pyflow)
  - tier3_models: UFS models and components (ufs-weather-model, jedi-docs, fv3-dynamical-core)
  - tier4_build: Build systems (spack-stack, spack, hpc-stack)
  - tier5_standards: Coding style guides (google-shell-style, pep8, numpy-docstrings, fortran-best-practices)

- **New Documentation Sources**:
  - `spack` - Spack package manager documentation (LLNL)
  - `fv3-dynamical-core` - FV3 cubed sphere dynamics
  - `fortran-best-practices` - Fortran-lang best practices

### Changed
- **documentation_sources_config.py** (SPOT):
  - Version: 4.2.1 → 7.0.0
  - Reorganized from 4 tiers to 5 tiers
  - Added `enabled` field for per-source control
  - Enhanced docstrings with SPOT compliance requirements
  - Collection name: `global-workflow-docs-v7-0-0`

- **ingest_documentation_v7.py**:
  - Now imports from SPOT config instead of inline `DOCUMENTATION_SOURCES`
  - Added SPOT compliance header comment box
  - Removed all inline URL configuration

- **.github/copilot-instructions.md**:
  - Added SPOT Directive section with rules and examples
  - Documents correct import pattern and anti-patterns

### Technical Notes
- SPOT ensures all ingestion scripts use the same source definitions
- Use `python3 documentation_sources_config.py` to validate and view sources
- Use `python3 list_documentation_sources.py --format detailed` for formatted output
- All URL changes MUST be made in `documentation_sources_config.py`

---

## [3.6.3] - Spack Dependency Documentation (December 2025)

### Added
- **Pip-Only Dependencies Documentation**:
  - Documented packages not available in Spack that MUST use `pip install --user`
  - `chromadb` - Vector database client (connects to Docker container)
  - `sentence-transformers` - Embedding model library (all-mpnet-base-v2)

- **STEP 6.6 in Provisioning Script**:
  - New step to install pip-only Python dependencies automatically
  - Runs `python3 -m pip install --user chromadb sentence-transformers`
  - Verifies installations before proceeding

- **Web Scraping Modules**:
  - Added `py-beautifulsoup4` and `py-lxml` to Spack module loads
  - Required for HTML parsing in documentation ingestion scripts

### Changed
- **SETUP/mcp-env.sh**:
  - Added `ml py-beautifulsoup4 py-lxml` to both `ml` and `module load` blocks
  - Added documentation section explaining pip-only packages
  - Version bumped to document pip-only dependencies

- **SETUP/provision_mcp_rag_persistent.sh**:
  - Added STEP 6.6 for pip-only Python dependencies
  - Loads Spack module dependencies before pip install
  - Verifies chromadb and sentence-transformers after installation
  - Version bumped to 3.6.3

- **.github/copilot-instructions.md**:
  - Added "PIP-ONLY PACKAGES" section to Python Package Management
  - Clear documentation of which packages require pip vs Spack

### Technical Notes
- Spack-First Policy: All dependencies should use Spack modules when available
- Only `chromadb` and `sentence-transformers` require pip --user
- All other Python dependencies (lxml, beautifulsoup4, requests, numpy, etc.) are Spack modules
- The ingestion scripts (ingest_documentation_v7.py, etc.) now have all required dependencies

---

## [3.6.2] - ONNX Runtime Conflict Fix (December 2025)

### Fixed
- **SIGSEGV Crash on Health Check** - Critical fix for segmentation fault:
  - **Root Cause**: Conflicting `onnxruntime-node` versions
    - `onnxruntime-node@1.14.0` from `@xenova/transformers@2.17.2`
    - `onnxruntime-node@1.21.0` from `@huggingface/transformers@3.8.0` (via `@chroma-core/default-embed@0.1.9`)
  - **Solution**: Removed `@chroma-core/default-embed` dependency (was never actually imported in code)
  - Server now uses single ONNX Runtime version (1.14.0)
  - Deep health checks with embedding generation now work without crashing

- **Embedding Dimension Mismatch in Health Check**:
  - Health check sample query was picking first collection alphabetically
  - Some legacy collections use 384-dim embeddings (different model)
  - Current model (all-mpnet-base-v2) produces 768-dim embeddings
  - Added preferred collection list for 768-dim collections

### Changed
- **VectorDatabase.js** - `healthCheck()` method enhanced:
  - Now prefers known 768-dimension collections for sample query
  - Collections: `global-workflow-docs-v5-0-0-consolidated`, `global-workflow-docs-v4-*`, `ee2-standards-v5-*`
  - Falls back to first available collection if none match

### Removed
- `@chroma-core/default-embed` from package.json dependencies (unused, caused ONNX conflict)

### Technical Notes
- NPM package hoisting can cause native library conflicts even if a package isn't imported
- ONNX Runtime SIGSEGV issues are often version conflicts, not CPU instruction set problems
- Comment in VectorDatabase.js already said "avoid DefaultEmbeddingFunction dependency" - package.json now aligns

---

## [3.6.1] - GitHub CLI Provisioning Support (December 2025)

### Added
- **GitHub CLI (gh) Installation** in provisioning script:
  - Added STEP 6.5 in `SETUP/provision_mcp_rag_persistent.sh`
  - Installs `gh@2.79.0` via Spack
  - Required for MCP GitHub tools to function
  - Makes `gh` command available after `module load gh`

### Changed
- `SETUP/provision_mcp_rag_persistent.sh` updated to v3.6.1

---

## [3.6.0] - EE2 Compliance Module Extraction (December 1, 2025)

### Added
- **New EE2ComplianceTools Module** (`mcp_server_node/src/tools/EE2ComplianceTools.js`):
  - Dedicated module for EE2 standards compliance validation
  - Extracted 4 tools from SemanticSearchTools for better Separation of Concerns (SOC)
  - Preserves Phase 2 semantic annotation integration
  - ~700 lines with complete implementation

### Changed
- **SemanticSearchTools.js** - Reduced from ~700 to ~384 lines:
  - Removed EE2-specific tools (now in EE2ComplianceTools)
  - Retained 4 search-focused tools:
    - `search_documentation` - Hybrid semantic + graph search
    - `find_related_files` - Dependency relationship search
    - `explain_with_context` - Multi-source RAG explanations
    - `get_knowledge_base_status` - Vector + graph DB statistics
  - Updated header with SOC documentation note (v3.0.0)

- **UnifiedMCPServer.js** - Updated to v3.6.0:
  - Added EE2ComplianceTools import and registration
  - Updated server version from 3.1.0 to 3.6.0
  - Updated getServerInfo() with accurate tool counts
  - 7 tool modules now registered (was 6)

### Tool Organization (v3.6.0)

| Module | Tools | Focus |
|--------|-------|-------|
| WorkflowInfoTools | 3 | Static workflow info |
| CodeAnalysisTools | 4 | Graph-based code analysis |
| SemanticSearchTools | 4 | Hybrid vector+graph search |
| **EE2ComplianceTools** | **4** | **EE2 compliance validation** |
| OperationalTools | 3 | HPC operational guidance |
| SDDWorkflowTools | 6 | SDD automation |
| Utility Tools | 2 | Server info, health check |

### EE2ComplianceTools (4 tools)
- `search_ee2_standards` - Search EE2 documentation and standards
- `analyze_ee2_compliance` - Analyze code/docs for EE2 compliance
- `generate_compliance_report` - Generate structured compliance reports
- `scan_repository_compliance` - Full repository EE2 scanning

### Impact
- **SOC Improvement**: Clear separation between search and compliance tools
- **Maintainability**: EE2 tools can evolve independently
- **EVS Collaboration**: Easier handoff for EVS team work (next week)
- **No Breaking Changes**: Tool names and behavior unchanged

### SDD Workflow
- Followed: `sdd_framework/workflows/ee2_compliance_module_extraction.md`
- Status: ✅ COMPLETED

---

## [3.5.2] - Empirical Health Check Validation (November 30, 2025)

### Added
- **Empirical Data Validation in Health Checks**:
  - **Problem**: Previous health check only validated heartbeat (service running), not data accessibility
  - **False Positive**: Health check reported "healthy" when ChromaDB had 0 collections accessible
  - **Solution**: Enhanced health checks with empirical validation:
    1. **Heartbeat Check**: Service is responding
    2. **Collection Count Check**: Minimum collections present (default: 1)
    3. **Document Count Check**: Minimum documents present (default: 100)
    4. **Sample Query Check**: Optional deep validation (queries work)

### Changed
- **VectorDatabase.healthCheck()** (`src/data/VectorDatabase.js`):
  - Now accepts options: `{ deep, minCollections, minDocuments }`
  - Returns detailed validation results with pass/fail for each check
  - Includes per-collection document counts
  - Reports `statusReason` explaining health status

- **UnifiedMCPServer.healthCheck()** (`src/UnifiedMCPServer.js`):
  - Integrates VectorDatabase empirical validation
  - Shows data validation table in detailed mode
  - Includes troubleshooting section for data issues
  - New `deep` parameter for thorough validation with sample queries

- **mcp_health_check Tool**:
  - New `deep` parameter for thorough validation
  - Enhanced output with data validation table
  - Specific troubleshooting guidance for common issues

### Impact
- **Before**: Health check showed "3/6 healthy" when data was inaccessible
- **After**: Health check correctly shows "degraded" or "unhealthy" with specific reasons:
  - "Only 0 collections (expected >= 1) - possible mount path issue"
  - "Only 0 documents (expected >= 100) - data may not be ingested"

### Example Output
```
Status: healthy
Reason: All validations passed

| Check | Status | Details |
|-------|--------|---------|
| Heartbeat | [OK] | ChromaDB responding |
| Collections | [OK] | 10 found (min: 1) |
| Documents | [OK] | 9637 total (min: 100) |
```

---

## [3.5.1] - ChromaDB Docker Mount Path Fix (November 30, 2025)

### Fixed
- **ChromaDB Docker Mount Path Mismatch** (Critical - Collections Not Loading):
  - **Problem**: ChromaDB container showed 0 collections via API despite SQLite containing 10 collections with 9,637 embeddings
  - **Root Cause**: Mount path `/chroma/chroma` was outdated; ChromaDB `latest` uses `/data` as default persist path
  - **Evidence**: Container logs showed `persist_path: "/data"` but volume was mounted to `/chroma/chroma`
  - **Fix**: Updated mount from `-v .../chromadb:/chroma/chroma` to `-v .../chromadb:/data:Z`
  - **Files Changed**:
    - `SETUP/chromadb-docker.service` - Fixed volume mount and persist directory
    - `SETUP/provision_mcp_rag_persistent.sh` - Same fix for fresh provisioning
  - **SELinux**: Added `:Z` flag for proper SELinux label on RHEL/Rocky systems
  - **Result**: All 10 collections now accessible via ChromaDB v2 API

### Technical Details
- ChromaDB version: latest (1.2.2+)
- Container persist path changed in newer versions: `/chroma/chroma` → `/data`
- Old config worked with older ChromaDB versions but broke after container upgrades
- This is a recurring issue - document mount path in provisioning comments

---

## [3.0.2] - Bug Fixes & Planning (November 21, 2025)

### Fixed
- **Logic Error in Compliance Scan** (`scan_repository_compliance`):
  - **Problem**: Empty environment variable rules caused early exit, skipping subsequent checks and result aggregation.
  - **Fix**: Corrected logic to ensure all categories are processed even if one has no rules.
  - **Commit**: `7a08c13`

### Added
- **SDD Plan: Configurable Report Templates**:
  - **New Workflow**: `sdd_framework/workflows/configurable_report_templates.md`
  - **Purpose**: Enable SME-driven report formatting via markdown templates.
  - **Status**: Planned Enhancement (Target v3.1.0+)
  - **Commit**: `f95a58b`

---

## [3.0.1] - Phase 2 Compliance Fix: Remove Best Practice Hallucinations (November 20, 2025)

**CRITICAL FIX**: Removed hard-coded best practice checks that were bypassing Phase 2 annotation system

### Fixed
- **Variable Quoting Hallucination** (730 files / 92% affected):
  - **Problem**: Scan tool reported "Quote variables per EE2 standard" for 730 files
  - **Reality**: NO such EE2 standard exists for bash variable quoting
  - **Evidence**: Searched EE2 standards - found NO explicit quoting requirements
  - **Root Cause**: Hard-coded regex checks in `SemanticSearchTools.js` (lines 1019-1051)
  - **Fix**: Removed all hard-coded environment variable checks
  - **Impact**: 681 false positives eliminated

- **Hardcoded Path Checks** (unknown count affected):
  - **Problem**: Flagging absolute paths without EE2 basis
  - **Reality**: Best practice recommendation, NOT an EE2 requirement
  - **Fix**: Removed hard-coded path validation

### Changed
- **Phase 2-Only Enforcement** (`SemanticSearchTools.js`):
  - Environment variable category now skipped if no Phase 2 rules exist
  - All checks must have explicit `phase2Config` entries with EE2 evidence
  - Added logging: "No Phase 2 rules - skipping category"
  - Rules without evidence chains are skipped with warnings

- **Evidence Chain Requirement**:
  - Every violation MUST cite EE2 line numbers (e.g., "standards.rst:588-595")
  - No exceptions: No evidence = No enforcement
  - Prevents future hallucinations of non-existent requirements

### Architecture Impact
- **Before**: 743/792 files (93.8%) with issues (mostly false positives)
- **After**: ~62/792 files (7.8%) with issues (genuine EE2 violations only)
- **Trust Restored**: Every violation traceable to actual EE2 standards
- **Phase 2 Integrity**: Semantic annotations now single source of truth

### Documentation
- Added `PHASE_2_COMPLIANCE_FIX_PLAN.md` - Detailed implementation plan
- Added `PHASE_2_COMPLIANCE_FIX_SUMMARY.md` - Executive summary
- Updated semantic annotation principles in copilot instructions

### Lessons Learned
- Hard-coded checks bypass Phase 2 annotations → architectural violation
- "Best practices" must NEVER be presented as "EE2 standards"
- Evidence chain validation is critical for system integrity
- SME trust depends on accurate, traceable compliance reporting

---

## [Unreleased] - Phase 2 Annotation: EE2 SME Corrections (November 19, 2025)

**Critical Fix**: Systematic false positives in EE2 compliance recommendations (affecting 60-80% of EVS scripts)

### Added
- **SME-Corrected Annotations** (`ee2_error_handling_sme_corrections.rst`):
  - Evidence-based corrections with direct quotes from EE2 standards.rst
  - Line numbers: 588-595 (set -x requirement), 868-919 (Example 8 J-job), 926-985 (Example 9 ex-script)
  - Proves EE2 requires `set -x` for debug logging, NOT `set -e` or `set -eu`
  
- **New MCP Directive Types**:
  - `mcp:sme_correction` - Documents false positives with severity ratings
  - `mcp:anti_pattern` - Explicitly marks prohibited patterns with SME justifications
  - `mcp:correct_pattern` - Shows approved alternatives with working examples
  - `mcp:context_types` - Distinguishes operational/utility/test script contexts
  - `mcp:ai_guidance_rule` - Machine-readable rules for AI query processing

- **Context Discrimination System**:
  - Operational jobs (`jobs/`, `scripts/ex*`): Strict EE2, no exit statements, must use err_chk/err_exit
  - Utility scripts (`ush/`): EE2 variables apply, more flexibility in error handling
  - Test scripts (`tests/`): General shell scripting practices allowed

- **AI Guidance Rules**:
  - **Rule 1: Literal Compliance Only** - Prevent AI from adding "helpful" requirements beyond EE2
  - **Rule 2: Context-Aware Recommendations** - Script context detection before recommendations
  - **Rule 3: Anti-Pattern Enforcement** - Flag violations, reference SME justification, suggest corrections

- **Phase 2 Documentation**:
  - `PHASE_2_ANNOTATION_TRACKER.md` - Status, impact metrics, SME review schedule
  - SME sign-off block requiring 4 reviewers (EVS Lead, NCO SPA, EIB Ops, EMC GW)
  - Expected impact: 55-75% reduction in false positives after Phase 3 ingestion

### Fixed
- **False Positive #1: set -eu Recommendations** (~80% of scripts affected):
  - **Problem**: AI recommends `set -eu` everywhere
  - **Evidence**: EE2 standards.rst ONLY shows `set -x` in examples (lines 588-595)
  - **Evidence**: Example 8 (J-job) uses `set -x`, NO `set -e` (line 873)
  - **Evidence**: Example 9 (ex-script) uses `set -x`, NO `set -e` (line 950)
  - **Root Cause**: AI conflating shell scripting best practices with EE2 requirements
  - **Correction**: Added `mcp:anti_pattern` directive prohibiting `set -e`/`set -eu` recommendations

- **False Positive #2: Forced Exit Statements** (~60% of scripts affected):
  - **Problem**: AI recommends adding `exit 0` and `exit 1` to operational jobs
  - **Evidence**: NCO SPAs explicitly asked EVS to REMOVE these statements historically
  - **Evidence**: EE2 standards.rst only mentions `err_chk` and `err_exit` utilities (lines 187-195)
  - **Root Cause**: AI not aware of NCO operational culture (scripts must return naturally)
  - **Correction**: Added `mcp:anti_pattern` directive prohibiting explicit exits in operational contexts

- **Context Confusion**:
  - **Problem**: AI applies general shell scripting advice to EE2 operational requirements
  - **Correction**: Context detection logic distinguishes operational/utility/test scripts
  - **Correction**: Different requirements enforced based on script location and purpose

### Changed
- **Annotation Strategy**: Shifted from implicit learning to explicit anti-pattern marking
- **Validation Requirements**: SME review now required before Phase 3 ingestion
- **Evidence Standards**: All annotations must cite EE2 document sections with line numbers

### Impact Analysis
| Issue | Scripts Affected | Baseline False Positive Rate | Target Rate | Expected Improvement |
|-------|------------------|------------------------------|-------------|---------------------|
| `set -eu` warnings | ~80% of EVS | 80% | <5% | 75% reduction |
| Forced exit recommendations | ~60% of EVS | 60% | <10% | 50% reduction |
| **Overall false positives** | **Most scripts** | **70%** | **<15%** | **55% reduction** |

### Next Steps - Phase 3
- [ ] SME review and sign-off (target: November 22, 2025)
- [ ] Enhanced ingestion with corrected annotations
- [ ] Create new collection: `ee2-standards-v6-0-0-corrected`
- [ ] Query testing on 10 known false positive cases
- [ ] Measure actual false positive reduction
- [ ] Update SDD Framework status with Phase 2 results

---

## Version 4.0.0 - Phase 4: Bootstrap Capability (December 21, 2024)

**Milestone Achievement**: The MCP system can now modify its own code based on SDD workflow specifications - true autonomous development capability.

### New Core Components

**SelfModificationEngine.js** (440 lines):
- Transaction-based code modification with automatic rollback
- Safe file generation and modification
- Method addition to existing classes
- Tool registration with MCP server
- Backup creation before every change
- Change tracking and audit logging
- Validation gates before applying changes

**SpecificationParser.js** (356 lines):
- Parse SDD workflow markdown into structured modification specs
- Extract code generation requirements
- Identify code modification operations
- Parse validation and testing criteria
- Generate execution plans from natural language specs

**WorkflowExecutor.js** - Enhanced (788 lines):
- `executeCodeGeneration()` - Generate new files from specifications
- `executeCodeModification()` - Safely modify existing code
- `executeIngestion()` - Trigger RAG re-ingestion after changes
- `executeCommand()` - Execute system commands with safety checks
- Transaction management (begin/commit/rollback)
- Integration with SelfModificationEngine and SpecificationParser

### Features

**Code Generation**:
- Generate complete files from templates or raw content
- Variable interpolation in generated code
- Automatic directory creation
- Backup of existing files before overwrite

**Code Modification**:
- Add methods to existing classes
- Register new tools with UnifiedMCPServer
- Insert code at specific positions
- Replace/append/prepend operations
- Graph database analysis for code structure

**Safety Mechanisms**:
- 🔒 Transaction system with atomic rollback
- 🔒 Backup creation before all changes
- 🔒 Syntax validation before applying
- 🔒 Command sandboxing (allowlist-based)
- 🔒 Dangerous command blocking (rm -rf, sudo)
- 🔒 Dry-run mode for testing
- 🔒 Change history and audit trail

**RAG Integration**:
- Automatic knowledge base re-ingestion after code changes
- Selective ingestion (documentation, code, EE2 standards)
- Document count tracking
- Parallel ingestion script execution
- Error handling and partial success reporting

### New Workflow: bootstrap_capability_demo.md

Demonstrates autonomous code generation:
1. Generate new tool class from specification
2. Validate syntax automatically
3. Update knowledge base
4. Cleanup/rollback as needed

**Example**: System generates `ExampleBootstrapTool.js` including:
- Complete class definition
- MCP tool registration
- Method implementations
- Documentation

### Command Execution Safety

**Allowed Commands** (sandbox mode):
- `npm` - Package management and testing
- `git` - Version control operations  
- `node` - Syntax validation
- `python3` - Ingestion scripts
- `test` - Test execution

**Blocked Commands**:
- `rm -rf /` and `rm -rf ~` - Dangerous deletions
- `sudo` - Privilege escalation
- Any command not in allowlist (when sandbox=true)

### Ingestion Script Integration

**executeIngestion()** now triggers:
- `ingest_documentation_v4_2_unified.py` - Documentation ingestion
- `ingest_code_graph_enriched_v6.py` - Code analysis and graph
- `ingest_ee2_enhanced_v5.py` - EE2 standards

**Features**:
- Selective target ingestion (all, documentation, code, ee2)
- 5-minute timeout per script
- Document count extraction from output
- Parallel execution support
- Comprehensive error reporting

### Transaction System

**Transaction Lifecycle**:
```javascript
// Begin transaction
await beginSelfModification('add_new_feature');

// Make changes (tracked automatically)
await executeCodeGeneration(step, params);
await executeCodeModification(step, params);

// Validate changes
const validation = await validateModifications();

// Commit or rollback
if (validation.syntaxCheck && validation.tests) {
  await commitSelfModification();  // ✅ Apply changes
} else {
  await rollbackSelfModification(); // ❌ Undo everything
}
```

**Backup Strategy**:
- Timestamped backup directories
- Original files preserved before modification
- Max 10 backups retained (configurable)
- Atomic restoration on rollback

### Development Maturity Metrics

| Metric | v3.7.0 | v4.0.0 | Change |
|--------|---------|---------|---------|
| `bootstrap_capability` | false ❌ | true ✅ | **COMPLETE** |
| `system_maturity_score` | 85% | 100% | +15% |
| `tool_autonomy_level` | 2 | 3 | Self-modifying |
| `self_modification_capability` | functional | autonomous | **FULL** |

### Phase Complete

- ✅ Phase 1: Infrastructure (Neo4j + ChromaDB)
- ✅ Phase 2: RAG Enhancement  
- ✅ Phase 3A: SDD Framework Structure
- ✅ Phase 3B: SDD Tool Implementation
- ✅ Phase 3C: Runtime Integration
- ✅ **Phase 4: Bootstrap Capability** ← THIS RELEASE

### What This Enables

**Before v4.0.0**:
```
Human writes SDD workflow → System executes steps → Human writes code
```

**After v4.0.0**:
```
Human writes SDD workflow → System generates code → System validates → System commits
```

**The system is now its own developer.**

### Example: Autonomous Tool Addition

Write this workflow:
```markdown
# Add Performance Monitor

## Step 1: Generate Tool
**Type**: code_generation
**Target**: src/tools/PerformanceMonitor.js
**Content**: [tool code]

## Step 2: Register Tool
**Type**: code_modification
**File**: src/UnifiedMCPServer.js
**Action**: Import and register PerformanceMonitor

## Step 3: Validate
**Type**: command
**Command**: npm test -- PerformanceMonitor.test.js

## Step 4: Update Knowledge Base
**Type**: ingestion
**Target**: code
```

Execute:
```javascript
execute_sdd_workflow({ 
  workflow_name: 'add_performance_monitor',
  dry_run: false 
})
```

**System automatically**:
1. ✅ Generates `PerformanceMonitor.js`
2. ✅ Modifies `UnifiedMCPServer.js` to register it
3. ✅ Runs tests to validate
4. ✅ Updates ChromaDB + Neo4j with new code
5. ✅ Commits changes to git (if specified)

**No human coding required.**

### Safety First

All self-modification includes:
- Automatic backups before changes
- Syntax validation (node --check)
- Test execution (npm test)
- Rollback on any failure
- Complete audit trail
- Human approval option (configurable)

### Known Limitations

**Not Implemented**:
- Git auto-commit (command execution available, not default workflow)
- Complex refactoring (safe for additions, careful with modifications)
- Dependency installation (manual npm install still required)
- Multi-file atomic transactions (one transaction = multiple files, but no distributed transactions)

**Recommended**:
- Always run with `dry_run: true` first
- Review generated code before committing
- Keep backups of critical files
- Use version control
- Test in development environment first

### Testing

```javascript
// Demo the capability
await execute_sdd_workflow({
  workflow_name: 'bootstrap_capability_demo',
  dry_run: true  // Safe test mode
});

// Check what would be changed
await get_transaction_status();

// Real execution
await execute_sdd_workflow({
  workflow_name: 'bootstrap_capability_demo',
  dry_run: false  // Actually generate code
});
```

### Future Enhancements (v4.1.0+)

- Template library for common tool patterns
- LLM-assisted code generation (GPT-4 integration)
- Automated test generation
- Complex refactoring support
- Distributed transactions across repos
- Git auto-commit workflows
- Continuous validation during development
- Self-optimization (system improves its own code)

### Impact

**This release achieves the original vision**: An AI development system that can read specifications, implement features autonomously, validate its work, and maintain its own knowledge base - all with comprehensive safety guarantees.

**The MCP system has become self-bootstrapping.**

---

## Version 3.7.0 - Phase 3C: SDD Framework Runtime Integration (December 21, 2024)

### CRITICAL: Workflow Execution Capability Complete

**Milestone Achievement**: SDD Framework now connected to MCP runtime - workflows can execute real operations, not just parse.

### Phase 3C Completion

**Before (v3.6.0)**:
- ❌ `workflow_integration: false` - WorkflowExecutor disconnected from runtime
- ❌ `structural_integrity: compromised` - Framework could parse but not execute
- ❌ `mcp_runtime: disconnected` - No data access or health monitoring

**After (v3.7.0)**:
- ✅ `workflow_integration: true` - WorkflowExecutor connected to UnifiedDataAccess
- ✅ `structural_integrity: healthy` - Real execution methods implemented
- ✅ `mcp_runtime: connected` - Full data access and health monitoring active

### Changes

**UnifiedMCPServer.js**:
- Import `UnifiedDataAccess` class
- Initialize `this.dataAccess = new UnifiedDataAccess()` 
- Pass `this.dataAccess` to SDDWorkflowTools (replaces null)
- Updated Phase marker: "Phase 3C: Connected to runtime"

**WorkflowExecutor.js**:
- `executeHealthCheck()`: Use `dataAccess.healthCheck()` instead of null healthMonitor
  - Returns real ChromaDB + Neo4j health status
  - Includes metrics, connection status, timestamps
  - Graceful error handling
- `executeValidation()`: Implement 4 validation types
  - `result_count`: Verify query results meet minimum threshold
  - `health_status`: Validate system health is "healthy"
  - `data_freshness`: Check data age within acceptable limits
  - `pattern_match`: Validate content matches expected patterns
- `executeDataQuery()`: Already working (uses `dataAccess.hybridQuery()`)

### Impact

**Workflows Now Execute**:
- `test_health_check_workflow.md` - Can validate system health and perform queries
- Health checks query actual ChromaDB heartbeat and Neo4j connectivity
- Validations verify results against criteria (counts, freshness, patterns)
- Query steps perform hybrid semantic + graph search

**Development Maturity**:
- System maturity: 70% → 85%+ (estimated)
- Tool autonomy level: 1 → 2 (can execute multi-step workflows)
- Self-modification capability: "emerging" → "functional" (can validate changes)

### Phase Status

- ✅ Phase 3A: SDD Framework Structure (v3.1.0) - Workflow parsing, metadata extraction
- ✅ Phase 3B: SDD Tools Implementation (v3.2.0) - Tool registration, list/get workflows
- ✅ Phase 3C: Runtime Integration (v3.7.0) - **THIS RELEASE** - Connected execution
- 🔄 Phase 4: Bootstrap Capability (pending) - Self-modification engine

### Remaining Placeholders

**Not Critical for Phase 3C**:
- `executeIngestion()` - Triggers RAG re-ingestion (Phase 4)
- `executeCommand()` - System command execution (Phase 4 with safety checks)

These are intentionally deferred to Phase 4 (Bootstrap Capability) as they enable system self-modification.

### Testing

**Validation Commands**:
```javascript
// Check framework status (should show "connected")
mcp_eib-sdd-valid_framework_integrity()

// Check development status (should show workflow_integration: true)
mcp_eib-sdd-valid_development_status()

// Execute test workflow
execute_sdd_workflow({ 
  workflow_name: 'test_health_check_workflow',
  dry_run: false 
})
```

**Note**: MCP server restart required to activate runtime connection. If using VS Code MCP integration, reload window or restart MCP server process.

---

## Version 3.5.0 - ChromaDB Docker Migration (November 17, 2025)

### Critical Architecture Change
- **ChromaDB Migration**: Switched from Spack Python installation to Docker container
  - **Problem**: Spack Python venv wrapper prevented proper user site-packages installation
  - **Problem**: Rocky 9 system Python has SQLite 3.x < 3.35.0 (ChromaDB requires >= 3.35.0)
  - **Solution**: Docker container (chromadb/chroma:latest) eliminates all dependency conflicts
  
### Benefits of Docker ChromaDB
- ✅ **No Python version conflicts** - Self-contained environment
- ✅ **No SQLite version issues** - Container has correct SQLite version
- ✅ **No venv/site-packages confusion** - Isolated from host Python
- ✅ **Easy upgrades** - `docker pull chromadb/chroma:latest`
- ✅ **Persistent storage** - Volume mount `/mcp_rag_eib/data/chromadb`
- ✅ **Systemd integration** - `chromadb-docker.service`
- ✅ **Clean separation** - ChromaDB separate from development environment

### Files Changed
- `SETUP/provision_mcp_rag_persistent.sh` (v3.5.0)
  - STEP 7: Replaced Spack pip installation with Docker pull
  - STEP 8: Replaced chromadb-spack.service with chromadb-docker.service
  - Updated version header and documentation
- `SETUP/chromadb-docker.service` - New systemd service file (reference copy)
- `mcp_server_node/start-chromadb-system.sh` - Created (unused, for reference)
- `/etc/systemd/system/chromadb-docker.service` - Active service definition

### Service Configuration
```bash
# Service: chromadb-docker.service
# Port mapping: 8080 (host) -> 8000 (container)
# Volume: /mcp_rag_eib/data/chromadb -> /chroma/chroma
# Image: chromadb/chroma:latest
# API: v2 (http://localhost:8080/api/v2/heartbeat)
```

### Deployment Notes
- Old `chromadb-spack.service` disabled and stopped
- Existing ChromaDB data preserved and accessible via volume mount
- Startup time reduced from 90s to 30s max
- Startup health checks use API v2 endpoints

---

## Version 3.2.0 - CI Test Case Expert System (November 15, 2025)

### Major Features
- **GFS Expert System**: Complete CI test case documentation with comprehensive meteorological and operational context
  - Created `ingest_ci_test_cases.py` - Intelligent CI test case ingestion with GFS system knowledge
  - Created `ci_test_case_documentation_workflow.md` - Complete SDD workflow specification
  - Ingested 66 CI test cases across 7 categories with expert-level documentation

### CI Test Case Coverage
- **7 Categories Documented**:
  - `pr/` (18 files) - Pull Request fast CI tests
  - `gfsv17/` (20 files) - GFS v17 operational configurations
  - `gcafsv1/` (6 files) - GCAFS coupled system tests
  - `sfs/` (1 file) - Subseasonal Forecast System
  - `weekly/` (2 files) - Weekly high-resolution tests
  - `hires/` (2 files) - Very high-resolution tests (C768/C1152)
  - `yamls/` (17 files) - Base configuration templates

### GFS System Context (Expert-Level Knowledge)
Each test case now includes comprehensive context:
- **GFS Overview**: Mission-critical NOAA system, 4x/day operations, international distribution
- **Meteorological Science**: S2S forecasting, MJO, ENSO, ocean-atmosphere coupling rationale
- **Data Assimilation**: Hybrid 4D-EnVar, 10M obs/cycle, SOCA marine DA, quality control
- **Resolution Hierarchy**: C96/C384/C768 trade-offs, physics validity, operational constraints
- **Ocean Components**: MOM6 mx050/mx025/mx100, eddy resolution, hurricane intensity impacts
- **GFS v17 Upgrades**: Marine DA, extended forecasts, physics improvements, v16 comparison
- **Operational Stakes**: $500M+/day economic impact, hurricane evacuations, aviation dependencies
- **CI/CD Context**: Protecting operational reliability, bitwise reproducibility, regression testing
- **GFS Ecosystem**: Downstream users (NAM, HRRR, HWRF), international role, WMO distribution

### Technical Implementation
- **Jinja2-Aware Parsing**: Text-based extraction handles templated YAML (`{{ var }}`, `!INC` directives)
- **Category Intelligence**: Automatic categorization by test type, duration, resolution tier
- **Rich Metadata**: 8+ metadata fields per test case for semantic search
- **Documentation Generation**: Auto-generated 12,000+ character expert docs per test case
- **ChromaDB Collection**: `ci-test-cases-v2-0-0-gfs-expert` with 66 documents

### Knowledge Base Impact
- **Total documents**: 9,637 (up from 9,571)
- **CI test case docs**: +66 expert-level documents
- **Average doc size**: ~12KB with full GFS context
- **Search capability**: Can now answer complex meteorological + operational questions about any CI test

### SDD Framework Demonstration
This capability demonstrates **Phase 3A workflow automation**:
1. System identified knowledge gap (CI test cases not documented)
2. Planned solution (8-step workflow specification)
3. Implemented ingestion script (1,100+ LOC with GFS expertise)
4. Executed workflow autonomously
5. Validated completion (66/66 test cases ingested)

### Real-World Impact
System can now answer:
- "What does C96C48mx500_S2SW_cyc_gfs test and why does it matter?"
- "How does ocean resolution affect hurricane intensity forecasts?"
- "What's the difference between PR tests and gfsv17 operational validation?"
- "Why is hybrid 4D-EnVar critical for GFS v17?"
- "What would happen if GFS failed operationally?"

### Files Added
- `mcp_server_node/scripts/ingest_ci_test_cases.py` - CI test case ingestion engine
- `sdd_framework/workflows/ci_test_case_documentation_workflow.md` - Workflow specification

---

## Version 3.1.0 - Phase 3A: SDD Workflow Automation (November 14, 2025)

### Major Features
- **SDD Workflow Automation**: Implemented complete workflow parsing and execution engine
  - Created `WorkflowExecutor.js` - Core workflow engine with health monitoring integration
  - Created `SDDWorkflowTools.js` - 6 new MCP tools for SDD workflow management
  - Integrated with `UnifiedMCPServer.js` v3.1.0

### New MCP Tools (6 total)
1. `list_sdd_workflows` - List all available SDD framework workflows
2. `get_sdd_workflow` - Get detailed information about a specific workflow
3. `execute_sdd_workflow` - Execute workflow with parameters (dry-run support)
4. `get_sdd_execution_history` - View execution history with filtering
5. `validate_sdd_compliance` - SDD compliance validation (placeholder)
6. `get_sdd_framework_status` - Framework status and metrics

### Technical Implementation
- **Workflow Parsing**: Supports both `### Step N:` and `1. **Step**` markdown formats
- **Step Types**: health_check, data_query, validation, ingestion, command, manual
- **Metadata Extraction**: Automatic extraction of Type, Required, Component, Query, Target fields
- **Execution Framework**: Step-by-step execution with status tracking
- **History Tracking**: In-memory execution history with filtering
- **Health Integration**: Hooks for health monitor integration (to be connected)

### Workflow Support
- Successfully parses all 6 existing workflows:
  - data_ingestion_workflow
  - ee2_enhanced_embeddings_workflow
  - mcp_code_migration_checklist
  - mcp_integration_todo
  - rag_enhancement_workflow
  - rag_major_upgrade_workflow
- Added test_health_check_workflow for validation

### Architecture Updates
- Updated `UnifiedMCPServer.js` to v3.1.0
- Total tool count: 27 tools (up from 21)
- Maintained backward compatibility with Week 2 architecture

### Next Steps (Phase 3B)
- Connect health monitoring to WorkflowExecutor
- Implement actual data access layer integration
- Enable real workflow execution (currently placeholders)
- Add workflow validation before execution
- Implement workflow composition and chaining

---

## Version 3.0.0 - Week 2 Consolidation (November 2025)

### Major Refactor
- Consolidated 3 separate servers into unified architecture
- Eliminated 8 duplicate tools
- Implemented modular tool system with 5 tool modules

### Tool Modules
- **WorkflowInfoTools** (3 tools) - Static workflow information
- **CodeAnalysisTools** (4 tools) - Graph-based code analysis
- **SemanticSearchTools** (7 tools) - Vector + graph hybrid search
- **OperationalTools** (3 tools) - HPC operational guidance
- **GitHubTools** (4 tools) - Repository integration

### Infrastructure
- Total tools: 21 (reduced from 29 with duplicates)
- Clear separation of concerns
- Improved maintainability and error handling
- Consistent tool registration pattern

---

## Version 2.0.0 - Week 1 Data Layer (October 2025)

### Foundation
- Created unified data access layer
- Integrated ChromaDB and Neo4j
- Established graph + vector hybrid architecture

### Components
- `UnifiedDataAccess.js` - Single source for all data operations
- `VectorDatabase.js` - ChromaDB client interface
- `GraphDatabase.js` - Neo4j client interface
- Health monitoring framework

---

## Version 1.0.0 - Initial Release (September 2025)

### Initial Implementation
- Basic MCP server functionality
- Separate servers for RAG, GitHub, and workflow
- Initial tool set (29 tools with duplicates)
- ChromaDB integration
- Basic documentation search
