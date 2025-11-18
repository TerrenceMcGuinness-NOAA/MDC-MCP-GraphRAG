# EVS EE2 Compliance Remediation Plan
**Project Planning Document**

**Date**: November 18, 2025  
**Repository**: NOAA-EMC/EVS (Environmental Verification System)  
**Branch**: `release/evs.v2.0.0`  
**Status**: Planning Phase  
**Project Lead**: [TBD]

---

## Executive Summary

### Problem Statement

The EVS repository requires **systematic remediation of 670 files (97.2% of operational code)** to meet NCEP Central Operations EE2 compliance standards for production deployment on WCOSS2.

**Critical Issues Identified**:
- **225 files (33%)** lack error handling (set -e, set -u, trap handlers)
- **631 files (92%)** contain unquoted environment variables
- **Overall compliance: 2.8%** (only 19 of 689 files compliant)

### Solution Approach

**4-Phase Systematic Remediation**:
1. **Phase 1 (Weeks 1-3)**: Fix 32 critical path scripts (P0 priority)
2. **Phase 2 (Weeks 4-6)**: Fix 95 secondary component scripts (P1 priority)
3. **Phase 3 (Weeks 7-10)**: Fix remaining 562 scripts using automation
4. **Phase 4 (Weeks 11-12)**: Final validation and production cutover

**Estimated Effort**: 462 total hours (5.25 FTE-months) over 13 weeks

### Business Impact

**Risks of Non-Compliance**:
- Silent failures propagate through operational workflows
- Path corruption from unquoted variables causes unpredictable behavior
- Debugging failures takes 10x longer without proper error handling
- Production deployment blocked by NCEP Central Operations

**Benefits of Remediation**:
- Meets WCOSS2 production deployment requirements
- Reduces mean-time-to-detection for failures from hours to <5 minutes
- Enables automated monitoring and alerting
- Improves code maintainability and developer productivity
- Establishes CI/CD enforcement to prevent future regressions

---

## Project Organization

### Team Structure

| Role | FTE | Duration | Key Responsibilities |
|------|-----|----------|---------------------|
| **Lead Developer** | 0.5 | 12 weeks | Architecture, code review, stakeholder communication |
| **Developer A** | 1.0 | 12 weeks | P0 scripts: mesoscale, RTOFS, NWPS |
| **Developer B** | 1.0 | 12 weeks | P0 scripts: global_det, subseasonal |
| **Developer C** | 1.0 | 8 weeks | P1 scripts: global_ens, global_chem |
| **Developer D** | 1.0 | 8 weeks | P1 scripts: NFCENS, GLWU |
| **Developer E** | 1.0 | 8 weeks | P1 scripts: AQM, CAM |
| **QA Tester** | 0.5 | 12 weeks | Test development, regression validation |
| **Tech Writer** | 0.25 | 4 weeks | Documentation updates, training materials |

**Total**: 5.25 FTE-months

### Communication Plan

- **Daily**: Stand-up meetings (developers)
- **Weekly**: Progress reviews with project lead
- **Bi-weekly**: Stakeholder status reports
- **Monthly**: NCEP operations coordination meetings

### Resource Requirements

**Computing**:
- Dedicated test system for parallel testing
- 5TB storage for regression test outputs
- GitHub Actions runners for CI/CD

**Tools**:
- Automated compliance scanner (MCP RAG tools)
- Error handling insertion scripts
- Variable quoting automation scripts
- Regression test framework

---

## Phase 1: Critical Path Scripts (Weeks 1-3)

### Overview

**Target**: 32 highest-priority scripts  
**Duration**: 3 weeks  
**Effort**: 128 hours  
**Priority**: P0 (Production Critical)

### Component Breakdown

#### Mesoscale (6 files) - Developer A
**Criticality**: CONUS forecasts - mission critical

Scripts:
- `exevs_stats_mesoscale_rap_snowfall.sh` (24 unquoted variables)
- `exevs_stats_mesoscale_rap_precip.sh`
- `exevs_stats_mesoscale_rap_grid2obs.sh`
- `exevs_stats_mesoscale_nam_snowfall.sh`
- `exevs_stats_mesoscale_nam_precip.sh`
- `exevs_stats_mesoscale_nam_grid2obs.sh`

**Issues**: Missing error handling, extensive unquoted variables

#### Global Deterministic (4 files) - Developer B
**Criticality**: GFS operational backbone

Scripts:
- `exevs_stats_global_det_wave_grid2obs.sh`
- `exevs_stats_global_det_atmos_wmo.sh`
- `exevs_stats_global_det_atmos_grid2obs.sh`
- `exevs_stats_global_det_atmos_grid2grid.sh` (12 unquoted variables)

**Issues**: No input validation, missing trap handlers

#### RTOFS (2 files) - Developer A
**Criticality**: Ocean forecasts - high visibility

Scripts:
- `exevs_stats_rtofs_grid2obs.sh` (69 unquoted variables)
- `exevs_stats_rtofs_grid2grid.sh` (82 unquoted variables - **worst in repo**)

**Issues**: Severe variable quoting problems, no input data validation

#### Subseasonal (2 files) - Developer B
**Criticality**: Extended forecasts - climate operations

Scripts:
- `exevs_stats_subseasonal_grid2obs.sh` (29 unquoted variables)
- `exevs_stats_subseasonal_grid2grid.sh` (28 unquoted variables)

**Issues**: Path construction without quotes causes failures on edge cases

#### NWPS (1 file) - Developer A
**Criticality**: Coastal wave forecasts - public safety

Scripts:
- `exevs_nwps_wave_grid2obs_stats.sh` (13 unquoted variables)

**Issues**: No error handling, no input validation

### Tasks & Acceptance Criteria

| Task | Description | Acceptance Criteria |
|------|-------------|-------------------|
| **Add Error Handling** | Insert `set -eu`, `set -o pipefail`, trap handlers | All scripts exit on error; cleanup handlers present |
| **Quote Variables** | Convert all `$VAR` to `"${VAR}"` | All environment variables quoted; intentional globs reviewed |
| **Input Validation** | Check file/directory existence before processing | Scripts fail fast with clear error messages if inputs missing |
| **Unit Testing** | Create tests for error conditions | Tests pass for undefined vars, missing files, permission errors |
| **Regression Testing** | Run on 30 days operational data | Output matches baseline exactly; performance <5% degradation |

### Deliverables

- ✅ 32 P0 scripts fully EE2 compliant
- ✅ Unit test suite for P0 scripts (100% coverage of error paths)
- ✅ Regression test results (pass/fail report with output comparison)
- ✅ Code review documentation (approved by lead developer)
- ✅ Performance benchmark results (baseline vs fixed)

### Week-by-Week Plan

**Week 1**: Mesoscale + Global Det (10 files)
- Days 1-2: Add error handling
- Days 3-4: Quote variables, add validation
- Day 5: Unit tests

**Week 2**: RTOFS + Subseasonal + NWPS (5 files)
- Days 1-2: RTOFS (complex due to 82 unquoted vars)
- Day 3: Subseasonal
- Day 4: NWPS + unit tests
- Day 5: Buffer for issues

**Week 3**: Testing & Documentation
- Days 1-3: Regression testing on 30 days data
- Days 4-5: Code review, performance benchmarking

---

## Phase 2: Secondary Components (Weeks 4-6)

### Overview

**Target**: 95 scripts  
**Duration**: 3 weeks  
**Effort**: 114 hours  
**Priority**: P1 (Important but Non-Critical)

### Component Assignments

| Component | Files | Developer | Criticality |
|-----------|-------|-----------|------------|
| Global Ensemble (GEFS) | 15 | Developer C | Ensemble forecasts |
| Global Chemistry | 10 | Developer C | Atmospheric chemistry |
| NFCENS (Navy) | 10 | Developer D | Navy ensemble |
| GLWU (Great Lakes) | 10 | Developer D | Great Lakes waves |
| AQM (Air Quality) | 25 | Developer E | Air quality modeling |
| CAM (Convection) | 25 | Developer E | High-resolution convection |

### Key Milestones

- **Week 4**: Global Ensemble + Global Chemistry (25 files)
- **Week 5**: NFCENS + GLWU (20 files)
- **Week 6**: AQM + CAM (50 files)

### New Activities

#### Automated Testing Framework
- Create test data generator for synthetic inputs
- Build test harness for batch execution
- Implement automated regression comparison tools

#### CI/CD Integration
- Add pre-commit hooks for compliance checks
- Configure GitHub Actions for PR validation
- Set up automated linting (shellcheck, pycodestyle)

### Deliverables

- ✅ 95 P1 scripts fully compliant
- ✅ Automated testing framework operational
- ✅ CI/CD pipeline configured and tested
- ✅ Compliance dashboard (real-time monitoring)

---

## Phase 3: Remaining Scripts (Weeks 7-10)

### Overview

**Target**: 562 scripts  
**Duration**: 4 weeks  
**Effort**: 144 hours  
**Priority**: P2 (Bulk Remediation)

### Automation Strategy

This phase leverages automated tools developed in Phases 1-2 to accelerate bulk processing:

1. **Automated Error Handling Insertion** (`tools/add_error_handling.sh`)
   - Scans all scripts for missing `set -e`
   - Inserts error handling after shebang
   - Creates backups for rollback

2. **Automated Variable Quoting** (`tools/quote_variables.sh`)
   - Converts `$VAR` to `"${VAR}"` for common patterns
   - Handles `cd`, `mkdir`, `export` statements
   - Flags complex cases for manual review

3. **Manual Review Process**
   - Review all automated changes via diff reports
   - Handle intentional glob expansions (keep unquoted if needed)
   - Fix complex variable substitutions

### Week-by-Week Plan

**Week 7**: Automated fixes (200 files)
- Run bulk error handling insertion
- Run bulk variable quoting
- Generate diff reports for review

**Week 8**: Manual review (200 files)
- Review automated changes
- Fix edge cases
- Commit batches after validation

**Week 9**: Remaining files + testing (162 files)
- Complete remaining scripts
- Run full regression suite on 90 days data
- Document discrepancies

**Week 10**: Documentation & polish
- Update developer guidelines
- Create compliance checklist
- Document common patterns and solutions

### Deliverables

- ✅ 562 remaining scripts compliant
- ✅ Automated tool suite documented and maintained
- ✅ Comprehensive regression test results (90 days data)
- ✅ Updated developer documentation and training materials

---

## Phase 4: Validation & Documentation (Weeks 11-12)

### Overview

**Duration**: 2 weeks  
**Effort**: 76 hours  
**Priority**: P0 (Production Readiness)

### Validation Activities

#### Full System Integration Testing
- Run complete EVS workflow with all fixed scripts
- Test on multiple HPC platforms:
  - Hera (development)
  - Hercules (testing)
  - WCOSS2 (production target)
- Validate end-to-end output accuracy
- Performance benchmarking across all components

#### Operational Readiness Review
- Code review by NCEP Central Operations
- Security review (if required by policy)
- Documentation completeness review
- Training session for operations staff

### Compliance Enforcement

#### CI/CD Enforcement Mechanisms
- Finalize pre-commit hooks (block non-compliant commits)
- Configure GitHub Actions for PR checks (automated validation)
- Deploy compliance dashboard (real-time monitoring)
- Document enforcement procedures for team

### Production Cutover Plan

#### Week 11 Activities
- Integration testing on all platforms
- Operational readiness review
- Create rollback plan
- Schedule parallel operations window

#### Week 12 Activities
- Final documentation review
- Stakeholder sign-off
- Production cutover checklist
- Post-deployment monitoring plan

#### Week 13 (Production Deployment)
- **Days 1-3**: Parallel operations (old + new code running simultaneously)
- **Day 4**: Production cutover (switch to new code)
- **Day 5**: Post-deployment monitoring and stabilization

### Deliverables

- ✅ Full integration test report (all platforms)
- ✅ Operational readiness certification (NCEP sign-off)
- ✅ Compliance enforcement framework (CI/CD operational)
- ✅ Complete documentation package (user guides, training)
- ✅ Production cutover plan (approved by operations)

---

## Risk Management

### High-Priority Risks

#### Risk #1: Breaking Changes in Production
- **Probability**: Medium
- **Impact**: High (service disruption)
- **Mitigation**:
  - Comprehensive regression testing (30-90 days operational data)
  - Parallel operations during cutover (3-day overlap)
  - Immediate rollback capability (< 30 minutes)
  - 24/7 on-call support during cutover week

#### Risk #2: Resource Constraints
- **Probability**: Medium
- **Impact**: High (schedule delay)
- **Mitigation**:
  - Phased approach allows flexibility in staffing
  - Automated tools reduce manual effort by 40%
  - Cross-training team members for redundancy
  - 2-week buffer built into timeline

#### Risk #3: Schedule Slippage
- **Probability**: Medium
- **Impact**: Medium (delayed production readiness)
- **Mitigation**:
  - Weekly progress reviews to identify blockers early
  - Automated tools accelerate Phase 3
  - Dedicated QA resource for parallel testing
  - Escalation process for critical issues

### Medium-Priority Risks

#### Risk #4: Unexpected Edge Cases
- **Probability**: Medium
- **Impact**: Low (requires manual fixes)
- **Mitigation**:
  - Manual review of all automated changes
  - Incremental rollout by component
  - Comprehensive unit tests for error conditions

#### Risk #5: Insufficient Test Coverage
- **Probability**: Low
- **Impact**: Medium (undetected regressions)
- **Mitigation**:
  - 90 days operational data for regression tests
  - Unit tests for all error paths
  - Integration tests on all HPC platforms

---

## Success Metrics & KPIs

### Code Quality Metrics

| Metric | Baseline | Target | Status | Measurement Method |
|--------|----------|--------|--------|-------------------|
| **Scripts with set -e** | 33% (228/689) | 100% (689/689) | 🔴 Planning | Automated scan |
| **Quoted variables** | 10% (69/689) | 100% (689/689) | 🔴 Planning | Automated scan |
| **Input validation** | <5% (34/689) | 100% (689/689) | 🔴 Planning | Code review |
| **Error messages** | Sparse | All failures | 🔴 Planning | Code review |
| **Overall compliance** | **2.8%** (19/689) | **100%** (689/689) | 🔴 Planning | Compliance report |

### Operational Metrics

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| **Silent failures** | 0 | Production monitoring (30 days post-deployment) |
| **Mean time to detection** | <5 minutes | Log analysis and alerting |
| **False positives** | <1% | Operations feedback |
| **Output accuracy** | 100% match | Regression test comparison |
| **Performance impact** | <5% degradation | Benchmark tests |

### Project Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| **On-time delivery** | Week 12 | Week 0 | 🟢 On track (planning) |
| **Budget adherence** | 100% | N/A | 🟢 Not started |
| **Team capacity** | 5.25 FTE-months | TBD | 🟡 Needs staffing |
| **Code review coverage** | 100% | 0% | 🔴 Planning |

---

## Timeline & Milestones

### Gantt Chart (Text Format)

```
Week  | Phase | Milestone                        | Owner
------|-------|----------------------------------|-------------
1-3   | P1    | P0 Critical Path Complete        | Dev A, B
      |       | - 32 scripts code-complete       |
      |       | - Unit tests passing             |
      |       | - Regression tests (30 days)     |
------|-------|----------------------------------|-------------
4-6   | P2    | P1 Secondary Complete            | Dev C, D, E
      |       | - 95 scripts code-complete       |
      |       | - Automated testing framework    |
      |       | - CI/CD integration              |
------|-------|----------------------------------|-------------
7-10  | P3    | All Scripts Remediated           | All devs
      |       | - 562 remaining scripts          |
      |       | - Full regression suite (90d)    |
      |       | - Documentation updated          |
------|-------|----------------------------------|-------------
11-12 | P4    | Ready for Production             | Lead + QA
      |       | - Integration tests complete     |
      |       | - NCEP operations approval       |
      |       | - Cutover plan approved          |
------|-------|----------------------------------|-------------
13    | Deploy| Production Cutover               | Operations
      |       | - Parallel operations (3 days)   |
      |       | - Production switch              |
      |       | - Post-deployment monitoring     |
```

### Critical Path

**Week 3**: P0 scripts complete → **Week 6**: P1 scripts complete → **Week 10**: All scripts complete → **Week 12**: Production ready → **Week 13**: Deploy

**Total Duration**: 13 weeks (including 1 week production cutover)

---

## Budget Estimate

### Personnel Costs

| Role | FTE | Duration | Rate* | Cost |
|------|-----|----------|-------|------|
| Lead Developer | 0.5 | 12 weeks | $X/hr | $Y |
| Developer A | 1.0 | 12 weeks | $X/hr | $Y |
| Developer B | 1.0 | 12 weeks | $X/hr | $Y |
| Developer C | 1.0 | 8 weeks | $X/hr | $Y |
| Developer D | 1.0 | 8 weeks | $X/hr | $Y |
| Developer E | 1.0 | 8 weeks | $X/hr | $Y |
| QA Tester | 0.5 | 12 weeks | $X/hr | $Y |
| Tech Writer | 0.25 | 4 weeks | $X/hr | $Y |

*Rates to be determined based on organizational pay scales

### Computing Costs

- Test system allocation: $TBD
- Storage (5TB): $TBD
- GitHub Actions runners: $TBD (or use organizational allocation)

### Total Estimated Budget

**Personnel**: $TBD  
**Computing**: $TBD  
**Total**: $TBD

---

## Next Steps

### Immediate Actions (Week 0)

1. **Stakeholder Approval**
   - Present plan to NCEP management
   - Obtain budget approval
   - Secure personnel commitments

2. **Team Formation**
   - Assign developer roles
   - Schedule kickoff meeting
   - Set up communication channels (Slack, email lists)

3. **Infrastructure Setup**
   - Provision test systems
   - Configure GitHub Actions
   - Set up compliance monitoring tools

4. **Kickoff Activities**
   - Review EE2 compliance report with team
   - Train team on EE2 standards
   - Establish coding conventions and review process

### Decision Points

- **Go/No-Go Decision**: End of Week 0 (after stakeholder approval)
- **Phase 1 Review**: End of Week 3 (assess progress, adjust if needed)
- **Phase 2 Review**: End of Week 6 (validate automation approach)
- **Production Readiness Review**: End of Week 12 (NCEP sign-off required)

---

## References & Resources

### Primary Documents

1. **EVS EE2 Compliance Report** (Comprehensive Analysis)
   - URL: https://gist.github.com/TerrenceMcGuinness-NOAA/fae7ea2c59c7ebb5cca40dae09a78959
   - Description: Full analysis of 689 files with code examples and remediation guidance

2. **NCEP WCOSS Implementation Standards (EE2)**
   - URL: https://nws-hpc-standards.readthedocs.io/
   - Description: Official NCEP production standards

3. **SDD Framework Workflow**
   - Location: `sdd_framework/workflows/evs_ee2_compliance_remediation.yaml`
   - Description: Machine-readable workflow definition

### Supporting Documents

- Global Workflow EE2 Analysis (for cross-reference)
- RRFS Workflow EE2 Analysis (lessons learned)
- Google Shell Style Guide
- ShellCheck documentation

### Tools & Scripts

- MCP RAG compliance scanner
- Automated error handling insertion script
- Automated variable quoting script
- Regression test framework

---

## Appendix: Sample Remediation

### Before (Non-Compliant)

```bash
#!/bin/bash
# exevs_stats_mesoscale_rap_grid2obs.sh

cd $DATA
mkdir -p $COMOUT
export MODEL=$MODELNAME
python $HOMEevs/scripts/run_stats.py
cp output/*.nc $COMOUT/
```

**Issues**:
- No error handling (script continues on failure)
- 5 unquoted variables (path corruption risk)
- No input validation
- No error messages

### After (Fully Compliant)

```bash
#!/bin/bash
# exevs_stats_mesoscale_rap_grid2obs.sh
#
# PURPOSE: Generate grid2obs statistics for RAP model
# INPUT:   Model forecast files in $COMIN
# OUTPUT:  Statistics in $COMOUT
# RETURNS: 0 on success, 1 on failure

set -eu  # Exit on error, undefined variables
set -o pipefail  # Catch errors in pipes

# Trap handler for cleanup
cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        echo "ERROR: Script failed with exit code $exit_code"
    fi
    [[ -f "${tmp_file:-}" ]] && rm -f "$tmp_file"
    exit $exit_code
}
trap cleanup EXIT INT TERM

# Validate required environment variables
for var in DATA COMOUT HOMEevs MODELNAME; do
    if [[ -z "${!var:-}" ]]; then
        echo "FATAL ERROR: Required variable $var not set"
        exit 1
    fi
done

# Validate directories exist
if [[ ! -d "${DATA}" ]]; then
    echo "FATAL ERROR: Working directory ${DATA} does not exist"
    exit 1
fi

# Change to working directory
cd "${DATA}" || {
    echo "FATAL ERROR: Cannot cd to ${DATA}"
    exit 1
}

# Create output directory
mkdir -p "${COMOUT}" || {
    echo "FATAL ERROR: Cannot create output directory ${COMOUT}"
    exit 1
}

# Set model name
export MODEL="${MODELNAME}"

# Validate Python script exists
if [[ ! -f "${HOMEevs}/scripts/run_stats.py" ]]; then
    echo "FATAL ERROR: Python script not found"
    exit 1
fi

# Run statistics generation
echo "INFO: Running statistics for model ${MODEL}"
if ! python "${HOMEevs}/scripts/run_stats.py"; then
    echo "FATAL ERROR: Statistics generation failed"
    exit 1
fi

# Validate output was created
if [[ ! -d "output" ]] || [[ -z "$(ls -A output/*.nc 2>/dev/null)" ]]; then
    echo "FATAL ERROR: No output files generated"
    exit 1
fi

# Copy output to COM directory
echo "INFO: Copying output to ${COMOUT}"
if ! cp output/*.nc "${COMOUT}/"; then
    echo "FATAL ERROR: Failed to copy output files"
    exit 1
fi

echo "INFO: Successfully completed RAP grid2obs statistics"
exit 0
```

**Improvements**:
- ✅ Error handling: `set -eu`, `set -o pipefail`
- ✅ Trap handler for cleanup
- ✅ All variables quoted
- ✅ Input validation (variables, directories, files)
- ✅ Error messages with context
- ✅ Informational logging
- ✅ Output validation before declaring success

---

**Document Status**: Draft v1.0  
**Last Updated**: November 18, 2025  
**Next Review**: Week 3 (after Phase 1 completion)

---

## Approval Signatures

| Role | Name | Signature | Date |
|------|------|-----------|------|
| **Project Lead** | [TBD] | __________ | ______ |
| **NCEP Manager** | [TBD] | __________ | ______ |
| **Technical Lead** | [TBD] | __________ | ______ |
| **Operations POC** | [TBD] | __________ | ______ |
