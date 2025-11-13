#!/usr/bin/env python3
"""
Code Embedding Ingestion Script - v1.0
Ingests Python and Shell code into ChromaDB for semantic code search.

CURRENT IMPLEMENTATION (v1.0):
- Function-level chunking from AST/regex parsing
- Static call graph analysis from parsed data
- Best-effort function body extraction

FUTURE ENHANCEMENT (Post-GitLab Migration):
- Real call trees from compilation (Fortran, C, C++)
- Binary analysis integration
- Cross-language call graph (Python→Shell→Fortran→C)
- See: MCP_REPO_MIGRATION_PLAN.md Phase 5+

Collection: code_with_context
Purpose: Enable semantic code similarity search and context-aware code retrieval
"""

import os
import sys
import json
import hashlib
import chromadb
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime

# Configuration
COLLECTION_NAME = "code_with_context"
CHUNK_SIZE = 1500  # Larger for code context
CHUNK_OVERLAP = 300  # More overlap for function boundaries
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))

# Paths
WORKFLOW_ROOT = os.getenv("MCP_WORKFLOW_ROOT", "/mcp_rag_eib/global-workflow_MCP_node.js-RAG")
PYTHON_PATHS = [
    f"{WORKFLOW_ROOT}/scripts",
    f"{WORKFLOW_ROOT}/ush/python",
]
SHELL_PATHS = [
    f"{WORKFLOW_ROOT}/scripts",
    f"{WORKFLOW_ROOT}/ush",
]


class CodeIngester:
    """
    Ingest code files into ChromaDB for semantic search.
    
    ARCHITECTURE NOTE:
    This is v1.0 implementation using static analysis. Future versions
    (post-GitLab migration) will integrate with compilation build systems
    to extract real call trees from Fortran/C/C++ binaries.
    
    See WEEK_3_PLAN.md and MCP_REPO_MIGRATION_PLAN.md for roadmap.
    """
    
    def __init__(self, workflow_root: str):
        self.workflow_root = workflow_root
        self.client = None
        self.collection = None
        self.stats = {
            'files_processed': 0,
            'chunks_created': 0,
            'functions_extracted': 0,
            'errors': 0
        }
        
    def log(self, message: str, level: str = 'INFO'):
        """Log with timestamp"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [{level}] {message}")
    
    def connect_chromadb(self):
        """Initialize ChromaDB connection"""
        try:
            self.client = chromadb.HttpClient(
                host=CHROMADB_HOST,
                port=CHROMADB_PORT
            )
            # Test connection
            self.client.heartbeat()
            self.log(f"✅ Connected to ChromaDB at {CHROMADB_HOST}:{CHROMADB_PORT}")
            return True
        except Exception as e:
            self.log(f"❌ Failed to connect to ChromaDB: {e}", 'ERROR')
            return False
    
    def get_or_create_collection(self):
        """Get or create code_with_context collection"""
        try:
            self.collection = self.client.get_collection(COLLECTION_NAME)
            count = self.collection.count()
            self.log(f"Using existing collection: {COLLECTION_NAME} ({count} documents)")
        except Exception:
            self.collection = self.client.create_collection(
                name=COLLECTION_NAME,
                metadata={
                    "description": "Code chunks with context for semantic search",
                    "version": "1.0.0",
                    "languages": "python,shell",
                    "created_date": datetime.now().isoformat(),
                    "chunking_strategy": "function-level"
                }
            )
            self.log(f"Created new collection: {COLLECTION_NAME}")
        return self.collection
    
    def find_code_files(self, paths: List[str], extensions: List[str]) -> List[str]:
        """Find all code files in given paths"""
        files = []
        for base_path in paths:
            path_obj = Path(base_path)
            if not path_obj.exists():
                self.log(f"⚠️  Path not found: {base_path}", 'WARNING')
                continue
            
            for ext in extensions:
                pattern = f"**/*{ext}"
                found = list(path_obj.glob(pattern))
                files.extend([str(f) for f in found])
                self.log(f"Found {len(found)} {ext} files in {base_path}")
        
        return sorted(set(files))
    
    def read_file_content(self, file_path: str) -> Optional[str]:
        """Read file content with error handling"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            self.log(f"❌ Error reading {file_path}: {e}", 'ERROR')
            self.stats['errors'] += 1
            return None
    
    def extract_python_functions(self, content: str, file_path: str) -> List[Dict]:
        """
        Extract Python functions with context.
        
        TODO (Post-GitLab): Integrate with Python C-API call tracing
        for runtime call graphs.
        """
        import ast
        
        functions = []
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Extract function with surrounding context
                    start_line = max(1, node.lineno - 5)  # 5 lines before
                    end_line = node.end_lineno + 5 if hasattr(node, 'end_lineno') else node.lineno + 20
                    
                    lines = content.split('\n')
                    function_context = '\n'.join(lines[start_line-1:end_line])
                    
                    # Get docstring
                    docstring = ast.get_docstring(node) or ""
                    
                    # Get imports (simple extraction from tree)
                    imports = self._extract_imports_from_ast(tree)
                    
                    functions.append({
                        'name': node.name,
                        'type': 'async_function' if isinstance(node, ast.AsyncFunctionDef) else 'function',
                        'line_start': node.lineno,
                        'line_end': node.end_lineno if hasattr(node, 'end_lineno') else node.lineno,
                        'content': function_context,
                        'docstring': docstring,
                        'imports': imports[:10],  # Limit for metadata
                        'file_path': file_path
                    })
                    
        except SyntaxError as e:
            self.log(f"⚠️  Syntax error in {file_path}: {e}", 'WARNING')
        except Exception as e:
            self.log(f"❌ Error parsing {file_path}: {e}", 'ERROR')
            
        return functions
    
    def _extract_imports_from_ast(self, tree: 'ast.Module') -> List[str]:
        """Extract import statements from AST"""
        import ast
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        return imports
    
    def extract_shell_functions(self, content: str, file_path: str) -> List[Dict]:
        """
        Extract Shell functions with context.
        
        TODO (Post-GitLab): Integrate with shell trace analysis (bash -x)
        for runtime call graphs.
        """
        import re
        
        functions = []
        lines = content.split('\n')
        
        # Regex for shell function definitions
        func_pattern = re.compile(r'^\s*(?:function\s+)?(\w+)\s*\(\s*\)\s*\{?\s*$')
        
        i = 0
        while i < len(lines):
            match = func_pattern.match(lines[i])
            if match:
                func_name = match.group(1)
                start_line = i + 1
                
                # Find function end (simple brace matching)
                brace_count = 1 if '{' in lines[i] else 0
                end_line = i
                
                for j in range(i + 1, min(i + 200, len(lines))):  # Max 200 lines
                    line = lines[j]
                    brace_count += line.count('{') - line.count('}')
                    if brace_count == 0:
                        end_line = j
                        break
                
                # Extract with context
                context_start = max(0, start_line - 5)
                context_end = min(len(lines), end_line + 5)
                function_context = '\n'.join(lines[context_start:context_end])
                
                # Extract source commands (simple grep)
                sources = []
                for line in lines[start_line:end_line]:
                    if 'source' in line or '. ' in line:
                        sources.append(line.strip())
                
                functions.append({
                    'name': func_name,
                    'type': 'shell_function',
                    'line_start': start_line,
                    'line_end': end_line,
                    'content': function_context,
                    'sources': sources[:5],  # Limit for metadata
                    'file_path': file_path
                })
                
                i = end_line + 1
            else:
                i += 1
        
        return functions
    
    def create_chunks_from_functions(self, functions: List[Dict], file_path: str, language: str) -> List[Dict]:
        """Create searchable chunks from extracted functions"""
        chunks = []
        
        for func in functions:
            content = func['content']
            
            # Create rich text for embedding
            if language == 'python':
                chunk_text = f"""
File: {file_path}
Function: {func['name']} (Line {func['line_start']})
Type: {func['type']}
Docstring: {func.get('docstring', 'None')}
Imports: {', '.join(func.get('imports', []))}

Code:
{content}
"""
            else:  # shell
                chunk_text = f"""
File: {file_path}
Function: {func['name']} (Line {func['line_start']})
Type: Shell function
Sources: {', '.join(func.get('sources', []))}

Code:
{content}
"""
            
            # Generate unique ID
            chunk_id = hashlib.sha256(
                f"{file_path}:{func['name']}:{func['line_start']}".encode()
            ).hexdigest()[:16]
            
            chunks.append({
                'id': chunk_id,
                'text': chunk_text.strip(),
                'metadata': {
                    'file_path': file_path,
                    'function_name': func['name'],
                    'function_type': func['type'],
                    'line_start': func['line_start'],
                    'line_end': func['line_end'],
                    'language': language,
                    'ingestion_date': datetime.now().isoformat(),
                    'version': '1.0.0'
                }
            })
        
        return chunks
    
    def ingest_chunks(self, chunks: List[Dict]):
        """Add chunks to ChromaDB collection"""
        if not chunks:
            return
        
        try:
            ids = [c['id'] for c in chunks]
            documents = [c['text'] for c in chunks]
            metadatas = [c['metadata'] for c in chunks]
            
            # Add in batches
            batch_size = 100
            for i in range(0, len(chunks), batch_size):
                batch_ids = ids[i:i+batch_size]
                batch_docs = documents[i:i+batch_size]
                batch_meta = metadatas[i:i+batch_size]
                
                self.collection.add(
                    ids=batch_ids,
                    documents=batch_docs,
                    metadatas=batch_meta
                )
                
                self.log(f"  Added batch {i//batch_size + 1}: {len(batch_ids)} chunks")
            
            self.stats['chunks_created'] += len(chunks)
            
        except Exception as e:
            self.log(f"❌ Error ingesting chunks: {e}", 'ERROR')
            self.stats['errors'] += 1
    
    def process_files(self, files: List[str], language: str):
        """Process code files and extract functions"""
        self.log(f"\n{'='*60}")
        self.log(f"Processing {len(files)} {language.upper()} files")
        self.log(f"{'='*60}\n")
        
        for file_path in files:
            self.log(f"Processing: {file_path}")
            
            content = self.read_file_content(file_path)
            if not content:
                continue
            
            # Extract functions based on language
            if language == 'python':
                functions = self.extract_python_functions(content, file_path)
            elif language == 'shell':
                functions = self.extract_shell_functions(content, file_path)
            else:
                continue
            
            if not functions:
                self.log(f"  No functions found")
                continue
            
            self.log(f"  Extracted {len(functions)} functions")
            self.stats['functions_extracted'] += len(functions)
            
            # Create chunks
            chunks = self.create_chunks_from_functions(functions, file_path, language)
            
            # Ingest to ChromaDB
            self.ingest_chunks(chunks)
            
            self.stats['files_processed'] += 1
    
    def run(self):
        """Main ingestion process"""
        self.log("="*60)
        self.log("Code Embedding Ingestion - v1.0")
        self.log("NOTE: Using static analysis. Real call trees planned post-GitLab migration")
        self.log("="*60)
        
        # Connect to ChromaDB
        if not self.connect_chromadb():
            return False
        
        # Get/create collection
        self.get_or_create_collection()
        
        # Find files
        python_files = self.find_code_files(PYTHON_PATHS, ['.py'])
        shell_files = self.find_code_files(SHELL_PATHS, ['.sh'])
        
        # Process Python files
        if python_files:
            self.process_files(python_files, 'python')
        
        # Process Shell files
        if shell_files:
            self.process_files(shell_files, 'shell')
        
        # Final stats
        self.log("\n" + "="*60)
        self.log("INGESTION COMPLETE")
        self.log("="*60)
        self.log(f"Files processed: {self.stats['files_processed']}")
        self.log(f"Functions extracted: {self.stats['functions_extracted']}")
        self.log(f"Chunks created: {self.stats['chunks_created']}")
        self.log(f"Errors: {self.stats['errors']}")
        self.log(f"Collection: {COLLECTION_NAME}")
        self.log(f"Total documents in collection: {self.collection.count()}")
        
        return True


def main():
    """Entry point"""
    workflow_root = os.getenv("MCP_WORKFLOW_ROOT", "/mcp_rag_eib/global-workflow_MCP_node.js-RAG")
    
    ingester = CodeIngester(workflow_root)
    success = ingester.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
