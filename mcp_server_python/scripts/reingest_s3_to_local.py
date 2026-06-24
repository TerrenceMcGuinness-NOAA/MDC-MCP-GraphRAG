#!/usr/bin/env python3
"""S3 Re-Ingestion script for Parallel Works local ChromaDB and Neo4j database restore.

Idempotently downloads pre-computed vectors and graph database files from S3 bucket
omdmcpdata and restores them to local databases.
"""

import os
import sys
import gzip
import csv
import json
import time
import logging
from typing import Any, Generator
import boto3
from chromadb import HttpClient
from neo4j import GraphDatabase

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("reingest")

WORKSPACE_ROOT = "/mcp_rag_eib/eib-mcp-rag-server"
AUTH_FILE = os.path.join(WORKSPACE_ROOT, "aws_s3_auth_omdmcpdata.txt")
WATERMARK_FILE = os.path.join(WORKSPACE_ROOT, "mcp_server_python/scripts/.ingest_watermark.json")


def load_s3_creds(file_path: str) -> dict[str, str]:
    """Parse local Parallel Works S3 credentials from text file."""
    if not os.path.exists(file_path):
        log.error("S3 Auth file not found at %s", file_path)
        sys.exit(1)
    
    creds = {}
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith("set "):
                continue
            parts = line[4:].split("=", 1)
            if len(parts) == 2:
                creds[parts[0].strip()] = parts[1].strip()
    return creds


def load_watermark() -> dict[str, Any]:
    """Load watermark file tracking completed ingest files."""
    if os.path.exists(WATERMARK_FILE):
        try:
            with open(WATERMARK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            log.warning("Failed to parse watermark file (%s), starting fresh.", exc)
    return {"completed_files": []}


def save_watermark(watermark: dict[str, Any], completed_file: str) -> None:
    """Save progress for resumption safety."""
    watermark["completed_files"].append(completed_file)
    try:
        os.makedirs(os.path.dirname(WATERMARK_FILE), exist_ok=True)
        with open(WATERMARK_FILE, "w", encoding="utf-8") as f:
            json.dump(watermark, f, indent=2)
    except Exception as exc:
        log.error("Failed to save watermark file: %s", exc)


def parse_node_identity(cell: str) -> tuple[str, str]:
    """Split Neptune-style Node Identity 'Label:ID' into (Label, ID)."""
    if ":" not in cell:
        return "Node", cell
    parts = cell.split(":", 1)
    return parts[0], parts[1]


def parse_csv_row_properties(row: dict[str, str]) -> dict[str, Any]:
    """Excludes ID/Label keys, parses strings/lists of properties for Neo4j."""
    properties = {}
    for k, v in row.items():
        if k in ("~id", "~from", "~to", "~label"):
            continue
        if v == "" or v is None:
            continue
        # Safeguard against Neo4j index size limits (max 8192 bytes for string indices)
        if len(v) > 8000:
            log.warning("[WARN] Truncating extremely large property '%s' of size %d to 8000 chars.", k, len(v))
            v = v[:8000] + "... [TRUNCATED]"
            
        # Try to parse list JSON properties (Neo4j supports arrays of primitives, but not maps/dicts)
        if v.startswith("["):
            try:
                properties[k] = json.loads(v)
                continue
            except json.JSONDecodeError:
                pass
        # Try integer
        try:
            properties[k] = int(v)
            continue
        except ValueError:
            pass
        # Try float
        try:
            properties[k] = float(v)
            continue
        except ValueError:
            pass
        
        properties[k] = v
    return properties


# ── Ingest Main ───────────────────────────────────────────────────────

def main() -> None:
    log.info("=== Starting S3 Database Re-Ingestion ===")
    
    # Load Credentials
    creds = load_s3_creds(AUTH_FILE)
    bucket_name = creds.get("BUCKET_URI", "s3://omdmcpdata").replace("s3://", "")
    
    # Initialize S3 Client
    s3 = boto3.client(
        "s3",
        aws_access_key_id=creds.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=creds.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=creds.get("AWS_SESSION_TOKEN"),
        region_name=creds.get("AWS_REGION", "us-east-1")
    )
    
    # Connect to local databases
    log.info("Connecting to local databases...")
    chroma = HttpClient(host="localhost", port=8080)
    
    # Test Neo4j connection eagerly
    neo4j_driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "gfsworkflow2025"))
    try:
        neo4j_driver.verify_connectivity()
        log.info("[OK] Local databases connected successfully")
    except Exception as exc:
        log.error("Failed to connect to local Neo4j database: %s", exc)
        sys.exit(1)
        
    watermark = load_watermark()
    
    # Fetch main manifest.json from S3
    manifest_key = "portable-export/dev/20260616-174650-df73fe6a/manifest.json"
    manifest_path = "/tmp/manifest.json"
    
    log.info("Downloading manifest: %s", manifest_key)
    s3.download_file(bucket_name, manifest_key, manifest_path)
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    # ── Part A: Vector Ingestion ──────────────────────────────────────
    log.info("\n=== Phase A: Restoring ChromaDB Vector Collections ===")
    
    for export in manifest.get("vector_exports", []):
        tenant_id = export.get("tenant_id")
        collection_name = export.get("collection_name")
        model_profile = export.get("model_profile")
        parts = export.get("parts", [])
        
        # We only restore the local mpnet768 pre-computed collections
        if model_profile != "mpnet768" or not parts:
            continue
            
        log.info("Processing Vector Collection: %s (Tenant: %s)", collection_name, tenant_id)
        
        # Verify collection counts
        try:
            coll = chroma.get_collection(collection_name)
            local_count = coll.count()
            if local_count >= export.get("record_count", 0) - 10:
                log.info("[OK] Collection %s is already fully loaded locally (%d docs). Skipping.", collection_name, local_count)
                continue
        except Exception:
            # Collection does not exist, get or create it
            coll = chroma.get_or_create_collection(collection_name)
            
        for part_key in parts:
            if part_key in watermark["completed_files"]:
                log.info("Part %s already ingested. Skipping.", part_key)
                continue
                
            local_part_path = "/tmp/part.jsonl.gz"
            log.info("Downloading vector chunk: %s", part_key)
            s3.download_file(bucket_name, part_key, local_part_path)
            
            # Read and ingest in batches of 500
            batch_ids = []
            batch_embeddings = []
            batch_metadatas = []
            batch_contents = []
            
            with gzip.open(local_part_path, "rt", encoding="utf-8") as gf:
                for line in gf:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    
                    batch_ids.append(record["id"])
                    batch_embeddings.append(record["embedding"])
                    batch_metadatas.append(record["metadata"] or {})
                    batch_contents.append(record["content"] or "")
                    
                    if len(batch_ids) >= 500:
                        coll.add(
                            ids=batch_ids,
                            embeddings=batch_embeddings,
                            metadatas=batch_metadatas,
                            documents=batch_contents
                        )
                        batch_ids, batch_embeddings, batch_metadatas, batch_contents = [], [], [], []
                        
                # Flush final batch
                if batch_ids:
                    coll.add(
                        ids=batch_ids,
                        embeddings=batch_embeddings,
                        metadatas=batch_metadatas,
                        documents=batch_contents
                    )
            
            # Purge local copy
            if os.path.exists(local_part_path):
                os.remove(local_part_path)
                
            save_watermark(watermark, part_key)
            log.info("[OK] Successfully loaded vector chunk: %s", part_key)

    # ── Part B: Graph Ingestion ────────────────────────────────────────
    log.info("\n=== Phase B: Restoring Neo4j Graph Database ===")
    
    for export in manifest.get("graph_exports", []):
        tenant_id = export.get("tenant_id")
        node_parts = export.get("node_parts", [])
        rel_parts = export.get("rel_parts", [])
        
        log.info("Processing Graph for Tenant: %s (%d nodes, %d relationships)", 
                 tenant_id, export.get("node_count"), export.get("relationship_count"))
        
        # 1. Load Nodes
        for node_file in node_parts:
            if node_file in watermark["completed_files"]:
                log.info("Nodes file %s already ingested. Skipping.", node_file)
                continue
                
            local_node_path = "/tmp/nodes.csv.gz"
            log.info("Downloading node chunk: %s", node_file)
            s3.download_file(bucket_name, node_file, local_node_path)
            
            # Read first row to determine label
            label = "Node"
            with gzip.open(local_node_path, "rt", encoding="utf-8") as gf:
                reader = csv.DictReader(gf)
                first_row = next(reader, None)
                if first_row:
                    label = first_row.get("~label", "Node")
            
            # Resolve unique property constraints to prevent ConstraintErrors
            merge_prop = "id"
            cypher = f"""
            UNWIND $batch AS row
            MERGE (n:`{label}` {{id: row.id_val}})
            SET n += row.properties
            SET n.id = row.raw_id
            """
            
            if label == "Community":
                cypher = f"""
                UNWIND $batch AS row
                MERGE (n:`{label}` {{communityId: row.properties.communityId, level: row.properties.level}})
                SET n += row.properties
                SET n.id = row.raw_id
                """
            elif label == "Commit":
                merge_prop = "hash"
            elif label == "EnvironmentVariable":
                merge_prop = "name"
            elif label == "Component":
                merge_prop = "path"
            elif label == "Developer":
                merge_prop = "email"
            elif label in ("File", "CodeFile", "ConfigFile", "GW_V17_ConfigFile", "GW_V17_File"):
                merge_prop = "path"
                
            if label != "Community" and merge_prop != "id":
                cypher = f"""
                UNWIND $batch AS row
                MERGE (n:`{label}` {{{merge_prop}: row.id_val}})
                SET n += row.properties
                SET n.id = row.raw_id
                """
                
            log.info("Loading nodes labeled :%s into local Neo4j (merging on '%s')...", label, "composite: communityId, level" if label == "Community" else merge_prop)
            
            # Batch loading nodes in blocks of 1,000 using unwind
            batch = []
            with gzip.open(local_node_path, "rt", encoding="utf-8") as gf:
                reader = csv.DictReader(gf)
                for row in reader:
                    node_id = row.get("~id")
                    if not node_id:
                        continue
                    properties = parse_csv_row_properties(row)
                    
                    # Extract the merge value from properties or fall back to ID
                    id_val = properties.get(merge_prop) or node_id
                    
                    batch.append({
                        "id_val": id_val, 
                        "properties": properties,
                        "raw_id": node_id
                    })
                    
                    if len(batch) >= 1000:
                        with neo4j_driver.session() as session:
                            session.run(cypher, {"batch": batch})
                        batch = []
                
                # Flush final batch
                if batch:
                    with neo4j_driver.session() as session:
                        session.run(cypher, {"batch": batch})
            
            if os.path.exists(local_node_path):
                os.remove(local_node_path)
                
            save_watermark(watermark, node_file)
            log.info("[OK] Staged nodes file: %s", node_file)
            
        # 2. Load Relationships
        for rel_file in rel_parts:
            if rel_file in watermark["completed_files"]:
                log.info("Relationships file %s already ingested. Skipping.", rel_file)
                continue
                
            local_rel_path = "/tmp/rels.csv.gz"
            log.info("Downloading relationship chunk: %s", rel_file)
            s3.download_file(bucket_name, rel_file, local_rel_path)
            
            # Resolve labels eagerly from first row
            rel_label = "REL"
            from_label = "Node"
            to_label = "Node"
            with gzip.open(local_rel_path, "rt", encoding="utf-8") as gf:
                reader = csv.DictReader(gf)
                first_row = next(reader, None)
                if first_row:
                    rel_label = first_row.get("~label", "REL")
                    from_label, _ = parse_node_identity(first_row.get("~from", ""))
                    to_label, _ = parse_node_identity(first_row.get("~to", ""))
            
            log.info("Loading relationship [:%s] (:%s) -> (:%s)...", rel_label, from_label, to_label)
            
            batch = []
            cypher = f"""
            UNWIND $batch AS row
            MATCH (from:`{from_label}` {{id: row.from_id}})
            MATCH (to:`{to_label}` {{id: row.to_id}})
            MERGE (from)-[r:`{rel_label}` {{id: row.id}}]->(to)
            SET r += row.properties
            """
            
            with gzip.open(local_rel_path, "rt", encoding="utf-8") as gf:
                reader = csv.DictReader(gf)
                for row in reader:
                    rel_id = row.get("~id")
                    from_raw = row.get("~from", "")
                    to_raw = row.get("~to", "")
                    if not rel_id or not from_raw or not to_raw:
                        continue
                    
                    _, from_id = parse_node_identity(from_raw)
                    _, to_id = parse_node_identity(to_raw)
                    properties = parse_csv_row_properties(row)
                    
                    batch.append({
                        "id": rel_id,
                        "from_id": from_id,
                        "to_id": to_id,
                        "properties": properties
                    })
                    
                    if len(batch) >= 1000:
                        with neo4j_driver.session() as session:
                            session.run(cypher, {"batch": batch})
                        batch = []
                        
                # Flush final batch
                if batch:
                    with neo4j_driver.session() as session:
                        session.run(cypher, {"batch": batch})
            
            if os.path.exists(local_rel_path):
                os.remove(local_rel_path)
                
            save_watermark(watermark, rel_file)
            log.info("[OK] Staged relationships file: %s", rel_file)
            
    # Cleanup main manifest file
    if os.path.exists(manifest_path):
        os.remove(manifest_path)
        
    log.info("\n=== Re-Ingestion Complete! Local databases are in full parity ===")
    neo4j_driver.close()


if __name__ == "__main__":
    main()
