#!/usr/bin/env python3
"""
Phase 24F-2 / 27I: Cross-Language Bridge Edge Ingestion

Creates EXECUTES and INVOKES relationships in Neo4j to connect:
  - Shell ex-scripts → Fortran executables (EXECUTES)
  - Shell ex-scripts → Python scripts (INVOKES)

Phase 27I additions:
  - Creates placeholder FortranProgram nodes for external packages (GSI, UFS_UTILS, Fit2Obs)
  - Fills all EXEC_TO_PROGRAM mappings (was 12 None entries, now fully resolved)

Approach:
  1. Create placeholder FortranProgram nodes for external executables
  2. Parse each shell ex-script for .x executable references and .py script references
  3. Match executable names to FortranProgram nodes (fuzzy: strip .x, match program name)
  4. Match .py references to PythonModule nodes (by filename)
  5. Create cross-language edges

Neo4j Schema:
  (f:File {absolutePath}) -[:EXECUTES {executable, line}]-> (p:FortranProgram {name})
  (f:File {absolutePath}) -[:INVOKES {script, line}]-> (m:PythonModule {name})

Usage:
  python ingest_cross_language_bridges.py --dry-run   # Parse only
  python ingest_cross_language_bridges.py              # Full ingestion
  python ingest_cross_language_bridges.py --verbose    # With detail

Author: NOAA EMC EIB MCP Team
Phase: 24F-2, 27I
Version: 2.0.0
"""

import os
import re
import sys
import argparse
from pathlib import Path
from collections import defaultdict

try:
    from neo4j import GraphDatabase
except ImportError:
    print("[WARN] neo4j package not found.")
    GraphDatabase = None

VERSION = "2.0.0"
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "gfsworkflow2025")

WORKFLOW_ROOT = os.getenv("WORKFLOW_ROOT",
    "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow")

# Patterns for finding executable invocations in shell scripts
EXEC_PATTERNS = [
    # $EXECgfs/name.x or ${EXECgfs}/name.x
    re.compile(r'\$\{?EXEC\w*\}?/(\w+)\.x'),
    # ${HOMEgfs}/exec/name.x
    re.compile(r'\$\{?HOME\w*\}?/exec/(\w+)\.x'),
    # Direct .x reference after path separator
    re.compile(r'/(\w+)\.x["\s]'),
    # pgm=${VARIABLE} where VARIABLE ends in EXEC
    re.compile(r'pgm=\$\{?(\w*EXEC\w*)\}?'),
    # APRUN commands referencing executables
    re.compile(r'APRUN\w*\}\s+"[^"]*?/(\w+)\.x"'),
    re.compile(r'APRUN\w*\}\s+"[^"]*?/(\w+)"'),
]

# Patterns for Python script invocations
PYTHON_PATTERNS = [
    # ${USHgfs}/script.py or $USHgfs/script.py
    re.compile(r'\$\{?USH\w*\}?/(\w+\.py)'),
    # Direct python3 invocation
    re.compile(r'python3?\s+["\']?(?:\$\{?\w+\}?/)?(\w+\.py)'),
    # Variable assignment referencing .py
    re.compile(r'=.*\$\{?\w+\}?/(\w+\.py)'),
]

# Known mappings: executable binary name → FortranProgram PROGRAM name
# (because Fortran PROGRAM names don't always match the compiled binary)
EXEC_TO_PROGRAM = {
    'gsi': 'gsi',
    'enkf': 'enkf_main',
    'calc_increment_ens': 'calc_increment_main',
    'calc_increment_ens_ncio': 'calc_increment_main',
    'calc_analysis': 'calc_analysis',
    'gaussian_sfcanl': 'gaussian_sfcanl',
    'interp_inc': 'interp_inc',
    'enkf_chgres_recenter': 'enkf_chgres_recenter',
    'enkf_chgres_recenter_nc': 'enkf_chgres_recenter_nc',
    'getsigensmeanp_smooth': 'getsigensmeanp_smooth',
    'getsfcensmeanp': 'getsfcensmeanp',
    'recentersigp': 'recentersigp',
    'fbwndgfs': 'fbwndgfs',
    'rdbfmsua': 'rdbfmsua',
    'chgres_cube': 'chgres_cube',
}

# External Fortran programs not in Neo4j — create placeholder nodes
EXTERNAL_PROGRAMS = [
    {'name': 'calc_analysis', 'package': 'UFS_UTILS', 'desc': 'Atmospheric analysis calculation'},
    {'name': 'gaussian_sfcanl', 'package': 'UFS_UTILS', 'desc': 'Gaussian surface analysis'},
    {'name': 'interp_inc', 'package': 'UFS_UTILS', 'desc': 'Interpolate increments'},
    {'name': 'chgres_cube', 'package': 'UFS_UTILS', 'desc': 'Change resolution cubed-sphere'},
    {'name': 'enkf_chgres_recenter', 'package': 'GSI', 'desc': 'EnKF change resolution + recenter'},
    {'name': 'enkf_chgres_recenter_nc', 'package': 'GSI', 'desc': 'EnKF chgres recenter (NetCDF)'},
    {'name': 'getsigensmeanp_smooth', 'package': 'GSI', 'desc': 'Ensemble mean + smoothing'},
    {'name': 'getsfcensmeanp', 'package': 'GSI', 'desc': 'Surface ensemble mean'},
    {'name': 'recentersigp', 'package': 'GSI', 'desc': 'Sigma-pressure recentering'},
    {'name': 'fbwndgfs', 'package': 'Fit2Obs', 'desc': 'Background wind GFS'},
    {'name': 'rdbfmsua', 'package': 'Fit2Obs', 'desc': 'Read BUFR mandatory/significant upper air'},
]


def parse_shell_script(file_path):
    """Parse a shell script for executable and Python references."""
    executables = []
    python_scripts = []

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            for lineno, line in enumerate(f, 1):
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue

                # Find Fortran executable references
                for pattern in EXEC_PATTERNS:
                    for match in pattern.finditer(line):
                        exe_name = match.group(1)
                        # Skip variable references like ${GSIEXEC}
                        if exe_name.endswith('EXEC') or exe_name.endswith('EXEC}'):
                            continue
                        executables.append({
                            'name': exe_name,
                            'line': lineno,
                            'context': stripped[:120]
                        })

                # Find Python script references
                for pattern in PYTHON_PATTERNS:
                    for match in pattern.finditer(line):
                        py_name = match.group(1)
                        python_scripts.append({
                            'name': py_name,
                            'line': lineno,
                            'context': stripped[:120]
                        })
    except Exception as e:
        print(f"  [ERROR] Failed to parse {file_path}: {e}")

    return {
        'executables': executables,
        'python_scripts': python_scripts
    }


def build_fortran_program_index(session):
    """Build lookup index: lowercase name → FortranProgram node."""
    result = session.run(
        'MATCH (p:FortranProgram) RETURN p.name as name, p.file_path as path'
    )
    index = {}
    for rec in result:
        name = rec['name']
        if name:
            index[name.lower()] = {'name': name, 'file_path': rec['path']}
    return index


def build_python_module_index(session):
    """Build lookup index: filename → PythonModule node."""
    result = session.run(
        'MATCH (m:PythonModule) WHERE m.file_path IS NOT NULL RETURN m.name as name, m.file_path as path'
    )
    index = {}
    for rec in result:
        path = rec['path']
        if path:
            filename = Path(path).name
            index[filename.lower()] = {'name': rec['name'], 'file_path': path}
    return index


def build_file_index(session):
    """Build lookup index: script basename → File node absolutePath."""
    result = session.run(
        'MATCH (f:File) WHERE f.absolutePath ENDS WITH ".sh" '
        'AND (f.absolutePath CONTAINS "/scripts/ex" OR f.absolutePath CONTAINS "/dev/scripts/ex") '
        'RETURN f.absolutePath as path'
    )
    index = {}
    for rec in result:
        path = rec['path']
        if path:
            basename = Path(path).name
            index[basename] = path
    return index


def create_external_program_nodes(session, dry_run=False):
    """Create placeholder FortranProgram nodes for external executables (Phase 27I).

    These represent Fortran programs from external packages (GSI, UFS_UTILS, Fit2Obs)
    whose source was never ingested. Placeholder nodes enable EXECUTES edges to form.
    """
    created = 0
    for prog in EXTERNAL_PROGRAMS:
        if dry_run:
            print(f"  [DRY-RUN] Placeholder: {prog['name']} ({prog['package']})")
            created += 1
            continue

        result = session.run('''
            MERGE (p:FortranProgram {name: $name})
            ON CREATE SET p.external = true,
                          p.package = $package,
                          p.description = $desc,
                          p.placeholder = true
            RETURN
                CASE WHEN p.external IS NOT NULL THEN 'existing' ELSE 'created' END AS status
        ''', name=prog['name'], package=prog['package'], desc=prog['desc'])
        created += 1

    print(f"  Placeholder FortranProgram nodes: {created} ({', '.join(set(p['package'] for p in EXTERNAL_PROGRAMS))})")
    return created


def match_executable(exe_name, fortran_index):
    """Match an executable name to a FortranProgram node."""
    lower = exe_name.lower()

    # Direct match
    if lower in fortran_index:
        return fortran_index[lower]

    # Known mapping
    if lower in EXEC_TO_PROGRAM:
        mapped = EXEC_TO_PROGRAM[lower]
        if mapped and mapped.lower() in fortran_index:
            return fortran_index[mapped.lower()]

    # Fuzzy: strip common suffixes/prefixes
    for suffix in ['_main', '_pmain', 'main']:
        if (lower + '_' + suffix) in fortran_index:
            return fortran_index[lower + '_' + suffix]
        candidate = lower + suffix
        if candidate in fortran_index:
            return fortran_index[candidate]

    # Substring match (last resort)
    for prog_name, prog_data in fortran_index.items():
        if lower in prog_name or prog_name in lower:
            return prog_data

    return None


def create_executes_edges(session, edges, dry_run=False):
    """Create EXECUTES relationships between File and FortranProgram nodes."""
    created = 0
    for edge in edges:
        if dry_run:
            print(f"  [DRY-RUN] EXECUTES: {edge['script']} → {edge['program']} "
                  f"(exe={edge['executable']}, L{edge['line']})")
            created += 1
            continue

        result = session.run('''
            MATCH (f:File {absolutePath: $script_path})
            MATCH (p:FortranProgram {name: $program_name})
            MERGE (f)-[r:EXECUTES]->(p)
            ON CREATE SET r.executable = $executable, r.line = $line
            RETURN count(r) as c
        ''',
            script_path=edge['script_path'],
            program_name=edge['program'],
            executable=edge['executable'],
            line=edge['line']
        )
        if result.single()['c'] > 0:
            created += 1

    return created


def create_shellscript_bridges(session, dry_run=False):
    """Phase 24F Step 1: Create EXECUTES/INVOKES edges on ShellScript nodes.

    For each (f:File)-[:EXECUTES]->(p:FortranProgram) edge, find the matching
    ShellScript node by filename and create a parallel
    (s:ShellScript)-[:EXECUTES]->(p:FortranProgram) edge.
    Same for INVOKES → PythonModule.
    """
    # Bridge EXECUTES: File → FortranProgram ⟹ ShellScript → FortranProgram
    executes_query = '''
        MATCH (f:File)-[r:EXECUTES]->(p:FortranProgram)
        WITH f, p, r, split(f.absolutePath, '/')[-1] AS filename
        MATCH (s:ShellScript)
        WHERE s.name = filename OR s.path ENDS WITH filename
        MERGE (s)-[br:EXECUTES {source: 'bridge_unification', bridged_from: f.absolutePath}]->(p)
        ON CREATE SET br.executable = r.executable, br.line = r.line
        RETURN s.name AS shell_script, p.name AS fortran_program
    '''

    # Bridge INVOKES: File → PythonModule ⟹ ShellScript → PythonModule
    invokes_query = '''
        MATCH (f:File)-[r:INVOKES]->(m:PythonModule)
        WITH f, m, r, split(f.absolutePath, '/')[-1] AS filename
        MATCH (s:ShellScript)
        WHERE s.name = filename OR s.path ENDS WITH filename
        MERGE (s)-[br:INVOKES {source: 'bridge_unification', bridged_from: f.absolutePath}]->(m)
        ON CREATE SET br.script = r.script, br.line = r.line
        RETURN s.name AS shell_script, m.name AS python_module
    '''

    if dry_run:
        print("  [DRY-RUN] Would create ShellScript EXECUTES→FortranProgram bridges")
        print("  [DRY-RUN] Would create ShellScript INVOKES→PythonModule bridges")
        return 0, 0

    exec_result = list(session.run(executes_query))
    exec_count = len(exec_result)
    for rec in exec_result:
        print(f"    [BRIDGE] {rec['shell_script']} ═══EXECUTES═══> {rec['fortran_program']}")

    inv_result = list(session.run(invokes_query))
    inv_count = len(inv_result)
    for rec in inv_result:
        print(f"    [BRIDGE] {rec['shell_script']} ═══INVOKES═══> {rec['python_module']}")

    return exec_count, inv_count


def create_invokes_edges(session, edges, dry_run=False):
    """Create INVOKES relationships between File and PythonModule nodes."""
    created = 0
    for edge in edges:
        if dry_run:
            print(f"  [DRY-RUN] INVOKES: {edge['script']} → {edge['module']} "
                  f"(py={edge['py_script']}, L{edge['line']})")
            created += 1
            continue

        result = session.run('''
            MATCH (f:File {absolutePath: $script_path})
            MATCH (m:PythonModule {file_path: $module_path})
            MERGE (f)-[r:INVOKES]->(m)
            ON CREATE SET r.script = $py_script, r.line = $line
            RETURN count(r) as c
        ''',
            script_path=edge['script_path'],
            module_path=edge['module_path'],
            py_script=edge['py_script'],
            line=edge['line']
        )
        if result.single()['c'] > 0:
            created += 1

    return created


def run_ingestion(dry_run=False, verbose=False):
    """Main ingestion: parse shell scripts, match targets, create edges."""
    print(f"[OK] Cross-Language Bridge Ingestion v{VERSION}")
    print(f"[OK] WORKFLOW_ROOT: {WORKFLOW_ROOT}")
    print(f"[OK] Mode: {'DRY-RUN' if dry_run else 'LIVE'}")

    # Check dev/scripts/ first (current repo layout), fall back to scripts/
    scripts_dir = Path(WORKFLOW_ROOT) / 'dev' / 'scripts'
    if not scripts_dir.exists():
        scripts_dir = Path(WORKFLOW_ROOT) / 'scripts'
    if not scripts_dir.exists():
        print(f"[ERROR] Scripts directory not found: {scripts_dir}")
        return
    print(f"[OK] Scanning ex-scripts in: {scripts_dir}")

    # Connect to Neo4j (always needed for index lookups)
    driver = None
    if GraphDatabase is None:
        print("[WARN] neo4j package not found — matching will be skipped")
    else:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    session = driver.session() if driver else None

    # Build lookup indices
    if session:
        # Phase 27I: Create placeholder nodes for external programs BEFORE building index
        print(f"[OK] Creating placeholder nodes for external Fortran programs...")
        create_external_program_nodes(session, dry_run)

        fortran_index = build_fortran_program_index(session)
        python_index = build_python_module_index(session)
        file_index = build_file_index(session)
        print(f"[OK] Indices: {len(fortran_index)} FortranPrograms, "
              f"{len(python_index)} PythonModules, {len(file_index)} Shell scripts")
    else:
        fortran_index = {}
        python_index = {}
        file_index = {}

    # Parse all shell ex-scripts
    shell_scripts = sorted(scripts_dir.glob('ex*.sh'))
    print(f"[OK] Found {len(shell_scripts)} shell ex-scripts to parse")

    executes_edges = []
    invokes_edges = []
    stats = defaultdict(int)

    for script_path in shell_scripts:
        parsed = parse_shell_script(script_path)
        basename = script_path.name
        neo4j_path = file_index.get(basename)

        if verbose:
            print(f"\n  Parsing: {basename}")

        # Match executables to FortranProgram nodes
        seen_exes = set()
        for exe in parsed['executables']:
            exe_name = exe['name']
            if exe_name in seen_exes:
                continue
            seen_exes.add(exe_name)
            stats['exe_refs'] += 1

            match = match_executable(exe_name, fortran_index)
            if match:
                stats['exe_matched'] += 1
                edge = {
                    'script': basename,
                    'script_path': neo4j_path,
                    'program': match['name'],
                    'executable': exe_name,
                    'line': exe['line']
                }
                executes_edges.append(edge)
                if verbose:
                    print(f"    [OK] {exe_name} → {match['name']}")
            else:
                stats['exe_unmatched'] += 1
                if verbose:
                    print(f"    [MISS] {exe_name} — no FortranProgram match")

        # Match Python references to PythonModule nodes
        seen_pys = set()
        for py in parsed['python_scripts']:
            py_name = py['name']
            if py_name in seen_pys:
                continue
            seen_pys.add(py_name)
            stats['py_refs'] += 1

            match = python_index.get(py_name.lower())
            if match:
                stats['py_matched'] += 1
                edge = {
                    'script': basename,
                    'script_path': neo4j_path,
                    'module': match['name'],
                    'module_path': match['file_path'],
                    'py_script': py_name,
                    'line': py['line']
                }
                invokes_edges.append(edge)
                if verbose:
                    print(f"    [OK] {py_name} → {match['name']}")
            else:
                stats['py_unmatched'] += 1
                if verbose:
                    print(f"    [MISS] {py_name} — no PythonModule match")

    # Create edges
    print(f"\n[OK] === Results ===")
    print(f"  Executable references: {stats['exe_refs']} "
          f"(matched: {stats['exe_matched']}, unmatched: {stats['exe_unmatched']})")
    print(f"  Python references: {stats['py_refs']} "
          f"(matched: {stats['py_matched']}, unmatched: {stats['py_unmatched']})")

    if executes_edges:
        created = create_executes_edges(session, executes_edges, dry_run)
        print(f"  EXECUTES edges created: {created}")
    else:
        print(f"  EXECUTES edges: 0 (no matches)")

    if invokes_edges:
        created = create_invokes_edges(session, invokes_edges, dry_run)
        print(f"  INVOKES edges created: {created}")
    else:
        print(f"  INVOKES edges: 0 (no matches)")

    # Phase 24F Step 1: Bridge edges to ShellScript nodes
    if session:
        print(f"\n[OK] === Phase 24F: ShellScript Bridge Unification ===")
        exec_bridges, inv_bridges = create_shellscript_bridges(session, dry_run)
        print(f"  ShellScript EXECUTES bridges: {exec_bridges}")
        print(f"  ShellScript INVOKES bridges: {inv_bridges}")

    # Also scan ush/ scripts for Python references
    ush_dir = Path(WORKFLOW_ROOT) / 'ush'
    if ush_dir.exists():
        ush_scripts = sorted(ush_dir.glob('*.sh'))
        ush_invokes = []
        for script_path in ush_scripts:
            parsed = parse_shell_script(script_path)
            basename = script_path.name
            neo4j_path = file_index.get(basename)
            for py in parsed['python_scripts']:
                py_name = py['name']
                match = python_index.get(py_name.lower())
                if match and neo4j_path:
                    ush_invokes.append({
                        'script': basename,
                        'script_path': neo4j_path,
                        'module': match['name'],
                        'module_path': match['file_path'],
                        'py_script': py_name,
                        'line': py['line']
                    })
        if ush_invokes:
            created = create_invokes_edges(session, ush_invokes, dry_run)
            print(f"  INVOKES edges from ush/: {created}")

    if session:
        session.close()
    if driver:
        driver.close()

    print(f"\n[OK] Cross-language bridge ingestion complete")


def main():
    parser = argparse.ArgumentParser(
        description='Phase 24F-2: Cross-Language Bridge Edge Ingestion',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest_cross_language_bridges.py --dry-run --verbose
  python ingest_cross_language_bridges.py
        """
    )
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Parse only, no Neo4j writes')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show per-script detail')
    parser.add_argument('--version', action='version',
                        version=f'%(prog)s {VERSION}')
    args = parser.parse_args()

    run_ingestion(dry_run=args.dry_run, verbose=args.verbose)


if __name__ == '__main__':
    main()
