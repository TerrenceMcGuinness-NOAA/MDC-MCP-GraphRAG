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
Version: 1.2.0
Phase: 10 (Milestone 2), Phase 34 (NCEPLIBS), Phase 39 (UFS)
Date: February 5, 2026

Key Discovery (M1):
  MUST use FortranFileReader - passing raw strings to parser fails on most files.
  
Phase 39 Enhancement:
  C preprocessor preprocessing (cpp -traditional-cpp) enables parsing of UFS/MOM6/CMEPS
  Fortran files that use #ifdef, #include, #define directives.
  
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
import subprocess
import tempfile
import resource
import time
import gc
import re
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

VERSION = "1.2.0"
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "gfsworkflow2025")

# Phase 48D: AWS backend support — set DB_BACKEND=aws to write to Neptune
# Phase 49: Registry-driven model selection
import sys as _sys
try:
    from ingestion_base import BaseIngester as _BaseIngester
    _bi = _BaseIngester.__new__(_BaseIngester)
    _bi.args = _BaseIngester._parse_common_args(_bi)
    from embedding_registry import EmbeddingModelRegistry as _Reg
    from collection_namer import CollectionNamer as _CN
    _profile = _Reg().get_profile(_bi.args.model)
    _namer = _CN(_profile)
    _REGISTRY_AVAILABLE = True
except Exception:
    _REGISTRY_AVAILABLE = False
    if "--backend" in _sys.argv:
        _bidx = _sys.argv.index("--backend")
        if _bidx + 1 < len(_sys.argv):
            os.environ["DB_BACKEND"] = _sys.argv[_bidx + 1]
try:
    from aws_backend import get_graph_driver as _get_graph_driver, BACKEND as _BACKEND
    _AWS_BACKEND_AVAILABLE = True
except ImportError:
    _AWS_BACKEND_AVAILABLE = False
    _BACKEND = "legacy"

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
# Phase 39: Corrected to match actual directory names
SUBMODULE_PATHS = [
    'sorc/ufs_model.fd',
    'sorc/gsi_enkf.fd',     # was gsi.fd
    'sorc/gdas.cd',          # was gdas.fd (note: .cd not .fd)
    'sorc/ufs_utils.fd',
    'sorc/gsi_utils.fd',
    'sorc/gsi_monitor.fd',
    'sorc/gfs_utils.fd',
    'sorc/nexus.fd',         # air quality emissions
    # JEDI DA ecosystem — pure Fortran heavyweights (Phase 42)
    'sorc/gdas.cd/sorc/crtm',           # 813 F90, 569K LOC — radiative transfer
    'sorc/gdas.cd/sorc/fv3-jedi-lm',    # 105 F90, 266K LOC — linearized model (TL/AD)
    'sorc/gdas.cd/sorc/gsw',            # 196 F90, 191K LOC — seawater toolbox
    'sorc/gdas.cd/sorc/gsibec',         # 108 F90,  92K LOC — GSI background error
    # JEDI DA ecosystem — mixed C++/Fortran interfaces (Phase 42)
    'sorc/gdas.cd/sorc/ufo',            # 209 F90,  68K LOC — observation operators
    'sorc/gdas.cd/sorc/fv3-jedi',       #  69 F90,  50K LOC — atmosphere DA
    'sorc/gdas.cd/sorc/oops',           #  69 F90,  20K LOC — abstract DA framework
    'sorc/gdas.cd/sorc/ioda',           #  26 F90,   6K LOC — observation database
    'sorc/gdas.cd/sorc/soca',           #  21 F90,   6K LOC — ocean DA
    'sorc/gdas.cd/sorc/saber',          #  12 F90,   5K LOC — background error cov.
    'sorc/gdas.cd/sorc/vader',          #   2 F90 — variable transforms
    'sorc/gdas.cd/sorc/bufr-query',     #   7 F90 — obs query library
    'sorc/gdas.cd/sorc/land-jediincr',  #   2 F90 — land DA increment
    # NOTE: femps does NOT exist on disk — omitted
    # NOTE: da-utils (0 F90), jcb (0 F90), jedicmake (CMake) — Python/CMake only
]


# ============================================================================
# SOURCE SANITIZATION (Phase 53 — fparser compatibility)
# ============================================================================

def _sanitize_fortran_source(file_path: str) -> Optional[str]:
    """Fix Fortran source issues that cause fparser to fail.

    Returns path to a sanitized temp file, or None if no fixes were needed.

    Known issues fixed:
    1. Dangling assignment continuations: ``VARIABLE = &`` followed by
       blank/comment lines with no actual continuation value.  Common in CRTM
       where CVS ``$Id$`` keywords were stripped by git.
       Fix: replace the ``&`` with an empty string literal.

    2. Dangling USE/ONLY continuations: ``USE Module, ONLY: X, &`` followed
       by blank/comment lines.  Same CVS stripping root cause.
       Fix: remove the trailing ``, &`` to close the ONLY list.

    3. Non-standard write comma: ``write(6,*),`` — some compilers accept a
       comma after the format specifier but fparser (strict F2003) rejects it.
       Fix: remove the extra comma.

    4. Git merge conflict markers: ``<<<<<<< variant A``, ``=======``,
       ``>>>>>>> variant B`` left in source files.
       Fix: comment them out.
    """
    try:
        with open(file_path, 'r', errors='replace') as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return None

    modified = False

    # --- New statement keywords that signal "this is NOT a continuation" ---
    _NEW_STMT = (
        'TYPE', 'END', 'INTEGER', 'REAL', 'CHARACTER', 'LOGICAL',
        'PUBLIC', 'PRIVATE', 'CONTAINS', 'SUBROUTINE', 'FUNCTION',
        'MODULE', 'PROGRAM', 'USE ', 'IMPLICIT', 'INTERFACE', 'CALL ',
        'IF ', 'IF(', 'DO ', 'SELECT', 'WRITE', 'READ', 'OPEN',
        'CLOSE', 'ALLOCATE', 'DEALLOCATE', 'NULLIFY', 'CLASS',
        'ABSTRACT', 'PROCEDURE', 'GENERIC', 'FINAL', 'DATA ',
    )

    i = 0
    while i < len(lines):
        stripped = lines[i].rstrip()
        code_part = stripped.lstrip()

        # --- Fix 4: Git merge conflict markers ---
        if code_part.startswith(('<<<<<<', '>>>>>>', '======= ')):
            lines[i] = '! [SANITIZED merge marker] ' + lines[i]
            modified = True
            i += 1
            continue

        # --- Fix 3: Non-standard write comma ---
        # write(6,*), or write(*,*), → remove the trailing comma
        if re.match(r'.*\bwrite\s*\([^)]*\)\s*,', code_part, re.IGNORECASE):
            new_line = re.sub(
                r'(\bwrite\s*\([^)]*\))\s*,',
                r'\1 ',
                lines[i],
                flags=re.IGNORECASE,
            )
            if new_line != lines[i]:
                lines[i] = new_line
                modified = True
                i += 1
                continue

        # --- Fixes 1 & 2: Dangling continuations ---
        if stripped.endswith('&') and not code_part.startswith('!'):
            # Scan ahead past blank/comment lines
            j = i + 1
            while j < len(lines) and (
                lines[j].strip() == '' or lines[j].strip().startswith('!')
            ):
                j += 1

            dangling = False
            if j >= len(lines):
                dangling = True
            elif j > i + 1:
                # There's a gap (blank/comment lines) before the next code line
                next_code = lines[j].strip().upper()
                if any(next_code.startswith(kw) for kw in _NEW_STMT):
                    dangling = True

            if dangling:
                # Fix 2: USE ... ONLY: X, &  →  USE ... ONLY: X
                if re.search(r',\s*&\s*$', stripped):
                    lines[i] = re.sub(r',\s*&\s*$', '\n', stripped) + '\n'
                    modified = True
                # Fix 1: VARIABLE = &  →  VARIABLE = ''
                elif '=' in stripped:
                    lines[i] = stripped[:-1] + "''\n"
                    modified = True
                else:
                    # Generic dangling & — just remove it
                    lines[i] = stripped[:-1] + '\n'
                    modified = True
        i += 1

    if not modified:
        return None

    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.f90', delete=False, dir=tempfile.gettempdir()
    )
    tmp.writelines(lines)
    tmp.close()
    return tmp.name


# ============================================================================
# C PREPROCESSOR SUPPORT (Phase 39)
# ============================================================================

# CPP directives that indicate preprocessing is needed
_CPP_DIRECTIVES = ('#ifdef', '#ifndef', '#if ', '#include', '#define', '#else',
                   '#endif', '#undef', '#elif')

# Cache for discovered include directories (per-run)
_include_dirs_cache: Optional[List[str]] = None


def needs_preprocessing(file_path: str) -> bool:
    """Check if a Fortran file uses C preprocessor directives."""
    try:
        with open(file_path, 'r', errors='replace') as f:
            for line in f:
                stripped = line.lstrip()
                if stripped.startswith('#') and any(
                    stripped.startswith(d) for d in _CPP_DIRECTIVES
                ):
                    return True
    except (OSError, UnicodeDecodeError):
        return False
    return False


def discover_include_dirs(workflow_root: str) -> List[str]:
    """Find all directories containing .h, .inc, or .fh files under sorc/."""
    global _include_dirs_cache
    if _include_dirs_cache is not None:
        return _include_dirs_cache

    include_dirs = set()
    sorc_dir = os.path.join(workflow_root, 'sorc')
    if not os.path.isdir(sorc_dir):
        sorc_dir = workflow_root

    for root, dirs, files in os.walk(sorc_dir):
        for f in files:
            if f.endswith(('.h', '.inc', '.fh')):
                include_dirs.add(root)
                break  # one hit per directory is enough

    _include_dirs_cache = sorted(include_dirs)
    return _include_dirs_cache


def preprocess_fortran(file_path: str, include_dirs: List[str] = None) -> Optional[str]:
    """Run cpp -traditional-cpp on a Fortran file, return path to cleaned temp file."""
    cmd = ['cpp', '-traditional-cpp', '-nostdinc', '-P']
    if include_dirs:
        for d in include_dirs:
            cmd.extend(['-I', d])
    cmd.append(file_path)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            tmp = tempfile.NamedTemporaryFile(
                mode='w', suffix='.f90', delete=False, dir=tempfile.gettempdir()
            )
            tmp.write(result.stdout)
            tmp.close()
            return tmp.name
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Fallback: strip directives manually
    return strip_directives_fallback(file_path)


def strip_directives_fallback(file_path: str) -> Optional[str]:
    """Simple fallback: comment out all # directives so fparser2 can parse."""
    try:
        with open(file_path, 'r', errors='replace') as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return None

    cleaned = []
    for line in lines:
        if line.lstrip().startswith('#'):
            cleaned.append('! CPP: ' + line)
        else:
            cleaned.append(line)

    try:
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.f90', delete=False, dir=tempfile.gettempdir()
        )
        tmp.writelines(cleaned)
        tmp.close()
        return tmp.name
    except OSError:
        return None


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
            'files_preprocessed': 0,
            'modules': 0,
            'subroutines': 0,
            'functions': 0,
            'programs': 0,
            'calls': 0,
            'uses': 0,
        }
        self.errors = []
        self._include_dirs = None
    
    def set_include_dirs(self, dirs: List[str]):
        """Set include directories for CPP preprocessing."""
        self._include_dirs = dirs
    
    def parse_file(self, filepath: str) -> Optional[Dict[str, Any]]:
        """
        Parse a Fortran file and extract AST structure.
        
        Phase 39: Automatically preprocesses files containing CPP directives
        (#ifdef, #include, etc.) using cpp -traditional-cpp before parsing.
        
        Phase 53: Sanitizes dangling continuations (e.g. stripped CVS $Id$
        keywords in CRTM) before parsing.  Sanitization runs first, then
        CPP preprocessing if needed.
        """
        temp_path = None
        sanitized_path = None
        actual_path = filepath
        
        try:
            # Phase 53: Sanitize dangling continuations
            sanitized_path = _sanitize_fortran_source(filepath)
            if sanitized_path:
                actual_path = sanitized_path
                self.stats.setdefault('files_sanitized', 0)
                self.stats['files_sanitized'] += 1
            
            # Phase 39: Preprocess files with CPP directives
            if needs_preprocessing(actual_path):
                temp_path = preprocess_fortran(actual_path, self._include_dirs)
                if temp_path:
                    actual_path = temp_path
                    self.stats['files_preprocessed'] += 1
            
            reader = FortranFileReader(actual_path, ignore_comments=True)
            tree = self.parser(reader)
            
            if tree is None:
                self.stats['files_failed'] += 1
                self.errors.append({'file': filepath, 'error': 'Parser returned None'})
                return None
            
            # Use original filepath for node metadata, not temp path
            result = self._extract_structure(tree, filepath)
            self.stats['files_processed'] += 1
            return result
            
        except (Exception, SystemExit) as e:
            self.stats['files_failed'] += 1
            self.errors.append({'file': filepath, 'error': str(e)})
            return None
        finally:
            for p in (temp_path, sanitized_path):
                if p and os.path.exists(p):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
    
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
                self.driver = (_get_graph_driver() if _AWS_BACKEND_AVAILABLE and _BACKEND == "aws"
                               else GraphDatabase.driver(uri, auth=(user, password)))
                # Test connection
                with self.driver.session() as session:
                    session.run("RETURN 1")
                print(f"[OK] Connected to Neo4j at {uri}")
            except Exception as e:
                print(f"[ERROR] Neo4j connection failed: {e}")
                self.driver = None
    
    def create_indexes(self):
        """Create indexes for Fortran nodes.
        
        Skipped on Neptune (DB_BACKEND=aws) — Neptune auto-indexes all properties.
        """
        if self.dry_run or not self.driver:
            print("[DRY-RUN] Would create indexes for FortranModule, FortranSubroutine, etc.")
            return
        
        if _AWS_BACKEND_AVAILABLE and _BACKEND == "aws":
            print("[OK] Skipping index creation (Neptune auto-indexes all properties)")
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
    # Phase 39: Enable preprocessing for test mode too
    include_dirs = discover_include_dirs(WORKFLOW_ROOT)
    parser.set_include_dirs(include_dirs)
    
    preprocessed = needs_preprocessing(filepath)
    result = parser.parse_file(filepath)
    
    if result:
        if verbose:
            print(f"\n[OK] Parsed: {filepath}")
            if preprocessed:
                print(f"    (preprocessed with cpp -traditional-cpp)")
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
            if preprocessed:
                print(f"    (was preprocessed with cpp)")
            if parser.errors:
                print(f"    Error: {parser.errors[-1]['error']}")
    
    return result


def run_sample_test(sample_size: int = 100):
    """Run parsing on a sample of files to validate success rate."""
    print(f"\n{'='*60}")
    print(f"Fortran Graph v{VERSION}: Sample Validation Test")
    print(f"{'='*60}")
    
    # Find files
    files = find_fortran_files(WORKFLOW_ROOT)
    print(f"\n[INFO] Found {len(files)} Fortran files in {WORKFLOW_ROOT}")
    
    if not files:
        print("[ERROR] No Fortran files found!")
        return
    
    # Phase 39: Discover include dirs
    include_dirs = discover_include_dirs(WORKFLOW_ROOT)
    print(f"[INFO] Discovered {len(include_dirs)} include directories for CPP")
    
    # Take sample
    import random
    sample = random.sample(files, min(sample_size, len(files)))
    print(f"[INFO] Testing sample of {len(sample)} files...")
    
    parser = FortranParser()
    parser.set_include_dirs(include_dirs)
    
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


def run_full_ingestion(dry_run: bool = False, repo_name: str = None,
                       skip: int = 0, limit: int = 0):
    """Run full ingestion of all Fortran files to Neo4j."""
    print(f"\n{'='*60}")
    print(f"Fortran Graph Ingestion v{VERSION}")
    if repo_name:
        print(f"Repository: {repo_name}")
    print(f"{'='*60}")
    print(f"Mode: {'DRY-RUN (no Neo4j writes)' if dry_run else 'LIVE'}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if skip:
        print(f"Skipping first {skip} files (resume mode)")
    if limit:
        print(f"Limiting to {limit} files")
    sys.stdout.flush()
    
    # Find all files
    files = find_fortran_files(WORKFLOW_ROOT)
    total_found = len(files)
    print(f"\n[INFO] Found {total_found} Fortran files")
    sys.stdout.flush()
    
    if not files:
        print("[ERROR] No Fortran files found!")
        return
    
    # Apply skip/limit for resume and batching
    if skip:
        files = files[skip:]
        print(f"[INFO] Skipped {skip}, {len(files)} files remaining")
    if limit:
        files = files[:limit]
        print(f"[INFO] Limited to {len(files)} files")
    sys.stdout.flush()
    
    # Phase 39: Discover include directories for CPP preprocessing
    include_dirs = discover_include_dirs(WORKFLOW_ROOT)
    print(f"[INFO] Discovered {len(include_dirs)} include directories for CPP")
    sys.stdout.flush()
    
    # Initialize
    parser = FortranParser()
    parser.set_include_dirs(include_dirs)
    ingester = Neo4jIngester(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, dry_run=dry_run)
    
    if not dry_run:
        ingester.create_indexes()
    
    total_nodes = 0
    total_rels = 0
    t_start = time.time()
    
    def _rss_mb():
        """Current RSS in MB."""
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    
    def _elapsed():
        """Elapsed time as H:MM:SS."""
        s = int(time.time() - t_start)
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    
    def _eta(i, total):
        """Estimated time remaining."""
        if i == 0:
            return "calculating..."
        elapsed = time.time() - t_start
        rate = i / elapsed  # files per second
        remaining = (total - i) / rate
        s = int(remaining)
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    
    print(f"\n[INFO] Processing {len(files)} files (RSS: {_rss_mb():.0f} MB)")
    print(f"[INFO] Progress logged every 50 files, per-file logging to stderr")
    sys.stdout.flush()
    
    # Process files with progress
    for i, filepath in enumerate(files):
        rel_path = os.path.relpath(filepath, WORKFLOW_ROOT)
        
        # Per-file logging to stderr (visible in real-time)
        print(f"  [{i+1}/{len(files)}] PARSE {rel_path}", file=sys.stderr, end="", flush=True)
        
        result = parser.parse_file(filepath)
        
        if result:
            file_nodes = (len(result.get('modules', [])) + len(result.get('subroutines', [])) +
                         len(result.get('functions', [])) + len(result.get('programs', [])))
            file_rels = len(result.get('calls', [])) + len(result.get('uses', []))
            
            print(f" → INGEST ({file_nodes}n/{file_rels}r)", file=sys.stderr, end="", flush=True)
            
            counts = ingester.ingest_file_result(result, repo_name=repo_name)
            total_nodes += counts['nodes']
            total_rels += counts['relationships']
            
            print(f" ✓", file=sys.stderr, flush=True)
        else:
            print(f" → SKIP (parse failed)", file=sys.stderr, flush=True)
        
        # Progress checkpoint every 50 files
        if (i + 1) % 50 == 0 or (i + 1) == len(files):
            # Force garbage collection to release fparser AST remnants
            gc.collect()
            rss = _rss_mb()
            pct = (i + 1) / len(files) * 100
            print(f"  Progress: {i+1}/{len(files)} ({pct:.0f}%) "
                  f"[OK:{parser.stats['files_processed']} FAIL:{parser.stats['files_failed']} "
                  f"CPP:{parser.stats['files_preprocessed']} "
                  f"SAN:{parser.stats.get('files_sanitized', 0)}] "
                  f"Nodes:{total_nodes:,} Rels:{total_rels:,} "
                  f"RSS:{rss:.0f}MB Elapsed:{_elapsed()} ETA:{_eta(i+1, len(files))}")
            sys.stdout.flush()
            # Memory pressure warning
            if rss > 4000:
                print(f"  [WARN] RSS {rss:.0f}MB exceeds 4GB — memory pressure risk", flush=True)
    
    # Final summary
    summary = parser.get_summary()
    print(f"\n{'='*60}")
    print(f"Ingestion Complete — {_elapsed()} elapsed")
    print(f"{'='*60}")
    print(f"  Files processed:    {summary['files']['processed']}")
    print(f"  Files failed:       {summary['files']['failed']}")
    print(f"  Files preprocessed: {parser.stats['files_preprocessed']}")
    print(f"  Success rate:       {summary['files']['success_rate']}")
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
    print(f"\nPeak RSS: {_rss_mb():.0f} MB")
    sys.stdout.flush()
    
    if parser.errors and not dry_run:
        error_file = Path(WORKFLOW_ROOT).parent / 'fortran_parse_errors.json'
        with open(error_file, 'w') as f:
            json.dump(parser.errors[:200], f, indent=2)
        print(f"\n[INFO] First 200 errors saved to: {error_file}")
    
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
    parser.add_argument('--skip', type=int, default=0, metavar='N',
                        help='Skip the first N files (for resuming after OOM)')
    parser.add_argument('--limit', type=int, default=0, metavar='N',
                        help='Process at most N files (0 = all)')
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
        run_full_ingestion(dry_run=args.dry_run, repo_name=args.repo_name,
                           skip=args.skip, limit=args.limit)


if __name__ == '__main__':
    main()
