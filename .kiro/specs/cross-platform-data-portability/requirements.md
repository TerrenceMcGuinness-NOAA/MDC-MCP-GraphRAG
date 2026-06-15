# Requirements Document

## Introduction

The MDC MCP-RAG knowledge base — vectors in Amazon OpenSearch (~310,000
documents across 21 indices, gw + gw_v17 populated today), the property graph
in Amazon Neptune (~149K nodes / 4.5M relationships for gw, ~81K nodes / 1.28M
relationships for gw_v17), and supporting artefacts (the
`mdc-content-sha-registry` dedupe index, ECR images, the tenant catalog) —
represents many compute-hours of ingestion work and significant Bedrock
embedding spend. Today this state lives entirely in AWS-managed services
(OpenSearch and Neptune), whose proprietary on-disk formats are not readable
by any other product.

This feature defines the **Portable_Data_Roundtrip_System**: a comprehensive,
bidirectional export and restore pipeline that persists the entire knowledge
base in **engine-neutral S3 artefacts** that any of the following can read or
produce:

- The original COTS stack (Docker + ChromaDB + Neo4j community edition) that
  the `mcp_server_node` codebase was first built against.
- The current AWS deployment (OpenSearch + Neptune).
- Any future AWS account, after the source AWS account's data has been
  archived to a long-term portable form independent of native snapshot
  retention windows.

The motivating constraint is **funding resilience under the NIH Sandbox
managed AWS envelope**. If the AWS account ever lapses — for cost, for policy,
for end-of-grant — a portable export in S3 (or pulled to local disk) lets the
entire knowledge base be rehydrated into a local Docker stack with zero
re-ingestion. When funding resumes, the same artefact pushes back to AWS.

This spec is explicitly orthogonal to `nih-sandbox-cost-control`:

| | `nih-sandbox-cost-control` | `cross-platform-data-portability` (this) |
|---|----------------------------|------------------------------------------|
| Goal | Hibernate AWS to ~20% hourly cost | Survive AWS account loss / move between platforms |
| Format | Native engine snapshots (Neptune cluster snapshot, OpenSearch manual snapshot) | Engine-neutral logical export (JSONL / Parquet / openCypher CSV) |
| Restore target | AWS only | AWS or COTS |
| Speed | Minutes to hours | Hours (depends on size) |
| Retention floor | Snapshot lifecycle (typically days–months) | S3 lifecycle (typically months–years) |

The two systems coexist, share the S3 bucket layout where natural, and are
implemented independently.

The pipeline supports four modes, each addressed by the requirements below:

- **Mode E1** — AWS → S3 → COTS. Export from OpenSearch + Neptune; load into
  ChromaDB + Neo4j community edition.
- **Mode E2** — AWS → S3 → AWS. Long-term portable archive that can rehydrate
  AWS even after native snapshot retention windows have expired.
- **Mode I1** — COTS → S3 → AWS. The original `migrate-to-aws.js` direction;
  this spec normalizes and re-implements it on the modern v8 pipeline so all
  four modes share one codebase.
- **Mode I2** — COTS → S3 → COTS. Backup/restore for a community-edition
  installation.

The pipeline reuses the structural template established by
`mcp_server_node/scripts/migrate-to-aws.js` (5 phases: export-vectors,
export-graph, load-vectors, load-graph, verify) and
`mcp_server_node/scripts/verify-migration.js` (count-parity check), running the
same arrows in either direction with shared phase logic.

The deliverables land at `SETUP_AWS/provisioning/portability/` alongside the
existing host-provisioning runbooks.

## Glossary

- **Portable_Data_Roundtrip_System**: The aggregate of every artefact under
  `SETUP_AWS/provisioning/portability/` that participates in cross-platform
  export and restore. Includes the exporters, loaders, verifiers, manifests,
  schemas, and operator runbook.
- **Operator**: The human or service identity that initiates an Export or
  Restore operation. Identified in `Audit_Log_Record` entries by AWS caller
  identity ARN (when running against AWS) or by hostname + UID (when running
  against COTS).
- **Mode_E1 (AWS → S3 → COTS)**: An Export operation reading from OpenSearch
  + Neptune followed by a Restore operation loading the resulting
  `Portable_Artefact` into ChromaDB + Neo4j on a Docker host.
- **Mode_E2 (AWS → S3 → AWS)**: An Export operation reading from
  OpenSearch + Neptune followed (immediately or arbitrarily later) by a
  Restore operation loading the same `Portable_Artefact` back into a
  potentially different AWS account.
- **Mode_I1 (COTS → S3 → AWS)**: An Export operation reading from
  ChromaDB + Neo4j followed by a Restore operation loading into OpenSearch +
  Neptune. Equivalent in intent to the original `migrate-to-aws.js`
  five-phase pipeline.
- **Mode_I2 (COTS → S3 → COTS)**: An Export operation reading from
  ChromaDB + Neo4j followed by a Restore operation loading into a different
  ChromaDB + Neo4j installation.
- **Portable_Artefact**: The complete set of S3 objects produced by a single
  Export operation, comprising one `Manifest` plus one `Vector_Bundle` per
  exported collection plus one `Graph_Bundle` per exported tenant plus one
  `Auxiliary_Bundle` for supporting state. Self-describing — a future loader
  needs nothing but the artefact's S3 prefix to perform a Restore.
- **Manifest**: The single JSON object at `<artefact_prefix>/manifest.json`
  that records, for the run that produced the artefact, the source system,
  source AWS account / region / endpoints (when applicable), the timestamp,
  the operation id, the tenant set covered, the embedding profiles
  included, the schema version of the artefact format, the per-bundle
  checksums, the per-collection / per-label / per-relationship-type counts,
  and an optional GPG signature.
- **Vector_Bundle**: The portable representation of a single OpenSearch index
  (or ChromaDB collection): one or more JSONL or Parquet files keyed by
  `<artefact_prefix>/vectors/<collection>/<part>.{jsonl.gz | parquet}`. Each
  record carries `id`, `content`, `embedding` (float array), `metadata`
  (object), `model_profile`, `collection_name`, `chunk_id`.
- **Graph_Bundle**: The portable representation of a single tenant's
  property-graph subset: a node-files set + a relationship-files set in a
  format consumable by both `neptune-loader` (AWS) and `neo4j-admin import`
  (COTS), keyed by `<artefact_prefix>/graph/<tenant>/{nodes,rels}/<part>.csv.gz`.
- **Auxiliary_Bundle**: Supporting state that is neither a vector nor a
  graph: the dedupe registry, the tenant catalog as it existed at export
  time, the embedding model registry, ECR image-tag references (digests
  recorded by reference, not body), and any other AWS-side bookkeeping the
  loader needs to recreate operational dedupe and tenant resolution. Keyed
  by `<artefact_prefix>/auxiliary/`.
- **Engine_Neutral**: A format readable without a specific database engine.
  JSONL with explicit fields, Parquet with a published schema, and openCypher
  property-graph CSV are Engine_Neutral. Native OpenSearch index snapshots
  and Neptune cluster snapshots are NOT Engine_Neutral.
- **Bitwise_Preservation**: The property that the float-array `embedding`
  values written to the `Portable_Artefact` are byte-equal to the values
  read from the source data store, with no re-embedding from `content`.
  Required for any model that the destination cannot replicate locally.
- **Re_embed_From_Text**: The opt-in fallback in which a Restore re-generates
  embeddings from each record's `content` field using an embedder available
  on the destination, rather than carrying the source vectors bitwise.
  Necessary when the destination cannot serve queries with the source
  embedder (for example, COTS without Bedrock reach-back facing a Titan
  vector store).
- **Embedding_Profile**: The named embedding model used to produce a vector,
  one of `mpnet768`, `titan1024`, `nova256`, `nova512`, `nova1024`,
  `nova3072`. Carried per record in the `Vector_Bundle` and per collection
  in the `Manifest`.
- **Tenant_Prefix_Handling**: The per-mode policy that decides how source
  tenant prefixes (OpenSearch index prefix `gw_v17_`, Neptune label prefix
  `GW_V17_`) are represented in the `Portable_Artefact` and re-applied at
  Restore. Two policies are supported: **Preserve** (carry the prefix into
  the bundle as part of the collection name / label name) and **Flatten**
  (strip the prefix, store the tenant in metadata, re-apply on Restore).
- **Dedupe_Registry_Export**: The Auxiliary sub-bundle containing the
  contents of `mdc-content-sha-registry` (or its COTS equivalent), so that
  re-ingestion against the restored knowledge base honors the same dedupe
  decisions and avoids re-embedding identical content.
- **Round_Trip_Integrity**: The property that, for any chain
  Export(source) → Restore(destination) → Export(destination) →
  Restore(source'), the final source' state has identical document
  identifiers, metadata, embeddings, node properties, relationship
  endpoints, and counts to the original source state, modulo documented
  per-engine fields that are auto-generated (timestamps, internal ids).
- **Watermarked_Resume**: The property that any Export or Restore phase
  may be killed and re-invoked with `--resume` to continue from the last
  successfully written watermark, identical in shape to the watermarks
  used by `migrate-to-aws.js`.
- **Verifier**: The post-Restore step that computes per-collection /
  per-label / per-relationship-type counts on the destination and compares
  them to the `Manifest`'s counts; emits a parity report; fails non-zero
  on mismatch beyond the configured tolerance.
- **Restore_Confirmation_Gate**: The interactive operator step that prevents
  a Restore from proceeding against a destination that already contains
  data, until the Operator supplies the exact phrase declared by the
  Restore subcommand or an explicit `--overwrite` token.
- **Schedule_Mode**: The optional automated invocation path that runs an
  Export on a recurring schedule (e.g., weekly), with S3 lifecycle policies
  for retention. Off by default.
- **Audit_Log_Record**: A structured JSON record emitted by every phase of
  every Export or Restore operation. Same shape as the cost-control audit
  record, with `event_type` values drawn from this spec's vocabulary
  (`Export_Started`, `Vector_Bundle_Written`, `Graph_Bundle_Written`,
  `Manifest_Written`, `Restore_Started`, `Vector_Restore_Completed`,
  `Graph_Restore_Completed`, `Verifier_Passed`, `Verifier_Failed`,
  `Export_Completed`, `Restore_Completed`, `Concurrent_Operation_Refused`).
- **Environment_Name**: The CDK / CLI context value (e.g. `dev`, `staging`,
  `prod`) that parameterizes every artefact prefix, every audit S3 prefix,
  and the operator confirmation phrase. Same allow-list as cost-control.
- **Provisioning_Directory**: The fixed path
  `SETUP_AWS/provisioning/` in this repository. Every artefact produced by
  this spec lands under `SETUP_AWS/provisioning/portability/`.

## Requirements

### Requirement 1: Engine-Neutral Artefact Format

**User Story:** As a knowledge-base steward, I want the exported data
artefact to be readable without OpenSearch or Neptune, so that the
knowledge base survives the loss of either AWS service or the AWS account
that hosts them.

#### Acceptance Criteria

1. THE Portable_Data_Roundtrip_System SHALL emit every Vector_Bundle as
   either gzipped JSONL or columnar Parquet, with a published schema that
   includes at minimum the fields `id`, `content`, `embedding` (float array),
   `metadata` (object), `model_profile`, `collection_name`, and `chunk_id`.
2. THE Portable_Data_Roundtrip_System SHALL emit every Graph_Bundle as
   openCypher property-graph CSV files (one set for nodes, one for
   relationships) consumable both by `neptune-loader` and by `neo4j-admin
   import` without translation.
3. THE Portable_Data_Roundtrip_System SHALL NOT emit any artefact whose
   readability depends on a specific OpenSearch index version, a specific
   Neptune snapshot version, or any other engine-proprietary on-disk
   format.
4. THE Portable_Data_Roundtrip_System SHALL include in every Vector_Bundle
   and Graph_Bundle a sibling `_schema.json` describing the field types
   and units, so that a future loader written against a later format
   version can read older bundles deterministically.

### Requirement 2: Bitwise Embedding Preservation

**User Story:** As a knowledge-base steward, I want every embedding in the
artefact to be byte-equal to the source value, so that no Bedrock spend or
local-model compute is required to round-trip the data and so that
similarity search produces the same results before and after a round-trip.

#### Acceptance Criteria

1. WHEN an Export operation reads a vector from OpenSearch or ChromaDB,
   THE Portable_Data_Roundtrip_System SHALL write the float array to the
   Vector_Bundle without converting precision, re-quantizing, or
   regenerating from `content`.
2. THE Portable_Data_Roundtrip_System SHALL tag every record in a
   Vector_Bundle with the `model_profile` value associated with the
   source collection, so that a future Restore can decide whether the
   bitwise vectors are usable in the target system.
3. WHEN a Restore operation loads a Vector_Bundle into OpenSearch or
   ChromaDB, THE Portable_Data_Roundtrip_System SHALL preserve the float
   array byte-for-byte unless the operator has explicitly opted into
   `Re_embed_From_Text` for that collection.
4. THE Portable_Data_Roundtrip_System SHALL emit a per-bundle checksum
   (SHA-256) over the concatenated record bodies and SHALL record that
   checksum in the Manifest, so that bitwise preservation is verifiable
   without re-reading the source.

### Requirement 3: Embedding-Model Fidelity Policy

**User Story:** As an operator restoring an artefact onto a target system
that may not have access to every embedding model, I want an explicit,
per-collection policy that decides which embeddings to keep bitwise versus
which to re-generate from `content`, so that the restored system can
actually serve queries.

#### Acceptance Criteria

1. THE Portable_Data_Roundtrip_System SHALL document an
   embedder-availability matrix for the supported targets — for example,
   COTS without Bedrock can serve queries against `mpnet768` collections
   but not against `titan1024` or `nova*` collections.
2. WHEN a Restore is invoked in `Mode_E1` (AWS → COTS), THE
   Portable_Data_Roundtrip_System SHALL by default include only
   collections whose `model_profile` is locally embeddable on the
   destination, and SHALL require an explicit `--include-bedrock-models`
   flag for collections whose `model_profile` requires Bedrock reach-back.
3. WHEN the operator opts into `Re_embed_From_Text` for a collection, THE
   Portable_Data_Roundtrip_System SHALL re-generate embeddings on the
   destination using the destination's locally available embedder, SHALL
   record the re-embedding event in the Audit_Log_Record, and SHALL update
   the Manifest's per-collection `model_profile` field to the new
   destination model.
4. WHEN a Restore is invoked in `Mode_E2` or `Mode_I2` (same-platform),
   THE Portable_Data_Roundtrip_System SHALL default to bitwise preservation
   for all collections regardless of profile.

### Requirement 4: Tenant Prefix Handling

**User Story:** As an operator round-tripping a multi-tenant deployment, I
want a documented, deterministic policy for how source tenant prefixes are
represented in the artefact and re-applied at Restore, so that tenant
isolation survives a round-trip in either direction.

#### Acceptance Criteria

1. WHEN an Export reads from a tenant-prefixed source (e.g. OpenSearch
   indices `gw_v17_mdc-*` or Neptune labels `GW_V17_*`), THE
   Portable_Data_Roundtrip_System SHALL apply the operator-selected
   `Tenant_Prefix_Handling` policy uniformly across the entire run, one
   of `Preserve` or `Flatten`.
2. WHEN the policy is `Preserve`, THE Portable_Data_Roundtrip_System SHALL
   carry the source prefix verbatim into the Vector_Bundle's
   `collection_name` and the Graph_Bundle's label names.
3. WHEN the policy is `Flatten`, THE Portable_Data_Roundtrip_System SHALL
   strip the source prefix from `collection_name` / label name, SHALL
   record the originating tenant in the per-record `metadata.tenant_id`
   and per-node `tenant_id` property, and SHALL preserve the round-trip
   so that a subsequent Restore against a tenant-aware destination can
   re-apply the prefix.
4. THE Portable_Data_Roundtrip_System SHALL record the chosen
   `Tenant_Prefix_Handling` policy in the Manifest, so that any future
   Restore knows which transformation to invert.
5. WHEN the operator selects a tenant subset via `--tenants gw,gw_v17`,
   THE Portable_Data_Roundtrip_System SHALL Export only the
   selected tenants and SHALL record the selected set in the Manifest.

### Requirement 5: Manifest and Provenance

**User Story:** As an operator who receives a Portable_Artefact months
later from a different system, I want a single self-describing Manifest
that tells me everything needed to Restore correctly, so that I can never
mistake what I am looking at.

#### Acceptance Criteria

1. THE Portable_Data_Roundtrip_System SHALL emit one Manifest per Export
   operation at `<artefact_prefix>/manifest.json`.
2. THE Manifest SHALL contain at minimum the fields `schema_version`,
   `artefact_id` (UUID), `produced_at` (ISO 8601 UTC), `produced_by`
   (caller identity), `source_system` (one of `aws-opensearch+neptune`,
   `cots-chromadb+neo4j`), `source_aws_account_id` (when applicable),
   `source_region` (when applicable), `tenants` (list of tenant ids),
   `tenant_prefix_handling` (one of `Preserve`, `Flatten`),
   `embedding_profiles` (per-collection map),
   `vector_bundles` (per-collection list of `{collection_name, record_count,
   parts, sha256}`), `graph_bundles` (per-tenant list of `{tenant_id,
   node_count, relationship_count, parts, sha256}`),
   `auxiliary_bundles` (list of `{name, parts, sha256}`).
3. THE Portable_Data_Roundtrip_System SHALL support an optional GPG
   signature on the Manifest, recorded as a sibling
   `<artefact_prefix>/manifest.json.sig` when the operator supplies a
   signing key.
4. THE Portable_Data_Roundtrip_System SHALL refuse a Restore whose
   Manifest's `schema_version` major version is greater than the loader's
   supported major, and SHALL exit with a non-zero status and a
   `Manifest_Schema_Unsupported` Audit_Log_Record.

### Requirement 6: Auxiliary Bundle (Dedupe Registry, Catalogs, Image References)

**User Story:** As an operator restoring an artefact into AWS, I want the
restored system to inherit the same dedupe decisions and tenant catalog as
the source, so that re-ingestion runs do not re-embed content that the
source already considered duplicate and so that the tenant resolver
recognizes the same tenants.

#### Acceptance Criteria

1. WHEN an Export reads from AWS, THE Portable_Data_Roundtrip_System SHALL
   include in the Auxiliary_Bundle a snapshot of the
   `mdc-content-sha-registry` index contents, sufficient for a Restore to
   recreate dedupe state.
2. WHEN an Export reads from COTS, THE Portable_Data_Roundtrip_System SHALL
   include in the Auxiliary_Bundle whatever dedupe state the COTS
   ingestion path uses, even if its representation differs from the AWS
   side.
3. THE Portable_Data_Roundtrip_System SHALL include in the Auxiliary_Bundle
   a copy of `mcp_server_python/src/config/tenants.yaml` as it existed at
   Export time and a copy of `mcp_server_python/src/data/embedding_registry.py`'s
   declared model registry.
4. THE Portable_Data_Roundtrip_System SHALL include in the
   Auxiliary_Bundle a list of ECR image references (digest, repo, tag) by
   reference only — image bodies SHALL NOT be exported because ECR storage
   is already content-addressed and engine-neutral.
5. WHEN a Restore loads the Auxiliary_Bundle, THE Portable_Data_Roundtrip_System
   SHALL recreate the dedupe registry on the destination if the destination
   uses a compatible registry layout, and SHALL emit a
   `Dedupe_Registry_Skipped` Audit_Log_Record otherwise so the operator
   knows to rebuild dedupe via re-ingestion.

### Requirement 7: Round-Trip Integrity Verification

**User Story:** As a knowledge-base steward, I want every Restore to
verify count parity and checksum integrity against the Manifest before
declaring success, so that I cannot mistakenly treat a partial Restore as
a successful one.

#### Acceptance Criteria

1. WHEN a Restore completes its load phases, THE Portable_Data_Roundtrip_System
   SHALL invoke the Verifier and SHALL not emit a `Restore_Completed`
   Audit_Log_Record until the Verifier passes.
2. THE Verifier SHALL compare per-collection record counts on the
   destination against the Manifest's `vector_bundles[*].record_count`
   values, per-tenant node and relationship counts on the destination
   against the Manifest's `graph_bundles[*].node_count` and
   `relationship_count` values, and per-bundle SHA-256 checksums recomputed
   on the destination's loaded data against the Manifest's `sha256`
   values, with a configurable tolerance defaulting to 0% for counts and
   0% for checksums.
3. IF the Verifier detects any mismatch beyond the configured tolerance,
   THEN THE Portable_Data_Roundtrip_System SHALL emit a
   `Verifier_Failed` Audit_Log_Record enumerating each mismatch, SHALL
   NOT mark the Restore as complete, and SHALL exit with a non-zero
   status.
4. THE Portable_Data_Roundtrip_System SHALL persist the Verifier report
   to S3 at `<artefact_prefix>/verify-<destination_id>-<timestamp>.json`,
   so that audit reviewers can reconstruct the parity check without
   re-running it.

### Requirement 8: Watermarked Resume

**User Story:** As an operator running a multi-hour Export or Restore
across hundreds of thousands of documents, I want any phase to resume
from the last successfully written watermark after a crash or interrupt,
so that I do not have to redo work that already succeeded.

#### Acceptance Criteria

1. THE Portable_Data_Roundtrip_System SHALL persist a watermark file at
   `<artefact_prefix>/watermarks.json` after every successfully written
   Vector_Bundle part, every successfully written Graph_Bundle part,
   every successfully written Auxiliary sub-bundle, and every successfully
   loaded destination batch.
2. WHEN an Export or Restore is invoked with `--resume`, THE
   Portable_Data_Roundtrip_System SHALL read the watermark file, SHALL
   skip every part marked complete, and SHALL re-execute every
   incomplete part exactly once.
3. THE Portable_Data_Roundtrip_System SHALL refuse a `--resume` whose
   watermark file references a different `artefact_id` than the one the
   current invocation is writing to, and SHALL exit with a non-zero
   status and a `Watermark_Mismatch` Audit_Log_Record.
4. THE Portable_Data_Roundtrip_System SHALL update the watermark file
   atomically (write-temp + rename, or S3 conditional write), so that a
   process killed mid-write does not corrupt the watermark.

### Requirement 9: Idempotency and Concurrent-Operation Refusal

**User Story:** As an operator, I want re-issuing an Export over an
already-current artefact to be a safe no-op, and concurrent Exports or
Restores against the same artefact prefix to be refused, so that I cannot
corrupt the artefact by running two operations at once.

#### Acceptance Criteria

1. WHEN the Operator invokes an Export and the target `<artefact_prefix>`
   already contains a Manifest whose source-state digest matches the
   current source-state digest, THE Portable_Data_Roundtrip_System SHALL
   emit an `Export_NoOp` Audit_Log_Record and SHALL exit with status 0
   without writing any new bundle.
2. THE Portable_Data_Roundtrip_System SHALL acquire an S3-versioned lock
   (read+If-Match write to `<artefact_prefix>/lock.json`) before
   beginning any Export or Restore, and SHALL refuse a second
   concurrent invocation with a `Concurrent_Operation_Refused`
   Audit_Log_Record and a non-zero exit when the prior lock holder is
   still active.
3. THE Portable_Data_Roundtrip_System SHALL release the lock on
   completion, on failure, and via a documented `--break-lock` flag whose
   use SHALL be recorded in the Audit_Log_Record.

### Requirement 10: Restore Confirmation Gate and Overwrite Protection

**User Story:** As an operator restoring an artefact into a destination
that may already contain data, I want an explicit confirmation gate
before the Restore proceeds, so that I cannot silently overwrite a
populated destination from a stale terminal.

#### Acceptance Criteria

1. WHEN a Restore is invoked interactively against a destination that is
   non-empty (any matching index, collection, label, or graph
   relationship exists), THE Portable_Data_Roundtrip_System SHALL display
   the destination summary, the Manifest summary, and the Restore plan,
   and SHALL prompt the Operator for an exact confirmation phrase before
   issuing any write API call against the destination.
2. THE Portable_Data_Roundtrip_System SHALL accept a non-interactive
   `--overwrite` token that substitutes for the interactive prompt, for
   CI runners and the Schedule_Mode invoker, and SHALL log usage of the
   flag in the Restore_Started Audit_Log_Record.
3. IF the Operator response to the Restore_Confirmation_Gate does not
   match the exact phrase, THEN THE Portable_Data_Roundtrip_System SHALL
   emit a `Confirmation_Declined` Audit_Log_Record, SHALL NOT modify any
   destination resource, and SHALL exit with status 0.
4. WHEN a Restore would write into a destination already containing
   records with the same `id` as records in the Vector_Bundle, THE
   Portable_Data_Roundtrip_System SHALL apply the operator-selected
   conflict policy, one of `error-on-conflict` (default), `skip`, or
   `overwrite`, and SHALL record the chosen policy and the resulting
   per-collection conflict counts in the Audit_Log_Record.

### Requirement 11: Encryption at Rest and KMS

**User Story:** As a steward of a knowledge base that may contain code
and documentation considered sensitive, I want every S3 object in the
Portable_Artefact encrypted at rest under a customer-managed KMS key, so
that the artefact's confidentiality is auditable and revocable.

#### Acceptance Criteria

1. THE Portable_Data_Roundtrip_System SHALL write every S3 object in the
   Portable_Artefact and the Audit_Log S3 prefix using SSE-KMS with a
   customer-managed key whose ARN is supplied by configuration.
2. THE Portable_Data_Roundtrip_System SHALL refuse to write to an S3
   bucket whose default encryption is not configured for SSE-KMS, and
   SHALL exit with a `Bucket_Encryption_Misconfigured`
   Audit_Log_Record and a non-zero status.
3. THE Portable_Data_Roundtrip_System SHALL document, in the runbook,
   the KMS key policy statements required for an off-account or off-AWS
   reader to decrypt the artefact (cross-account `kms:Decrypt` grants,
   or off-AWS download by an AWS-credentialed reader).

### Requirement 12: Audit Trail and Observability

**User Story:** As an auditor, I want every phase of every Export and
Restore to leave a structured, searchable record, so that operations
months apart can be reconstructed without re-running them.

#### Acceptance Criteria

1. THE Portable_Data_Roundtrip_System SHALL emit every Audit_Log_Record
   as a single JSON object on a single line, with at minimum the fields
   `timestamp`, `event_type`, `operation_id`, `caller_arn` (or
   `caller_host` for COTS-side), `mode` (`E1`, `E2`, `I1`, `I2`),
   `environment_name`, `artefact_id`, `phase`, `aws_resource_arns`
   (when applicable), `bundle_keys` (when applicable),
   `record_counts` (when applicable), `elapsed_seconds`, and `error`.
2. THE Portable_Data_Roundtrip_System SHALL persist every
   Audit_Log_Record to a CloudWatch log group named
   `mdc-mcp-rag-portability-{environment_name}` (when running with
   AWS credentials) and to the local file
   `~/.mdc-mcp-rag/portability/<operation_id>.jsonl` in all cases.
3. THE Portable_Data_Roundtrip_System SHALL persist a per-operation
   consolidated audit S3 object at
   `<artefact_prefix>/audit/<operation_id>.jsonl` upon Export or Restore
   completion, written exactly once.

### Requirement 13: Multi-Environment and Multi-Tenant Parameterization

**User Story:** As a developer maintaining the pipeline, I want every
artefact prefix and every audit prefix to be parameterized by environment
and tenant, so that test, staging, and production exports cannot be
mixed and so that a single tenant can be selectively exported and
restored.

#### Acceptance Criteria

1. THE Portable_Data_Roundtrip_System SHALL accept an `Environment_Name`
   from the same allow-list defined for `nih-sandbox-cost-control` and
   SHALL refuse any value outside the allow-list.
2. THE Portable_Data_Roundtrip_System SHALL include `Environment_Name` in
   every artefact prefix
   (`s3://<bucket>/portability/<environment>/<artefact_id>/`) and in
   every audit S3 key.
3. THE Portable_Data_Roundtrip_System SHALL accept a `--tenants` argument
   that selects a subset of the source `Tenant_Catalog` for both Export
   and Restore, defaulting to all tenants present at the source.
4. THE Portable_Data_Roundtrip_System SHALL apply the tag
   `mdc-mcp-rag:portability-environment` set to the resolved
   `Environment_Name` on every AWS resource it creates.

### Requirement 14: Optional Schedule Mode

**User Story:** As a steward who wants a hands-off retention strategy, I
want the option to enable a recurring Export schedule (for example,
weekly), so that an off-AWS reader always has a recent artefact and so
that S3 lifecycle policies retain the right number of versions.

#### Acceptance Criteria

1. THE Portable_Data_Roundtrip_System SHALL support a Schedule_Mode that,
   when enabled, registers an EventBridge cron rule plus a Lambda
   invoker that executes the same Export code path used by the operator
   CLI.
2. THE Portable_Data_Roundtrip_System SHALL ship with Schedule_Mode
   disabled by default; enabling SHALL require the operator to set a
   CDK context value (`schedule_enabled=true`) and to provide an export
   cron expression.
3. WHERE Schedule_Mode is enabled, THE Portable_Data_Roundtrip_System
   SHALL bypass the interactive Confirmation_Gate (Export only — Restore
   never auto-runs) and SHALL emit a `Scheduled_Export`
   Audit_Log_Record whose `caller_arn` is the EventBridge invoker's
   role ARN.
4. THE Portable_Data_Roundtrip_System SHALL apply an S3 lifecycle policy
   to the artefact prefix that retains the most recent N artefacts
   (configurable, default 4) and that transitions older artefacts to a
   cheaper storage class (Standard-IA or Glacier) after a configurable
   age (default 30 days) before deletion at a configurable age (default
   365 days).

### Requirement 15: Artifact Location and Provisioning Alignment

**User Story:** As an operator, I want every artefact produced by this
feature to land alongside the existing host-provisioning runbooks and
the cost-control system, so that operator workflows are co-located.

#### Acceptance Criteria

1. THE Portable_Data_Roundtrip_System SHALL deliver every CLI module,
   loader, verifier, schema definition, IAM policy template, EventBridge
   schedule definition, Lambda handler, and operator runbook to a
   subtree rooted at `SETUP_AWS/provisioning/portability/`.
2. THE Portable_Data_Roundtrip_System SHALL deliver an operator runbook
   at `SETUP_AWS/provisioning/RUNBOOK_portability.md` that documents the
   four modes (`Mode_E1`, `Mode_E2`, `Mode_I1`, `Mode_I2`), the
   embedder-availability matrix, the Restore_Confirmation_Gate
   procedure, the `--break-lock` recovery procedure, the KMS cross-
   account access procedure, and the Schedule_Mode procedures, modeled
   on `RUNBOOK_agentcore_creds.md` and `RUNBOOK_cost_control.md`.
3. WHEN a CLI is invoked from a path outside
   `SETUP_AWS/provisioning/portability/`, THE
   Portable_Data_Roundtrip_System SHALL still resolve every relative
   path it depends on to a location under
   `SETUP_AWS/provisioning/portability/`, so that the artefact tree is
   the single source of truth regardless of the operator's working
   directory.

### Requirement 16: Independence from Cost-Control

**User Story:** As a maintainer reading this spec months from now, I
want a clear, enforced separation between the portable export pipeline
and the AWS-only hibernate/wake pipeline, so that the two systems can
evolve independently and so that future operators are not confused
about which to use when.

#### Acceptance Criteria

1. THE Portable_Data_Roundtrip_System SHALL NOT consume any S3 object
   produced by `nih-sandbox-cost-control` (Neptune cluster snapshots,
   OpenSearch manual snapshots) as the source of an Export.
2. THE Portable_Data_Roundtrip_System SHALL NOT register any
   EventBridge rule, Lambda function, or IAM role that
   `nih-sandbox-cost-control` also registers with the same name.
3. THE Portable_Data_Roundtrip_System SHALL share the S3 bucket layout
   only at the bucket level (`<state-bucket>`, `<audit-bucket>`,
   `<artefact-bucket>`), not at the prefix level — cost-control writes
   under `cost-control/`, this spec writes under `portability/`, and
   neither prefix shall reference the other.
4. THE Portable_Data_Roundtrip_System SHALL document, in its runbook,
   the choice matrix that tells an operator when to use this system
   (cross-platform, long-term, slower) versus when to use
   `nih-sandbox-cost-control` (AWS-only, hibernation-paced, faster).
