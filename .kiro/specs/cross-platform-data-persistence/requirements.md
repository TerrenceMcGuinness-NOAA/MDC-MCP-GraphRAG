# Requirements Document

## Introduction

The MDC MCP-RAG knowledge base currently lives entirely inside the NIH Sandbox AWS
account: vector embeddings and documents in Amazon OpenSearch, and the code/workflow
property graph in Amazon Neptune. That data was originally built in an open-source
GOTS stack (ChromaDB for vectors, Neo4j for the graph) running in Docker, then moved
into AWS by the inbound `migrate-to-aws.js` pipeline (ChromaDB -> S3 -> OpenSearch,
Neo4j -> S3 -> Neptune) using gzipped JSON staging, watermarks for idempotent resume,
and a count-parity verification step (`verify-migration.js`).

This feature is the OUTBOUND mirror of that pipeline. It persists the entire knowledge
base across platforms so it can leave AWS and come back without re-ingestion. The
motivation is funding resilience: if the NIH Sandbox AWS account lapses, a portable
export lets the whole knowledge base rehydrate into a local COTS/open-source stack
(ChromaDB + Neo4j) with zero re-ingestion, and push back to AWS when funding resumes.
This complements, and does not replace, the separate `nih-sandbox-cost-control`
sleep/wake feature.

The feature covers ALL modes of system-state persistence by naming two distinct
persistence modes and three transfer directions.

### Two persistence modes

- **Native_Snapshot mode** (AWS -> S3 -> AWS only): an OpenSearch manual snapshot plus
  a Neptune cluster snapshot. Fast and lossless, but engine-proprietary; the artifacts
  are NOT readable by ChromaDB or Neo4j and can only round-trip back to AWS. This mode
  already exists for the `nih-sandbox-cost-control` sleep/wake feature. This spec
  references it as the AWS-only fast path and does not duplicate it.
- **Portable_Export mode** (engine-neutral, cross-platform): a logical export of
  vectors to a row-oriented format (such as gzipped JSONL or Parquet) and the graph to
  a property-graph format (such as CSV or JSON). The result is readable by BOTH the
  COTS stack (ChromaDB + Neo4j) AND re-importable to AWS (OpenSearch + Neptune). This
  is the new capability and the heart of the spec.

### Three transfer directions

1. **AWS_Export** (AWS -> S3): scroll/scan OpenSearch and Neptune into the engine-neutral
   Portable_Export staged in S3.
2. **COTS_Restore** (S3 -> ChromaDB + Neo4j): load the Portable_Export into the original
   open-source Docker stack, including offline on a disconnected host.
3. **AWS_Reimport** (S3 -> OpenSearch + Neptune): load the Portable_Export back into AWS
   at a later date, completing the round trip.

The proven inbound mapping tables, S3 staging layout, and bitwise embedding-preservation
approach from `migrate-to-aws.js` carry over to the outbound direction.

## Glossary

- **Knowledge_Base**: The combined OpenSearch vector store and Neptune property graph
  that the MCP-RAG server reads, across all tenants.
- **Portable_Export**: An engine-neutral, cross-platform export of the Knowledge_Base
  (vectors + graph) staged in S3, readable by both the COTS stack and AWS.
- **Native_Snapshot**: An engine-proprietary OpenSearch manual snapshot plus Neptune
  cluster snapshot. Fast and lossless, but round-trips only back to AWS. Owned by the
  `nih-sandbox-cost-control` feature; referenced, not implemented, here.
- **AWS_Export**: The transfer direction that reads OpenSearch and Neptune and writes a
  Portable_Export to S3.
- **COTS_Restore**: The transfer direction that reads a Portable_Export from S3 and writes
  it into the COTS stack (ChromaDB + Neo4j).
- **AWS_Reimport**: The transfer direction that reads a Portable_Export from S3 and writes
  it back into AWS (OpenSearch + Neptune).
- **COTS_Stack**: The original open-source Docker deployment the platform was ported FROM,
  comprising ChromaDB (vectors) and Neo4j (graph).
- **Vector_Export**: The portion of a Portable_Export holding, per document,
  `(id, content, embedding, metadata, model_profile, collection_name)`.
- **Graph_Export**: The portion of a Portable_Export holding the property graph as nodes
  (labels + properties) and relationships (type + properties).
- **Export_Manifest**: A machine-readable document written with every Portable_Export
  recording source endpoints, timestamp, per-collection and per-tenant counts, model
  profiles, embedding dimensions, tenant list, schema version, tool version, and per-object
  checksums.
- **Model_Profile**: The identifier of the embedding model that produced a stored vector
  (for example `titan1024` for Amazon Bedrock Titan 1024-dim, or `mpnet768` for the
  768-dim MPNet model). Carried per document.
- **Query_Embedder**: The embedding model a consuming system uses to embed query text at
  search time. Similarity search is only meaningful when the Query_Embedder matches the
  Model_Profile of the stored vectors.
- **Query_Compatible**: A state in which a restore target has access to a Query_Embedder
  matching every restored Model_Profile.
- **Query_Incompatible**: A state in which a restore target lacks a Query_Embedder matching
  one or more restored Model_Profiles; the restore is explicitly flagged as such.
- **Round_Trip_Fidelity**: The property that an AWS_Export followed by an AWS_Reimport
  reproduces the source: per-tenant Neptune node and relationship counts equal, per-index
  OpenSearch document counts equal, and embeddings bitwise-identical.
- **Count_Parity_Check**: A verification step that compares source and destination counts
  per collection, per Model_Profile, and per tenant, and reports a non-zero exit status
  on any mismatch. Mirrors `verify-migration.js`.
- **Dedupe_Registry**: The AWS-internal content-hash bookkeeping store
  (`mdc-content-sha-registry`, approximately 52,000 entries) keyed by `(collection, sha)`
  per tenant, used to skip re-ingesting duplicate content.
- **Dedupe_Registry_Export**: The exported form of the Dedupe_Registry, or the rules for
  deterministically rebuilding it on AWS_Reimport.
- **Watermark**: A persisted progress marker in S3 recording the last completed batch for
  a phase/collection/model/tenant unit, enabling idempotent resume.
- **Export_Bundle**: A single self-contained gzipped tarball artifact containing a complete
  Portable_Export plus its Export_Manifest, suitable for offline transfer to a disconnected
  COTS host.
- **Tenant_Catalog**: The set of tenants defined in `tenants.yaml` (`gw`, `gw_sfs`,
  `gw_jedi_gfs`, `gw_v17`, `gw_gefs_v12`), each with an index prefix and label prefix.
- **Index_Family**: The set of OpenSearch indices belonging to one tenant, identified by
  the tenant's index prefix (for example the unprefixed `mdc-*` baseline for `gw`, or
  `gw_v17_mdc-*` for `gw_v17`).
- **Operator**: The human running the export/restore/reimport tooling, who confirms gated
  destructive actions.

## Requirements

### Requirement 1: Engine-neutral export of AWS data to S3 (Portable_Export)

**User Story:** As an Operator, I want the full AWS Knowledge_Base exported to S3 in an
engine-neutral form, so that the data can be restored to either the COTS stack or back to
AWS.

#### Acceptance Criteria

1. WHEN AWS_Export runs in Portable_Export mode, THE System SHALL read every targeted
   OpenSearch index and write each document to S3 as a Vector_Export record containing
   `(id, content, embedding, metadata, model_profile, collection_name)`.
2. WHEN AWS_Export runs in Portable_Export mode, THE System SHALL read the Neptune property
   graph and write a Graph_Export to S3 containing nodes with labels and properties and
   relationships with type and properties.
3. THE System SHALL stage Vector_Export and Graph_Export artifacts in S3 under a
   model-aware and tenant-aware key layout consistent with the inbound migration layout.
4. WHERE the Operator selects Native_Snapshot mode, THE System SHALL defer to the
   `nih-sandbox-cost-control` snapshot path and SHALL NOT produce an engine-neutral export.
5. THE System SHALL produce Portable_Export artifacts that are independent of any running
   OpenSearch or Neptune instance once written to S3.

### Requirement 2: Restore the S3 export into the COTS stack (ChromaDB + Neo4j)

**User Story:** As an Operator, I want to restore the S3 Portable_Export into ChromaDB and
Neo4j, so that the knowledge base runs on the original open-source stack with no
re-ingestion.

#### Acceptance Criteria

1. WHEN COTS_Restore runs, THE System SHALL load each Vector_Export record into ChromaDB as
   `(ids, documents, embeddings, metadatas)`.
2. WHEN COTS_Restore runs, THE System SHALL load the Graph_Export into Neo4j as nodes with
   labels and properties and relationships with type and properties.
3. THE System SHALL preserve tenant-prefixed label families and relationship types during
   COTS_Restore for every tenant present in the Portable_Export.
4. IF a Vector_Export record is missing a required field of `(id, content, embedding,
   model_profile)`, THEN THE System SHALL record the record identifier as an error and
   SHALL continue restoring the remaining records.
5. THE System SHALL load embeddings into ChromaDB exactly as stored in the Vector_Export,
   without re-computing any embedding.

### Requirement 3: Re-import the S3 export back into AWS (OpenSearch + Neptune)

**User Story:** As an Operator, I want to re-import the S3 Portable_Export back into
OpenSearch and Neptune, so that the data can return to AWS when funding resumes.

#### Acceptance Criteria

1. WHEN AWS_Reimport runs, THE System SHALL load each Vector_Export record into the
   OpenSearch index resolved from `collection_name`, `model_profile`, and tenant prefix.
2. WHEN AWS_Reimport runs, THE System SHALL load the Graph_Export into Neptune using the
   Neptune bulk loader from the S3 staging location.
3. THE System SHALL re-create OpenSearch indices with a `knn_vector` mapping matching the
   embedding dimension of each Model_Profile before loading vectors into them.
4. THE System SHALL preserve tenant-prefixed index families and label families during
   AWS_Reimport for every tenant present in the Portable_Export.
5. IF a target OpenSearch index already exists with an incompatible field mapping, THEN THE
   System SHALL report the conflict and SHALL NOT write vectors into that index.

### Requirement 4: Embedding-model fidelity

**User Story:** As an Operator, I want every exported vector to carry its embedding model
identity, so that a restored knowledge base produces meaningful similarity search instead
of noise.

#### Acceptance Criteria

1. THE System SHALL record the Model_Profile of every document in its Vector_Export record.
2. THE System SHALL record, in the Export_Manifest, the set of Model_Profiles present and
   the embedding dimension associated with each Model_Profile.
3. WHEN COTS_Restore or AWS_Reimport runs, THE System SHALL verify that the restore target
   has access to a Query_Embedder matching each restored Model_Profile.
4. IF a restore target lacks a Query_Embedder matching a restored Model_Profile, THEN THE
   System SHALL mark that restore as Query_Incompatible in its completion report.
5. WHERE a restore target is marked Query_Incompatible, THE System SHALL complete the data
   load and SHALL report which Model_Profiles cannot be queried at the target.

### Requirement 5: No re-embedding invariant

**User Story:** As an Operator, I want vectors carried bitwise through every transfer, so
that round-trip parity is never broken by recomputed embeddings.

#### Acceptance Criteria

1. THE System SHALL carry every embedding vector bitwise unchanged through AWS_Export,
   COTS_Restore, and AWS_Reimport.
2. THE System SHALL NOT recompute, re-embed, normalize, or quantize any embedding vector
   during any transfer direction.
3. WHEN AWS_Export reads a vector and AWS_Reimport writes it back, THE System SHALL produce
   a stored vector bitwise-identical to the source vector.

### Requirement 6: Bidirectional round-trip fidelity

**User Story:** As an Operator, I want an export followed by a re-import to reproduce the
source exactly, so that I can trust the round trip before relying on it for funding
resilience.

#### Acceptance Criteria

1. WHEN an AWS_Export is followed by an AWS_Reimport of the same Portable_Export, THE System
   SHALL produce per-tenant Neptune node counts equal to the source per-tenant node counts.
2. WHEN an AWS_Export is followed by an AWS_Reimport of the same Portable_Export, THE System
   SHALL produce per-tenant Neptune relationship counts equal to the source per-tenant
   relationship counts.
3. WHEN an AWS_Export is followed by an AWS_Reimport of the same Portable_Export, THE System
   SHALL produce per-index OpenSearch document counts equal to the source per-index document
   counts.
4. WHEN an AWS_Export is followed by an AWS_Reimport of the same Portable_Export, THE System
   SHALL produce stored embeddings bitwise-identical to the source embeddings.
5. WHEN an AWS_Export is followed by a COTS_Restore, THE System SHALL produce per-collection
   and per-tenant counts in ChromaDB and Neo4j equal to the source counts.

### Requirement 7: Completeness across all tenants

**User Story:** As an Operator, I want every tenant in the Tenant_Catalog exported, so that
no branch of the knowledge base is left behind.

#### Acceptance Criteria

1. WHEN a full AWS_Export runs, THE System SHALL enumerate every tenant defined in the
   Tenant_Catalog and SHALL export each tenant's Index_Family and label family.
2. THE System SHALL export the default `gw` baseline using its unprefixed indices and
   unprefixed labels.
3. THE System SHALL export each non-default tenant using its index prefix and label prefix.
4. THE System SHALL record, in the Export_Manifest, the list of tenants included in the
   Portable_Export.
5. IF a tenant defined in the Tenant_Catalog has no data in a store, THEN THE System SHALL
   record a zero count for that tenant and store in the Export_Manifest and SHALL continue.

### Requirement 8: Dedupe registry handling

**User Story:** As an Operator, I want the dedupe registry preserved across the round trip,
so that re-ingestion dedupe still works after AWS_Reimport.

#### Acceptance Criteria

1. WHEN a full AWS_Export runs, THE System SHALL either export the Dedupe_Registry as a
   Dedupe_Registry_Export or record in the Export_Manifest that the registry will be
   deterministically rebuilt on AWS_Reimport.
2. WHERE the Dedupe_Registry is exported, THE System SHALL preserve its `(collection, sha)`
   composite keys per tenant.
3. WHEN AWS_Reimport completes, THE System SHALL produce a Dedupe_Registry whose
   `(collection, sha)` entries match the content present in the re-imported stores.
4. WHEN AWS_Reimport reconstructs the Dedupe_Registry from re-imported content, THE System
   SHALL produce the same registry entries regardless of how many times the reconstruction
   runs.

### Requirement 9: Idempotent, resumable, watermarked transfers

**User Story:** As an Operator, I want a failed transfer to resume from the last completed
batch, so that large exports and imports survive interruptions without duplicating work.

#### Acceptance Criteria

1. WHEN a transfer phase completes a batch, THE System SHALL persist a Watermark in S3
   recording the completed phase, collection, Model_Profile, and tenant unit.
2. WHEN a transfer is re-run after an interruption, THE System SHALL resume from the last
   recorded Watermark and SHALL skip units already marked complete.
3. WHEN a transfer phase that is already fully complete is re-run, THE System SHALL perform
   no writes for that phase.
4. THE System SHALL apply idempotent and resumable behavior to AWS_Export, COTS_Restore,
   and AWS_Reimport.

### Requirement 10: Count-parity verification at each hop

**User Story:** As an Operator, I want a verification step after each transfer, so that a
mismatch is detected before the data is trusted.

#### Acceptance Criteria

1. WHEN a Count_Parity_Check runs, THE System SHALL compare source and destination counts
   per collection, per Model_Profile, and per tenant.
2. IF any compared count differs between source and destination, THEN THE System SHALL
   report the mismatch and SHALL exit with a non-zero status.
3. WHEN all compared counts match, THE System SHALL report success and SHALL exit with a
   zero status.
4. THE System SHALL run a Count_Parity_Check after AWS_Export, after COTS_Restore, and after
   AWS_Reimport.
5. THE System SHALL write the parity report to S3 with a timestamp.

### Requirement 11: Manifest and provenance

**User Story:** As an Operator, I want every export to carry a manifest, so that a restore
can validate compatibility before it starts.

#### Acceptance Criteria

1. WHEN AWS_Export completes, THE System SHALL write an Export_Manifest recording source
   endpoints, timestamp, per-collection counts, per-tenant counts, Model_Profiles,
   embedding dimensions, tenant list, schema version, and tool version.
2. WHEN COTS_Restore or AWS_Reimport starts, THE System SHALL read the Export_Manifest and
   SHALL validate schema version and Model_Profile compatibility before writing data.
3. IF the Export_Manifest schema version is incompatible with the restore tool, THEN THE
   System SHALL report the incompatibility and SHALL NOT write data.
4. THE System SHALL record per-object checksums in the Export_Manifest.

### Requirement 12: Portability packaging and offline restore

**User Story:** As an Operator, I want the export downloadable as a single self-contained
bundle, so that I can move it to a disconnected COTS host and restore offline.

#### Acceptance Criteria

1. WHERE the Operator requests a bundled artifact, THE System SHALL package the complete
   Portable_Export and its Export_Manifest into a single gzipped Export_Bundle.
2. THE System SHALL support restoring from an Export_Bundle on a host with no connection to
   AWS.
3. THE System SHALL support a Portable_Export in an S3-native layout in addition to the
   single Export_Bundle artifact.
4. WHEN COTS_Restore reads an Export_Bundle, THE System SHALL restore the same data that the
   equivalent S3-native layout would restore.

### Requirement 13: Compression and integrity

**User Story:** As an Operator, I want exports compressed and checksummed, so that a
corrupted transfer is detected before a restore consumes it.

#### Acceptance Criteria

1. THE System SHALL write Vector_Export and Graph_Export artifacts in gzipped form.
2. THE System SHALL compute a checksum for each export object and SHALL record it in the
   Export_Manifest.
3. WHEN COTS_Restore or AWS_Reimport reads an export object, THE System SHALL verify the
   object checksum against the Export_Manifest before consuming the object.
4. IF an object checksum does not match the Export_Manifest, THEN THE System SHALL report
   the corrupted object and SHALL NOT restore from that object.

### Requirement 14: Selective export

**User Story:** As an Operator, I want to export a single tenant, collection, or store, so
that partial backups and targeted restores are possible.

#### Acceptance Criteria

1. WHERE the Operator specifies a single tenant, THE System SHALL export only that tenant's
   Index_Family and label family.
2. WHERE the Operator specifies a single collection, THE System SHALL export only that
   collection.
3. WHERE the Operator specifies vectors-only, THE System SHALL export only the Vector_Export
   and SHALL omit the Graph_Export.
4. WHERE the Operator specifies graph-only, THE System SHALL export only the Graph_Export and
   SHALL omit the Vector_Export.
5. WHEN a selective export completes, THE System SHALL record the selected scope in the
   Export_Manifest.

### Requirement 15: Operator gating on destructive re-import and ASCII-only tooling

**User Story:** As an Operator, I want destructive restores to require explicit
confirmation, so that I do not overwrite a live store by accident.

#### Acceptance Criteria

1. IF COTS_Restore or AWS_Reimport would write into a store that already contains data,
   THEN THE System SHALL require explicit Operator confirmation before writing.
2. WHILE running without Operator confirmation for a destructive write, THE System SHALL
   report the pending action and SHALL NOT modify the target store.
3. THE System SHALL emit ASCII-only console output using markers such as `[OK]`, `[ERROR]`,
   and `[WARN]`.
4. THE System SHALL place its tooling under the provisioning directory consistent with the
   other provisioning tooling.
5. WHEN a transfer modifies a store, THE System SHALL record the change in the change log
   and SHALL NOT auto-commit the change.
