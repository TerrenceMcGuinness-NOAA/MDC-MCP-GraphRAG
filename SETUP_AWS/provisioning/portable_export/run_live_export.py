#!/usr/bin/env python3.12
"""Live AWS_Export runner — operator-gated Wave 8.

Wires real OpenSearch (scroll/scan via SigV4) and Neptune (openCypher via
SigV4) readers to the export phases, writing the Portable_Export to S3
(SSE-S3 default encryption). Produces a manifest + optional bundle.

Usage:
    OPENSEARCH_ENDPOINT=https://... \
    NEPTUNE_ENDPOINT=https://... \
    PORTABLE_EXPORT_BUCKET=mdc-mcp-rag-snapshots-903050880929 \
    AWS_REGION=us-east-1 \
    python3.12 -m portable_export.run_live_export \
        --tenants gw,gw_v17 [--bundle] [--prefix <s3-key-prefix>]

Env vars:
    OPENSEARCH_ENDPOINT — full https URL to the VPC OpenSearch domain
    NEPTUNE_ENDPOINT    — full https URL (with port) to Neptune cluster
    PORTABLE_EXPORT_BUCKET — S3 bucket name (default: mdc-mcp-rag-snapshots-903050880929)
    AWS_REGION          — AWS region (default: us-east-1)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import boto3
from requests_aws4auth import AWS4Auth
from opensearchpy import OpenSearch, RequestsHttpConnection

# ── Add parent to path so portable_export is importable ────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portable_export.adapters.opensearch_reader import OpenSearchReader
from portable_export.adapters.neptune_reader import NeptuneReader
from portable_export.config import load_tenant_catalog
from portable_export.kms_writer import KmsWriter, compute_sha256
from portable_export.manifest import ExportManifest, VectorExportEntry, GraphExportEntry
from portable_export.phases.export_vectors import export_vectors
from portable_export.phases.export_graph import export_graph
from portable_export.phases.export_dedupe import export_dedupe
from portable_export.bundle import pack_objects
from portable_export.watermarks import Watermarks


def _build_opensearch_client(endpoint: str, region: str):
    """Build a SigV4-authed opensearch-py client."""
    session = boto3.Session(region_name=region)
    creds = session.get_credentials().get_frozen_credentials()
    auth = AWS4Auth(creds.access_key, creds.secret_key, region, "es",
                    session_token=creds.token)
    # Strip protocol for the host param
    host = endpoint.replace("https://", "").replace("http://", "")
    client = OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
    )
    return client


def _build_neptune_query_fn(endpoint: str, region: str):
    """Build a SigV4-authed Neptune openCypher query function.

    Uses the same botocore SigV4Auth approach as the production adapter in
    mcp_server_python/src/data/aws_backend.py.
    """
    import json
    import urllib.parse
    import urllib3
    import botocore.auth
    import botocore.awsrequest

    # Normalize endpoint
    base = endpoint.rstrip("/")
    if not base.endswith("/opencypher"):
        base = f"{base}/opencypher"

    pool = urllib3.PoolManager()

    def query_fn(cypher: str, params: Optional[dict] = None) -> list[dict]:
        body_parts = {"query": cypher}
        if params:
            body_parts["parameters"] = json.dumps(params)
        body = urllib.parse.urlencode(body_parts)

        creds = boto3.Session(region_name=region).get_credentials().get_frozen_credentials()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        aws_request = botocore.awsrequest.AWSRequest(
            method="POST", url=base, data=body, headers=headers,
        )
        botocore.auth.SigV4Auth(creds, "neptune-db", region).add_auth(aws_request)

        response = pool.request(
            "POST", base, body=body, headers=dict(aws_request.headers), timeout=300,
        )
        if response.status >= 400:
            raise RuntimeError(
                f"Neptune HTTP {response.status}: {response.data[:500].decode('utf-8', errors='replace')}"
            )
        data = json.loads(response.data)
        return data.get("results", [])

    return query_fn


class OsClientShim:
    """Thin shim wrapping opensearch-py to match OpenSearchReader's expected interface."""

    def __init__(self, client):
        self._c = client

    def list_indices(self) -> list[str]:
        indices = self._c.cat.indices(format="json")
        return [i["index"] for i in indices if not i["index"].startswith(".")]

    def count(self, index: str) -> dict:
        return self._c.count(index=index)

    def search(self, index: str, scroll: str, size: int, body: dict) -> dict:
        return self._c.search(index=index, scroll=scroll, size=size, body=body)

    def scroll(self, scroll_id: str, scroll: str) -> dict:
        return self._c.scroll(scroll_id=scroll_id, scroll=scroll)

    def clear_scroll(self, scroll_id: str) -> dict:
        return self._c.clear_scroll(scroll_id=scroll_id)


def main():
    parser = argparse.ArgumentParser(description="Live AWS_Export")
    parser.add_argument("--tenants", default="gw,gw_v17")
    parser.add_argument("--bundle", action="store_true")
    parser.add_argument("--prefix", default=None)
    args = parser.parse_args()

    # Resolve config from environment
    region = os.environ.get("AWS_REGION", "us-east-1")
    os_endpoint = os.environ.get("OPENSEARCH_ENDPOINT")
    nep_endpoint = os.environ.get("NEPTUNE_ENDPOINT")
    bucket = os.environ.get("PORTABLE_EXPORT_BUCKET", "mdc-mcp-rag-snapshots-903050880929")

    if not os_endpoint:
        print("[ERROR] OPENSEARCH_ENDPOINT env var required", file=sys.stderr)
        return 1
    if not nep_endpoint:
        print("[ERROR] NEPTUNE_ENDPOINT env var required", file=sys.stderr)
        return 1

    tenants = [t.strip() for t in args.tenants.split(",") if t.strip()]
    op_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    prefix = args.prefix or f"portable-export/dev/{op_id}"

    print(f"[INFO] AWS_Export starting")
    print(f"[INFO]   operation_id: {op_id}")
    print(f"[INFO]   bucket: {bucket}")
    print(f"[INFO]   prefix: {prefix}")
    print(f"[INFO]   tenants: {tenants}")
    print(f"[INFO]   bundle: {args.bundle}")
    print(f"[INFO]   opensearch: {os_endpoint}")
    print(f"[INFO]   neptune: {nep_endpoint}")
    print()

    # Load tenant catalog
    catalog = load_tenant_catalog()
    index_prefixes = {t.tenant_id: t.index_prefix for t in catalog.tenants}
    label_prefixes = {t.tenant_id: t.label_prefix for t in catalog.tenants}

    # Build adapters
    print("[INFO] Connecting to OpenSearch...")
    os_raw_client = _build_opensearch_client(os_endpoint, region)
    os_shim = OsClientShim(os_raw_client)
    os_reader = OpenSearchReader(os_shim, index_prefixes=index_prefixes)

    print("[INFO] Connecting to Neptune...")
    neptune_qfn = _build_neptune_query_fn(nep_endpoint, region)
    nep_reader = NeptuneReader(neptune_qfn, label_prefixes=label_prefixes)

    # Build KMS writer (S3) — guard_encryption=False because bucket uses SSE-S3
    s3_client = boto3.client("s3", region_name=region)
    kms_writer = KmsWriter(s3_client, bucket=bucket, kms_key_arn=None,
                           guard_encryption=False)

    # Manifest + watermarks
    manifest = ExportManifest(
        manifest_id=op_id,
        produced_at=datetime.now(timezone.utc).isoformat(),
        source_endpoints={"opensearch": os_endpoint, "neptune": nep_endpoint},
        tenants=tenants,
    )
    watermarks = None  # No resume on first run

    # ── Phase 1: Export vectors ────────────────────────────────────────
    print("[INFO] Phase 1/3: Exporting vectors...")
    t0 = time.time()

    # Enumerate index families per tenant
    units = []
    for tenant in tenants:
        indices = os_reader.index_family_for_tenant(tenant)
        print(f"[INFO]   tenant={tenant}: {len(indices)} indices")
        for idx in indices:
            # Skip the dedupe registry (not a vector index)
            if "sha-registry" in idx:
                continue
            from portable_export.config import infer_model_profile
            mp = infer_model_profile(idx)
            units.append((tenant, idx, mp))

    entries = export_vectors(
        os_reader, kms_writer, watermarks, manifest,
        prefix=prefix, units=units, batch=500, part_max_records=5000,
    )
    vec_elapsed = time.time() - t0
    total_vec = sum(e.record_count for e in entries)
    print(f"[OK]  Vectors exported: {total_vec} records in {vec_elapsed:.1f}s")
    print()

    # ── Phase 2: Export graph ──────────────────────────────────────────
    print("[INFO] Phase 2/3: Exporting graph...")
    t1 = time.time()
    graph_entries = export_graph(
        nep_reader, kms_writer, watermarks, manifest,
        prefix=prefix, tenants=tenants,
    )
    graph_elapsed = time.time() - t1
    total_nodes = sum(e.node_count for e in graph_entries)
    total_rels = sum(e.relationship_count for e in graph_entries)
    print(f"[OK]  Graph exported: {total_nodes} nodes, {total_rels} rels in {graph_elapsed:.1f}s")
    print()

    # ── Phase 3: Export dedupe registry ────────────────────────────────
    print("[INFO] Phase 3/3: Exporting dedupe registry...")
    t2 = time.time()
    # The dedupe registry lives in the 'mdc-content-sha-registry' index.
    # Read it via scroll and convert to DedupeRow objects.
    from portable_export.adapters import DedupeRow
    dedupe_rows = []
    registry_index = "mdc-content-sha-registry"
    try:
        for batch in os_reader.scroll_records(registry_index, 1000):
            for rec in batch:
                meta = rec.get("metadata", {})
                dedupe_rows.append(DedupeRow(
                    tenant_id=meta.get("tenant_id", "gw"),
                    collection=meta.get("collection", rec.get("collection_name", "")),
                    sha=meta.get("sha", rec.get("id", "")),
                ))
    except Exception as e:
        print(f"[WARN] Could not read dedupe registry: {e}")
    dedupe_result = export_dedupe(
        dedupe_rows, kms_writer, watermarks, prefix=prefix,
    )
    manifest.dedupe_export = dedupe_result
    dedupe_elapsed = time.time() - t2
    print(f"[OK]  Dedupe exported: {dedupe_result.get('entry_count', 0)} entries in {dedupe_elapsed:.1f}s")
    print()

    # ── Finalize manifest ──────────────────────────────────────────────
    manifest_body = json.dumps(manifest.to_dict(), indent=2).encode("utf-8")
    manifest_key = f"{prefix}/manifest.json"
    kms_writer.put(manifest_key, manifest_body, content_type="application/json")
    print(f"[OK]  Manifest written: s3://{bucket}/{manifest_key}")

    # ── Optional bundle ────────────────────────────────────────────────
    if args.bundle:
        print("[INFO] Packing Export_Bundle from S3 objects...")
        t3 = time.time()
        # List all objects under the prefix, download them, pack into a tarball
        bundle_key = f"{prefix}.tar.gz"
        paginator = s3_client.get_paginator("list_objects_v2")
        objects: dict[str, bytes] = {}
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix + "/"):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                relative = key[len(prefix) + 1:]  # strip prefix/
                body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
                objects[relative] = body
        bundle_bytes = pack_objects(objects)
        s3_client.put_object(Bucket=bucket, Key=bundle_key, Body=bundle_bytes)
        bundle_size_mb = len(bundle_bytes) / (1024 * 1024)
        bundle_elapsed = time.time() - t3
        print(f"[OK]  Bundle written: s3://{bucket}/{bundle_key} ({bundle_size_mb:.1f} MB, {bundle_elapsed:.1f}s)")

    # ── Summary ────────────────────────────────────────────────────────
    total_elapsed = time.time() - t0
    print()
    print("=" * 60)
    print(f"[OK]  AWS_Export complete in {total_elapsed:.1f}s")
    print(f"       vectors: {total_vec} records")
    print(f"       graph:   {total_nodes} nodes, {total_rels} rels")
    print(f"       prefix:  s3://{bucket}/{prefix}/")
    if args.bundle:
        print(f"       bundle:  s3://{bucket}/{prefix}.tar.gz")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
