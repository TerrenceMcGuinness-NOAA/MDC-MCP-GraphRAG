# Phase 45: EnKF Surface Analysis (esfc) CTest — CI Coverage Gap Closure

**Version**: 1.0.0
**Status**: Planned
**Created**: 2025-06-08
**Author**: AI Assistant + Terry McGuinness
**Dependency**: CTest framework (dev/ctests/), C48_gsienkf_atmDA CI experiment, config.resources esfc fix (cpu_overutilize branch)
**Archaeology**: Root cause analysis of enkfgfs_esfc Slurm failure on Orion nightly CI (2025-06), published as [GitHub Gist](https://gist.github.com/TerrenceMcGuinness-NOAA/fd0dfe633cca376f4199a9b56923050e)

---

## 1. Executive Summary

The `enkfgdas_esfc` job (ensemble surface analysis via `global_cycle`) is the **only EnKF DA job that interacts with Slurm resource allocation in a shared-node configuration**, and it is the job that failed on Orion due to CPU oversubscription (`srun: error: Unable to create step for job: More processors requested than permitted`). Despite this, **zero CTests exist for any EnKF DA job**, and the nightly CI experiments that exercise EnKF DA (`C48_gsienkf_atmDA`, `C48_ufsenkf_atmDA`) are **skipped on both MSU platforms** (Orion, Hercules) — the exact platforms where the bug manifests.

This phase constructs a standalone CTest for the `gdas_enkf_sfc` JJOB that:

1. Validates the resource allocation fix (`memory="96GB"`, export consistency) from the `cpu_overutilize` branch
2. Exercises the `global_cycle` executable on ensemble surface restart tiles
3. Can run on **all HPC platforms** including Orion and Hercules (no `skip_ci_on_hosts` exclusion)
4. Produces deterministic, comparable output (`sfcanl_data.tile{1-6}.nc` per member)
5. Fills the first EnKF DA slot in the CTest matrix (currently 15 tests, all forecast/post-processing)

### Motivation

The Orion nightly failure exposed a **systemic CI blind spot**: MSU systems (Orion 40-core nodes, Hercules 80-core nodes) are the smallest-node platforms AND the only ones that skip EnKF experiments. The resource allocation bug was invisible to CI because the platforms where it matters most are the ones where it's never tested.

### Actionable vs Notional

| Tier | What | Status |
|------|------|--------|
| **ACTIONABLE** | CTest YAML, CMakeLists.txt entry, baseline data generation on Hera, validation on Hera | Can be built with current infrastructure |
| **NOTIONAL** | Orion/Hercules baseline staging, full EnKF chain CTests (eobs/ediag/eupd/ecen/epos), skip_ci_on_hosts removal for C48_gsienkf_atmDA | Requires coordination with NCO/role.glopara for baseline data |

---

## 2. Problem Analysis

### 2.1 The CI Coverage Gap

**Platform CI Matrix** (from `dev/ci/gitlab-ci-hosts.yml`):

| Platform | Cores/Node | EnKF CI Cases | Vulnerable? |
|----------|-----------|---------------|-------------|
| Hera | 40 | C48_gsienkf_atmDA, C48_ufsenkf_atmDA | Yes (40 cores), but covered by CI |
| GAEAC6 | 128 | C48_gsienkf_atmDA, C48_ufsenkf_atmDA | No (large nodes) |
| Ursa | 40 | C48_gsienkf_atmDA, C48_ufsenkf_atmDA | Yes, but covered |
| **Orion** | **40** | **NONE** | **Yes — UNCOVERED** |
| **Hercules** | **80** | **NONE** | **Yes — UNCOVERED** |

The `C48_gsienkf_atmDA.yaml` experiment explicitly skips MSU:
```yaml
skip_ci_on_hosts:
  - gaeac5
  - orion        # <-- exactly where the bug hit
  - hercules     # <-- also vulnerable (80 cores, half-node = 40)
  - awsepicglobalworkflow
```

### 2.2 Root Cause Recap

The esfc job in `config.resources` allocated half a node (`node_numerator=1, node_denominator=2`) without `is_exclusive=True` or `memory` reservation. On Orion:
- Half node = 20 task slots
- `NTHREADS_CYCLE` defaulted to 14 (via `ORION.env` esfc block)
- `srun --cpus-per-task=14` with 12 tasks requested 168 CPUs on a 20-slot allocation
- Result: `More processors requested than permitted`

**Fix applied** (committed as `deb3a108` on `cpu_overutilize` branch):
```bash
# In config.resources esfc block:
memory="96GB"                              # prevent co-tenant memory pressure
export threads_per_task_cycle=${threads_per_task}          # was missing
export tasks_per_node_cycle=$(( max_tasks_per_node / threads_per_task_cycle ))  # was missing
```

### 2.3 Why a CTest (Not Just CI Coverage Removal)

Removing `orion` and `hercules` from `skip_ci_on_hosts` would enable EnKF nightly testing on MSU, but:
1. The full `C48_gsienkf_atmDA` experiment runs the **entire EnKF chain** (eobs → ediag → eupd → esfc → ecen → epos → efcs), consuming significant HPC allocation
2. CTests are **isolated, reproducible, fast** — they test a single JJOB with staged inputs
3. CTests run in the CMake/CTest framework, not Rocoto, so they can be part of PR validation
4. A CTest for esfc directly validates the resource allocation and `global_cycle` execution

### 2.4 Prior Art — Existing CTest Patterns

**15 existing CTests** (all in `dev/ctests/CMakeLists.txt`):

| Case | Jobs | Type |
|------|------|------|
| C48_ATM | gfs_stage_ic, gfs_fcst_seg0, gfs_atmos_prod_f000-f002, gfs_tracker, gfs_genesis | Deterministic ATM |
| C48_S2SW | gfs_stage_ic, gfs_fcst_seg0, gfs_ice/ocean_prod, gfs_wave* (6 jobs) | Coupled S2SW |
| C48_S2SWA_gefs | gefs_fcst_mem001_seg0 | Ensemble (single member) |

**Key pattern**: The existing C48_S2SWA_gefs YAML demonstrates how ensemble member data is organized — under `mem001/model/atmos/input/` with separate tile files. This pattern extends directly to EnKF DA members.

**No DA CTests exist.** This would be the first.

---

## 3. Technical Specification

### 3.1 New CTest: `C48_gsienkf_atmDA-gdas_enkf_sfc`

#### Naming Convention
Following the established `${CASE}-${JOB}` pattern:
- **CASE**: `C48_gsienkf_atmDA` (reuses the existing CI experiment case definition)
- **JOB**: `gdas_enkf_sfc` (the rocoto task name from `gfs_tasks.py`)
- **TEST_NAME**: `C48_gsienkf_atmDA-gdas_enkf_sfc`
- **TEST_DATE**: `2024022400` (matching the C48_gsienkf_atmDA experiment idate `2024022318` → first analysis cycle at `2024022400`)

#### Files to Create

| File | Purpose |
|------|---------|
| `dev/ctests/cases/C48_gsienkf_atmDA-gdas_enkf_sfc.yaml` | CTest case YAML (input/output file definitions) |
| Entry in `dev/ctests/CMakeLists.txt` | CMake registration of the test |

#### Files to Modify

| File | Change |
|------|--------|
| `dev/ctests/CMakeLists.txt` | Add `AddJJOBTest()` call |

### 3.2 Execution Call Chain

Understanding the full call chain is critical for knowing what inputs need staging and what outputs to validate.

```
CTest execute.sh
  └─ rocotoboot --dryrun → generates jobcard
      └─ sbatch jobcard
          └─ dev/job_cards/rocoto/esfc.sh
              └─ load_modules.sh gsi
              └─ dev/jobs/JGLOBAL_ENKF_SFC
                  └─ jjob_header.sh -e "esfc" -c "base esfc"
                      └─ source config.base
                      └─ source config.esfc
                          └─ source config.resources esfc  ← OUR FIX LIVES HERE
                  └─ dev/scripts/exglobal_enkf_sfc.sh
                      ├─ [if DO_GSISOILDA] ush/regrid_gsiSfcIncr_to_tile.sh
                      │     └─ exec/regridStates.x
                      ├─ [loop: tiles 1-6]
                      │     ├─ Copy sfc_data restart tiles (per member)
                      │     ├─ Copy grid/orog fix files (per member)
                      │     └─ ush/global_cycle.sh
                      │           └─ exec/global_cycle  ← MAIN EXECUTABLE
                      └─ Copy sfcanl_data tiles to COMOUT (per member)
```

### 3.3 Environment Variables

The JJOB (`JGLOBAL_ENKF_SFC`) sources `config.base` and `config.esfc`, which together establish:

| Variable | Value for C48_gsienkf_atmDA | Source |
|----------|---------------------------|--------|
| `RUN` | `enkfgdas` | config.base (cycled mode) |
| `CASE_ENS` | `C48` | experiment yaml (resensatmos: 48) |
| `NMEM_ENS` | `2` | experiment yaml (nens: 2) |
| `DOENKFONLY_ATM` | `YES` | gsienkf_atmDA_defaults.ci.yaml |
| `DONST` | `NO` | config.esfc (forced when DOENKFONLY_ATM=YES) |
| `DO_GSISOILDA` | `NO` | config.esfc default |
| `DOIAU_ENKF` | `NO` | gsienkf_atmDA_defaults.ci.yaml (DOIAU: "NO") |
| `DOSFCANL_ENKF` | `YES` | exglobal_enkf_sfc.sh default |
| `assim_freq` | `6` | config.base default |
| `PDY` | `20240224` | from TEST_DATE |
| `cyc` | `00` | from TEST_DATE |
| `gPDY` | `20240223` | PDY - assim_freq |
| `gcyc` | `18` | cyc - assim_freq |
| `GDUMP` | `gdas` | JGLOBAL_ENKF_SFC |
| `GDUMP_ENS` | `enkfgdas` | JGLOBAL_ENKF_SFC |
| `OCNRES` | `500` | config.base for C48 |
| `ntiles` | `6` | exglobal_enkf_sfc.sh default |

### 3.4 Input Files (to Stage)

With `DOIAU_ENKF=NO` and `DOSFCANL_ENKF=YES`, the script follows the **DOSFCANL_ENKF path** (lines ~240-310 of `exglobal_enkf_sfc.sh`).

For **each member** (mem001, mem002 with nens=2) and **each tile** (1-6):

#### Per-Member Per-Tile Inputs

| Source Path | Description |
|-------------|-------------|
| `enkfgdas.{gPDY}/{gcyc}/{gmemchar}/model/atmos/restart/{PDY}.{cyc}0000.sfc_data.tile{n}.nc` | Previous cycle sfc restart (from COMIN_ATMOS_RESTART_MEM_PREV) |
| `FIXglobal/orog/{CASE}/{CASE}_grid.tile{n}.nc` | Grid specification (from FIX) |
| `FIXglobal/orog/{CASE}/{CASE}.mx{OCNRES}_oro_data.tile{n}.nc` | Orography data (from FIX) |

#### Observation Files (Shared)

| Source Path | Description |
|-------------|-------------|
| `gdas.{PDY}/{cyc}/obs/gdas.t{cyc}z.seaice.5min.blend.grb` | Sea ice analysis (FNACNA) |
| `gdas.{PDY}/{cyc}/obs/gdas.t{cyc}z.snogrb_t{JCAP}.{LONB}.{LATB}` | Current snow analysis (FNSNOA) — may fallback to t1534.3072.1536 |
| `gdas.{gPDY}/{gcyc}/obs/gdas.t{gcyc}z.snogrb_t{JCAP}.{LONB}.{LATB}` | Previous snow analysis (FNSNOG) — may fallback to t1534.3072.1536 |

Where for C48: `res=48`, `JCAP_CASE=94`, `LATB_CASE=96`, `LONB_CASE=192`

#### Concrete File List (C48, nens=2, TEST_DATE=2024022400)

```
# Observation files
enkfgdas.20240224/00/obs/ or gdas.20240224/00/obs/
  gdas.t00z.seaice.5min.blend.grb
  gdas.t00z.snogrb_t94.192.96       (or gdas.t00z.snogrb_t1534.3072.1536)

gdas.20240223/18/obs/
  gdas.t18z.snogrb_t94.192.96       (or gdas.t18z.snogrb_t1534.3072.1536)

# Member 001 - previous cycle restarts
enkfgdas.20240223/18/mem001/model/atmos/restart/
  20240224.000000.sfc_data.tile1.nc
  20240224.000000.sfc_data.tile2.nc
  20240224.000000.sfc_data.tile3.nc
  20240224.000000.sfc_data.tile4.nc
  20240224.000000.sfc_data.tile5.nc
  20240224.000000.sfc_data.tile6.nc

# Member 002 - previous cycle restarts
enkfgdas.20240223/18/mem002/model/atmos/restart/
  20240224.000000.sfc_data.tile1.nc
  20240224.000000.sfc_data.tile2.nc
  20240224.000000.sfc_data.tile3.nc
  20240224.000000.sfc_data.tile4.nc
  20240224.000000.sfc_data.tile5.nc
  20240224.000000.sfc_data.tile6.nc

# FIX files (from FIXglobal, not COMROOT — may need symlink or env override)
FIXglobal/orog/C48/
  C48_grid.tile{1-6}.nc              (6 files)
  C48.mx500_oro_data.tile{1-6}.nc    (6 files)
```

**Total input files**: ~2 obs + possibly 2 snow + 12 sfc_data + 12 grid/orog = **~28 files**

### 3.5 Output Files (to Validate)

The DOSFCANL_ENKF path produces:

```
# Member 001
enkfgdas.20240224/00/mem001/model/atmos/restart/
  20240224.000000.sfcanl_data.tile1.nc
  20240224.000000.sfcanl_data.tile2.nc
  20240224.000000.sfcanl_data.tile3.nc
  20240224.000000.sfcanl_data.tile4.nc
  20240224.000000.sfcanl_data.tile5.nc
  20240224.000000.sfcanl_data.tile6.nc

# Member 002
enkfgdas.20240224/00/mem002/model/atmos/restart/
  20240224.000000.sfcanl_data.tile1.nc
  20240224.000000.sfcanl_data.tile2.nc
  20240224.000000.sfcanl_data.tile3.nc
  20240224.000000.sfcanl_data.tile4.nc
  20240224.000000.sfcanl_data.tile5.nc
  20240224.000000.sfcanl_data.tile6.nc
```

**Total output files**: 12 `sfcanl_data.tile{1-6}.nc` (2 members × 6 tiles)

**Validation**: Binary comparison (`cmpfiles`) of each output against the baseline in STAGED_CTESTS.

### 3.6 FIX File Strategy

The `global_cycle` executable requires FIX files (`FIXglobal/orog/C48/`) which are part of the build tree, not COMROOT. Two approaches:

1. **Preferred**: FIX files are already available via `HOMEglobal` (they're in `fix/orog/C48/` within the global-workflow checkout). The JJOB sources `config.base` which sets `FIXglobal` to point to the checkout's fix directory. No staging needed — the CTest `setup.sh` creates the experiment with `create_experiment.py` which wires `FIXglobal` correctly.

2. **Fallback**: If FIX files are not present in the checkout (submodule not initialized), the `create_experiment.py` will fail at setup. This is the same behavior as any other CTest and is handled by the CI infrastructure.

---

## 4. Implementation Steps

### Step 1: Generate Baseline Data on Hera

Before writing the CTest YAML, baseline data must exist in `STAGED_CTESTS`. The C48_gsienkf_atmDA experiment already runs on Hera nightly, so the baseline data should already exist at:

```bash
# On Hera:
STAGED_CTESTS=/scratch3/NCEPDEV/global/role.glopara/GFS_CI_CD/HERA/BUILDS/GITLAB/stable/RUNTESTS
```

**Verification command**:
```bash
# Check if the experiment COMROOT exists
ls ${STAGED_CTESTS}/COMROOT/C48_gsienkf_atmDA_*/enkfgdas.20240224/00/mem001/model/atmos/restart/

# Expected: sfcanl_data.tile{1-6}.nc files from the nightly run
```

If baseline data doesn't exist or uses different dates, you must:
1. Run the C48_gsienkf_atmDA experiment manually on Hera
2. Copy the COMROOT output to `STAGED_CTESTS/COMROOT/`
3. Update `TEST_DATE` in the CTest to match the available baselines

**Critical**: The `TEST_DATE` in the `AddJJOBTest()` call and the dates in the YAML must match what's available in the staged baselines. Check the nightly output to determine the correct cycle date.

### Step 2: Determine Correct TEST_DATE

```bash
# On Hera: Find what PSLOTs exist for gsienkf_atmDA
ls ${STAGED_CTESTS}/COMROOT/ | grep gsienkf

# Then check which cycle dates have esfc output
PSLOT=$(ls ${STAGED_CTESTS}/COMROOT/ | grep gsienkf | head -1)
ls ${STAGED_CTESTS}/COMROOT/${PSLOT}/enkfgdas.*/*/mem001/model/atmos/restart/ | head -20

# The TEST_DATE should be the cycle where sfcanl_data files exist
# Format: YYYYMMDDHH (e.g., 2024022400)
```

### Step 3: Create the CTest Case YAML

Create `dev/ctests/cases/C48_gsienkf_atmDA-gdas_enkf_sfc.yaml`.

**Template** (adjust dates based on Step 2 findings):

```yaml
# CTest Case: C48_gsienkf_atmDA-gdas_enkf_sfc
#
# Purpose: Validate the EnKF ensemble surface analysis job (esfc).
# This is the first EnKF DA CTest. It exercises global_cycle on
# ensemble member surface restarts, validating:
#   - Resource allocation (memory="96GB", shared-node safety)
#   - Surface field updates via global_cycle
#   - Correct per-member, per-tile output generation
#
# Context: The esfc job failed on Orion (2025-06) due to CPU
# oversubscription on shared nodes. This CTest ensures the fix
# (config.resources esfc block: memory reservation + export
# consistency) produces correct output.
#
# Experiment: C48_gsienkf_atmDA (C96 det, C48 ensemble, nens=2)
# Config: DOENKFONLY_ATM=YES, DOIAU=NO, DOSFCANL_ENKF=YES
# Job chain: eobs → ediag → eupd → [esfc] → ecen → epos

{% set cyc = TEST_DATE | strftime('%H') %}
{% set PDY = TEST_DATE | to_YMD %}

{% set assim_freq_hours = 6 %}
{% set H_offset = '-' + assim_freq_hours | string + 'H' %}
{% set H_timedelta = H_offset | to_timedelta %}
{% set PREV_DATE = TEST_DATE | add_to_datetime(H_timedelta) %}
{% set gcyc = PREV_DATE | strftime('%H') %}
{% set gPDY = PREV_DATE | to_YMD %}

{% set SRC_DIR = STAGED_CTESTS + '/COMROOT/' + PSLOT %}
{% set DST_DIR = RUNTESTS + '/COMROOT/' + TEST_NAME %}

input_files:
    mkdir:
        # Observation directories
        - {{ DST_DIR }}/gdas.{{ PDY }}/{{ cyc }}/obs
        - {{ DST_DIR }}/gdas.{{ gPDY }}/{{ gcyc }}/obs

        # Member restart directories (previous cycle)
        - {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem001/model/atmos/restart
        - {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem002/model/atmos/restart

        # Member output restart directories (current cycle)
        - {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem001/model/atmos/restart
        - {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem002/model/atmos/restart

    copy:
        # =================================================================
        # Observation files (sea ice + snow analyses)
        # =================================================================
        - [{{ SRC_DIR }}/gdas.{{ PDY }}/{{ cyc }}/obs/gdas.t{{ cyc }}z.seaice.5min.blend.grb,
           {{ DST_DIR }}/gdas.{{ PDY }}/{{ cyc }}/obs/gdas.t{{ cyc }}z.seaice.5min.blend.grb]

        # Current cycle snow file (may be t1534 fallback — check baseline)
        - [{{ SRC_DIR }}/gdas.{{ PDY }}/{{ cyc }}/obs/gdas.t{{ cyc }}z.snogrb_t1534.3072.1536,
           {{ DST_DIR }}/gdas.{{ PDY }}/{{ cyc }}/obs/gdas.t{{ cyc }}z.snogrb_t1534.3072.1536]

        # Previous cycle snow file
        - [{{ SRC_DIR }}/gdas.{{ gPDY }}/{{ gcyc }}/obs/gdas.t{{ gcyc }}z.snogrb_t1534.3072.1536,
           {{ DST_DIR }}/gdas.{{ gPDY }}/{{ gcyc }}/obs/gdas.t{{ gcyc }}z.snogrb_t1534.3072.1536]

        # =================================================================
        # Member 001 — previous cycle surface restarts (6 tiles)
        # =================================================================
        - [{{ SRC_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile1.nc,
           {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile1.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile2.nc,
           {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile2.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile3.nc,
           {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile3.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile4.nc,
           {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile4.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile5.nc,
           {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile5.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile6.nc,
           {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile6.nc]

        # =================================================================
        # Member 002 — previous cycle surface restarts (6 tiles)
        # =================================================================
        - [{{ SRC_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile1.nc,
           {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile1.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile2.nc,
           {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile2.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile3.nc,
           {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile3.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile4.nc,
           {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile4.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile5.nc,
           {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile5.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile6.nc,
           {{ DST_DIR }}/enkfgdas.{{ gPDY }}/{{ gcyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfc_data.tile6.nc]

output_files:
    cmpfiles:
        # =================================================================
        # Member 001 — surface analysis output (6 tiles)
        # =================================================================
        - [{{ SRC_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile1.nc,
           {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile1.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile2.nc,
           {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile2.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile3.nc,
           {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile3.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile4.nc,
           {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile4.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile5.nc,
           {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile5.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile6.nc,
           {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem001/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile6.nc]

        # =================================================================
        # Member 002 — surface analysis output (6 tiles)
        # =================================================================
        - [{{ SRC_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile1.nc,
           {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile1.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile2.nc,
           {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile2.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile3.nc,
           {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile3.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile4.nc,
           {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile4.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile5.nc,
           {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile5.nc]
        - [{{ SRC_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile6.nc,
           {{ DST_DIR }}/enkfgdas.{{ PDY }}/{{ cyc }}/mem002/model/atmos/restart/{{ PDY }}.{{ cyc }}0000.sfcanl_data.tile6.nc]
```

**IMPORTANT**: The snow observation filenames above use the `t1534.3072.1536` fallback pattern. On Hera, verify which pattern the baseline actually has:
```bash
ls ${STAGED_CTESTS}/COMROOT/${PSLOT}/gdas.20240224/00/obs/ | grep snogrb
```
If the resolution-specific file (`snogrb_t94.192.96`) exists instead, update the YAML accordingly.

### Step 4: Add CMakeLists.txt Entry

Add this block to `dev/ctests/CMakeLists.txt` after the existing GEFS test:

```cmake
# ------------------------------------------------------------------------- #
# EnKF DA Tests (Phase 45 - EnKF esfc CTest)
# ------------------------------------------------------------------------- #
# First EnKF DA CTest. Validates ensemble surface analysis (global_cycle)
# with resource allocation fix for shared-node safety.
# See: sdd_framework/workflows/phase45_enkf_esfc_ctest.md
# ------------------------------------------------------------------------- #

AddJJOBTest(
  CASE "C48_gsienkf_atmDA"
  JOB "gdas_enkf_sfc"
  TEST_DATE "2024022400"
)
```

**Note on TEST_DATE**: The value `2024022400` assumes the first valid analysis cycle from the experiment definition (`idate: 2024022318`, `edate: 2024022406`). The 00Z cycle on 20240224 is the first complete cycle where eupd output (and thus esfc input) would exist. **Verify this against baseline data** — if the baseline has a different cycle, adjust accordingly.

### Step 5: Verify on Hera

```bash
# 1. Build CTests
cd ${HOMEglobal}/dev
mkdir -p build && cd build
cmake .. \
  -DSTAGED_CTESTS=/scratch3/NCEPDEV/global/role.glopara/GFS_CI_CD/HERA/BUILDS/GITLAB/stable/RUNTESTS \
  -DICSDIR_ROOT=/scratch3/NCEPDEV/global/role.glopara/data/ICSDIR \
  -DHPC_ACCOUNT=fv3-cpu

# 2. List all tests (should now include the new one)
ctest -N | grep enkf

# Expected output:
#   test_C48_gsienkf_atmDA-gdas_enkf_sfc_setup
#   test_C48_gsienkf_atmDA-gdas_enkf_sfc_stage
#   test_C48_gsienkf_atmDA-gdas_enkf_sfc_execute
#   test_C48_gsienkf_atmDA-gdas_enkf_sfc_validate

# 3. Run just the setup phase first (creates the experiment)
ctest -R "C48_gsienkf_atmDA-gdas_enkf_sfc_setup" -V

# 4. Run the stage phase (copies inputs from baseline)
ctest -R "C48_gsienkf_atmDA-gdas_enkf_sfc_stage" -V

# 5. Run the execute phase (submits JJOB via Slurm)
ctest -R "C48_gsienkf_atmDA-gdas_enkf_sfc_execute" -V

# 6. Run the validate phase (compares outputs to baseline)
ctest -R "C48_gsienkf_atmDA-gdas_enkf_sfc_validate" -V

# Or run all 4 phases in sequence:
ctest -L "C48_gsienkf_atmDA-gdas_enkf_sfc" -V
```

### Step 6: Debug Common Failures

| Failure Phase | Likely Cause | Fix |
|---------------|-------------|-----|
| **setup** | CASE YAML not found or `create_experiment.py` error | Check `C48_gsienkf_atmDA.yaml` exists in `dev/ci/cases/pr/`. Verify ICSDIR_ROOT has C96C48 initial conditions. |
| **stage** | Baseline files missing in STAGED_CTESTS | Run `ls ${STAGED_CTESTS}/COMROOT/` to verify pslot exists. Check date alignment. |
| **stage** | YAML Jinja2 template error | Run `python -c "from wxflow import ...; ..."` to test template rendering manually |
| **execute** | `rocotoboot --dryrun` fails | Verify `GFS_CI_ROCOTO_PATH` points to the custom dryrun Rocoto build. Check `config.hera` has paths. |
| **execute** | Slurm job fails (the bug we're testing!) | Check `${ROTDIR}/logs/*/enkfgdas_esfc.log`. If `More processors requested` appears, the config.resources fix wasn't picked up — verify branch. |
| **execute** | `global_cycle` segfault or missing FIX | Check FIXglobal path in config.base. Verify `fix/` submodule is initialized. |
| **execute** | Snow file not found warnings | This is usually benign — script handles missing snow gracefully with `CYCLVARS="FSNOL=99999."` |
| **validate** | Output mismatch | May be due to different compiler versions or floating-point differences. Check if files exist first, then investigate numerical diffs. |
| **validate** | Output files don't exist | Job ran but produced no output. Check the JJOB log for `DOSFCANL_ENKF` value — if `NO` (IAU mode), no sfcanl_data produced via this path. Verify `DOIAU_ENKF=NO` in experiment config. |

---

## 5. Rocoto Task Dependency Context

Understanding esfc's position in the EnKF chain helps explain what inputs it expects and why they must be staged:

```
                    ┌──────────┐
                    │   prep   │
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │   eobs   │  enkf observation operator
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │  ediag   │  enkf diagnostics
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │   eupd   │  enkf update (produces analysis increments)
                    └────┬─────┘
                         │
              ┌──────────┼──────────┐
              │          │          │
         ┌────▼─────┐   │     ┌────▼─────┐
         │  [esfc]  │   │     │   ecen   │  enkf recenter
         │  THIS    │   │     └────┬─────┘
         │  TEST    │   │          │
         └────┬─────┘   │          │
              │          │          │
              └──────────┼──────────┘
                         │
                    ┌────▼─────┐
                    │   efcs   │  enkf forecasts
                    └──────────┘
```

The CTest stages inputs that would normally come from:
- **prep** (observations): sea ice, snow — staged from `gdas.*/obs/`
- **previous cycle efcs** (forecasts): sfc_data restarts — staged from `enkfgdas.*/mem*/model/atmos/restart/`
- **FIX data** (static): grid, orography — available from the checkout's `fix/` directory

The esfc job does **not** depend on eupd for its actual computation (it runs global_cycle, not analysis). The Rocoto dependency on eupd is for **workflow ordering** — ensuring the analysis update is complete before updating surface fields. In the CTest, inputs are staged directly, bypassing the workflow dependency.

---

## 6. Key Implementation Decisions for the Executing Agent

### 6.1 Date Alignment

The CTest framework passes `TEST_DATE` as a single `YYYYMMDDHH` string. The YAML uses Jinja2 filters to extract `PDY` and `cyc`. The esfc job also needs the **previous cycle** date (`gPDY`, `gcyc`), which is `TEST_DATE - assim_freq` (6 hours). The YAML template computes this using `add_to_datetime` with a `-6H` timedelta, following the pattern in `C48_S2SWA_gefs-gefs_fcst_mem001_seg0.yaml`.

### 6.2 RUN Prefix

In the C48_gsienkf_atmDA experiment, the EnKF jobs run under `RUN=enkfgdas`. The COMROOT directory layout uses `enkfgdas.YYYYMMDD/HH/memNNN/`. This is different from deterministic runs (`gdas.YYYYMMDD/HH/`). The JJOB sets:
```bash
export GDUMP="gdas"
export GDUMP_ENS="enkfgdas"
```
Observation files live under `gdas.*` (deterministic), while ensemble restart files live under `enkfgdas.*`.

### 6.3 OPREFIX / GPREFIX

The JJOB constructs filename prefixes that the script uses for obs files:
```bash
OPREFIX="${RUN/enkf/}.t${cyc}z."   # "gdas.t00z." (strips "enkf" prefix)
GPREFIX="${GDUMP}.t${gcyc}z."      # "gdas.t18z."
```
So obs files are named like `gdas.t00z.seaice.5min.blend.grb`, not `enkfgdas.t00z.*`.

### 6.4 Snow File Resolution Fallback

The script first looks for `snogrb_t94.192.96` (C48-specific), then falls back to `snogrb_t1534.3072.1536`. For the CTest YAML, **use whatever the baseline actually has**. The t1534 fallback is more likely since C48 resolution-specific snow files are rarely generated.

### 6.5 Rocoto Dryrun Requirement

The `execute.sh.in` script requires a custom Rocoto build with `--dryrun` support. This generates the Slurm jobcard without scheduling through Rocoto. The CI platforms (`config.hera`, etc.) define `GFS_CI_ROCOTO_PATH` pointing to this custom build. If it's missing, execute will fail with `ERROR: Custom Rocoto build with dryrun feature not found`.

### 6.6 The JOB Name for Rocoto Dryrun

The `execute.sh` passes `JOB` to `rocotoboot --dryrun -t "${JOB}"`. The JOB must match the Rocoto task name exactly:
- In `gfs_tasks.py`: `task_name = f'{self.run}_esfc'` → `enkfgdas_esfc`
- But the CTest `AddJJOBTest` JOB parameter should be just the task suffix that rocotoboot maps: `gdas_enkf_sfc`

**Verify this mapping**: Look at the generated XML from the C48_gsienkf_atmDA experiment to see the exact task name used by Rocoto. It may be `enkfgdas_esfc` (from gfs_tasks.py) rather than `gdas_enkf_sfc`. The correct value is whatever appears as the `<task name="...">` attribute in the workflow XML.

```bash
# On Hera, after setup.sh runs:
grep -o 'task name="[^"]*esfc[^"]*"' ${RUNTESTS}/COMROOT/${TEST_NAME}*/EXPDIR/*/enkfgdas*.xml
```

### 6.7 Module Loading

The job card `esfc.sh` loads `gsi` modules via `load_modules.sh gsi`. This ensures the GSI/global_cycle executables and libraries are available. The CTest execute phase submits the real job card via Slurm, so module loading happens inside the batch job, not in the CTest wrapper.

---

## 7. Validation Criteria

A successful CTest run means:

1. **setup**: `create_experiment.py` completes without error, experiment directory exists with config files
2. **stage**: All input files copied from STAGED_CTESTS to RUNTESTS without error
3. **execute**: Slurm job completes with status COMPLETED (not FAILED/CANCELLED/TIMEOUT)
4. **validate**: All 12 `sfcanl_data.tile{1-6}.nc` files (2 members × 6 tiles) match baseline bit-for-bit

If the execute phase fails with the original `srun: More processors requested` error on any platform, it confirms the resource allocation fix was not applied and needs to be merged.

---

## 8. Future Work (Notional)

### 8.1 Remove MSU skip_ci_on_hosts

Once the esfc CTest is validated on Hera, consider removing `orion` and `hercules` from `C48_gsienkf_atmDA.yaml`'s `skip_ci_on_hosts` to enable full EnKF nightly coverage on MSU. This requires:
- Ensuring baseline data is staged on both platforms
- Verifying role.glopara disk quotas can accommodate the additional experiment data

### 8.2 Additional EnKF DA CTests

The esfc CTest is a beachhead. Future work could add:
- `gdas_enkf_eupd` — validates the EnKF update with increments
- `gdas_enkf_ecen` — validates recentering
- `gdas_enkf_eobs` — validates observation operator

### 8.3 Cross-Platform CTest Runs

Currently CTests only run during PR builds on the platform where the PR is opened. Extending CTest runs to MSU platforms specifically for EnKF tests would close the coverage gap permanently.

---

## Appendix A: File Reference

| File | Role |
|------|------|
| `dev/ctests/CMakeLists.txt` | CTest registration (AddJJOBTest function) |
| `dev/ctests/cases/*.yaml` | Per-test input/output definitions (Jinja2) |
| `dev/ctests/scripts/setup.sh.in` | Phase 1: create_experiment.py |
| `dev/ctests/scripts/stage.sh.in` → `stage.py` | Phase 2: copy inputs from baseline |
| `dev/ctests/scripts/execute.sh.in` | Phase 3: rocotoboot --dryrun → sbatch |
| `dev/ctests/scripts/validate.sh.in` → `validate.py` | Phase 4: compare outputs to baseline |
| `dev/ci/cases/pr/C48_gsienkf_atmDA.yaml` | Experiment definition (C96det, C48ens, nens=2) |
| `dev/ci/cases/yamls/gsienkf_atmDA_defaults.ci.yaml` | Experiment defaults (DOENKFONLY_ATM=YES) |
| `dev/ci/platforms/config.hera` | Hera paths (STAGED_CTESTS, ROCOTO, etc.) |
| `dev/parm/config/gfs/config.esfc` | Job-specific config (DONST, DO_GSISOILDA logic) |
| `dev/parm/config/gfs/config.resources` | Resource allocation (esfc block — our fix) |
| `dev/jobs/JGLOBAL_ENKF_SFC` | JJOB entry point |
| `dev/job_cards/rocoto/esfc.sh` | Rocoto job card (loads gsi modules, calls JJOB) |
| `dev/scripts/exglobal_enkf_sfc.sh` | Main script (global_cycle per member/tile) |
| `dev/workflow/rocoto/gfs_tasks.py` | Rocoto task definitions (esfc at line ~3048) |

## Appendix B: Commit Reference

- **Fix commit**: `deb3a108` on `cpu_overutilize` branch
- **Changes**: `dev/parm/config/gfs/config.resources` (esfc block: memory + exports)
- **Also in commit**: Deleted 4 orphan GEFS configs (config.fetch, config.wavepostbndpnt, config.wavepostbndpntbll, config.wavepostpnt)

## Appendix C: Platform Node Sizes

| Platform | Cores/Node | Memory/Node | Half-Node Tasks | Vulnerable to esfc Bug? |
|----------|-----------|-------------|-----------------|------------------------|
| Hera | 40 | 180 GB | 20 | Yes (but CI covered) |
| Orion | 40 | 180 GB | 20 | **Yes — UNCOVERED** |
| Hercules | 80 | 512 GB | 40 | **Yes — UNCOVERED** |
| GAEAC6 | 128 | 230 GB | 64 | Less likely (large nodes) |
| WCOSS2 | 128 | 235 GB | 64 | Less likely (large nodes) |
