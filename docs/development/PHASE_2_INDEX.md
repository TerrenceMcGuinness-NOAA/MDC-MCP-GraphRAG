# Phase 2 Documentation Index

**Phase**: 2 - Source Annotation (EE2 Error Handling)  
**Status**: ✅ Complete - Pending SME Review  
**Date**: November 19, 2025

---

## Quick Start

**If you're an SME reviewer**, start here:
1. Read [`PHASE_2_SUMMARY.md`](PHASE_2_SUMMARY.md) (8.9KB) - Executive overview
2. Review [`ee2_error_handling_sme_corrections.rst`](../../sdd_framework/phase2_annotations/ee2_error_handling_sme_corrections.rst) (18KB) - Primary annotations
3. Check evidence citations against EE2 standards.rst lines 588-595, 868-985

**If you're implementing Phase 3**, start here:
1. Read [`mcp_rst_enhanced_directives_phase2.md`](../../sdd_framework/templates/mcp_rst_enhanced_directives_phase2.md) (15KB) - Directive specs
2. Review [`PHASE_2_TESTING_PROTOCOL.md`](PHASE_2_TESTING_PROTOCOL.md) (12KB) - Test queries
3. Follow [`PHASE_2_ANNOTATION_TRACKER.md`](PHASE_2_ANNOTATION_TRACKER.md) (8.8KB) - Next steps

---

## Document Hierarchy

### Primary Documents (Must Read)

1. **[PHASE_2_SUMMARY.md](PHASE_2_SUMMARY.md)** (8.9KB)
   - Executive summary
   - What was created today
   - Expected impact metrics
   - SME review questions
   - **Best for**: Quick overview, management briefing

2. **[ee2_error_handling_sme_corrections.rst](../../sdd_framework/phase2_annotations/ee2_error_handling_sme_corrections.rst)** (18KB)
   - Primary annotation document
   - 10 MCP directives (2 corrections, 3 anti-patterns, 2 correct-patterns, 3 rules)
   - Evidence with EE2 line numbers
   - SME sign-off block
   - **Best for**: Technical implementation, SME review

---

### Implementation Guides

3. **[mcp_rst_enhanced_directives_phase2.md](../../sdd_framework/templates/mcp_rst_enhanced_directives_phase2.md)** (15KB)
   - Complete directive catalog (9 types)
   - Parser requirements
   - Embedding strategy
   - Validation rules
   - **Best for**: Ingestion script developers

4. **[PHASE_2_TESTING_PROTOCOL.md](PHASE_2_TESTING_PROTOCOL.md)** (12KB)
   - 5 test queries with before/after
   - Expected behavior changes
   - Validation metrics
   - SME validation questions
   - **Best for**: Testing and validation

---

### Project Management

5. **[PHASE_2_ANNOTATION_TRACKER.md](PHASE_2_ANNOTATION_TRACKER.md)** (8.8KB)
   - Status tracking
   - False positive metrics
   - SME review schedule
   - Success criteria checklist
   - **Best for**: Project tracking, status updates

6. **[PHASE_2_COMPLETION_REPORT.md](PHASE_2_COMPLETION_REPORT.md)** (18KB)
   - Comprehensive completion summary
   - Technical achievements
   - Quality metrics
   - Risk assessment
   - Files inventory
   - **Best for**: Final review, archival record

---

### Visual Aids

7. **[PHASE_2_WORKFLOW_DIAGRAM.md](PHASE_2_WORKFLOW_DIAGRAM.md)** (28KB)
   - ASCII workflow visualization
   - Step-by-step process
   - Current status indicators
   - Phase 3 preview
   - **Best for**: Understanding process flow

---

## Key Findings Summary

### Issue #1: `set -eu` False Positives
- **Problem**: AI recommends `set -eu` but EE2 only requires `set -x`
- **Evidence**: standards.rst lines 588-595, 873, 950
- **Impact**: ~80% of EVS scripts flagged incorrectly
- **Solution**: `mcp:anti_pattern` directive prohibiting `set -e`/`set -eu`

### Issue #2: Forced Exit False Positives
- **Problem**: AI recommends `exit 0`/`exit 1` but NCO SPAs prohibit this
- **Evidence**: standards.rst lines 187-195, NCO historical guidance
- **Impact**: ~60% of EVS scripts flagged incorrectly
- **Solution**: `mcp:anti_pattern` directive with NCO SPA justification

### Expected Impact
- Overall false positive reduction: **~55%** (70% → <15%)
- `set -eu` warnings: 80% → <5% (**75% reduction**)
- Forced exit warnings: 60% → <10% (**50% reduction**)

---

## Critical Paths

### For SME Review (Target: Nov 22, 2025)

**Path 1: Quick Review** (30 minutes)
```
PHASE_2_SUMMARY.md
    ↓
ee2_error_handling_sme_corrections.rst (sections 1-3 only)
    ↓
Sign-off decision
```

**Path 2: Detailed Review** (2 hours)
```
PHASE_2_SUMMARY.md
    ↓
ee2_error_handling_sme_corrections.rst (complete)
    ↓
PHASE_2_TESTING_PROTOCOL.md (test queries)
    ↓
Verify EE2 citations in standards.rst
    ↓
Sign-off with feedback
```

---

### For Phase 3 Implementation

**Path 1: Ingestion Script Development**
```
mcp_rst_enhanced_directives_phase2.md (directive specs)
    ↓
ee2_error_handling_sme_corrections.rst (example annotations)
    ↓
Implement parser enhancements
    ↓
Unit test each directive type
    ↓
Run enhanced ingestion
```

**Path 2: Validation Testing**
```
PHASE_2_TESTING_PROTOCOL.md (test cases)
    ↓
Run 5 test queries
    ↓
Measure false positive rate
    ↓
Document improvements
    ↓
Update PHASE_2_ANNOTATION_TRACKER.md
```

---

## Files by Role

### SME Reviewers Need:
- ✅ PHASE_2_SUMMARY.md (overview)
- ✅ ee2_error_handling_sme_corrections.rst (annotations)
- ✅ EE2 standards.rst (for citation verification)
- ⚠️ Optional: PHASE_2_TESTING_PROTOCOL.md (test cases)

### Ingestion Script Developers Need:
- ✅ mcp_rst_enhanced_directives_phase2.md (parser specs)
- ✅ ee2_error_handling_sme_corrections.rst (example)
- ✅ PHASE_2_TESTING_PROTOCOL.md (validation)
- ⚠️ Optional: PHASE_2_WORKFLOW_DIAGRAM.md (context)

### Project Managers Need:
- ✅ PHASE_2_ANNOTATION_TRACKER.md (status)
- ✅ PHASE_2_COMPLETION_REPORT.md (metrics)
- ✅ PHASE_2_SUMMARY.md (executive brief)
- ⚠️ Optional: PHASE_2_WORKFLOW_DIAGRAM.md (visual)

### Future Developers Need:
- ✅ PHASE_2_COMPLETION_REPORT.md (complete record)
- ✅ PHASE_2_WORKFLOW_DIAGRAM.md (process)
- ✅ mcp_rst_enhanced_directives_phase2.md (technical ref)
- ✅ CHANGELOG.md (version history)

---

## Directive Reference Quick Links

### New Directives (Phase 2)
- `mcp:sme_correction` - Documents false positives
- `mcp:anti_pattern` - Marks prohibited patterns
- `mcp:correct_pattern` - Shows alternatives
- `mcp:context_types` - Defines script contexts
- `mcp:ai_guidance_rule` - Machine-readable rules

### Existing Directives (Phase 1)
- `mcp:compliance` - Marks compliance sections
- `mcp:intent` - Describes requirement purpose
- `mcp:example` - Provides code examples
- `mcp:see-also` - Cross-references

Full catalog: [mcp_rst_enhanced_directives_phase2.md](../../sdd_framework/templates/mcp_rst_enhanced_directives_phase2.md)

---

## Evidence Citations Index

All EE2 citations in `ee2_error_handling_sme_corrections.rst`:

| Line Numbers | Content | Purpose |
|--------------|---------|---------|
| 588-595 | "Enable debug logging...set -x" | Proves only set -x required |
| 868-919 | J-job Example 8 | Shows NO set -e in production |
| 926-985 | ex-script Example 9 | Shows NO set -e in production |
| 187-195 | "err_chk / err_exit" | Proves only utilities documented |
| 912 | "export err=$?; err_chk" | Example of correct pattern |
| 978 | "err_exit 'message'" | Example of correct pattern |

Verify all citations in: `supported_repos/nws-hpc-standards/docs/standards.rst`

---

## Status Dashboard

```
Phase 2 Status: ✅ COMPLETE
├─ Annotations: ✅ Done (18KB RST)
├─ Documentation: ✅ Done (~90KB total)
├─ Testing Protocol: ✅ Done (5 test cases)
├─ SME Review: ⏳ Pending (target: Nov 22)
├─ Phase 3 Prep: ⏳ Ready (specs complete)
└─ Validation: ⏳ Pending Phase 3

Expected Impact:
├─ False Positives: 70% → <15%
├─ set -eu warnings: 80% → <5%
└─ exit warnings: 60% → <10%

Next Milestone: SME Sign-Off
Target Date: November 22, 2025
Blockers: None
```

---

## Contact & Sign-Off

**SME Review Sign-Off Required**:
- [ ] EVS Development Team Lead
- [ ] NCO SPA (Site Preparation Analyst)
- [ ] EIB Operations Representative
- [ ] EMC Global Workflow Maintainers

**Questions?** See [PHASE_2_SUMMARY.md](PHASE_2_SUMMARY.md) Q&A section

**Ready to Proceed?** Follow [PHASE_2_ANNOTATION_TRACKER.md](PHASE_2_ANNOTATION_TRACKER.md) next steps

---

**Last Updated**: November 19, 2025  
**Phase**: 2 - Source Annotation  
**Total Documentation**: ~90KB across 7 files
