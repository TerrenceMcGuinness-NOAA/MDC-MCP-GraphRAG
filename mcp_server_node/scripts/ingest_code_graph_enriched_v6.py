#!/usr/bin/env python3
"""
Graph-Enriched Code Ingestion v6.0.0
Higher-dimensional embeddings with Neo4j relationship folding

This is the ADVANCED ingestion that creates:
1. Vector embeddings with semantic code understanding
2. Graph nodes/relationships in Neo4j for structural analysis
3. ENRICHED embeddings that include graph context in metadata

Architecture:
- Parse: AST extraction of functions, classes, imports, calls
- Graph: Build Neo4j relationships (IMPORTS, CALLS, DEFINES, DEPENDS_ON)
- Enrich: Augment vector embeddings with graph context (neighbors, patterns)
- Store: ChromaDB vectors + Neo4j graph for hybrid search

Collection: code_with_context_v6_graph_enriched
Graph: Neo4j nodes (File, Function, Class, Module) with relationships

Author: NOAA EMC Global Workflow MCP Team
Version: 6.0.0
Date: November 14, 2025
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
# CONFIGURATION
# ============================================================================

COLLECTION_NAME = os.getenv("CODE_COLLECTION", "code_with_context_v7_docker")
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "gfsworkflow2025")

# Source paths (use submodule)
WORKFLOW_ROOT = "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow"

# Language configurations
PYTHON_EXTENSIONS = ['.py']
SHELL_EXTENSIONS = ['.sh', '.bash', '.ksh']
FORTRAN_EXTENSIONS = ['.f90', '.F90', '.f', '.F']

# Chunking parameters
MIN_CHUNK_SIZE = 200
MAX_CHUNK_SIZE = 2000
CONTEXT_LINES_BEFORE = 3
CONTEXT_LINES_AFTER = 3


# ============================================================================
# CODE STRUCTURE PARSER
# ============================================================================

class CodeStructureParser:
    """
    Parse code files to extract structural information for graph building.
    Supports Python, Shell (basic), and Fortran (basic).
    """
    
    def __init__(self):
        self.stats = defaultdict(int)
    
    def parse_file(self, file_path: str, content: str, language: str) -> Dict:
        """
        Parse file and extract structure.
        
        Returns:
            {
                'file_path': str,
                'language': str,
                'imports': [str],
                'functions': [{name, line_start, line_end, calls, docstring}],
                'classes': [{name, line_start, methods}],
                'global_calls': [str]
            }
        """
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
            'global_calls': []
        }
        
        try:
            tree = ast.parse(content)
            
            # Extract imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        structure['imports'].append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        structure['imports'].append(node.module)
            
            # Extract functions and classes
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Get function calls within this function
                    calls = self._extract_calls_from_function(node)
                    
                    structure['functions'].append({
                        'name': node.name,
                        'line_start': node.lineno,
                        'line_end': getattr(node, 'end_lineno', node.lineno + 20),
                        'calls': calls,
                        'docstring': ast.get_docstring(node) or '',
                        'is_async': isinstance(node, ast.AsyncFunctionDef),
                        'args': [arg.arg for arg in node.args.args]
                    })
                    self.stats['functions'] += 1
                    
                elif isinstance(node, ast.ClassDef):
                    # Extract class methods
                    methods = [
                        child.name for child in node.body 
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ]
                    
                    structure['classes'].append({
                        'name': node.name,
                        'line_start': node.lineno,
                        'line_end': getattr(node, 'end_lineno', node.lineno + 50),
                        'methods': methods,
                        'docstring': ast.get_docstring(node) or ''
                    })
                    self.stats['classes'] += 1
            
        except SyntaxError as e:
            print(f"[WARN] Syntax error in {file_path}: {e}")
            self.stats['syntax_errors'] += 1
        except Exception as e:
            print(f"[ERROR] Parse error in {file_path}: {e}")
            self.stats['parse_errors'] += 1
        
        return structure
    
    def _extract_calls_from_function(self, func_node: ast.FunctionDef) -> List[str]:
        """Extract function/method calls from function body"""
        calls = []
        for node in ast.walk(func_node):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.append(node.func.attr)
        return list(set(calls))[:20]  # Limit to 20 unique calls
    
    def _parse_shell(self, file_path: str, content: str) -> Dict:
        """Parse Shell script (regex-based, best effort)"""
        structure = {
            'file_path': file_path,
            'language': 'shell',
            'imports': [],  # Shell "imports" are sourced files
            'functions': [],
            'classes': [],  # N/A for shell
            'global_calls': []
        }
        
        lines = content.split('\n')
        
        # Extract sourced files (shell imports)
        source_pattern = re.compile(r'^\s*(?:source|\.)\ +([^\s]+)')
        for line in lines:
            match = source_pattern.match(line)
            if match:
                structure['imports'].append(match.group(1))
        
        # Extract function definitions
        func_pattern = re.compile(r'^(?:function\s+)?(\w+)\s*\(\)\s*\{?')
        in_function = None
        brace_count = 0
        func_start = 0
        
        for i, line in enumerate(lines, 1):
            func_match = func_pattern.match(line)
            if func_match and not in_function:
                in_function = func_match.group(1)
                func_start = i
                brace_count = line.count('{') - line.count('}')
            elif in_function:
                brace_count += line.count('{') - line.count('}')
                if brace_count <= 0:
                    structure['functions'].append({
                        'name': in_function,
                        'line_start': func_start,
                        'line_end': i,
                        'calls': [],  # TODO: Extract from function body
                        'docstring': ''
                    })
                    self.stats['functions'] += 1
                    in_function = None
        
        return structure
    
    def _parse_fortran(self, file_path: str, content: str) -> Dict:
        """Parse Fortran file (regex-based, basic)"""
        structure = {
            'file_path': file_path,
            'language': 'fortran',
            'imports': [],  # USE statements
            'functions': [],  # SUBROUTINE, FUNCTION
            'classes': [],  # TYPE definitions
            'global_calls': []
        }
        
        lines = content.split('\n')
        
        # Extract USE statements (Fortran imports)
        use_pattern = re.compile(r'^\s*use\s+(\w+)', re.IGNORECASE)
        for line in lines:
            match = use_pattern.match(line)
            if match:
                structure['imports'].append(match.group(1))
        
        # Extract subroutines and functions
        sub_pattern = re.compile(r'^\s*(?:recursive\s+)?subroutine\s+(\w+)', re.IGNORECASE)
        func_pattern = re.compile(r'^\s*(?:recursive\s+)?(?:integer|real|logical|character)?\s*function\s+(\w+)', re.IGNORECASE)
        end_pattern = re.compile(r'^\s*end\s+(?:subroutine|function)', re.IGNORECASE)
        
        in_routine = None
        routine_start = 0
        
        for i, line in enumerate(lines, 1):
            sub_match = sub_pattern.match(line)
            func_match = func_pattern.match(line)
            
            if (sub_match or func_match) and not in_routine:
                in_routine = sub_match.group(1) if sub_match else func_match.group(1)
                routine_start = i
            elif end_pattern.match(line) and in_routine:
                structure['functions'].append({
                    'name': in_routine,
                    'line_start': routine_start,
                    'line_end': i,
                    'calls': [],
                    'docstring': ''
                })
                self.stats['functions'] += 1
                in_routine = None
        
        return structure
    
    def _empty_structure(self, file_path: str, language: str) -> Dict:
        """Return empty structure for unsupported language"""
        return {
            'file_path': file_path,
            'language': language,
            'imports': [],
            'functions': [],
            'classes': [],
            'global_calls': []
        }


# ============================================================================
# NEO4J GRAPH BUILDER
# ============================================================================

class Neo4jGraphBuilder:
    """
    Build Neo4j graph from parsed code structures.
    
    Nodes:
    - File (path, language, loc)
    - Function (name, file, line_start, line_end)
    - Class (name, file)
    - Module (name)
    
    Relationships:
    - (File)-[:IMPORTS]->(Module)
    - (File)-[:DEFINES]->(Function)
    - (File)-[:DEFINES]->(Class)
    - (Function)-[:CALLS]->(Function)
    - (Class)-[:HAS_METHOD]->(Function)
    - (Function)-[:DEPENDS_ON]->(Module)
    """
    
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.stats = defaultdict(int)
    
    def close(self):
        """Close Neo4j connection"""
        self.driver.close()
    
    def clear_code_graph(self, confirm: bool = False):
        """Clear existing code graph (dangerous!)"""
        if not confirm:
            print("[WARN] clear_code_graph called without confirmation")
            return
        
        with self.driver.session() as session:
            # Delete relationships first
            session.run("MATCH ()-[r:IMPORTS|DEFINES|CALLS|HAS_METHOD|DEPENDS_ON]->() DELETE r")
            # Then delete nodes
            session.run("MATCH (n:CodeFile) DETACH DELETE n")
            session.run("MATCH (n:CodeFunction) DETACH DELETE n")
            session.run("MATCH (n:CodeClass) DETACH DELETE n")
            session.run("MATCH (n:CodeModule) DETACH DELETE n")
        
        print("[OK] Code graph cleared")
    
    def create_file_node(self, structure: Dict, content: str):
        """Create File node with metadata"""
        with self.driver.session() as session:
            loc = len(content.split('\n'))
            
            session.run("""
                MERGE (f:CodeFile {path: $path})
                SET f.language = $language,
                    f.loc = $loc,
                    f.num_functions = $num_functions,
                    f.num_classes = $num_classes,
                    f.updated_at = datetime()
            """, 
                path=structure['file_path'],
                language=structure['language'],
                loc=loc,
                num_functions=len(structure['functions']),
                num_classes=len(structure['classes'])
            )
            self.stats['files'] += 1
    
    def create_import_relationships(self, structure: Dict):
        """Create IMPORTS relationships"""
        file_path = structure['file_path']
        
        with self.driver.session() as session:
            for module_name in structure['imports']:
                # Create Module node if not exists
                session.run("""
                    MERGE (m:CodeModule {name: $module})
                """, module=module_name)
                
                # Create IMPORTS relationship
                session.run("""
                    MATCH (f:CodeFile {path: $file_path})
                    MATCH (m:CodeModule {name: $module})
                    MERGE (f)-[:IMPORTS]->(m)
                """, file_path=file_path, module=module_name)
                
                self.stats['imports'] += 1
    
    def create_function_nodes(self, structure: Dict):
        """Create Function nodes and DEFINES relationships"""
        file_path = structure['file_path']
        
        with self.driver.session() as session:
            for func in structure['functions']:
                # Create Function node
                session.run("""
                    MERGE (fn:CodeFunction {name: $name, file: $file})
                    SET fn.line_start = $line_start,
                        fn.line_end = $line_end,
                        fn.docstring = $docstring,
                        fn.is_async = $is_async,
                        fn.language = $language
                """,
                    name=func['name'],
                    file=file_path,
                    line_start=func['line_start'],
                    line_end=func['line_end'],
                    docstring=func.get('docstring', ''),
                    is_async=func.get('is_async', False),
                    language=structure['language']
                )
                
                # Create DEFINES relationship
                session.run("""
                    MATCH (f:CodeFile {path: $file_path})
                    MATCH (fn:CodeFunction {name: $func_name, file: $file_path})
                    MERGE (f)-[:DEFINES]->(fn)
                """, file_path=file_path, func_name=func['name'])
                
                self.stats['functions'] += 1
    
    def create_call_relationships(self, structure: Dict):
        """Create CALLS relationships between functions"""
        file_path = structure['file_path']
        
        with self.driver.session() as session:
            for func in structure['functions']:
                caller = func['name']
                
                for callee in func.get('calls', []):
                    # Try to find callee function (may be in same or different file)
                    session.run("""
                        MATCH (caller:CodeFunction {name: $caller, file: $file})
                        MATCH (callee:CodeFunction {name: $callee})
                        MERGE (caller)-[:CALLS]->(callee)
                    """, caller=caller, callee=callee, file=file_path)
                    
                    self.stats['calls'] += 1
    
    def create_class_nodes(self, structure: Dict):
        """Create Class nodes and relationships"""
        file_path = structure['file_path']
        
        with self.driver.session() as session:
            for cls in structure['classes']:
                # Create Class node
                session.run("""
                    MERGE (c:CodeClass {name: $name, file: $file})
                    SET c.line_start = $line_start,
                        c.line_end = $line_end,
                        c.docstring = $docstring,
                        c.language = $language
                """,
                    name=cls['name'],
                    file=file_path,
                    line_start=cls['line_start'],
                    line_end=cls['line_end'],
                    docstring=cls.get('docstring', ''),
                    language=structure['language']
                )
                
                # Create DEFINES relationship
                session.run("""
                    MATCH (f:CodeFile {path: $file_path})
                    MATCH (c:CodeClass {name: $class_name, file: $file_path})
                    MERGE (f)-[:DEFINES]->(c)
                """, file_path=file_path, class_name=cls['name'])
                
                # Create HAS_METHOD relationships
                for method_name in cls.get('methods', []):
                    session.run("""
                        MATCH (c:CodeClass {name: $class_name, file: $file})
                        MATCH (fn:CodeFunction {name: $method_name, file: $file})
                        MERGE (c)-[:HAS_METHOD]->(fn)
                    """, class_name=cls['name'], method_name=method_name, file=file_path)
                
                self.stats['classes'] += 1
    
    def get_function_graph_context(self, file_path: str, function_name: str) -> Dict:
        """
        Get graph context for a function (for embedding enrichment).
        
        Returns:
            {
                'callers': [func_names],
                'callees': [func_names],
                'imports': [module_names],
                'class_membership': str or None,
                'call_depth': int
            }
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (fn:CodeFunction {name: $func_name, file: $file})
                OPTIONAL MATCH (caller)-[:CALLS]->(fn)
                OPTIONAL MATCH (fn)-[:CALLS]->(callee)
                OPTIONAL MATCH (cls)-[:HAS_METHOD]->(fn)
                OPTIONAL MATCH (f:CodeFile {path: $file})-[:IMPORTS]->(m:CodeModule)
                RETURN 
                    collect(DISTINCT caller.name) as callers,
                    collect(DISTINCT callee.name) as callees,
                    collect(DISTINCT m.name) as imports,
                    cls.name as class_name
            """, func_name=function_name, file=file_path)
            
            record = result.single()
            if record:
                return {
                    'callers': [c for c in record['callers'] if c],
                    'callees': [c for c in record['callees'] if c],
                    'imports': [i for i in record['imports'] if i],
                    'class_membership': record['class_name'],
                    'call_depth': len([c for c in record['callers'] if c])  # Simplified
                }
            else:
                return {
                    'callers': [],
                    'callees': [],
                    'imports': [],
                    'class_membership': None,
                    'call_depth': 0
                }


# ============================================================================
# GRAPH-ENRICHED EMBEDDINGS CREATOR
# ============================================================================

class GraphEnrichedEmbeddings:
    """
    Create vector embeddings enriched with graph context.
    Each code chunk gets:
    1. Semantic embedding (from code text)
    2. Graph metadata (callers, callees, dependencies)
    3. Structural tags (function/class/module)
    """
    
    def __init__(self, chromadb_host: str, chromadb_port: int, 
                 neo4j_builder: Neo4jGraphBuilder):
        self.chroma_client = chromadb.HttpClient(host=chromadb_host, port=chromadb_port)
        self.neo4j = neo4j_builder
        self.collection = None
        self.stats = defaultdict(int)
    
    def get_or_create_collection(self):
        """Get or create ChromaDB collection"""
        try:
            self.collection = self.chroma_client.get_collection(COLLECTION_NAME)
            count = self.collection.count()
            print(f"[OK] Using existing collection: {COLLECTION_NAME} ({count} docs)")
        except:
            self.collection = self.chroma_client.create_collection(
                name=COLLECTION_NAME,
                metadata={
                    "description": "Graph-enriched code embeddings with Neo4j context",
                    "version": "6.0.0",
                    "created": datetime.now().isoformat()
                }
            )
            print(f"[OK] Created collection: {COLLECTION_NAME}")
        
        return self.collection
    
    def create_enriched_embedding(self, structure: Dict, content: str):
        """
        Create graph-enriched embeddings for code file.
        Each function becomes a document with graph context.
        """
        file_path = structure['file_path']
        lines = content.split('\n')
        
        documents = []
        metadatas = []
        ids = []
        
        # Create embeddings for each function
        for func in structure['functions']:
            # Extract function content with context
            start_idx = max(0, func['line_start'] - CONTEXT_LINES_BEFORE - 1)
            end_idx = min(len(lines), func['line_end'] + CONTEXT_LINES_AFTER)
            func_content = '\n'.join(lines[start_idx:end_idx])
            
            # Get graph context from Neo4j
            graph_context = self.neo4j.get_function_graph_context(
                file_path, func['name']
            )
            
            # Create enriched metadata
            metadata = {
                'file_path': file_path,
                'language': structure['language'],
                'type': 'function',
                'name': func['name'],
                'line_start': func['line_start'],
                'line_end': func['line_end'],
                'docstring': func.get('docstring', ''),
                'is_async': func.get('is_async', False),
                
                # Graph context (THE MAGIC!)
                'callers': ','.join(graph_context['callers'][:10]),  # Who calls this
                'callees': ','.join(graph_context['callees'][:10]),  # What it calls
                'imports': ','.join(graph_context['imports'][:10]),  # Dependencies
                'class_membership': graph_context['class_membership'] or '',
                'call_depth': graph_context['call_depth'],
                
                # Structural metadata
                'num_callers': len(graph_context['callers']),
                'num_callees': len(graph_context['callees']),
                'is_method': bool(graph_context['class_membership']),
                'is_leaf': len(graph_context['callees']) == 0,
                'is_root': len(graph_context['callers']) == 0,
                
                # Version tracking
                'ingestion_version': '6.0.0',
                'created_at': datetime.now().isoformat()
            }
            
            # Generate unique ID
            doc_id = hashlib.sha256(
                f"{file_path}::{func['name']}::{func['line_start']}".encode()
            ).hexdigest()[:16]
            
            documents.append(func_content)
            metadatas.append(metadata)
            ids.append(doc_id)
            
            self.stats['chunks'] += 1
        
        # Batch add to ChromaDB
        if documents:
            self.collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            print(f"[OK] Added {len(documents)} enriched chunks from {Path(file_path).name}")


# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================

class GraphEnrichedCodeIngester:
    """
    Main orchestrator for graph-enriched code ingestion.
    
    Pipeline:
    1. Parse code files → extract structure
    2. Build Neo4j graph → nodes + relationships
    3. Enrich embeddings → add graph context to vectors
    4. Store in ChromaDB → hybrid-ready embeddings
    """
    
    def __init__(self, workflow_root: str):
        self.workflow_root = Path(workflow_root)
        self.parser = CodeStructureParser()
        self.neo4j = None
        self.embeddings = None
        self.stats = {
            'files_processed': 0,
            'files_skipped': 0,
            'parse_errors': 0
        }
    
    def connect(self):
        """Initialize connections"""
        print("[INIT] Connecting to Neo4j...")
        self.neo4j = Neo4jGraphBuilder(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        
        print("[INIT] Connecting to ChromaDB...")
        self.embeddings = GraphEnrichedEmbeddings(
            CHROMADB_HOST, CHROMADB_PORT, self.neo4j
        )
        self.embeddings.get_or_create_collection()
        
        print("[OK] Connections established")
    
    def close(self):
        """Close connections"""
        if self.neo4j:
            self.neo4j.close()
    
    def find_code_files(self, extensions: List[str]) -> List[Path]:
        """Find all code files with given extensions"""
        files = []
        for ext in extensions:
            found = list(self.workflow_root.rglob(f"*{ext}"))
            files.extend(found)
            print(f"[OK] Found {len(found)} {ext} files")
        return sorted(files)
    
    def determine_language(self, file_path: Path) -> str:
        """Determine programming language from extension"""
        ext = file_path.suffix.lower()
        if ext in PYTHON_EXTENSIONS:
            return 'python'
        elif ext in SHELL_EXTENSIONS:
            return 'shell'
        elif ext in FORTRAN_EXTENSIONS:
            return 'fortran'
        else:
            return 'unknown'
    
    def ingest_file(self, file_path: Path):
        """Ingest single file with full pipeline"""
        try:
            # Read content
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            language = self.determine_language(file_path)
            
            if language == 'unknown':
                self.stats['files_skipped'] += 1
                return
            
            print(f"\n[INGEST] {file_path.relative_to(self.workflow_root)} ({language})")
            
            # Step 1: Parse structure
            structure = self.parser.parse_file(str(file_path), content, language)
            
            if not structure['functions'] and not structure['classes']:
                print(f"  [SKIP] No functions/classes found")
                self.stats['files_skipped'] += 1
                return
            
            # Step 2: Build Neo4j graph
            self.neo4j.create_file_node(structure, content)
            self.neo4j.create_import_relationships(structure)
            self.neo4j.create_function_nodes(structure)
            self.neo4j.create_class_nodes(structure)
            self.neo4j.create_call_relationships(structure)
            
            # Step 3: Create enriched embeddings
            self.embeddings.create_enriched_embedding(structure, content)
            
            self.stats['files_processed'] += 1
            print(f"  [OK] Processed {len(structure['functions'])} functions, "
                  f"{len(structure['classes'])} classes")
            
        except Exception as e:
            print(f"[ERROR] Failed to ingest {file_path}: {e}")
            self.stats['parse_errors'] += 1
    
    def ingest_directory(self, extensions: List[str] = None, 
                        max_files: int = None, clear_existing: bool = False):
        """
        Ingest entire directory.
        
        Args:
            extensions: File extensions to process (default: Python + Shell)
            max_files: Limit number of files (for testing)
            clear_existing: Clear existing graph before ingestion
        """
        if extensions is None:
            extensions = PYTHON_EXTENSIONS + SHELL_EXTENSIONS
        
        # Find files
        files = self.find_code_files(extensions)
        if max_files:
            files = files[:max_files]
        
        print(f"\n[START] Ingesting {len(files)} files from {self.workflow_root}")
        
        # Clear existing data if requested
        if clear_existing:
            confirm = input("Clear existing graph data? (yes/no): ")
            if confirm.lower() == 'yes':
                self.neo4j.clear_code_graph(confirm=True)
        
        # Process files
        for i, file_path in enumerate(files, 1):
            print(f"\n[{i}/{len(files)}]", end=" ")
            self.ingest_file(file_path)
        
        # Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print ingestion summary"""
        print("\n" + "="*70)
        print("GRAPH-ENRICHED CODE INGESTION SUMMARY")
        print("="*70)
        print(f"  Files processed: {self.stats['files_processed']}")
        print(f"  Files skipped: {self.stats['files_skipped']}")
        print(f"  Parse errors: {self.stats['parse_errors']}")
        print(f"\n  Parser stats:")
        print(f"    Functions: {self.parser.stats['functions']}")
        print(f"    Classes: {self.parser.stats['classes']}")
        print(f"    Syntax errors: {self.parser.stats['syntax_errors']}")
        print(f"\n  Neo4j graph stats:")
        print(f"    Files: {self.neo4j.stats['files']}")
        print(f"    Functions: {self.neo4j.stats['functions']}")
        print(f"    Classes: {self.neo4j.stats['classes']}")
        print(f"    Import relationships: {self.neo4j.stats['imports']}")
        print(f"    Call relationships: {self.neo4j.stats['calls']}")
        print(f"\n  ChromaDB embeddings:")
        print(f"    Enriched chunks: {self.embeddings.stats['chunks']}")
        print(f"    Collection: {COLLECTION_NAME}")
        print("="*70)


# ============================================================================
# CLI INTERFACE
# ============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Graph-Enriched Code Ingestion v6.0.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Ingest Python files only
  python3 ingest_code_graph_enriched_v6.py --python-only
  
  # Test with first 10 files
  python3 ingest_code_graph_enriched_v6.py --max-files 10
  
  # Clear existing data and re-ingest
  python3 ingest_code_graph_enriched_v6.py --clear --python-only
  
  # Custom workflow root
  python3 ingest_code_graph_enriched_v6.py --root /path/to/global-workflow
        """
    )
    
    parser.add_argument(
        '--root',
        default=WORKFLOW_ROOT,
        help='Workflow root directory'
    )
    parser.add_argument(
        '--python-only',
        action='store_true',
        help='Ingest Python files only'
    )
    parser.add_argument(
        '--shell-only',
        action='store_true',
        help='Ingest Shell files only'
    )
    parser.add_argument(
        '--max-files',
        type=int,
        help='Limit number of files (for testing)'
    )
    parser.add_argument(
        '--clear',
        action='store_true',
        help='Clear existing graph before ingestion'
    )
    
    args = parser.parse_args()
    
    # Determine extensions
    if args.python_only:
        extensions = PYTHON_EXTENSIONS
    elif args.shell_only:
        extensions = SHELL_EXTENSIONS
    else:
        extensions = PYTHON_EXTENSIONS + SHELL_EXTENSIONS
    
    # Run ingestion
    ingester = GraphEnrichedCodeIngester(args.root)
    
    try:
        ingester.connect()
        ingester.ingest_directory(
            extensions=extensions,
            max_files=args.max_files,
            clear_existing=args.clear
        )
    finally:
        ingester.close()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
