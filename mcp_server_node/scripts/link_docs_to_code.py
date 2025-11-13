#!/usr/bin/env python3
"""
Link Documentation to Code in Neo4j
Creates DOC_DESCRIBES relationships between documentation chunks and code entities

This implements Phase 3 of WEEK_3_PLAN.md
"""

import re
from neo4j import GraphDatabase
import chromadb
from typing import List, Dict, Set

class DocCodeLinker:
    def __init__(self, neo4j_uri="bolt://localhost:7687", neo4j_user="neo4j", neo4j_password="gfsworkflow2025"):
        self.driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        self.chroma_client = chromadb.HttpClient(host='localhost', port=8080)
        self.collection = self.chroma_client.get_collection('global-workflow-docs-v3-0-8')
        
    def close(self):
        self.driver.close()
    
    def extract_code_mentions(self, text: str) -> Dict[str, List[str]]:
        """Extract mentions of files, functions, and jobs from documentation text"""
        mentions = {
            'files': [],
            'functions': [],
            'jobs': [],
            'scripts': []
        }
        
        # File patterns: *.py, *.sh, *.yaml, etc.
        file_pattern = r'\b([\w_-]+\.(?:py|sh|bash|yaml|yml|config))\b'
        mentions['files'] = list(set(re.findall(file_pattern, text, re.IGNORECASE)))
        
        # Function patterns: functionName(), function_name()
        func_pattern = r'\b([a-z_][a-z0-9_]*)\s*\(\)'
        mentions['functions'] = list(set(re.findall(func_pattern, text, re.IGNORECASE)))
        
        # Job/script patterns: exglobal_*, JGLOBAL_*, gdas_*
        job_pattern = r'\b((?:ex|J)?g(?:lobal|das)_[\w_]+)\b'
        mentions['jobs'] = list(set(re.findall(job_pattern, text, re.IGNORECASE)))
        
        # Script directory mentions: scripts/, ush/, jobs/
        script_pattern = r'(?:scripts|ush|jobs)/([a-z_][a-z0-9_]*)'
        mentions['scripts'] = list(set(re.findall(script_pattern, text, re.IGNORECASE)))
        
        return mentions
    
    def find_matching_code_entities(self, session, mentions: Dict[str, List[str]]) -> List[Dict]:
        """Find code entities in Neo4j that match the mentions"""
        matches = []
        
        # Match files
        if mentions['files']:
            query = """
            MATCH (f:File)
            WHERE ANY(filename IN $filenames WHERE f.path CONTAINS filename)
            RETURN 'File' as type, f.path as name, id(f) as nodeId
            """
            result = session.run(query, filenames=mentions['files'])
            matches.extend([dict(r) for r in result])
        
        # Match functions
        if mentions['functions']:
            query = """
            MATCH (func:Function)
            WHERE func.name IN $functionNames
            RETURN 'Function' as type, func.name as name, id(func) as nodeId
            """
            result = session.run(query, functionNames=mentions['functions'])
            matches.extend([dict(r) for r in result])
        
        # Match job scripts (in File nodes)
        if mentions['jobs'] or mentions['scripts']:
            all_scripts = mentions['jobs'] + mentions['scripts']
            query = """
            MATCH (f:File)
            WHERE ANY(script IN $scripts WHERE f.path CONTAINS script)
            RETURN 'File' as type, f.path as name, id(f) as nodeId
            """
            result = session.run(query, scripts=all_scripts)
            matches.extend([dict(r) for r in result])
        
        return matches
    
    def create_doc_node_if_not_exists(self, session, doc_id: str, doc_metadata: Dict) -> int:
        """Create or update Documentation node in Neo4j"""
        query = """
        MERGE (d:Documentation {chromaId: $docId})
        ON CREATE SET
            d.source = $source,
            d.url = $url,
            d.title = $title,
            d.ingestionDate = datetime()
        ON MATCH SET
            d.lastUpdated = datetime()
        RETURN id(d) as nodeId
        """
        result = session.run(query, 
            docId=doc_id,
            source=doc_metadata.get('source', 'unknown'),
            url=doc_metadata.get('source_url', ''),
            title=doc_metadata.get('title', '')
        )
        return result.single()['nodeId']
    
    def create_doc_describes_relationship(self, session, doc_node_id: int, code_node_id: int, confidence: float):
        """Create DOC_DESCRIBES relationship"""
        query = """
        MATCH (d:Documentation), (c)
        WHERE id(d) = $docId AND id(c) = $codeId
        MERGE (d)-[r:DOC_DESCRIBES]->(c)
        ON CREATE SET r.confidence = $confidence, r.createdAt = datetime()
        """
        session.run(query, docId=doc_node_id, codeId=code_node_id, confidence=confidence)
    
    def process_all_documents(self):
        """Main processing loop: link all documentation to code"""
        print("🔗 Starting Documentation-to-Code Linking...")
        print("=" * 80)
        
        # Get all documents from ChromaDB
        results = self.collection.get(include=['documents', 'metadatas'])
        total_docs = len(results['ids'])
        
        print(f"📚 Processing {total_docs} documentation chunks...")
        
        stats = {
            'docs_processed': 0,
            'mentions_found': 0,
            'links_created': 0,
            'files_linked': 0,
            'functions_linked': 0
        }
        
        with self.driver.session() as session:
            for i, (doc_id, text, metadata) in enumerate(zip(
                results['ids'], 
                results['documents'], 
                results['metadatas']
            )):
                if (i + 1) % 50 == 0:
                    print(f"  Progress: {i+1}/{total_docs} docs processed...")
                
                # Extract code mentions from documentation text
                mentions = self.extract_code_mentions(text)
                total_mentions = sum(len(v) for v in mentions.values())
                
                if total_mentions == 0:
                    continue
                
                stats['mentions_found'] += total_mentions
                
                # Find matching code entities in Neo4j
                matches = self.find_matching_code_entities(session, mentions)
                
                if not matches:
                    continue
                
                # Create/update Documentation node
                doc_node_id = self.create_doc_node_if_not_exists(session, doc_id, metadata)
                
                # Create DOC_DESCRIBES relationships
                for match in matches:
                    confidence = 0.8  # High confidence for direct mentions
                    self.create_doc_describes_relationship(
                        session, doc_node_id, match['nodeId'], confidence
                    )
                    stats['links_created'] += 1
                    
                    if match['type'] == 'File':
                        stats['files_linked'] += 1
                    elif match['type'] == 'Function':
                        stats['functions_linked'] += 1
                
                stats['docs_processed'] += 1
        
        # Print results
        print("\n" + "=" * 80)
        print("✅ Documentation-to-Code Linking Complete!")
        print("=" * 80)
        print(f"📊 Statistics:")
        print(f"  • Documents processed: {stats['docs_processed']}")
        print(f"  • Code mentions found: {stats['mentions_found']}")
        print(f"  • Links created: {stats['links_created']}")
        print(f"  • Files linked: {stats['files_linked']}")
        print(f"  • Functions linked: {stats['functions_linked']}")
        print()
        
        # Validate results
        self.validate_links()
    
    def validate_links(self):
        """Validate the created relationships"""
        print("🔍 Validating DOC_DESCRIBES relationships...")
        
        with self.driver.session() as session:
            # Count total DOC_DESCRIBES relationships
            result = session.run("""
                MATCH (d:Documentation)-[r:DOC_DESCRIBES]->()
                RETURN COUNT(r) as totalLinks,
                       COUNT(DISTINCT d) as docsWithLinks
            """)
            record = result.single()
            
            print(f"  • Total DOC_DESCRIBES links: {record['totalLinks']}")
            print(f"  • Documentation nodes with links: {record['docsWithLinks']}")
            
            # Show sample links
            result = session.run("""
                MATCH (d:Documentation)-[r:DOC_DESCRIBES]->(target)
                RETURN d.title as docTitle, 
                       labels(target)[0] as targetType,
                       CASE 
                           WHEN 'File' IN labels(target) THEN target.path
                           WHEN 'Function' IN labels(target) THEN target.name
                           ELSE 'Unknown'
                       END as targetName
                LIMIT 10
            """)
            
            print("\n  Sample links:")
            for i, record in enumerate(result, 1):
                doc = record['docTitle'] or 'Untitled'
                target_type = record['targetType']
                target_name = record['targetName']
                print(f"    {i}. '{doc}' → {target_type}: {target_name}")
        
        print()


def main():
    print("\n" + "=" * 80)
    print("  Documentation-to-Code Linker (Phase 3)")
    print("  Part of MCP RAG System v3.0")
    print("=" * 80 + "\n")
    
    linker = DocCodeLinker()
    try:
        linker.process_all_documents()
    finally:
        linker.close()
    
    print("✨ Phase 3 complete! Documentation is now linked to code.")
    print("   Use Neo4j Browser to explore DOC_DESCRIBES relationships.\n")


if __name__ == '__main__':
    main()
