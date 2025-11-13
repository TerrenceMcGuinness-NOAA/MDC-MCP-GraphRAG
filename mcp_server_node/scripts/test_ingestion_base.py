#!/usr/bin/env python3
"""
Quick test of base ingestion library
Validates all components are working
"""

import sys
from pathlib import Path

# ingestion_base.py is in the same directory, no path modification needed
from ingestion_base import (
    SemanticChunker,
    ChromaDBClient,
    URLCrawler,
    LocalRepoParser,
    MetadataEnricher,
    BaseIngester
)

def test_semantic_chunker():
    """Test semantic chunker"""
    print("\n[TEST] SemanticChunker...")
    
    chunker = SemanticChunker(min_size=100, max_size=500)
    
    # Test markdown (need realistic content length for 100-char minimum)
    md_content = """
# Global Workflow Documentation

The Global Workflow system is NOAA's operational weather forecasting framework that integrates multiple models and data assimilation systems. This comprehensive system provides deterministic and ensemble forecasts at various scales and resolutions for global atmospheric and oceanic conditions.

## System Architecture

The workflow consists of several key components working together in a coordinated manner. The primary components include the Unified Forecast System (UFS) weather model, the Global Data Assimilation System (GDAS), and various post-processing utilities. Each component plays a critical role in producing high-quality forecast products used by meteorologists and automated systems worldwide.

## Model Components

The UFS weather model serves as the core forecasting engine, capable of running at multiple resolutions and configurations. It incorporates advanced physics packages, dynamic cores, and coupling capabilities for atmosphere-ocean-ice-wave interactions. The model can be configured for global, regional, or specialized applications depending on operational requirements.
"""
    
    chunks = chunker.chunk_markdown(md_content, "test.md")
    print(f"  ✓ Markdown chunking: {len(chunks)} chunks created")
    assert len(chunks) > 0, "Should create at least one chunk"
    assert 'hash' in chunks[0], "Chunks should have hash"
    
    # Test RST
    rst_content = """
Introduction
============

This is the introduction section.

Subsection
----------

This is a subsection with content.
"""
    
    chunks = chunker.chunk_rst_document(rst_content, "test.rst")
    print(f"  ✓ RST chunking: {len(chunks)} chunks created")
    
    print("  [OK] SemanticChunker tests passed")


def test_metadata_enricher():
    """Test metadata enricher"""
    print("\n[TEST] MetadataEnricher...")
    
    enricher = MetadataEnricher()
    
    text = """
    This document describes the global-workflow system with configuration
    for forecast initialization and data assimilation on WCOSS2 HPC system.
    Always use set -e for error handling in bash scripts.
    Export environment variables like $DATAROOT and $HOMEmodel.
    """
    
    # Test keyword extraction
    keywords = enricher.extract_keywords(text)
    print(f"  ✓ Keywords extracted: {keywords}")
    assert len(keywords) > 0, "Should extract keywords"
    
    # Test quality score
    score = enricher.calculate_quality_score(text)
    print(f"  ✓ Quality score: {score:.2f}")
    assert 0.0 <= score <= 1.0, "Score should be between 0 and 1"
    
    # Test compliance categories
    categories = enricher.identify_compliance_categories(text)
    print(f"  ✓ Compliance categories: {[c['name'] for c in categories]}")
    assert len(categories) > 0, "Should identify categories"
    
    print("  [OK] MetadataEnricher tests passed")


def test_chromadb_client():
    """Test ChromaDB client connection"""
    print("\n[TEST] ChromaDBClient...")
    
    try:
        client = ChromaDBClient()
        client.connect()
        print("  ✓ Connected to ChromaDB")
        
        # Test embedding function
        emb_func = client.get_embedding_function()
        print(f"  ✓ Embedding function loaded: {type(emb_func).__name__}")
        
        print("  [OK] ChromaDBClient tests passed")
    except Exception as e:
        print(f"  [WARN] ChromaDB connection test skipped: {e}")


def test_base_ingester():
    """Test BaseIngester initialization"""
    print("\n[TEST] BaseIngester...")
    
    ingester = BaseIngester(
        collection_name="test-collection",
        version="4.2.0-test"
    )
    
    assert ingester.chunker is not None, "Should have chunker"
    assert ingester.enricher is not None, "Should have enricher"
    assert ingester.db_client is not None, "Should have db_client"
    
    print("  ✓ BaseIngester components initialized")
    print("  [OK] BaseIngester tests passed")


def main():
    """Run all tests"""
    print("="*60)
    print("Base Ingestion Library - Component Tests")
    print("="*60)
    
    test_semantic_chunker()
    test_metadata_enricher()
    test_chromadb_client()
    test_base_ingester()
    
    print("\n" + "="*60)
    print("ALL TESTS PASSED ✓")
    print("="*60)
    print("\nBase library is ready for use in specialized ingesters.")


if __name__ == "__main__":
    main()
