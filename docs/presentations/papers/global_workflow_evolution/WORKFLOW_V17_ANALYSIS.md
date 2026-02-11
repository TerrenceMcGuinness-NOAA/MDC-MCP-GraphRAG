# Global Workflow v17+ Parallel Sequencing Analysis

## Overview

This document summarizes the comprehensive analysis comparing the v16 workflow diagram to the current global-workflow implementation (commit 2a679b4a).

## Key Findings

### Task Count Expansion
- **v16**: ~50 J-jobs
- **v17+**: 89 J-jobs (78% increase)

### New Analysis Systems

#### 1. JEDI Atmospheric Analysis (Replaces/Complements GSI)
```
atmanlinit → atmanlvar → atmanlfv3inc → atmanlfinal
```
- Modern JEDI-based data assimilation
- Supports both GSI and JEDI paths simultaneously

#### 2. JEDI Ensemble Analysis
```
atmensanlinit → atmensanlobs → atmensanlsol → atmensanlletkf → atmensanlfv3inc → atmensanlfinal
```
- New split obs/sol path for parallelization
- LETKF solver option

#### 3. Marine Analysis System (SOCA - New)
```
prepoceanobs → marinebmatinit → marinebmat → marineanlinit → marineanlvar → marineanlchkpt → marineanlfinal
```
- Complete ocean/ice data assimilation
- Ensemble path: marineanlletkf, marineanlecen

#### 4. Aerosol Analysis (New)
```
aeroanlgenb → aeroanlinit → aeroanlvar → aeroanlfinal
```
- Full JEDI-based aerosol DA system

#### 5. Snow Analysis (New)
- `snowanl` - Deterministic snow analysis
- `esnowanl` - Ensemble snow analysis

### New Product Tasks
| Task | Description |
|------|-------------|
| ocean_prod | Ocean product generation |
| ice_prod | Sea ice product generation |
| atmanlupp | Analysis-time UPP processing |
| atmanlprod | Analysis products |
| goesupp | GOES satellite post-processing |

### Archive System Modernization
**v16**: Single `arch` task
**v17+**: Split into verification and tarball phases
- `arch_vrfy` / `earc_vrfy` - Archive verification
- `arch_tars` / `earc_tars` - Tarball creation
- `globus_arch` / `globus_earc` - Globus transfer support
- `cleanup` - Explicit cleanup task

### Wave Enhancements
- `wavegempak` - Wave GEMPAK products (new)
- `waveawipsbulls` - Wave AWIPS bulletins (new)
- `waveawipsgridded` - Wave AWIPS gridded products (new)

### New Application Types
| Application | Mode | Tasks |
|-------------|------|-------|
| GFS | cycled | Full 89 task set |
| GFS | forecast-only | Reduced task set |
| GEFS | forecast-only | 21 tasks, ensemble support |
| SFS | forecast-only | 18 tasks, subseasonal |
| GCAFS | cycled | Air quality + climate |
| GCAFS | forecast-only | Simplified GCAFS |

### Removed/Deprecated Tasks
| v16 Task | Status | Notes |
|----------|--------|-------|
| gldas | Removed | GLDAS land DA deprecated |
| post | Renamed | Now atmupp + atmos_prod |
| arch | Split | Now arch_vrfy + arch_tars |

## Generated Artifacts

1. **workflow_v17_parallel_sequencing.tex** - LaTeX source with TikZ workflow diagram
2. **workflow_v17_parallel_sequencing.pdf** - 4-page PDF with:
   - Full workflow diagram color-coded by task type
   - Changes from v16 table
   - New tasks inventory
   - Application type summary

## Color Coding in Diagram

| Color | Task Type |
|-------|-----------|
| Light Blue | GDAS/GFS standard tasks |
| Sky Blue | JEDI analysis tasks |
| Teal | Marine analysis tasks |
| Gold | Aerosol analysis tasks |
| Alice Blue | Snow analysis tasks |
| Light Green | New in v17+ |
| Yellow | EnKF/Ensemble tasks |
| Pink | Metatasks |
| Purple | Wave tasks |
| Orange | Verification tasks |

## Analysis Method

This analysis was performed using:
1. MCP `list_job_scripts` tool - Retrieved 89 J-job inventory
2. MCP `get_workflow_structure` tool - Component structure analysis
3. MCP `find_dependencies` tool - GGSR dependency traversal
4. Direct codebase analysis:
   - `gfs_tasks.py` - 89 task methods
   - `gefs_tasks.py` - 21 task methods
   - `sfs_tasks.py` - 18 task methods
   - `gfs_cycled.py` - Task ordering for cycled mode
   - `gfs_forecast_only.py` - Task ordering for forecast-only

## References

- global-workflow commit: 2a679b4a
- v16 reference diagram (provided)
- Application factory: `dev/workflow/applications/`
- Rocoto task definitions: `dev/workflow/rocoto/`
