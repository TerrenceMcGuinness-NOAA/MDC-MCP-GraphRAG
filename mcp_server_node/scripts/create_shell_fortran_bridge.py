#!/usr/bin/env python3
"""
Phase 10 M4: Shell-Fortran EXECUTES Bridge

Creates EXECUTES relationships between ShellScript nodes and FortranProgram nodes
by parsing shell scripts for executable references ($EXEC*/name.x patterns).

Usage:
    python create_shell_fortran_bridge.py [--dry-run] [--verbose]
"""

import os
import re
import sys
import argparse
from pathlib import Path
from neo4j import GraphDatabase

# Configuration
NEO4J_URI = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_USER = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', 'gfsworkflow2025')
WORKFLOW_ROOT = os.getenv('MCP_WORKFLOW_ROOT', '/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow_develop')

# Patterns to match executable references in shell scripts
EXEC_PATTERNS = [
    # ${EXECgfs}/name.x or $EXECgfs/name.x
    r'\$\{?EXEC[a-z]*\}?/([a-zA-Z0-9_-]+)\.x\b',
    # ${HOMEgfs}/exec/name.x or $HOMEgfs/exec/name.x  
    r'\$\{?HOME[a-z]*\}?/exec/([a-zA-Z0-9_-]+)\.x\b',
    # Direct executable assignment: GSIEXEC=.../gsi.x
    r'[A-Z_]+EXEC[^=]*=.*?([a-zA-Z0-9_-]+)\.x\b',
    # export pgm="name.x"
    r'export\s+pgm=["\']?([a-zA-Z0-9_-]+)\.x["\']?',
]

# Known executable→FortranProgram mappings from link_workflow.sh
# Maps executable name (without .x) to the PROGRAM name in source
# This is needed because many programs use "program main" but are
# named after their containing *.fd directory at build time
KNOWN_EXEC_MAPPINGS = {
    # gfs_utils programs (use various internal names)
    'gaussian_sfcanl': None,  # program main - no FortranProgram node
    'gfs_bufr': None,         # program meteormrf - no match
    'fbwndgfs': None,
    'supvit': None,
    'syndat_getjtbul': None,
    'syndat_maksynrc': None,
    'syndat_qctropcy': None,
    'tocsbufr': 'TOCSBUFR',   # matches exactly
    'overgridid': None,
    'rdbfmsua': None,
    'mkgfsawps': None,
    'tave': None,
    'vint': None,
    'webtitle': None,
    'ensstat': None,
    
    # gsi_utils programs
    'calc_analysis': None,    # program main
    'calc_increment_ens': 'calc_increment',  # matches base program
    'calc_increment_ens_ncio': 'calc_increment',
    'getsfcensmeanp': 'getsfcensmeanp',  # exact match
    'getsigensmeanp_smooth': None,
    'interp_inc': None,
    'recentersigp': 'recentersigp',
    
    # gsi_monitor programs
    'oznmon_horiz': None,
    'oznmon_time': None,
    'radmon_angle': None,
    'radmon_bcoef': None,
    'radmon_bcor': None,
    'radmon_time': None,
    
    # ufs_utils programs
    'emcsfc_ice_blend': None,
    'emcsfc_snow2mdl': None,
    'global_cycle': None,
    
    # Core GSI/EnKF - these have proper PROGRAM names
    'gsi': 'gsi',
    'enkf': 'enkf_main',
}


def get_fortran_programs(driver):
    """Fetch all FortranProgram nodes from Neo4j."""
    programs = {}
    with driver.session() as session:
        result = session.run("MATCH (p:FortranProgram) RETURN p.name, p.filepath")
        for record in result:
            name = record['p.name']
            filepath = record['p.filepath']
            programs[name.lower()] = {'name': name, 'filepath': filepath}
    return programs


def get_shell_scripts(driver):
    """Fetch all ShellScript nodes from Neo4j."""
    scripts = {}
    with driver.session() as session:
        result = session.run("MATCH (s:ShellScript) RETURN s.name, s.filepath")
        for record in result:
            name = record['s.name']
            filepath = record['s.filepath']
            scripts[name] = {'name': name, 'filepath': filepath}
    return scripts


def find_executable_refs(filepath):
    """Parse a shell script and extract executable references."""
    refs = set()
    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read()
        
        for pattern in EXEC_PATTERNS:
            matches = re.findall(pattern, content)
            for match in matches:
                # Normalize: strip any trailing characters, lowercase
                exec_name = match.strip().lower()
                if exec_name and len(exec_name) > 1:
                    refs.add(exec_name)
    except Exception as e:
        print(f"  [WARN] Could not read {filepath}: {e}")
    
    return refs


def match_exec_to_program(exec_name, programs):
    """
    Try to match an executable name to a FortranProgram node.
    
    Matching strategies:
    0. Check KNOWN_EXEC_MAPPINGS table first (for mismatched names)
    1. Exact match (exec_name == program_name)
    2. Program name ends with _main (enkf -> enkf_main)
    3. Program name starts with exec_name (calc_increment -> calc_increment_main)
    4. Exec name starts with program (calc_increment_ens -> calc_increment)
    5. Normalize underscores and try again
    """
    exec_lower = exec_name.lower()
    
    # Strategy 0: Check known mappings table
    if exec_lower in KNOWN_EXEC_MAPPINGS:
        mapped_name = KNOWN_EXEC_MAPPINGS[exec_lower]
        if mapped_name is None:
            # Known executable but no matching FortranProgram node exists
            return None
        if mapped_name.lower() in programs:
            return programs[mapped_name.lower()]['name']
    
    # Strategy 1: Exact match
    if exec_lower in programs:
        return programs[exec_lower]['name']
    
    # Strategy 2: Look for _main suffix
    main_name = f"{exec_lower}_main"
    if main_name in programs:
        return programs[main_name]['name']
    
    # Strategy 3: Prefix match (find any program starting with exec_name)
    for prog_name in programs:
        if prog_name.startswith(exec_lower) and (
            prog_name == exec_lower or 
            prog_name[len(exec_lower):].startswith('_')
        ):
            return programs[prog_name]['name']
    
    # Strategy 4: Exec name starts with program name (exec is more specific)
    # e.g., calc_increment_ens -> calc_increment
    for prog_name in programs:
        if exec_lower.startswith(prog_name) and (
            len(exec_lower) == len(prog_name) or
            exec_lower[len(prog_name)] == '_'
        ):
            return programs[prog_name]['name']
    
    # Strategy 5: Try removing common suffixes from exec name
    # e.g., calc_increment_ens_ncio -> calc_increment_ens -> calc_increment
    parts = exec_lower.split('_')
    for i in range(len(parts) - 1, 0, -1):
        partial = '_'.join(parts[:i])
        if partial in programs:
            return programs[partial]['name']
        # Also try with _main suffix
        if f"{partial}_main" in programs:
            return programs[f"{partial}_main"]['name']
    
    return None


def create_executes_relationship(driver, shell_name, program_name, dry_run=False):
    """Create an EXECUTES relationship between ShellScript and FortranProgram."""
    query = """
    MATCH (s:ShellScript {name: $shell_name})
    MATCH (p:FortranProgram {name: $program_name})
    MERGE (s)-[:EXECUTES]->(p)
    RETURN count(*) as created
    """
    if dry_run:
        return 1
    
    with driver.session() as session:
        result = session.run(query, shell_name=shell_name, program_name=program_name)
        record = result.single()
        return record['created'] if record else 0


def scan_shell_scripts_on_disk(workflow_root):
    """Scan shell scripts on disk in jobs/, scripts/, ush/ directories."""
    shell_files = []
    for subdir in ['jobs', 'scripts', 'ush']:
        dirpath = Path(workflow_root) / subdir
        if dirpath.exists():
            for sh_file in dirpath.glob('**/*.sh'):
                shell_files.append(sh_file)
    return shell_files


def main():
    parser = argparse.ArgumentParser(description='Create Shell-Fortran EXECUTES bridge')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed output')
    args = parser.parse_args()

    print("[INFO] Phase 10 M4: Shell-Fortran EXECUTES Bridge")
    print(f"[INFO] Workflow root: {WORKFLOW_ROOT}")
    print(f"[INFO] Neo4j URI: {NEO4J_URI}")
    if args.dry_run:
        print("[INFO] DRY RUN MODE - no changes will be made")
    print()

    # Connect to Neo4j
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    try:
        # Get existing graph data
        print("[1/4] Fetching FortranProgram nodes from Neo4j...")
        programs = get_fortran_programs(driver)
        print(f"       Found {len(programs)} FortranProgram nodes")
        
        print("[2/4] Fetching ShellScript nodes from Neo4j...")
        scripts = get_shell_scripts(driver)
        print(f"       Found {len(scripts)} ShellScript nodes")
        
        # Scan shell scripts on disk
        print("[3/4] Scanning shell scripts on disk for executable references...")
        shell_files = scan_shell_scripts_on_disk(WORKFLOW_ROOT)
        print(f"       Found {len(shell_files)} shell files in jobs/, scripts/, ush/")
        
        # Extract executable references and build mappings
        all_refs = {}  # {exec_name: [shell_files]}
        matched_refs = {}  # {(shell_name, program_name): True}
        unmatched_execs = set()
        
        for sh_file in shell_files:
            exec_refs = find_executable_refs(sh_file)
            shell_name = sh_file.name
            
            for exec_name in exec_refs:
                if exec_name not in all_refs:
                    all_refs[exec_name] = []
                all_refs[exec_name].append(shell_name)
                
                # Try to match to a FortranProgram
                program_name = match_exec_to_program(exec_name, programs)
                if program_name:
                    # Check if shell script exists in graph
                    # Try multiple name variants
                    shell_variants = [
                        shell_name,
                        f"ex{shell_name}",
                        shell_name.replace('.sh', ''),
                        f"J{shell_name.upper().replace('.SH', '')}",
                    ]
                    for variant in shell_variants:
                        if variant in scripts:
                            matched_refs[(variant, program_name)] = True
                            if args.verbose:
                                print(f"  [MATCH] {variant} -> EXECUTES -> {program_name}")
                            break
                else:
                    unmatched_execs.add(exec_name)
        
        print(f"       Found {len(all_refs)} unique executable references")
        print(f"       Matched {len(matched_refs)} shell->program pairs")
        print(f"       Unmatched executables: {len(unmatched_execs)}")
        
        if args.verbose and unmatched_execs:
            print("       Unmatched executable names:")
            for name in sorted(unmatched_execs)[:20]:
                print(f"         - {name}")
            if len(unmatched_execs) > 20:
                print(f"         ... and {len(unmatched_execs) - 20} more")
        
        # Create EXECUTES relationships
        print("[4/4] Creating EXECUTES relationships...")
        created = 0
        for (shell_name, program_name) in matched_refs:
            result = create_executes_relationship(driver, shell_name, program_name, args.dry_run)
            if result:
                created += 1
                if args.verbose:
                    print(f"  [CREATE] ({shell_name})-[:EXECUTES]->({program_name})")
        
        print()
        print("=" * 60)
        print("Summary:")
        print(f"  Shell files scanned: {len(shell_files)}")
        print(f"  Unique executables found: {len(all_refs)}")
        print(f"  EXECUTES relationships {'would be ' if args.dry_run else ''}created: {created}")
        print("=" * 60)
        
        if not args.dry_run and created > 0:
            # Verify by counting
            with driver.session() as session:
                result = session.run("MATCH ()-[r:EXECUTES]->() RETURN count(r) as count")
                record = result.single()
                print(f"\nTotal EXECUTES relationships in graph: {record['count']}")
        
    finally:
        driver.close()


if __name__ == '__main__':
    main()
