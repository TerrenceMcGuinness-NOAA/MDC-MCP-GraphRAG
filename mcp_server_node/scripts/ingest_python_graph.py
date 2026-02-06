#!/usr/bin/env python3
"""
Phase 24F-0: Python Graph Ingestion for Neo4j
Parse Python AST and create graph nodes/relationships in Neo4j

This script creates a comprehensive graph of Python code structure:
  - PythonModule, PythonClass, PythonFunction nodes
  - IMPORTS, CALLS, INHERITS, DEFINES relationships
  - Shell->Python INVOKES bridge

Neo4j Schema:
  (:PythonModule {name, file_path, docstring, package})
  (:PythonClass {name, file_path, line_number, base_classes, decorators, docstring})
  (:PythonFunction {name, file_path, line_number, parameters, is_async, is_method, class_name, return_type, decorators})
  
  (module)-[:DEFINES]->(function|class)
  (class)-[:INHERITS]->(base_class:PythonClass)
  (caller)-[:CALLS {line}]->(callee:PythonFunction)
  (module)-[:IMPORTS {type, alias, line}]->(target_module:PythonModule)
  (shell:ShellScript)-[:INVOKES]->(python:PythonModule)  // Shell->Python bridge

Relies on: parse-python-ast.py for AST extraction (stdlib ast module).

Author: NOAA EMC Global Workflow MCP Team
Version: 1.0.0
Phase: 24F-0 (Python Graph Ingestion)
Date: February 2026

Usage:
  # Test single file
  python ingest_python_graph.py --test /path/to/file.py

  # Dry run (no Neo4j writes)
  python ingest_python_graph.py --dry-run

  # Sample validation (50 random files)
  python ingest_python_graph.py --sample

  # Full ingestion
  python ingest_python_graph.py
"""

import os
import sys
import re
import ast
import json
import argparse
import random
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from collections import defaultdict
from datetime import datetime

try:
    from neo4j import GraphDatabase
except ImportError:
    print("[WARN] neo4j package not found. Neo4j ingestion disabled.")
    GraphDatabase = None


# ============================================================================
# CONFIGURATION
# ============================================================================

VERSION = "1.0.0"
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "gfsworkflow2025")

WORKFLOW_ROOT = os.getenv("WORKFLOW_ROOT",
    "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow")

# Python source directories to scan (relative to WORKFLOW_ROOT)
PYTHON_DIRECTORIES = [
    "ush",                     # Utility scripts and pygfs
    "dev",                     # Development workflow (rocoto, ecflow, setup)
    "sorc/wxflow",             # wxflow framework
    "sorc/gdas.cd/ush",        # GDAS utilities (bufr2ioda, etc.)
    "sorc/gdas.cd/sorc/spoc",  # SPOC dump scripts
    "sorc/ufs_model.fd/UFSATM/ccpp/framework/scripts",  # CCPP framework
    "sorc/verif-global.fd/ush",                          # Verification plotting
    "sorc/nexus.fd/utils/python",                        # NEXUS utils
]

# Patterns to exclude (test files, __pycache__, setup.py boilerplate)
EXCLUDE_PATTERNS = [
    r'__pycache__',
    r'\.eggs?/',
    r'\.tox/',
    r'/build/',
    r'/dist/',
    r'\.egg-info',
]

# Shell patterns that invoke Python scripts
PYTHON_INVOKE_PATTERNS = [
    # python3 /path/to/script.py or python /path/to/script.py
    r'(?:python3?|/usr/bin/env\s+python3?)\s+["\']?\$?\{?([A-Za-z_]+)\}?/([a-zA-Z0-9_/.-]+\.py)',
    # ${USHgfs}/script.py or $USHgfs/script.py
    r'\$\{?USH[a-z]*\}?/([a-zA-Z0-9_/.-]+\.py)',
    # ${HOMEgfs}/ush/python/script.py
    r'\$\{?HOME[a-z]*\}?/ush/([a-zA-Z0-9_/.-]+\.py)',
]


# ============================================================================
# PYTHON AST PARSER (inline - mirrors parse-python-ast.py)
# ============================================================================

class PythonASTParser(ast.NodeVisitor):
    """Extract structural information from Python AST.

    This is a self-contained version of parse-python-ast.py for use in the
    ingestion pipeline without subprocess overhead.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.functions: List[Dict[str, Any]] = []
        self.classes: List[Dict[str, Any]] = []
        self.imports: List[Dict[str, Any]] = []
        self.calls: List[Dict[str, Any]] = []
        self.current_class: Optional[str] = None
        self.current_function: Optional[str] = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        func_info = {
            'name': node.name,
            'line_number': node.lineno,
            'end_line': node.end_lineno,
            'parameters': [arg.arg for arg in node.args.args],
            'decorators': [self._get_decorator_name(dec) for dec in node.decorator_list],
            'is_async': False,
            'is_method': self.current_class is not None,
            'class_name': self.current_class,
            'docstring': ast.get_docstring(node),
        }
        if node.returns:
            func_info['return_type'] = self._get_type_annotation(node.returns)
        self.functions.append(func_info)
        previous_function = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = previous_function

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        func_info = {
            'name': node.name,
            'line_number': node.lineno,
            'end_line': node.end_lineno,
            'parameters': [arg.arg for arg in node.args.args],
            'decorators': [self._get_decorator_name(dec) for dec in node.decorator_list],
            'is_async': True,
            'is_method': self.current_class is not None,
            'class_name': self.current_class,
            'docstring': ast.get_docstring(node),
        }
        if node.returns:
            func_info['return_type'] = self._get_type_annotation(node.returns)
        self.functions.append(func_info)
        previous_function = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = previous_function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_info = {
            'name': node.name,
            'line_number': node.lineno,
            'end_line': node.end_lineno,
            'base_classes': [self._get_base_class_name(base) for base in node.bases],
            'decorators': [self._get_decorator_name(dec) for dec in node.decorator_list],
            'docstring': ast.get_docstring(node),
        }
        self.classes.append(class_info)
        previous_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = previous_class

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append({
                'type': 'import',
                'module': alias.name,
                'alias': alias.asname,
                'line_number': node.lineno,
            })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ''
        for alias in node.names:
            self.imports.append({
                'type': 'from_import',
                'module': module,
                'name': alias.name,
                'alias': alias.asname,
                'line_number': node.lineno,
                'level': node.level,
            })
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        callee_name = self._get_call_name(node.func)
        if callee_name:
            self.calls.append({
                'callee': callee_name,
                'line_number': node.lineno,
                'caller_function': self.current_function,
                'caller_class': self.current_class,
                'num_args': len(node.args),
                'num_kwargs': len(node.keywords),
            })
        self.generic_visit(node)

    # -- Helper methods --

    def _get_decorator_name(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_attr_chain(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return self._get_call_name(node.func) or str(node)
        return str(node)

    def _get_base_class_name(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_attr_chain(node.value)}.{node.attr}"
        return str(node)

    def _get_type_annotation(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_attr_chain(node.value)}.{node.attr}"
        elif isinstance(node, ast.Subscript):
            return f"{self._get_type_annotation(node.value)}[...]"
        return "Any"

    def _get_call_name(self, node: ast.expr) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_attr_chain(node.value)}.{node.attr}"
        return None

    def _get_attr_chain(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_attr_chain(node.value)}.{node.attr}"
        return "?"


# ============================================================================
# FILE PARSER
# ============================================================================

def parse_python_file(filepath: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single Python file and return structured data.

    Returns None on failure.
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()

        tree = ast.parse(source, filename=filepath)
        parser = PythonASTParser(filepath)
        parser.visit(tree)

        # Extract module-level docstring
        docstring = ast.get_docstring(tree)

        # Derive module name from file path
        rel_path = _relative_path(filepath)
        module_name = _path_to_module_name(rel_path)

        return {
            'file': filepath,
            'relative_path': rel_path,
            'module_name': module_name,
            'docstring': docstring,
            'functions': parser.functions,
            'classes': parser.classes,
            'imports': parser.imports,
            'calls': parser.calls,
        }
    except SyntaxError as e:
        return None
    except Exception as e:
        return None


def _relative_path(filepath: str) -> str:
    """Get path relative to WORKFLOW_ROOT."""
    try:
        return os.path.relpath(filepath, WORKFLOW_ROOT)
    except ValueError:
        return filepath


def _path_to_module_name(rel_path: str) -> str:
    """
    Convert relative file path to Python module name.

    Examples:
        ush/python/pygfs/task/analysis.py  -> pygfs.task.analysis
        sorc/wxflow/src/wxflow/logger.py   -> wxflow.logger
        dev/workflow/rocoto/gfs_tasks.py    -> rocoto.gfs_tasks
    """
    p = Path(rel_path)
    parts = list(p.with_suffix('').parts)

    # Remove leading path noise
    noise_prefixes = ['ush', 'python', 'src', 'sorc', 'dev', 'workflow',
                      'utils', 'scripts', 'lib']

    # Try to find a meaningful package root
    # Walk from end to find __init__.py neighbor or known package
    clean = []
    found_package = False
    for part in reversed(parts):
        if found_package:
            break
        clean.insert(0, part)
        # Known package roots
        if part in ('pygfs', 'wxflow', 'rocoto', 'ecflow', 'bufr2ioda',
                     'spoc', 'applications', 'manic'):
            found_package = True

    if found_package:
        return '.'.join(clean)

    # Fallback: strip common noise prefixes
    filtered = [p for p in parts if p not in noise_prefixes]
    if len(filtered) == 0:
        filtered = [parts[-1]]
    return '.'.join(filtered)


# ============================================================================
# FILE DISCOVERY
# ============================================================================

def find_python_files(root_path: str, directories: List[str] = None) -> List[str]:
    """
    Find all Python files in the specified directories under root_path.

    Returns sorted list of absolute file paths.
    """
    if directories is None:
        directories = PYTHON_DIRECTORIES

    files = []
    root = Path(root_path)

    if not root.exists():
        print(f"[WARN] Workflow root does not exist: {root_path}")
        return files

    exclude_re = re.compile('|'.join(EXCLUDE_PATTERNS))

    for scan_dir in directories:
        scan_path = root / scan_dir
        if not scan_path.exists():
            print(f"[WARN] Directory not found: {scan_path}")
            continue

        for py_file in scan_path.rglob("*.py"):
            abs_path = str(py_file)
            if exclude_re.search(abs_path):
                continue
            files.append(abs_path)

    return sorted(set(files))


# ============================================================================
# STATISTICS TRACKER
# ============================================================================

class IngestionStats:
    """Track parsing and ingestion statistics."""

    def __init__(self):
        self.files_processed = 0
        self.files_failed = 0
        self.modules = 0
        self.classes = 0
        self.functions = 0
        self.imports = 0
        self.calls = 0
        self.defines = 0
        self.inherits = 0
        self.invokes = 0
        self.errors: List[Dict[str, str]] = []

    def record_success(self, result: Dict[str, Any]):
        self.files_processed += 1
        self.modules += 1  # One PythonModule per file
        self.classes += len(result.get('classes', []))
        self.functions += len(result.get('functions', []))
        self.imports += len(result.get('imports', []))
        self.calls += len(result.get('calls', []))

    def record_failure(self, filepath: str, error: str):
        self.files_failed += 1
        self.errors.append({'file': filepath, 'error': error})

    def get_summary(self) -> Dict[str, Any]:
        total = self.files_processed + self.files_failed
        rate = (self.files_processed / total * 100) if total > 0 else 0
        return {
            'version': VERSION,
            'timestamp': datetime.now().isoformat(),
            'files': {
                'processed': self.files_processed,
                'failed': self.files_failed,
                'success_rate': f"{rate:.1f}%",
            },
            'nodes': {
                'modules': self.modules,
                'classes': self.classes,
                'functions': self.functions,
            },
            'relationships': {
                'imports': self.imports,
                'calls': self.calls,
                'defines': self.defines,
                'inherits': self.inherits,
                'invokes': self.invokes,
            },
            'error_count': len(self.errors),
        }


# ============================================================================
# NEO4J INGESTION
# ============================================================================

class Neo4jIngester:
    """Ingest Python parse results into Neo4j graph database."""

    def __init__(self, uri: str, user: str, password: str, dry_run: bool = False):
        self.dry_run = dry_run
        self.driver = None
        self.stats = IngestionStats()

        if not dry_run and GraphDatabase:
            try:
                self.driver = GraphDatabase.driver(uri, auth=(user, password))
                with self.driver.session() as session:
                    session.run("RETURN 1")
                print(f"[OK] Connected to Neo4j at {uri}")
            except Exception as e:
                print(f"[ERROR] Neo4j connection failed: {e}")
                self.driver = None

    def create_indexes(self):
        """Create indexes and constraints for Python nodes."""
        if self.dry_run or not self.driver:
            print("[DRY-RUN] Would create indexes for PythonModule, PythonClass, PythonFunction")
            return

        indexes = [
            "CREATE INDEX IF NOT EXISTS FOR (m:PythonModule) ON (m.name)",
            "CREATE INDEX IF NOT EXISTS FOR (m:PythonModule) ON (m.file_path)",
            "CREATE INDEX IF NOT EXISTS FOR (c:PythonClass) ON (c.name)",
            "CREATE INDEX IF NOT EXISTS FOR (f:PythonFunction) ON (f.name)",
        ]

        with self.driver.session() as session:
            for idx in indexes:
                try:
                    session.run(idx)
                except Exception as e:
                    print(f"[WARN] Index creation: {e}")

        print("[OK] Neo4j indexes created for Python nodes")

    def ingest_file_result(self, result: Dict[str, Any]) -> Dict[str, int]:
        """
        Ingest a single file's parse result into Neo4j.

        Creates:
          - 1 PythonModule node per file
          - PythonClass nodes for each class
          - PythonFunction nodes for each function/method
          - DEFINES relationships (module->class, module->function, class->method)
          - IMPORTS relationships (module->module)
          - CALLS relationships (function->function)
          - INHERITS relationships (class->base class)

        Returns counts of operations performed.
        """
        counts = {'nodes': 0, 'rels': 0}
        rel_path = result.get('relative_path', result['file'])
        module_name = result.get('module_name', Path(rel_path).stem)
        docstring = result.get('docstring', '')

        if self.dry_run or not self.driver:
            # Count what would be created
            counts['nodes'] = 1 + len(result.get('classes', [])) + len(result.get('functions', []))
            counts['rels'] = (
                len(result.get('imports', [])) +
                len(result.get('calls', [])) +
                len(result.get('functions', [])) +  # DEFINES
                len(result.get('classes', [])) +     # DEFINES
                sum(len(c.get('base_classes', [])) for c in result.get('classes', []))  # INHERITS
            )
            self.stats.record_success(result)
            return counts

        with self.driver.session() as session:
            # -- 1. Create PythonModule node --
            session.run("""
                MERGE (m:PythonModule {file_path: $file_path})
                SET m.name = $name,
                    m.docstring = $docstring,
                    m.package = $package
            """, file_path=rel_path,
                 name=module_name,
                 docstring=(docstring or '')[:500],  # Truncate long docstrings
                 package=module_name.rsplit('.', 1)[0] if '.' in module_name else module_name)
            counts['nodes'] += 1

            # -- 2. Create PythonClass nodes + DEFINES --
            for cls in result.get('classes', []):
                session.run("""
                    MERGE (c:PythonClass {name: $name, file_path: $file_path})
                    SET c.line_number = $line_number,
                        c.end_line = $end_line,
                        c.base_classes = $base_classes,
                        c.decorators = $decorators,
                        c.docstring = $docstring
                """, name=cls['name'],
                     file_path=rel_path,
                     line_number=cls.get('line_number'),
                     end_line=cls.get('end_line'),
                     base_classes=cls.get('base_classes', []),
                     decorators=cls.get('decorators', []),
                     docstring=(cls.get('docstring') or '')[:300])
                counts['nodes'] += 1

                # DEFINES: module -> class
                session.run("""
                    MATCH (m:PythonModule {file_path: $file_path})
                    MATCH (c:PythonClass {name: $name, file_path: $file_path})
                    MERGE (m)-[:DEFINES]->(c)
                """, file_path=rel_path, name=cls['name'])
                counts['rels'] += 1
                self.stats.defines += 1

                # INHERITS: class -> base classes
                for base in cls.get('base_classes', []):
                    if base in ('object', 'ABC', 'Exception', 'dict', 'list',
                                'tuple', 'set', 'str', 'int', 'float'):
                        continue  # Skip builtin bases
                    session.run("""
                        MERGE (base:PythonClass {name: $base_name})
                        WITH base
                        MATCH (c:PythonClass {name: $class_name, file_path: $file_path})
                        MERGE (c)-[:INHERITS]->(base)
                    """, base_name=base, class_name=cls['name'], file_path=rel_path)
                    counts['rels'] += 1
                    self.stats.inherits += 1

            # -- 3. Create PythonFunction nodes + DEFINES --
            for func in result.get('functions', []):
                session.run("""
                    MERGE (f:PythonFunction {name: $name, file_path: $file_path, line_number: $line_number})
                    SET f.end_line = $end_line,
                        f.parameters = $params,
                        f.decorators = $decorators,
                        f.is_async = $is_async,
                        f.is_method = $is_method,
                        f.class_name = $class_name,
                        f.return_type = $return_type,
                        f.docstring = $docstring
                """, name=func['name'],
                     file_path=rel_path,
                     line_number=func.get('line_number'),
                     end_line=func.get('end_line'),
                     params=func.get('parameters', []),
                     decorators=func.get('decorators', []),
                     is_async=func.get('is_async', False),
                     is_method=func.get('is_method', False),
                     class_name=func.get('class_name'),
                     return_type=func.get('return_type'),
                     docstring=(func.get('docstring') or '')[:300])
                counts['nodes'] += 1

                # DEFINES: module/class -> function
                if func.get('is_method') and func.get('class_name'):
                    session.run("""
                        MATCH (c:PythonClass {name: $class_name, file_path: $file_path})
                        MATCH (f:PythonFunction {name: $func_name, file_path: $file_path, line_number: $line_number})
                        MERGE (c)-[:DEFINES]->(f)
                    """, class_name=func['class_name'], func_name=func['name'],
                         file_path=rel_path, line_number=func.get('line_number'))
                else:
                    session.run("""
                        MATCH (m:PythonModule {file_path: $file_path})
                        MATCH (f:PythonFunction {name: $func_name, file_path: $file_path, line_number: $line_number})
                        MERGE (m)-[:DEFINES]->(f)
                    """, file_path=rel_path, func_name=func['name'],
                         line_number=func.get('line_number'))
                counts['rels'] += 1
                self.stats.defines += 1

            # -- 4. Create IMPORTS relationships --
            seen_imports = set()
            for imp in result.get('imports', []):
                target_module = imp.get('module', '')
                if not target_module or target_module in seen_imports:
                    continue
                seen_imports.add(target_module)

                # Resolve module to a PythonModule if it's local
                session.run("""
                    MERGE (target:PythonModule {name: $target_name})
                    WITH target
                    MATCH (m:PythonModule {file_path: $file_path})
                    MERGE (m)-[r:IMPORTS]->(target)
                    SET r.import_type = $import_type,
                        r.line = $line
                """, target_name=target_module,
                     file_path=rel_path,
                     import_type=imp.get('type', 'import'),
                     line=imp.get('line_number'))
                counts['rels'] += 1

            # -- 5. Create CALLS relationships --
            # Batch calls by unique callee to reduce Neo4j round-trips
            calls_by_callee = defaultdict(list)
            for call in result.get('calls', []):
                callee = call.get('callee', '')
                if not callee or callee.startswith('self.') or '.' in callee:
                    # Skip self.method() and attr.method() - too noisy without
                    # full type resolution. Only create CALLS for direct name calls.
                    # Exception: keep Class.method() style calls  
                    if callee.startswith('self.') or callee.count('.') > 1:
                        continue
                callee_simple = callee.split('.')[-1] if '.' in callee else callee
                calls_by_callee[callee_simple].append(call)

            for callee_name, call_list in calls_by_callee.items():
                if callee_name in ('print', 'len', 'str', 'int', 'float', 'list',
                                   'dict', 'set', 'tuple', 'range', 'enumerate',
                                   'zip', 'map', 'filter', 'sorted', 'reversed',
                                   'isinstance', 'issubclass', 'hasattr', 'getattr',
                                   'setattr', 'delattr', 'super', 'type', 'open',
                                   'format', 'repr', 'bool', 'abs', 'min', 'max',
                                   'sum', 'any', 'all', 'next', 'iter', 'id',
                                   'round', 'hash', 'input', 'staticmethod',
                                   'classmethod', 'property', 'ValueError',
                                   'TypeError', 'KeyError', 'RuntimeError',
                                   'FileNotFoundError', 'NotImplementedError',
                                   'AttributeError', 'IndexError', 'OSError',
                                   'Exception', 'IOError'):
                    continue  # Skip builtins and exceptions

                first_call = call_list[0]
                caller_func = first_call.get('caller_function')

                if caller_func:
                    session.run("""
                        MERGE (callee:PythonFunction {name: $callee_name})
                        WITH callee
                        MATCH (caller:PythonFunction {name: $caller_name, file_path: $file_path})
                        MERGE (caller)-[r:CALLS]->(callee)
                        SET r.line = $line,
                            r.call_count = $count,
                            r.source_file = $file_path
                    """, callee_name=callee_name,
                         caller_name=caller_func,
                         file_path=rel_path,
                         line=first_call.get('line_number'),
                         count=len(call_list))
                else:
                    # Module-level call (not inside a function)
                    session.run("""
                        MERGE (callee:PythonFunction {name: $callee_name})
                        WITH callee
                        MATCH (m:PythonModule {file_path: $file_path})
                        MERGE (m)-[r:CALLS]->(callee)
                        SET r.line = $line,
                            r.call_count = $count,
                            r.source_file = $file_path
                    """, callee_name=callee_name,
                         file_path=rel_path,
                         line=first_call.get('line_number'),
                         count=len(call_list))
                counts['rels'] += 1

        self.stats.record_success(result)
        return counts

    def create_shell_python_bridge(self):
        """
        Create INVOKES relationships from ShellScript nodes to PythonModule nodes.

        Scans existing ShellScript nodes for Python invocations in their content.
        Falls back to filename pattern matching.
        """
        if self.dry_run or not self.driver:
            print("[DRY-RUN] Would create Shell->Python INVOKES relationships")
            return 0

        bridge_count = 0
        with self.driver.session() as session:
            # Find shell scripts that reference .py files
            result = session.run("""
                MATCH (s:ShellScript)
                WHERE s.file_path IS NOT NULL
                RETURN s.name AS name, s.file_path AS file_path
            """)
            shell_scripts = [(r['name'], r['file_path']) for r in result]

        if not shell_scripts:
            print("[INFO] No ShellScript nodes found - skipping bridge creation")
            return 0

        print(f"[INFO] Scanning {len(shell_scripts)} shell scripts for Python invocations...")

        for script_name, script_path in shell_scripts:
            abs_path = os.path.join(WORKFLOW_ROOT, script_path)
            if not os.path.exists(abs_path):
                continue

            try:
                with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except Exception:
                continue

            # Find Python script references
            py_refs = set()
            for pattern in PYTHON_INVOKE_PATTERNS:
                for match in re.finditer(pattern, content):
                    ref = match.group(match.lastindex)
                    if ref.endswith('.py'):
                        py_refs.add(ref)

            # Also find direct "python script.py" patterns
            for match in re.finditer(r'python3?\s+["\']?(\S+\.py)', content):
                py_refs.add(match.group(1))

            # Create INVOKES relationships
            for py_ref in py_refs:
                py_basename = Path(py_ref).stem
                with self.driver.session() as session:
                    result = session.run("""
                        MATCH (m:PythonModule)
                        WHERE m.file_path CONTAINS $basename
                        WITH m LIMIT 1
                        MATCH (s:ShellScript {file_path: $shell_path})
                        MERGE (s)-[r:INVOKES]->(m)
                        SET r.reference = $py_ref
                        RETURN count(r) AS created
                    """, basename=py_basename, shell_path=script_path, py_ref=py_ref)
                    for r in result:
                        if r['created'] > 0:
                            bridge_count += 1
                            self.stats.invokes += 1

        print(f"[OK] Created {bridge_count} Shell->Python INVOKES relationships")
        return bridge_count

    def close(self):
        """Close Neo4j driver."""
        if self.driver:
            self.driver.close()


# ============================================================================
# MAIN EXECUTION MODES
# ============================================================================

def test_single_file(filepath: str, verbose: bool = True) -> Optional[Dict[str, Any]]:
    """Test parsing a single Python file."""
    result = parse_python_file(filepath)

    if result and verbose:
        rel = result.get('relative_path', filepath)
        mod = result.get('module_name', '?')
        print(f"\n[OK] Parsed: {rel}")
        print(f"    Module name: {mod}")
        print(f"    Classes:     {len(result['classes'])}")
        print(f"    Functions:   {len(result['functions'])}")
        print(f"    Imports:     {len(result['imports'])}")
        print(f"    Calls:       {len(result['calls'])}")

        if result.get('docstring'):
            doc_preview = result['docstring'][:80].replace('\n', ' ')
            print(f"    Docstring:   {doc_preview}...")

        if result['classes']:
            for cls in result['classes'][:3]:
                bases = ', '.join(cls.get('base_classes', []))
                print(f"    Class: {cls['name']}" +
                      (f" ({bases})" if bases else ""))

        if result['functions'][:5]:
            print(f"    Functions (first 5):")
            for fn in result['functions'][:5]:
                prefix = f"  {fn.get('class_name', '')}." if fn.get('is_method') else "  "
                params = ', '.join(fn.get('parameters', [])[:4])
                if len(fn.get('parameters', [])) > 4:
                    params += ', ...'
                async_flag = "async " if fn.get('is_async') else ""
                print(f"      {async_flag}{prefix}{fn['name']}({params})")

        if result['imports'][:5]:
            print(f"    Imports (first 5):")
            for imp in result['imports'][:5]:
                if imp['type'] == 'import':
                    print(f"      import {imp['module']}")
                else:
                    name = imp.get('name', '*')
                    print(f"      from {imp['module']} import {name}")
    elif not result and verbose:
        print(f"\n[ERROR] Failed to parse: {filepath}")

    return result


def run_sample_test(sample_size: int = 50):
    """Run parsing on a sample of files to validate success rate."""
    print(f"\n{'='*60}")
    print("Phase 24F-0: Python Sample Validation Test")
    print(f"{'='*60}")

    files = find_python_files(WORKFLOW_ROOT)
    print(f"\n[INFO] Found {len(files)} Python files in scan directories")

    if not files:
        print("[ERROR] No Python files found!")
        return

    sample = random.sample(files, min(sample_size, len(files)))
    print(f"[INFO] Testing sample of {len(sample)} files...\n")

    stats = IngestionStats()

    for filepath in sample:
        result = parse_python_file(filepath)
        if result:
            stats.record_success(result)
        else:
            stats.record_failure(filepath, "parse error")

    summary = stats.get_summary()
    print(f"\n{'='*60}")
    print("Results:")
    print(f"{'='*60}")
    print(f"  Files processed: {summary['files']['processed']}")
    print(f"  Files failed:    {summary['files']['failed']}")
    print(f"  Success rate:    {summary['files']['success_rate']}")
    print(f"\nNodes to create:")
    print(f"  PythonModules:   {summary['nodes']['modules']}")
    print(f"  PythonClasses:   {summary['nodes']['classes']}")
    print(f"  PythonFunctions: {summary['nodes']['functions']}")
    print(f"\nRelationships to create:")
    print(f"  IMPORTS: {summary['relationships']['imports']}")
    print(f"  CALLS:   {summary['relationships']['calls']}")

    # Projections
    total = len(files)
    processed = summary['files']['processed']
    if processed > 0:
        factor = total / processed
        proj_classes = int(summary['nodes']['classes'] * factor)
        proj_funcs = int(summary['nodes']['functions'] * factor)
        proj_imports = int(summary['relationships']['imports'] * factor)
        proj_calls = int(summary['relationships']['calls'] * factor)
        print(f"\nProjected for all {total} files:")
        print(f"  PythonClasses:   ~{proj_classes:,}")
        print(f"  PythonFunctions: ~{proj_funcs:,}")
        print(f"  IMPORTS:         ~{proj_imports:,}")
        print(f"  CALLS:           ~{proj_calls:,}")

    if stats.errors:
        print(f"\nFailed files:")
        for err in stats.errors[:10]:
            print(f"  {_relative_path(err['file'])}: {err['error']}")


def run_full_ingestion(dry_run: bool = False, skip_bridge: bool = False):
    """Run full ingestion of all Python files into Neo4j."""
    print(f"\n{'='*60}")
    print("Phase 24F-0: Full Python Graph Ingestion")
    print(f"{'='*60}")
    print(f"Mode: {'DRY-RUN (no Neo4j writes)' if dry_run else 'LIVE'}")

    # Discover files
    files = find_python_files(WORKFLOW_ROOT)
    print(f"\n[INFO] Found {len(files)} Python files to process")

    if not files:
        print("[ERROR] No Python files found!")
        return

    # Initialize Neo4j
    ingester = Neo4jIngester(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, dry_run=dry_run)
    if not dry_run:
        ingester.create_indexes()

    total_nodes = 0
    total_rels = 0

    # Process files with progress
    print(f"\n[INFO] Processing files...")
    for i, filepath in enumerate(files):
        if (i + 1) % 100 == 0 or (i + 1) == len(files):
            print(f"  Progress: {i+1}/{len(files)} files...")

        result = parse_python_file(filepath)
        if result:
            counts = ingester.ingest_file_result(result)
            total_nodes += counts['nodes']
            total_rels += counts['rels']
        else:
            ingester.stats.record_failure(filepath, "parse error")

    # Create Shell->Python bridge
    if not skip_bridge:
        ingester.create_shell_python_bridge()

    # Final summary
    summary = ingester.stats.get_summary()
    print(f"\n{'='*60}")
    print("Ingestion Complete")
    print(f"{'='*60}")
    print(f"  Files processed: {summary['files']['processed']}")
    print(f"  Files failed:    {summary['files']['failed']}")
    print(f"  Success rate:    {summary['files']['success_rate']}")
    print(f"\nNeo4j Graph Nodes:")
    print(f"  PythonModules:   {summary['nodes']['modules']}")
    print(f"  PythonClasses:   {summary['nodes']['classes']}")
    print(f"  PythonFunctions: {summary['nodes']['functions']}")
    print(f"  Total nodes:     {total_nodes:,}")
    print(f"\nNeo4j Graph Relationships:")
    print(f"  DEFINES:   {summary['relationships']['defines']}")
    print(f"  IMPORTS:   {summary['relationships']['imports']}")
    print(f"  CALLS:     {summary['relationships']['calls']}")
    print(f"  INHERITS:  {summary['relationships']['inherits']}")
    print(f"  INVOKES:   {summary['relationships']['invokes']}")
    print(f"  Total rels: {total_rels:,}")

    # Save errors
    if ingester.stats.errors:
        error_file = Path(__file__).parent / 'python_parse_errors.json'
        with open(str(error_file), 'w') as f:
            json.dump(ingester.stats.errors[:100], f, indent=2)
        print(f"\n[INFO] First {min(100, len(ingester.stats.errors))} errors saved to: {error_file}")

    # Phase 24F-0 target comparison
    print(f"\n{'='*60}")
    print("Phase 24F-0 Target Comparison:")
    print(f"{'='*60}")
    targets = {
        'PythonModules': ('modules', 200),
        'PythonClasses': ('classes', 150),
        'PythonFunctions': ('functions', 2500),
        'IMPORTS': ('imports', 3000),
    }
    for label, (key, target) in targets.items():
        if key in summary['nodes']:
            actual = summary['nodes'][key]
        else:
            actual = summary['relationships'][key]
        status = "[OK]" if actual >= target else "[BELOW TARGET]"
        print(f"  {label}: {actual:,} / {target:,} target  {status}")

    ingester.close()


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        description="Phase 24F-0: Python Graph Ingestion for Neo4j",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test single file
  python ingest_python_graph.py --test ush/python/pygfs/task/analysis.py

  # Sample validation (50 files)
  python ingest_python_graph.py --sample

  # Dry run (parse only, no Neo4j writes)
  python ingest_python_graph.py --dry-run

  # Full ingestion
  python ingest_python_graph.py

  # Full ingestion, skip shell bridge
  python ingest_python_graph.py --skip-bridge
        """
    )

    parser.add_argument('--test', '-t', metavar='FILE',
                        help='Test parsing a single Python file')
    parser.add_argument('--sample', '-s', action='store_true',
                        help='Run sample validation on random files')
    parser.add_argument('--sample-size', type=int, default=50,
                        help='Number of files for sample test (default: 50)')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Parse files but do not write to Neo4j')
    parser.add_argument('--skip-bridge', action='store_true',
                        help='Skip Shell->Python INVOKES bridge creation')
    parser.add_argument('--version', '-v', action='version',
                        version=f'%(prog)s {VERSION}')

    args = parser.parse_args()

    print(f"Python Graph Ingestion v{VERSION}")
    print(f"WORKFLOW_ROOT: {WORKFLOW_ROOT}")

    if args.test:
        # Resolve relative paths against WORKFLOW_ROOT
        test_path = args.test
        if not os.path.isabs(test_path):
            test_path = os.path.join(WORKFLOW_ROOT, test_path)
        test_single_file(test_path)
    elif args.sample:
        run_sample_test(args.sample_size)
    else:
        run_full_ingestion(dry_run=args.dry_run, skip_bridge=args.skip_bridge)


if __name__ == '__main__':
    main()
