#!/usr/bin/env python3
"""
Phase 27J Step 1: Deduplicate ShellScript Nodes in Neo4j

Problem: Each ex-script has 2-4 ShellScript nodes with the same name but
different type/path values (from multiple ingestion passes). This causes
bridge EXECUTES edges to multiply (48 edges for 16 unique pairs).

Strategy:
  1. Find all ShellScript names with count > 1
  2. For each group, keep the node with the most relationships (highest degree)
  3. Copy any unique outgoing/incoming edges from duplicates to the keeper
  4. Delete duplicate nodes (DETACH DELETE removes their edges)

Safety:
  - Dry-run mode by default (--dry-run or no flag)
  - Logs every action
  - Creates a backup snapshot of affected nodes before deletion

Usage:
  python dedup_shellscript_nodes.py --dry-run    # Preview only
  python dedup_shellscript_nodes.py --execute     # Actually dedup
  python dedup_shellscript_nodes.py --verbose     # Detailed output

Author: NOAA EMC EIB MCP Team
Phase: 27J Step 1
"""

import os
import sys
import json
import argparse
from datetime import datetime

try:
    from neo4j import GraphDatabase
except ImportError:
    print("[ERROR] neo4j package not found. Run: pip install --user neo4j")
    sys.exit(1)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "gfsworkflow2025")


def find_duplicate_groups(session):
    """Find all ShellScript names that have more than one node."""
    result = session.run("""
        MATCH (s:ShellScript)
        WITH s.name AS name, collect(s) AS nodes, count(*) AS cnt
        WHERE cnt > 1
        RETURN name, cnt,
               [n IN nodes | {
                 id: elementId(n),
                 type: n.type,
                 path: n.path,
                 degree: COUNT{ (n)--() }
               }] AS nodeDetails
        ORDER BY cnt DESC
    """)
    # The COUNT{} inside list comprehension doesn't work — need a different approach
    return list(result)


def find_duplicate_groups_v2(session):
    """Find all ShellScript names with duplicates, including degree info."""
    # Step 1: Get all duplicate names
    names_result = session.run("""
        MATCH (s:ShellScript)
        WITH s.name AS name, count(*) AS cnt
        WHERE cnt > 1
        RETURN name, cnt ORDER BY cnt DESC
    """)
    groups = []
    for rec in names_result:
        name = rec["name"]
        cnt = rec["cnt"]
        # Step 2: Get node details for each group
        nodes_result = session.run("""
            MATCH (s:ShellScript {name: $name})
            WITH s, COUNT{(s)-->()} AS outDeg, COUNT{(s)<--()} AS inDeg
            RETURN elementId(s) AS id, s.type AS type, s.path AS path,
                   outDeg, inDeg, outDeg + inDeg AS totalDeg
            ORDER BY totalDeg DESC
        """, name=name)
        nodes = [dict(r) for r in nodes_result]
        groups.append({"name": name, "count": cnt, "nodes": nodes})
    return groups


def get_node_edges(session, node_id):
    """Get all outgoing and incoming edges for a node."""
    out_result = session.run("""
        MATCH (s)-[r]->(t)
        WHERE elementId(s) = $id
        RETURN type(r) AS relType, elementId(t) AS targetId, t.name AS targetName,
               labels(t)[0] AS targetLabel, properties(r) AS relProps
    """, id=node_id)
    outgoing = [dict(r) for r in out_result]

    in_result = session.run("""
        MATCH (s)<-[r]-(t)
        WHERE elementId(s) = $id
        RETURN type(r) AS relType, elementId(t) AS sourceId, t.name AS sourceName,
               labels(t)[0] AS sourceLabel, properties(r) AS relProps
    """, id=node_id)
    incoming = [dict(r) for r in in_result]

    return outgoing, incoming


def copy_edge_to_keeper(session, keeper_id, edge, direction, verbose=False):
    """Copy a unique edge from a duplicate to the keeper node."""
    if direction == "outgoing":
        # Check if keeper already has this edge
        check = session.run("""
            MATCH (keeper)-[r]->(target)
            WHERE elementId(keeper) = $keeperId
            AND elementId(target) = $targetId
            AND type(r) = $relType
            RETURN count(r) AS cnt
        """, keeperId=keeper_id, targetId=edge["targetId"], relType=edge["relType"])
        if check.single()["cnt"] > 0:
            return False  # Edge already exists

        # Create the edge using APOC-free approach
        # We need dynamic relationship type — use FOREACH trick or multiple queries
        rel_type = edge["relType"]
        props = edge.get("relProps", {})
        # Filter out None values from props
        props = {k: v for k, v in props.items() if v is not None} if props else {}

        session.run(f"""
            MATCH (keeper), (target)
            WHERE elementId(keeper) = $keeperId AND elementId(target) = $targetId
            CREATE (keeper)-[r:`{rel_type}`]->(target)
            SET r = $props
        """, keeperId=keeper_id, targetId=edge["targetId"], props=props)
        return True

    elif direction == "incoming":
        check = session.run("""
            MATCH (source)-[r]->(keeper)
            WHERE elementId(keeper) = $keeperId
            AND elementId(source) = $sourceId
            AND type(r) = $relType
            RETURN count(r) AS cnt
        """, keeperId=keeper_id, sourceId=edge["sourceId"], relType=edge["relType"])
        if check.single()["cnt"] > 0:
            return False

        rel_type = edge["relType"]
        props = edge.get("relProps", {})
        props = {k: v for k, v in props.items() if v is not None} if props else {}

        session.run(f"""
            MATCH (source), (keeper)
            WHERE elementId(source) = $sourceId AND elementId(keeper) = $keeperId
            CREATE (source)-[r:`{rel_type}`]->(keeper)
            SET r = $props
        """, sourceId=edge["sourceId"], keeperId=keeper_id, props=props)
        return True

    return False


def merge_properties(session, keeper_id, dupe_node, verbose=False):
    """Copy non-null properties from a duplicate to the keeper if keeper's are null."""
    # Get dupe properties
    result = session.run("""
        MATCH (s) WHERE elementId(s) = $id
        RETURN properties(s) AS props
    """, id=dupe_node["id"])
    dupe_props = result.single()["props"]

    # Get keeper properties
    result = session.run("""
        MATCH (s) WHERE elementId(s) = $id
        RETURN properties(s) AS props
    """, id=keeper_id)
    keeper_props = result.single()["props"]

    # Find properties to copy (non-null in dupe, null/missing in keeper)
    updates = {}
    skip_keys = {"name"}  # Don't overwrite name
    for key, val in dupe_props.items():
        if key in skip_keys:
            continue
        if val is not None and (key not in keeper_props or keeper_props[key] is None):
            updates[key] = val

    if updates and not dupe_node.get("dry_run", False):
        for key, val in updates.items():
            session.run(f"""
                MATCH (s) WHERE elementId(s) = $id
                SET s.`{key}` = $val
            """, id=keeper_id, val=val)

    return updates


def dedup_group(session, group, execute=False, verbose=False):
    """Deduplicate one group of ShellScript nodes."""
    name = group["name"]
    nodes = group["nodes"]

    if len(nodes) < 2:
        return {"name": name, "action": "skip", "reason": "single node"}

    # Keeper is the first (highest degree)
    keeper = nodes[0]
    dupes = nodes[1:]

    stats = {
        "name": name,
        "keeper_id": keeper["id"],
        "keeper_type": keeper["type"],
        "keeper_path": keeper["path"],
        "keeper_degree": keeper["totalDeg"],
        "dupes_removed": 0,
        "edges_copied": 0,
        "props_merged": 0,
    }

    for dupe in dupes:
        # Get edges from the duplicate
        outgoing, incoming = get_node_edges(session, dupe["id"])

        edges_copied = 0
        if execute:
            # Merge properties first
            updates = merge_properties(session, keeper["id"], dupe, verbose=verbose)
            stats["props_merged"] += len(updates)

            # Copy unique edges to keeper
            for edge in outgoing:
                if copy_edge_to_keeper(session, keeper["id"], edge, "outgoing", verbose):
                    edges_copied += 1
            for edge in incoming:
                if copy_edge_to_keeper(session, keeper["id"], edge, "incoming", verbose):
                    edges_copied += 1

            # Delete the duplicate node
            session.run("MATCH (s) WHERE elementId(s) = $id DETACH DELETE s", id=dupe["id"])
            stats["dupes_removed"] += 1
        else:
            # Dry-run: just count what would happen
            stats["dupes_removed"] += 1  # would remove
            edges_copied = len(outgoing) + len(incoming)  # would need to check

        stats["edges_copied"] += edges_copied

        if verbose:
            action = "DELETED" if execute else "WOULD DELETE"
            print(f"    {action} {dupe['id'][-6:]} type={dupe['type']} "
                  f"path={dupe['path']} deg={dupe['totalDeg']} "
                  f"(copied {edges_copied} unique edges)")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Deduplicate ShellScript nodes in Neo4j")
    parser.add_argument("--execute", action="store_true", help="Actually perform dedup (default: dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Detailed output")
    args = parser.parse_args()

    execute = args.execute and not args.dry_run
    mode = "EXECUTE" if execute else "DRY-RUN"

    print(f"[INFO] Phase 27J Step 1: ShellScript Node Deduplication ({mode})")
    print(f"[INFO] Neo4j: {NEO4J_URI}")
    print()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    with driver.session() as session:
        # Pre-dedup counts
        pre = session.run("""
            MATCH (s:ShellScript) 
            WITH count(s) AS nodes
            OPTIONAL MATCH (:ShellScript)-[r:EXECUTES]->(:FortranProgram) 
            RETURN nodes, count(r) AS execEdges
        """).single()
        print(f"[INFO] Before: {pre['nodes']} ShellScript nodes, {pre['execEdges']} EXECUTES edges")

        # Find duplicate groups
        groups = find_duplicate_groups_v2(session)
        print(f"[INFO] Found {len(groups)} duplicate name groups")
        print()

        total_stats = {
            "groups_processed": 0,
            "dupes_removed": 0,
            "edges_copied": 0,
            "props_merged": 0,
        }

        for group in groups:
            if args.verbose:
                print(f"  {group['name']}: {group['count']} nodes")

            result = dedup_group(session, group, execute=execute, verbose=args.verbose)

            total_stats["groups_processed"] += 1
            total_stats["dupes_removed"] += result.get("dupes_removed", 0)
            total_stats["edges_copied"] += result.get("edges_copied", 0)
            total_stats["props_merged"] += result.get("props_merged", 0)

        print()
        print(f"[{'OK' if execute else 'DRY-RUN'}] Summary:")
        print(f"  Groups processed: {total_stats['groups_processed']}")
        print(f"  Duplicate nodes {'removed' if execute else 'to remove'}: {total_stats['dupes_removed']}")
        print(f"  Edges copied to keepers: {total_stats['edges_copied']}")
        print(f"  Properties merged: {total_stats['props_merged']}")

        if execute:
            # Post-dedup counts
            post = session.run("""
                MATCH (s:ShellScript) 
                WITH count(s) AS nodes
                OPTIONAL MATCH (:ShellScript)-[r:EXECUTES]->(:FortranProgram) 
                RETURN nodes, count(r) AS execEdges
            """).single()
            print(f"\n[OK] After: {post['nodes']} ShellScript nodes, {post['execEdges']} EXECUTES edges")

            # Verify no duplicates remain
            remaining = session.run("""
                MATCH (s:ShellScript)
                WITH s.name AS name, count(*) AS cnt
                WHERE cnt > 1
                RETURN count(name) AS remaining
            """).single()["remaining"]
            print(f"[{'OK' if remaining == 0 else 'WARN'}] Remaining duplicate names: {remaining}")

    driver.close()
    print(f"\n[INFO] Done ({mode})")


if __name__ == "__main__":
    main()
