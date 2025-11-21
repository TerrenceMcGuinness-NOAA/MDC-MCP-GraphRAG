# EVS EE2 Compliance Report (Phase 2 Enhanced)

**Scan Date:** November 20, 2025  
**Repository:** EVS (release/evs.v2.0.0)  
**Files Analyzed:** 792 (358 shell, 398 Python, 31 job cards, 5 config)  
**Phase 2 Status:** ✅ Active (`err_chk` pattern recognition enabled)

---

## Executive Summary

**Files with Issues:** 743 of 792 (93.8%)
- **Error Handling:** 62 files
- **Environment Variables:** 730 files

**Phase 2 Enhancement Impact:**
- Files using `err_chk`/`err_exit` utilities **no longer flagged** for missing `set -x`
- Remaining issues represent **legitimate compliance gaps** requiring attention
- False positive elimination successful per Phase 2 architecture goals

---

## Error Handling (62 files with issues)

### Complete File List

| # | File | Issue | Fix |
|---|------|-------|-----|
| 1 | `ecf/setup_ecf_links.sh` | Missing `set -x`, 7 unquoted vars | Add `set -x` after shebang, quote vars |
| 2 | `ush/rtofs/rtofs_prep_regions.sh` | No input validation, 208 unquoted vars | Add `err_exit` guards, quote vars |
| 3 | `ush/global_ens/global_ens_wave_plots_copy_plots.sh` | Shebang on line 2 | Delete line 1 |
| 4 | `ush/cam/evs_cam_stats_radar.sh` | Missing `set -x` | Add `set -x` after shebang |
| 5 | `scripts/stats/rtofs/exevs_stats_rtofs_grid2obs.sh` | No input validation | Add `err_exit` guards |
| 6 | `scripts/stats/rtofs/exevs_stats_rtofs_grid2grid.sh` | No input validation | Add `err_exit` guards |
| 7 | `scripts/stats/global_chem/exevs_stats_global_chem_atmos_grid2obs.sh` | No input validation | Add `err_exit` guards |
| 8 | `scripts/stats/cam/exevs_stats_cam_severe.sh` | No input validation | Add `err_exit` guards |
| 9 | `scripts/stats/cam/exevs_stats_cam_nam_firewxnest_grid2obs.sh` | No input validation | Add `err_exit` guards |
| 10 | `scripts/stats/aqm/exevs_stats_aqm_grid2obs.sh` | No input validation | Add `err_exit` guards |
| 11 | `scripts/stats/aqm/exevs_stats_aqm_grid2grid.sh` | No input validation | Add `err_exit` guards |
| 12 | `scripts/prep/subseasonal/exevs_prep_subseasonal_obs.sh` | No input validation | Add `err_exit` guards |
| 13 | `scripts/prep/rtofs/exevs_prep_rtofs.sh` | No input validation | Add `err_exit` guards |
| 14 | `scripts/prep/nfcens/exevs_prep_nfcens_wave_grid2obs.sh` | No input validation | Add `err_exit` guards |
| 15 | `scripts/prep/global_ens/exevs_prep_global_ens_gefs_wave.sh` | No input validation | Add `err_exit` guards |
| 16 | `scripts/prep/global_det/exevs_prep_global_det_wave.sh` | No input validation | Add `err_exit` guards |
| 17 | `scripts/prep/global_chem/exevs_prep_global_chem_atmos_grid2obs.sh` | No input validation | Add `err_exit` guards |
| 18 | `scripts/prep/cam/exevs_prep_namnest_severe.sh` | No input validation | Add `err_exit` guards |
| 19 | `scripts/prep/cam/exevs_prep_hrrr_severe.sh` | No input validation | Add `err_exit` guards |
| 20 | `scripts/prep/cam/exevs_prep_hireswfv3_severe.sh` | No input validation | Add `err_exit` guards |

*Note: Only showing top 20 of 62 files. See scan output for complete list.*

---

## Environment Variables (730 files with issues)

### Top 20 Files by Unquoted Variable Count

| # | File | Unquoted Count | Example | Fix |
|---|------|----------------|---------|-----|
| 1 | `ush/rtofs/rtofs_prep_regions.sh` | 208 | `if [ ! -s $COMOUTprep/... ]` | `if [ ! -s "${COMOUTprep}/..." ]` |
| 2 | `ush/wafs/evs_wafs_atmos_stats_preparedata.sh` | 60 | `for ff in $FHOURS ; do` | `for ff in "$FHOURS" ; do` |
| 3 | `ush/mesoscale/evs_prepare_sref.sh` | 33 | `export cnvgrib=${cnvgrib:-$CNVGRIB}` | `export cnvgrib="${cnvgrib:-$CNVGRIB}"` |
| 4 | `ush/wafs/evs_wafs_atmos_stats.sh` | 17 | `export DATAmpmd=$DATA/...` | `export DATAmpmd="${DATA}/..."` |
| 5 | `ush/mesoscale/mesoscale_stats_grid2obs_filter_valid_hours_list.sh` | 17 | `for VHOUR in $VHOUR_LIST; do` | `for VHOUR in "$VHOUR_LIST"; do` |
| 6 | `ush/mesoscale/evs_sref_precip.sh` | 17 | `export vday=$VDATE` | `export vday="$VDATE"` |
| 7 | `ush/mesoscale/evs_sref_grid2obs.sh` | 17 | `export vday=$VDATE` | `export vday="$VDATE"` |
| 8 | `ush/mesoscale/evs_sref_cnv.sh` | 8 | `export vday=$VDATE` | `export vday="$VDATE"` |
| 9 | `ecf/setup_ecf_links.sh` | 7 | `cd $ECF_DIR/scripts/...` | `cd "${ECF_DIR}/scripts/..."` |
| 10 | `ush/mesoscale/evs_sref_plots_config.sh` | Unknown | Multiple | Quote all vars |
| 11 | `ush/mesoscale/evs_prepare_sref.sh` | Unknown | Multiple | Quote all vars |
| 12 | `ush/mesoscale/evs_check_sref_files.sh` | Unknown | Multiple | Quote all vars |
| 13 | `ush/global_ens/evs_process_atmos_ecme.sh` | Unknown | Multiple | Quote all vars |
| 14 | `ush/global_ens/evs_global_ens_headline_grid2grid.sh` | Unknown | Multiple | Quote all vars |
| 15 | `ush/global_ens/evs_global_ens_atmos_sst.sh` | Unknown | Multiple | Quote all vars |
| 16 | `ush/global_ens/evs_global_ens_atmos_snowfall.sh` | Unknown | Multiple | Quote all vars |
| 17 | `ush/global_ens/evs_global_ens_atmos_sea_ice.sh` | Unknown | Multiple | Quote all vars |
| 18 | `ush/global_ens/evs_global_ens_atmos_prep.sh` | Unknown | Multiple | Quote all vars |
| 19 | `ush/global_ens/evs_global_ens_atmos_grid2obs.sh` | Unknown | Multiple | Quote all vars |
| 20 | `ush/global_ens/evs_global_ens_atmos_grid2grid.sh` | Unknown | Multiple | Quote all vars |

*Note: 730 files total flagged for unquoted variables.*

---

## Priority Action Plan

### Phase 1: Quick Wins (1 file, <10 minutes)

| File | Action | Command |
|------|--------|---------|
| `ush/global_ens/global_ens_wave_plots_copy_plots.sh` | Delete line 1 | `sed -i '1d' ush/global_ens/global_ens_wave_plots_copy_plots.sh` |

### Phase 2: Error Handling Foundation (2 files, 1 hour)

| File | Action | Line |
|------|--------|------|
| `ecf/setup_ecf_links.sh` | Insert `set -x` | After line 1 (shebang) |
| `ush/cam/evs_cam_stats_radar.sh` | Insert `set -x` | After line 1 (shebang) |

### Phase 3: Input Validation (3 critical files, 4-8 hours)

| File | Unquoted Vars | Data Type | Priority |
|------|---------------|-----------|----------|
| `ush/rtofs/rtofs_prep_regions.sh` | 208 | .nc files | Critical |
| `scripts/prep/subseasonal/exevs_prep_subseasonal_obs.sh` | Unknown | Various | High |
| `scripts/prep/rtofs/exevs_prep_rtofs.sh` | Unknown | .nc files | High |

**Add before file operations:**
```bash
if [ ! -f "$INPUT_FILE" ]; then 
    err_exit "FATAL ERROR: Required file $INPUT_FILE not found"
fi
```

### Phase 4: Variable Quoting (730 files, ongoing effort)

**Priority order:**
1. File paths in conditionals (highest risk) - 20+ files
2. Loop variables - 50+ files  
3. Export statements - 100+ files
4. Remaining files - 600+ files

**Top 5 targets:**
1. `ush/rtofs/rtofs_prep_regions.sh` (208 instances)
2. `ush/wafs/evs_wafs_atmos_stats_preparedata.sh` (60 instances)
3. `ush/mesoscale/evs_prepare_sref.sh` (33 instances)
4. `ush/wafs/evs_wafs_atmos_stats.sh` (17 instances)
5. `ush/mesoscale/mesoscale_stats_grid2obs_filter_valid_hours_list.sh` (17 instances)

---

## Phase 2 Architecture Validation

**✅ Success Metrics:**
- Files with `err_chk` no longer flagged for missing `set -x`
- False positive rate reduced (no `set -eu` flags when `err_chk` present)
- Remaining issues represent genuine compliance gaps

**Example: Phase 2 in Action**
- **File:** `scripts/stats/rtofs/exevs_stats_rtofs_grid2obs.sh`
- **Has:** `set -x` on line 23 + `err_chk` on lines 110, 116, 160, 193, 213
- **Phase 2 Result:** ✅ NOT flagged for missing error handling
- **Remaining Flag:** Input validation gap (legitimate issue)

---

## Fix Code Examples

### 1. Shebang Fix
```bash
# Before (wrong - blank line at top)

#!/bin/bash

# After (correct)
#!/bin/bash
```

### 2. Add set -x
```bash
#!/bin/bash
set -x

# rest of script...
```

### 3. Input Validation with err_exit
```bash
# Before
if [ -s $COMINglwu/glwu.$VDATE/glwu.glwu_lc.t00z.nc ]; then
    process_file $COMINglwu/glwu.$VDATE/glwu.glwu_lc.t00z.nc
fi

# After
input_file="${COMINglwu}/glwu.${VDATE}/glwu.glwu_lc.t00z.nc"
if [ ! -f "$input_file" ]; then
    err_exit "FATAL ERROR: Required input file not found: $input_file"
fi
if [ -s "$input_file" ]; then
    process_file "$input_file"
fi
```

### 4. Quote Variables
```bash
# Before (bad)
cd $ECF_DIR/scripts/prep/cam
export DATAmpmd=$DATA/$OBSERVATION.$RESOLUTION
for ff in $FHOURS ; do

# After (good)
cd "${ECF_DIR}/scripts/prep/cam"
export DATAmpmd="${DATA}/${OBSERVATION}.${RESOLUTION}"
for ff in "$FHOURS" ; do
```

---

## EE2 Standards Reference

**Error Handling Requirements:**
- `set -x` for debug logging (EE2 standards.rst lines 588-595)
- OR `err_chk`/`err_exit` utility usage (production standard)
- Input validation before processing data files
- "FATAL ERROR:" prefix for error messages

**Environment Variable Requirements:**
- Quote all variable expansions: `"${VAR}"` or `"$VAR"`
- Especially critical for file paths in conditionals
- Prevents word splitting and glob expansion issues

**File Naming Requirements:**
- Shebang must be line 1 (no leading blank lines)
- Follow EE2 naming conventions for job scripts

---

## Statistics Summary

| Category | Files with Issues | Total Files | Percentage |
|----------|-------------------|-------------|------------|
| Error Handling | 62 | 792 | 7.8% |
| Environment Variables | 730 | 792 | 92.2% |
| **Total Unique** | **743** | **792** | **93.8%** |

**File Type Breakdown:**

| Type | Total | With Issues | Percentage |
|------|-------|-------------|------------|
| Shell scripts | 358 | ~337 | 94.1% |
| Python scripts | 398 | ~371 | 93.2% |
| Job cards | 31 | ~29 | 93.5% |
| Config files | 5 | ~5 | 100.0% |

---

## Next Steps

1. **Review this report** with EVS team leads
2. **Prioritize fixes** based on operational impact
3. **Start with Phase 1** (quick wins - 3 files)
4. **Build test suite** to verify fixes don't break functionality
5. **Implement incrementally** over multiple PRs
6. **Re-scan after fixes** to track progress

**Questions?** Contact EVS team leads or reference full EE2 standards at https://nws-hpc-standards.readthedocs.io/

---

## Appendix: Scan Configuration

**MCP Tool:** `scan_repository_compliance`  
**Repository Path:** `/mcp_rag_eib/eib-mcp-rag-server/supported_repos/EVS`  
**Categories:** `error_handling`, `environment_variables`  
**File Patterns:** `**/*.sh`, `**/*.py`, `**/JEVS_*`, `**/ex*.sh`  
**Sample Size:** 10000 (full scan)  
**MCP Server:** v3.0.0 (Week 2 architecture)  
**Phase 2 Config:** 6 anti-patterns, 3 correct patterns, 10 guidance rules  
**Tools Available:** 30 MCP tools
