# Global Workflow Development Context

You are assisting a developer working on the NOAA/EMC Global Workflow — a production
weather and climate forecasting system that runs GFS, GDAS, GEFS, and coupled Earth
system models on NOAA's HPC platforms (Hera, WCOSS2, Hercules, Orion, Gaea).

## The System

The global-workflow repository (`NOAA-EMC/global-workflow`) orchestrates:
- Atmospheric forecasting (FV3/UFS model)
- Data assimilation (GSI, JEDI, EnKF)
- Ocean modeling (MOM6, CICE6)
- Wave modeling (WW3)
- Aerosol/chemistry (GOCART, GCAFS)
- Land surface (Noah-MP)
- Post-processing (UPP, GRIB2, GEMPAK, AWIPS)
- Verification (METplus, fit2obs)

## Repository Structure

- `dev/jobs/` — J-Job scripts (Rocoto task entry points, uppercase J-prefix)
- `dev/scripts/` — ex-scripts (execution scripts called by J-Jobs)
- `ush/` — Utility shell scripts and Python modules (pygfs)
- `parm/config/` — Configuration files (config.fcst, config.base, etc.)
- `sorc/` — Source code submodules (UFS, GSI, UPP, etc.)
- `ecf/` — ECFlow definitions (legacy)
- `env/` — Platform-specific module loads
- `fix/` — Fixed input data references

## Available AI Tools

You have access to an AI-powered code intelligence system that understands the
global-workflow codebase. Use it to:

- **Search documentation**: "How do I configure the ocean model?"
- **Trace execution chains**: "What happens when JGLOBAL_FORECAST runs?"
- **Find dependencies**: "What does config.fcst depend on?"
- **Understand env vars**: "Where is COMROOT set?"
- **Check compliance**: "Does this script follow EE2 standards?"
- **Explore the Rocoto DAG**: "What jobs run before the forecast?"

## Multi-Tenant Workflow Versions

The system supports multiple workflow branches simultaneously. Use the
`tenant_id` parameter to target a specific version:

- `tenant_id="gw"` — the develop branch (default, production baseline)
- `tenant_id="gw_v17"` — the dev/gfs.v17 branch (next-gen forecast system)
- `tenant_id="gw_sfs"` — the dev/sfs branch (Subseasonal Forecasting System)
- `tenant_id="gw_jedi_gfs"` — the dev/jedi-gfs branch (JEDI-based DA)
- `tenant_id="gw_gefs_v12"` — the release/gefs_v12 branch (GEFS v12)

When working on a specific branch, always pass the appropriate tenant_id
so the tools return branch-specific results.

## Development Workflow

1. Branch from `develop` for new features
2. Follow EE2 coding standards for all scripts
3. Use `setup_expt.py` to generate experiment directories
4. Test with Rocoto on an HPC platform before PR
5. CI runs the full test suite across multiple configurations
