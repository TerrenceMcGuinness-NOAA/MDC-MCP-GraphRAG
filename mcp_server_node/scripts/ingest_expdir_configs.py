#!/usr/bin/env python3
"""
Phase 40 Step 40-6: EXPDIR Config & XML Ingestion for Neo4j + ChromaDB

Ingests experiment directory (EXPDIR) resolved configs and Rocoto XML from
supported_repos/EXPDIR/. EXPDIRs contain materialized configuration with
experiment-specific values filled in — the resolved versions of template configs.

Creates:
  Neo4j:    Experiment, EXPDIRConfig nodes + RESOLVES_FROM, PART_OF, SETS_ENV edges
  ChromaDB: code-with-context-v8-0-0 with file_type='expdir-config'

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

# Import sibling parsers
sys.path.insert(0, str(Path(__file__).parent))

try:
    from ingest_config_files import ConfigFileParser
except ImportError:
    print("[ERROR] Cannot import ConfigFileParser from ingest_config_files.py")
    sys.exit(1)

try:
    from ingest_rocoto_xml import RocotoXMLParser
    ROCOTO_AVAILABLE = True
except ImportError:
    print("[WARN] Cannot import RocotoXMLParser. XML parsing disabled.")
    ROCOTO_AVAILABLE = False

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

# Default EXPDIR base (three levels up from scripts/ to repo root)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DEFAULT_EXPDIR_BASE = os.path.join(REPO_ROOT, "supported_repos", "EXPDIR")

# Regex to strip hash suffix from experiment directory names
# e.g. "C48_ATM_250b0130-10380" → "C48_ATM"
HASH_SUFFIX = re.compile(r'_[0-9a-f]{6,12}-[0-9a-f]{3,6}$')


# ============================================================================
# EXPDIR DISCOVERER
# ============================================================================

class EXPDIRDiscoverer:
    """Auto-discover experiments and their files in EXPDIR base directory."""

    @staticmethod
    def discover_experiments(expdir_base: str,
                             experiment_filter: Optional[str] = None
                             ) -> List[dict]:
        """Discover all experiment directories.

        Parameters
        ----------
        expdir_base : str
            Path to EXPDIR base (contains one subdir per experiment).
        experiment_filter : str, optional
            If set, only return experiments matching this substring.

        Returns
        -------
        list[dict]
            List of dicts with: dir_name, abs_path, experiment_name, pslot,
            resolution, configs[], xml_path.
        """
        base = Path(expdir_base)
        if not base.is_dir():
            print(f"[ERROR] EXPDIR base not found: {expdir_base}")
            return []

        experiments = []
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue

            dir_name = d.name
            if experiment_filter and experiment_filter not in dir_name:
                continue

            # Extract human-readable name by stripping hash suffix
            experiment_name = HASH_SUFFIX.sub('', dir_name)

            # Extract resolution from name (e.g. C48, C96, C384)
            res_match = re.match(r'(C\d+)', dir_name)
            resolution = res_match.group(1) if res_match else 'unknown'

            # Find config files
            configs = sorted([
                f for f in d.iterdir()
                if f.is_file() and f.name.startswith('config.')
            ])

            # Find XML file (one per experiment)
            xml_files = list(d.glob("*.xml"))
            xml_path = str(xml_files[0]) if xml_files else None

            experiments.append({
                'dir_name': dir_name,
                'abs_path': str(d),
                'experiment_name': experiment_name,
                'pslot': dir_name,
                'resolution': resolution,
                'configs': [str(c) for c in configs],
                'xml_path': xml_path,
            })

        return experiments

    @staticmethod
    def classify_config(filename: str) -> str:
        """Classify a config filename into a category.

        Parameters
        ----------
        filename : str
            Config filename (e.g. 'config.fcst', 'config.resources.GAEAC6').

        Returns
        -------
        str
            Category name.
        """
        # Resource platform overrides
        if filename.startswith('config.resources'):
            return 'resources'
        # Strip 'config.' prefix to get the key
        key = filename.replace('config.', '')
        from ingest_config_files import CATEGORY_MAP
        return CATEGORY_MAP.get(key, 'other')


# ============================================================================
# EXPDIR INGESTOR
# ============================================================================

class EXPDIRIngestor:
    """Ingest EXPDIR configs into Neo4j and ChromaDB."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.neo4j_driver = None
        self.chroma_collection = None
        self.stats = defaultdict(int)
        self.errors = []

    def connect_neo4j(self) -> bool:
        """Connect to Neo4j."""
        if GraphDatabase is None:
            print("[WARN] Neo4j driver not installed")
            return False
        try:
            self.neo4j_driver = GraphDatabase.driver(
                NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD),
                max_connection_lifetime=3600)
            with self.neo4j_driver.session() as session:
                session.run("RETURN 1")
            print(f"[OK] Connected to Neo4j: {NEO4J_URI}")
            return True
        except Exception as e:
            print(f"[ERROR] Neo4j connection failed: {e}")
            return False

    def connect_chromadb(self) -> bool:
        """Connect to ChromaDB."""
        if chromadb is None:
            print("[WARN] chromadb package not installed")
            return False
        try:
            client = chromadb.HttpClient(
                host=CHROMADB_HOST, port=CHROMADB_PORT)
            embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=EMBEDDING_MODEL)
            try:
                self.chroma_collection = client.get_collection(
                    name=COLLECTION_NAME,
                    embedding_function=embedding_fn)
                print(f"[OK] Using ChromaDB collection: {COLLECTION_NAME} "
                      f"({self.chroma_collection.count()} docs)")
            except Exception:
                self.chroma_collection = client.create_collection(
                    name=COLLECTION_NAME,
                    embedding_function=embedding_fn,
                    metadata={
                        "version": VERSION,
                        "type": "code",
                        "embedding_model": EMBEDDING_MODEL,
                    })
                print(f"[OK] Created ChromaDB collection: {COLLECTION_NAME}")
            return True
        except Exception as e:
            print(f"[ERROR] ChromaDB connection failed: {e}")
            return False

    def create_indexes(self):
        """Create Neo4j indexes for EXPDIR nodes."""
        indexes = [
            "CREATE INDEX experiment_name IF NOT EXISTS "
            "FOR (e:Experiment) ON (e.name)",
            "CREATE INDEX experiment_pslot IF NOT EXISTS "
            "FOR (e:Experiment) ON (e.pslot)",
            "CREATE INDEX expdir_config_name IF NOT EXISTS "
            "FOR (ec:EXPDIRConfig) ON (ec.name)",
            "CREATE INDEX expdir_config_experiment IF NOT EXISTS "
            "FOR (ec:EXPDIRConfig) ON (ec.experiment)",
        ]
        with self.neo4j_driver.session() as session:
            for idx in indexes:
                try:
                    session.run(idx)
                except Exception:
                    pass
        print("[OK] Created EXPDIR Neo4j indexes")

    def ingest_experiment(self, experiment: dict, parsed_configs: List[dict]):
        """Create Experiment node and EXPDIRConfig nodes for one experiment.

        Parameters
        ----------
        experiment : dict
            From EXPDIRDiscoverer.discover_experiments().
        parsed_configs : list[dict]
            List of dicts with: filename, file_path, parsed (from ConfigFileParser),
            category.
        """
        exp_name = experiment['experiment_name']

        # Create Experiment node
        if self.neo4j_driver:
            self._ingest_experiment_neo4j(experiment, parsed_configs)

        # Create ChromaDB docs
        if self.chroma_collection:
            self._ingest_experiment_chromadb(experiment, parsed_configs)

    def _ingest_experiment_neo4j(self, experiment: dict,
                                  parsed_configs: List[dict]):
        """Create Neo4j nodes for one experiment."""
        exp_name = experiment['experiment_name']
        pslot = experiment['pslot']

        with self.neo4j_driver.session() as session:
            # MERGE Experiment node
            session.run("""
                MERGE (e:Experiment {name: $name})
                SET e.pslot = $pslot,
                    e.resolution = $resolution,
                    e.config_count = $config_count,
                    e.has_xml = $has_xml,
                    e.version = $version,
                    e.updated_at = $updated_at
            """,
                name=exp_name,
                pslot=pslot,
                resolution=experiment['resolution'],
                config_count=len(parsed_configs),
                has_xml=experiment['xml_path'] is not None,
                version=VERSION,
                updated_at=datetime.now().isoformat())
            self.stats['experiments'] += 1

            # Create EXPDIRConfig nodes
            for cfg in parsed_configs:
                filename = cfg['filename']
                parsed = cfg['parsed']
                category = cfg['category']
                env_vars = parsed.get('env_vars', [])

                # Compound key: experiment + config name
                config_key = f"{exp_name}/{filename}"

                session.run("""
                    MERGE (ec:EXPDIRConfig {name: $config_key})
                    SET ec.filename = $filename,
                        ec.experiment = $experiment,
                        ec.category = $category,
                        ec.env_var_count = $env_var_count,
                        ec.source_count = $source_count,
                        ec.line_count = $line_count,
                        ec.file_path = $file_path,
                        ec.version = $version,
                        ec.updated_at = $updated_at
                """,
                    config_key=config_key,
                    filename=filename,
                    experiment=exp_name,
                    category=category,
                    env_var_count=len(env_vars),
                    source_count=len(parsed.get('sources', [])),
                    line_count=parsed.get('line_count', 0),
                    file_path=cfg['file_path'],
                    version=VERSION,
                    updated_at=datetime.now().isoformat())
                self.stats['expdir_configs'] += 1

                # PART_OF → Experiment
                session.run("""
                    MATCH (ec:EXPDIRConfig {name: $config_key})
                    MATCH (e:Experiment {name: $experiment})
                    MERGE (ec)-[:PART_OF]->(e)
                """, config_key=config_key, experiment=exp_name)
                self.stats['part_of_edges'] += 1

                # RESOLVES_FROM → ConfigFile (template)
                # Match against existing ConfigFile nodes by short name
                # e.g. config.fcst → ConfigFile {name: 'fcst'}
                config_short = filename.replace('config.', '')
                # Skip resource platform overrides for template linking
                if not filename.startswith('config.resources.'):
                    session.run("""
                        MATCH (ec:EXPDIRConfig {name: $config_key})
                        MATCH (cf:ConfigFile {name: $short_name})
                        MERGE (ec)-[:RESOLVES_FROM]->(cf)
                    """, config_key=config_key, short_name=config_short)
                    self.stats['resolves_from_edges'] += 1

                # SETS_ENV → EnvironmentVariable (for top env vars only)
                for ev in env_vars[:50]:
                    session.run("""
                        MATCH (ec:EXPDIRConfig {name: $config_key})
                        MERGE (e:EnvironmentVariable {name: $var_name})
                        MERGE (ec)-[:SETS_ENV {
                            value: $value,
                            is_resolved: true,
                            experiment: $experiment
                        }]->(e)
                    """,
                        config_key=config_key,
                        var_name=ev['name'],
                        value=str(ev.get('default_value', ''))[:200],
                        experiment=exp_name)
                    self.stats['sets_env_edges'] += 1

    def _ingest_experiment_chromadb(self, experiment: dict,
                                     parsed_configs: List[dict]):
        """Ingest resolved configs into ChromaDB."""
        exp_name = experiment['experiment_name']

        for cfg in parsed_configs:
            filename = cfg['filename']
            parsed = cfg['parsed']
            content = parsed.get('raw_content', '')
            if not content.strip():
                continue

            env_vars = parsed.get('env_vars', [])
            var_names = [v['name'] for v in env_vars[:20]]

            doc_text = (
                f"# EXPDIR Resolved Config: {filename}\n"
                f"# Experiment: {exp_name}\n"
                f"# Resolution: {experiment['resolution']}\n"
                f"# Category: {cfg['category']}\n"
                f"# Environment variables ({len(env_vars)}): "
                f"{', '.join(var_names)}\n\n"
                f"{content}"
            )

            doc_id = (f"expdir-"
                      f"{hashlib.md5(f'{exp_name}/{filename}'.encode()).hexdigest()[:12]}")

            metadata = {
                'file_type': 'expdir-config',
                'experiment': exp_name,
                'resolution': experiment['resolution'],
                'filename': filename,
                'category': cfg['category'],
                'env_var_count': len(env_vars),
                'source': 'phase40_expdir_ingestion',
                'version': VERSION,
            }

            try:
                self.chroma_collection.add(
                    ids=[doc_id],
                    documents=[doc_text],
                    metadatas=[metadata])
                self.stats['chromadb_docs'] += 1
            except Exception as e:
                self.errors.append({
                    'file': f"{exp_name}/{filename}",
                    'error': str(e)
                })

    def close(self):
        if self.neo4j_driver:
            self.neo4j_driver.close()

    def get_statistics(self) -> dict:
        return dict(self.stats)


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Phase 40-6: EXPDIR Config & XML Ingestion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest_expdir_configs.py --dry-run
  python ingest_expdir_configs.py --experiment C48_ATM --dry-run
  python ingest_expdir_configs.py --skip-xml --verbose
  python ingest_expdir_configs.py
        """
    )
    parser.add_argument('--expdir-base', metavar='DIR',
                        default=DEFAULT_EXPDIR_BASE,
                        help=f'Path to EXPDIR base (default: {DEFAULT_EXPDIR_BASE})')
    parser.add_argument('--experiment', metavar='FILTER',
                        help='Only process experiments matching this substring')
    parser.add_argument('--skip-xml', action='store_true',
                        help='Skip Rocoto XML parsing (configs only)')
    parser.add_argument('--skip-neo4j', action='store_true',
                        help='Skip Neo4j ingestion (ChromaDB only)')
    parser.add_argument('--skip-chromadb', action='store_true',
                        help='Skip ChromaDB ingestion (Neo4j only)')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Parse without writing to databases')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show per-file details')
    parser.add_argument('--version', action='version',
                        version=f'%(prog)s {VERSION}')

    args = parser.parse_args()

    print(f"[STEP 1] EXPDIR Config Ingestion v{VERSION}")
    print(f"  EXPDIR base: {args.expdir_base}")

    # Discover experiments
    experiments = EXPDIRDiscoverer.discover_experiments(
        args.expdir_base, args.experiment)
    print(f"[SCAN] Found {len(experiments)} experiments")

    if not experiments:
        print("[WARN] No experiments found. Exiting.")
        return

    for exp in experiments:
        print(f"  {exp['experiment_name']:40s}  "
              f"{len(exp['configs']):3d} configs  "
              f"{'XML' if exp['xml_path'] else '---'}")

    # Parse all configs
    print(f"\n[STEP 2] Parsing resolved configs...")
    total_configs = 0
    total_vars = 0
    all_experiments_data = []

    for i, exp in enumerate(experiments):
        parsed_configs = []
        for config_path in exp['configs']:
            filename = Path(config_path).name
            parsed = ConfigFileParser.parse_config_file(config_path)
            category = EXPDIRDiscoverer.classify_config(filename)

            parsed_configs.append({
                'filename': filename,
                'file_path': config_path,
                'parsed': parsed,
                'category': category,
            })

            env_count = len(parsed.get('env_vars', []))
            total_vars += env_count

            if args.verbose:
                print(f"  [{exp['experiment_name']}] {filename}: "
                      f"{env_count} vars, {category}")

        total_configs += len(parsed_configs)
        all_experiments_data.append((exp, parsed_configs))

        if not args.verbose:
            print(f"  [PROGRESS] {i+1}/{len(experiments)} "
                  f"{exp['experiment_name']}: {len(parsed_configs)} configs")

    print(f"\n  Parse Summary:")
    print(f"    Experiments: {len(experiments)}")
    print(f"    Configs:     {total_configs}")
    print(f"    Env Vars:    {total_vars}")

    # XML summary (if not skipped)
    xml_count = sum(1 for e in experiments if e['xml_path'])
    if not args.skip_xml and ROCOTO_AVAILABLE and xml_count > 0:
        print(f"\n[STEP 2b] Parsing Rocoto XML files...")
        xml_stats = {'tasks': 0, 'deps': 0}
        for exp in experiments:
            if exp['xml_path']:
                try:
                    result = RocotoXMLParser.parse_rocoto_xml(exp['xml_path'])
                    xml_stats['tasks'] += len(result.get('tasks', []))
                    xml_stats['deps'] += sum(
                        len(t.get('dependencies', []))
                        for t in result.get('tasks', []))
                    if args.verbose:
                        print(f"  [{exp['experiment_name']}] "
                              f"{len(result.get('tasks', []))} tasks, "
                              f"{len(result.get('metatasks', []))} metatasks")
                except Exception as e:
                    print(f"  [WARN] XML parse error for "
                          f"{exp['experiment_name']}: {e}")
        print(f"    XML tasks: {xml_stats['tasks']}")
        print(f"    XML deps:  {xml_stats['deps']}")

    # Dry-run summary
    if args.dry_run:
        print(f"\n{'=' * 60}")
        print(f"  DRY-RUN SUMMARY (no database writes)")
        print(f"{'=' * 60}")
        print(f"  Experiments:      {len(experiments)}")
        print(f"  EXPDIRConfig:     {total_configs} (would create)")
        print(f"  Env var edges:    {total_vars} (would create)")
        print(f"  RESOLVES_FROM:    ~{total_configs} (would link to templates)")
        print(f"  ChromaDB docs:    {total_configs} (would ingest)")
        if not args.skip_xml and xml_count > 0:
            print(f"  XML files:        {xml_count} (parsed above)")
        print(f"{'=' * 60}")
        print(f"\n  Re-run without --dry-run to write to databases.")
        return

    # Live mode
    print(f"\n[STEP 3] Connecting to databases...")
    ingestor = EXPDIRIngestor()

    neo4j_ok = False
    chromadb_ok = False

    if not args.skip_neo4j:
        neo4j_ok = ingestor.connect_neo4j()
        if neo4j_ok:
            ingestor.create_indexes()
    if not args.skip_chromadb:
        chromadb_ok = ingestor.connect_chromadb()

    if not neo4j_ok and not chromadb_ok:
        print("[ERROR] No database connections available. Exiting.")
        return

    # Ingest
    print(f"\n[STEP 4] Ingesting {len(experiments)} experiments...")
    for i, (exp, parsed_configs) in enumerate(all_experiments_data):
        ingestor.ingest_experiment(exp, parsed_configs)
        print(f"  [PROGRESS] {i+1}/{len(experiments)} "
              f"{exp['experiment_name']}: {len(parsed_configs)} configs")

    stats = ingestor.get_statistics()
    print(f"\n{'=' * 60}")
    print(f"  INGESTION COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Experiments:      {stats.get('experiments', 0)}")
    print(f"  EXPDIRConfig:     {stats.get('expdir_configs', 0)} nodes")
    print(f"  PART_OF edges:    {stats.get('part_of_edges', 0)}")
    print(f"  RESOLVES_FROM:    {stats.get('resolves_from_edges', 0)}")
    print(f"  SETS_ENV:         {stats.get('sets_env_edges', 0)}")
    print(f"  ChromaDB docs:    {stats.get('chromadb_docs', 0)}")
    print(f"  Errors:           {len(ingestor.errors)}")
    print(f"{'=' * 60}")

    if ingestor.errors:
        print(f"\n[WARN] {len(ingestor.errors)} errors:")
        for err in ingestor.errors[:10]:
            print(f"  {err}")

    ingestor.close()
    print("\n[OK] Done.")


if __name__ == '__main__':
    main()
