#!/usr/bin/env python3
"""
Phase 40 Step 40-2: Configuration File Ingestion for ChromaDB + Neo4j

Parses config.* shell fragments from dev/parm/config/{gfs,gefs,gcafs,sfs},
extracts environment variable exports and source chains, and ingests into:
  - ChromaDB (code-with-context-v8-0-0) for semantic search
  - Neo4j (ConfigFile enrichment + SETS_ENV edges) for graph queries

Enriches existing ConfigFile skeleton nodes created by ingest_shell_graph_v8.py
rather than creating duplicates.

Neo4j Schema:
  (:ConfigFile {name, file_path, system, category, env_var_count})
  (:ConfigFile)-[:SETS_ENV {value, is_default}]->(:EnvironmentVariable)

ChromaDB: code-with-context-v8-0-0, metadata file_type='config'

Author: NOAA EMC Global Workflow MCP Team
Version: 40.1.0
"""

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

try:
    from neo4j import GraphDatabase
except ImportError:
    print("[WARN] neo4j package not found. Neo4j ingestion disabled.")
    GraphDatabase = None

try:
    import chromadb
    from chromadb.utils import embedding_functions
except ImportError:
    print("[WARN] chromadb package not found. ChromaDB ingestion disabled.")
    chromadb = None


# ============================================================================
# CONFIGURATION
# ============================================================================

VERSION = "40.1.0"
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "gfsworkflow2025")
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))
EMBEDDING_MODEL = "all-mpnet-base-v2"
COLLECTION_NAME = os.getenv("CODE_COLLECTION", "code-with-context-v8-0-0")

WORKFLOW_ROOT = os.getenv("WORKFLOW_ROOT",
    "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow")

CONFIG_DIRECTORIES = {
    'dev/parm/config/gfs': 'gfs',
    'dev/parm/config/gefs': 'gefs',
    'dev/parm/config/gcafs': 'gcafs',
    'dev/parm/config/sfs': 'sfs',
}

CATEGORY_MAP = {
    'base': 'common', 'fcst': 'forecast', 'anal': 'analysis',
    'analcalc': 'analysis', 'analdiag': 'analysis',
    'resources': 'resources', 'arch': 'archive', 'arch_tars': 'archive',
    'cleanup': 'housekeeping', 'stage_ic': 'initialization',
    'prep': 'preprocessing', 'sfcanl': 'surface_analysis',
    'tracker': 'verification', 'genesis': 'verification',
    'fit2obs': 'verification', 'verfozn': 'verification',
    'verfrad': 'verification', 'metp': 'verification',
    'ocn': 'ocean', 'ice': 'ice', 'wave': 'wave',
    'marineanl': 'marine_analysis', 'marinebmat': 'marine_analysis',
    'aeroanl': 'aerosol_analysis', 'aeroanlvar': 'aerosol_analysis',
    'snowanl': 'snow_analysis', 'esnowanl': 'snow_analysis',
    'ecen': 'ensemble', 'eobs': 'ensemble', 'eupd': 'ensemble',
    'esfc': 'ensemble', 'epos': 'ensemble', 'earc': 'ensemble',
    'atmanl': 'atmospheric_analysis', 'atmensanl': 'ensemble_analysis',
}


# ============================================================================
# CONFIG FILE PARSER
# ============================================================================

class ConfigFileParser:
    """Parse shell config files to extract environment variables and sources."""

    # Matches: export VAR=value, export VAR=${VAR:-default}, VAR=value
    ENV_PATTERN = re.compile(
        r'^(?:export\s+)?([A-Z_][A-Z0-9_]*)=(?:\$\{[^}]*:-)?([^}"\n]*)'
    )
    # Also match: export VAR="${VAR:-default}"
    ENV_PATTERN_QUOTED = re.compile(
        r'^(?:export\s+)?([A-Z_][A-Z0-9_]*)=["\']?\$\{([^}]*):-([^}]*)\}["\']?'
    )
    # Simple export: export VAR="literal"
    ENV_SIMPLE = re.compile(
        r'^(?:export\s+)([A-Z_][A-Z0-9_]*)=["\']([^"\']*)["\']'
    )
    # Source patterns
    SOURCE_PATTERN = re.compile(
        r'(?:source|\.\s+)["\s]*([^\s;|&"\'#]+)'
    )
    # Bare export (no value, just declaring)
    BARE_EXPORT = re.compile(r'^export\s+([A-Z_][A-Z0-9_]*)\s*$')

    @staticmethod
    def parse_config_file(file_path: str) -> dict:
        """Extract environment variables and metadata from a config file.

        Parameters
        ----------
        file_path : str
            Absolute path to the config file.

        Returns
        -------
        dict
            {env_vars: [{name, default_value, comment}], sources: [...],
             raw_content: str, line_count: int}
        """
        env_vars = []
        sources = []
        seen_vars = set()

        try:
            content = Path(file_path).read_text(errors='replace')
        except Exception as e:
            return {'env_vars': [], 'sources': [], 'raw_content': '',
                    'line_count': 0, 'error': str(e)}

        for line in content.splitlines():
            stripped = line.strip()

            # Skip comments and empty lines
            if not stripped or stripped.startswith('#'):
                continue

            # Try quoted export with default: export VAR="${VAR:-default}"
            m = ConfigFileParser.ENV_PATTERN_QUOTED.match(stripped)
            if m:
                var_name = m.group(1)
                default_val = m.group(3).strip('"\'')
                if var_name not in seen_vars:
                    env_vars.append({
                        'name': var_name,
                        'default_value': default_val,
                        'is_default': True,
                    })
                    seen_vars.add(var_name)
                continue

            # Try simple export: export VAR="literal"
            m = ConfigFileParser.ENV_SIMPLE.match(stripped)
            if m:
                var_name = m.group(1)
                value = m.group(2)
                if var_name not in seen_vars:
                    env_vars.append({
                        'name': var_name,
                        'default_value': value,
                        'is_default': False,
                    })
                    seen_vars.add(var_name)
                continue

            # Try general pattern
            m = ConfigFileParser.ENV_PATTERN.match(stripped)
            if m:
                var_name = m.group(1)
                value = m.group(2).strip('"\'')
                if var_name not in seen_vars:
                    env_vars.append({
                        'name': var_name,
                        'default_value': value,
                        'is_default': ':-' in stripped,
                    })
                    seen_vars.add(var_name)
                continue

            # Bare export
            m = ConfigFileParser.BARE_EXPORT.match(stripped)
            if m:
                var_name = m.group(1)
                if var_name not in seen_vars:
                    env_vars.append({
                        'name': var_name,
                        'default_value': '',
                        'is_default': False,
                    })
                    seen_vars.add(var_name)
                continue

            # Source chain
            m = ConfigFileParser.SOURCE_PATTERN.search(stripped)
            if m:
                sources.append(m.group(1))

        return {
            'env_vars': env_vars,
            'sources': sources,
            'raw_content': content,
            'line_count': len(content.splitlines()),
        }

    @staticmethod
    def categorize_config(filename: str) -> str:
        """Map config filename to a human-readable category.

        Parameters
        ----------
        filename : str
            Config filename like 'config.fcst' or 'config.resources.HERA'.

        Returns
        -------
        str
            Category string.
        """
        # Strip 'config.' prefix
        name = filename.replace('config.', '')
        # Strip platform suffix for resources
        if name.startswith('resources'):
            return 'resources'
        # Try direct map
        for key, category in CATEGORY_MAP.items():
            if name.startswith(key):
                return category
        return 'other'

    @staticmethod
    def config_short_name(filename: str) -> str:
        """Extract the short name from a config filename.

        Matches the naming used by ingest_shell_graph_v8.py ConfigFile nodes.
        e.g. 'config.fcst' -> 'fcst', 'config.resources.HERA' -> 'resources.HERA'
        """
        if filename.startswith('config.'):
            return filename[7:]  # strip 'config.'
        return filename


# ============================================================================
# CONFIG FILE INGESTOR
# ============================================================================

class ConfigFileIngestor:
    """Ingest config files into Neo4j and ChromaDB."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.driver = None
        self.collection = None
        self.stats = defaultdict(int)
        self.errors = []

    def connect_neo4j(self) -> bool:
        """Connect to Neo4j."""
        if GraphDatabase is None:
            print("[WARN] Neo4j driver not available")
            return False
        try:
            self.driver = GraphDatabase.driver(
                NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD),
                max_connection_lifetime=3600)
            with self.driver.session() as session:
                session.run("RETURN 1")
            print(f"[OK] Connected to Neo4j: {NEO4J_URI}")
            return True
        except Exception as e:
            print(f"[ERROR] Neo4j connection failed: {e}")
            return False

    def connect_chromadb(self) -> bool:
        """Connect to ChromaDB."""
        if chromadb is None:
            print("[WARN] chromadb not available")
            return False
        try:
            self.chroma = chromadb.HttpClient(
                host=CHROMADB_HOST, port=CHROMADB_PORT)
            self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=EMBEDDING_MODEL)
            try:
                self.collection = self.chroma.get_collection(
                    name=COLLECTION_NAME,
                    embedding_function=self.embedding_fn)
                print(f"[OK] Using collection: {COLLECTION_NAME} "
                      f"({self.collection.count()} docs)")
            except Exception:
                self.collection = self.chroma.create_collection(
                    name=COLLECTION_NAME,
                    embedding_function=self.embedding_fn,
                    metadata={
                        "version": VERSION,
                        "type": "code",
                        "embedding_model": EMBEDDING_MODEL,
                    })
                print(f"[OK] Created collection: {COLLECTION_NAME}")
            return True
        except Exception as e:
            print(f"[ERROR] ChromaDB connection failed: {e}")
            return False

    def close(self):
        """Close connections."""
        if self.driver:
            self.driver.close()

    def create_indexes(self):
        """Create Neo4j indexes for ConfigFile."""
        if not self.driver:
            return
        indexes = [
            "CREATE INDEX config_file_path IF NOT EXISTS FOR (c:ConfigFile) ON (c.file_path)",
        ]
        with self.driver.session() as session:
            for idx in indexes:
                try:
                    session.run(idx)
                except Exception:
                    pass
        print("[OK] Created ConfigFile indexes")

    def ingest_config(self, rel_path: str, parsed: dict, system: str,
                      filename: str):
        """Ingest a single config file into Neo4j and ChromaDB.

        Parameters
        ----------
        rel_path : str
            Repo-relative path (e.g., 'dev/parm/config/gfs/config.fcst')
        parsed : dict
            Output of ConfigFileParser.parse_config_file()
        system : str
            System identifier (gfs, gefs, gcafs, sfs)
        filename : str
            Config filename (e.g., 'config.fcst')
        """
        short_name = ConfigFileParser.config_short_name(filename)
        category = ConfigFileParser.categorize_config(filename)

        # Neo4j: enrich existing ConfigFile or create new
        if self.driver:
            self._ingest_neo4j(short_name, rel_path, system, category,
                               parsed, filename)

        # ChromaDB: add as searchable document
        if self.collection:
            self._ingest_chromadb(rel_path, parsed, system, category,
                                  filename)

    def _ingest_neo4j(self, short_name: str, rel_path: str, system: str,
                      category: str, parsed: dict, filename: str):
        """Create/enrich ConfigFile node and SETS_ENV edges."""
        # Use system-qualified name for non-first systems to avoid collision
        # GFS gets the short name (enriches shell graph nodes); others qualified
        node_name = short_name if system == 'gfs' else f"{system}/{short_name}"

        query = """
        MERGE (c:ConfigFile {name: $name})
        SET c.file_path = $file_path,
            c.system = $system,
            c.category = $category,
            c.env_var_count = $env_var_count,
            c.line_count = $line_count,
            c.filename = $filename,
            c.version = $version,
            c.updated_at = $updated_at
        """
        with self.driver.session() as session:
            session.run(query,
                        name=node_name,
                        file_path=rel_path,
                        system=system,
                        category=category,
                        env_var_count=len(parsed['env_vars']),
                        line_count=parsed.get('line_count', 0),
                        filename=filename,
                        version=VERSION,
                        updated_at=datetime.now().isoformat())
        self.stats['config_nodes'] += 1

        # SETS_ENV edges
        for var in parsed['env_vars']:
            var_name = var['name']
            if not var_name:
                continue
            query = """
            MATCH (c:ConfigFile {name: $config_name})
            MERGE (e:EnvironmentVariable {name: $var_name})
            MERGE (c)-[r:SETS_ENV]->(e)
            SET r.value = $value,
                r.is_default = $is_default
            """
            with self.driver.session() as session:
                session.run(query,
                            config_name=node_name,
                            var_name=var_name,
                            value=var.get('default_value', ''),
                            is_default=var.get('is_default', False))
            self.stats['sets_env_edges'] += 1

    def _ingest_chromadb(self, rel_path: str, parsed: dict, system: str,
                         category: str, filename: str):
        """Add config file as ChromaDB document."""
        content = parsed.get('raw_content', '')
        if not content.strip():
            return

        # Build document text with context
        var_names = [v['name'] for v in parsed['env_vars']]
        doc_text = (
            f"# Configuration File: {filename}\n"
            f"# System: {system}, Category: {category}\n"
            f"# Path: {rel_path}\n"
            f"# Environment variables: {', '.join(var_names[:20])}\n\n"
            f"{content}"
        )

        # Deterministic ID
        doc_id = f"config-{hashlib.md5(rel_path.encode()).hexdigest()[:12]}"

        metadata = {
            'file_type': 'config',
            'system': system,
            'category': category,
            'file_path': rel_path,
            'filename': filename,
            'env_var_count': len(parsed['env_vars']),
            'env_vars': json.dumps(var_names[:50]),
            'source': 'phase40_config_ingestion',
            'version': VERSION,
        }

        try:
            self.collection.add(
                ids=[doc_id],
                documents=[doc_text],
                metadatas=[metadata]
            )
            self.stats['chromadb_docs'] += 1
        except Exception as e:
            self.errors.append({'file': rel_path, 'error': str(e)})

    def get_statistics(self) -> dict:
        return dict(self.stats)


# ============================================================================
# FILE DISCOVERY
# ============================================================================

def discover_config_files(workflow_root: str,
                          system_filter: str = None) -> List[dict]:
    """Discover all plain config files (non-.j2, non-.yaml).

    Parameters
    ----------
    workflow_root : str
        Path to global-workflow repo root.
    system_filter : str, optional
        Filter to a single system (gfs, gefs, gcafs, sfs).

    Returns
    -------
    list[dict]
        List of dicts with abs_path, rel_path, filename, system.
    """
    configs = []
    root = Path(workflow_root)

    for rel_dir, system in CONFIG_DIRECTORIES.items():
        if system_filter and system != system_filter:
            continue

        abs_dir = root / rel_dir
        if not abs_dir.is_dir():
            print(f"[WARN] Directory not found: {abs_dir}")
            continue

        for f in sorted(abs_dir.iterdir()):
            if not f.is_file():
                continue
            # Skip Jinja2 templates and YAML files
            if f.suffix in ('.j2', '.yaml', '.yml'):
                continue
            # Skip hidden files and directories
            if f.name.startswith('.'):
                continue

            configs.append({
                'abs_path': str(f),
                'rel_path': str(f.relative_to(root)),
                'filename': f.name,
                'system': system,
            })

    return configs


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Phase 40-2: Config File Ingestion for ChromaDB + Neo4j",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest_config_files.py --dry-run
  python ingest_config_files.py --system gfs --dry-run
  python ingest_config_files.py
  python ingest_config_files.py --verbose
        """
    )
    parser.add_argument('--workflow-root', metavar='DIR',
                        default=WORKFLOW_ROOT,
                        help=f'Path to global-workflow (default: {WORKFLOW_ROOT})')
    parser.add_argument('--system', choices=['gfs', 'gefs', 'gcafs', 'sfs'],
                        help='Filter to a single system')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Parse and count without writing to databases')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show per-file details')
    parser.add_argument('--version', action='version',
                        version=f'%(prog)s {VERSION}')

    args = parser.parse_args()

    print(f"[STEP 1] Config File Ingestion v{VERSION}")
    print(f"  Workflow root: {args.workflow_root}")

    # Discover config files
    configs = discover_config_files(args.workflow_root, args.system)
    print(f"[SCAN] Found {len(configs)} plain config files")

    if not configs:
        print("[WARN] No config files found. Exiting.")
        return

    # Parse all files
    print(f"\n[STEP 2] Parsing config files...")
    total_vars = 0
    total_sources = 0
    parsed_configs = []

    for i, cfg in enumerate(configs, 1):
        parsed = ConfigFileParser.parse_config_file(cfg['abs_path'])
        parsed_configs.append((cfg, parsed))

        var_count = len(parsed['env_vars'])
        total_vars += var_count
        total_sources += len(parsed['sources'])

        if args.verbose and var_count > 0:
            var_names = [v['name'] for v in parsed['env_vars'][:5]]
            print(f"  {cfg['rel_path']}: {var_count} vars "
                  f"[{', '.join(var_names)}{'...' if var_count > 5 else ''}]")

        if i % 50 == 0:
            print(f"  [PROGRESS] Parsed {i}/{len(configs)} files...")

    # Summary by system
    by_system = defaultdict(lambda: {'files': 0, 'vars': 0})
    for cfg, parsed in parsed_configs:
        by_system[cfg['system']]['files'] += 1
        by_system[cfg['system']]['vars'] += len(parsed['env_vars'])

    print(f"\n  Parse Summary:")
    for system in ['gfs', 'gefs', 'gcafs', 'sfs']:
        s = by_system.get(system, {'files': 0, 'vars': 0})
        print(f"    {system}: {s['files']} files, {s['vars']} env vars")
    print(f"    TOTAL: {len(configs)} files, {total_vars} env vars, "
          f"{total_sources} source chains")

    if args.dry_run:
        print(f"\n{'=' * 60}")
        print(f"  DRY-RUN SUMMARY (no database writes)")
        print(f"{'=' * 60}")
        print(f"  Would create/enrich {len(configs)} ConfigFile nodes")
        print(f"  Would create ~{total_vars} SETS_ENV edges")
        print(f"  Would add {len(configs)} ChromaDB documents")
        print(f"{'=' * 60}")
        print(f"\n  Re-run without --dry-run to write to databases.")
        return

    # Live mode: connect and ingest
    print(f"\n[STEP 3] Connecting to databases...")
    ingestor = ConfigFileIngestor()
    neo4j_ok = ingestor.connect_neo4j()
    chromadb_ok = ingestor.connect_chromadb()

    if neo4j_ok:
        ingestor.create_indexes()

    print(f"\n[STEP 4] Ingesting {len(configs)} config files...")
    for i, (cfg, parsed) in enumerate(parsed_configs, 1):
        ingestor.ingest_config(cfg['rel_path'], parsed,
                               cfg['system'], cfg['filename'])

        if i % 50 == 0:
            print(f"  [PROGRESS] Ingested {i}/{len(configs)} files...")

    stats = ingestor.get_statistics()
    print(f"\n{'=' * 60}")
    print(f"  INGESTION COMPLETE")
    print(f"{'=' * 60}")
    print(f"  ConfigFile nodes:  {stats.get('config_nodes', 0)}")
    print(f"  SETS_ENV edges:    {stats.get('sets_env_edges', 0)}")
    print(f"  ChromaDB docs:     {stats.get('chromadb_docs', 0)}")
    print(f"  Errors:            {len(ingestor.errors)}")
    print(f"{'=' * 60}")

    if ingestor.errors:
        print(f"\n[WARN] {len(ingestor.errors)} errors:")
        for err in ingestor.errors[:10]:
            print(f"  {err}")

    ingestor.close()
    print("\n[OK] Done.")


if __name__ == '__main__':
    main()
