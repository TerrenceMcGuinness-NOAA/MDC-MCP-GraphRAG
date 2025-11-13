# MCP Server Archive Directory

This directory contains archived code from previous development phases.

## Structure

- `legacy_pre_week1/` - Pre-AWS prototype artifacts from before Week 1 refactor
  - Archived: 2025-11-03
  - Contains: Optimization experiments and early RAG implementations
  - Status: Superseded by Week 1 Data Access Layer architecture
  - See: `ARCHIVE_METADATA.json` for complete manifest

## Archive Policy

- Legacy code is preserved for reference and historical context
- Each archive has metadata file documenting:
  - What was archived
  - When and why
  - Source version and deployment manifest
- Archives are managed by `deploy-to-runtime.sh` script

## Future Archives

As the MCP system evolves through Week 2, Week 3, and beyond, additional archives may be created here following the same pattern.

## Related Files

- `../deployment-manifest.json` - Defines what gets archived during deployment
- `../deploy-to-runtime.sh` - Automated deployment script that creates archives
