Environment Variable Standards
==============================

Overview
--------

This document defines the standards for environment variable usage in 
NOAA operational production scripts. Proper environment variable handling
is critical for operational reliability and error detection.

.. mcp:standard:: environment_variables
   :category: environment_variables
   :level: must
   :intent: validation
   :platforms: hera,hercules,orion,wcoss2,gaea
   :priority: critical

Required Environment Variable Validation
-----------------------------------------

All production scripts **MUST** check for the presence of required 
environment variables before proceeding with execution. Missing environment 
variables should cause immediate script failure with a clear error message
indicating which variable is missing.

Critical environment variables that must be validated:

- ``COMROOT``: Root directory for operational data
- ``DATAROOT``: Working directory for job execution
- ``cyc``: Cycle time for the forecast (format: HH)
- ``PDY``: Processing date (format: YYYYMMDD)

Scripts must exit with non-zero status if any required environment 
variable is undefined or empty.

.. mcp:example::
   :category: environment_variables
   :intent: example
   :language: bash

Environment Variable Validation Example
----------------------------------------

This example demonstrates proper validation of required environment
variables in a production script:

.. code-block:: bash

   #!/bin/bash
   set -eu
   
   # Validate required environment variables
   required_vars=(
       "COMROOT"
       "DATAROOT"
       "cyc"
       "PDY"
   )
   
   for var in "${required_vars[@]}"; do
       if [[ -z "${!var:-}" ]]; then
           echo "ERROR: Required environment variable $var is not set"
           exit 1
       fi
   done
   
   echo "Environment validation passed"
   echo "COMROOT=$COMROOT"
   echo "DATAROOT=$DATAROOT"
   echo "cyc=$cyc PDY=$PDY"

.. mcp:guidance::
   :category: environment_variables
   :intent: guidance
   :platform: hera

Platform-Specific Environment Setup (Hera)
-------------------------------------------

On Hera systems, environment variables for operational workflows should be
set in module files located in ``/scratch1/NCEPDEV/global/glopara/modulefiles``.

Recommended settings for Hera:

.. code-block:: bash

   # Hera-specific environment variables
   export COMROOT=/scratch1/NCEPDEV/global/glopara/com
   export DATAROOT=/scratch1/NCEPDEV/stmp2/$USER
   export ROTDIR=/scratch1/NCEPDEV/global/glopara/archive
   
   # Hera compute node settings
   export OMP_NUM_THREADS=1
   export OMP_STACKSIZE=2048M

**Best Practices for Hera:**

1. Use ``err_chk`` utility for error handling
2. Set appropriate stack size for OpenMP applications
3. Validate scratch space availability before job execution
4. Use ``$TMPDIR`` for temporary files when available

.. mcp:guidance::
   :category: environment_variables
   :intent: guidance
   :platform: wcoss2

Platform-Specific Environment Setup (WCOSS2)
---------------------------------------------

On WCOSS2 systems, operational environment variables follow NCO standards.
Production scripts must source the appropriate environment files.

Standard WCOSS2 setup:

```bash
# WCOSS2 production environment
export COMROOT=/lfs/h1/ops/prod/com
export DATAROOT=/lfs/h2/emc/ptmp/$USER
export GESIN=/lfs/h1/ops/prod/com/gfs/prod

# NCO utilities path
export utilscript=/lfs/h1/ops/prod/libs/ush
export utilexec=/lfs/h1/ops/prod/libs/exec
```

.. mcp:validation::
   :category: environment_variables
   :intent: validation

Validation Test Criteria
-------------------------

Environment variable validation must meet these test criteria:

1. **Required Variable Test**: Script must exit with code 1 if any required
   variable is missing

2. **Empty Variable Test**: Script must treat empty strings as undefined
   and fail validation

3. **Error Message Test**: Error messages must clearly identify which
   variable failed validation

4. **Exit Code Test**: Non-zero exit code must be returned on validation
   failure

Automated tests should verify these criteria for all production scripts.

.. mcp:reference::
   :category: code_standards
   :intent: reference

Related Standards and Documentation
------------------------------------

See also:

- **Error Handling Standards** (Section 3.2): trap usage and cleanup procedures
- **Production Utilities Guide** (Section 5.1): ``err_chk`` and ``err_exit`` utilities  
- **Code Documentation Requirements** (Section 2.4): Inline documentation standards
- **Workflow Structure Guide** (Section 4.3): Rocoto job design patterns

External References:

- NCO Production Standards: https://www.nco.ncep.noaa.gov/pmb/docs/
- Bash Best Practices: https://www.gnu.org/software/bash/manual/
- OpenMP Environment Variables: https://www.openmp.org/specifications/
