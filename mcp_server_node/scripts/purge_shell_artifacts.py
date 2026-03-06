#!/usr/bin/env python3
"""Purge spurious ShellScript nodes from Neo4j.

The source-ingestion regex occasionally captures shell tokens, variable
expansions, and glob fragments as ShellScript nodes.  These artifacts
never contain a ``/`` in their ``path`` property (real scripts always
have a path component).  This script finds and removes them, along with
any attached relationships (via DETACH DELETE).
"""

import argparse
import os
import sys

from neo4j import GraphDatabase

MATCH_QUERY = "MATCH (s:ShellScript) WHERE NOT s.path CONTAINS '/' RETURN s.path AS path ORDER BY path"
DELETE_QUERY = "MATCH (s:ShellScript) WHERE NOT s.path CONTAINS '/' DETACH DELETE s RETURN count(s) AS deleted"


def main():
    parser = argparse.ArgumentParser(
        description="Delete spurious ShellScript nodes (no '/' in path) from Neo4j."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List nodes that would be deleted without actually deleting them.",
    )
    args = parser.parse_args()

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "gfsworkflow2025")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            if args.dry_run:
                result = session.run(MATCH_QUERY)
                records = list(result)
                for record in records:
                    print(f"  would delete: {record['path']}")
                print(f"[DRY-RUN] Would purge {len(records)} nodes")
            else:
                # List nodes first so the operator sees what is being removed.
                preview = session.run(MATCH_QUERY)
                for record in preview:
                    print(f"  deleting: {record['path']}")

                result = session.run(DELETE_QUERY)
                deleted = result.single()["deleted"]
                print(f"[OK] Purged {deleted} spurious ShellScript nodes")
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
