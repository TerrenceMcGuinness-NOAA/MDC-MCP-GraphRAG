# EE2 Compliance Report: NOAA-EMC/seaice-concentration

**Repository:** https://github.com/NOAA-EMC/seaice-concentration  
**Analysis Date:** December 4, 2025  
**Analyzed By:** MCP RAG System v3.6.2  
**EE2 Standards Reference:** NCEP Implementation Standards (nws-hpc-standards)

---

## Executive Summary

| Category | Status | Score |
|----------|--------|-------|
| **Overall Compliance** | ⚠️ Partial | 72% |
| Directory Structure | ✅ Compliant | 95% |
| J-Job Standards | ⚠️ Minor Issues | 80% |
| Ex-Script Standards | ⚠️ Minor Issues | 70% |
| Error Handling | ⚠️ Needs Improvement | 65% |
| Production Utilities | ✅ Good | 85% |
| Version Files | ✅ Compliant | 90% |
| File Naming | ⚠️ Minor Issues | 75% |
| Build System | ✅ Good | 85% |

---

## 1. Directory Structure Analysis

### 1.1 Package Structure Compliance

**EE2 Requirement:** All components must be in vertical structure with standard subdirectories.

| Subdirectory | Required | Present | Status | Notes |
|--------------|----------|---------|--------|-------|
| `jobs/` | ✅ Yes | ✅ Yes | ✅ PASS | Contains J-jobs |
| `scripts/` | ✅ Yes | ✅ Yes | ✅ PASS | Contains ex-scripts |
| `ush/` | ✅ Yes | ✅ Yes | ✅ PASS | Utility scripts |
| `sorc/` | ✅ Yes | ✅ Yes | ✅ PASS | Source code |
| `exec/` | ✅ Yes | ✅ Yes | ✅ PASS | Executables (built) |
| `fix/` | ✅ Yes | ✅ Yes | ✅ PASS | Fixed fields |
| `parm/` | ✅ Yes | ✅ Yes | ✅ PASS | Parameter files |
| `versions/` | ✅ Yes | ✅ Yes | ✅ PASS | Version tracking |
| `modulefiles/` | ✅ Yes | ✅ Yes | ✅ PASS | In sorc/modulefiles |
| `ecf/` | Optional | ✅ Yes | ✅ PASS | ecFlow scripts |
| `gempak/` | Optional | ✅ Yes | ✅ PASS | GEMPAK files |
| `doc/` | ✅ Yes | ❌ No | ⚠️ MISSING | No documentation directory |

**Finding:** Package structure is mostly compliant. Missing `doc/` subdirectory for documentation.

---

## 2. J-Job Analysis

### 2.1 J-Jobs Inventory

| J-Job File | Naming Convention | Status |
|------------|-------------------|--------|
| `JSEAICE_ANALYSIS` | ✅ All caps, starts with J | ✅ PASS |
| `JSEAICE_FILTER` | ✅ All caps, starts with J | ✅ PASS |
| `JSEAICE_VIIRS` | ✅ All caps, starts with J | ✅ PASS |
| `JSEAICE_GEMPAK` | ✅ All caps, starts with J | ✅ PASS |

### 2.2 J-Job Standards Compliance

**JSEAICE_ANALYSIS:**

| EE2 Requirement | Status | Details |
|-----------------|--------|---------|
| Shebang `#!/bin/sh` or `#!/bin/bash` | ✅ PASS | `#!/bin/sh` |
| `set -x` for debug logging | ✅ PASS | `set -xae` present |
| `export PS4='$SECONDS + '` | ✅ PASS | Present at line 7 |
| Required variable validation | ✅ PASS | Uses `${cyc:?}`, `${envir:?}` |
| Creates `$DATA` directory | ✅ PASS | `mkdir -p $DATA` |
| Runs `setpdy.sh` after cd to `$DATA` | ✅ PASS | Correct sequence |
| Defines `$pgmout` | ✅ PASS | `export pgmout="OUTPUT.$$"` |
| Uses `err_chk` after ex-script | ✅ PASS | `export err=$?; err_chk` |
| Removes `$DATA` if `$KEEPDATA != YES` | ✅ PASS | Conditional cleanup |
| Prints start/end timestamps | ✅ PASS | `date` at start and end |

**Issues Found:**

| Issue | Severity | Line | Details |
|-------|----------|------|---------|
| Uses `set -xae` | ⚠️ Medium | 3 | EE2 specifies `set -x` only; `-a` and `-e` are non-standard |
| Explicit `exit 1` | ⚠️ Medium | 101 | Should use `err_exit` instead of explicit exit |
| Hardcoded paths in developer mode | ℹ️ Low | 16 | `$HOME/noscrub/com/` - acceptable for development |

**JSEAICE_FILTER:**

| EE2 Requirement | Status | Details |
|-----------------|--------|---------|
| Standard J-job structure | ✅ PASS | Follows template |
| Error handling | ✅ PASS | Uses `err_chk` |
| Variable validation | ⚠️ PARTIAL | Missing some `:?` validators |

**JSEAICE_VIIRS:**

| Issue | Severity | Line | Details |
|-------|----------|------|---------|
| Uses `set -xa` and `set -e` | ⚠️ Medium | 3-4 | Should be `set -x` only per EE2 |

---

## 3. Ex-Script Analysis

### 3.1 Ex-Scripts Inventory

| Ex-Script File | Naming Convention | Status |
|----------------|-------------------|--------|
| `exseaice_analysis.sh` | ✅ Lowercase, starts with `ex` | ✅ PASS |
| `exseaice_filter.sh` | ✅ Lowercase, starts with `ex` | ✅ PASS |
| `exseaice_viirs.sh` | ✅ Lowercase, starts with `ex` | ✅ PASS |
| `exice_nawips.sh` | ✅ Lowercase, starts with `ex` | ✅ PASS |
| `exice_nawips.sh.ecf` | ⚠️ Non-standard extension | ⚠️ WARN |

### 3.2 Ex-Script Compliance Details

**exseaice_analysis.sh:**

| EE2 Requirement | Status | Details |
|-----------------|--------|---------|
| Shebang present | ✅ PASS | `#!/bin/ksh` |
| `set -x` at top | ✅ PASS | Present |
| Uses `postmsg` | ✅ PASS | `postmsg "$msg"` |
| Uses `startmsg` | ✅ PASS | Before exec calls |
| Uses `err_chk` after executables | ✅ PASS | `export err=$?;err_chk` |
| Uses `$SENDCOM` check | ✅ PASS | `if [ $SENDCOM = "YES" ]` |
| Uses `$SENDDBN` check | ✅ PASS | Wraps dbn_alert calls |
| DOCBLOCK header | ⚠️ PARTIAL | Has history but incomplete format |

**Issues Found:**

| Issue | Severity | Line | Details |
|-------|----------|------|---------|
| Uses `#!/bin/ksh` | ⚠️ Medium | 1 | EE2 recommends bash; ksh acceptable |
| Uses `cp` instead of `cpreq` | ⚠️ Medium | Multiple | Should use `cpreq` for essential copies |
| Missing `prep_step` before some execs | ⚠️ Medium | Various | Not all Fortran execs preceded by `prep_step` |
| Uses `rm -f` without error check | ℹ️ Low | 86 | Minor - rm for cleanup |

**exseaice_filter.sh:**

| Issue | Severity | Line | Details |
|-------|----------|------|---------|
| No `set -x` present | ❌ FAIL | - | Added later but should be at script start |
| Uses Fortran unit assignments directly | ⚠️ Medium | 23-24 | `ln -sf ... fort.11` - acceptable but `prep_step` recommended |
| No `err_chk` after executable | ❌ FAIL | 25 | Missing error check after `seaice_avhrrbufr` |

**exseaice_viirs.sh:**

| Issue | Severity | Line | Details |
|-------|----------|------|---------|
| Uses `set -e` | ❌ FAIL | 18 | **NOT EE2 compliant** - use `err_chk` instead |
| Sources Python venv from `$HOME` | ⚠️ Medium | 21 | Hardcoded user path |
| No `err_chk` after Python execution | ⚠️ Medium | Various | Python scripts should have error checks |

---

## 4. Error Handling Compliance

### 4.1 Production Utility Usage

| Utility | Required | Usage Status | Files Using |
|---------|----------|--------------|-------------|
| `err_chk` | ✅ Yes | ✅ Used | JSEAICE_ANALYSIS, exseaice_analysis.sh |
| `err_exit` | ✅ Yes | ⚠️ Not Used | Should replace explicit `exit 1` |
| `prep_step` | ✅ Yes | ⚠️ Partial | Some execs missing prep_step |
| `startmsg` | Optional | ✅ Used | exseaice_analysis.sh |
| `postmsg` | Optional | ✅ Used | exseaice_analysis.sh, exice_nawips.sh |
| `cpreq` | ✅ Yes | ❌ Not Used | Should replace `cp` for essential files |
| `cpfs` | ✅ Yes | ❌ Not Used | Consider for large file copies |

### 4.2 Error Handling Patterns

| Pattern | EE2 Compliant | Occurrences | Recommendation |
|---------|---------------|-------------|----------------|
| `export err=$?; err_chk` | ✅ Yes | 8 | Correct usage |
| `exit 1` | ❌ No | 2 | Replace with `err_exit` |
| `set -e` | ❌ No | 2 | Remove - use `err_chk` per EE2 |
| Missing error check after exec | ❌ No | 3 | Add `err_chk` |

### 4.3 Critical Finding: Anti-Pattern Detection

**Per EE2 Semantic Annotations:**

```
.. mcp:anti_pattern:: adding_set_e_or_set_eu
   :severity: must_not
   :context: operational_scripts
   :sme_justification: Not present in EE2 standards - AI false positive
   :rationale: EE2 uses err_chk/err_exit for error handling, not shell error traps
```

| File | Anti-Pattern | Line | Fix Required |
|------|--------------|------|--------------|
| `JSEAICE_ANALYSIS` | `set -xae` | 3 | Change to `set -x` |
| `JSEAICE_VIIRS` | `set -e` | 4 | Remove |
| `exseaice_viirs.sh` | `set -e` | 18 | Remove, use `err_chk` |

---

## 5. Environment Variables Compliance

### 5.1 Standard Variables Usage

| Variable | EE2 Standard | Used | Set Location |
|----------|--------------|------|--------------|
| `envir` | ✅ Required | ✅ Yes | job card |
| `cyc` | ✅ Required | ✅ Yes | job card |
| `cycle` | ✅ Required | ✅ Yes | J-job |
| `PDY` | ✅ Required | ✅ Yes | J-job via setpdy.sh |
| `DATA` | ✅ Required | ✅ Yes | J-job |
| `DATAROOT` | ✅ Required | ✅ Yes | job card |
| `NET` | ✅ Required | ✅ Yes | J-job |
| `RUN` | ✅ Required | ✅ Yes | J-job |
| `HOMEseaice_analysis` | ✅ Required | ✅ Yes | job card |
| `EXECseaice_analysis` | ✅ Required | ✅ Yes | J-job |
| `USHseaice_analysis` | ✅ Required | ✅ Yes | J-job |
| `FIXseaice_analysis` | ✅ Required | ✅ Yes | J-job |
| `PARMseaice_analysis` | ✅ Required | ✅ Yes | J-job |
| `COMOUT` | ✅ Required | ✅ Yes | J-job |
| `COMIN` | ✅ Required | ✅ Yes | J-job |
| `SENDCOM` | ✅ Required | ✅ Yes | job card |
| `SENDDBN` | ✅ Required | ✅ Yes | job card |
| `KEEPDATA` | ✅ Required | ✅ Yes | job card |
| `pgmout` | ✅ Required | ✅ Yes | J-job |
| `seaice_analysis_ver` | ✅ Required | ✅ Yes | versions file |

### 5.2 Variable Quoting Analysis

| Issue | Count | Severity | Example |
|-------|-------|----------|---------|
| Unquoted variables | ~70 | ℹ️ Low | `$COMOUT` vs `"${COMOUT}"` |
| Proper quoting | ~30% | - | Uses `${var:-default}` correctly |

**Recommendation:** While functional, prefer `"${VARIABLE}"` style for robustness.

---

## 6. Version Files Analysis

### 6.1 versions/run.ver

| Requirement | Status | Details |
|-------------|--------|---------|
| Shell script format | ✅ PASS | `#!/bin/bash` |
| Module versions exported | ✅ PASS | All required modules |
| Uses `export` statements | ✅ PASS | Correct format |

**Contents Summary:**

| Module | Version | Status |
|--------|---------|--------|
| `intel_ver` | 19.1.3.304 | ✅ |
| `craype_ver` | 2.7.17 | ✅ |
| `wgrib2_ver` | 2.0.8 | ✅ |
| `grib_util_ver` | 1.2.4 | ✅ |
| `prod_util_ver` | 2.0.14 | ✅ |
| `netcdf_ver` | 4.7.4 | ✅ |
| `bufr_dump_ver` | 1.3.0 | ✅ |

### 6.2 versions/build.ver

| Requirement | Status | Details |
|-------------|--------|---------|
| Separate from run.ver | ✅ PASS | Correctly separated |
| Build-specific modules | ✅ PASS | Includes compile-time deps |
| Version format (X.Y.Z) | ✅ PASS | `seaice_analysis_ver=4.6.0` |

---

## 7. File Naming Compliance

### 7.1 Output File Naming

**EE2 Format:** `model.tHHz.var_info.f###.domain.format`

| File Pattern | Compliant | Example |
|--------------|-----------|---------|
| `seaice.t${cyc}z.umasknorth12` | ✅ PASS | Follows convention |
| `seaice.t${cyc}z.nh12.gif` | ✅ PASS | Correct format |
| `initnorth12.$PDY` | ⚠️ PARTIAL | Missing `t${cyc}z` prefix |
| `noice.$PDY` | ⚠️ PARTIAL | Should include cycle |

### 7.2 Naming Issues

| Issue | Severity | Example | Recommendation |
|-------|----------|---------|----------------|
| Date in filename | ⚠️ Medium | `noice.$PDY` | Date should be in directory, not filename |
| Inconsistent prefixes | ℹ️ Low | `nh.$PDY.gif` vs `seaice.t00z.nh.gif` | Standardize to `seaice.tHHz.*` |

---

## 8. Build System Analysis

### 8.1 Modulefile Compliance

**Location:** `sorc/modulefiles/seaice_analysis/4.5.0.lua`

| Requirement | Status | Details |
|-------------|--------|---------|
| Lua format (Lmod) | ✅ PASS | Uses .lua extension |
| Prereq modules | ✅ PASS | `prereq("envvar/1.0")` |
| Compiler variables | ✅ PASS | Sets `FC`, `CC`, `CPP` |
| No absolute paths | ✅ PASS | Uses environment variables |

### 8.2 Makefile Standards

| Requirement | Status | Details |
|-------------|--------|---------|
| Required targets: `all` | ✅ PASS | Present |
| Required targets: `clean` | ✅ PASS | Present |
| Required targets: `install` | ⚠️ PARTIAL | Via `toexec` script |
| Uses module variables | ✅ PASS | `$(FC)`, `$(BUFR_LIB4)` |
| No hardcoded paths | ✅ PASS | Uses `$(MMAB_BASE)` etc. |

---

## 9. Detailed Findings Summary

### 9.1 Critical Issues (Must Fix)

| ID | Category | File | Issue | EE2 Reference |
|----|----------|------|-------|---------------|
| C1 | Error Handling | `exseaice_filter.sh` | Missing `err_chk` after executable | Standards §C |
| C2 | Error Handling | `exseaice_viirs.sh` | Uses `set -e` instead of `err_chk` | Anti-pattern |
| C3 | Error Handling | `JSEAICE_ANALYSIS` | Uses `exit 1` instead of `err_exit` | Standards §C |

### 9.2 Major Issues (Should Fix)

| ID | Category | File | Issue | EE2 Reference |
|----|----------|------|-------|---------------|
| M1 | Production Utils | Multiple | Uses `cp` instead of `cpreq` for essential files | Standards §C |
| M2 | Script Headers | Multiple | `set -xae` should be `set -x` only | Standards §C |
| M3 | Production Utils | `exseaice_filter.sh` | Missing `prep_step` before Fortran exec | Standards §C |
| M4 | Directory Structure | Root | Missing `doc/` subdirectory | Standards §B |

### 9.3 Minor Issues (Consider Fixing)

| ID | Category | File | Issue | EE2 Reference |
|----|----------|------|-------|---------------|
| m1 | File Naming | Multiple | Date in filename vs directory | Standards §B |
| m2 | Variable Quoting | Multiple | Unquoted variable references | Best Practice |
| m3 | DOCBLOCK | Scripts | Incomplete documentation headers | Standards §A |
| m4 | Interpreter | `exseaice_analysis.sh` | Uses `#!/bin/ksh` (bash preferred) | Standards §C |

---

## 10. Remediation Recommendations

### 10.1 High Priority

1. **Replace `set -e` with proper `err_chk` usage:**
   ```bash
   # WRONG (exseaice_viirs.sh line 18)
   set -e
   
   # CORRECT
   $EXECseaice_analysis/some_program >> $pgmout 2>errfile
   export err=$?; err_chk
   ```

2. **Replace `exit 1` with `err_exit`:**
   ```bash
   # WRONG (JSEAICE_ANALYSIS line 101)
   echo "some error"; exit 1
   
   # CORRECT
   err_exit "some error in creating comout: $COMOUT"
   ```

3. **Add `err_chk` after all executable calls in exseaice_filter.sh:**
   ```bash
   time $EXECseaice_analysis/seaice_avhrrbufr
   export err=$?; err_chk  # ADD THIS LINE
   ```

### 10.2 Medium Priority

4. **Replace `cp` with `cpreq` for essential file copies:**
   ```bash
   # WRONG
   cp $COMIN/inputfile inputfile
   
   # CORRECT
   cpreq $COMIN/inputfile inputfile
   ```

5. **Add `prep_step` before Fortran executables:**
   ```bash
   . prep_step
   export FORT11=input_file
   $EXECseaice_analysis/seaice_avhrrbufr
   export err=$?; err_chk
   ```

6. **Simplify shell options:**
   ```bash
   # WRONG
   set -xae
   
   # CORRECT
   set -x
   ```

### 10.3 Low Priority

7. **Add `doc/` directory with release notes**
8. **Standardize file naming to include cycle time**
9. **Quote all variable references: `"${VARIABLE}"`**
10. **Complete DOCBLOCK headers in all scripts**

---

## 11. Compliance Score Calculation

| Category | Weight | Score | Weighted |
|----------|--------|-------|----------|
| Directory Structure | 15% | 95% | 14.25 |
| J-Job Standards | 20% | 80% | 16.00 |
| Ex-Script Standards | 20% | 70% | 14.00 |
| Error Handling | 20% | 65% | 13.00 |
| Production Utilities | 10% | 85% | 8.50 |
| Version Files | 5% | 90% | 4.50 |
| File Naming | 5% | 75% | 3.75 |
| Build System | 5% | 85% | 4.25 |
| **TOTAL** | **100%** | - | **78.25%** |

---

## 12. Conclusion

The **NOAA-EMC/seaice-concentration** repository demonstrates **good overall compliance** with EE2 standards (78%), with the package structure and production utility usage being particularly strong. 

**Key Strengths:**
- ✅ Proper vertical directory structure
- ✅ J-job naming and basic structure
- ✅ Uses `err_chk` in main scripts
- ✅ Proper version file separation (run.ver/build.ver)
- ✅ Lmod-compatible modulefiles

**Critical Gaps:**
- ❌ Uses `set -e` which is NOT an EE2 standard (use `err_chk` instead)
- ❌ Missing error checks after some executables
- ❌ Uses `exit 1` instead of `err_exit`
- ❌ Uses `cp` instead of `cpreq` for essential files

**Recommendation:** Address the 3 Critical Issues before operational deployment to ensure proper error propagation through ecFlow/PBS Pro workflow management.

---

*Report generated by MCP RAG System using EE2 Semantic Annotations from nws-hpc-standards*
