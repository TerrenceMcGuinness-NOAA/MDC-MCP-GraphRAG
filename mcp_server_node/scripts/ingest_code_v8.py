#!/usr/bin/env python3
"""
Graph-Enriched Code Ingestion v8.0.0
MPNet 768-dim embeddings with v8 collection naming

This script creates vector embeddings with Neo4j graph enrichment
using MPNet (768 dimensions) for consistency with J-Jobs and documentation.

Collection: code-with-context-v8-0-0
Graph: Neo4j nodes (File, Function, Class, Module) with relationships

Author: NOAA EMC Global Workflow MCP Team
Version: 8.0.0
Date: February 4, 2026
"""

import os
import sys
import ast
import re
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from datetime import datetime
from collections import defaultdict

# Import database clients
try:
    import chromadb
    from chromadb.utils import embedding_functions
    from neo4j import GraphDatabase
except ImportError as e:
    print(f"[ERROR] Missing dependency: {e}")
    print("Install: pip install chromadb neo4j")
    sys.exit(1)

# Try to import SentenceTransformers for explicit embedding verification
try:
    from sentence_transformers import SentenceTransformer
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False


# ============================================================================
# V8 CONFIGURATION - MPNet 768-dim
# ============================================================================

VERSION = "8.0.0"
COLLECTION_NAME = os.getenv("CODE_COLLECTION", "code-with-context-v8-0-0")
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "gfsworkflow2025")

# Embedding model - MUST match jjobs-v8-0-0 and documentation
EMBEDDING_MODEL = "all-mpnet-base-v2"
EMBEDDING_DIMENSIONS = 768

# Source paths (use submodule)
WORKFLOW_ROOT = os.getenv("WORKFLOW_ROOT", 
    "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow")

# Language configurations
PYTHON_EXTENSIONS = ['.py']
SHELL_EXTENSIONS = ['.sh', '.bash', '.ksh']
FORTRAN_EXTENSIONS = ['.f90', '.F90', '.f', '.F', '.f77', '.F77']

# Directories to scan - INCLUDING dev/ structure
CODE_DIRECTORIES = [
    'dev/scripts',      # ex-scripts (exgdas_*, exgfs_*)
    'dev/jobs',         # J-Jobs (handled separately but included for reference)
    'ush',              # Utility shell scripts
    'sorc',             # Source code (Fortran, C)
    'workflow',         # Workflow Python code
    'scripts',          # Legacy scripts (if any remain)
]

# Chunking parameters
MIN_CHUNK_SIZE = 200
MAX_CHUNK_SIZE = 2000
CONTEXT_LINES_BEFORE = 3
CONTEXT_LINES_AFTER = 3


# ============================================================================
# CODE STRUCTURE PARSER
# ============================================================================

class CodeStructureParser:
    """Parse code files to extract structural information"""
    
    def __init__(self):
        self.stats = defaultdict(int)
    
    def parse_file(self, file_path: str, content: str, language: str) -> Dict:
        """Parse file and extract structure"""
        if language == 'python':
            return self._parse_python(file_path, content)
        elif language == 'shell':
            return self._parse_shell(file_path, content)
        elif language == 'fortran':
            return self._parse_fortran(file_path, content)
        else:
            return self._empty_structure(file_path, language)
    
    def _parse_python(self, file_path: str, content: str) -> Dict:
        """Parse Python file with AST"""
        structure = {
            'file_path': file_path,
            'language': 'python',
            'imports': [],
            'functions': [],
            'classes': [],
            'module_docstring': ''
        }
        
        try:
            tree = ast.parse(content)
            
            # Get module docstring
            if (tree.body and isinstance(tree.body[0], ast.Expr) and 
                isinstance(tree.body[0].value, ast.Constant)):
                structure['module_docstring'] = str(tree.body[0].value.value)[:500]
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        structure['imports'].append(alias.name)
                        self.stats['imports'] += 1
                
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ''
                    for alias in node.names:
                        structure['imports'].append(f"{module}.{alias.name}")
                        self.stats['imports'] += 1
                
                elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    func_info = {
                        'name': node.name,
                        'line_start': node.lineno,
                        'line_end': getattr(node, 'end_lineno', node.lineno + 10),
                        'docstring': ast.get_docstring(node) or '',
                        'args': [arg.arg for arg in node.args.args],
                        'decorators': [self._get_decorator_name(d) for d in node.decorator_list]
                    }
                    structure['functions'].append(func_info)
                    self.stats['functions'] += 1
                
                elif isinstance(node, ast.ClassDef):
                    class_info = {
                        'name': node.name,
                        'line_start': node.lineno,
                        'line_end': getattr(node, 'end_lineno', node.lineno + 20),
                        'docstring': ast.get_docstring(node) or '',
                        'bases': [self._get_name(b) for b in node.bases],
                        'methods': []
                    }
                    
                    # Get methods
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            class_info['methods'].append(item.name)
                    
                    structure['classes'].append(class_info)
                    self.stats['classes'] += 1
        
        except SyntaxError as e:
            print(f"  [WARN] Python syntax error in {file_path}: {e}")
        
        return structure
    
    def _parse_shell(self, file_path: str, content: str) -> Dict:
        """Parse Shell script for functions and sources"""
        structure = {
            'file_path': file_path,
            'language': 'shell',
            'functions': [],
            'sources': [],
            'exports': []
        }
        
        lines = content.split('\n')
        
        # Regex patterns
        func_pattern = re.compile(r'^(?:function\s+)?(\w+)\s*\(\s*\)\s*\{?')
        source_pattern = re.compile(r'(?:source|\.|\.)\s+["\']?([^"\';\s]+)["\']?')
        export_pattern = re.compile(r'^export\s+(\w+)=')
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Functions
            match = func_pattern.match(stripped)
            if match:
                func_name = match.group(1)
                # Find function end (simple heuristic)
                end_line = i + 1
                brace_count = 1 if '{' in line else 0
                for j in range(i + 1, min(i + 200, len(lines))):
                    brace_count += lines[j].count('{') - lines[j].count('}')
                    if brace_count <= 0:
                        end_line = j + 1
                        break
                
                structure['functions'].append({
                    'name': func_name,
                    'line_start': i + 1,
                    'line_end': end_line,
                    'docstring': ''
                })
                self.stats['functions'] += 1
            
            # Source statements
            match = source_pattern.search(stripped)
            if match and not stripped.startswith('#'):
                structure['sources'].append(match.group(1))
            
            # Exports
            match = export_pattern.match(stripped)
            if match:
                structure['exports'].append(match.group(1))
        
        return structure
    
    def _parse_fortran(self, file_path: str, content: str) -> Dict:
        """Parse Fortran file for subroutines, functions, and modules"""
        structure = {
            'file_path': file_path,
            'language': 'fortran',
            'functions': [],
            'subroutines': [],
            'modules': [],
            'uses': []
        }
        
        lines = content.split('\n')
        
        # Fortran patterns (case-insensitive)
        subroutine_pattern = re.compile(r'^\s*subroutine\s+(\w+)', re.IGNORECASE)
        function_pattern = re.compile(r'^\s*(?:[\w\(\)\*]+\s+)?function\s+(\w+)', re.IGNORECASE)
        module_pattern = re.compile(r'^\s*module\s+(\w+)(?!\s+procedure)', re.IGNORECASE)
        program_pattern = re.compile(r'^\s*program\s+(\w+)', re.IGNORECASE)
        use_pattern = re.compile(r'^\s*use\s+(\w+)', re.IGNORECASE)
        end_pattern = re.compile(r'^\s*end\s+(subroutine|function|module|program)', re.IGNORECASE)
        
        in_unit = None
        unit_start = 0
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Skip comments
            if stripped.startswith('!') or stripped.startswith('c') or stripped.startswith('C'):
                continue
            
            # Uses
            match = use_pattern.match(stripped)
            if match:
                structure['uses'].append(match.group(1))
                self.stats['imports'] += 1
            
            # Subroutines
            match = subroutine_pattern.match(stripped)
            if match:
                if in_unit:
                    # Close previous unit
                    structure['subroutines'].append({
                        'name': in_unit,
                        'line_start': unit_start + 1,
                        'line_end': i,
                        'docstring': ''
                    })
                in_unit = match.group(1)
                unit_start = i
                self.stats['functions'] += 1
            
            # Functions
            match = function_pattern.match(stripped)
            if match:
                if in_unit:
                    structure['functions'].append({
                        'name': in_unit,
                        'line_start': unit_start + 1,
                        'line_end': i,
                        'docstring': ''
                    })
                in_unit = match.group(1)
                unit_start = i
                self.stats['functions'] += 1
            
            # Modules
            match = module_pattern.match(stripped)
            if match:
                structure['modules'].append({
                    'name': match.group(1),
                    'line_start': i + 1
                })
                self.stats['classes'] += 1  # Count as "class" for stats
            
            # Program
            match = program_pattern.match(stripped)
            if match:
                in_unit = match.group(1)
                unit_start = i
            
            # End of unit
            match = end_pattern.match(stripped)
            if match and in_unit:
                unit_type = match.group(1).lower()
                if unit_type == 'subroutine':
                    structure['subroutines'].append({
                        'name': in_unit,
                        'line_start': unit_start + 1,
                        'line_end': i + 1,
                        'docstring': ''
                    })
                elif unit_type == 'function':
                    structure['functions'].append({
                        'name': in_unit,
                        'line_start': unit_start + 1,
                        'line_end': i + 1,
                        'docstring': ''
                    })
                in_unit = None
        
        return structure
    
    def _get_decorator_name(self, node) -> str:
        """Get decorator name from AST node"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return self._get_decorator_name(node.func)
        return 'unknown'
    
    def _get_name(self, node) -> str:
        """Get name from AST node"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        return 'unknown'
    
    def _empty_structure(self, file_path: str, language: str) -> Dict:
        """Return empty structure for unsupported languages"""
        return {
            'file_path': file_path,
            'language': language,
            'functions': [],
            'classes': []
        }


# ============================================================================
# GRAPH DATABASE CLIENT
# ============================================================================

class GraphDatabaseClient:
    """Neo4j graph database client for code relationships"""
    
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
            print(f"[WARN] Neo4j connection failed: {e}")
            print("[WARN] Continuing without graph enrichment")
            self.driver = None
    
    def close(self):
        if self.driver:
            self.driver.close()
    
    def create_file_node(self, file_path: str, language: str, structure: Dict):
        """Create File node in graph"""
        if not self.driver:
            return
        
        query = """
        MERGE (f:File {path: $file_path})
        SET f.language = $language,
            f.version = $version,
            f.updated_at = $updated_at
        """
        with self.driver.session() as session:
            session.run(query, 
                       file_path=file_path, 
                       language=language,
                       version=VERSION,
                       updated_at=datetime.now().isoformat())
    
    def create_function_node(self, file_path: str, func: Dict, language: str):
        """Create Function node linked to File"""
        if not self.driver:
            return
        
        query = """
        MATCH (f:File {path: $file_path})
        MERGE (fn:Function {name: $name, file: $file_path})
        SET fn.line_start = $line_start,
            fn.line_end = $line_end,
            fn.docstring = $docstring,
            fn.language = $language
        MERGE (f)-[:DEFINES]->(fn)
        """
        with self.driver.session() as session:
            session.run(query, 
                       file_path=file_path,
                       name=func['name'],
                       line_start=func.get('line_start', 0),
                       line_end=func.get('line_end', 0),
                       docstring=func.get('docstring', '')[:500],
                       language=language)
    
    def create_import_relationship(self, file_path: str, imported: str):
        """Create IMPORTS relationship"""
        if not self.driver:
            return
        
        query = """
        MATCH (f:File {path: $file_path})
        MERGE (m:Module {name: $imported})
        MERGE (f)-[:IMPORTS]->(m)
        """
        with self.driver.session() as session:
            session.run(query, file_path=file_path, imported=imported)
    
    def create_fortran_use_relationship(self, file_path: str, used_module: str):
        """Create USES relationship for Fortran modules"""
        if not self.driver:
            return
        
        query = """
        MATCH (f:File {path: $file_path})
        MERGE (m:FortranModule {name: $used_module})
        MERGE (f)-[:USES]->(m)
        """
        with self.driver.session() as session:
            session.run(query, file_path=file_path, used_module=used_module)


# ============================================================================
# CODE INGESTER V8 - WITH MPNET EMBEDDINGS
# ============================================================================

class CodeIngesterV8:
    """V8 Code ingester with MPNet embeddings and graph enrichment"""
    
    def __init__(self, collection_name: str = COLLECTION_NAME):
        self.collection_name = collection_name
        self.parser = CodeStructureParser()
        self.graph = GraphDatabaseClient()
        
        # Initialize ChromaDB with MPNet embedding function
        self.chroma = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
        
        # Create embedding function
        print(f"[OK] Loading embedding model: {EMBEDDING_MODEL}")
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        
        # Get or create collection with MPNet
        try:
            self.collection = self.chroma.get_collection(
                name=collection_name,
                embedding_function=self.embedding_fn
            )
            print(f"[OK] Using existing collection: {collection_name} ({self.collection.count()} docs)")
        except:
            self.collection = self.chroma.create_collection(
                name=collection_name,
                embedding_function=self.embedding_fn,
                metadata={
                    "version": VERSION,
                    "type": "code",
                    "embedding_model": EMBEDDING_MODEL,
                    "embedding_dimensions": str(EMBEDDING_DIMENSIONS),
                    "created": datetime.now().isoformat()
                }
            )
            print(f"[OK] Created new collection: {collection_name}")
        
        self.stats = {
            'files_processed': 0,
            'chunks_created': 0,
            'functions_indexed': 0,
            'classes_indexed': 0,
            'subroutines_indexed': 0,
            'fortran_files': 0,
            'imports_indexed': 0,
            'errors': 0
        }
        self.seen_ids = set()
    
    def ingest_directory(self, root_path: str = WORKFLOW_ROOT):
        """Ingest all code from workflow directory"""
        print(f"\n{'='*70}")
        print(f"Code Ingestion v{VERSION} - MPNet Embeddings")
        print(f"{'='*70}")
        print(f"Collection: {self.collection_name}")
        print(f"Embedding:  {EMBEDDING_MODEL} ({EMBEDDING_DIMENSIONS} dimensions)")
        print(f"Source:     {root_path}")
        print(f"{'='*70}\n")
        
        for code_dir in CODE_DIRECTORIES:
            dir_path = Path(root_path) / code_dir
            if dir_path.exists():
                print(f"\n[DIR] Processing {code_dir}/")
                self._process_directory(dir_path)
            else:
                print(f"[SKIP] Directory not found: {code_dir}/")
        
        # Also process sorc/ subdirectories for Fortran
        sorc_path = Path(root_path) / 'sorc'
        if sorc_path.exists():
            print(f"\n[DIR] Processing sorc/ for Fortran sources")
            self._process_sorc_directory(sorc_path)
        
        self._print_summary()
        self.graph.close()
    
    def _process_sorc_directory(self, sorc_path: Path):
        """Process sorc/ directory recursively for Fortran files"""
        for subdir in sorc_path.iterdir():
            if subdir.is_dir():
                print(f"  [SUBDIR] {subdir.name}/")
                self._process_directory(subdir, fortran_focus=True)
    
    def _process_directory(self, dir_path: Path, fortran_focus: bool = False):
        """Process all code files in directory"""
        for file_path in dir_path.rglob('*'):
            if not file_path.is_file():
                continue
            
            language = self._detect_language(file_path)
            if language is None:
                continue
            
            # Skip J-Jobs (handled by ingest_jjobs_v8.py)
            if language == 'shell' and file_path.name.startswith('J') and file_path.name.isupper():
                continue
            
            try:
                # Read and parse file
                content = file_path.read_text(errors='replace')
                
                # Skip very small files
                if len(content) < 50:
                    continue
                
                rel_path = str(file_path.relative_to(dir_path.parent.parent))
                # Phase 38: Strip leading repo directory name to ensure consistent relative paths
                _repo_dir = os.path.basename(str(dir_path.parent))
                if rel_path.startswith(_repo_dir + "/"):
                    rel_path = rel_path[len(_repo_dir) + 1:]
                
                # Parse structure
                structure = self.parser.parse_file(rel_path, content, language)
                
                # Create graph nodes
                self.graph.create_file_node(rel_path, language, structure)
                
                # Index functions/subroutines
                for func in structure.get('functions', []):
                    self.graph.create_function_node(rel_path, func, language)
                    self.stats['functions_indexed'] += 1
                
                for sub in structure.get('subroutines', []):
                    self.graph.create_function_node(rel_path, sub, language)
                    self.stats['subroutines_indexed'] += 1
                
                # Index imports
                for imp in structure.get('imports', []):
                    self.graph.create_import_relationship(rel_path, imp)
                    self.stats['imports_indexed'] += 1
                
                # Index Fortran uses
                for use in structure.get('uses', []):
                    self.graph.create_fortran_use_relationship(rel_path, use)
                    self.stats['imports_indexed'] += 1
                
                # Count Fortran files
                if language == 'fortran':
                    self.stats['fortran_files'] += 1
                
                # Create chunks for vector DB
                chunks = self._create_chunks(rel_path, content, language, structure)
                
                for chunk in chunks:
                    doc_id = self._generate_id(chunk['text'], rel_path)
                    if doc_id not in self.seen_ids:
                        self.seen_ids.add(doc_id)
                        self.collection.add(
                            ids=[doc_id],
                            documents=[chunk['text']],
                            metadatas=[chunk['metadata']]
                        )
                        self.stats['chunks_created'] += 1
                
                self.stats['files_processed'] += 1
                
            except Exception as e:
                print(f"  [ERROR] {file_path}: {e}")
                self.stats['errors'] += 1
    
    def _detect_language(self, file_path: Path) -> Optional[str]:
        """Detect language from file extension"""
        suffix = file_path.suffix.lower()
        if suffix in PYTHON_EXTENSIONS:
            return 'python'
        elif suffix in SHELL_EXTENSIONS:
            return 'shell'
        elif suffix in FORTRAN_EXTENSIONS:
            return 'fortran'
        return None
    
    def _create_chunks(self, file_path: str, content: str, language: str, 
                       structure: Dict) -> List[Dict]:
        """Create semantic chunks from code file"""
        chunks = []
        lines = content.split('\n')
        
        # Get all units (functions, subroutines)
        all_units = structure.get('functions', []) + structure.get('subroutines', [])
        
        # Create function/subroutine-level chunks
        for unit in all_units:
            start = max(0, unit['line_start'] - CONTEXT_LINES_BEFORE - 1)
            end = min(len(lines), unit['line_end'] + CONTEXT_LINES_AFTER)
            
            chunk_text = '\n'.join(lines[start:end])
            if MIN_CHUNK_SIZE <= len(chunk_text) <= MAX_CHUNK_SIZE:
                unit_type = 'subroutine' if 'subroutines' in structure and unit in structure.get('subroutines', []) else 'function'
                chunks.append({
                    'text': chunk_text,
                    'metadata': {
                        'file_path': file_path,
                        'language': language,
                        'type': unit_type,
                        'name': unit['name'],
                        'line_start': unit['line_start'],
                        'line_end': unit['line_end'],
                        'docstring': unit.get('docstring', '')[:200],
                        'version': VERSION,
                        'embedding_model': EMBEDDING_MODEL,
                        'ingested_at': datetime.now().isoformat()
                    }
                })
        
        # Create file-level chunk if no units found or for small files
        if not all_units:
            if MIN_CHUNK_SIZE <= len(content) <= MAX_CHUNK_SIZE * 2:
                chunks.append({
                    'text': content[:MAX_CHUNK_SIZE],
                    'metadata': {
                        'file_path': file_path,
                        'language': language,
                        'type': 'file',
                        'version': VERSION,
                        'embedding_model': EMBEDDING_MODEL,
                        'ingested_at': datetime.now().isoformat()
                    }
                })
        
        return chunks
    
    def _generate_id(self, text: str, file_path: str) -> str:
        """Generate unique document ID"""
        content = f"{file_path}:{text[:500]}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _print_summary(self):
        """Print ingestion summary"""
        print(f"\n{'='*70}")
        print("CODE INGESTION SUMMARY")
        print(f"{'='*70}")
        print(f"Collection:           {self.collection_name}")
        print(f"Version:              {VERSION}")
        print(f"Embedding Model:      {EMBEDDING_MODEL} ({EMBEDDING_DIMENSIONS}-dim)")
        print(f"Files processed:      {self.stats['files_processed']}")
        print(f"  - Fortran files:    {self.stats['fortran_files']}")
        print(f"Chunks created:       {self.stats['chunks_created']}")
        print(f"Functions indexed:    {self.stats['functions_indexed']}")
        print(f"Subroutines indexed:  {self.stats['subroutines_indexed']}")
        print(f"Classes indexed:      {self.stats['classes_indexed']}")
        print(f"Imports/Uses indexed: {self.stats['imports_indexed']}")
        print(f"Errors:               {self.stats['errors']}")
        print(f"{'='*70}")
        print(f"Total in collection:  {self.collection.count()} documents")
        print(f"{'='*70}\n")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='V8 Code Ingestion with MPNet Embeddings')
    parser.add_argument('--collection', default=COLLECTION_NAME,
                       help=f'Collection name (default: {COLLECTION_NAME})')
    parser.add_argument('--root', default=WORKFLOW_ROOT,
                       help=f'Workflow root path (default: {WORKFLOW_ROOT})')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be processed without ingesting')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("CODE INGESTION V8.0.0 - MPNet Embeddings")
    print("=" * 70)
    print(f"Languages: Python, Shell, Fortran")
    print(f"Embedding: {EMBEDDING_MODEL} ({EMBEDDING_DIMENSIONS} dimensions)")
    print("=" * 70)
    
    if args.dry_run:
        print("\n[DRY RUN] Would process the following directories:")
        for code_dir in CODE_DIRECTORIES:
            dir_path = Path(args.root) / code_dir
            if dir_path.exists():
                # Count by language
                py_count = sum(1 for _ in dir_path.rglob('*.py'))
                sh_count = sum(1 for ext in SHELL_EXTENSIONS for _ in dir_path.rglob(f'*{ext}'))
                f_count = sum(1 for ext in FORTRAN_EXTENSIONS for _ in dir_path.rglob(f'*{ext}'))
                print(f"  - {code_dir}/: Python={py_count}, Shell={sh_count}, Fortran={f_count}")
            else:
                print(f"  - {code_dir}/: (not found)")
        
        # Check sorc/ separately
        sorc_path = Path(args.root) / 'sorc'
        if sorc_path.exists():
            f_count = sum(1 for ext in FORTRAN_EXTENSIONS for _ in sorc_path.rglob(f'*{ext}'))
            print(f"  - sorc/: Fortran={f_count}")
        return
    
    ingester = CodeIngesterV8(args.collection)
    ingester.ingest_directory(args.root)


if __name__ == '__main__':
    main()
