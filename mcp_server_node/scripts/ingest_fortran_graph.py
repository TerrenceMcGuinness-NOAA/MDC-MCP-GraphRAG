#!/usr/bin/env python3
"""
Phase 10: Fortran Call Graph Ingestion for Neo4j
Extract CALL/USE relationships from Fortran sources using fparser2

This script creates a comprehensive graph of Fortran code structure:
- Modules, Subroutines, Functions, Programs
- CALL statements with caller context
- USE statements with module dependencies

Neo4j Schema:
  (:FortranModule {name, file_path, line_start})
  (:FortranSubroutine {name, file_path, line_start, parent_module})
  (:FortranFunction {name, file_path, line_start, return_type, parent_module})
  (:FortranProgram {name, file_path, executable_name})
  
  (caller)-[:CALLS {line}]->(callee:FortranSubroutine)
  (code)-[:USES {only}]->(module:FortranModule)
  (module)-[:CONTAINS]->(subroutine|function)
  (shell:ShellScript)-[:EXECUTES]->(program:FortranProgram)

Author: NOAA EMC Global Workflow MCP Team
Version: 1.0.0
Phase: 10 (Milestone 2)
Date: February 5, 2026

Key Discovery (M1):
  MUST use FortranFileReader - passing raw strings to parser fails on most files.
  
Usage:
  # Test single file
  python ingest_fortran_graph.py --test /path/to/file.F90
  
  # Dry run (no Neo4j writes)
  python ingest_fortran_graph.py --dry-run
  
  # Full ingestion
  python ingest_fortran_graph.py
  
  # Phase 34: Ingest an external NCEPLIBS repo
  python ingest_fortran_graph.py --repo-name nceplibs-bufr --root-dir ../supported_repos/nceplibs/NCEPLIBS-bufr
"""

import os
import sys
import argparse
import json
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any
from collections import defaultdict
from datetime import datetime

# fparser2 imports - loaded via Spack (module load py-fparser)
try:
    from fparser.common.readfortran import FortranFileReader
    from fparser.two.parser import ParserFactory
    from fparser.two.utils import walk
    from fparser.two import Fortran2003 as f2003
except ImportError:
    print("[ERROR] fparser package not found.")
    print("       Load via Spack: source mcp-env.sh && module load py-fparser")
    sys.exit(1)

try:
    from neo4j import GraphDatabase
except ImportError:
    print("[WARN] neo4j package not found. Neo4j ingestion disabled.")
    GraphDatabase = None


# ============================================================================
# CONFIGURATION
# ============================================================================

VERSION = "1.1.0"
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "gfsworkflow2025")

WORKFLOW_ROOT = os.getenv("WORKFLOW_ROOT", 
    "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow")

# Fortran file extensions to process
FORTRAN_EXTENSIONS = {'.F90', '.f90', '.F', '.f', '.F95', '.f95', '.F03', '.f03', '.F08', '.f08'}

# Directories containing Fortran source code
FORTRAN_DIRECTORIES = [
    'sorc',           # Main source directory
    'ush',            # May contain Fortran utilities
]

# External submodule paths (relative to WORKFLOW_ROOT)
SUBMODULE_PATHS = [
    'sorc/ufs_model.fd',
    'sorc/gsi.fd',
    'sorc/gdas.fd',
    'sorc/ufs_utils.fd',
    'sorc/gfs_wafs.fd',
    'sorc/fit2obs.fd',
]


# ============================================================================
# FORTRAN PARSER
# ============================================================================

class FortranParser:
    """Parse Fortran files using fparser2 with FortranFileReader."""
    
    def __init__(self):
        """Initialize the parser factory."""
        self.parser = ParserFactory().create(std='f2003')
        self.stats = {
            'files_processed': 0,
            'files_failed': 0,
            'modules': 0,
            'subroutines': 0,
            'functions': 0,
            'programs': 0,
            'calls': 0,
            'uses': 0,
        }
        self.errors = []
    
    def parse_file(self, filepath: str) -> Optional[Dict[str, Any]]:
        """
        Parse a Fortran file and extract AST structure.
        
        Key: Uses FortranFileReader instead of raw string (critical for success).
        """
        try:
            # CRITICAL: Use FortranFileReader, NOT raw file content
            reader = FortranFileReader(filepath, ignore_comments=True)
            tree = self.parser(reader)
            
            if tree is None:
                self.stats['files_failed'] += 1
                self.errors.append({'file': filepath, 'error': 'Parser returned None'})
                return None
            
            result = self._extract_structure(tree, filepath)
            self.stats['files_processed'] += 1
            return result
            
        except Exception as e:
            self.stats['files_failed'] += 1
            self.errors.append({'file': filepath, 'error': str(e)})
            return None
    
    def _extract_structure(self, tree, filepath: str) -> Dict[str, Any]:
        """Extract modules, subroutines, functions, calls, uses from AST."""
        result = {
            'file': filepath,
            'relative_path': self._relative_path(filepath),
            'modules': [],
            'subroutines': [],
            'functions': [],
            'programs': [],
            'calls': [],
            'uses': [],
        }
        
        # Track current context for caller attribution
        current_module = None
        current_subprogram = None
        
        # First pass: Extract all container nodes (modules, subroutines, functions, programs)
        
        # Extract modules
        for node in walk(tree, f2003.Module_Stmt):
            try:
                name = str(node.items[1]).strip()
                line = getattr(node, 'item', None)
                line_num = line.span[0] if hasattr(line, 'span') else None
                result['modules'].append({
                    'name': name,
                    'line_start': line_num,
                })
                self.stats['modules'] += 1
            except Exception:
                pass
        
        # Extract subroutines
        for node in walk(tree, f2003.Subroutine_Stmt):
            try:
                name = str(node.items[1]).strip()
                line = getattr(node, 'item', None)
                line_num = line.span[0] if hasattr(line, 'span') else None
                result['subroutines'].append({
                    'name': name,
                    'line_start': line_num,
                    'parent_module': None,  # Will be resolved in context pass
                })
                self.stats['subroutines'] += 1
            except Exception:
                pass
        
        # Extract functions
        for node in walk(tree, f2003.Function_Stmt):
            try:
                # Function name is in items[1] for most cases
                name = str(node.items[1]).strip() if node.items[1] else 'unknown'
                line = getattr(node, 'item', None)
                line_num = line.span[0] if hasattr(line, 'span') else None
                result['functions'].append({
                    'name': name,
                    'line_start': line_num,
                    'parent_module': None,
                })
                self.stats['functions'] += 1
            except Exception:
                pass
        
        # Extract programs
        for node in walk(tree, f2003.Program_Stmt):
            try:
                name = str(node.items[1]).strip() if node.items[1] else 'MAIN'
                result['programs'].append({
                    'name': name,
                    'executable_name': self._infer_executable(filepath, name),
                })
                self.stats['programs'] += 1
            except Exception:
                pass
        
        # Extract CALL statements
        for node in walk(tree, f2003.Call_Stmt):
            try:
                # Call target is in items[0] (Procedure_Designator or Name)
                callee = str(node.items[0]).strip()
                # Clean up any argument list that might be included
                if '(' in callee:
                    callee = callee.split('(')[0].strip()
                line = getattr(node, 'item', None)
                line_num = line.span[0] if hasattr(line, 'span') else None
                result['calls'].append({
                    'callee': callee,
                    'line': line_num,
                    'caller': None,  # Will be resolved if we track context
                })
                self.stats['calls'] += 1
            except Exception:
                pass
        
        # Extract USE statements
        for node in walk(tree, f2003.Use_Stmt):
            try:
                # Module name is typically in items[2]
                module_name = str(node.items[2]).strip() if node.items[2] else None
                if not module_name:
                    continue
                # Check for ONLY clause
                only_list = None
                if len(node.items) > 4 and node.items[4]:
                    only_list = str(node.items[4])
                result['uses'].append({
                    'module': module_name,
                    'only': only_list,
                })
                self.stats['uses'] += 1
            except Exception:
                pass
        
        return result
    
    def _relative_path(self, filepath: str) -> str:
        """Get path relative to WORKFLOW_ROOT."""
        try:
            return os.path.relpath(filepath, WORKFLOW_ROOT)
        except ValueError:
            return filepath
    
    def _infer_executable(self, filepath: str, program_name: str) -> Optional[str]:
        """
        Infer executable name from file path.
        
        Pattern: sorc/X.fd/X → executable X
        Example: sorc/ufs_model.fd/... → ufs_model.x
        """
        parts = Path(filepath).parts
        for i, part in enumerate(parts):
            if part.endswith('.fd'):
                exe_name = part.replace('.fd', '')
                return f"{exe_name}.x"
        return None
    
    def get_summary(self) -> Dict[str, Any]:
        """Get parsing statistics summary."""
        total = self.stats['files_processed'] + self.stats['files_failed']
        success_rate = (self.stats['files_processed'] / total * 100) if total > 0 else 0
        return {
            'version': VERSION,
            'timestamp': datetime.now().isoformat(),
            'files': {
                'processed': self.stats['files_processed'],
                'failed': self.stats['files_failed'],
                'success_rate': f"{success_rate:.1f}%",
            },
            'entities': {
                'modules': self.stats['modules'],
                'subroutines': self.stats['subroutines'],
                'functions': self.stats['functions'],
                'programs': self.stats['programs'],
            },
            'relationships': {
                'calls': self.stats['calls'],
                'uses': self.stats['uses'],
            },
            'error_count': len(self.errors),
        }


# ============================================================================
# FILE DISCOVERY
# ============================================================================

def find_fortran_files(root_path: str, extensions: Set[str] = FORTRAN_EXTENSIONS) -> List[str]:
    """
    Find all Fortran source files under root_path.
    
    Returns list of absolute file paths.
    """
    files = []
    root = Path(root_path)
    
    if not root.exists():
        print(f"[WARN] Path does not exist: {root_path}")
        return files
    
    for ext in extensions:
        # Handle both cases: .F90 and .f90
        files.extend(str(p) for p in root.rglob(f"*{ext}"))
    
    return sorted(set(files))


# ============================================================================
# NEO4J INGESTION
# ============================================================================

class Neo4jIngester:
    """Ingest Fortran parse results into Neo4j graph database."""
    
    def __init__(self, uri: str, user: str, password: str, dry_run: bool = False):
        """Initialize Neo4j connection."""
        self.dry_run = dry_run
        self.driver = None
        
        if not dry_run and GraphDatabase:
            try:
                self.driver = GraphDatabase.driver(uri, auth=(user, password))
                # Test connection
                with self.driver.session() as session:
                    session.run("RETURN 1")
                print(f"[OK] Connected to Neo4j at {uri}")
            except Exception as e:
                print(f"[ERROR] Neo4j connection failed: {e}")
                self.driver = None
    
    def create_indexes(self):
        """Create indexes for Fortran nodes."""
        if self.dry_run or not self.driver:
            print("[DRY-RUN] Would create indexes for FortranModule, FortranSubroutine, etc.")
            return
        
        indexes = [
            "CREATE INDEX IF NOT EXISTS FOR (m:FortranModule) ON (m.name)",
            "CREATE INDEX IF NOT EXISTS FOR (s:FortranSubroutine) ON (s.name)",
            "CREATE INDEX IF NOT EXISTS FOR (f:FortranFunction) ON (f.name)",
            "CREATE INDEX IF NOT EXISTS FOR (p:FortranProgram) ON (p.name)",
        ]
        
        with self.driver.session() as session:
            for idx in indexes:
                try:
                    session.run(idx)
                except Exception as e:
                    print(f"[WARN] Index creation: {e}")
        
        print("[OK] Neo4j indexes created")
    
    def ingest_file_result(self, result: Dict[str, Any], repo_name: str = None) -> Dict[str, int]:
        """
        Ingest a single file's parse result into Neo4j.
        
        Args:
            result: Parsed file structure from FortranParser.
            repo_name: Optional repo tag (e.g., 'nceplibs-bufr') for multi-repo support.
        
        Returns counts of nodes/relationships created.
        """
        counts = {'nodes': 0, 'relationships': 0}
        
        if self.dry_run or not self.driver:
            # Count what would be created
            counts['nodes'] = (
                len(result.get('modules', [])) +
                len(result.get('subroutines', [])) +
                len(result.get('functions', [])) +
                len(result.get('programs', []))
            )
            counts['relationships'] = (
                len(result.get('calls', [])) +
                len(result.get('uses', []))
            )
            return counts
        
        file_path = result['file']
        rel_path = result.get('relative_path', file_path)
        
        # Build optional repo SET clause for multi-repo tagging (Phase 34)
        repo_set = ", n.repo = $repo" if repo_name else ""
        repo_params = {'repo': repo_name} if repo_name else {}
        
        with self.driver.session() as session:
            # Create Module nodes
            for mod in result.get('modules', []):
                session.run(f"""
                    MERGE (n:FortranModule {{name: $name}})
                    SET n.file_path = $file_path,
                        n.line_start = $line_start{repo_set}
                """, name=mod['name'], file_path=rel_path, line_start=mod.get('line_start'), **repo_params)
                counts['nodes'] += 1
            
            # Create Subroutine nodes
            for sub in result.get('subroutines', []):
                session.run(f"""
                    MERGE (n:FortranSubroutine {{name: $name, file_path: $file_path}})
                    SET n.line_start = $line_start{repo_set}
                """, name=sub['name'], file_path=rel_path, line_start=sub.get('line_start'), **repo_params)
                counts['nodes'] += 1
            
            # Create Function nodes
            for func in result.get('functions', []):
                session.run(f"""
                    MERGE (n:FortranFunction {{name: $name, file_path: $file_path}})
                    SET n.line_start = $line_start{repo_set}
                """, name=func['name'], file_path=rel_path, line_start=func.get('line_start'), **repo_params)
                counts['nodes'] += 1
            
            # Create Program nodes
            for prog in result.get('programs', []):
                session.run(f"""
                    MERGE (n:FortranProgram {{name: $name}})
                    SET n.file_path = $file_path,
                        n.executable_name = $exe_name{repo_set}
                """, name=prog['name'], file_path=rel_path, exe_name=prog.get('executable_name'), **repo_params)
                counts['nodes'] += 1
            
            # Create CALLS relationships
            # For now, create placeholder callee nodes if they don't exist
            for call in result.get('calls', []):
                session.run("""
                    MERGE (callee:FortranSubroutine {name: $callee_name})
                    WITH callee
                    MATCH (caller) WHERE caller.file_path = $file_path
                      AND (caller:FortranSubroutine OR caller:FortranFunction OR caller:FortranProgram)
                    MERGE (caller)-[r:CALLS]->(callee)
                    SET r.line = $line, r.source_file = $file_path
                """, callee_name=call['callee'], file_path=rel_path, line=call.get('line'))
                counts['relationships'] += 1
            
            # Create USES relationships
            for use in result.get('uses', []):
                session.run("""
                    MERGE (mod:FortranModule {name: $module_name})
                    WITH mod
                    MATCH (user) WHERE user.file_path = $file_path
                    MERGE (user)-[r:USES]->(mod)
                    SET r.only = $only_clause
                """, module_name=use['module'], file_path=rel_path, only_clause=use.get('only'))
                counts['relationships'] += 1
        
        return counts
    
    def close(self):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def test_single_file(filepath: str, verbose: bool = True) -> Dict[str, Any]:
    """Test parsing a single Fortran file."""
    parser = FortranParser()
    result = parser.parse_file(filepath)
    
    if result:
        if verbose:
            print(f"\n[OK] Parsed: {filepath}")
            print(f"    Modules:     {len(result['modules'])}")
            print(f"    Subroutines: {len(result['subroutines'])}")
            print(f"    Functions:   {len(result['functions'])}")
            print(f"    Programs:    {len(result['programs'])}")
            print(f"    CALL stmts:  {len(result['calls'])}")
            print(f"    USE stmts:   {len(result['uses'])}")
            
            if result['modules']:
                print(f"\n    Modules: {[m['name'] for m in result['modules']]}")
            if result['subroutines'][:5]:
                print(f"    Subroutines (first 5): {[s['name'] for s in result['subroutines'][:5]]}")
            if result['calls'][:5]:
                print(f"    Calls (first 5): {[c['callee'] for c in result['calls'][:5]]}")
            if result['uses'][:5]:
                print(f"    Uses (first 5): {[u['module'] for u in result['uses'][:5]]}")
    else:
        if verbose:
            print(f"\n[ERROR] Failed to parse: {filepath}")
            if parser.errors:
                print(f"    Error: {parser.errors[-1]['error']}")
    
    return result


def run_sample_test(sample_size: int = 100):
    """Run parsing on a sample of files to validate success rate."""
    print(f"\n{'='*60}")
    print(f"Phase 10 Milestone 2: Sample Validation Test")
    print(f"{'='*60}")
    
    # Find files
    files = find_fortran_files(WORKFLOW_ROOT)
    print(f"\n[INFO] Found {len(files)} Fortran files in {WORKFLOW_ROOT}")
    
    if not files:
        print("[ERROR] No Fortran files found!")
        return
    
    # Take sample
    import random
    sample = random.sample(files, min(sample_size, len(files)))
    print(f"[INFO] Testing sample of {len(sample)} files...")
    
    parser = FortranParser()
    
    for filepath in sample:
        parser.parse_file(filepath)
    
    # Report
    summary = parser.get_summary()
    print(f"\n{'='*60}")
    print("Results:")
    print(f"{'='*60}")
    print(f"  Files processed: {summary['files']['processed']}")
    print(f"  Files failed:    {summary['files']['failed']}")
    print(f"  Success rate:    {summary['files']['success_rate']}")
    print(f"\nEntities extracted:")
    print(f"  Modules:     {summary['entities']['modules']}")
    print(f"  Subroutines: {summary['entities']['subroutines']}")
    print(f"  Functions:   {summary['entities']['functions']}")
    print(f"  Programs:    {summary['entities']['programs']}")
    print(f"\nRelationships:")
    print(f"  CALLS: {summary['relationships']['calls']}")
    print(f"  USES:  {summary['relationships']['uses']}")
    
    # Projections
    total_files = len(files)
    success_count = summary['files']['processed']
    if success_count > 0:
        calls_per_file = summary['relationships']['calls'] / success_count
        uses_per_file = summary['relationships']['uses'] / success_count
        projected_calls = int(calls_per_file * total_files * 0.85)  # Assume 85% success
        projected_uses = int(uses_per_file * total_files * 0.85)
        print(f"\nProjected for all {total_files} files:")
        print(f"  CALLS: ~{projected_calls:,}")
        print(f"  USES:  ~{projected_uses:,}")


def run_full_ingestion(dry_run: bool = False, repo_name: str = None):
    """Run full ingestion of all Fortran files to Neo4j."""
    print(f"\n{'='*60}")
    print(f"Phase 10: Full Fortran Graph Ingestion")
    if repo_name:
        print(f"Repository: {repo_name}")
    print(f"{'='*60}")
    print(f"Mode: {'DRY-RUN (no Neo4j writes)' if dry_run else 'LIVE'}")
    
    # Find all files
    files = find_fortran_files(WORKFLOW_ROOT)
    print(f"\n[INFO] Found {len(files)} Fortran files")
    
    if not files:
        print("[ERROR] No Fortran files found!")
        return
    
    # Initialize
    parser = FortranParser()
    ingester = Neo4jIngester(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, dry_run=dry_run)
    
    if not dry_run:
        ingester.create_indexes()
    
    total_nodes = 0
    total_rels = 0
    
    # Process files with progress
    print(f"\n[INFO] Processing files...")
    for i, filepath in enumerate(files):
        if (i + 1) % 500 == 0:
            print(f"  Progress: {i+1}/{len(files)} files...")
        
        result = parser.parse_file(filepath)
        if result:
            counts = ingester.ingest_file_result(result, repo_name=repo_name)
            total_nodes += counts['nodes']
            total_rels += counts['relationships']
    
    # Final summary
    summary = parser.get_summary()
    print(f"\n{'='*60}")
    print("Ingestion Complete")
    print(f"{'='*60}")
    print(f"  Files processed: {summary['files']['processed']}")
    print(f"  Files failed:    {summary['files']['failed']}")
    print(f"  Success rate:    {summary['files']['success_rate']}")
    print(f"\nNeo4j Graph:")
    print(f"  Nodes created:         {total_nodes:,}")
    print(f"  Relationships created: {total_rels:,}")
    print(f"\nEntity breakdown:")
    print(f"  Modules:     {summary['entities']['modules']}")
    print(f"  Subroutines: {summary['entities']['subroutines']}")
    print(f"  Functions:   {summary['entities']['functions']}")
    print(f"  Programs:    {summary['entities']['programs']}")
    print(f"  CALLS:       {summary['relationships']['calls']}")
    print(f"  USES:        {summary['relationships']['uses']}")
    
    if parser.errors and not dry_run:
        # Save errors to file
        error_file = Path(WORKFLOW_ROOT).parent / 'fortran_parse_errors.json'
        with open(error_file, 'w') as f:
            json.dump(parser.errors[:100], f, indent=2)  # Save first 100 errors
        print(f"\n[INFO] First 100 errors saved to: {error_file}")
    
    ingester.close()


def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        description="Phase 10: Fortran Call Graph Ingestion for Neo4j",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test single file
  python ingest_fortran_graph.py --test sorc/ufs_model.fd/FV3/atmos_cubed_sphere/model/fv_dynamics.F90
  
  # Run sample validation (100 files)
  python ingest_fortran_graph.py --sample
  
  # Dry run (no Neo4j writes)
  python ingest_fortran_graph.py --dry-run
  
  # Full ingestion
  python ingest_fortran_graph.py
        """
    )
    
    parser.add_argument('--test', '-t', metavar='FILE',
                        help='Test parsing a single Fortran file')
    parser.add_argument('--sample', '-s', action='store_true',
                        help='Run sample validation on 100 random files')
    parser.add_argument('--sample-size', type=int, default=100,
                        help='Number of files for sample validation')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Parse files but do not write to Neo4j')
    parser.add_argument('--repo-name', metavar='NAME',
                        help='Tag all nodes with this repo name (e.g., nceplibs-bufr)')
    parser.add_argument('--root-dir', metavar='DIR',
                        help='Root directory to scan instead of WORKFLOW_ROOT')
    parser.add_argument('--version', '-v', action='version',
                        version=f'%(prog)s {VERSION}')
    
    args = parser.parse_args()
    
    # Override WORKFLOW_ROOT if --root-dir is specified
    global WORKFLOW_ROOT
    if args.root_dir:
        WORKFLOW_ROOT = os.path.abspath(args.root_dir)
    
    print(f"Fortran Call Graph Ingestion v{VERSION}")
    print(f"WORKFLOW_ROOT: {WORKFLOW_ROOT}")
    if args.repo_name:
        print(f"REPO_NAME: {args.repo_name}")
    
    if args.test:
        test_single_file(args.test)
    elif args.sample:
        run_sample_test(args.sample_size)
    else:
        run_full_ingestion(dry_run=args.dry_run, repo_name=args.repo_name)


if __name__ == '__main__':
    main()
