#!/usr/bin/env python3
"""One-off: load gw_v17 graph RELATIONSHIPS from the S3 portable-export into
local Neo4j.

Context (Phase 60): the v17 tenant nodes are fully present locally (90,899,
matching the export), but ZERO relationships touch any ``GW_V17_*`` node. The
original ``reingest_s3_to_local.py`` marked all 19 v17 rel files complete in
the watermark, yet produced no edges — the rels were loaded before the v17
nodes existed, so every ``MATCH (from)/(to)`` missed and ``MERGE`` was skipped.

This script re-loads ONLY the 19 v17 rel parts now that the nodes exist,
bypassing the watermark. Idempotent (``MERGE`` on relationship ``id``). Node
endpoints are matched by ``id`` (the Neptune ``~id``) using per-label id
indexes created up front for speed. Rows in each part are bucketed by
``(from_label, to_label, rel_type)`` so a single UNWIND statement can use
fixed labels and hit the indexes.

Usage:
    source /mcp_rag_eib/spack/share/spack/setup-env.sh
    module load python/3.11.14 py-pip py-neo4j py-httpx py-pydantic
    python mcp_server_python/scripts/load_v17_rels_local.py
"""
from __future__ import annotations

import csv
import gzip
import json
import logging
import os
import sys
from collections import defaultdict
from typing import Any

import boto3
from neo4j import GraphDatabase

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("v17rels")

CREDS = os.environ.get(
    "S3_AUTH_FILE", "/mcp_rag_eib/SCRATCH_SPACE/Terry.McGuinness/aws_s3_auth_omdmcpdata.txt"
)
MANIFEST_KEY = "portable-export/dev/20260616-174650-df73fe6a/manifest.json"
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "gfsworkflow2025")
BATCH = 1000


def load_creds(fp: str) -> dict[str, str]:
    c: dict[str, str] = {}
    for line in open(fp, encoding="utf-8"):
        line = line.strip()
        if line.startswith("set "):
            k, _, v = line[4:].partition("=")
            c[k.strip()] = v.strip()
    return c


def parse_node_identity(cell: str) -> tuple[str, str]:
    if ":" not in cell:
        return "Node", cell
    a, b = cell.split(":", 1)
    return a, b


def parse_props(row: dict[str, str]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for k, v in row.items():
        if k in ("~id", "~from", "~to", "~label") or v in ("", None):
            continue
        if len(v) > 8000:
            v = v[:8000] + "... [TRUNCATED]"
        if v.startswith("["):
            try:
                props[k] = json.loads(v)
                continue
            except json.JSONDecodeError:
                pass
        try:
            props[k] = int(v)
            continue
        except ValueError:
            pass
        try:
            props[k] = float(v)
            continue
        except ValueError:
            pass
        props[k] = v
    return props


def _v17_count(session: Any) -> int:
    return session.run(
        "MATCH (n)-[r]->() WHERE any(l IN labels(n) WHERE l STARTS WITH 'GW_V17_') "
        "RETURN count(r)"
    ).single()[0]


def main() -> int:
    creds = load_creds(CREDS)
    bucket = creds.get("BUCKET_URI", "s3://omdmcpdata").replace("s3://", "")
    s3 = boto3.client(
        "s3",
        aws_access_key_id=creds.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=creds.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=creds.get("AWS_SESSION_TOKEN"),
        region_name=creds.get("AWS_REGION", "us-east-1"),
    )

    man = json.loads(s3.get_object(Bucket=bucket, Key=MANIFEST_KEY)["Body"].read())
    v17 = next(e for e in man["graph_exports"] if e["tenant_id"] == "gw_v17")
    rel_parts = v17["rel_parts"]
    log.info(
        "[OK] manifest: gw_v17 has %d rel parts (%d rels expected)",
        len(rel_parts),
        v17.get("relationship_count"),
    )

    drv = GraphDatabase.driver(NEO4J_URI, auth=("neo4j", NEO4J_PASSWORD))

    v17_labels = [
        "GW_V17_FortranSubroutine", "GW_V17_File", "GW_V17_FortranFunction",
        "GW_V17_EnvironmentVariable", "GW_V17_FortranModule", "GW_V17_ShellScript",
        "GW_V17_EXPDIRConfig", "GW_V17_FortranProgram", "GW_V17_RocotoTask",
        "GW_V17_ShellFunction", "GW_V17_ConfigFile", "GW_V17_DataDependency",
        "GW_V17_JJob", "GW_V17_RocotoMetatask", "GW_V17_RocotoCycledef",
        "GW_V17_Experiment",
    ]
    with drv.session() as s:
        for lab in v17_labels:
            s.run(f"CREATE INDEX IF NOT EXISTS FOR (n:`{lab}`) ON (n.id)")
        s.run("CALL db.awaitIndexes(300)")
        before = _v17_count(s)
        # Build id -> GW_V17_ label map. The export's rel ~from/~to are bare
        # node ids (no "Label:" prefix), so we resolve each endpoint's label
        # from the already-loaded nodes to MATCH with the right (indexed) label.
        id_label: dict[str, str] = {}
        for rec in s.run(
            "MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'GW_V17_') "
            "RETURN n.id AS id, [l IN labels(n) WHERE l STARTS WITH 'GW_V17_'][0] AS label"
        ):
            id_label[rec["id"]] = rec["label"]
    log.info("[OK] id indexes ensured for %d v17 labels", len(v17_labels))
    log.info("[OK] id->label map built: %d v17 nodes", len(id_label))
    log.info("v17 rels BEFORE: %d", before)

    total = 0
    skipped = 0
    for i, key in enumerate(rel_parts, 1):
        local = "/tmp/v17_rel.csv.gz"
        s3.download_file(bucket, key, local)
        buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        with gzip.open(local, "rt", encoding="utf-8") as gf:
            for row in csv.DictReader(gf):
                rid, frm, to = row.get("~id"), row.get("~from", ""), row.get("~to", "")
                if not rid or not frm or not to:
                    continue
                # ~from/~to are bare ids; resolve label from the node map.
                _, fid = parse_node_identity(frm)
                _, tid = parse_node_identity(to)
                fl = id_label.get(fid)
                tl = id_label.get(tid)
                if fl is None or tl is None:
                    skipped += 1
                    continue
                rl = row.get("~label", "REL")
                buckets[(fl, tl, rl)].append(
                    {"id": rid, "from_id": fid, "to_id": tid, "properties": parse_props(row)}
                )
        part = 0
        with drv.session() as s:
            for (fl, tl, rl), rows in buckets.items():
                cy = (
                    "UNWIND $batch AS row "
                    f"MATCH (a:`{fl}` {{id: row.from_id}}) "
                    f"MATCH (b:`{tl}` {{id: row.to_id}}) "
                    f"MERGE (a)-[r:`{rl}` {{id: row.id}}]->(b) "
                    "SET r += row.properties"
                )
                for j in range(0, len(rows), BATCH):
                    s.run(cy, {"batch": rows[j:j + BATCH]})
                part += len(rows)
        total += part
        log.info("[%2d/%d] %-28s -> %7d rels", i, len(rel_parts), key.split("/")[-1], part)
        os.remove(local)

    with drv.session() as s:
        after = _v17_count(s)
    log.info("v17 rels AFTER: %d (processed %d rows, skipped %d unmatched)", after, total, skipped)
    drv.close()
    if after > before:
        log.info("[OK] FLIP achieved: v17 nodes now have relationships.")
        return 0
    log.error("[ERROR] No new v17 relationships created — investigate id matching.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
