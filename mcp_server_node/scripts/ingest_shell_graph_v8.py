#!/usr/bin/env python3
"""
Phase 27B: Shell Script Graph Ingestion for Neo4j
Full J-Job call tree with SOURCES, INVOKES, DEPENDS_ON_ENV relationships

This script creates a comprehensive graph of shell script relationships:
- J-Jobs (dev/jobs/) → ex-scripts relationship tracking
- Source file dependencies (source, .)
- Script invocations (${SCRIPT}/file.sh)
- Environment variable dependencies
- Configuration file reads

Neo4j Schema:
  (:ShellScript {name, path, type, category})
  (:EnvironmentVariable {name, default_value})
  (:ConfigFile {name, path})
  
  (script)-[:SOURCES]->(other_script)
  (script)-[:INVOKES]->(ex_script)
  (script)-[:READS_CONFIG]->(config)
  (script)-[:EXPORTS]->(env_var)
  (script)-[:DEPENDS_ON_ENV]->(env_var)

Author: NOAA EMC Global Workflow MCP Team
Version: 8.0.0
Date: February 5, 2026
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict
from datetime import datetime

try:
    from neo4j import GraphDatabase
except ImportError:
    print("[ERROR] neo4j package not found. Install: pip install neo4j")
    sys.exit(1)


# ============================================================================
# CONFIGURATION
# ============================================================================

VERSION = "8.0.0"
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "gfsworkflow2025")

WORKFLOW_ROOT = os.getenv("WORKFLOW_ROOT", 
    "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow")

# Script directories to scan
SCRIPT_DIRECTORIES = {
    'dev/jobs': 'j-job',
    'dev/scripts': 'ex-script', 
    'ush': 'ush-script',
    'scripts': 'legacy-script',
}

# Known external packages (scripts from external repos)
EXTERNAL_PACKAGES = {
    'SCRIPTSfit2obs': 'Fit2Obs',
    'SCRIPTSgfs_wafs': 'WAFS',
    'SCRIPTSprepobs': 'PrepObs',
    'SCRIPTSgldas': 'GLDAS',
    'SCRIPTSsnow': 'Snow',
    'HOMEgfs': 'GFS',
    'HOMEgdas': 'GDAS',
    'HOMEwave': 'Wave',
}


# ============================================================================
# SHELL SCRIPT PARSER
# ============================================================================

class ShellScriptParser:
    """Parse shell scripts for graph relationships"""
    
    def __init__(self):
        self.stats = defaultdict(int)
        
        # Regex patterns
        self.source_pattern = re.compile(
            r'(?:source|\.) +["\']?([^\s;|&"\']+/[^\s;|&"\']+|[^\s;|&"\']+\.(?:sh|bash|ksh|env|conf))["\']?',
            re.MULTILINE
        )
        self.invoke_pattern = re.compile(
            r'\$\{?(\w+)\}?/([^;\s\n"\']+\.sh)',
            re.MULTILINE
        )
        self.direct_invoke_pattern = re.compile(
            r'(?:^|\s)(?:\./|sh\s+|bash\s+)([^;\s\n"\']+\.sh)',
            re.MULTILINE
        )
        self.export_pattern = re.compile(
            r'^export\s+(\w+)=(.*)$',
            re.MULTILINE
        )
        self.env_use_pattern = re.compile(
            r'\$\{?(\w+)\}?'
        )
        self.function_pattern = re.compile(
            r'^(?:function\s+)?(\w+)\s*\(\s*\)\s*\{?',
            re.MULTILINE
        )
        self.config_pattern = re.compile(
            r'config\.(\w+)',
            re.MULTILINE
        )
        self.setobsenv_pattern = re.compile(
            r'setpdy\.sh|setup\.sh|machine\.sh|jjob_header\.sh',
            re.MULTILINE
        )
    
    def parse_script(self, file_path: str, content: str) -> Dict:
        """Parse a shell script and extract relationships"""
        
        result = {
            'path': file_path,
            'name': Path(file_path).name,
            'sources': [],
            'invokes': [],
            'exports': [],
            'env_deps': set(),
            'functions': [],
            'configs': [],
            'type': self._determine_type(file_path),
            'category': self._determine_category(file_path, content),
        }
        
        lines = content.split('\n')
        
        # Track line numbers for relationships
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # Skip comments
            if stripped.startswith('#'):
                continue
            
            # Source statements
            for match in self.source_pattern.finditer(line):
                source_path = match.group(1)
                # Post-filter: reject non-path matches
                if (source_path.startswith('-')
                        or source_path in ('*', '...')
                        or (source_path[0:1].isupper() and '/' not in source_path and '.' not in source_path)):
                    continue
                result['sources'].append({
                    'path': source_path,
                    'line': i,
                    'resolved': self._resolve_path(source_path)
                })
                self.stats['sources'] += 1
            
            # Script invocations via variable
            for match in self.invoke_pattern.finditer(line):
                var_name = match.group(1)
                script_name = match.group(2)
                result['invokes'].append({
                    'script': script_name,
                    'variable': var_name,
                    'line': i,
                    'package': EXTERNAL_PACKAGES.get(var_name, 'internal')
                })
                self.stats['invokes'] += 1
            
            # Direct script invocations
            for match in self.direct_invoke_pattern.finditer(line):
                script_name = match.group(1)
                if not script_name.startswith('$'):
                    result['invokes'].append({
                        'script': script_name,
                        'variable': None,
                        'line': i,
                        'package': 'internal'
                    })
                    self.stats['invokes'] += 1
            
            # Exports
            match = self.export_pattern.match(stripped)
            if match:
                var_name = match.group(1)
                var_value = match.group(2).strip('"\'')
                result['exports'].append({
                    'name': var_name,
                    'value': var_value[:200],  # Truncate long values
                    'line': i
                })
                self.stats['exports'] += 1
            
            # Config references
            for match in self.config_pattern.finditer(line):
                config_name = match.group(1)
                if config_name not in [c['name'] for c in result['configs']]:
                    result['configs'].append({
                        'name': config_name,
                        'line': i
                    })
                    self.stats['configs'] += 1
        
        # Function definitions (full scan)
        for match in self.function_pattern.finditer(content):
            func_name = match.group(1)
            if func_name not in ['if', 'while', 'for', 'case', 'then', 'else', 'fi', 'do', 'done']:
                result['functions'].append({
                    'name': func_name,
                    'line': content[:match.start()].count('\n') + 1
                })
                self.stats['functions'] += 1
        
        # Environment variable dependencies (unique set)
        for match in self.env_use_pattern.finditer(content):
            var_name = match.group(1)
            # Filter out common shell builtins
            if var_name not in ['HOME', 'PATH', 'PWD', 'USER', 'SHELL', 'TERM', 
                                '1', '2', '3', '4', '5', '6', '7', '8', '9', '0',
                                'i', 'j', 'n', 'x', 'y', 'z', 'file', 'line', 'err']:
                result['env_deps'].add(var_name)
        
        result['env_deps'] = list(result['env_deps'])
        self.stats['env_deps'] += len(result['env_deps'])
        
        return result
    
    def _determine_type(self, file_path: str) -> str:
        """Determine script type from path"""
        if 'dev/jobs' in file_path or file_path.startswith('J'):
            return 'j-job'
        elif 'dev/scripts' in file_path or file_path.startswith('ex'):
            return 'ex-script'
        elif 'ush' in file_path:
            return 'ush-script'
        elif 'parm' in file_path or 'config' in file_path:
            return 'config'
        else:
            return 'script'
    
    def _determine_category(self, file_path: str, content: str) -> str:
        """Determine operational category"""
        name = Path(file_path).name.upper()
        
        # Category detection from name patterns
        categories = {
            'FORECAST': ['FCST', 'FORECAST', 'FV3'],
            'analysis': ['ANAL', 'ANALYSIS', 'ENKF', 'ATMANL', 'AERO'],
            'verification': ['VRFY', 'FIT2OBS', 'VERFRAD', 'VERFOZN'],
            'archive': ['ARCH', 'ARCHIVE'],
            'preprocessing': ['PREP', 'OBSPROC', 'BUFR'],
            'postprocessing': ['POST', 'GEMPAK', 'AWIPS', 'GRIB'],
            'wave': ['WAVE', 'WW3'],
            'ocean': ['OCEAN', 'MOM6', 'CICE'],
            'aerosol': ['AERO', 'GOCART'],
            'land': ['LAND', 'NOAHMP'],
            'coupled': ['COUPLED', 'UFS'],
            'init': ['INIT', 'COLDSTART', 'WARMSTART'],
            'cleanup': ['CLEANUP', 'EARC'],
        }
        
        for category, patterns in categories.items():
            for pattern in patterns:
                if pattern in name:
                    return category
        
        return 'general'
    
    def _resolve_path(self, source_path: str) -> Optional[str]:
        """Try to resolve a source path to actual file"""
        # Handle variable paths
        if '$' in source_path:
            # Common resolutions
            resolutions = {
                '${USHgfs}': 'ush',
                '${HOMEgfs}': '',
                '${PARMgfs}': 'parm',
                '${SCRIPTSgfs}': 'dev/scripts',
                '${EXPDIR}': 'expdir',
            }
            for var, path in resolutions.items():
                if var in source_path:
                    return source_path.replace(var, path)
        
        return None


# ============================================================================
# NEO4J GRAPH CLIENT
# ============================================================================

class Neo4jGraphClient:
    """Neo4j client for shell script graph"""
    
    def __init__(self):
        try:
            self.driver = GraphDatabase.driver(
                NEO4J_URI,
                auth=(NEO4J_USER, NEO4J_PASSWORD),
                max_connection_lifetime=3600
            )
            # Test connection
            with self.driver.session() as session:
                session.run("RETURN 1")
            print(f"[OK] Connected to Neo4j: {NEO4J_URI}")
        except Exception as e:
            print(f"[ERROR] Neo4j connection failed: {e}")
            sys.exit(1)
    
    def close(self):
        if self.driver:
            self.driver.close()
    
    def clear_shell_graph(self):
        """Clear existing shell script graph (optional fresh start)"""
        queries = [
            "MATCH (s:ShellScript) DETACH DELETE s",
            "MATCH (e:EnvironmentVariable) DETACH DELETE e",
            "MATCH (c:ConfigFile) DETACH DELETE c",
            "MATCH (f:ShellFunction) DETACH DELETE f",
        ]
        with self.driver.session() as session:
            for query in queries:
                session.run(query)
        print("[OK] Cleared existing shell script graph")
    
    def create_indexes(self):
        """Create indexes for performance"""
        indexes = [
            "CREATE INDEX shell_script_name IF NOT EXISTS FOR (s:ShellScript) ON (s.name)",
            "CREATE INDEX shell_script_path IF NOT EXISTS FOR (s:ShellScript) ON (s.path)",
            "CREATE INDEX env_var_name IF NOT EXISTS FOR (e:EnvironmentVariable) ON (e.name)",
            "CREATE INDEX config_name IF NOT EXISTS FOR (c:ConfigFile) ON (c.name)",
            "CREATE INDEX shell_func_name IF NOT EXISTS FOR (f:ShellFunction) ON (f.name)",
        ]
        with self.driver.session() as session:
            for idx in indexes:
                try:
                    session.run(idx)
                except Exception:
                    pass  # Index may already exist
        print("[OK] Created Neo4j indexes")
    
    def create_script_node(self, script_data: Dict):
        """Create ShellScript node"""
        query = """
        MERGE (s:ShellScript {path: $path})
        SET s.name = $name,
            s.type = $type,
            s.category = $category,
            s.version = $version,
            s.updated_at = $updated_at,
            s.source_count = $source_count,
            s.invoke_count = $invoke_count,
            s.export_count = $export_count,
            s.function_count = $function_count
        """
        with self.driver.session() as session:
            session.run(query,
                path=script_data['path'],
                name=script_data['name'],
                type=script_data['type'],
                category=script_data['category'],
                version=VERSION,
                updated_at=datetime.now().isoformat(),
                source_count=len(script_data['sources']),
                invoke_count=len(script_data['invokes']),
                export_count=len(script_data['exports']),
                function_count=len(script_data['functions'])
            )
    
    def create_sources_relationship(self, script_path: str, source_info: Dict):
        """Create SOURCES relationship between scripts"""
        query = """
        MATCH (s:ShellScript {path: $script_path})
        MERGE (t:ShellScript {path: $source_path})
        ON CREATE SET t.name = $source_name, t.type = 'sourced'
        MERGE (s)-[r:SOURCES]->(t)
        SET r.line = $line
        """
        source_path = source_info.get('resolved') or source_info['path']
        source_name = Path(source_info['path']).name
        
        with self.driver.session() as session:
            session.run(query,
                script_path=script_path,
                source_path=source_path,
                source_name=source_name,
                line=source_info['line']
            )
    
    def create_invokes_relationship(self, script_path: str, invoke_info: Dict):
        """Create INVOKES relationship for script execution"""
        query = """
        MATCH (s:ShellScript {path: $script_path})
        MERGE (t:ShellScript {name: $invoked_name})
        ON CREATE SET t.type = 'ex-script', t.package = $package
        MERGE (s)-[r:INVOKES]->(t)
        SET r.line = $line, r.variable = $variable
        """
        with self.driver.session() as session:
            session.run(query,
                script_path=script_path,
                invoked_name=invoke_info['script'],
                package=invoke_info['package'],
                line=invoke_info['line'],
                variable=invoke_info.get('variable')
            )
    
    def create_export_relationship(self, script_path: str, export_info: Dict):
        """Create EXPORTS relationship for environment variables"""
        query = """
        MATCH (s:ShellScript {path: $script_path})
        MERGE (e:EnvironmentVariable {name: $var_name})
        ON CREATE SET e.default_value = $default_value
        MERGE (s)-[r:EXPORTS]->(e)
        SET r.line = $line
        """
        with self.driver.session() as session:
            session.run(query,
                script_path=script_path,
                var_name=export_info['name'],
                default_value=export_info.get('value', ''),
                line=export_info['line']
            )
    
    def create_depends_on_env_relationship(self, script_path: str, var_name: str):
        """Create DEPENDS_ON_ENV relationship"""
        query = """
        MATCH (s:ShellScript {path: $script_path})
        MERGE (e:EnvironmentVariable {name: $var_name})
        MERGE (s)-[:DEPENDS_ON_ENV]->(e)
        """
        with self.driver.session() as session:
            session.run(query,
                script_path=script_path,
                var_name=var_name
            )
    
    def create_reads_config_relationship(self, script_path: str, config_info: Dict):
        """Create READS_CONFIG relationship"""
        query = """
        MATCH (s:ShellScript {path: $script_path})
        MERGE (c:ConfigFile {name: $config_name})
        ON CREATE SET c.path = $config_path
        MERGE (s)-[r:READS_CONFIG]->(c)
        SET r.line = $line
        """
        config_path = f"parm/config/config.{config_info['name']}"
        
        with self.driver.session() as session:
            session.run(query,
                script_path=script_path,
                config_name=config_info['name'],
                config_path=config_path,
                line=config_info['line']
            )
    
    def create_function_node(self, script_path: str, func_info: Dict):
        """Create ShellFunction node linked to script"""
        query = """
        MATCH (s:ShellScript {path: $script_path})
        MERGE (f:ShellFunction {name: $func_name, script: $script_path})
        SET f.line = $line
        MERGE (s)-[:DEFINES]->(f)
        """
        with self.driver.session() as session:
            session.run(query,
                script_path=script_path,
                func_name=func_info['name'],
                line=func_info['line']
            )
    
    def get_statistics(self) -> Dict:
        """Get graph statistics"""
        queries = {
            'scripts': "MATCH (s:ShellScript) RETURN count(s) as count",
            'j_jobs': "MATCH (s:ShellScript {type: 'j-job'}) RETURN count(s) as count",
            'ex_scripts': "MATCH (s:ShellScript {type: 'ex-script'}) RETURN count(s) as count",
            'env_vars': "MATCH (e:EnvironmentVariable) RETURN count(e) as count",
            'configs': "MATCH (c:ConfigFile) RETURN count(c) as count",
            'functions': "MATCH (f:ShellFunction) RETURN count(f) as count",
            'sources_rels': "MATCH ()-[r:SOURCES]->() RETURN count(r) as count",
            'invokes_rels': "MATCH ()-[r:INVOKES]->() RETURN count(r) as count",
            'exports_rels': "MATCH ()-[r:EXPORTS]->() RETURN count(r) as count",
            'depends_rels': "MATCH ()-[r:DEPENDS_ON_ENV]->() RETURN count(r) as count",
            'config_rels': "MATCH ()-[r:READS_CONFIG]->() RETURN count(r) as count",
        }
        
        stats = {}
        with self.driver.session() as session:
            for key, query in queries.items():
                result = session.run(query)
                stats[key] = result.single()['count']
        
        return stats


# ============================================================================
# MAIN INGESTION PIPELINE
# ============================================================================

def find_shell_scripts(workflow_root: str) -> List[Tuple[str, str]]:
    """Find all shell scripts in workflow directories"""
    scripts = []
    
    for dir_path, script_type in SCRIPT_DIRECTORIES.items():
        full_path = Path(workflow_root) / dir_path
        if not full_path.exists():
            print(f"[WARN] Directory not found: {full_path}")
            continue
        
        print(f"[SCAN] {dir_path}/ ({script_type})")
        
        for ext in ['*.sh', '*.bash', '*.ksh']:
            for script_file in full_path.rglob(ext):
                rel_path = str(script_file.relative_to(workflow_root))
                scripts.append((str(script_file), rel_path))
        
        # Also find J-Jobs (no extension)
        if script_type == 'j-job':
            for script_file in full_path.iterdir():
                if script_file.is_file() and script_file.name.startswith('J'):
                    rel_path = str(script_file.relative_to(workflow_root))
                    scripts.append((str(script_file), rel_path))
    
    return scripts


def main():
    import argparse
    
    arg_parser = argparse.ArgumentParser(
        description='Phase 27B: Shell Script Graph Ingestion for Neo4j',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest_shell_graph_v8.py --dry-run       # Parse only, no Neo4j writes
  python ingest_shell_graph_v8.py --clear          # Clear existing + re-ingest
  python ingest_shell_graph_v8.py                   # Incremental (MERGE, no clear)
        """
    )
    arg_parser.add_argument('--dry-run', '-n', action='store_true',
                            help='Parse and report without writing to Neo4j')
    arg_parser.add_argument('--clear', action='store_true',
                            help='Clear existing shell graph before ingestion')
    arg_parser.add_argument('--verbose', '-v', action='store_true',
                            help='Show per-script detail')
    arg_parser.add_argument('--version', action='version',
                            version=f'%(prog)s {VERSION}')
    args = arg_parser.parse_args()
    
    print("=" * 70)
    print("Phase 27B: Shell Script Graph Ingestion for Neo4j")
    print(f"Version: {VERSION}")
    print(f"Workflow Root: {WORKFLOW_ROOT}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print(f"Clear existing: {'YES' if args.clear else 'NO (incremental MERGE)'}")
    print("=" * 70)
    
    # Initialize parser
    script_parser = ShellScriptParser()
    
    # Find all shell scripts (always do this, even for dry-run)
    scripts = find_shell_scripts(WORKFLOW_ROOT)
    print(f"\n[OK] Found {len(scripts)} shell scripts to process\n")
    
    if args.dry_run:
        # Parse only — report what would be ingested
        total_sources = 0
        total_invokes = 0
        total_exports = 0
        total_envdeps = 0
        total_configs = 0
        total_functions = 0
        
        for abs_path, rel_path in scripts:
            try:
                with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                script_data = script_parser.parse_script(rel_path, content)
                total_sources += len(script_data['sources'])
                total_invokes += len(script_data['invokes'])
                total_exports += len(script_data['exports'])
                total_envdeps += len(script_data['env_deps'])
                total_configs += len(script_data['configs'])
                total_functions += len(script_data['functions'])
                
                if args.verbose:
                    print(f"  {rel_path}: {script_data['type']}/{script_data['category']} "
                          f"src={len(script_data['sources'])} inv={len(script_data['invokes'])} "
                          f"exp={len(script_data['exports'])} env={len(script_data['env_deps'])} "
                          f"cfg={len(script_data['configs'])} fn={len(script_data['functions'])}")
            except Exception as e:
                print(f"  [ERROR] {rel_path}: {e}")
        
        print("\n" + "=" * 70)
        print("DRY-RUN SUMMARY (no writes performed)")
        print("=" * 70)
        print(f"Scripts found:         {len(scripts)}")
        print(f"SOURCES relationships: {total_sources}")
        print(f"INVOKES relationships: {total_invokes}")
        print(f"EXPORTS relationships: {total_exports}")
        print(f"DEPENDS_ON_ENV rels:   {total_envdeps}")
        print(f"READS_CONFIG rels:     {total_configs}")
        print(f"Shell functions:       {total_functions}")
        print("=" * 70)
        print("\nRe-run without --dry-run to write to Neo4j.")
        return
    
    # Live mode — connect to Neo4j
    graph = Neo4jGraphClient()
    
    if args.clear:
        graph.clear_shell_graph()
    
    graph.create_indexes()
    
    # Process each script
    processed = 0
    errors = 0
    
    for abs_path, rel_path in scripts:
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Parse script
            script_data = script_parser.parse_script(rel_path, content)
            
            # Create nodes and relationships
            graph.create_script_node(script_data)
            
            for source in script_data['sources']:
                graph.create_sources_relationship(rel_path, source)
            
            for invoke in script_data['invokes']:
                graph.create_invokes_relationship(rel_path, invoke)
            
            for export in script_data['exports']:
                graph.create_export_relationship(rel_path, export)
            
            for var in script_data['env_deps']:
                graph.create_depends_on_env_relationship(rel_path, var)
            
            for config in script_data['configs']:
                graph.create_reads_config_relationship(rel_path, config)
            
            for func in script_data['functions']:
                graph.create_function_node(rel_path, func)
            
            processed += 1
            
            if args.verbose:
                print(f"  [OK] {rel_path} ({script_data['type']}/{script_data['category']})")
            elif processed % 50 == 0:
                print(f"  [PROGRESS] Processed {processed}/{len(scripts)} scripts...")
        
        except Exception as e:
            print(f"  [ERROR] Failed to process {rel_path}: {e}")
            errors += 1
    
    # Get final statistics
    stats = graph.get_statistics()
    
    print("\n" + "=" * 70)
    print("SHELL SCRIPT GRAPH INGESTION SUMMARY")
    print("=" * 70)
    print(f"Scripts processed:     {processed}")
    print(f"Errors:                {errors}")
    print()
    print("Neo4j Graph Statistics:")
    print(f"  Total ShellScripts:  {stats['scripts']}")
    print(f"    - J-Jobs:          {stats['j_jobs']}")
    print(f"    - Ex-Scripts:      {stats['ex_scripts']}")
    print(f"  Environment Vars:    {stats['env_vars']}")
    print(f"  Config Files:        {stats['configs']}")
    print(f"  Shell Functions:     {stats['functions']}")
    print()
    print("Relationships:")
    print(f"  SOURCES:             {stats['sources_rels']}")
    print(f"  INVOKES:             {stats['invokes_rels']}")
    print(f"  EXPORTS:             {stats['exports_rels']}")
    print(f"  DEPENDS_ON_ENV:      {stats['depends_rels']}")
    print(f"  READS_CONFIG:        {stats['config_rels']}")
    print("=" * 70)
    
    # Parser stats
    print("\nParser Statistics:")
    for key, count in script_parser.stats.items():
        print(f"  {key}: {count}")
    
    graph.close()
    print("\n[OK] Shell script graph ingestion complete!")
    print(f"[OK] View in Neo4j Browser: http://localhost:7474")


if __name__ == "__main__":
    main()
