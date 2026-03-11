# enkfgfs_esfc Nightly CI/CD Failure Analysis — Orion

**Date:** March 10, 2026
**Platform:** Orion (MSU HPC)
**Build:** `nightly_0_bbe30912_10286`
**Experiment:** `C96C48mx500_S2SW_cyc_gfs_bbe30912-10286`
**Cycle:** `2021122018` (December 20, 2021 18Z)
**Job ID:** Slurm 22576580 (PID 318286)
**Node:** `orion-13-24`
**Source Log:** [emcbot/enkfgfs_esfc.log](https://gist.github.com/emcbot/72a642e0226d8dd5db27e6f7c2c81566)

---

## Root Cause

**FATAL: Slurm `srun` step failed — "More processors requested than permitted"**

The `global_cycle` executable was launched via `srun -n 12` but the Slurm job allocation on `orion-13-24` did not have enough processor slots available to create a new step with 12 tasks.

From the errfile (log lines 1211–1212):

```
srun: error: Unable to create step for job 22576580: More processors requested than permitted
[2026-03-09T21:45:39.262] error: *** JOB 22576580 ON orion-13-24 CANCELLED AT 2026-03-09T21:45:39 DUE to SIGNAL Terminated ***
```

## Failure Chain

```
esfc.sh →
  JGLOBAL_ENKF_SFC →
    exglobal_enkf_sfc.sh →
      global_cycle.sh →
        srun -n 12 --cpus-per-task=1 global_cycle  ← FAILED (exit code 1)
          err_exit "Failed to update surface fields!"
```

## Resource Allocation Analysis

### What config.resources requested

| Parameter | Value | Source |
|-----------|-------|--------|
| `ntasks` | 12 | `NMEM_ENS(2) * ntiles(6) = 12` |
| `threads_per_task` | 1 | config.resources |
| `node_numerator` | 1 | config.resources |
| `node_denominator` | 2 | config.resources |
| `tasks_per_node` | 20 | `1 * 40 / 2 = 20` |
| `max_tasks_per_node` (Orion) | 40 | Machine default |

The esfc step is configured to use **half a node** (1/2 ratio) to leave memory for regridding operations. This means Rocoto/Slurm should allocate 1 node with 20 task slots. The `srun -n 12` call to `global_cycle` should fit within 20 available slots.

### What actually happened

The `srun -n 12` call inside `global_cycle.sh` failed because the Slurm allocation for job 22576580 did not have 12 processor slots available. This can occur when:

1. **The Slurm job was allocated fewer resources than requested** — Slurm may have scheduled the job on a partially-available node or with reduced resources due to cluster load
2. **Prior srun steps consumed the allocation** — The `exglobal_enkf_sfc.sh` script stages files using CFP (Consolidated File Processing with `USE_CFP=YES`), and if a prior srun step was still holding resources, the subsequent `global_cycle.sh` srun would fail
3. **Non-exclusive allocation overlap** — The esfc step does NOT set `is_exclusive=True` (unlike ecen/epos), so the half-node allocation could overlap with other jobs consuming available task slots

### Most likely cause

The esfc step **does not set `is_exclusive=True`** in config.resources. It only requests `node_numerator=1, node_denominator=2` (half a node). On a shared node, another job's srun steps could have consumed the remaining slot capacity, leaving fewer than 12 processors available for the `global_cycle` srun step.

## Contributing Warnings (Non-Fatal)

These warnings occurred earlier in the log but did **not** cause the failure:

| Line | Warning | Impact |
|------|---------|--------|
| 103 | `sed: can't read .../COMROOT/date/t18z: No such file or directory` | PDY date file missing — setpdy.sh fallback |
| 106 | `./PDY: No such file or directory` | PDY sourcing failed — jjob_header.sh continues |
| 8 | `INFO: gw_gsi.orion module not available, falling back to gw_run.orion` | Module fallback — normal for CI |
| 972 | `WARNING: Previous cycle snow file ... is missing. Snow coverage will not be updated.` | Previous cycle gdas snow grb missing — snow disabled |

The missing previous-cycle snow file at line 972 triggers a defensive code path that sets `FNSNOA=' '` and `CYCLVARS=FSNOL=99999.,FSNOS=99999.` (disabling snow updates). This is expected behavior when a prior cycle's snow observation data is unavailable.

## Execution Timeline

| Time (CDT) | Event |
|-------------|-------|
| 02:45:22 | JGLOBAL_ENKF_SFC begins |
| 02:45:xx | config.base, config.esfc, config.resources sourced |
| 02:45:xx | ORION.env sets `APRUN_CYCLE="srun -l --export=ALL --hint=nomultithread -n 12 --cpus-per-task=1"` |
| 02:45:xx | exglobal_enkf_sfc.sh stages sfc_data for mem001, mem002 across tile 1 |
| 02:45:xx | global_cycle.sh invoked with `gcycle_date=2021122015` |
| 21:45:38 | `srun` fails — "More processors requested than permitted" |
| 21:45:38 | `err_exit "Failed to update surface fields!"` — RETURN CODE 1 |
| 21:45:39 | JOB 22576580 CANCELLED DUE TO SIGNAL Terminated |

> **Note**: The ~19-hour gap between job start (02:45) and failure (21:45) suggests the job was pending in the Slurm queue for an extended period before executing on orion-13-24.

## Recommended Actions

### Immediate Fix

1. **Add `is_exclusive=True` to the esfc step** in `config.resources` to prevent shared-node resource contention:

   ```bash
   "esfc")
     walltime="01:15:00"
     ntasks=$(( NMEM_ENS * 6))
     threads_per_task=1
     node_numerator=1
     node_denominator=2
     tasks_per_node=$(( node_numerator*max_tasks_per_node/node_denominator ))
     threads_per_task_cycle=${threads_per_task}
     tasks_per_node_cycle=$(( max_tasks_per_node / threads_per_task_cycle ))
     is_exclusive=True  # <-- ADD THIS
     ;;
   ```

### Alternatives

2. **Reduce srun task count** — If exclusive allocation is too expensive, reduce the `global_cycle` srun from `-n 12` to a smaller value, though this changes the parallelism of the surface update
3. **Investigate Slurm node health** — Check if `orion-13-24` had degraded resources at runtime via `sacct -j 22576580 --format=JobID,AllocCPUS,ReqCPUS,State,ExitCode,NodeList`
4. **Retry** — This may be a transient Slurm scheduling issue; re-running the CI pipeline may succeed

## MCP RAG Analysis Context

This analysis leveraged the following EIB MCP-RAG tools:

- **`get_job_details`** — Retrieved JGLOBAL_ENKF_SFC job structure, configs, and ChromaDB documentation
- **`find_callers_callees`** — Traced the `global_cycle` call chain (6 callers, leaf script)
- **`get_operational_guidance`** — Retrieved Orion platform-specific operational context
- **`search_documentation`** — Searched for Slurm resource allocation patterns in the RAG knowledge base
- **`find_env_dependencies`** — Identified scripts depending on `APRUN_CYCLE` environment variable
- **`analyze_code_structure`** — Analyzed exglobal_enkf_sfc.sh structure and dependencies

## Files Involved

| File | Role |
|------|------|
| `dev/job_cards/rocoto/esfc.sh` | Rocoto job card — loads modules, calls JGLOBAL_ENKF_SFC |
| `dev/jobs/JGLOBAL_ENKF_SFC` | J-Job — sets up COMROOT paths, calls exglobal_enkf_sfc.sh |
| `dev/scripts/exglobal_enkf_sfc.sh` | Ex-script — stages sfc_data, calls global_cycle.sh |
| `ush/global_cycle.sh` | USH script — runs `global_cycle` executable via `${APRUNCY}` |
| `exec/global_cycle` | Fortran executable — performs surface field updates |
| `dev/parm/config/gfs/config.resources` | Resource definitions — ntasks=12, half-node allocation |
| `dev/parm/config/gfs/config.esfc` | ESFC config — coupled mode, IAU settings |
| `env/ORION.env` | Platform env — sets `APRUN_CYCLE`, `APRUN_ESFC` srun commands |
