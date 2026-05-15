#!/usr/bin/env python3
"""
ingest_env_variables.py - Parse shell scripts for environment variable
declarations and usage, creating EnvironmentVariable nodes and
EXPORTS/DEPENDS_ON_ENV relationships in Neo4j.

Phase 24 Gap 1: Closes the missing EnvironmentVariable node schema
that find_env_dependencies requires.

Patterns detected:
  - export VAR=value      -> EXPORTS relationship
  - export VAR            -> EXPORTS relationship  
  - VAR=value (no export) -> SETS relationship
  - ${VAR}                -> DEPENDS_ON_ENV relationship
  - $VAR (bare)           -> DEPENDS_ON_ENV relationship

Usage:
  python3 ingest_env_variables.py                    # Full ingestion
  python3 ingest_env_variables.py --dry-run           # Preview only
  python3 ingest_env_variables.py --test FILE         # Single file
  python3 ingest_env_variables.py --sample            # First 20 files
  python3 ingest_env_variables.py --var HOMEgfs       # Query single var

@version 1.0.0
@date 2026-02-09
@phase Phase 24 Gap 1 (EnvironmentVariable schema)
"""

import os
import re
import sys
import argparse
import glob
from collections import defaultdict
from pathlib import Path

try:
    from neo4j import GraphDatabase
except ImportError:
    print("[ERROR] neo4j package required: pip install --user neo4j")
    sys.exit(1)


# ===========================================================================
# Configuration
# ===========================================================================

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "gfsworkflow2025")

# Phase 48D: AWS backend support
# Phase 49: Registry-driven model selection
import sys as _sys
try:
    from ingestion_base import BaseIngester as _BaseIngester
    _bi = _BaseIngester.__new__(_BaseIngester)
    _bi.args = _BaseIngester._parse_common_args(_bi)
    from embedding_registry import EmbeddingModelRegistry as _Reg
    from collection_namer import CollectionNamer as _CN
    _profile = _Reg().get_profile(_bi.args.model)
    _namer = _CN(_profile)
    _REGISTRY_AVAILABLE = True
except Exception:
    _REGISTRY_AVAILABLE = False
    if "--backend" in _sys.argv:
        _bidx = _sys.argv.index("--backend")
        if _bidx + 1 < len(_sys.argv):
            os.environ["DB_BACKEND"] = _sys.argv[_bidx + 1]
try:
    from aws_backend import get_graph_driver as _get_graph_driver, BACKEND as _BACKEND
    _AWS_BACKEND_AVAILABLE = True
except ImportError:
    _AWS_BACKEND_AVAILABLE = False
    _BACKEND = "legacy"

WORKFLOW_ROOT = os.environ.get(
    "MCP_WORKFLOW_ROOT",
    "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow"
)

# Directories to scan (relative to WORKFLOW_ROOT)
SCAN_DIRS = [
    "dev/jobs",
    "jobs",
    "ush",
    "scripts",
    "parm/config",
    "env",
    "dev/ush",
    "dev/ci/scripts",
    "dev/ci/platforms",
    "ecf",
]

# File patterns to include
FILE_PATTERNS = ["*.sh", "*.bash", "*.env"]

# EE2 standard variables (from NCO standards Table 1) - tag these as standard
EE2_STANDARD_VARS = {
    "envir", "PACKAGEROOT", "OPSROOT", "job", "jobid", "NET", "RUN",
    "PDY", "cyc", "cycle", "subcyc", "DATAROOT", "DATA", "COMROOT",
    "COMIN", "COMOUT", "DCOMROOT", "DCOMIN", "DBNROOT",
    "SENDECF", "SENDDBN", "SENDDBN_NTC", "SENDCOM", "SENDWEB",
    "KEEPDATA", "MAILTO", "MAILCC", "model_ver",
}

# HOMEmodel pattern (HOMEgfs, HOMEobsproc, etc.)
HOME_MODEL_PATTERN = re.compile(r'^HOME[a-z][a-z_]*$')

# Variables to skip (shell builtins, loop vars, etc.)
SKIP_VARS = {
    "PATH", "HOME", "USER", "SHELL", "TERM", "LANG", "LC_ALL",
    "PWD", "OLDPWD", "HOSTNAME", "LOGNAME", "MAIL", "EDITOR",
    "TMPDIR", "TMP", "TEMP", "IFS", "PS1", "PS2", "PS4",
    "BASH_SOURCE", "BASH_LINENO", "FUNCNAME", "LINENO",
    "PIPESTATUS", "RANDOM", "SECONDS", "SHLVL", "PPID",
    "OPTARG", "OPTIND", "OPTERR", "REPLY",
    # Common shell keywords/builtins that look like vars
    "if", "fi", "do", "in", "then", "else", "elif", "esac", "done",
    "for", "while", "case", "function", "local", "declare",
    "echo", "exit", "return", "shift", "set", "unset", "eval",
    "true", "false", "test", "read", "trap", "wait", "source",
    # Single-letter vars (loop counters, both cases)
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
}

# Minimum variable name length
MIN_VAR_LENGTH = 2


# ===========================================================================
# Regex patterns for shell env var extraction
# ===========================================================================

# export VAR=value or export VAR (mixed case: HOMEgfs, envir, cyc)
RE_EXPORT = re.compile(
    r'^\s*export\s+([A-Za-z_][A-Za-z0-9_]{1,})\s*(?:=\s*(.*))?$',
    re.MULTILINE
)

# VAR=value (assignment without export, at start of line or after ;)
RE_ASSIGN = re.compile(
    r'(?:^|;\s*)([A-Za-z_][A-Za-z0-9_]{1,})\s*=\s*(?:\$\{[^}]+:-)?([^\s;#]*)',
    re.MULTILINE
)

# ${VAR} usage (mixed case)
RE_USAGE_BRACED = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]{1,})(?:[:#%/].*?)?\}')

# $VAR usage (bare, not inside braces, mixed case)
RE_USAGE_BARE = re.compile(r'(?<!\$)\$([A-Za-z_][A-Za-z0-9_]{1,})(?=[^A-Za-z0-9_{]|$)')


# ===========================================================================
# Parser
# ===========================================================================

def classify_script(path_str):
    """Classify script type based on path convention."""
    p = path_str.lower()
    if "/jobs/" in p or "/dev/jobs/" in p:
        if Path(path_str).name.startswith("J"):
            return "j-job"
        return "job"
    if "/scripts/" in p:
        return "ex-script"
    if "/ush/" in p:
        return "ush"
    if "/parm/config/" in p:
        return "config"
    if "/env/" in p:
        return "env"
    if "/ecf/" in p:
        return "ecf"
    if "/ci/" in p:
        return "ci"
    return "other"


def parse_env_vars(file_path):
    """Parse a shell script for environment variable exports and usage.
    
    Returns:
        dict with keys: exports, assignments, usages, script_type
    """
    try:
        with open(file_path, "r", errors="replace") as f:
            content = f.read()
    except (IOError, OSError) as e:
        print(f"[WARN] Cannot read {file_path}: {e}")
        return None

    exports = {}     # var_name -> {line, value}
    assignments = {} # var_name -> {line, value}
    usages = set()   # set of var_names used

    lines = content.split("\n")

    for line_num, line in enumerate(lines, 1):
        # Skip comments
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        # Find exports: export VAR=value
        for match in RE_EXPORT.finditer(line):
            var_name = match.group(1)
            value = match.group(2) or ""
            value = value.strip().strip('"').strip("'")
            if var_name not in SKIP_VARS and len(var_name) >= MIN_VAR_LENGTH:
                exports[var_name] = {"line": line_num, "value": value[:200]}

        # Find assignments: VAR=value (only if not already in exports)
        for match in RE_ASSIGN.finditer(line):
            var_name = match.group(1)
            value = match.group(2) or ""
            value = value.strip().strip('"').strip("'")
            if (var_name not in SKIP_VARS and 
                var_name not in exports and 
                len(var_name) >= MIN_VAR_LENGTH):
                assignments[var_name] = {"line": line_num, "value": value[:200]}

        # Find usage: ${VAR} and $VAR
        for match in RE_USAGE_BRACED.finditer(line):
            var_name = match.group(1)
            if var_name not in SKIP_VARS and len(var_name) >= MIN_VAR_LENGTH:
                usages.add(var_name)

        for match in RE_USAGE_BARE.finditer(line):
            var_name = match.group(1)
            if var_name not in SKIP_VARS and len(var_name) >= MIN_VAR_LENGTH:
                usages.add(var_name)

    # Remove vars that are exported/assigned from usage (self-references)
    # Keep them if they're also used elsewhere, but don't double-count
    # Actually, a script can both export and use a var, so keep usages

    rel_path = os.path.relpath(file_path, WORKFLOW_ROOT)
    script_type = classify_script(rel_path)

    return {
        "file_path": file_path,
        "rel_path": rel_path,
        "script_name": Path(file_path).name,
        "script_type": script_type,
        "exports": exports,
        "assignments": assignments,
        "usages": usages,
    }


# ===========================================================================
# Neo4j Ingestion
# ===========================================================================

def create_constraints(tx):
    """Create uniqueness constraints for EnvironmentVariable nodes.
    
    Skipped on Neptune (DB_BACKEND=aws) — Neptune auto-indexes all properties
    and does not support CREATE CONSTRAINT syntax.
    """
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (e:EnvironmentVariable) REQUIRE e.name IS UNIQUE")


def ingest_script(tx, parsed):
    """Create EnvironmentVariable nodes and relationships for one script."""
    file_path = parsed["file_path"]
    script_name = parsed["script_name"]
    script_type = parsed["script_type"]
    rel_path = parsed["rel_path"]
    
    counts = {"exports": 0, "sets": 0, "depends": 0}

    # Ensure CodeFile node exists for this script
    tx.run("""
        MERGE (f:CodeFile {path: $path})
        SET f.language = 'shell',
            f.script_type = $script_type,
            f.name = $name
    """, path=file_path, script_type=script_type, name=script_name)

    # Create EXPORTS relationships
    for var_name, info in parsed["exports"].items():
        is_ee2 = var_name in EE2_STANDARD_VARS
        is_home = bool(HOME_MODEL_PATTERN.match(var_name))
        
        tx.run("""
            MERGE (e:EnvironmentVariable {name: $var_name})
            ON CREATE SET e.is_ee2_standard = $is_ee2,
                          e.is_home_model = $is_home,
                          e.first_seen_in = $rel_path
            WITH e
            MATCH (f:CodeFile {path: $file_path})
            MERGE (f)-[r:EXPORTS]->(e)
            SET r.line = $line,
                r.value = $value
        """, var_name=var_name, is_ee2=is_ee2, is_home=is_home,
             rel_path=rel_path, file_path=file_path,
             line=info["line"], value=info["value"])
        counts["exports"] += 1

    # Create SETS relationships (assignment without export)
    for var_name, info in parsed["assignments"].items():
        is_ee2 = var_name in EE2_STANDARD_VARS
        is_home = bool(HOME_MODEL_PATTERN.match(var_name))

        tx.run("""
            MERGE (e:EnvironmentVariable {name: $var_name})
            ON CREATE SET e.is_ee2_standard = $is_ee2,
                          e.is_home_model = $is_home,
                          e.first_seen_in = $rel_path
            WITH e
            MATCH (f:CodeFile {path: $file_path})
            MERGE (f)-[r:SETS]->(e)
            SET r.line = $line,
                r.value = $value
        """, var_name=var_name, is_ee2=is_ee2, is_home=is_home,
             rel_path=rel_path, file_path=file_path,
             line=info["line"], value=info["value"])
        counts["sets"] += 1

    # Create DEPENDS_ON_ENV relationships
    for var_name in parsed["usages"]:
        is_ee2 = var_name in EE2_STANDARD_VARS
        is_home = bool(HOME_MODEL_PATTERN.match(var_name))

        tx.run("""
            MERGE (e:EnvironmentVariable {name: $var_name})
            ON CREATE SET e.is_ee2_standard = $is_ee2,
                          e.is_home_model = $is_home,
                          e.first_seen_in = $rel_path
            WITH e
            MATCH (f:CodeFile {path: $file_path})
            MERGE (f)-[r:DEPENDS_ON_ENV]->(e)
        """, var_name=var_name, is_ee2=is_ee2, is_home=is_home,
             rel_path=rel_path, file_path=file_path)
        counts["depends"] += 1

    return counts


# ===========================================================================
# File discovery
# ===========================================================================

def find_shell_scripts():
    """Find all shell scripts in configured directories."""
    scripts = []
    for scan_dir in SCAN_DIRS:
        full_dir = os.path.join(WORKFLOW_ROOT, scan_dir)
        if not os.path.isdir(full_dir):
            continue
        for pattern in FILE_PATTERNS:
            for f in glob.glob(os.path.join(full_dir, "**", pattern), recursive=True):
                scripts.append(f)
        # Also find extensionless J-jobs in dev/jobs/ and jobs/
        if "jobs" in scan_dir:
            for f in glob.glob(os.path.join(full_dir, "J*")):
                if os.path.isfile(f) and not os.path.splitext(f)[1]:
                    scripts.append(f)
    
    return sorted(set(scripts))


# ===========================================================================
# Query mode
# ===========================================================================

def query_variable(driver, var_name):
    """Query a specific environment variable from the graph."""
    with driver.session() as session:
        # Exporters
        exporters = session.run("""
            MATCH (f:CodeFile)-[r:EXPORTS]->(e:EnvironmentVariable {name: $name})
            RETURN f.path AS path, f.script_type AS type, r.line AS line, r.value AS value
            ORDER BY f.script_type, f.path
        """, name=var_name).data()

        # Setters
        setters = session.run("""
            MATCH (f:CodeFile)-[r:SETS]->(e:EnvironmentVariable {name: $name})
            RETURN f.path AS path, f.script_type AS type, r.line AS line, r.value AS value
            ORDER BY f.script_type, f.path
        """, name=var_name).data()

        # Dependents
        dependents = session.run("""
            MATCH (f:CodeFile)-[:DEPENDS_ON_ENV]->(e:EnvironmentVariable {name: $name})
            RETURN f.path AS path, f.script_type AS type
            ORDER BY f.script_type, f.path
        """, name=var_name).data()

        # Variable metadata
        meta = session.run("""
            MATCH (e:EnvironmentVariable {name: $name})
            RETURN e.is_ee2_standard AS ee2, e.is_home_model AS home, e.first_seen_in AS first_seen
        """, name=var_name).data()

    print(f"\n{'='*60}")
    print(f" Environment Variable: {var_name}")
    print(f"{'='*60}")
    
    if meta:
        m = meta[0]
        tags = []
        if m.get("ee2"): tags.append("EE2-Standard")
        if m.get("home"): tags.append("HOMEmodel")
        print(f" Tags: {', '.join(tags) if tags else 'none'}")
        print(f" First seen: {m.get('first_seen', 'unknown')}")
    
    print(f"\n Exported by ({len(exporters)} scripts):")
    for e in exporters:
        val = f" = {e['value']}" if e.get('value') else ""
        print(f"   [{e.get('type','?'):10s}] {os.path.basename(e['path'])}:{e.get('line','?')}{val}")
    
    print(f"\n Set by ({len(setters)} scripts):")
    for s in setters:
        val = f" = {s['value']}" if s.get('value') else ""
        print(f"   [{s.get('type','?'):10s}] {os.path.basename(s['path'])}:{s.get('line','?')}{val}")
    
    print(f"\n Used by ({len(dependents)} scripts):")
    by_type = defaultdict(list)
    for d in dependents:
        by_type[d.get("type", "other")].append(d)
    for t, scripts in sorted(by_type.items()):
        print(f"   {t} ({len(scripts)}):")
        for s in scripts[:10]:
            print(f"     - {os.path.basename(s['path'])}")
        if len(scripts) > 10:
            print(f"     ... and {len(scripts) - 10} more")
    
    print(f"\n Impact: {len(dependents)} scripts depend on this variable")
    print()


# ===========================================================================
# Main
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="Ingest environment variables into Neo4j")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no Neo4j writes")
    parser.add_argument("--test", type=str, help="Test single file")
    parser.add_argument("--sample", action="store_true", help="Process first 20 files")
    parser.add_argument("--var", type=str, help="Query mode: show info for a variable")
    parser.add_argument("--stats", action="store_true", help="Show current graph statistics")
    args = parser.parse_args()

    # Connect to Neo4j
    driver = (_get_graph_driver() if _AWS_BACKEND_AVAILABLE and _BACKEND == "aws"
              else GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)))
    
    try:
        driver.verify_connectivity()
        print(f"[OK] Connected to Neo4j at {NEO4J_URI}")
    except Exception as e:
        print(f"[ERROR] Cannot connect to Neo4j: {e}")
        sys.exit(1)

    # Query mode
    if args.var:
        query_variable(driver, args.var)
        driver.close()
        return

    # Stats mode
    if args.stats:
        with driver.session() as session:
            ev_count = session.run("MATCH (e:EnvironmentVariable) RETURN count(e) AS cnt").single()["cnt"]
            exp_count = session.run("MATCH ()-[r:EXPORTS]->() RETURN count(r) AS cnt").single()["cnt"]
            dep_count = session.run("MATCH ()-[r:DEPENDS_ON_ENV]->() RETURN count(r) AS cnt").single()["cnt"]
            set_count = session.run("MATCH ()-[r:SETS]->() RETURN count(r) AS cnt").single()["cnt"]
            ee2_count = session.run("MATCH (e:EnvironmentVariable {is_ee2_standard: true}) RETURN count(e) AS cnt").single()["cnt"]
        print(f"\n  EnvironmentVariable nodes: {ev_count}")
        print(f"  EE2 standard variables:    {ee2_count}")
        print(f"  EXPORTS relationships:     {exp_count}")
        print(f"  SETS relationships:        {set_count}")
        print(f"  DEPENDS_ON_ENV rels:       {dep_count}")
        print()
        driver.close()
        return

    # Find scripts
    if args.test:
        scripts = [args.test]
    else:
        scripts = find_shell_scripts()
        if args.sample:
            scripts = scripts[:20]

    print(f"[OK] Found {len(scripts)} shell scripts to process")

    # Parse all scripts
    all_parsed = []
    total_exports = 0
    total_assigns = 0
    total_usages = 0
    all_vars = set()

    for script in scripts:
        parsed = parse_env_vars(script)
        if parsed is None:
            continue
        all_parsed.append(parsed)
        total_exports += len(parsed["exports"])
        total_assigns += len(parsed["assignments"])
        total_usages += len(parsed["usages"])
        all_vars.update(parsed["exports"].keys())
        all_vars.update(parsed["assignments"].keys())
        all_vars.update(parsed["usages"])

    print(f"[OK] Parsed {len(all_parsed)} scripts")
    print(f"     Unique variables: {len(all_vars)}")
    print(f"     Export statements: {total_exports}")
    print(f"     Assignments: {total_assigns}")
    print(f"     Usages (${{}}/$ refs): {total_usages}")

    # Show top variables
    var_counts = defaultdict(int)
    for p in all_parsed:
        for v in p["exports"]:
            var_counts[v] += 1
        for v in p["assignments"]:
            var_counts[v] += 1
        for v in p["usages"]:
            var_counts[v] += 1
    
    top_vars = sorted(var_counts.items(), key=lambda x: -x[1])[:15]
    print(f"\n     Top 15 variables:")
    for var, cnt in top_vars:
        ee2 = " [EE2]" if var in EE2_STANDARD_VARS else ""
        home = " [HOME]" if HOME_MODEL_PATTERN.match(var) else ""
        print(f"       {cnt:4d}x  {var}{ee2}{home}")

    if args.dry_run:
        print(f"\n[DRY-RUN] Would create {len(all_vars)} EnvironmentVariable nodes")
        print(f"[DRY-RUN] Would create ~{total_exports} EXPORTS relationships")
        print(f"[DRY-RUN] Would create ~{total_assigns} SETS relationships")
        print(f"[DRY-RUN] Would create ~{total_usages} DEPENDS_ON_ENV relationships")
        driver.close()
        return

    # Ingest to Neo4j
    print(f"\n[OK] Starting Neo4j ingestion...")
    
    with driver.session() as session:
        # Create constraints (skip on Neptune — auto-indexes all properties)
        if _AWS_BACKEND_AVAILABLE and _BACKEND == "aws":
            print("[OK] Skipping constraint creation (Neptune auto-indexes all properties)")
        else:
            session.execute_write(create_constraints)
            print("[OK] Constraints created")

        # Ingest each script
        total_counts = {"exports": 0, "sets": 0, "depends": 0}
        for i, parsed in enumerate(all_parsed):
            if _AWS_BACKEND_AVAILABLE and _BACKEND == "aws":
                # Neptune adapter: call ingest_script directly with session
                counts = ingest_script(session, parsed)
            else:
                counts = session.execute_write(ingest_script, parsed)
            total_counts["exports"] += counts["exports"]
            total_counts["sets"] += counts["sets"]
            total_counts["depends"] += counts["depends"]
            
            if (i + 1) % 25 == 0 or (i + 1) == len(all_parsed):
                print(f"  [{i+1}/{len(all_parsed)}] Processed {parsed['script_name']}")

    # Final stats
    with driver.session() as session:
        ev_count = session.run("MATCH (e:EnvironmentVariable) RETURN count(e) AS cnt").single()["cnt"]
        ee2_count = session.run("MATCH (e:EnvironmentVariable {is_ee2_standard: true}) RETURN count(e) AS cnt").single()["cnt"]
        home_count = session.run("MATCH (e:EnvironmentVariable {is_home_model: true}) RETURN count(e) AS cnt").single()["cnt"]

    print(f"\n{'='*60}")
    print(f" Ingestion Complete")
    print(f"{'='*60}")
    print(f" EnvironmentVariable nodes: {ev_count}")
    print(f"   EE2 standard:           {ee2_count}")
    print(f"   HOMEmodel pattern:      {home_count}")
    print(f" EXPORTS relationships:    {total_counts['exports']}")
    print(f" SETS relationships:       {total_counts['sets']}")
    print(f" DEPENDS_ON_ENV rels:      {total_counts['depends']}")
    print(f"{'='*60}")

    driver.close()
    print("[OK] Done")


if __name__ == "__main__":
    main()
