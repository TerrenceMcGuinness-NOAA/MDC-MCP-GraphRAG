# Implementation Plan — `cross-platform-data-persistence`

## Overview

Build the `Cross_Platform_Data_Persistence_System` bottom-up under
`SETUP_AWS/provisioning/portable_export/`: shared primitives (manifest,
lock, watermarks, audit, KMS writer, query-embedder check) first, then the
six adapters (two AWS source readers + two AWS target writers + two COTS
target writers) with contract tests, then the direction-agnostic phases
(export vectors / graph / dedupe; load vectors / graph for COTS and AWS;
count parity; bundle), then the dispatcher and CLI, then the integration
tests, then the operator-gated live acceptance against `dev`.

Every code task has a paired `*` test task. The nine correctness
properties from the design are covered across the test waves. All
destructive live operations are operator-gated, and `--dry-run` is
available from Wave 4 so no mutation can occur before the plan is
reviewed.

All paths are relative to the workspace root `/mdc-mcp-rag/eib-mcp-rag-server/`.

## Tasks

- [ ] 1. Scaffold the `portable_export` package and config
  - Create `SETUP_AWS/provisioning/portable_export/` with `__init__.py`,
    `config.py`, and a `tests/` subdir.
  - `config.py`: resolve env -> S3 bucket(s), KMS key ARN, AWS endpoints
    (OpenSearch, Neptune), tenant catalog (loaded from
    `mcp_server_python/src/config/tenants.yaml`), and the embedding
    registry. Reuse the `_ingest_common` boto3 session pattern.
  - Define the `valid_environments` allow-list (`dev`, `staging`, `prod`)
    matching `nih-sandbox-cost-control`.
  - _Requirements: 11.1 (manifest needs source endpoints), 15.4
    (provisioning directory)_

  - [ ]* 1.1 Config unit tests
    - Valid env resolves; invalid env rejected; tenant catalog parsed.
    - _Requirements: 7.1, 11.1_

- [ ] 2. Implement the audit logger
  - `audit.py`: emit one JSON object per line with the standard fields
    (`timestamp`, `event_type`, `operation_id`, `caller_arn`,
    `environment_name`, `direction`, `phase`, `aws_resource_arns`,
    `bundle_keys`, `record_counts`, `elapsed_seconds`, `error`).
  - Persist to CloudWatch log group
    `mdc-mcp-rag-portable-export-{env}` (when AWS-credentialed) AND to
    a per-op S3 object at `<prefix>/audit/<operation_id>.jsonl` AND to
    a local fallback `~/.mdc-mcp-rag/portable_export/<op>.jsonl`.
  - ASCII-only console mirror (`[OK]`/`[ERROR]`/`[WARN]`/`[INFO]`/`[SKIP]`).
  - _Requirements: 15.3 (ASCII-only console)_

  - [ ]* 2.1 Audit unit tests
    - Required field set; ASCII-only assertion; per-op S3 object written
      exactly once; local fallback when no AWS credentials.
    - _Requirements: 15.3_

- [ ] 3. Implement the lock and watermark primitives
  - `lock.py`: read S3 object + ETag; PUT with `IfMatch=<etag>`; map 412
    PreconditionFailed to a typed `ConcurrentOperationError`. Lock file
    schema includes `holder_arn`, `operation_id`, `operation`,
    `acquired_at`, `expected_release_by`. Support `--break-lock` once
    `expected_release_by` is past.
  - `watermarks.py`: atomic update via write-temp + S3 If-Match swap.
    Schema records `(phase, tenant, collection, model_profile, part)`
    completed units per R9.1.
  - Refuse `--resume` when the watermark file's `manifest_id` differs
    from the current run's (`Watermark_Mismatch`).
  - _Requirements: 9.1, 9.2_

  - [ ]* 3.1 Lock + watermarks unit tests + Property 6 (resume)
    - Stale-ETag write -> `ConcurrentOperationError`; missing/corrupt
      lock object handled; watermark mismatch surfaces; atomic update
      under simulated kill mid-write.
    - Property 6: phase already complete is a no-op; phase interrupted
      mid-flight resumes to a final state byte-equal to the
      uninterrupted run.
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [ ] 4. Implement the Export_Manifest model and KMS writer
  - `manifest.py`: dataclass + JSON reader/writer; schema validation;
    refusal on schema_version major mismatch
    (`Manifest_Schema_Unsupported`); per-part SHA-256 fields
    (`sha256_per_part`); preflight counts; tool version capture.
  - `kms_writer.py`: SSE-KMS PUT helpers with streaming SHA-256
    computed during write; refuse to write to a bucket without
    KMS-default-encryption configured (defensive guard).
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 13.1, 13.2_

  - [ ]* 4.1 Manifest + KMS writer unit tests
    - Manifest schema validation; major-mismatch refusal; SHA-256
      streaming correctness; bucket-encryption guard refuses non-KMS.
    - _Requirements: 11.3, 13.2_

- [ ] 5. Implement the query-embedder availability check
  - `query_embedder_check.py`: per-Model_Profile lookup against the
    target's available embedders. The matrix:
    - AWS target: every profile available (Bedrock for titan/nova, local
      for mpnet).
    - COTS target with Bedrock IAM: every profile available.
    - COTS target without Bedrock: only mpnet768 is Query_Compatible;
      titan/nova are Query_Incompatible (data loaded; cannot serve
      queries).
  - Returns per-collection `Query_Compatible` / `Query_Incompatible`
    flags surfaced in the audit record.
  - _Requirements: 4.3, 4.4, 4.5_

  - [ ]* 5.1 Query-embedder check unit tests
    - Table-driven: every (target, model_profile, has_bedrock)
      combination resolves correctly. `Query_Incompatible` does not
      block restore, only flags it.
    - _Requirements: 4.3, 4.4, 4.5_

- [ ] 6. Define the SourceReader + TargetWriter protocols and implement OpenSearch + Neptune readers
  - `adapters/__init__.py`: `SourceReader` and `TargetWriter` protocols
    per the design.
  - `adapters/opensearch_reader.py`: scroll/scan API; enumerate
    Index_Family per tenant from index naming convention; iterate
    documents in batches with bitwise embedding read; respect
    point-in-time / search-after for consistency under concurrent
    writes; enforce read-only invariant.
  - `adapters/neptune_reader.py`: openCypher streaming export of nodes
    (label + properties) and relationships (type + endpoints +
    properties) per tenant; respect Neptune statement timeouts; chunk
    large label sets.
  - _Requirements: 1.1, 1.2, 1.5, 7.1, 7.2, 7.3_

  - [ ]* 6.1 AWS reader contract tests (botocore Stubber)
    - Property 5 (source immutability): assert no PUT/POST/DELETE
      against OpenSearch or Neptune across any reader call. Fails if
      a future code path introduces a mutation.
    - Index_Family enumeration; tenant prefix correctness;
      relationship + node streaming completeness.
    - _Requirements: 1.5, 7.1, 7.2, 7.3_

- [ ] 7. Implement OpenSearch + Neptune writers
  - `adapters/opensearch_writer.py`: ensure index exists with
    `knn_vector` mapping matching the Model_Profile dimension before
    writing (R3.3); refuse on incompatible existing mapping (R3.5);
    bulk index preserving embedding bytes; respect tenant index
    prefix.
  - `adapters/neptune_loader.py`: POST to `/loader` with the S3 prefix
    and the bulk-loader IAM role; poll status until `LOAD_COMPLETED`;
    map errors to typed exceptions.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ]* 7.1 AWS writer contract tests (botocore Stubber)
    - Index ensure-or-refuse on mapping conflict; `knn_vector`
      dimension matches Model_Profile; bulk insert preserves embedding
      bytes; Neptune-loader poll loop; tenant prefix preservation.
    - _Requirements: 3.3, 3.4, 3.5_

- [ ] 8. Implement ChromaDB + Neo4j writers (COTS targets)
  - `adapters/chromadb_writer.py`: ChromaDB version-pinned client;
    `collection.add(ids, documents, embeddings, metadatas)` with
    bitwise embedding pass-through (no recompute); collection name
    preservation including tenant prefix.
  - `adapters/neo4j_writer.py`: shell-out to `neo4j-admin import` for
    bulk node + relationship loading from S3-staged or
    locally-extracted CSV files; transactional INSERT path for small
    deltas; preserve tenant-prefixed labels.
  - Refuse mismatched ChromaDB / Neo4j versions outside the supported
    range with a clear error.
  - _Requirements: 2.1, 2.2, 2.3, 2.5_

  - [ ]* 8.1 COTS writer contract tests
    - In-memory ChromaDB + Neo4j fixtures (or driver mocks); bitwise
      embedding pass-through; tenant prefix preservation; missing
      required-field handling per R2.4.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [ ] 9. Implement the Export phases
  - `phases/export_vectors.py`: per-(tenant, collection) scroll loop
    -> gzipped JSONL parts (target ≤ 64 MB compressed) ->
    `kms_writer` PUT with streaming SHA-256 -> watermark update.
    Bitwise embedding write per R5.
  - `phases/export_graph.py`: per-tenant node + relationship streams
    -> gzipped CSV in Neptune-loader format (one CSV per (label,
    part)) -> `kms_writer` PUT -> watermark update.
  - `phases/export_dedupe.py`: scan `mdc-content-sha-registry` per
    tenant -> JSONL.gz with `(collection, sha)` composite keys
    preserved -> KMS PUT -> watermark update.
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 5.1, 5.2, 5.3, 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 13.1, 13.2_

  - [ ]* 9.1 Export-phase unit tests + Property 1 + Property 2
    - Property 1 (engine-neutral readability): JSONL.gz parts parse
      with `gzip` + `json` only; CSV parts load with the
      Neptune-loader CSV reader and match the `neo4j-admin import`
      header rules.
    - Property 2 (no-re-embedding): SHA-256 over read embeddings
      equals SHA-256 over written embeddings.
    - Tenant zero-data case yields zero count, no error (R7.5).
    - _Requirements: 1.1, 1.2, 1.5, 5.1, 5.2, 5.3, 7.5_

- [ ] 10. Implement the Restore phases (COTS direction)
  - `phases/load_vectors_cots.py`: read Vector_Export parts; verify
    SHA-256; ChromaDB `collection.add` with bitwise embedding;
    watermark update; per-collection count assertion against
    manifest at end.
  - `phases/load_graph_cots.py`: read Graph_Export parts; verify
    SHA-256; either bulk-import via `neo4j-admin import` (preferred
    for >10K nodes) or transactional INSERT; watermark update.
  - `query_embedder_check` runs before any write and surfaces
    Query_Compatible / Query_Incompatible flags in the
    `COTS_Restore_Started` audit record.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 4.3, 4.4, 4.5, 13.3, 13.4_

  - [ ]* 10.1 COTS Restore unit tests + Property 4 (COTS_Restore completeness)
    - Property 4: per-collection ChromaDB count == manifest count
      (modulo Query_Incompatible flagged collections); per-tenant
      Neo4j node + relationship counts == manifest counts.
    - Per-part SHA-256 mismatch refuses load (R13.4).
    - Missing required fields per R2.4 records error and continues.
    - _Requirements: 2.1, 2.2, 2.4, 6.5, 13.3, 13.4_

- [ ] 11. Implement the Restore phases (AWS direction)
  - `phases/load_vectors_aws.py`: read Vector_Export parts; verify
    SHA-256; ensure target index has `knn_vector` mapping matching
    Model_Profile dimension; bulk index with bitwise embedding
    write; refuse on existing-incompatible-mapping per R3.5;
    watermark update.
  - `phases/load_graph_aws.py`: stage Graph_Export parts in S3
    (already there); invoke Neptune bulk loader pointing at
    `<prefix>/graph/<tenant>/`; poll until LOAD_COMPLETED;
    watermark update.
  - `phases/rebuild_dedupe_aws.py`: walk the re-imported content,
    compute `(collection, sha)` per tenant, write to
    `mdc-content-sha-registry`. Deterministic from content (R8.4).
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 5.3, 8.3, 8.4, 13.3, 13.4_

  - [ ]* 11.1 AWS Reimport unit tests + Property 3 (round-trip fidelity)
    - Property 3: per-tenant Neptune node + relationship counts and
      per-index OpenSearch document counts equal source via manifest;
      embeddings bitwise-identical (SHA-256 round-trip).
    - Incompatible mapping refusal (R3.5); dedupe rebuild
      idempotent across reruns (R8.4).
    - _Requirements: 3.3, 3.4, 3.5, 5.3, 6.1, 6.2, 6.3, 6.4, 8.3, 8.4_

- [ ] 12. Implement Count_Parity_Check and bundle support
  - `phases/count_parity.py`: per-collection / per-Model_Profile /
    per-tenant count comparison source-vs-destination; tolerance
    parameter (default 0%); JSON parity report written to S3 with
    timestamp; non-zero exit on any mismatch.
  - `bundle.py`: tar.gz pack of `<prefix>/**/*` for offline transfer;
    unpack to a destination directory for COTS_Restore on a
    network-disconnected host; preserve internal layout so S3-native
    and bundle restores are byte-equivalent.
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 12.1, 12.2, 12.3, 12.4, 13.1_

  - [ ]* 12.1 Verifier + bundle unit tests
    - Mismatched counts trigger non-zero exit with enumerated
      mismatches; tolerance applies per R10.1; bundle pack -> unpack
      yields byte-equivalent layout to S3-native (R12.4).
    - _Requirements: 10.2, 10.3, 12.4_

- [ ] 13. Implement the direction dispatcher and CLI
  - `direction_dispatcher.py`: direction -> (source readers, target
    writers, defaults) map; selective scope honored
    (`--vectors-only`, `--graph-only`, `--collections`, `--tenants`).
  - `portable_export_cli.py`: argparse for
    `{export|restore|reimport|verify|status}` with the flag set from
    the design; `status` reads manifest + watermarks + lock without
    locking; `--dry-run` prints the full plan with zero mutation;
    interactive confirmation gate (exact phrase) before any
    destination write per R15.1; `--yes` non-interactive token; CLI
    enforces `--vectors-only` / `--graph-only` per R14.3, R14.4.
  - Wire `query_embedder_check` into restore startup; surface
    `Query_Compatible` / `Query_Incompatible` flags in the completion
    audit.
  - _Requirements: 1, 2, 3, 9.4, 11.2, 14.1, 14.2, 14.3, 14.4, 14.5, 15.1, 15.2_

  - [ ]* 13.1 Dispatcher + CLI unit tests + Property 7 (confirmation gate)
    - Every direction resolves to expected adapter pair; selective
      scope honored; `--dry-run` mutates nothing;
      `status` does not lock.
    - Property 7: no destination write call across any restore /
      reimport path until confirmation phrase or `--yes` is captured
      and audit-recorded.
    - _Requirements: 9.4, 14.1, 14.2, 14.3, 14.4, 14.5, 15.1, 15.2_

- [ ] 14. Integration tests
  - **AWS_Export -> AWS_Reimport**: small fixture corpus (moto +
    Neptune stub); end-to-end run; Count_Parity_Check passes;
    Property 3 holds (counts equal, embeddings bitwise).
  - **AWS_Export -> COTS_Restore**: Docker-fixtures ChromaDB +
    Neo4j; Count_Parity_Check passes; Property 4 holds;
    Query_Incompatible flag surfaces correctly when ChromaDB has no
    Bedrock IAM.
  - **Bundle round-trip**: produce Export_Bundle; restore from
    bundle on a network-disconnected fixture; assert
    byte-equivalence with S3-native restore (R12.4).
  - **Resume round-trip**: kill an Export at part N; re-run with
    `--resume`; final manifest equals an uninterrupted manifest
    byte-for-byte.
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.1, 9.2, 12.4_

- [ ] 15. CHANGELOG and full-suite gate
  - CHANGELOG entry under the next minor version (new feature).
  - `cd SETUP_AWS/provisioning && python3.12 -m pytest portable_export/tests/ -q`
    green; `py_compile` clean on every module.
  - Deliver `SETUP_AWS/provisioning/RUNBOOK_portable_export.md`
    documenting AWS_Export, COTS_Restore, AWS_Reimport, the
    Query_Embedder availability matrix, the dedupe export-vs-rebuild
    policy, the bundle / offline-restore flow, and the Phase A-D
    operator-gated acceptance procedure. Modeled on
    `RUNBOOK_agentcore_creds.md` and `RUNBOOK_cost_control.md`.
  - _Requirements: 15.4, 15.5_

- [ ] 16. Phase A — gated `--dry-run` AWS_Export against `dev`
  - STOP-AND-CONFIRM before invoking against the live `dev` env.
  - `portable_export_cli.py export --env dev --tenants gw --dry-run`;
    golden-file the printed plan against the live tenant's
    `get_knowledge_base_status` output for sanity.
  - _Requirements: 1, 11.1_

- [ ] 17. Phase B — gated live AWS_Export of the `gw` tenant
  - STOP-AND-CONFIRM before any S3 write.
  - `portable_export_cli.py export --env dev --tenants gw` to a
    dedicated `s3://.../portable-export/dev/<id>/` prefix.
  - Verify `manifest.totals` match `get_knowledge_base_status(tenant_id="gw")`
    byte-for-byte; per-part SHA-256s reproducible by re-reading from
    S3 and recomputing.
  - Record manifest_id + total bytes + wall-clock for runbook.
  - _Requirements: 1.1, 1.2, 7.4, 11.1, 11.4, 13.2_

- [ ] 18. Phase C — gated live AWS_Reimport into a fresh dev destination
  - STOP-AND-CONFIRM before any destination write.
  - Provision a fresh `dev-reimport` env (separate index family, fresh
    Neptune cluster) and `portable_export_cli.py reimport --artefact
    s3://.../<id>/ --env dev-reimport`.
  - Confirm Count_Parity_Check passes and Property 3 holds live
    (post-reimport counts equal the manifest's preflight counts;
    embeddings bitwise-equal verified via SHA-256 round-trip).
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 6.1, 6.2, 6.3, 6.4, 10.1, 10.2_

- [ ] 19. Phase D — optional gated live COTS_Restore on a Docker host
  - STOP-AND-CONFIRM before any destination write.
  - Pull the Phase B artifact (or its Export_Bundle) onto a Docker
    host running the COTS_Stack (ChromaDB + Neo4j community);
    `portable_export_cli.py restore --artefact <bundle-or-s3>
    --target cots`.
  - Confirm Count_Parity_Check passes, Property 4 holds live, and
    Query_Compatible / Query_Incompatible flags are reported per
    Model_Profile.
  - _Requirements: 2.1, 2.2, 2.3, 4.3, 4.4, 4.5, 6.5, 12.2_

- [ ] 20. Final checkpoint
  - All unit + integration tests green.
  - Phase A-D live runs documented with audit captures and parity
    reports.
  - Runbook posted at `SETUP_AWS/provisioning/RUNBOOK_portable_export.md`.
  - Update `.kiro/steering/12-multi-tenant-gap-tracker.md` (or a
    portable-export note) noting first successful round-trip + the
    measured embedding-bitwise SHA-256 floor.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "1.1"] },
    { "id": 1, "tasks": ["2", "2.1", "3", "3.1", "4", "4.1", "5", "5.1"] },
    { "id": 2, "tasks": ["6", "6.1", "7", "7.1", "8", "8.1"] },
    { "id": 3, "tasks": ["9", "9.1", "10", "10.1", "11", "11.1", "12", "12.1"] },
    { "id": 4, "tasks": ["13", "13.1"] },
    { "id": 5, "tasks": ["14"] },
    { "id": 6, "tasks": ["15"] },
    { "id": 7, "tasks": ["16"] },
    { "id": 8, "tasks": ["17"] },
    { "id": 9, "tasks": ["18"] },
    { "id": 10, "tasks": ["19"] },
    { "id": 11, "tasks": ["20"] }
  ]
}
```

Wave 0 scaffolds the package + config. Wave 1 builds the shared primitives
(audit, lock+watermarks, manifest+KMS writer, query-embedder check) — all
independent and parallelizable. Wave 2 builds the six adapters on top of
those primitives — also parallelizable. Wave 3 builds the
direction-agnostic phase modules and the verifier+bundle. Wave 4 composes
them in the dispatcher + CLI and lands the property tests for resume,
idempotency, and confirmation. Wave 5 runs end-to-end integration tests
(round-trip, bundle, resume). Wave 6 is the CHANGELOG + suite gate +
runbook. Waves 7-11 are the operator-gated live Phase A->D against `dev`
plus the final checkpoint.

## Notes

- **Bottom-up with paired tests**: shared primitives -> adapters ->
  phases -> dispatcher/CLI -> integration -> live. Every code task has a
  `*` test task. The nine correctness properties are covered: P1 +
  P2 in 9.1, P3 in 11.1, P4 in 10.1, P5 in 6.1, P6 in 3.1 + 14, P7 in
  13.1, P8 in 9.1 + 11.1 (tenant prefix preservation in both
  directions), P9 in 11.1 (dedupe rebuild idempotent).
- **`--dry-run` from Wave 4**: no mutation can occur before the plan is
  reviewed. The first invocation in any env must be `--dry-run`.
- **Operator gates**: every Phase A-D step is STOP-AND-CONFIRM, per the
  existing provisioning convention. `--yes` is reserved for CI / the
  optional schedule mode (not in scope for v1).
- **Read-only invariant on AWS_Export**: Property 5 is enforced
  structurally — the SourceReader protocol exposes only read methods,
  and the test in 6.1 asserts no PUT/POST/DELETE call lands on the
  source data plane during any export run.
- **No re-embedding ever**: Property 2 is the hardest contract;
  per-part SHA-256 in the manifest is the on-the-wire enforcement, and
  the round-trip test in 11.1 closes the loop.
- **Engine-neutral by construction**: gzipped JSONL for vectors and
  Neptune-loader CSV for graph (a superset of `neo4j-admin import`)
  means both engines load the same files unchanged. No translation
  step.
- **Powers**: `aws-infrastructure-as-code` is not strictly required
  here (no CDK stacks; pure Python pipeline + S3), but
  `iam-policy-autopilot-power` is recommended for generating the
  least-privilege role for the export tooling once the source is
  written (Wave 5 / Wave 6).
- **No auto-commit**: CHANGELOG noted, commits only on operator
  request, per `08-git-operation-policy.md`.
- **Round-trip fidelity is the contract**: Property 3 (counts +
  embeddings byte-equal) gates the live acceptance in Phase C. A
  regression there is a fix-the-code moment, never a weaken-the-test
  moment.
