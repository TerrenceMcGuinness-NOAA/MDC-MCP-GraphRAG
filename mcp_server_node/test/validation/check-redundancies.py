#!/usr/bin/env python3
"""
Check for Redundancies in Documentation References
Identify duplicate URLs, overlapping content, and optimization opportunities
"""

import json
import os
from collections import defaultdict
from urllib.parse import urlparse
import re

def load_documentation_references():
    """Load and parse the documentation references JSON file."""
    # Look for the file in the parent directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    file_path = os.path.join(parent_dir, 'documentation-references.json')
    
    with open(file_path, 'r') as f:
        return json.load(f)

def extract_all_urls_with_context(data, path=""):
    """Extract all URLs with their context path."""
    urls_with_context = []
    
    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            if isinstance(value, str) and value.startswith('http'):
                urls_with_context.append({
                    'url': value,
                    'path': new_path,
                    'key': key
                })
            elif isinstance(value, dict):
                urls_with_context.extend(extract_all_urls_with_context(value, new_path))
    
    return urls_with_context

def normalize_url(url):
    """Normalize URL for comparison."""
    # Remove trailing slashes, fragments, and common variations
    url = url.rstrip('/')
    url = url.replace('http://', 'https://')
    url = re.sub(r'#.*$', '', url)  # Remove fragments
    url = re.sub(r'\?.*$', '', url)  # Remove query params
    return url

def check_for_duplicates(urls_with_context):
    """Check for duplicate URLs."""
    duplicates = defaultdict(list)
    normalized_to_original = {}
    
    for item in urls_with_context:
        normalized = normalize_url(item['url'])
        
        if normalized in normalized_to_original:
            # Found a duplicate
            if normalized not in duplicates:
                # Add the first occurrence
                duplicates[normalized].append(normalized_to_original[normalized])
            duplicates[normalized].append(item)
        else:
            normalized_to_original[normalized] = item
    
    return dict(duplicates)

def check_for_similar_repositories(urls_with_context):
    """Check for similar GitHub repositories that might be redundant."""
    github_repos = defaultdict(list)
    
    for item in urls_with_context:
        url = item['url']
        if 'github.com' in url:
            # Extract repo name
            match = re.search(r'github\.com/([^/]+)/([^/]+)', url)
            if match:
                org, repo = match.groups()
                repo = repo.replace('.git', '')
                github_repos[f"{org}/{repo}"].append(item)
    
    # Find potential redundancies
    similar_repos = {}
    repo_names = list(github_repos.keys())
    
    for i, repo1 in enumerate(repo_names):
        for repo2 in repo_names[i+1:]:
            # Check for similar names
            repo1_name = repo1.split('/')[-1].lower()
            repo2_name = repo2.split('/')[-1].lower()
            
            if (repo1_name in repo2_name or repo2_name in repo1_name or
                repo1_name.replace('-', '') == repo2_name.replace('-', '') or
                repo1_name.replace('_', '') == repo2_name.replace('_', '')):
                similar_repos[f"{repo1} vs {repo2}"] = {
                    'repo1': github_repos[repo1],
                    'repo2': github_repos[repo2]
                }
    
    return similar_repos

def check_for_overlapping_domains(urls_with_context):
    """Check for overlapping documentation domains."""
    domains = defaultdict(list)
    
    for item in urls_with_context:
        parsed = urlparse(item['url'])
        domain = parsed.netloc.lower()
        
        # Group by domain
        domains[domain].append(item)
    
    # Find domains with multiple URLs
    overlapping = {domain: urls for domain, urls in domains.items() if len(urls) > 1}
    
    return overlapping

def analyze_redundancies():
    """Main analysis function."""
    print("🔍 Analyzing Documentation References for Redundancies")
    print("=" * 60)
    
    # Load data
    refs = load_documentation_references()
    urls_with_context = extract_all_urls_with_context(refs['documentation_references'])
    
    print(f"Total URLs found: {len(urls_with_context)}")
    print()
    
    # Check for exact duplicates
    print("1️⃣ EXACT DUPLICATE URLs")
    print("-" * 30)
    duplicates = check_for_duplicates(urls_with_context)
    
    if duplicates:
        for normalized_url, items in duplicates.items():
            print(f"🔴 DUPLICATE: {normalized_url}")
            for item in items:
                print(f"   📍 {item['path']} → {item['url']}")
            print()
    else:
        print("✅ No exact duplicate URLs found")
    print()
    
    # Check for similar repositories
    print("2️⃣ SIMILAR GITHUB REPOSITORIES")
    print("-" * 35)
    similar_repos = check_for_similar_repositories(urls_with_context)
    
    if similar_repos:
        for comparison, repos in similar_repos.items():
            print(f"🟡 SIMILAR: {comparison}")
            for repo_group in [repos['repo1'], repos['repo2']]:
                for item in repo_group:
                    print(f"   📍 {item['path']} → {item['url']}")
            print()
    else:
        print("✅ No similar GitHub repositories found")
    print()
    
    # Check for overlapping domains
    print("3️⃣ OVERLAPPING DOMAINS")
    print("-" * 25)
    overlapping = check_for_overlapping_domains(urls_with_context)
    
    if overlapping:
        for domain, items in overlapping.items():
            if len(items) > 2:  # Only show domains with 3+ URLs
                print(f"🟠 DOMAIN: {domain} ({len(items)} URLs)")
                for item in items:
                    print(f"   📍 {item['path']} → {item['url']}")
                print()
    else:
        print("✅ No significant domain overlaps found")
    print()
    
    # Analysis summary
    print("4️⃣ REDUNDANCY ANALYSIS SUMMARY")
    print("-" * 35)
    
    total_duplicates = sum(len(items) - 1 for items in duplicates.values())
    potential_savings = total_duplicates
    
    print(f"📊 Total URLs: {len(urls_with_context)}")
    print(f"🔴 Exact duplicates: {total_duplicates}")
    print(f"🟡 Similar repos: {len(similar_repos)}")
    print(f"🟠 Domain overlaps: {len([d for d, items in overlapping.items() if len(items) > 2])}")
    print(f"💾 Potential URL reduction: {potential_savings}")
    print(f"📈 Efficiency after cleanup: {len(urls_with_context) - potential_savings} URLs")
    
    # Recommendations
    print()
    print("5️⃣ OPTIMIZATION RECOMMENDATIONS")
    print("-" * 40)
    
    if duplicates:
        print("🔧 IMMEDIATE ACTIONS:")
        for normalized_url, items in duplicates.items():
            print(f"   • Remove duplicate entries for: {normalized_url}")
            keep_item = min(items, key=lambda x: len(x['path']))  # Keep shortest path
            remove_items = [item for item in items if item != keep_item]
            print(f"     ✅ Keep: {keep_item['path']}")
            for item in remove_items:
                print(f"     ❌ Remove: {item['path']}")
        print()
    
    if similar_repos:
        print("🔍 REVIEW NEEDED:")
        for comparison, repos in similar_repos.items():
            print(f"   • Review if both are needed: {comparison}")
        print()
    
    if not duplicates and not similar_repos:
        print("✅ Documentation references are well-organized!")
        print("   • No exact duplicates found")
        print("   • No obvious redundancies detected")
        print("   • Current structure is efficient")
    
    # Save detailed analysis
    analysis_results = {
        'total_urls': len(urls_with_context),
        'duplicates': duplicates,
        'similar_repos': similar_repos,
        'overlapping_domains': {k: v for k, v in overlapping.items() if len(v) > 2},
        'recommendations': {
            'exact_duplicates_to_remove': total_duplicates,
            'potential_url_count_after_cleanup': len(urls_with_context) - potential_savings
        }
    }
    
    with open('redundancy-analysis.json', 'w') as f:
        json.dump(analysis_results, f, indent=2, default=str)
    
    print(f"📁 Detailed analysis saved to: redundancy-analysis.json")

if __name__ == "__main__":
    analyze_redundancies()
