# Phase 53: Neptune Recovery and Incremental Graph Ingestion Pipeline

## Overview

The CDK deployment of MdcDataStack (Phase 51, April 22 2026) inadvertently deleted
the Neptune cluster `mdc-mcp-rag-neptune` containing 59,759 nodes and 2,633,374
relationships. The surviving cluster `mdc-mcp-graprag-neptune-1` is empty (0 nodes).
OpenSearch data (85,921+ docs across 17 indices) is intact.

This spec covers three tracks:
- **Track A**: Immediate recovery — restore graph from S3 bulk load dump
- **Track B**: Incremental update — re-ingest from current source tree to capture drift since April 7
- **Track C**: Ongoing maintenance — build automated incremental ingestion pipeline

## Root Cause

The MdcDataStack CDK change replaced Neptune/OpenSearch resource creation with
imports of existing resources. CloudFormation interpreted the removed CDK resources
as "delete them." The Neptune cluster had `removalPolicy: DESTROY` (CDK default),
so CloudFormation deleted the cluster, instance, subnet group, and security group.
OpenSearch and EFS survived because they had `removalPolicy: RETAIN`.

**Lesson learned**: When converting CDK-managed resources to imports, the old
resources must first have their `removalPolicy` set to `RETAIN` in a separate
deployment before removing them from the stack. This is a two-step process.

## Current State

| Resource | Status | Data |
|----------|--------|------|
| Neptune `mdc-mcp-rag-neptune` | DELETED | 59,759 nodes lost |
| Neptune `mdc-mcp-graprag-neptune-1` | AVAILABLE (empty) | 0 nodes |
| OpenSearch `mdc-mcp-rag-search` | HEALTHY | 85,921+ docs, 17 indices |
| S3 `mdc-mcp-rag-migration/graph/` | AVAILABLE | Phase 50 dump (April 7) |
| S3 `mdc-mcp-rag-migration/graph/opencypher-csv/` | AVAILABLE | Bulk loader CSVs |

## Track A: Immediate Recovery (S3 Bulk Load)

### Prerequisites
- Neptune cluster `mdc-mcp-graprag-neptune-1` is available
- S3 bucket `mdc-mcp-rag-migration` has the openCypher CSV files
- Neptune IAM role `mdc-mcp-rag-neptune-s3-loader` is attached to the cluster
- Neptune security group allows port 8182 from EC2

### Steps

1. **Verify S3 data exists**
   - Tag: validate
   - `aws s3 ls s3://mdc-mcp-rag-migration/graph/opencypher-csv/`
   - Confirm node and relationship CSV files are present

2. **Verify Neptune bulk loader role**
   - Tag: validate
   - Check if `mdc-mcp-rag-neptune-s3-loader` role is attached to `mdc-mcp-graprag-neptune-1`
   - If not, submit admin request to attach it (same as Phase 50b)

3. **Run Neptune bulk load**
   - Tag: implement
   - `node scripts/neptune-bulk-load.js --cluster mdc-mcp-graprag-neptune-1`
   - Or use Neptune `/loader` API directly with SigV4 auth
   - Monitor load status via `/loader/{loadId}` polling

4. **Verify node and relationship counts**
   - Tag: validate
   - Expected: ~59,759 nodes, ~2,633,374 relationships
   - Run: `MATCH (n) RETURN count(n)` and `MATCH ()-[r]->() RETURN count(r)`

5. **Update start-aws-mcp.sh with correct endpoint**
   - Tag: configure
   - Neptune endpoint: `wss://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182`
   - Restart MCP server and verify health check

6. **Run parity comparison**
   - Tag: validate
   - `node scripts/compare-backends.js`
   - Verify all 6 tools at ≥80% parity

## Track B: Incremental Update (Source Tree Re-Ingestion)

### Context
The S3 dump is from April 7. Any code changes merged into global-workflow
between April 7 and today are not in the graph. The ingestion scripts use
MERGE (idempotent upsert) so re-running them is safe.

### Steps

7. **Assess drift since April 7**
   - Tag: research
   - `cd supported_repos/global-workflow && git log --oneline --since="2026-04-07" | wc -l`
   - Identify which subsystems changed (sorc/, ush/, jobs/, parm/)

8. **Re-run Fortran graph ingestion**
   - Tag: implement
   - `python3 scripts/ingest_fortran_graph.py --backend aws`
   - Picks up new/changed Fortran subroutines, functions, modules
   - MERGE ensures no duplicates

9. **Re-run shell script graph ingestion**
   - Tag: implement
   - `python3 scripts/ingest_shell_graph_v8.py --backend aws`
   - Picks up new/changed J-Jobs, ex-scripts, ush scripts
   - Updates SOURCES, INVOKES, DEPENDS_ON_ENV relationships

10. **Re-run cross-language bridge ingestion**
    - Tag: implement
    - `python3 scripts/ingest_cross_language_bridges.py --backend aws`
    - Rebuilds EXECUTES (Shell→Fortran) and INVOKES (Shell→Python) bridges

11. **Re-run Python graph ingestion**
    - Tag: implement
    - `python3 scripts/ingest_code_v8.py --backend aws --model mpnet768`
    - Updates Python module/function/class nodes

12. **Re-run community detection**
    - Tag: implement
    - Requires GDS (Graph Data Science) — only available on Neo4j, not Neptune
    - Alternative: export graph to Neo4j on PW, run Leiden, export communities, import to Neptune
    - Or: skip community refresh if changes are minor

13. **Verify updated counts**
    - Tag: validate
    - Compare node/relationship counts before and after incremental update
    - Run parity comparison against legacy

## Track C: Automated Incremental Ingestion Pipeline (Future)

### Design Goals
- Detect source tree changes via git diff
- Re-ingest only changed files/modules
- Run on schedule (daily or on-merge)
- Report drift metrics

### Components Needed

14. **Git-aware change detector**
    - Tag: design
    - Compare `git log --since=<last_ingestion>` against ingested file list
    - Output: list of files to re-ingest, categorized by type (Fortran, shell, Python)

15. **Selective re-ingestion runner**
    - Tag: design
    - Takes file list from change detector
    - Runs appropriate ingestion script for each file type
    - Uses MERGE for idempotent updates

16. **Graph staleness monitor**
    - Tag: design
    - Extend `check_knowledge_integrity` to compare graph node timestamps against git commit dates
    - Alert when >10% of nodes are stale (source file modified after ingestion)

17. **Scheduled execution**
    - Tag: design
    - Options: cron on EC2, EventBridge rule, or SageMaker Processing Job
    - Trigger: daily at 2 AM, or on git push webhook

## CDK Remediation

18. **Fix MdcDataStack to prevent future data loss**
    - Tag: implement
    - Add explicit `removalPolicy: cdk.RemovalPolicy.RETAIN` to ALL data resources
    - Neptune cluster, OpenSearch domain, EFS, KMS key, S3 bucket
    - Deploy this change BEFORE any future stack modifications
    - This is a one-line fix per resource but critical for data safety

19. **Update CDK import pattern**
    - Tag: implement
    - Two-step process for converting CDK-managed to imported:
      Step 1: Set `removalPolicy: RETAIN` on existing resources, deploy
      Step 2: Replace resource creation with imports, deploy (old resources retained)
    - Document this pattern in the CDK README

## Total Steps: 19

## Acceptance Criteria

- Track A: Neptune has ≥59,000 nodes and ≥2.6M relationships
- Track A: All 6 parity benchmark tools at ≥80%
- Track B: Graph reflects current source tree (post-April 7 changes included)
- Track C: Design documented for future implementation
- CDK: All data resources have `removalPolicy: RETAIN`

## Environment

| Variable | Value |
|----------|-------|
| Neptune Cluster | mdc-mcp-graprag-neptune-1 |
| Neptune Endpoint | mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182 |
| OpenSearch | vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com |
| S3 Migration | s3://mdc-mcp-rag-migration/ |
| Neptune S3 Loader Role | mdc-mcp-rag-neptune-s3-loader |

## Branch

`develop_aws`
