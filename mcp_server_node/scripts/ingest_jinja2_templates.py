#!/usr/bin/env python3
"""
Phase 40 Step 40-4: Jinja2 Template Ingestion for ChromaDB

Parses .j2 template files from dev/parm/config/ and dev/workflow/rocoto/,
extracts template variables, conditionals, and loops, and ingests into
ChromaDB for semantic search.

ChromaDB: code-with-context-v8-0-0, metadata file_type='jinja2-template'

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
from typing import Dict, List

try:
    import chromadb
    from chromadb.utils import embedding_functions
except ImportError:
    print("[ERROR] chromadb package not found. Install: pip install chromadb")
    sys.exit(1)


# ============================================================================
# CONFIGURATION
# ============================================================================

VERSION = "40.1.0"
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))
EMBEDDING_MODEL = "all-mpnet-base-v2"
COLLECTION_NAME = os.getenv("CODE_COLLECTION", "code-with-context-v8-0-0")

WORKFLOW_ROOT = os.getenv("WORKFLOW_ROOT",
    "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow_develop")

TEMPLATE_LOCATIONS = [
    'dev/parm/config/gfs',
    'dev/parm/config/gefs',
    'dev/parm/config/gcafs',
    'dev/parm/config/sfs',
    'dev/workflow/rocoto',
]


# ============================================================================
# JINJA2 TEMPLATE PARSER
# ============================================================================

class Jinja2TemplateParser:
    """Parse Jinja2 template files to extract variables, conditionals, loops."""

    # {{ variable }} or {{ variable | filter }}
    JINJA_VAR = re.compile(
        r'\{\{\s*([\w.]+(?:\s*\|\s*\w+(?:\([^)]*\))?)*)\s*\}\}')
    # {% if/for/elif/else/endif/endfor/set/block %}
    JINJA_BLOCK = re.compile(
        r'\{%[-\s]*(if|for|elif|else|endif|endfor|set|block|endblock|'
        r'macro|endmacro|include|extends)\s*(.*?)\s*[-]?%\}')
    # {# comment #}
    JINJA_COMMENT = re.compile(r'\{#.*?#\}', re.DOTALL)

    @staticmethod
    def parse_template(file_path: str) -> dict:
        """Extract template metadata from a .j2 file.

        Parameters
        ----------
        file_path : str
            Absolute path to the .j2 file.

        Returns
        -------
        dict
            {variables: [...], conditionals: [...], loops: [...],
             filters: [...], raw_content: str, line_count: int}
        """
        try:
            content = Path(file_path).read_text(errors='replace')
        except Exception as e:
            return {'variables': [], 'conditionals': [], 'loops': [],
                    'filters': [], 'raw_content': '', 'line_count': 0,
                    'error': str(e)}

        # Extract variables
        variables = set()
        filters = set()
        for match in Jinja2TemplateParser.JINJA_VAR.finditer(content):
            expr = match.group(1).strip()
            parts = [p.strip() for p in expr.split('|')]
            # First part is the variable name
            var_name = parts[0]
            if var_name:
                variables.add(var_name)
            # Remaining parts are filters
            for f in parts[1:]:
                filter_name = f.split('(')[0].strip()
                if filter_name:
                    filters.add(filter_name)

        # Extract block statements
        conditionals = []
        loops = []
        for match in Jinja2TemplateParser.JINJA_BLOCK.finditer(content):
            block_type = match.group(1)
            block_expr = match.group(2).strip()
            if block_type == 'if':
                conditionals.append(block_expr)
            elif block_type == 'elif':
                conditionals.append(block_expr)
            elif block_type == 'for':
                loops.append(block_expr)

        # Also extract shell-style env var exports (templates mix bash + jinja2)
        shell_exports = set()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith('export '):
                m = re.match(r'export\s+([A-Z_][A-Z0-9_]*)=', stripped)
                if m:
                    shell_exports.add(m.group(1))

        return {
            'variables': sorted(variables),
            'conditionals': conditionals,
            'loops': loops,
            'filters': sorted(filters),
            'shell_exports': sorted(shell_exports),
            'raw_content': content,
            'line_count': len(content.splitlines()),
        }

    @staticmethod
    def classify_template(rel_path: str) -> str:
        """Classify template type based on path.

        Returns
        -------
        str
            'config', 'workflow', or 'script'
        """
        if 'parm/config' in rel_path:
            return 'config'
        elif 'workflow/rocoto' in rel_path:
            return 'workflow'
        elif 'scripts' in rel_path:
            return 'script'
        return 'other'

    @staticmethod
    def detect_system(rel_path: str) -> str:
        """Detect the system from the file path."""
        for system in ['gfs', 'gefs', 'gcafs', 'sfs']:
            if f'config/{system}' in rel_path:
                return system
        return 'common'


# ============================================================================
# JINJA2 INGESTOR
# ============================================================================

class Jinja2Ingestor:
    """Ingest Jinja2 templates into ChromaDB."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.collection = None
        self.stats = defaultdict(int)
        self.errors = []

    def connect(self) -> bool:
        """Connect to ChromaDB."""
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

    def ingest_template(self, rel_path: str, parsed: dict):
        """Add a Jinja2 template as a ChromaDB document."""
        content = parsed.get('raw_content', '')
        if not content.strip():
            return

        template_type = Jinja2TemplateParser.classify_template(rel_path)
        system = Jinja2TemplateParser.detect_system(rel_path)
        filename = Path(rel_path).name

        # Build searchable document
        doc_text = (
            f"# Jinja2 Template: {filename}\n"
            f"# Type: {template_type}, System: {system}\n"
            f"# Path: {rel_path}\n"
            f"# Template variables: {', '.join(parsed['variables'][:20])}\n"
            f"# Conditionals: {len(parsed['conditionals'])}\n"
            f"# Shell exports: {', '.join(parsed['shell_exports'][:20])}\n\n"
            f"{content}"
        )

        doc_id = f"j2-{hashlib.md5(rel_path.encode()).hexdigest()[:12]}"

        metadata = {
            'file_type': 'jinja2-template',
            'template_type': template_type,
            'system': system,
            'file_path': rel_path,
            'filename': filename,
            'template_variables': json.dumps(parsed['variables'][:50]),
            'variable_count': len(parsed['variables']),
            'conditional_count': len(parsed['conditionals']),
            'loop_count': len(parsed['loops']),
            'filter_count': len(parsed['filters']),
            'shell_export_count': len(parsed['shell_exports']),
            'source': 'phase40_jinja2_ingestion',
            'version': VERSION,
        }

        try:
            self.collection.add(
                ids=[doc_id],
                documents=[doc_text],
                metadatas=[metadata]
            )
            self.stats['docs'] += 1
        except Exception as e:
            self.errors.append({'file': rel_path, 'error': str(e)})

    def get_statistics(self) -> dict:
        return dict(self.stats)


# ============================================================================
# FILE DISCOVERY
# ============================================================================

def discover_j2_templates(workflow_root: str) -> List[dict]:
    """Discover all .j2 template files.

    Returns
    -------
    list[dict]
        List of dicts with abs_path, rel_path, filename.
    """
    templates = []
    root = Path(workflow_root)

    for rel_dir in TEMPLATE_LOCATIONS:
        abs_dir = root / rel_dir
        if not abs_dir.is_dir():
            print(f"[WARN] Directory not found: {abs_dir}")
            continue

        for f in sorted(abs_dir.glob("*.j2")):
            if f.is_file():
                templates.append({
                    'abs_path': str(f),
                    'rel_path': str(f.relative_to(root)),
                    'filename': f.name,
                })

    return templates


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Phase 40-4: Jinja2 Template Ingestion for ChromaDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest_jinja2_templates.py --dry-run
  python ingest_jinja2_templates.py --verbose
  python ingest_jinja2_templates.py
        """
    )
    parser.add_argument('--workflow-root', metavar='DIR',
                        default=WORKFLOW_ROOT,
                        help=f'Path to global-workflow (default: {WORKFLOW_ROOT})')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Parse without writing to ChromaDB')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show per-file details')
    parser.add_argument('--version', action='version',
                        version=f'%(prog)s {VERSION}')

    args = parser.parse_args()

    print(f"[STEP 1] Jinja2 Template Ingestion v{VERSION}")
    print(f"  Workflow root: {args.workflow_root}")

    # Discover templates
    templates = discover_j2_templates(args.workflow_root)
    print(f"[SCAN] Found {len(templates)} Jinja2 templates")

    if not templates:
        print("[WARN] No templates found. Exiting.")
        return

    # Parse
    print(f"\n[STEP 2] Parsing templates...")
    total_vars = 0
    total_conds = 0
    total_loops = 0
    parsed_templates = []

    for tmpl in templates:
        parsed = Jinja2TemplateParser.parse_template(tmpl['abs_path'])
        parsed_templates.append((tmpl, parsed))
        total_vars += len(parsed['variables'])
        total_conds += len(parsed['conditionals'])
        total_loops += len(parsed['loops'])

        if args.verbose:
            vars_str = ', '.join(parsed['variables'][:5])
            if len(parsed['variables']) > 5:
                vars_str += '...'
            print(f"  {tmpl['rel_path']}: {len(parsed['variables'])} vars "
                  f"[{vars_str}], {len(parsed['conditionals'])} conds, "
                  f"{len(parsed['loops'])} loops")

    print(f"\n  Parse Summary:")
    print(f"    Templates:    {len(templates)}")
    print(f"    Variables:    {total_vars}")
    print(f"    Conditionals: {total_conds}")
    print(f"    Loops:        {total_loops}")

    if args.dry_run:
        print(f"\n{'=' * 60}")
        print(f"  DRY-RUN SUMMARY (no database writes)")
        print(f"{'=' * 60}")
        print(f"  Would add {len(templates)} ChromaDB documents")
        print(f"{'=' * 60}")
        print(f"\n  Re-run without --dry-run to write to ChromaDB.")
        return

    # Live mode
    print(f"\n[STEP 3] Connecting to ChromaDB...")
    ingestor = Jinja2Ingestor()
    if not ingestor.connect():
        return

    print(f"\n[STEP 4] Ingesting {len(templates)} templates...")
    for tmpl, parsed in parsed_templates:
        ingestor.ingest_template(tmpl['rel_path'], parsed)

    stats = ingestor.get_statistics()
    print(f"\n{'=' * 60}")
    print(f"  INGESTION COMPLETE")
    print(f"{'=' * 60}")
    print(f"  ChromaDB docs: {stats.get('docs', 0)}")
    print(f"  Errors:        {len(ingestor.errors)}")
    print(f"{'=' * 60}")

    if ingestor.errors:
        print(f"\n[WARN] {len(ingestor.errors)} errors:")
        for err in ingestor.errors[:10]:
            print(f"  {err}")

    print("\n[OK] Done.")


if __name__ == '__main__':
    main()
