# Phase 25: CTest Framework Expansion - C48_S2SW Wave Component Tests

**Status**: PLANNED  
**Created**: January 16, 2026  
**Author**: Terrence McGuinness  
**Priority**: HIGH - CI/CD testing infrastructure enhancement  
**GitHub Issue**: [NOAA-EMC/global-workflow#4318](https://github.com/NOAA-EMC/global-workflow/issues/4318)  
**Labels**: CI/CD, enhancement, testing  
**Depends On**: Existing CTest framework (`dev/ctests/`)

---

## Problem Statement

The current global-workflow CTest framework has **9 tests** covering basic atmosphere and coupled forecast scenarios, but lacks comprehensive coverage for **wave model components** in the C48_S2SW coupled configuration. This gap means:

1. **No isolated wave job testing** - Wave initialization, post-processing, and boundary point jobs cannot be tested independently
2. **Regression risk** - Changes to wave-related code may break production without CI detection
3. **Debugging difficulty** - Wave job failures in full workflow runs are harder to diagnose than isolated CTest failures
4. **Incomplete coverage** - Only 3 of 89 job cards have CTest coverage in S2SW configuration

### Current CTest Coverage

| Configuration | Existing Tests | Wave Coverage |
|---------------|----------------|---------------|
| **C48_ATM** | gfs_stage_ic, gfs_fcst_seg0, gfs_atmos_prod_f000-f002, gfs_tracker, gfs_genesis | N/A |
| **C48_S2SW** | gfs_fcst_seg0, gfs_ocean_prod_f006, gfs_ice_prod_f006 | ❌ None |
| **C48_S2SWA_gefs** | gefs_fcst_mem001_seg0 | ❌ None |

### Target Coverage After Phase 25

| Configuration | Tests After | Wave Coverage |
|---------------|-------------|---------------|
| **C48_S2SW** | 9 total (+6 new) | ✅ Full coverage |

---

## Solution: 6 New Wave Component CTests

Add comprehensive wave model testing to the C48_S2SW configuration, enabling isolated validation of WaveWatch III jobs.

### New Test Cases

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    NEW C48_S2SW WAVE TESTS (6)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. C48_S2SW-gfs_stage                                                      │
│     └── Coupled IC staging (atm + ocean + ice + wave)                       │
│                                                                              │
│  2. C48_S2SW-gfs_waveinit                                                   │
│     └── WaveWatch III grid initialization                                   │
│                                                                              │
│  3. C48_S2SW-gfs_wavepostsbs_f000-f002                                      │
│     └── Wave spectral bin statistics post-processing                        │
│                                                                              │
│  4. C48_S2SW-gfs_wavebndpnt                                                 │
│     └── Wave boundary point extraction                                      │
│                                                                              │
│  5. C48_S2SW-gfs_wavebndpntbll                                              │
│     └── Wave boundary point bulletin generation                             │
│                                                                              │
│  6. C48_S2SW-gfs_wavepostpnt                                                │
│     └── Wave point output post-processing                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Dependency Chain

```
                    gfs_stage
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
      gfs_waveinit  (existing    (existing
          │          fcst)        ocean/ice)
          ▼            │
    gfs_fcst_seg0 ◄────┘
          │
          ├──────────────────────────────────┐
          ▼                                  ▼
    gfs_wavepostsbs_f000-f002          gfs_wavebndpnt
          │                                  │
          ▼                                  ▼
    (validation)                       gfs_wavebndpntbll
                                             │
                                             ▼
                                       gfs_wavepostpnt
                                             │
                                             ▼
                                       (validation)
```

---

## Test Case Specifications

### Test 1: C48_S2SW-gfs_stage

**Purpose**: Validate staging of coupled model initial conditions across all components.

**Job Script**: `jobs/rocoto/stage_ic.sh` → `scripts/exglobal_stage_ic.py`

| Attribute | Value |
|-----------|-------|
| Input Files | 13 atmosphere ICs, 3 restarts (ocean, ice, wave), 1 wave prep |
| Output Files | Staged ICs in `${ROTDIR}` |
| Dependencies | None (first in chain) |
| Est. Runtime | 2 minutes |
| HPC Resources | 1 node, low memory |

**Test Focus**:
- Multi-component staging coordination
- Restart file handling (6-hour offset pattern from previous cycle)
- Component consistency checks
- Missing component detection and error reporting

**YAML Configuration**: `cases/C48_S2SW-gfs_stage.yaml`

```yaml
{% set cyc = TEST_DATE | strftime('%H') %}
{% set PDY = TEST_DATE | to_YMD %}
{% set SRC_DIR = STAGED_CTESTS + '/COMROOT/' + PSLOT %}
{% set DST_DIR = RUNTESTS + '/COMROOT/' + TEST_NAME %}

input_files:
    mkdir:
        - {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/atmos/input
        - {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/ocean/restart
        - {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/ice/restart
        - {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/restart

    copy:
        # Atmosphere ICs (13 files: ctrl + 6 tiles × 2 types)
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/atmos/input/gfs_ctrl.nc,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/atmos/input/gfs_ctrl.nc]
        # ... tile files (gfs_data.tile[1-6].nc, sfc_data.tile[1-6].nc)
        
        # Ocean restart (from previous cycle)
        - [{{ SRC_DIR }}/gfs.{{ PDY_prev }}/{{ cyc_prev }}/model/ocean/restart/MOM.res.nc,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/ocean/restart/MOM.res.nc]
        
        # Ice restart
        - [{{ SRC_DIR }}/gfs.{{ PDY_prev }}/{{ cyc_prev }}/model/ice/restart/ice.res.nc,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/ice/restart/ice.res.nc]
        
        # Wave prep file
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/station/ww3_prep.inp,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/station/ww3_prep.inp]

output_files:
    cmpfiles:
        - [{{ SRC_DIR }}/logs/{{ PDY }}{{ cyc }}/gfs_stage.log,
           {{ DST_DIR }}/logs/{{ PDY }}{{ cyc }}/gfs_stage.log]
```

---

### Test 2: C48_S2SW-gfs_waveinit

**Purpose**: Test WaveWatch III grid initialization and configuration generation.

**Job Script**: `jobs/rocoto/waveinit.sh` → `scripts/exgfs_wave_init.sh`

| Attribute | Value |
|-----------|-------|
| Input Files | Wave prep file, staged ICs |
| Output Files | `mod_def.ww3`, `ww3_grid.inp`, boundary setup files |
| Dependencies | `gfs_stage` |
| Est. Runtime | 5 minutes |
| HPC Resources | 1 node |

**Test Focus**:
- WaveWatch III grid initialization
- Boundary condition setup
- Configuration file generation
- Grid consistency validation against model domain

**YAML Configuration**: `cases/C48_S2SW-gfs_waveinit.yaml`

```yaml
input_files:
    copy:
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/station/ww3_prep.inp,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/station/ww3_prep.inp]
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/grid/wind_forcing.nc,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/grid/wind_forcing.nc]

output_files:
    cmpfiles:
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/grid/mod_def.ww3,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/grid/mod_def.ww3]
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/grid/ww3_grid.inp,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/grid/ww3_grid.inp]
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/conf/wave.input.nml,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/conf/wave.input.nml]
```

---

### Test 3: C48_S2SW-gfs_wavepostsbs_f000-f002

**Purpose**: Wave post-processing for spectral bin statistics at forecast hours 0, 1, 2.

**Job Script**: `jobs/rocoto/wavepostsbs.sh` → `scripts/exgfs_wave_postsbs.sh`

| Attribute | Value |
|-----------|-------|
| Input Files | Wave forecast output (f000, f001, f002) |
| Output Files | Spectral statistics files |
| Dependencies | `gfs_fcst_seg0` (wave output) |
| Est. Runtime | 10 minutes |
| HPC Resources | 4 nodes (parallel processing) |

**Test Focus**:
- Spectral binning accuracy
- Multi-hour batch processing
- Output file completeness (all bins generated)
- Missing hour handling and error recovery

**YAML Configuration**: `cases/C48_S2SW-gfs_wavepostsbs_f000-f002.yaml`

```yaml
input_files:
    copy:
        # Wave forecast output files
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/history/gfs.wave.f000.nc,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/history/gfs.wave.f000.nc]
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/history/gfs.wave.f001.nc,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/history/gfs.wave.f001.nc]
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/history/gfs.wave.f002.nc,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/history/gfs.wave.f002.nc]

output_files:
    cmpfiles:
        # Spectral bin statistics output
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/grib2/gfs.t{{ cyc }}z.wave_sbs.f000.grib2,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/grib2/gfs.t{{ cyc }}z.wave_sbs.f000.grib2]
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/grib2/gfs.t{{ cyc }}z.wave_sbs.f001.grib2,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/grib2/gfs.t{{ cyc }}z.wave_sbs.f001.grib2]
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/grib2/gfs.t{{ cyc }}z.wave_sbs.f002.grib2,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/grib2/gfs.t{{ cyc }}z.wave_sbs.f002.grib2]
```

---

### Test 4: C48_S2SW-gfs_wavebndpnt

**Purpose**: Wave boundary point data extraction from forecast output.

**Job Script**: `jobs/rocoto/wavebndpnt.sh` → `scripts/exgfs_wave_bndpnt.sh`

| Attribute | Value |
|-----------|-------|
| Input Files | Wave forecast output (f000-f048) |
| Output Files | Boundary point data files |
| Dependencies | `gfs_fcst_seg0` (wave output) |
| Est. Runtime | 15 minutes |
| HPC Resources | 2 nodes |

**Test Focus**:
- Boundary point identification from model grid
- Data extraction accuracy at specified locations
- Time series construction across forecast hours
- Coordinate consistency with point definitions

**YAML Configuration**: `cases/C48_S2SW-gfs_wavebndpnt.yaml`

```yaml
input_files:
    copy:
        # Wave forecast output (representative subset)
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/history/gfs.wave.f000.nc,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/history/gfs.wave.f000.nc]
        # ... additional forecast hours
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/station/ww3_bndpnt.inp,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/station/ww3_bndpnt.inp]

output_files:
    cmpfiles:
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/bndpnt/gfs.t{{ cyc }}z.wave_bndpnt.tar,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/bndpnt/gfs.t{{ cyc }}z.wave_bndpnt.tar]
```

---

### Test 5: C48_S2SW-gfs_wavebndpntbll

**Purpose**: Generate formatted bulletins from boundary point data for dissemination.

**Job Script**: `jobs/rocoto/wavebndpntbll.sh` → `scripts/exgfs_wave_bndpntbll.sh`

| Attribute | Value |
|-----------|-------|
| Input Files | Boundary point data from `wavebndpnt` |
| Output Files | WMO-formatted bulletins |
| Dependencies | `gfs_wavebndpnt` |
| Est. Runtime | 5 minutes |
| HPC Resources | 1 node |

**Test Focus**:
- Bulletin formatting compliance with WMO standards
- WMO header generation (TTAAii CCCC YYGGgg)
- Data validation and quality flags
- Missing data handling and placeholder insertion

**YAML Configuration**: `cases/C48_S2SW-gfs_wavebndpntbll.yaml`

```yaml
input_files:
    copy:
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/bndpnt/gfs.t{{ cyc }}z.wave_bndpnt.tar,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/bndpnt/gfs.t{{ cyc }}z.wave_bndpnt.tar]

output_files:
    cmpfiles:
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/bulletin/gfs.t{{ cyc }}z.wave_bndpnt.bull,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/bulletin/gfs.t{{ cyc }}z.wave_bndpnt.bull]
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/bulletin/gfs.t{{ cyc }}z.wave_bndpnt.wmo,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/bulletin/gfs.t{{ cyc }}z.wave_bndpnt.wmo]
```

---

### Test 6: C48_S2SW-gfs_wavepostpnt

**Purpose**: Wave point output post-processing to NetCDF format.

**Job Script**: `jobs/rocoto/wavepostpnt.sh` → `scripts/exgfs_wave_postpnt.sh`

| Attribute | Value |
|-----------|-------|
| Input Files | Wave forecast point output |
| Output Files | Post-processed NetCDF files |
| Dependencies | `gfs_fcst_seg0` (wave output) |
| Est. Runtime | 8 minutes |
| HPC Resources | 2 nodes |

**Test Focus**:
- Point output extraction at station locations
- NetCDF file generation with CF-compliant metadata
- Metadata completeness (time, lat, lon, variables)
- Quality control flags and valid range checks

**YAML Configuration**: `cases/C48_S2SW-gfs_wavepostpnt.yaml`

```yaml
input_files:
    copy:
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/history/gfs.wave.pnt.f000.nc,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/history/gfs.wave.pnt.f000.nc]
        # ... additional point files
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/station/ww3_pnt.inp,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/wave/station/ww3_pnt.inp]

output_files:
    cmpfiles:
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/point/gfs.t{{ cyc }}z.wave_pnt.nc,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/point/gfs.t{{ cyc }}z.wave_pnt.nc]
        - [{{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/point/gfs.t{{ cyc }}z.wave_pnt.nc.idx,
           {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/wave/point/gfs.t{{ cyc }}z.wave_pnt.nc.idx]
```

---

## Implementation Plan

### Phase 25A: YAML Configuration Files (4 hours)

Create 6 new YAML test case configurations following existing patterns:

| File | Template Source |
|------|-----------------|
| `C48_S2SW-gfs_stage.yaml` | `C48_ATM-gfs_stage_ic.yaml` |
| `C48_S2SW-gfs_waveinit.yaml` | New (wave-specific) |
| `C48_S2SW-gfs_wavepostsbs_f000-f002.yaml` | `C48_ATM-gfs_atmos_prod_f000-f002.yaml` |
| `C48_S2SW-gfs_wavebndpnt.yaml` | New (wave-specific) |
| `C48_S2SW-gfs_wavebndpntbll.yaml` | New (wave-specific) |
| `C48_S2SW-gfs_wavepostpnt.yaml` | New (wave-specific) |

**Key Implementation Details**:
- Use existing Jinja2 filters: `to_timedelta`, `add_to_datetime`, `strftime`, `to_YMD`
- Handle 6-hour offset pattern for restart files from previous cycle
- Include complete file manifests for input staging and output validation

### Phase 25B: CMakeLists.txt Updates (1 hour)

Add 6 new test cases to `dev/ctests/CMakeLists.txt`:

```cmake
# ===================================================================
# C48_S2SW Wave Component Tests (Phase 25)
# ===================================================================

# Test 4: Coupled IC staging (all components)
AddJJOBTest(C48_S2SW gfs_stage 2021032312)

# Test 5: Wave model initialization
AddJJOBTest(C48_S2SW gfs_waveinit 2021032312)

# Test 6: Wave spectral bin statistics post-processing
AddJJOBTest(C48_S2SW gfs_wavepostsbs_f000-f002 2021032312)

# Test 7: Wave boundary point extraction
AddJJOBTest(C48_S2SW gfs_wavebndpnt 2021032312)

# Test 8: Wave boundary point bulletin generation
AddJJOBTest(C48_S2SW gfs_wavebndpntbll 2021032312)

# Test 9: Wave point output post-processing
AddJJOBTest(C48_S2SW gfs_wavepostpnt 2021032312)
```

### Phase 25C: Input Data Staging (2 hours)

Coordinate with CI team to stage required inputs from nightly baseline runs:

1. **Identify baseline run**: Stable C48_S2SW 12Z cycle from nightly CI
2. **Extract wave-specific outputs**: Wave history files, point files, configuration
3. **Stage to `$STAGED_CTESTS`**: Following existing directory structure
4. **Document data provenance**: Record baseline commit hash and run date

**Storage Requirements**:
| Test Case | Input Size | Output Size | Total |
|-----------|------------|-------------|-------|
| gfs_stage | 500 MB | 50 MB | 550 MB |
| gfs_waveinit | 100 MB | 50 MB | 150 MB |
| gfs_wavepostsbs | 200 MB | 100 MB | 300 MB |
| gfs_wavebndpnt | 500 MB | 200 MB | 700 MB |
| gfs_wavebndpntbll | 200 MB | 50 MB | 250 MB |
| gfs_wavepostpnt | 300 MB | 100 MB | 400 MB |
| **Total** | **1.8 GB** | **550 MB** | **~2.4 GB** |

### Phase 25D: Validation Scripts (2 hours)

Extend `validate.py` if needed for wave-specific validation:

- **Spectral data validation**: Check frequency/direction bins
- **NetCDF metadata validation**: CF compliance checks
- **Bulletin format validation**: WMO header parsing
- **Point coordinate validation**: Lat/lon consistency

### Phase 25E: Documentation Updates (1 hour)

Update `dev/ctests/README.md`:

```markdown
## Test Cases

### C48_S2SW Configuration (9 tests)

| Test Name | Job | Purpose |
|-----------|-----|---------|
| gfs_fcst_seg0 | fcst | Coupled forecast segment 0 |
| gfs_ocean_prod_f006 | ocean_products | Ocean products at f006 |
| gfs_ice_prod_f006 | ice_products | Sea ice products at f006 |
| **gfs_stage** | stage_ic | Coupled IC staging (NEW) |
| **gfs_waveinit** | waveinit | Wave initialization (NEW) |
| **gfs_wavepostsbs_f000-f002** | wavepostsbs | Wave spectral stats (NEW) |
| **gfs_wavebndpnt** | wavebndpnt | Wave boundary points (NEW) |
| **gfs_wavebndpntbll** | wavebndpntbll | Wave bulletins (NEW) |
| **gfs_wavepostpnt** | wavepostpnt | Wave point output (NEW) |
```

### Phase 25F: CI Pipeline Integration (2 hours)

1. Add new tests to GitHub Actions workflow
2. Configure test parallelization (tests with no dependencies run in parallel)
3. Set up artifact collection for failed tests
4. Configure notification for test failures

---

## Test Data Requirements

### Input Staging from Nightly Baseline

All tests use input data from stable nightly baseline runs staged in `$STAGED_CTESTS`:

| Source | Cycle | Components |
|--------|-------|------------|
| C48_S2SW nightly | 12Z (2021032312) | atm + ocean + ice + wave |
| Previous cycle | 06Z (2021032306) | Restart files for staging test |

### Directory Structure

```
$STAGED_CTESTS/
└── COMROOT/
    └── C48_S2SW/
        └── gfs.20210323/
            ├── 12/
            │   ├── model/
            │   │   ├── atmos/input/      # Atmosphere ICs
            │   │   ├── ocean/restart/    # Ocean restarts
            │   │   ├── ice/restart/      # Ice restarts
            │   │   └── wave/
            │   │       ├── grid/         # Wave grid files
            │   │       ├── history/      # Wave forecast output
            │   │       └── station/      # Wave station config
            │   └── products/
            │       └── wave/
            │           ├── grib2/        # GRIB2 products
            │           ├── bndpnt/       # Boundary point data
            │           ├── bulletin/     # WMO bulletins
            │           └── point/        # NetCDF point output
            └── 06/
                └── model/
                    └── */restart/        # Previous cycle restarts
```

---

## Acceptance Criteria

### Per Test Case

- [ ] YAML configuration file follows naming convention: `CASE-JOB.yaml`
- [ ] Input files staged correctly from baseline runs
- [ ] Output files generated and validated against expected results
- [ ] Test runs successfully in isolated EXPDIR environment
- [ ] Pass/fail criteria clearly defined and documented
- [ ] Integration with CMake CTest framework complete
- [ ] CI/CD pipeline includes new tests

### Overall Project

- [ ] All 6 new tests pass consistently on Hera, Hercules, Orion
- [ ] Runtime < 30 minutes per test (parallel execution)
- [ ] Documentation updated with test descriptions and usage
- [ ] Zero false positives in 10 consecutive CI runs
- [ ] Total CTest coverage increases from 9 to 15 tests

---

## Validation Commands

### Run All New Tests

```bash
cd global-workflow/build
ctest -R "C48_S2SW-gfs_(stage|wave)" --output-on-failure
```

### Run Specific Wave Test

```bash
ctest -R "C48_S2SW-gfs_waveinit" -V
```

### Check Test Dependencies

```bash
# Verify dependency chain
ctest -N | grep C48_S2SW
```

### Debug Failed Test

```bash
# View detailed logs
cat $RUNTESTS/COMROOT/C48_S2SW-gfs_waveinit/logs/*/gfs_waveinit.log
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Baseline data not available | Low | High | Coordinate with CI team early |
| Wave job scripts change | Medium | Medium | Pin baseline commit hash |
| Storage quota exceeded | Low | Medium | Monitor and request increase |
| Test timeout on slow nodes | Medium | Low | Set conservative timeout (120 min) |
| Custom Rocoto `--dryrun` issues | Low | High | Test on all target platforms early |

---

## Timeline

| Phase | Duration | Deliverable | Assignee |
|-------|----------|-------------|----------|
| 25A | 4 hours | 6 YAML configuration files | TBD |
| 25B | 1 hour | CMakeLists.txt updates | TBD |
| 25C | 2 hours | Input data staged | CI Team |
| 25D | 2 hours | Validation enhancements | TBD |
| 25E | 1 hour | Documentation updates | TBD |
| 25F | 2 hours | CI pipeline integration | TBD |
| Test | 4 hours | Full validation on 3 platforms | TBD |

**Total Estimated Effort**: ~16 hours

---

## References

- **GitHub Issue**: [NOAA-EMC/global-workflow#4318](https://github.com/NOAA-EMC/global-workflow/issues/4318)
- **Existing CTest README**: `dev/ctests/README.md`
- **CMake Test Framework**: `dev/ctests/CMakeLists.txt`
- **Wave Model Documentation**: `docs/wave_model_guide.md`
- **WaveWatch III User Guide**: External reference

---

## Related SDDs

- Phase 20: COM Compliance Tools (output validation integration)
- Phase 22: Validation Benchmarking Subsystem (test metrics tracking)

---

## Appendix: Wave Job Script Inventory

Reference scripts for test development:

| Job Card | Ex-Script | Purpose |
|----------|-----------|---------|
| `waveinit.sh` | `exgfs_wave_init.sh` | Grid initialization |
| `waveprep.sh` | `exgfs_wave_prep.sh` | Boundary forcing prep |
| `wavepostsbs.sh` | `exgfs_wave_postsbs.sh` | Spectral bin stats |
| `wavebndpnt.sh` | `exgfs_wave_bndpnt.sh` | Boundary points |
| `wavebndpntbll.sh` | `exgfs_wave_bndpntbll.sh` | Point bulletins |
| `wavepostpnt.sh` | `exgfs_wave_postpnt.sh` | Point post-processing |
| `waveawipsbulls.sh` | `exgfs_wave_awipsbulls.sh` | AWIPS bulletins |
| `waveawipsgridded.sh` | `exgfs_wave_awipsgridded.sh` | AWIPS gridded |
| `wavegempak.sh` | `exgfs_wave_gempak.sh` | GEMPAK products |
