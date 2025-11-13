#!/usr/bin/env python3
"""
URL Content Relevance Checker
Check if URL content matches the labeling and is relevant for Global Workflow
"""

import json
import os
import asyncio
import aiohttp
from bs4 import BeautifulSoup
import time

async def check_url_relevance(session, url, label, context):
    """Check if URL content is relevant to its label."""
    try:
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                text = await response.text()
                soup = BeautifulSoup(text, 'html.parser')
                
                # Extract title and first paragraph for relevance check
                title = soup.title.string if soup.title else "No title"
                
                # Get first few paragraphs
                paragraphs = soup.find_all('p')[:3]
                content_sample = ' '.join([p.get_text() for p in paragraphs])[:500]
                
                return {
                    "url": url,
                    "label": label,
                    "context": context,
                    "status": "accessible",
                    "title": title.strip() if title else "No title",
                    "content_sample": content_sample.strip(),
                    "word_count": len(content_sample.split()),
                    "relevance_keywords": extract_relevance_keywords(title, content_sample, context)
                }
            else:
                return {
                    "url": url,
                    "label": label,
                    "context": context,
                    "status": f"HTTP {response.status}",
                    "error": f"HTTP {response.status}"
                }
    except Exception as e:
        return {
            "url": url,
            "label": label,
            "context": context,
            "status": "error",
            "error": str(e)
        }

def extract_relevance_keywords(title, content, context):
    """Extract keywords to assess relevance."""
    text = f"{title} {content}".lower()
    
    # Define relevance keywords by category
    relevance_map = {
        "global_workflow": ["global", "workflow", "forecast", "analysis", "gdas", "gfs", "noaa", "emc"],
        "ufs": ["ufs", "weather", "model", "atmospheric", "forecast", "finite", "volume", "cube"],
        "rocoto": ["rocoto", "workflow", "job", "scheduler", "dependency", "xml"],
        "gsi": ["gsi", "analysis", "data", "assimilation", "observation", "background"],
        "hpc": ["hpc", "cluster", "computing", "parallel", "slurm", "pbs", "batch"],
        "python": ["python", "pep", "style", "docstring", "pylint", "coding"],
        "shell": ["bash", "shell", "script", "shellcheck", "style"],
        "cmake": ["cmake", "build", "configuration", "makefile"],
        "fortran": ["fortran", "f90", "programming", "style", "standard"]
    }
    
    found_keywords = []
    for category, keywords in relevance_map.items():
        for keyword in keywords:
            if keyword in text:
                found_keywords.append(f"{category}:{keyword}")
    
    return found_keywords

async def main():
    """Main function to check URL relevance."""
    print("🔍 === URL Content Relevance Check ===\n")
    
    # Load documentation references from parent directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    file_path = os.path.join(parent_dir, 'documentation-references.json')
    
    with open(file_path, 'r') as f:
        refs = json.load(f)
    
    # Extract URLs with their context
    urls_to_check = []
    
    def extract_urls_with_context(data, context_path=""):
        for key, value in data.items():
            new_context = f"{context_path}.{key}" if context_path else key
            if isinstance(value, str) and value.startswith('http'):
                urls_to_check.append({
                    "url": value,
                    "label": key,
                    "context": new_context
                })
            elif isinstance(value, dict):
                extract_urls_with_context(value, new_context)
    
    extract_urls_with_context(refs['documentation_references'])
    
    print(f"Checking {len(urls_to_check)} URLs for content relevance...\n")
    
    # Check URLs for relevance
    async with aiohttp.ClientSession() as session:
        tasks = [check_url_relevance(session, item['url'], item['label'], item['context']) 
                for item in urls_to_check]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results
    relevant_urls = []
    questionable_urls = []
    error_urls = []
    
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"❌ EXCEPTION: {urls_to_check[i]['url']} - {result}")
            error_urls.append(urls_to_check[i])
            continue
        
        if result['status'] != 'accessible':
            print(f"❌ ERROR: {result['label']} - {result['url']} - {result['status']}")
            error_urls.append(result)
            continue
        
        # Assess relevance
        keyword_count = len(result['relevance_keywords'])
        
        if keyword_count >= 2:  # High relevance
            print(f"✅ HIGHLY RELEVANT: {result['label']}")
            print(f"   URL: {result['url']}")
            print(f"   Title: {result['title'][:80]}...")
            print(f"   Keywords: {', '.join(result['relevance_keywords'][:5])}")
            print(f"   Sample: {result['content_sample'][:100]}...")
            print()
            relevant_urls.append(result)
        elif keyword_count >= 1:  # Medium relevance
            print(f"⚠️  MODERATELY RELEVANT: {result['label']}")
            print(f"   URL: {result['url']}")
            print(f"   Title: {result['title'][:80]}...")
            print(f"   Keywords: {', '.join(result['relevance_keywords'])}")
            print(f"   Sample: {result['content_sample'][:100]}...")
            print()
            relevant_urls.append(result)
        else:  # Low relevance
            print(f"❓ QUESTIONABLE RELEVANCE: {result['label']}")
            print(f"   URL: {result['url']}")
            print(f"   Title: {result['title'][:80]}...")
            print(f"   No matching keywords found")
            print(f"   Sample: {result['content_sample'][:100]}...")
            print()
            questionable_urls.append(result)
    
    # Summary
    print("\n📊 === RELEVANCE SUMMARY ===")
    print(f"✅ Highly/Moderately Relevant: {len(relevant_urls)}")
    print(f"❓ Questionable Relevance: {len(questionable_urls)}")
    print(f"❌ Errors/Inaccessible: {len(error_urls)}")
    print(f"📝 Total URLs Checked: {len(urls_to_check)}")
    
    # Save detailed results
    detailed_results = {
        "timestamp": time.time(),
        "total_checked": len(urls_to_check),
        "relevant": relevant_urls,
        "questionable": questionable_urls,
        "errors": error_urls,
        "summary": {
            "relevant_count": len(relevant_urls),
            "questionable_count": len(questionable_urls),
            "error_count": len(error_urls)
        }
    }
    
    with open('url-relevance-check.json', 'w') as f:
        json.dump(detailed_results, f, indent=2)
    
    print(f"\n📁 Detailed results saved to url-relevance-check.json")
    
    # Recommendations
    if questionable_urls:
        print(f"\n💡 RECOMMENDATIONS:")
        print(f"   Consider reviewing questionable URLs for relevance")
        print(f"   You may want to exclude or replace them")
    
    if error_urls:
        print(f"\n⚠️  ATTENTION NEEDED:")
        print(f"   {len(error_urls)} URLs had errors and should be investigated")

if __name__ == "__main__":
    asyncio.run(main())
