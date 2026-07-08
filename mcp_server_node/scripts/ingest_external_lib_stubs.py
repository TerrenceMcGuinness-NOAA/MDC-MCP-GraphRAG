#!/usr/bin/env python3
"""
ExternalLibrary Stub Creator for ESMF, NUOPC, and FMS/MPP

Phase 46 Step 8: Creates ExternalLibrary nodes in Neo4j for external Fortran
libraries that are referenced via USE statements but have no graph representation.

Scans supported_repos/global-workflow_develop/sorc/ for USE statements, then creates:
  - ExternalLibrary nodes (esmf, nuopc, fms)
  - USES edges from existing File nodes to ExternalLibrary nodes

Follows existing patterns from CMakeGraphIngester.js and parse-ver-files.js.

Author: NOAA EMC Global Workflow MCP Team
Phase: 46 (Knowledge Base Gap Closure)
"""

import os
import re
import sys
import argparse
from pathlib import Path
from collections import defaultdict

from neo4j import GraphDatabase

# Neo4j connection config (same pattern as other ingestion scripts)
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "gfsworkflow2025")

# Repository root
REPO_ROOT = os.getenv(
    "GLOBAL_WORKFLOW_PATH",
    str(Path(__file__).parent.parent.parent / "supported_repos" / "global-workflow")
)

# Library definitions
EXTERNAL_LIBRARIES = {
    'esmf': {
        'family': 'coupling',
        'repo_url': 'https://github.com/esmf-org/esmf',
        'description': 'Earth System Modeling Framework - coupling infrastructure',
        'use_patterns': [r'\buse\s+esmf\b'],
    },
    'nuopc': {
        'family': 'coupling',
        'repo_url': 'https://github.com/esmf-org/esmf',
        'description': 'National Unified Operational Prediction Capability - component model interface',
        'use_patterns': [r'\buse\s+nuopc\b', r'\buse\s+nuopc_\w+'],
    },
    'fms': {
        'family': 'infrastructure',
        'repo_url': 'https://github.com/NOAA-GFDL/FMS',
        'description': 'GFDL Flexible Modeling System - FMS/MPP infrastructure library',
        'use_patterns': [r'\buse\s+fms_\w+', r'\buse\s+mpp_\w+'],
    },
}

# Fortran file extensions
FORTRAN_EXTENSIONS = {'.f', '.f90', '.f95', '.f03', '.f08', '.F', '.F90', '.F95', '.F03', '.F08'}


def find_fortran_files(root_dir):
    """Find all Fortran files under sorc/."""
    sorc_dir = Path(root_dir) / "sorc"
    if not sorc_dir.exists():
        print(f"[ERROR] sorc/ directory not found at {sorc_dir}")
        return []

    fortran_files = []
    for f in sorc_dir.rglob("*"):
        if f.is_file() and f.suffix in FORTRAN_EXTENSIONS:
            fortran_files.append(f)
    return fortran_files


def scan_use_statements(fortran_files, library_config):
    """Scan Fortran files for USE statements matching library patterns."""
    results = defaultdict(lambda: defaultdict(set))  # lib_name -> {file_path: set(modules)}

    for lib_name, config in library_config.items():
        compiled = [re.compile(p, re.IGNORECASE) for p in config['use_patterns']]

        for fpath in fortran_files:
            try:
                content = fpath.read_text(errors='replace')
                for line in content.splitlines():
                    stripped = line.strip()
                    if not stripped.lower().startswith('use '):
                        continue
                    for pattern in compiled:
                        match = pattern.search(stripped)
                        if match:
                            # Extract the module name from USE statement
                            mod_match = re.match(r'use\s+(\w+)', stripped, re.IGNORECASE)
                            if mod_match:
                                module_name = mod_match.group(1).lower()
                                rel_path = str(fpath.relative_to(Path(REPO_ROOT)))
                                results[lib_name][rel_path].add(module_name)
                            break
            except Exception as e:
                print(f"[WARN] Could not read {fpath}: {e}")

    return results


def create_library_nodes(session, library_config, dry_run=False):
    """Create ExternalLibrary nodes for each library."""
    count = 0
    for lib_name, config in library_config.items():
        if dry_run:
            print(f"  [DRY RUN] Would create ExternalLibrary: {lib_name}")
            count += 1
            continue

        result = session.run('''
            MERGE (el:ExternalLibrary {name: $name})
            SET el.family = $family,
                el.repo_url = $repo_url,
                el.description = $description,
                el.lastUpdated = datetime()
            RETURN count(el) as cnt
        ''',
            name=lib_name,
            family=config['family'],
            repo_url=config['repo_url'],
            description=config['description']
        )
        cnt = result.single()['cnt']
        count += cnt
        print(f"  [OK] ExternalLibrary node: {lib_name} (family={config['family']})")

    return count


def create_uses_edges(session, scan_results, dry_run=False):
    """Create USES edges from FortranModule nodes to ExternalLibrary nodes."""
    total_edges = 0
    total_missing = 0

    for lib_name, file_modules in scan_results.items():
        lib_edges = 0
        for file_path, modules in file_modules.items():
            if dry_run:
                lib_edges += 1
                continue

            # Match FortranModule nodes by file_path (sorc/ prefix matches Neo4j paths)
            result = session.run('''
                MATCH (fm:FortranModule)
                WHERE fm.file_path = $path
                WITH fm LIMIT 1
                MATCH (el:ExternalLibrary {name: $lib_name})
                MERGE (fm)-[r:USES]->(el)
                SET r.modules = $modules,
                    r.lastUpdated = datetime()
                RETURN count(r) as cnt
            ''',
                path=file_path,
                lib_name=lib_name,
                modules=sorted(list(modules))
            )
            cnt = result.single()['cnt']
            if cnt > 0:
                lib_edges += cnt
            else:
                # Try matching via suffix for absolute paths
                result = session.run('''
                    MATCH (fm:FortranModule)
                    WHERE fm.file_path ENDS WITH $suffix
                    WITH fm LIMIT 1
                    MATCH (el:ExternalLibrary {name: $lib_name})
                    MERGE (fm)-[r:USES]->(el)
                    SET r.modules = $modules,
                        r.lastUpdated = datetime()
                    RETURN count(r) as cnt
                ''',
                    suffix='/' + file_path.split('sorc/')[-1] if 'sorc/' in file_path else '/' + file_path,
                    lib_name=lib_name,
                    modules=sorted(list(modules))
                )
                cnt = result.single()['cnt']
                if cnt > 0:
                    lib_edges += cnt
                else:
                    total_missing += 1

        total_edges += lib_edges
        print(f"  [OK] {lib_name}: {lib_edges} USES edges created ({len(file_modules)} files scanned)")

    if total_missing > 0:
        print(f"  [WARN] {total_missing} files had no matching FortranModule node in Neo4j")

    return total_edges


def validate_results(session):
    """Run validation queries."""
    print("\n[VALIDATE] Checking ExternalLibrary state...")

    result = session.run('''
        MATCH (el:ExternalLibrary)
        WHERE el.name IN ['esmf', 'nuopc', 'fms']
        OPTIONAL MATCH (el)<-[r:USES]-(fm:FortranModule)
        RETURN el.name AS name, el.family AS family, count(r) AS uses_count
        ORDER BY el.name
    ''')

    for record in result:
        print(f"  {record['name']}: family={record['family']}, USES edges={record['uses_count']}")

    # Total ExternalLibrary count
    result = session.run('MATCH (el:ExternalLibrary) RETURN count(el) as total')
    total = result.single()['total']
    print(f"\n  Total ExternalLibrary nodes: {total}")


def main():
    parser = argparse.ArgumentParser(
        description='Create ExternalLibrary stubs for ESMF, NUOPC, FMS/MPP (Phase 46)'
    )
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be created without modifying Neo4j')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed output for each file')
    parser.add_argument('--validate-only', action='store_true',
                       help='Only run validation queries, no ingestion')
    args = parser.parse_args()

    print("=" * 70)
    print("EXTERNAL LIBRARY STUB CREATOR - Phase 46")
    print("=" * 70)
    print(f"Repository: {REPO_ROOT}")
    print(f"Libraries:  {', '.join(EXTERNAL_LIBRARIES.keys())}")
    print(f"Mode:       {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 70)

    driver = None
    session = None

    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        session = driver.session()

        if args.validate_only:
            validate_results(session)
            return

        # Step 1: Find Fortran files
        print("\n[STEP 1] Scanning for Fortran files...")
        fortran_files = find_fortran_files(REPO_ROOT)
        print(f"  Found {len(fortran_files)} Fortran files")

        # Step 2: Scan USE statements
        print("\n[STEP 2] Scanning USE statements for ESMF/NUOPC/FMS...")
        scan_results = scan_use_statements(fortran_files, EXTERNAL_LIBRARIES)
        for lib_name, file_modules in scan_results.items():
            total_modules = sum(len(m) for m in file_modules.values())
            print(f"  {lib_name}: {len(file_modules)} files, {total_modules} unique module references")

        # Step 3: Create ExternalLibrary nodes
        print("\n[STEP 3] Creating ExternalLibrary nodes...")
        node_count = create_library_nodes(session, EXTERNAL_LIBRARIES, dry_run=args.dry_run)
        print(f"  Created {node_count} ExternalLibrary nodes")

        # Step 4: Create USES edges
        print("\n[STEP 4] Creating USES edges from Fortran files...")
        edge_count = create_uses_edges(session, scan_results, dry_run=args.dry_run)
        print(f"  Created {edge_count} total USES edges")

        # Step 5: Validate
        if not args.dry_run:
            validate_results(session)

        print("\n" + "=" * 70)
        print(f"[OK] ExternalLibrary stub creation complete")
        print(f"  Nodes: {node_count}")
        print(f"  Edges: {edge_count}")
        print("=" * 70)

    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    finally:
        if session:
            session.close()
        if driver:
            driver.close()


if __name__ == '__main__':
    main()
