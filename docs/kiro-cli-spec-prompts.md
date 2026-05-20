# Kiro CLI Chat Prompts — Spec Task Execution

Run these prompts sequentially in `kiro-cli chat` sessions.
Each phase should complete before starting the next.

```bash
cd /mdc-mcp-rag/eib-mcp-rag-server
kiro-cli chat
```

---

## Phase 57 — Manifest Status Writeback

### Prompt 1 (Tasks 1 + 2: GapDetector fix + ManifestRegistry wrapper)

```
Read the spec at .kiro/specs/manifest-status-writeback/tasks.md and execute tasks 1.1 and 2.1 in parallel.

Task 1.1: Add `update_source_from_ingest(name, doc_count)` method to `mcp_server_python/src/manifest/registry.py`. It should call `self.update_source(name, last_ingested=datetime.now(timezone.utc).isoformat(), doc_count=doc_count)`. One-liner wrapper.

Task 2.1: Fix `GapDetector._get_actual_counts()` in `mcp_server_python/src/manifest/gap_detector.py`. Add DEBUG logging of health dict keys after health_check call. Add fallback loop over alternative key names (index_details, index_counts, per_index_counts) when indices_detail is empty. Add WARNING log when result is empty despite successful health check.

After both changes, run: python3.12 -m pytest tests/unit/ -q --tb=short
Mark tasks 1.1 and 2.1 as complete in tasks.md when tests pass.
```

### Prompt 2 (Task 3: list_all_sources warning)

```
Execute task 3.1 from .kiro/specs/manifest-status-writeback/tasks.md.

In `mcp_server_python/src/tools/semantic_search.py`, in the `_tool_list_all_sources` function:
1. After resolving actual_counts from health_check, add a WARNING log if actual_counts is empty despite a successful health response.
2. In the gap detection rendering section, when include_gaps is true and reports are empty with empty actual_counts, render a notice: "_⚠️ Actual index counts unavailable — gap status may be inaccurate._"

Run tests after. Mark task 3.1 complete.
```

### Prompt 3 (Task 5: Backfill script)

```
Execute task 5.1 from .kiro/specs/manifest-status-writeback/tasks.md.

Create `mcp_server_python/scripts/backfill_manifest_status.py` per the design at .kiro/specs/manifest-status-writeback/design.md (Component 2). The script:
1. Accepts --manifest, --opensearch-endpoint, --region, --dry-run args
2. Queries OpenSearch _cat/indices?format=json with AWS SigV4 signing (boto3 + requests_aws4auth)
3. Builds reverse index map via resolve_index from src.config.aws_config
4. For each source with matching index and doc_count > 0, calls registry.update_source_from_ingest
5. Saves manifest unless --dry-run

Make it executable (chmod +x). Test with --dry-run:
python3.12 mcp_server_python/scripts/backfill_manifest_status.py \
  --manifest mcp_server_python/src/config/unified_manifest.json \
  --opensearch-endpoint vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com \
  --region us-east-1 \
  --dry-run

Mark task 5.1 complete. Then run without --dry-run to populate the manifest.
```

---

## Phase 58 — URL Crawl Gap Closure

### Prompt 4 (Task 1: Reachability check)

```
Execute task 1.1 from .kiro/specs/url-crawl-gap-closure/tasks.md.

Run HTTP HEAD smoke test against all 12 pending source URLs:
- https://dtcenter.org/sites/default/files/community-code/gsi/docs/users-guide/html_v3.7/
- https://uwtools.readthedocs.io/en/latest/
- https://www2.mmm.ucar.edu/projects/mpas/site/index.html
- https://ufs-community.github.io/CATChem
- https://ufs-community.github.io/CECE
- https://escomp.github.io/CDEPS/versions/master/html/index.html
- https://land-da.readthedocs.io/en/stable/
- https://ufs-srweather-app.readthedocs.io/en/develop/
- https://hafsdoc.readthedocs.io/en/latest/
- https://escomp.github.io/CMEPS/
- https://noaa-emc.github.io/NCEPLIBS-sfcio/
- https://kokkos.org/kokkos-core-wiki/api-references.html

Use curl -sL -o /dev/null -w "%{http_code}" for each. Report results. Flag any 404/5xx. Mark task complete.
```

### Prompt 5 (Tasks 2+3: Tier 1 + Tier 2 ingestion)

```
Execute tasks 2.1, 2.2, 3.1, and 3.2 from .kiro/specs/url-crawl-gap-closure/tasks.md.

Run the ingest pipeline for gsi-user-guide and uwtools using titan1024 embeddings:

cd /mdc-mcp-rag/eib-mcp-rag-server
python3 mcp_server_node/scripts/ingest_documentation_v8.py --model titan1024 --tiers tier1_critical --delay 1.5
python3 mcp_server_node/scripts/ingest_documentation_v8.py --model titan1024 --tiers tier2_workflow --delay 1.5

After each completes, verify via the agentcore-mcp-rag MCP tool:
- search_documentation("GSI gridpoint statistical interpolation")
- search_documentation("uwtools workflow tools")

Report doc_count for each. Mark tasks complete.
```

### Prompt 6 (Task 5: Tier 3 batch)

```
Execute tasks 5.1 and 5.2 from .kiro/specs/url-crawl-gap-closure/tasks.md.

Run tier3_models ingestion (this will process mpas-atmosphere, catchem, cece, cdeps, land-da, ufs-srweather-app, hafs plus skip already-indexed sources):

python3 mcp_server_node/scripts/ingest_documentation_v8.py --model titan1024 --tiers tier3_models --delay 1.5

After completion, verify via search_documentation:
- "MPAS unstructured mesh"
- "HAFS hurricane vortex initialization"
- "CATChem aerosol chemistry"
- "CDEPS data model"
- "land data assimilation Noah-MP"

Report doc_counts. Mark tasks complete.
```

### Prompt 7 (Tasks 6+7: Tier 4 + cmeps retry)

```
Execute tasks 6.1, 6.2, and 7.1 from .kiro/specs/url-crawl-gap-closure/tasks.md.

Run tier4_build ingestion:
python3 mcp_server_node/scripts/ingest_documentation_v8.py --model titan1024 --tiers tier4_build --delay 1.5

For kokkos-api and nceplibs-sfcio: if they produce 0 docs after valid crawl, mark as empty_site (keep enabled:true in manifest).

For cmeps: check if it was processed in the tier3 run. If 0 docs, manually verify the URL content with curl. Mark as empty_site if no crawlable content.

Mark tasks complete.
```

### Prompt 8 (Task 9: Manifest writeback + verification)

```
Execute tasks 9.1, 9.2, 9.3, and 9.4 from .kiro/specs/url-crawl-gap-closure/tasks.md.

1. Run the backfill script:
python3.12 mcp_server_python/scripts/backfill_manifest_status.py \
  --manifest mcp_server_python/src/config/unified_manifest.json \
  --opensearch-endpoint vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com \
  --region us-east-1

2. Verify via MCP: list_all_sources(include_gaps=True) — pending count should be 0 or only empty sites
3. Verify via MCP: get_knowledge_base_status() — total docs >= 27,222
4. Produce summary: list all 12 sources with final doc_count, status (ingested/empty_site/failed)

Mark tasks complete. Report batch success (>= 9 sources with doc_count > 0).
```

---

## Phase 59 — PDF Ingestion Pipeline

### Prompt 9 (Tasks 1+2+3: Script implementation)

```
Execute tasks 1.1, 2.1, 3.1, and 3.2 from .kiro/specs/pdf-ingestion-pipeline/tasks.md.

Create mcp_server_node/scripts/ingest_pdf_sources.py per the design at .kiro/specs/pdf-ingestion-pipeline/design.md. Implement:
1. CLI with --manifest, --region, --source, --dry-run (argparse)
2. load_pdf_sources() — filter manifest for crawl_type==pdf_download + enabled
3. download_pdf() — requests.get with 60s timeout, returns None on failure
4. extract_text() — pypdf PdfReader, concatenate pages with "--- Page N ---" markers
5. chunk_text() — 512-token chunks, 64-token overlap, whitespace tokenization
6. embed_chunks() — BedrockProvider with titan1024 profile, skip failed chunks

Make it executable. Mark tasks complete.
```

### Prompt 10 (Tasks 4+5: Indexing + orchestrator)

```
Execute tasks 4.1, 4.2, and 5.1 from .kiro/specs/pdf-ingestion-pipeline/tasks.md.

Continue implementing mcp_server_node/scripts/ingest_pdf_sources.py:
1. index_chunks() — deterministic IDs ({source_name}-chunk-{chunk_index}), 6 metadata fields, OpenSearchVectorClient
2. _estimate_page() — extract page number from chunk text markers
3. update_manifest() — atomic write (temp file + os.replace)
4. main() — wire everything together with dry-run support and summary output

Test with --dry-run:
python3 mcp_server_node/scripts/ingest_pdf_sources.py --dry-run

Should show PDF sizes, page counts, and chunk counts for all 4 PDF sources. Mark tasks complete.
```

### Prompt 11 (Task 7: Live ingestion)

```
Execute tasks 7.1 and 7.2 from .kiro/specs/pdf-ingestion-pipeline/tasks.md.

1. Verify manifest has the 4 PDF entries (esmf-ref-pdf, esmc-ref-pdf, nuopc-ref-pdf, esmpy-pdf) with crawl_type: pdf_download and enabled: true.

2. Run live ingestion:
python3 mcp_server_node/scripts/ingest_pdf_sources.py --region us-east-1

3. Verify manifest updated with last_ingested and doc_count values.

4. Verify via MCP search_documentation:
- "ESMF_FieldCreate Fortran API"
- "ESMPy regrid"
- "NUOPC_CompSetEntryPoint"

Report results. Mark tasks complete.
```

---

## Post-Execution

After all three phases complete, rebuild the AgentCore image to include the updated manifest:

```bash
cd /mdc-mcp-rag/eib-mcp-rag-server/mcp_server_python
docker build --platform linux/arm64 \
  -t 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-all-tools-v5 \
  -f Dockerfile .

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin 903050880929.dkr.ecr.us-east-1.amazonaws.com
docker push 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-all-tools-v5

aws bedrock-agentcore-control update-agent-runtime \
  --region us-east-1 \
  --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN \
  --agent-runtime-artifact '{"containerConfiguration":{"containerUri":"903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-all-tools-v5"}}' \
  --role-arn arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role \
  --network-configuration '{"networkMode":"VPC","networkModeConfig":{"subnets":["subnet-0e13af6b3a9a6416f","subnet-04447750c61bd7e06"],"securityGroups":["sg-096489a0876cc78c1"]}}' \
  --protocol-configuration '{"serverProtocol":"MCP"}' \
  --lifecycle-configuration '{"idleRuntimeSessionTimeout":900,"maxLifetime":28800}' \
  --environment-variables '{"DB_BACKEND":"aws","NEPTUNE_ENDPOINT":"https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182","OPENSEARCH_ENDPOINT":"https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com","AWS_REGION":"us-east-1","MCP_STATELESS_HTTP":"true","MCP_WORKFLOW_ROOT":"/app/supported_repos/global-workflow"}'
```
