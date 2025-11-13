#!/usr/bin/env python3
"""
Documentation Sources Listing Utility

Programmatically lists all documentation sources from the v4.2 ingestion manifest.
Can output in various formats: table, json, markdown
"""

import sys
import json
import argparse
from pathlib import Path

# Import SINGLE SOURCE OF TRUTH for documentation sources
from documentation_sources_config import (
    DOCUMENTATION_SOURCES,
    VERSION,
    get_tier_names,
    get_total_source_count
)


def list_sources_table():
    """Print sources in table format"""
    print(f"\nDocumentation Sources - v{VERSION}")
    print("="*100)
    
    total_sources = 0
    for tier_name, sources in DOCUMENTATION_SOURCES.items():
        print(f"\n{tier_name.upper().replace('_', ' ')}")
        print("-"*100)
        print(f"{'Name':<20} {'Type':<15} {'Priority':<10} {'URL':<55}")
        print("-"*100)
        
        for source in sources:
            name = source['name']
            url = source['url']
            src_type = source['type']
            priority = source['priority']
            
            # Truncate URL if too long
            display_url = url if len(url) <= 55 else url[:52] + "..."
            
            print(f"{name:<20} {src_type:<15} {priority:<10} {display_url:<55}")
            total_sources += 1
        
        print()
    
    print("="*100)
    print(f"Total sources: {total_sources}")
    print()


def list_sources_detailed():
    """Print sources with full details"""
    print(f"\nDocumentation Sources - v{VERSION}")
    print("="*100)
    
    total_sources = 0
    for tier_name, sources in DOCUMENTATION_SOURCES.items():
        print(f"\n{tier_name.upper().replace('_', ' ')}")
        print("="*100)
        
        for i, source in enumerate(sources, 1):
            print(f"\n{i}. {source['name']}")
            print(f"   URL: {source['url']}")
            print(f"   Type: {source['type']}")
            print(f"   Priority: {source['priority']}")
            print(f"   Description: {source['description']}")
            if 'max_pages' in source:
                print(f"   Max Pages: {source['max_pages']}")
            total_sources += 1
    
    print("\n" + "="*100)
    print(f"Total sources: {total_sources}")
    print()


def list_sources_json():
    """Output sources as JSON"""
    output = {
        'version': VERSION,
        'total_sources': sum(len(sources) for sources in DOCUMENTATION_SOURCES.values()),
        'tiers': {}
    }
    
    for tier_name, sources in DOCUMENTATION_SOURCES.items():
        output['tiers'][tier_name] = {
            'count': len(sources),
            'sources': sources
        }
    
    print(json.dumps(output, indent=2))


def list_sources_markdown():
    """Output sources as markdown table"""
    print(f"# Documentation Sources - v{VERSION}\n")
    
    total_sources = 0
    for tier_name, sources in DOCUMENTATION_SOURCES.items():
        print(f"\n## {tier_name.replace('_', ' ').title()}\n")
        print("| Name | Type | Priority | URL | Description |")
        print("|------|------|----------|-----|-------------|")
        
        for source in sources:
            name = source['name']
            url = source['url']
            src_type = source['type']
            priority = source['priority']
            desc = source['description']
            
            print(f"| {name} | {src_type} | {priority} | [{url}]({url}) | {desc} |")
            total_sources += 1
    
    print(f"\n**Total sources:** {total_sources}\n")


def list_by_tier(tier_name):
    """List sources for a specific tier"""
    if tier_name not in DOCUMENTATION_SOURCES:
        print(f"[ERROR] Unknown tier: {tier_name}")
        print(f"Available tiers: {', '.join(DOCUMENTATION_SOURCES.keys())}")
        return
    
    sources = DOCUMENTATION_SOURCES[tier_name]
    print(f"\n{tier_name.upper().replace('_', ' ')} ({len(sources)} sources)")
    print("="*100)
    
    for i, source in enumerate(sources, 1):
        print(f"\n{i}. {source['name']}")
        print(f"   URL: {source['url']}")
        print(f"   Type: {source['type']}")
        print(f"   Description: {source['description']}")
    
    print()


def list_urls_only():
    """List just URLs (useful for wget/curl scripts)"""
    for tier_name, sources in DOCUMENTATION_SOURCES.items():
        for source in sources:
            print(source['url'])


def main():
    parser = argparse.ArgumentParser(
        description='List documentation sources for ingestion',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Table format (default)
  python3 list_documentation_sources.py

  # Detailed view
  python3 list_documentation_sources.py --format detailed

  # JSON output
  python3 list_documentation_sources.py --format json

  # Markdown table
  python3 list_documentation_sources.py --format markdown

  # Specific tier only
  python3 list_documentation_sources.py --tier tier1_critical

  # Just URLs
  python3 list_documentation_sources.py --urls-only
        """
    )
    
    parser.add_argument(
        '--format',
        choices=['table', 'detailed', 'json', 'markdown'],
        default='table',
        help='Output format (default: table)'
    )
    parser.add_argument(
        '--tier',
        choices=list(DOCUMENTATION_SOURCES.keys()),
        help='Show only specific tier'
    )
    parser.add_argument(
        '--urls-only',
        action='store_true',
        help='Output only URLs (one per line)'
    )
    
    args = parser.parse_args()
    
    if args.urls_only:
        list_urls_only()
    elif args.tier:
        list_by_tier(args.tier)
    elif args.format == 'table':
        list_sources_table()
    elif args.format == 'detailed':
        list_sources_detailed()
    elif args.format == 'json':
        list_sources_json()
    elif args.format == 'markdown':
        list_sources_markdown()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
