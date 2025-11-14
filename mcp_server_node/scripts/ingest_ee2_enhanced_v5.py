#!/usr/bin/env python3
"""
Enhanced EE2 Compliance Ingester v5.0.0
Specialized ingester for EE2 compliance documentation with RST directive parsing

Features:
- RST directive parsing (mcp:standard, mcp:example, mcp:guidance, etc.)
- Intent-aware metadata (validation, guidance, example, reference)
- Multi-category compliance classification
- Platform-specific filtering (hera, hercules, orion, wcoss2, gaea)
- Code example detection and language tagging
- Quality scoring and importance weighting
- Semantic tag extraction

Author: NOAA EMC Global Workflow MCP Team
Version: 5.0.0
Date: November 14, 2025
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import argparse

# Import base ingestion classes
from ingestion_base import (
    BaseIngester,
    RSTDirectiveParser,
    ChromaDBClient,
    SemanticChunker,
    MetadataEnricher
)


class EnhancedEE2Ingester(BaseIngester):
    """
    Specialized ingester for EE2 compliance documentation.
    Inherits from BaseIngester and adds RST directive parsing capabilities.
    """
    
    def __init__(self, collection_name='ee2-standards-v5-0-0-enhanced',
                 chromadb_host='localhost', chromadb_port=8080):
        """
        Initialize Enhanced EE2 Ingester
        
        Args:
            collection_name: ChromaDB collection name
            chromadb_host: ChromaDB server host
            chromadb_port: ChromaDB server port
        """
        super().__init__(
            collection_name=collection_name,
            version='5.0.0'
        )
        
        # Initialize RST directive parser
        self.rst_parser = RSTDirectiveParser()
        
        # Load EE2 category definitions (from EE2VectorStore.js)
        self.ee2_categories = self.rst_parser.COMPLIANCE_CATEGORIES
        
        # ChromaDB connection
        self.chromadb_host = chromadb_host
        self.chromadb_port = chromadb_port
        
        # Enhanced statistics
        self.stats = {
            'rst_files_processed': 0,
            'directives_parsed': 0,
            'chunks_created': 0,
            'code_examples_found': 0,
            'validation_chunks': 0,
            'guidance_chunks': 0,
            'example_chunks': 0,
            'reference_chunks': 0,
            'by_category': {},
            'by_platform': {},
        }
    
    def process_rst_document(self, file_path: str, content: str,
                            base_metadata: Dict = None) -> List[Dict]:
        """
        Process RST document with directive parsing and metadata enrichment.
        
        Args:
            file_path: Path to source RST file
            content: Raw RST document content
            base_metadata: Optional base metadata dict
            
        Returns:
            List of chunk dicts with {text, metadata}
        """
        if base_metadata is None:
            base_metadata = {}
        
        # Add source file info
        base_metadata['source_file'] = str(file_path)
        base_metadata['file_type'] = 'rst'
        base_metadata['ingestion_version'] = '5.0.0'
        
        # Parse RST directives
        directive_sections = self.rst_parser.parse_document(content, str(file_path))
        
        chunks = []
        
        for section in directive_sections:
            # Get directive info
            directive_type = section['directive_type']
            directive_attrs = section['attributes']
            section_text = section['text']
            
            # Skip empty sections
            if not section_text.strip():
                continue
            
            # Chunk the section text semantically (if large)
            section_chunks = self._chunk_section_text(
                section_text,
                min_size=200,
                max_size=2000
            )
            
            # Enrich each chunk with directive metadata
            for i, chunk_text in enumerate(section_chunks):
                metadata = self.enrich_metadata(
                    chunk_text,
                    base_metadata.copy(),
                    directive_type,
                    directive_attrs,
                    chunk_index=i,
                    total_chunks=len(section_chunks)
                )
                
                chunks.append({
                    'text': chunk_text,
                    'metadata': metadata
                })
        
        self.stats['rst_files_processed'] += 1
        self.stats['directives_parsed'] += len(directive_sections)
        self.stats['chunks_created'] += len(chunks)
        
        return chunks
    
    def _chunk_section_text(self, text: str, min_size: int, max_size: int) -> List[str]:
        """
        Split large section text into smaller semantic chunks.
        Preserves paragraph boundaries.
        """
        # If text is within limits, return as single chunk
        if len(text) <= max_size:
            return [text]
        
        chunks = []
        current_chunk = ""
        
        # Split by double newline (paragraph boundary)
        paragraphs = text.split('\n\n')
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # If adding this paragraph exceeds max_size, save current chunk
            if current_chunk and len(current_chunk) + len(para) > max_size:
                if len(current_chunk) >= min_size:
                    chunks.append(current_chunk)
                    current_chunk = para
                else:
                    # Current chunk too small, keep accumulating
                    current_chunk += '\n\n' + para
            else:
                if current_chunk:
                    current_chunk += '\n\n' + para
                else:
                    current_chunk = para
        
        # Add final chunk
        if current_chunk and len(current_chunk) >= min_size:
            chunks.append(current_chunk)
        elif current_chunk and chunks:
            # Append to last chunk if too small
            chunks[-1] += '\n\n' + current_chunk
        elif current_chunk:
            # Only chunk, keep even if small
            chunks.append(current_chunk)
        
        return chunks
    
    def enrich_metadata(self, chunk_text: str, base_metadata: Dict,
                       directive_type: Optional[str], directive_attrs: Dict,
                       chunk_index: int = 0, total_chunks: int = 1) -> Dict:
        """
        Add intent-aware metadata to chunk.
        
        Combines:
        - Base metadata (URL, file, chunk index)
        - RST directive information
        - Compliance category classification
        - Intent detection
        - Platform specificity
        - Quality/importance scoring
        - Semantic tags
        - Code example detection
        """
        metadata = base_metadata.copy()
        
        # Chunk tracking
        metadata['chunk_index'] = chunk_index
        metadata['total_chunks'] = total_chunks
        metadata['chunk_type'] = 'semantic_section'
        
        # RST directive information
        metadata['rst_directive'] = directive_type if directive_type else 'none'
        
        # Extract explicit attributes from directive
        metadata['compliance_category'] = directive_attrs.get('category', 'general')
        metadata['standard_level'] = directive_attrs.get('level', 'should')
        metadata['platform'] = directive_attrs.get('platforms', directive_attrs.get('platform', 'all'))
        metadata['priority'] = directive_attrs.get('priority', 'medium')
        
        # Classify intent (validation, guidance, example, reference)
        intent, intent_confidence = self.rst_parser.identify_intent(
            chunk_text, 
            directive_type
        )
        metadata['intent'] = intent
        metadata['intent_confidence'] = intent_confidence
        
        # Track intent statistics
        intent_key = f"{intent}_chunks"
        self.stats[intent_key] = self.stats.get(intent_key, 0) + 1
        
        # Multi-category compliance classification
        categories = self.rst_parser.categorize_compliance(
            chunk_text,
            directive_attrs
        )
        
        if categories:
            # Primary category (highest confidence)
            metadata['compliance_category'] = categories[0][0]
            metadata['category_confidence'] = categories[0][1]
            
            # All applicable categories (convert list to comma-separated string)
            metadata['compliance_categories'] = ','.join([cat for cat, _ in categories])
            
            # Track category statistics
            for category, _ in categories:
                self.stats['by_category'][category] = self.stats['by_category'].get(category, 0) + 1
        else:
            metadata['compliance_categories'] = 'general'
            metadata['category_confidence'] = 0.5
        
        # Extract semantic tags for enhanced searchability
        # (convert list to comma-separated string for ChromaDB)
        categories_list = metadata['compliance_categories'].split(',')
        semantic_tags = self.extract_semantic_tags(chunk_text, categories_list)
        metadata['semantic_tags'] = ','.join(semantic_tags) if semantic_tags else ''
        
        # Code example detection
        code_blocks = self.rst_parser.extract_code_blocks(chunk_text)
        metadata['has_code_example'] = len(code_blocks) > 0
        
        if code_blocks:
            metadata['example_language'] = code_blocks[0].get('language', 'unknown')
            metadata['example_count'] = len(code_blocks)
            self.stats['code_examples_found'] += 1
        else:
            metadata['has_code_example'] = False
            metadata['example_count'] = 0
        
        # Quality scoring
        metadata['quality_score'] = self.compute_quality_score(chunk_text, metadata)
        
        # Importance scoring (from EE2VectorStore.js category weights)
        category = metadata['compliance_category']
        category_info = self.ee2_categories.get(category, {})
        metadata['importance_score'] = category_info.get('weight', 1.0)
        
        # Platform specificity
        platforms = metadata['platform'].split(',')
        metadata['platform_specific'] = metadata['platform'] != 'all' and len(platforms) > 0
        
        # Track platform statistics
        for platform in platforms:
            platform = platform.strip()
            if platform and platform != 'all':
                self.stats['by_platform'][platform] = self.stats['by_platform'].get(platform, 0) + 1
        
        # Timestamps
        metadata['created_at'] = datetime.now().isoformat()
        metadata['ingestion_version'] = '5.0.0'
        
        return metadata
    
    def extract_semantic_tags(self, text: str, categories: List[str]) -> List[str]:
        """
        Extract semantic tags from text for enhanced searchability.
        
        Uses simple keyword extraction based on:
        - Category-specific keywords
        - All-caps identifiers (ENV_VAR)
        - Common technical terms
        """
        tags = set()
        
        # Add category-based keywords
        for category in categories:
            if category in self.ee2_categories:
                category_keywords = self.ee2_categories[category]['keywords']
                for keyword in category_keywords:
                    if keyword.lower() in text.lower():
                        tags.add(keyword)
        
        # Extract all-caps identifiers (likely env vars or constants)
        all_caps_pattern = r'\b[A-Z][A-Z_]{2,}\b'
        all_caps_matches = re.findall(all_caps_pattern, text)
        for match in all_caps_matches[:5]:  # Limit to 5
            tags.add(match.lower())
        
        # Extract common technical terms (simple heuristic)
        technical_terms = [
            'bash', 'python', 'script', 'function', 'module',
            'check', 'validate', 'error', 'exit', 'trap',
            'export', 'source', 'workflow', 'job', 'task'
        ]
        
        for term in technical_terms:
            if term in text.lower():
                tags.add(term)
        
        return sorted(list(tags))[:10]  # Limit to 10 tags
    
    def compute_quality_score(self, text: str, metadata: Dict) -> float:
        """
        Calculate quality score based on:
        - Text completeness (has structure, examples)
        - Metadata richness
        - Code example presence
        - Standard level (MUST > SHOULD > MAY)
        - RST directive structure
        - Intent confidence
        
        Returns: Score 0.0 - 1.0
        """
        score = 0.0
        
        # Length appropriateness (200-2000 chars optimal)
        length = len(text)
        if 500 <= length <= 1500:
            score += 0.20
        elif 200 <= length < 500 or 1500 < length <= 2000:
            score += 0.15
        elif length < 200:
            score += 0.05
        else:
            score += 0.10
        
        # Has structured content (headers, lists, code)
        if any(marker in text for marker in ['##', '===', '---', '- ', '```', '.. code-block::']):
            score += 0.15
        
        # Code example bonus
        if metadata.get('has_code_example'):
            score += 0.20
        
        # Standard level importance
        level = metadata.get('standard_level', 'should')
        if level == 'must':
            score += 0.15
        elif level == 'should':
            score += 0.10
        else:  # may
            score += 0.05
        
        # RST directive structure (explicit metadata)
        if metadata.get('rst_directive') != 'none':
            score += 0.10
        
        # Intent confidence
        intent_conf = metadata.get('intent_confidence', 0.5)
        score += intent_conf * 0.10
        
        # Category confidence
        cat_conf = metadata.get('category_confidence', 0.5)
        score += cat_conf * 0.10
        
        # Normalize to 0-1 range
        return min(score, 1.0)
    
    def ingest_directory(self, directory: str, pattern: str = '*.rst',
                        recursive: bool = True) -> int:
        """
        Ingest all RST files from a directory.
        
        Args:
            directory: Root directory to scan
            pattern: File pattern (default: *.rst)
            recursive: Scan subdirectories
            
        Returns:
            Number of documents ingested
        """
        print(f"\n[INIT] Enhanced EE2 Ingester v5.0.0")
        print(f"[INIT] Directory: {directory}")
        print(f"[INIT] Pattern: {pattern}")
        print(f"[INIT] Collection: {self.collection_name}")
        
        # Find RST files
        path = Path(directory)
        if recursive:
            rst_files = list(path.rglob(pattern))
        else:
            rst_files = list(path.glob(pattern))
        
        print(f"[INIT] Found {len(rst_files)} RST files\n")
        
        if not rst_files:
            print("[WARN] No RST files found")
            return 0
        
        # Initialize ChromaDB client
        self.db_client = ChromaDBClient(
            host=self.chromadb_host,
            port=self.chromadb_port
        )
        self.db_client.connect()
        
        self.collection = self.db_client.get_or_create_collection(
            self.collection_name,
            metadata={
                'version': '5.0.0-enhanced',
                'created': datetime.now().isoformat(),
                'description': 'Enhanced EE2 Compliance Standards with Intent-Aware Metadata',
                'embedding_model': 'all-mpnet-base-v2',
                'embedding_dimensions': '768',
                'source_type': 'rst_directives',
                'intent_aware': 'true',
                'compliance_categories': ','.join(self.ee2_categories.keys())
            }
        )
        
        # Process each RST file
        total_chunks = 0
        
        for i, rst_file in enumerate(rst_files):
            print(f"[{i+1}/{len(rst_files)}] Processing: {rst_file.name}")
            
            try:
                # Read file
                with open(rst_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Process RST document
                chunks = self.process_rst_document(
                    rst_file,
                    content,
                    base_metadata={
                        'source_path': str(rst_file),
                        'relative_path': str(rst_file.relative_to(directory))
                    }
                )
                
                # Add chunks to collection
                if chunks:
                    documents = [c['text'] for c in chunks]
                    metadatas = [c['metadata'] for c in chunks]
                    ids = [f"{rst_file.stem}_{j}" for j in range(len(chunks))]
                    
                    self.db_client.add_documents_batch(
                        self.collection,
                        documents,
                        metadatas,
                        ids
                    )
                    
                    total_chunks += len(chunks)
                    print(f"  Added {len(chunks)} chunks")
                else:
                    print(f"  [SKIP] No chunks generated")
                    
            except Exception as e:
                print(f"  [ERROR] Failed to process {rst_file.name}: {e}")
                continue
        
        # Print statistics
        self.print_statistics()
        
        return total_chunks
    
    def print_statistics(self):
        """Print detailed ingestion statistics"""
        print("\n" + "="*70)
        print("ENHANCED EE2 INGESTION STATISTICS")
        print("="*70)
        print(f"  RST files processed: {self.stats['rst_files_processed']}")
        print(f"  Directives parsed: {self.stats['directives_parsed']}")
        print(f"  Chunks created: {self.stats['chunks_created']}")
        print(f"  Code examples found: {self.stats['code_examples_found']}")
        
        print(f"\n  By Intent:")
        print(f"    Validation: {self.stats.get('validation_chunks', 0)}")
        print(f"    Guidance: {self.stats.get('guidance_chunks', 0)}")
        print(f"    Example: {self.stats.get('example_chunks', 0)}")
        print(f"    Reference: {self.stats.get('reference_chunks', 0)}")
        
        if self.stats['by_category']:
            print(f"\n  By Category:")
            for category, count in sorted(self.stats['by_category'].items()):
                print(f"    {category}: {count}")
        
        if self.stats['by_platform']:
            print(f"\n  By Platform:")
            for platform, count in sorted(self.stats['by_platform'].items()):
                print(f"    {platform}: {count}")
        
        if self.collection:
            print(f"\n  Collection size: {self.collection.count()} documents")
        
        print("="*70)


def main():
    """Main entry point for CLI usage"""
    parser = argparse.ArgumentParser(
        description='Enhanced EE2 Compliance Ingester v5.0.0'
    )
    parser.add_argument(
        'directory',
        help='Directory containing RST files'
    )
    parser.add_argument(
        '--collection',
        default='ee2-standards-v5-0-0-enhanced',
        help='ChromaDB collection name'
    )
    parser.add_argument(
        '--pattern',
        default='*.rst',
        help='File pattern to match (default: *.rst)'
    )
    parser.add_argument(
        '--no-recursive',
        action='store_true',
        help='Do not scan subdirectories'
    )
    parser.add_argument(
        '--host',
        default='localhost',
        help='ChromaDB host'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8080,
        help='ChromaDB port'
    )
    
    args = parser.parse_args()
    
    # Create ingester
    ingester = EnhancedEE2Ingester(
        collection_name=args.collection,
        chromadb_host=args.host,
        chromadb_port=args.port
    )
    
    # Ingest directory
    try:
        chunks_ingested = ingester.ingest_directory(
            args.directory,
            pattern=args.pattern,
            recursive=not args.no_recursive
        )
        
        print(f"\n[OK] Ingestion complete: {chunks_ingested} chunks")
        return 0
        
    except Exception as e:
        print(f"\n[ERROR] Ingestion failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
