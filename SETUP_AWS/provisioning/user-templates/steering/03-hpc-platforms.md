# HPC Platform Reference

The global-workflow runs on multiple NOAA HPC platforms. Use `get_operational_guidance`
or `get_system_configs` with the platform name to get platform-specific details.

## Platforms

| Platform | Location | Scheduler | Compiler | Notes |
|---|---|---|---|---|
| WCOSS2 | NCO Production (Dell) | PBS Pro | Intel | Operations — most restrictive |
| Hera | RDHPCS (NESCC) | Slurm | Intel/GNU | Primary R&D |
| Hercules | RDHPCS (MSU) | Slurm | Intel | Newer hardware |
| Orion | RDHPCS (MSU) | Slurm | Intel | Large memory nodes |
| Gaea (C5/C6) | GFDL/RDHPCS | Slurm | Intel | Climate-focused |

## Platform-Specific Configs

Each platform has a `config.resources.<PLATFORM>` file in the experiment directory
that sets job resource limits (walltime, nodes, memory, queue). The base `config.resources`
sets defaults that platform overrides specialize.

## Module Loading

Platform module loads live in `env/` — e.g. `env/HERA.env`, `env/WCOSS2.env`.
These set up compilers, MPI, NetCDF, and model-specific libraries.

## Testing a Change Across Platforms

When your PR modifies resource requirements or platform-specific logic, test on at
least Hera + one other platform before submitting. The CI matrix covers:
- C48 ATM (quick, atmosphere-only)
- C96 cycled (full DA cycle)
- Coupled configurations (atmosphere + ocean + ice)
