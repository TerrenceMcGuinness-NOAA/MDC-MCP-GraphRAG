#!/usr/bin/env python3
"""
Graph-Enriched Code Ingestion v7.0.0
Unified code ingestion with v7 collection naming

This script creates vector embeddings with Neo4j graph enrichment
using consistent v7 naming convention.

Collection: code-with-context-v7-0-0
Graph: Neo4j nodes (File, Function, Class, Module) with relationships

Author: NOAA EMC Global Workflow MCP Team
Version: 7.0.0
Date: December 3, 2025
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
    from neo4j import GraphDatabase
except ImportError as e:
    print(f"[ERROR] Missing dependency: {e}")
    print("Install: pip install chromadb neo4j")
    sys.exit(1)


# ============================================================================
# V7 CONFIGURATION
# ============================================================================

VERSION = "7.0.0"
COLLECTION_NAME = os.getenv("CODE_COLLECTION", "code-with-context-v7-0-0")
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "gfsworkflow2025")

# Source paths (use submodule)
WORKFLOW_ROOT = os.getenv("WORKFLOW_ROOT", 
    "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow")

# Language configurations
PYTHON_EXTENSIONS = ['.py']
SHELL_EXTENSIONS = ['.sh', '.bash', '.ksh']
FORTRAN_EXTENSIONS = ['.f90', '.F90', '.f', '.F']

# Directories to scan
CODE_DIRECTORIES = [
    'scripts',
    'ush',
    'jobs',
    'workflow',
    'sorc',
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
            'global_calls': []
        }
        
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        structure['imports'].append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        structure['imports'].append(node.module)
                elif isinstance(node, ast.FunctionDef):
                    func_info = {
                        'name': node.name,
                        'line_start': node.lineno,
                        'line_end': node.end_lineno or node.lineno,
                        'docstring': ast.get_docstring(node) or '',
                        'calls': []
                    }
                    # Extract function calls
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            if isinstance(child.func, ast.Name):
                                func_info['calls'].append(child.func.id)
                    structure['functions'].append(func_info)
                elif isinstance(node, ast.ClassDef):
                    class_info = {
                        'name': node.name,
                        'line_start': node.lineno,
                        'methods': [m.name for m in node.body if isinstance(m, ast.FunctionDef)]
                    }
                    structure['classes'].append(class_info)
                    
        except SyntaxError as e:
            self.stats['parse_errors'] += 1
            
        return structure
    
    def _parse_shell(self, file_path: str, content: str) -> Dict:
        """Parse shell script (basic)"""
        structure = {
            'file_path': file_path,
            'language': 'shell',
            'imports': [],
            'functions': [],
            'classes': [],
            'global_calls': []
        }
        
        # Extract sourced files
        for match in re.finditer(r'^\s*(?:source|\.)\s+([^\s#]+)', content, re.MULTILINE):
            structure['imports'].append(match.group(1))
        
        # Extract function definitions
        for match in re.finditer(r'^(\w+)\s*\(\)\s*\{', content, re.MULTILINE):
            structure['functions'].append({
                'name': match.group(1),
                'line_start': content[:match.start()].count('\n') + 1,
                'line_end': 0,
                'docstring': '',
                'calls': []
            })
        
        return structure
    
    def _empty_structure(self, file_path: str, language: str) -> Dict:
        """Return empty structure for unsupported languages"""
        return {
            'file_path': file_path,
            'language': language,
            'imports': [],
            'functions': [],
            'classes': [],
            'global_calls': []
        }


# ============================================================================
# GRAPH DATABASE CLIENT
# ============================================================================

class GraphDatabaseClient:
    """Neo4j graph database client for code relationships"""
    
    def __init__(self, uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD):
        self.driver = None
        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            self.driver.verify_connectivity()
            print(f"[OK] Connected to Neo4j: {uri}")
        except Exception as e:
            print(f"[WARN] Neo4j connection failed: {e}")
            print("   Continuing without graph enrichment...")
    
    def close(self):
        if self.driver:
            self.driver.close()
    
    def create_file_node(self, file_path: str, metadata: Dict):
        """Create or update file node"""
        if not self.driver:
            return
        
        query = """
        MERGE (f:File {path: $path})
        SET f.language = $language,
            f.updated_at = datetime(),
            f.version = $version
        """
        with self.driver.session() as session:
            session.run(query, path=file_path, 
                       language=metadata.get('language', 'unknown'),
                       version=VERSION)
    
    def create_function_node(self, file_path: str, func: Dict):
        """Create function node and link to file"""
        if not self.driver:
            return
        
        query = """
        MATCH (f:File {path: $file_path})
        MERGE (fn:Function {name: $name, file: $file_path})
        SET fn.line_start = $line_start,
            fn.line_end = $line_end,
            fn.docstring = $docstring
        MERGE (f)-[:DEFINES]->(fn)
        """
        with self.driver.session() as session:
            session.run(query, 
                       file_path=file_path,
                       name=func['name'],
                       line_start=func.get('line_start', 0),
                       line_end=func.get('line_end', 0),
                       docstring=func.get('docstring', '')[:500])
    
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
    
    def create_calls_relationship(self, caller_file: str, caller_func: str, called_func: str):
        """Create CALLS relationship between functions"""
        if not self.driver:
            return
        
        query = """
        MATCH (caller:Function {name: $caller_func, file: $caller_file})
        MERGE (called:Function {name: $called_func})
        MERGE (caller)-[:CALLS]->(called)
        """
        with self.driver.session() as session:
            session.run(query, 
                       caller_file=caller_file,
                       caller_func=caller_func,
                       called_func=called_func)


# ============================================================================
# CODE INGESTER
# ============================================================================

class CodeIngesterV7:
    """V7 Code ingester with graph enrichment"""
    
    def __init__(self, collection_name: str = COLLECTION_NAME):
        self.collection_name = collection_name
        self.parser = CodeStructureParser()
        self.graph = GraphDatabaseClient()
        
        # Initialize ChromaDB
        self.chroma = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
        self.collection = self.chroma.get_or_create_collection(
            name=collection_name,
            metadata={"version": VERSION, "type": "code"}
        )
        
        self.stats = {
            'files_processed': 0,
            'chunks_created': 0,
            'functions_indexed': 0,
            'classes_indexed': 0,
            'imports_indexed': 0,
            'errors': 0
        }
        self.seen_ids = set()
    
    def ingest_directory(self, root_path: str = WORKFLOW_ROOT):
        """Ingest all code from workflow directory"""
        print(f"\n{'='*70}")
        print(f"Code Ingestion v{VERSION}")
        print(f"Collection: {self.collection_name}")
        print(f"Source: {root_path}")
        print(f"{'='*70}\n")
        
        for code_dir in CODE_DIRECTORIES:
            dir_path = Path(root_path) / code_dir
            if dir_path.exists():
                print(f"\n[DIR] Processing {code_dir}/")
                self._process_directory(dir_path)
            else:
                print(f"[SKIP] Directory not found: {code_dir}/")
        
        self._print_summary()
        self.graph.close()
    
    def _process_directory(self, dir_path: Path):
        """Process all code files in directory"""
        for file_path in dir_path.rglob('*'):
            if not file_path.is_file():
                continue
            
            language = self._detect_language(file_path)
            if language is None:
                continue
            
            try:
                content = file_path.read_text(errors='replace')
                rel_path = str(file_path.relative_to(WORKFLOW_ROOT))
                
                # Parse structure
                structure = self.parser.parse_file(rel_path, content, language)
                
                # Create graph nodes
                self.graph.create_file_node(rel_path, {'language': language})
                
                for imp in structure['imports']:
                    self.graph.create_import_relationship(rel_path, imp)
                    self.stats['imports_indexed'] += 1
                
                for func in structure['functions']:
                    self.graph.create_function_node(rel_path, func)
                    self.stats['functions_indexed'] += 1
                    
                    for called in func.get('calls', []):
                        self.graph.create_calls_relationship(rel_path, func['name'], called)
                
                for cls in structure['classes']:
                    self.stats['classes_indexed'] += 1
                
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
        
        # Create function-level chunks
        for func in structure['functions']:
            start = max(0, func['line_start'] - CONTEXT_LINES_BEFORE - 1)
            end = min(len(lines), func['line_end'] + CONTEXT_LINES_AFTER)
            
            chunk_text = '\n'.join(lines[start:end])
            if MIN_CHUNK_SIZE <= len(chunk_text) <= MAX_CHUNK_SIZE:
                chunks.append({
                    'text': chunk_text,
                    'metadata': {
                        'file_path': file_path,
                        'language': language,
                        'type': 'function',
                        'name': func['name'],
                        'line_start': func['line_start'],
                        'line_end': func['line_end'],
                        'docstring': func.get('docstring', '')[:200],
                        'version': VERSION,
                        'ingested_at': datetime.now().isoformat()
                    }
                })
        
        # Create file-level chunk if no functions
        if not structure['functions']:
            if MIN_CHUNK_SIZE <= len(content) <= MAX_CHUNK_SIZE * 2:
                chunks.append({
                    'text': content[:MAX_CHUNK_SIZE],
                    'metadata': {
                        'file_path': file_path,
                        'language': language,
                        'type': 'file',
                        'version': VERSION,
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
        print(f"Collection:         {self.collection_name}")
        print(f"Version:            {VERSION}")
        print(f"Files processed:    {self.stats['files_processed']}")
        print(f"Chunks created:     {self.stats['chunks_created']}")
        print(f"Functions indexed:  {self.stats['functions_indexed']}")
        print(f"Classes indexed:    {self.stats['classes_indexed']}")
        print(f"Imports indexed:    {self.stats['imports_indexed']}")
        print(f"Errors:             {self.stats['errors']}")
        print(f"{'='*70}\n")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='V7 Code Ingestion')
    parser.add_argument('--collection', default=COLLECTION_NAME,
                       help=f'Collection name (default: {COLLECTION_NAME})')
    parser.add_argument('--root', default=WORKFLOW_ROOT,
                       help=f'Workflow root path (default: {WORKFLOW_ROOT})')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be processed without ingesting')
    
    args = parser.parse_args()
    
    if args.dry_run:
        print("[DRY RUN] Would process the following directories:")
        for code_dir in CODE_DIRECTORIES:
            dir_path = Path(args.root) / code_dir
            if dir_path.exists():
                file_count = sum(1 for _ in dir_path.rglob('*') if _.is_file())
                print(f"  - {code_dir}/: {file_count} files")
            else:
                print(f"  - {code_dir}/: (not found)")
        return
    
    ingester = CodeIngesterV7(args.collection)
    ingester.ingest_directory(args.root)


if __name__ == '__main__':
    main()
