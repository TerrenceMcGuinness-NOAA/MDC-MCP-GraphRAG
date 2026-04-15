#!/usr/bin/env python3
"""
Enhanced EE2 Compliance Ingester v7.0.0
Specialized ingester for EE2 compliance documentation with RST directive parsing

Features:
- RST directive parsing (all phases)
- Intent-aware metadata (validation, guidance, example, reference)
- Multi-category compliance classification
- Platform-specific filtering (hera, hercules, orion, wcoss2, gaea)
- Code example detection and language tagging

Collection: ee2-standards-v7-0-0
Source: nws-hpc-standards RST documentation

Author: NOAA EMC Global Workflow MCP Team
Version: 7.0.0
Date: December 3, 2025
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import argparse
import hashlib

try:
    import chromadb
except ImportError:
    print("[ERROR] chromadb not installed. Run: pip install chromadb")
    sys.exit(1)

# ============================================================================
# V7 CONFIGURATION
# ============================================================================

VERSION = "7.0.0"
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))

# Phase 49: Registry-driven model selection + AWS backend support
import sys as _sys
_REGISTRY_AVAILABLE = False
_PROVIDER = None
try:
    from embedding_registry import EmbeddingModelRegistry as _Reg
    from embedding_provider import create_provider as _cp
    from collection_namer import CollectionNamer as _CN
    _args_model = "mpnet768"
    for _i, _a in enumerate(_sys.argv):
        if _a == "--model" and _i + 1 < len(_sys.argv):
            _args_model = _sys.argv[_i + 1]
    _profile = _Reg().get_profile(_args_model)
    _PROVIDER = _cp(_profile)
    _namer = _CN(_profile)
    COLLECTION_NAME = _namer.get_name("ee2-standards", "v7-0-0")
    _REGISTRY_AVAILABLE = True
except Exception:
    COLLECTION_NAME = os.getenv("EE2_COLLECTION", "ee2-standards-v5-0-0-enhanced")

if "--backend" in _sys.argv:
    _bidx = _sys.argv.index("--backend")
    if _bidx + 1 < len(_sys.argv):
        os.environ["DB_BACKEND"] = _sys.argv[_bidx + 1]
try:
    from aws_backend import get_vector_client as _get_vector_client, BACKEND as _BACKEND
    _AWS_BACKEND_AVAILABLE = True
except ImportError:
    _AWS_BACKEND_AVAILABLE = False
    _BACKEND = "legacy"

# EE2 Standards source (git submodule)
EE2_ROOT = os.getenv("EE2_ROOT",
    "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/nws-hpc-standards")

# SDD Framework annotations (SME corrections, pattern recognition)
SDD_ANNOTATIONS_ROOT = os.getenv("SDD_ANNOTATIONS_ROOT",
    "/mcp_rag_eib/eib-mcp-rag-server/sdd_framework/phase2_annotations")

# Directories to scan for RST files
RST_DIRECTORIES = [
    'standards',
    'docs',
    'examples',
]

# EE2 Compliance categories
EE2_CATEGORIES = [
    'error_handling',
    'environment_variables',
    'file_naming',
    'workflow_structure',
    'production_utilities',
    'code_standards',
    'directory_structure',
    'logging',
    'testing',
    'documentation'
]

# HPC Platforms
HPC_PLATFORMS = ['hera', 'hercules', 'orion', 'wcoss2', 'gaea']


# ============================================================================
# RST DIRECTIVE PARSER
# ============================================================================

class RSTDirectiveParser:
    """Parse RST files and extract MCP directives"""
    
    def __init__(self):
        # Standard RST directives
        self.directive_patterns = {
            'note': re.compile(r'\.\.\s+note::\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'warning': re.compile(r'\.\.\s+warning::\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'code-block': re.compile(r'\.\.\s+code-block::\s*(\w+)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'important': re.compile(r'\.\.\s+important::\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
        }
        
        # MCP custom directives - capture directive name and full content block
        # Phase 2 Core Directives (per PHASE_2_HYBRID_ARCHITECTURE_SPECIFICATION.md)
        self.mcp_patterns = {
            'sme_correction': re.compile(r'\.\.\s+mcp:sme_correction::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'anti_pattern': re.compile(r'\.\.\s+mcp:anti_pattern::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'correct_pattern': re.compile(r'\.\.\s+mcp:correct_pattern::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'ai_guidance_rule': re.compile(r'\.\.\s+mcp:ai_guidance_rule::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'intent': re.compile(r'\.\.\s+mcp:intent::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'compliance': re.compile(r'\.\.\s+mcp:compliance::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'severity': re.compile(r'\.\.\s+mcp:severity::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'utility': re.compile(r'\.\.\s+mcp:utility::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'example': re.compile(r'\.\.\s+mcp:example::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'pattern': re.compile(r'\.\.\s+mcp:pattern::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'envvar': re.compile(r'\.\.\s+mcp:envvar::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            # File naming convention directives (added Dec 2025)
            'file_naming_pattern': re.compile(r'\.\.\s+mcp:file_naming_pattern::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'file_naming_rule': re.compile(r'\.\.\s+mcp:file_naming_rule::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'llm_validation_prompt': re.compile(r'\.\.\s+mcp:llm_validation_prompt::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            # Missing directives from nws-hpc-standards/docs/standards.rst (added Dec 17, 2025)
            'context_types': re.compile(r'\.\.\s+mcp:context_types::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'guidance': re.compile(r'\.\.\s+mcp:guidance::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'sme_guidance': re.compile(r'\.\.\s+mcp:sme_guidance::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'sme_validation': re.compile(r'\.\.\s+mcp:sme_validation::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'validation': re.compile(r'\.\.\s+mcp:validation::\s*(\w*)\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
        }
        
        # Pattern to extract directive attributes like :severity: critical
        self.attribute_pattern = re.compile(r':(\w+):\s*(.+?)(?=\n\s*:|$)', re.MULTILINE)
    
    def _parse_directive_attributes(self, content: str) -> Dict[str, str]:
        """Extract :attribute: value pairs from directive content"""
        attributes = {}
        for match in self.attribute_pattern.finditer(content):
            key = match.group(1).strip()
            value = match.group(2).strip()
            attributes[key] = value
        return attributes
    
    def _extract_mcp_directives(self, content: str, file_path: str) -> List[Dict]:
        """Extract MCP semantic annotation directives as separate high-value chunks.
        
        These directives are invisible to RST renderers (they're comments)
        but provide high-value semantic annotations for AI guidance.
        """
        directives = []
        
        # Map directive types to intent categories
        intent_map = {
            'sme_correction': 'validation',
            'anti_pattern': 'validation',
            'correct_pattern': 'guidance',
            'ai_guidance_rule': 'guidance',
            'intent': 'reference',
            'compliance': 'validation',
            'severity': 'validation',
            'utility': 'reference',
            'example': 'example',
            'pattern': 'guidance',
            'envvar': 'reference',
            # File naming convention directives
            'file_naming_pattern': 'guidance',
            'file_naming_rule': 'validation',
            'llm_validation_prompt': 'guidance',
            # New directives from nws-hpc-standards (Dec 17, 2025)
            'context_types': 'reference',       # Defines context discrimination rules
            'guidance': 'guidance',             # Platform-specific guidance (hera, wcoss2)
            'sme_guidance': 'guidance',         # Subject Matter Expert guidance annotations
            'sme_validation': 'validation',     # SME validation criteria
            'validation': 'validation',         # Test/validation criteria
        }
        
        for directive_type, pattern in self.mcp_patterns.items():
            for match in pattern.finditer(content):
                directive_name = match.group(1) if match.group(1) else 'unnamed'
                directive_content = match.group(2)
                
                # Parse attributes from content
                attributes = self._parse_directive_attributes(directive_content)
                
                # Clean up the text content (remove attribute lines, keep description)
                lines = directive_content.split('\n')
                text_lines = []
                for line in lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith(':'):
                        text_lines.append(stripped)
                cleaned_text = ' '.join(text_lines)
                
                # Build full text including directive context
                full_text = f"[MCP:{directive_type}:{directive_name}] {cleaned_text}"
                
                if len(full_text) >= 30:  # Minimum content threshold
                    directives.append({
                        'title': f'mcp:{directive_type}::{directive_name}',
                        'text': full_text[:2000],
                        'has_code': '```' in directive_content or 'code-block' in directive_content,
                        'directive_type': directive_type,
                        'directive_name': directive_name,
                        'intent': intent_map.get(directive_type, 'guidance'),
                        'is_mcp_annotation': True,
                        'attributes': attributes,
                    })
        
        return directives
    
    def parse_file(self, file_path: Path) -> List[Dict]:
        """Parse RST file and extract chunks with metadata"""
        content = file_path.read_text(errors='replace')
        chunks = []
        
        # Extract title
        title_match = re.search(r'^([^\n]+)\n[=]+\s*$', content, re.MULTILINE)
        title = title_match.group(1) if title_match else file_path.stem
        
        # Detect categories
        categories = self._detect_categories(content, str(file_path))
        
        # Detect platforms
        platforms = self._detect_platforms(content)
        
        # FIRST: Extract MCP semantic annotation directives (high-value chunks)
        mcp_directives = self._extract_mcp_directives(content, str(file_path))
        
        for directive in mcp_directives:
            # Build metadata from directive attributes
            metadata = {
                'source': 'ee2-standards-rst',
                'source_type': 'mcp_directive',
                'file_path': str(file_path),
                'title': title,
                'section': directive['title'],
                'categories': ','.join(categories),
                'platforms': ','.join(platforms),
                'has_code_example': directive.get('has_code', False),
                'directive_type': directive['directive_type'],
                'directive_name': directive.get('directive_name', ''),
                'intent': directive['intent'],
                'is_mcp_annotation': True,
                'version': VERSION,
                'ingested_at': datetime.now().isoformat()
            }
            # Add parsed attributes as metadata
            for attr_key, attr_value in directive.get('attributes', {}).items():
                metadata[f'mcp_{attr_key}'] = attr_value
            
            chunks.append({
                'text': directive['text'],
                'metadata': metadata
            })
        
        # SECOND: Extract regular RST sections
        sections = self._extract_sections(content)
        
        for section in sections:
            chunk = {
                'text': section['text'],
                'metadata': {
                    'source': 'ee2-standards-rst',
                    'source_type': 'local_rst',
                    'file_path': str(file_path),
                    'title': title,
                    'section': section['title'],
                    'categories': ','.join(categories),
                    'platforms': ','.join(platforms),
                    'has_code_example': section.get('has_code', False),
                    'directive_type': section.get('directive_type', 'content'),
                    'intent': section.get('intent', 'reference'),
                    'is_mcp_annotation': False,
                    'version': VERSION,
                    'ingested_at': datetime.now().isoformat()
                }
            }
            chunks.append(chunk)
        
        return chunks
    
    def _detect_categories(self, content: str, file_path: str) -> List[str]:
        """Detect EE2 compliance categories from content"""
        categories = []
        content_lower = content.lower()
        path_lower = file_path.lower()
        
        keyword_map = {
            'error_handling': ['error', 'exception', 'try', 'catch', 'err_exit', 'err_chk'],
            'environment_variables': ['export', 'env', 'environment', 'variable', 'parm'],
            'file_naming': ['naming', 'convention', 'file name', 'filename'],
            'workflow_structure': ['workflow', 'rocoto', 'ecflow', 'job'],
            'production_utilities': ['production', 'prod_util', 'utility'],
            'code_standards': ['standard', 'style', 'convention', 'best practice'],
            'logging': ['log', 'logging', 'postmsg', 'echo'],
            'testing': ['test', 'validation', 'verify'],
        }
        
        for category, keywords in keyword_map.items():
            for keyword in keywords:
                if keyword in content_lower or keyword in path_lower:
                    categories.append(category)
                    break
        
        return list(set(categories)) or ['general']
    
    def _detect_platforms(self, content: str) -> List[str]:
        """Detect HPC platforms mentioned in content"""
        platforms = []
        content_lower = content.lower()
        
        for platform in HPC_PLATFORMS:
            if platform in content_lower:
                platforms.append(platform)
        
        return platforms or ['generic']
    
    def _extract_sections(self, content: str) -> List[Dict]:
        """Extract sections from RST content"""
        sections = []
        
        # Split by section headers (underlined titles)
        section_pattern = re.compile(r'^([^\n]+)\n[-~^]+\s*$', re.MULTILINE)
        matches = list(section_pattern.finditer(content))
        
        if not matches:
            # No sections found, treat entire content as one chunk
            if len(content.strip()) >= 100:
                sections.append({
                    'title': 'main',
                    'text': content[:2000],
                    'has_code': '.. code-block::' in content,
                    'directive_type': 'content',
                    'intent': 'reference'
                })
            return sections
        
        for i, match in enumerate(matches):
            section_title = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            
            section_text = content[start:end].strip()
            
            if len(section_text) >= 100:
                # Detect intent
                intent = 'reference'
                if 'must' in section_text.lower() or 'required' in section_text.lower():
                    intent = 'validation'
                elif 'example' in section_title.lower():
                    intent = 'example'
                elif 'how to' in section_title.lower() or 'guide' in section_title.lower():
                    intent = 'guidance'
                
                sections.append({
                    'title': section_title,
                    'text': section_text[:2000],
                    'has_code': '.. code-block::' in section_text,
                    'directive_type': 'content',
                    'intent': intent
                })
        
        return sections


# ============================================================================
# EE2 INGESTER
# ============================================================================

class EE2IngesterV7:
    """V7 EE2 Standards ingester"""
    
    def __init__(self, collection_name: str = COLLECTION_NAME):
        self.collection_name = collection_name
        self.parser = RSTDirectiveParser()
        
        # Initialize vector client (ChromaDB or OpenSearch)
        if _AWS_BACKEND_AVAILABLE and _BACKEND == "aws":
            embed_fn = _PROVIDER.embed if _PROVIDER else None
            self.chroma = _get_vector_client(embedding_function=embed_fn)
        else:
            self.chroma = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
        self.collection = self.chroma.get_or_create_collection(
            name=collection_name,
            metadata={"version": VERSION, "type": "ee2-standards"}
        )
        
        self.stats = {
            'files_processed': 0,
            'chunks_created': 0,
            'mcp_directives_found': 0,
            'categories_found': set(),
            'platforms_found': set(),
            'directive_types_found': set(),
            'errors': 0
        }
        self.seen_ids = set()
    
    def ingest_directory(self, root_path: str = EE2_ROOT):
        """Ingest all EE2 documentation from directory"""
        print(f"\n{'='*70}")
        print(f"EE2 Standards Ingestion v{VERSION}")
        print(f"Collection: {self.collection_name}")
        print(f"Source: {root_path}")
        print(f"{'='*70}\n")
        
        root = Path(root_path)
        if not root.exists():
            print(f"[ERROR] Root path not found: {root_path}")
            print("  Make sure nws-hpc-standards submodule is initialized:")
            print("  git submodule update --init --recursive")
            return
        
        for rst_dir in RST_DIRECTORIES:
            dir_path = root / rst_dir
            if dir_path.exists():
                print(f"\n[DIR] Processing {rst_dir}/")
                self._process_directory(dir_path)
            else:
                print(f"[SKIP] Directory not found: {rst_dir}/")
        
        # Also process root-level RST files
        print("\n[DIR] Processing root RST files")
        for rst_file in root.glob('*.rst'):
            self._process_file(rst_file)
        
        # Process SDD Framework annotations (SME corrections)
        sdd_root = Path(SDD_ANNOTATIONS_ROOT)
        if sdd_root.exists():
            print(f"\n[DIR] Processing SDD annotations: {SDD_ANNOTATIONS_ROOT}")
            self._process_directory(sdd_root, source_prefix='sdd-annotations')
        else:
            print(f"[SKIP] SDD annotations not found: {SDD_ANNOTATIONS_ROOT}")
        
        self._print_summary()
    
    def _process_directory(self, dir_path: Path, source_prefix: str = None):
        """Process all RST files in directory"""
        for rst_file in dir_path.rglob('*.rst'):
            self._process_file(rst_file, source_prefix=source_prefix)
    
    def _process_file(self, file_path: Path, source_prefix: str = None):
        """Process single RST file"""
        try:
            chunks = self.parser.parse_file(file_path)
            
            for chunk in chunks:
                # Override source if prefix provided (e.g., for SDD annotations)
                if source_prefix:
                    chunk['metadata']['source'] = source_prefix
                    chunk['metadata']['source_type'] = 'sdd_annotation'
                
                doc_id = self._generate_id(chunk['text'], str(file_path))
                
                if doc_id not in self.seen_ids:
                    self.seen_ids.add(doc_id)
                    self.collection.add(
                        ids=[doc_id],
                        documents=[chunk['text']],
                        metadatas=[chunk['metadata']]
                    )
                    self.stats['chunks_created'] += 1
                    
                    # Track MCP annotations
                    if chunk['metadata'].get('is_mcp_annotation'):
                        self.stats['mcp_directives_found'] += 1
                        directive_type = chunk['metadata'].get('directive_type', 'unknown')
                        self.stats['directive_types_found'].add(directive_type)
                    
                    # Track categories and platforms
                    for cat in chunk['metadata'].get('categories', '').split(','):
                        if cat:
                            self.stats['categories_found'].add(cat)
                    for plat in chunk['metadata'].get('platforms', '').split(','):
                        if plat:
                            self.stats['platforms_found'].add(plat)
            
            self.stats['files_processed'] += 1
            print(f"  [OK] {file_path.name}: {len(chunks)} chunks")
            
        except Exception as e:
            print(f"  [ERROR] {file_path.name}: {e}")
            self.stats['errors'] += 1
    
    def _generate_id(self, text: str, file_path: str) -> str:
        """Generate unique document ID"""
        content = f"{file_path}:{text[:500]}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _print_summary(self):
        """Print ingestion summary"""
        print(f"\n{'='*70}")
        print("EE2 INGESTION SUMMARY")
        print(f"{'='*70}")
        print(f"Collection:         {self.collection_name}")
        print(f"Version:            {VERSION}")
        print(f"Files processed:    {self.stats['files_processed']}")
        print(f"Chunks created:     {self.stats['chunks_created']}")
        print(f"MCP directives:     {self.stats['mcp_directives_found']}")
        if self.stats['directive_types_found']:
            print(f"Directive types:    {', '.join(sorted(self.stats['directive_types_found']))}")
        print(f"Categories found:   {', '.join(sorted(self.stats['categories_found']))}")
        print(f"Platforms found:    {', '.join(sorted(self.stats['platforms_found']))}")
        print(f"Errors:             {self.stats['errors']}")
        print(f"{'='*70}\n")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='V7 EE2 Standards Ingestion')
    parser.add_argument('--collection', default=COLLECTION_NAME,
                       help=f'Collection name (default: {COLLECTION_NAME})')
    parser.add_argument('--root', default=EE2_ROOT,
                       help=f'EE2 standards root path (default: {EE2_ROOT})')
    parser.add_argument('--model', default='mpnet768',
                       help='Embedding model profile (default: mpnet768)')
    parser.add_argument('--backend', default='legacy',
                       help='Database backend: legacy or aws (default: legacy)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be processed without ingesting')
    
    args, _ = parser.parse_known_args()
    
    if args.dry_run:
        print("[DRY RUN] Would process the following:")
        root = Path(args.root)
        for rst_dir in RST_DIRECTORIES:
            dir_path = root / rst_dir
            if dir_path.exists():
                file_count = sum(1 for _ in dir_path.rglob('*.rst'))
                print(f"  - {rst_dir}/: {file_count} RST files")
            else:
                print(f"  - {rst_dir}/: (not found)")
        return
    
    ingester = EE2IngesterV7(args.collection)
    ingester.ingest_directory(args.root)


if __name__ == '__main__':
    main()
