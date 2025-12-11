# EVS EE2 Compliance Report (Full) — 2025-12-05

## Scope and Method
- Target: supported_repos/EVS (643 files scanned: 210 shell, 398 Python, 30 job cards, 5 configs).
- Tooling: MCP EE2 repository scan (`scan_repository_compliance`, detailed error_handling pass) + standards mapping (`ee2-standards-v5-0-0-enhanced`).
- Status: 39 files with error_handling issues (other categories not flagged in this run).

## Summary Table
| Category | Files w/issues | % of scanned | Notes |
| --- | --- | --- | --- |
| Error handling | 39 | 6.1% | Missing set -x; shebang not first line; missing err_exit file guards |
| Others | 0 | 0% | Not flagged in this scan |

## Top Violations and Fixes (Actionable)
| Violation | Example files | Fix guidance |
| --- | --- | --- |
| Missing `set -x` after shebang | [ecf/setup_ecf_links.sh](supported_repos/EVS/ecf/setup_ecf_links.sh), scripts/prep/*/exevs_prep_* (multiple) | Add `set -x` immediately after `#!/bin/bash` (EE2 debug requirement; do **not** add `-eu`). |
| Shebang not on line 1 | [ush/global_ens/global_ens_wave_plots_copy_plots.sh](supported_repos/EVS/ush/global_ens/global_ens_wave_plots_copy_plots.sh) | Remove leading blank lines so `#!/bin/bash` is line 1; then add `set -x`. |
| Missing `err_exit` guard for required inputs | [ush/rtofs/rtofs_prep_regions.sh](supported_repos/EVS/ush/rtofs/rtofs_prep_regions.sh), [scripts/stats/rtofs/exevs_stats_rtofs_grid2obs.sh](supported_repos/EVS/scripts/stats/rtofs/exevs_stats_rtofs_grid2obs.sh), [scripts/prep/global_ens/exevs_prep_global_ens_gefs_wave.sh](supported_repos/EVS/scripts/prep/global_ens/exevs_prep_global_ens_gefs_wave.sh) | Before processing, guard inputs: `if [ ! -f "$INPUT_FILE" ]; then err_exit "FATAL ERROR: Required file $INPUT_FILE not found"; fi` (repeat for each required file/dir). |

## Priority Fix List (by impact/coverage)
1) [ecf/setup_ecf_links.sh](supported_repos/EVS/ecf/setup_ecf_links.sh) — add `set -x` after shebang.
2) [ush/global_ens/global_ens_wave_plots_copy_plots.sh](supported_repos/EVS/ush/global_ens/global_ens_wave_plots_copy_plots.sh) — move shebang to line 1; add `set -x`.
3) [ush/rtofs/rtofs_prep_regions.sh](supported_repos/EVS/ush/rtofs/rtofs_prep_regions.sh) — add `err_exit` guards for required inputs.
4) [scripts/stats/rtofs/exevs_stats_rtofs_grid2obs.sh](supported_repos/EVS/scripts/stats/rtofs/exevs_stats_rtofs_grid2obs.sh) — add `err_exit` guards.
5) [scripts/prep/global_ens/exevs_prep_global_ens_gefs_wave.sh](supported_repos/EVS/scripts/prep/global_ens/exevs_prep_global_ens_gefs_wave.sh) — add `err_exit` guards; ensure `set -x` present.

## Representative Examples (ready-to-fix snippets)
- Add debug flag:
  - Before: `#!/bin/bash` (no debug)
  - After:
    ```bash
    #!/bin/bash
    set -x
    ```
- Guard required inputs:
  ```bash
  if [ ! -f "$INPUT_FILE" ]; then
    err_exit "FATAL ERROR: Required file $INPUT_FILE not found"
  fi
  ```
- Fix shebang position:
  - Remove leading blank lines; ensure `#!/bin/bash` is the very first line, followed by `set -x`.

## Next Steps (suggested workflow)
- Apply fixes to the 5 priority files above, then propagate the same patterns to the remaining 34 flagged shell scripts.
- Re-run EE2 scan to verify zero error_handling findings; add category checks for env handling and logging if needed.

---
Generated via MCP EE2 tools on 2025-12-05.
