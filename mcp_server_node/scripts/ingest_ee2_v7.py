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
COLLECTION_NAME = os.getenv("EE2_COLLECTION", "ee2-standards-v7-0-0")
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))

# EE2 Standards source (git submodule)
EE2_ROOT = os.getenv("EE2_ROOT",
    "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/nws-hpc-standards")

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
        
        # MCP custom directives
        self.mcp_patterns = {
            'sme_correction': re.compile(r'\.\.\s+mcp:sme_correction::\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'anti_pattern': re.compile(r'\.\.\s+mcp:anti_pattern::\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'correct_pattern': re.compile(r'\.\.\s+mcp:correct_pattern::\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
            'ai_guidance_rule': re.compile(r'\.\.\s+mcp:ai_guidance_rule::\s*\n((?:\s{3,}.*\n)*)', re.MULTILINE),
        }
    
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
        
        # Extract sections
        sections = self._extract_sections(content)
        
        for section in sections:
            chunk = {
                'text': section['text'],
                'metadata': {
                    'file_path': str(file_path),
                    'title': title,
                    'section': section['title'],
                    'categories': ','.join(categories),
                    'platforms': ','.join(platforms),
                    'has_code_example': section.get('has_code', False),
                    'directive_type': section.get('directive_type', 'content'),
                    'intent': section.get('intent', 'reference'),
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
        
        # Initialize ChromaDB
        self.chroma = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
        self.collection = self.chroma.get_or_create_collection(
            name=collection_name,
            metadata={"version": VERSION, "type": "ee2-standards"}
        )
        
        self.stats = {
            'files_processed': 0,
            'chunks_created': 0,
            'categories_found': set(),
            'platforms_found': set(),
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
        
        self._print_summary()
    
    def _process_directory(self, dir_path: Path):
        """Process all RST files in directory"""
        for rst_file in dir_path.rglob('*.rst'):
            self._process_file(rst_file)
    
    def _process_file(self, file_path: Path):
        """Process single RST file"""
        try:
            chunks = self.parser.parse_file(file_path)
            
            for chunk in chunks:
                doc_id = self._generate_id(chunk['text'], str(file_path))
                
                if doc_id not in self.seen_ids:
                    self.seen_ids.add(doc_id)
                    self.collection.add(
                        ids=[doc_id],
                        documents=[chunk['text']],
                        metadatas=[chunk['metadata']]
                    )
                    self.stats['chunks_created'] += 1
                    
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
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be processed without ingesting')
    
    args = parser.parse_args()
    
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
