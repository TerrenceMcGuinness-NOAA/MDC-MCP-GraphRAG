# Runbook -- Cross_Platform_Data_Persistence_System (portable export)

Operator runbook for the `Cross_Platform_Data_Persistence_System`, the
**outbound** pipeline that exports the entire MDC MCP-RAG Knowledge_Base
(OpenSearch vectors + Neptune property graph, across all tenants) to an
engine-neutral `Portable_Export` in S3, and restores it either into the
original open-source COTS stack (ChromaDB + Neo4j) or back into AWS
(OpenSearch + Neptune). Spec: `.kiro/specs/cross-platform-data-persistence/`.

All tooling lives under `SETUP_AWS/provisioning/portable_export/`. It is the
outbound mirror of the inbound `migrate-to-aws.js` pipeline and complements,
but does not replace, the separate `nih-sandbox-cost-control` sleep/wake
feature (which owns the AWS-only fast-path `Native_Snapshot`).

> Modeled on `SETUP_AWS/provisioning/RUNBOOK_cost_control.md` and
> `RUNBOOK_agentcore_creds.md`.

## Two persistence modes

- **Native_Snapshot** (AWS -> S3 -> AWS only) -- engine-proprietary OpenSearch
  + Neptune snapshots. Fast and lossless, round-trips only to AWS. Owned by
  `nih-sandbox-cost-control`; referenced, not implemented, here.
- **Portable_Export** (engine-neutral, cross-platform) -- the new capability
  this runbook covers. Readable by BOTH the COTS stack and AWS.

## Three transfer directions

| Direction | Reads | Writes | CLI verb |
|-----------|-------|--------|----------|
| `AWS_Export`   | OpenSearch + Neptune (read-only) | S3 Portable_Export | `export` |
| `COTS_Restore` | S3 Portable_Export | ChromaDB + Neo4j | `restore` |
| `AWS_Reimport` | S3 Portable_Export | OpenSearch + Neptune | `reimport` |

## Prerequisites

- Python 3.12 with `boto3` and `PyYAML`. Run from `SETUP_AWS/provisioning/`.
- The operator (or CI role) can read OpenSearch + Neptune (export) and/or write
  the destination store (restore / reimport).
- Environment variables (resolved by `portable_export/config.py`):
  - `AWS_REGION` (default `us-east-1`)
  - `PORTABLE_EXPORT_BUCKET` (default `mdc-mcp-rag-snapshots-903050880929`)
  - `OPENSEARCH_ENDPOINT`, `NEPTUNE_ENDPOINT` (export / reimport sources/targets)
  - `PORTABLE_EXPORT_KMS_KEY_ARN` (optional; SSE-KMS for staged objects)
  - `valid_environments` allow-list: `dev`, `staging`, `prod`.

## S3 Portable_Export layout (the contract)

```
<prefix>/                                  # e.g. portable-export/dev/<manifest_id>/
  manifest.json                            # Export_Manifest (schema + counts + SHA-256)
  lock.json                                # S3 If-Match operation lock
  watermarks.json                          # idempotent-resume progress
  vectors/<tenant>/<collection>/NNN.jsonl.gz   # Vector_Export parts
  graph/<tenant>/nodes/<Label>-NNN.csv.gz      # Graph_Export node parts
  graph/<tenant>/rels/<Type>-NNN.csv.gz        # Graph_Export relationship parts
  dedupe/<tenant>/NNN.jsonl.gz             # Dedupe_Registry_Export
  parity/parity-<ts>.json                  # Count_Parity_Check reports
  audit/<operation_id>.jsonl               # per-operation audit trail
```

The default `gw` tenant uses unprefixed indices / labels; non-default tenants
use their `index_prefix` (`gw_v17_`) and `label_prefix` (`GW_V17_`), preserved
verbatim through every direction.

## Commands

All commands run from `SETUP_AWS/provisioning/`:

```bash
python3.12 -m portable_export.portable_export_cli export   --env dev [...]
python3.12 -m portable_export.portable_export_cli restore  --artefact <s3-or-bundle> --target cots [...]
python3.12 -m portable_export.portable_export_cli reimport --artefact s3://... --env <name> [...]
python3.12 -m portable_export.portable_export_cli verify   --artefact <s3-or-bundle> [--target {aws|cots}]
python3.12 -m portable_export.portable_export_cli status   --artefact <s3-or-bundle>
```

### Dry run first (mandatory on a new environment)

```bash
python3.12 -m portable_export.portable_export_cli export --env dev --tenants gw --dry-run
```

Prints the full plan -- direction, source/target adapters, selected scope,
tenants, collections -- with **zero mutation**. The first invocation in any
environment must be `--dry-run`.

### export (AWS_Export -> S3 Portable_Export)

```bash
python3.12 -m portable_export.portable_export_cli export \
  --env dev [--tenants gw,gw_v17] [--collections code,docs] \
  [--vectors-only | --graph-only] [--prefix s3://.../portable-export/dev/<id>/] \
  [--bundle] [--resume]
```

Read-only against OpenSearch + Neptune. Scrolls each targeted index into
gzipped JSONL Vector_Export parts and streams the graph into Neptune-loader
CSV parts, each written SSE-KMS with a per-part SHA-256 recorded in the
manifest. `--bundle` additionally produces a single `<prefix>.tar.gz`
Export_Bundle for offline transfer. Selective flags (`--tenants`,
`--collections`, `--vectors-only`, `--graph-only`) scope the export (R14);
`--vectors-only` and `--graph-only` are mutually exclusive.

### restore (COTS_Restore -> ChromaDB + Neo4j)

```bash
python3.12 -m portable_export.portable_export_cli restore \
  --artefact s3://.../portable-export/dev/<id>/  --target cots \
  [--chromadb-url URL] [--neo4j-uri URI] [--has-bedrock] \
  [--tenants ...] [--collections ...] [--yes] [--break-lock] [--resume]
```

Reads + validates the manifest (refusing an unsupported schema MAJOR), runs the
Query_Embedder check, probes the target, and -- after confirmation -- loads
each part (SHA-256 verified before consuming) into ChromaDB
(`collection.add`, embeddings bitwise) and Neo4j (`neo4j-admin import` /
transactional). Restoring from a downloaded Export_Bundle on a
network-disconnected host restores byte-equivalent data to the S3-native
layout.

### reimport (AWS_Reimport -> OpenSearch + Neptune)

```bash
python3.12 -m portable_export.portable_export_cli reimport \
  --artefact s3://.../portable-export/dev/<id>/  --env dev-reimport \
  [--tenants ...] [--collections ...] [--yes] [--resume]
```

Ensures each target OpenSearch index exists with a `knn_vector` mapping
matching the Model_Profile dimension (refusing an existing incompatible
mapping), bulk-indexes the records with embeddings written verbatim, loads the
graph with the Neptune bulk loader pointed at `<prefix>/graph/<tenant>/`, and
deterministically rebuilds the Dedupe_Registry from the re-imported content.

### verify (Count_Parity_Check)

```bash
python3.12 -m portable_export.portable_export_cli verify \
  --artefact s3://.../<id>/ --target aws --env dev-reimport [--tolerance 0.0]
```

Compares source counts (from the manifest) against live destination counts per
collection, per Model_Profile, and per tenant; exits non-zero on any mismatch
and writes a timestamped parity report under `<prefix>/parity/`.

### status (read-only, never locks)

```bash
python3.12 -m portable_export.portable_export_cli status --artefact s3://.../<id>/
```

Reads the manifest + watermarks + lock and reports progress **without
acquiring the lock** and without mutating anything.

## Confirmation gate (destructive restores)

`restore` and `reimport` write to a destination store. When the target is
**non-empty**, the CLI requires an exact confirmation phrase before any write
(R15.1, R15.2):

- `reimport`: type the destination environment name (e.g. `dev-reimport`).
- `restore`:  type `restore-cots`.

`--yes` substitutes a recorded confirmation token for the interactive prompt
(CI use only) and is logged in the audit trail. No write API call against any
destination resource is issued before the confirmation completes -- enforced in
one place (`direction_dispatcher.execute_restore`) and asserted by Property 7.

## Query_Embedder availability matrix (R4.3-R4.5)

A restore always **loads** every Model_Profile's vectors bitwise, but can only
serve meaningful similarity search where it has a matching Query_Embedder:

| Restore target | mpnet768 | titan1024 | nova{256,512,1024,3072} |
|----------------|----------|-----------|--------------------------|
| AWS (`AWS_Reimport`)        | yes | yes | yes |
| COTS with Bedrock IAM       | yes | yes | yes |
| COTS without Bedrock        | yes | **Query_Incompatible** | **Query_Incompatible** |

`mpnet768` is locally embeddable everywhere; `titan1024` / `nova*` need Bedrock
at query time. A `Query_Incompatible` profile is **loaded anyway** and flagged
in the completion report (pass `--has-bedrock` on a COTS host with Bedrock IAM).

## Dedupe export-vs-rebuild policy (R8)

The Dedupe_Registry (`mdc-content-sha-registry`, ~52K entries keyed by
`(collection, sha)` per tenant) is **exported by default** during `AWS_Export`
(cheap) and preserved verbatim. On `AWS_Reimport` the registry is
**deterministically rebuilt** from the re-imported content: each entry key is
`(tenant_id, collection_token, sha256(content))`, a pure function of content,
so the rebuild is idempotent across reruns (Property 9). Use the export when
round-tripping; rely on the rebuild when the source registry is suspect.

## Bundle / offline restore (R12)

Pass `--bundle` to `export` to produce a single `<prefix>.tar.gz` containing
`manifest.json` plus every Vector_Export / Graph_Export / Dedupe_Registry_Export
part in the same internal layout. Copy it to a disconnected COTS host and
`restore --artefact <bundle.tar.gz> --target cots`. A restore from the bundle
loads byte-equivalent data to the S3-native layout (R12.4). Full-corpus bundles
are ~2 GB compressed -- ensure the offline host has the disk headroom.

## Compression + integrity (R13)

All Vector_Export / Graph_Export parts are gzipped (`mtime=0`, so re-runs are
byte-identical). A per-part SHA-256 is computed during the write and recorded
in the manifest; every restore re-reads each part and verifies its SHA-256
against the manifest before consuming it, refusing a corrupted part and exiting
non-zero.

## Idempotent resume (R9)

Each completed unit `(phase, tenant, collection, model_profile, part)` is
recorded in `<prefix>/watermarks.json` via an atomic S3 If-Match swap. Re-run
with `--resume` to skip completed units and finish only the incomplete ones; a
fully-complete phase re-run performs no writes. A `--resume` against a watermark
written for a different `manifest_id` is refused (`Watermark_Mismatch`).

## Audit trail

Every step emits a one-line JSON `Audit_Log_Record` to the CloudWatch log group
`mdc-mcp-rag-portable-export-{env}` (when AWS-credentialed), to a per-operation
S3 object `<prefix>/audit/<operation_id>.jsonl`, and to a local fallback
`~/.mdc-mcp-rag/portable_export/<operation_id>.jsonl` (so an offline COTS
restore still records its trail). Console output is ASCII-only (`[OK]` /
`[ERROR]` / `[WARN]` / `[INFO]` / `[SKIP]`).

## Tests

```bash
cd SETUP_AWS/provisioning && python3.12 -m pytest portable_export/tests/ -q
```

149 tests (145 unit + 4 end-to-end integration). Integration tests use `moto`
for S3 and in-memory fixtures for the OpenSearch / Neptune / ChromaDB / Neo4j
data planes. No live AWS calls in any test.

## Phase A-D operator-gated live acceptance (run separately)

The live acceptance runs are operator-driven and **STOP-AND-CONFIRM gated**.
They are NOT exercised by the test suite; run them interactively against a live
environment when ready.

- **Phase A** -- `--dry-run` AWS_Export against the live `dev` env; golden-file
  the printed plan against `get_knowledge_base_status` for sanity.

  ```bash
  python3.12 -m portable_export.portable_export_cli export --env dev --tenants gw --dry-run
  ```

- **Phase B** -- real AWS_Export of the `gw` tenant only to a dedicated
  `s3://.../portable-export/dev/<id>/` prefix. Verify `manifest.totals` match
  `get_knowledge_base_status(tenant_id="gw")` and that per-part SHA-256s are
  reproducible by re-reading from S3 and recomputing. Record `manifest_id` +
  total bytes + wall-clock.

  ```bash
  python3.12 -m portable_export.portable_export_cli export --env dev --tenants gw
  ```

- **Phase C** -- AWS_Reimport from that artifact into a fresh `dev-reimport`
  destination; confirm the Count_Parity_Check passes and Property 3 holds live
  (post-reimport counts equal the manifest's preflight counts; embeddings
  bitwise-equal via SHA-256 round-trip).

  ```bash
  python3.12 -m portable_export.portable_export_cli reimport \
    --artefact s3://.../portable-export/dev/<id>/ --env dev-reimport
  python3.12 -m portable_export.portable_export_cli verify \
    --artefact s3://.../portable-export/dev/<id>/ --target aws --env dev-reimport
  ```

- **Phase D (optional)** -- COTS_Restore on a Docker host running ChromaDB +
  Neo4j community; confirm the Count_Parity_Check passes, Property 4 holds, and
  the Query_Compatible / Query_Incompatible flags are reported per
  Model_Profile.

  ```bash
  python3.12 -m portable_export.portable_export_cli restore \
    --artefact <bundle-or-s3> --target cots
  ```

A regression in Property 3 (counts + embeddings byte-equal) at Phase C is a
fix-the-code moment, never a weaken-the-test moment.

## No auto-commit

Per `08-git-operation-policy.md`, this tooling never auto-commits. Commits are
made only on explicit operator request.
