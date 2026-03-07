#!/usr/bin/env python3
"""
Phase 34D: Link NCEPLIBS FortranSubroutine nodes to ChromaDB documentation.

Queries Neo4j for all NCEPLIBS Fortran nodes, searches ChromaDB for matching
API documentation, and sets chromadb_doc_id + documented=true on matches
with similarity distance < threshold (default 0.3).

Usage: python3 scripts/link-nceplibs-chromadb.py [--dry-run] [--threshold 0.3]
"""

import os
import sys
import argparse
from neo4j import GraphDatabase
import chromadb

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "gfsworkflow2025")
CHROMADB_HOST = os.environ.get("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.environ.get("CHROMADB_PORT", "8080"))
COLLECTION_NAME = "global-workflow-docs-v8-0-0"

def main():
    parser = argparse.ArgumentParser(description="Phase 34D ChromaDB Linkage")
    parser.add_argument("--dry-run", action="store_true", help="Skip Neo4j writes")
    parser.add_argument("--threshold", type=float, default=0.3, help="Max distance for linking (default: 0.3)")
    parser.add_argument("--batch-size", type=int, default=20, help="ChromaDB query batch size")
    args = parser.parse_args()

    print(f"[INFO] Phase 34D ChromaDB Linkage")
    print(f"[INFO] Threshold: {args.threshold}, Dry run: {args.dry_run}")

    # Connect to Neo4j
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    driver.verify_connectivity()
    print("[OK] Neo4j connected")

    # Connect to ChromaDB
    chroma = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
    collection = chroma.get_collection(COLLECTION_NAME)
    print(f"[OK] ChromaDB collection: {COLLECTION_NAME} ({collection.count()} docs)")

    # Get all NCEPLIBS Fortran nodes from Neo4j
    with driver.session() as session:
        result = session.run("""
            MATCH (n)
            WHERE n.repo STARTS WITH 'nceplibs-'
              AND (n:FortranSubroutine OR n:FortranFunction OR n:FortranModule)
            RETURN n.name AS name, labels(n)[0] AS label, n.repo AS repo
            ORDER BY n.repo, n.name
        """)
        nodes = [{"name": r["name"], "label": r["label"], "repo": r["repo"]} for r in result]

    print(f"[OK] Found {len(nodes)} NCEPLIBS Fortran nodes to match")

    linked = 0
    skipped = 0
    link_details = []

    for i in range(0, len(nodes), args.batch_size):
        batch = nodes[i:i + args.batch_size]
        queries = []
        for n in batch:
            lib_name = n["repo"].replace("nceplibs-", "")
            kind = n["label"].replace("Fortran", "").lower()
            queries.append(f"{lib_name} {n['name']} Fortran {kind}")

        try:
            results = collection.query(query_texts=queries, n_results=1)
        except Exception as e:
            print(f"[WARN] ChromaDB query error for batch {i}: {e}")
            skipped += len(batch)
            continue

        for j, node in enumerate(batch):
            distances = results["distances"][j]
            ids = results["ids"][j]

            if distances and distances[0] < args.threshold:
                doc_id = ids[0]
                distance = distances[0]

                if not args.dry_run:
                    with driver.session() as session:
                        session.run("""
                            MATCH (n)
                            WHERE n.name = $name AND n.repo = $repo
                              AND (n:FortranSubroutine OR n:FortranFunction OR n:FortranModule)
                            SET n.chromadb_doc_id = $docId, n.documented = true
                        """, name=node["name"], repo=node["repo"], docId=doc_id)

                linked += 1
                link_details.append((node["repo"], node["name"], doc_id, distance))
                if linked <= 15 or linked % 50 == 0:
                    print(f"  [LINK] {node['repo']}/{node['name']} -> {doc_id[:20]}... (dist={distance:.4f})")
            else:
                skipped += 1

        processed = min(i + args.batch_size, len(nodes))
        if processed % 200 == 0 or processed >= len(nodes):
            print(f"[INFO] Progress: {processed}/{len(nodes)} processed, {linked} linked so far")

    # Verify in Neo4j
    if not args.dry_run and linked > 0:
        with driver.session() as session:
            result = session.run("""
                MATCH (n)
                WHERE n.chromadb_doc_id IS NOT NULL AND n.repo STARTS WITH 'nceplibs-'
                RETURN count(n) AS cnt
            """)
            verified = result.single()["cnt"]
            print(f"[OK] Verified: {verified} nodes have chromadb_doc_id in Neo4j")

    print(f"\n[SUMMARY]")
    print(f"  Total nodes:  {len(nodes)}")
    print(f"  Linked:       {linked} (distance < {args.threshold})")
    print(f"  Skipped:      {skipped}")
    print(f"  Link rate:    {linked / len(nodes) * 100:.1f}%")
    if args.dry_run:
        print(f"  [DRY RUN] No Neo4j writes performed")

    # Show top links by library
    if link_details:
        print(f"\n[BREAKDOWN] Links by library:")
        from collections import Counter
        lib_counts = Counter(d[0] for d in link_details)
        for lib, cnt in lib_counts.most_common():
            print(f"  {lib:25s}: {cnt} links")

    driver.close()

if __name__ == "__main__":
    main()
