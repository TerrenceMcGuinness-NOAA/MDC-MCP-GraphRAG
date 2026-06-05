# EMC Coding Standards & EE2 Compliance

When writing or reviewing shell scripts for the global-workflow, follow these standards.
The AI tools can check compliance — use `search_ee2_standards` and
`analyze_ee2_compliance` to verify.

## Shell Script Standards

- Use `err_chk` or `err_exit` for error handling (NOT `set -e` or `set -eu`)
- All scripts must have a proper shebang: `#!/bin/bash` for bash, `#!/bin/ksh` for ksh
- Use `${variable}` syntax (braces) for all variable references
- Environment variables: UPPERCASE with underscores (e.g. `COMOUT`, `DATA`, `PDY`)
- Local variables in functions: lowercase or declare with `local`

## File Naming Conventions

- J-Jobs: `JGFS_<SYSTEM>_<TASK>` (e.g. `JGFS_ATMOS_FORECAST`)
- Ex-scripts: `ex<system>_<task>.sh` (e.g. `exglobal_forecast.sh`)
- Config files: `config.<name>` (e.g. `config.fcst`, `config.base`)
- Utility scripts: descriptive lowercase (e.g. `parsing_namelists.sh`)

## Environment Variable Patterns

- `HOMEgfs` — root of the workflow installation
- `COMROOT` / `COMOUT` / `COMIN` — COM directory structure
- `DATA` — job working directory (created per job, cleaned on success)
- `PDY` / `cyc` — date and cycle hour
- `RUN` — run type (gdas, gfs, gefs)
- `CDUMP` — same as RUN (legacy name)

## When Reviewing Code

Ask the AI to check compliance:
- "Does this script follow EE2 error handling standards?"
- "Is this output file naming correct for production?"
- "What environment variables does this job need?"
