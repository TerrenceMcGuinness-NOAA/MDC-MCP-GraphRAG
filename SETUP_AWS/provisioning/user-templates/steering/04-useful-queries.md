# Useful AI Queries for Workflow Development

Quick reference for common questions you can ask. The AI has indexed the full
workflow codebase, configuration files, documentation, and job-dependency structure.

## Understanding a Job

- "What does JGFS_ATMOS_FORECAST do?"
- "Show me the execution chain for JGDAS_ATMOS_ANALYSIS"
- "What scripts does this job source?"
- "What environment variables does JGLOBAL_FORECAST depend on?"

## Tracing Dependencies

- "What runs before the forecast job?"
- "What depends on config.fcst?"
- "Where is FHMAX set?"
- "What other scripts use the variable HOMEgfs?"

## Exploring Code Structure

- "Show me the Fortran call tree from ufs_model"
- "What subroutines does the radiation module call?"
- "Find similar code to this error handling pattern"
- "What files import the pygfs.task module?"

## Configuration Questions

- "What is the default value of FHMAX in config.fcst?"
- "How does config.resources differ between Hera and WCOSS2?"
- "What configs are sourced by the forecast ex-script?"

## Compliance & Standards

- "Check this script for EE2 compliance"
- "Is this output path naming correct?"
- "Show me the EE2 standard for error handling"

## Working with Specific Branches

Add `tenant_id="gw_v17"` to any query to target the v17 branch:
- "What changed in config.fcst on the v17 branch?" (compare by asking both)
- "Show dependencies for JGLOBAL_FORECAST on gw_v17"

## Workflow Structure

- "List all jobs in the GFS configuration"
- "Show me the Rocoto task hierarchy for the coupled model"
- "What data dependencies does the analysis job have?"
