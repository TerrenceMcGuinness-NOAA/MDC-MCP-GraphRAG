#!/usr/bin/env python3
"""
Validate documentation URLs and check sitemaps
Quick test before starting full ingestion
"""

import requests
from urllib.parse import urlparse

# Import SINGLE SOURCE OF TRUTH for documentation sources
from documentation_sources_config import (
    DOCUMENTATION_SOURCES,
    get_all_sources,
    VERSION
)

def check_url(source):
    """Check if URL is accessible and get page count from sitemap"""
    name = source['name']
    url = source['url']
    
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"URL: {url}")
    
    # Check main URL
    try:
        response = requests.get(url, timeout=10)
        status = response.status_code
        
        if status == 200:
            print(f"[OK] Main URL accessible (200 OK)")
            print(f"   Content-Length: {len(response.content):,} bytes")
        else:
            print(f"[WARN] Main URL returned {status}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Main URL failed: {e}")
        return False
    
    # Check sitemap if ReadTheDocs
    if source['type'] == 'readthedocs':
        # Construct sitemap URL
        sitemap_url = url.rstrip('/') + '/sitemap.xml'
        try:
            response = requests.get(sitemap_url, timeout=10)
            if response.status_code == 200:
                # Count URLs in sitemap
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.content, 'xml')
                urls = soup.find_all('loc')
                print(f"[OK] Sitemap accessible ({len(urls)} URLs)")
                return True, len(urls)
            else:
                print(f"[WARN] Sitemap returned {response.status_code}")
                return True, 0
        except Exception as e:
            print(f"[WARN] Sitemap check failed: {e}")
            return True, 0
    else:
        print(f"[INFO] No sitemap ({source['type']} type)")
        return True, source.get('max_pages', 1)
    
    return True, 0


def main():
    print("="*70)
    print(f"Documentation URL Validation - v{VERSION}")
    print("="*70)
    
    # Get all sources from config
    all_sources = get_all_sources()
    
    results = []
    total_pages = 0
    
    for source in all_sources:
        result = check_url(source)
        if isinstance(result, tuple):
            accessible, page_count = result
            results.append((source['name'], accessible, page_count))
            if accessible:
                total_pages += page_count
        else:
            results.append((source['name'], result, 0))
    
    # Summary
    print("\n" + "="*70)
    print("VALIDATION SUMMARY")
    print("="*70)
    
    accessible_count = sum(1 for _, accessible, _ in results if accessible)
    
    print(f"\nAccessible: {accessible_count}/{len(results)}")
    print(f"Total Pages (from sitemaps): {total_pages}")
    print(f"Estimated Chunks (1000 chars, 200 overlap): {total_pages * 10} (rough estimate)")
    
    print("\nPer-Source Results:")
    print("-" * 70)
    print(f"{'Source':<25} {'Status':<12} {'Pages':<10}")
    print("-" * 70)
    
    for name, accessible, page_count in results:
        status = "[OK]" if accessible else "[FAIL]"
        pages = str(page_count) if page_count > 0 else "N/A"
        print(f"{name:<25} {status:<12} {pages:<10}")
    
    print("="*70)
    
    if accessible_count == len(results):
        print("\n[OK] All documentation sources are accessible!")
        print("   Ready to proceed with ingestion.")
    else:
        print(f"\n[WARN] {len(results) - accessible_count} source(s) failed validation.")
        print("   Review errors above before proceeding.")
    
    return accessible_count == len(results)


if __name__ == '__main__':
    import sys
    success = main()
    sys.exit(0 if success else 1)
