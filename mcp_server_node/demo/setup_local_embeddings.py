#!/usr/bin/env python3

"""
Local Vector Embedding Setup for EE2 Documentation
No Hugging Face account required - everything runs locally
"""

import os
import sys
import subprocess
import json
from pathlib import Path

def check_requirements():
    """Check if required packages are available"""
    print("🔍 Checking Requirements...")

    required_packages = [
        'sentence-transformers',
        'torch',
        'numpy',
        'chromadb'
    ]

    missing_packages = []

    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"  ✅ {package} - Available")
        except ImportError:
            print(f"  ❌ {package} - Missing")
            missing_packages.append(package)

    if missing_packages:
        print(f"\n📦 Install missing packages:")
        print(f"pip install {' '.join(missing_packages)}")
        return False

    return True

def setup_local_embedding():
    """Setup local embedding environment"""
    print("\n🚀 Setting up Local Vector Embeddings...")

    # Check if we can import sentence transformers
    try:
        from sentence_transformers import SentenceTransformer
        print("  ✅ SentenceTransformers available")
    except ImportError:
        print("  ❌ SentenceTransformers not available")
        print("  Install with: pip install sentence-transformers")
        return False

    # Download and cache the model (one-time operation)
    print("  📥 Loading all-MiniLM-L6-v2 model (22MB)...")
    try:
        model = SentenceTransformer('all-MiniLM-L6-v2')
        print("  ✅ Model loaded and cached locally")

        # Test encoding
        test_text = "Environmental Equivalence standards for NOAA operations"
        embedding = model.encode(test_text)
        print(f"  ✅ Test embedding: {len(embedding)} dimensions")

        return True
    except Exception as e:
        print(f"  ❌ Error loading model: {e}")
        return False

def create_ee2_embedding_script():
    """Create script to process EE2 documentation"""

    script_content = '''#!/usr/bin/env python3

"""
EE2 Documentation Vector Embedding Processor
Processes Environmental Equivalence documentation for RAG integration
"""

import os
import json
import requests
from pathlib import Path
from sentence_transformers import SentenceTransformer
import numpy as np

class EE2EmbeddingProcessor:
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        """Initialize with local embedding model"""
        print(f"🤗 Loading {model_name} model...")
        self.model = SentenceTransformer(model_name)
        self.embeddings = {}
        self.documents = {}

    def fetch_ee2_documentation(self):
        """Fetch EE2 documentation from our reference"""
        print("📥 Fetching EE2 documentation...")

        # Load our documentation references
        refs_file = Path('documentation-references.json')
        if refs_file.exists():
            with open(refs_file) as f:
                refs = json.load(f)

            ee2_url = refs['documentation_references']['standards_and_policies']['environmental_equivalence']['ee2_standards']
            print(f"  📄 EE2 URL: {ee2_url}")

            # In a real implementation, you would:
            # 1. Fetch the full documentation
            # 2. Parse HTML/markdown content
            # 3. Split into chunks
            # For now, we'll use the content we already fetched
            return self.create_sample_ee2_content()
        else:
            print("  ❌ documentation-references.json not found")
            return []

    def create_sample_ee2_content(self):
        """Create sample EE2 content chunks for testing"""
        return [
            {
                "id": "ee2_intro",
                "title": "Environmental Equivalence Introduction",
                "content": "Environmental Equivalence (EE2) standards ensure consistent behavior and performance of numerical weather prediction models across different computing environments within NCEP and between NCEP and developing organizations.",
                "section": "Introduction",
                "priority": "HIGH"
            },
            {
                "id": "ee2_workflow",
                "title": "EE2 Workflow Standards",
                "content": "All production jobs are scheduled and submitted to the WCOSS resource manager PBS Pro by ecFlow. The workflow follows: job card -> J-job -> ex-script -> ush scripts -> executables.",
                "section": "Workflow",
                "priority": "HIGH"
            },
            {
                "id": "ee2_variables",
                "title": "Standard Environment Variables",
                "content": "Standard environment variables include envir, PACKAGEROOT, OPSROOT, job, jobid, NET, RUN, PDY, cyc, cycle, subcyc, DATAROOT, DATA, and model-specific variables like HOMEmodel, USHmodel, EXECmodel.",
                "section": "Variables",
                "priority": "MEDIUM"
            },
            {
                "id": "ee2_file_naming",
                "title": "File Naming Conventions",
                "content": "File names must follow standard conventions: model.tHHz.var_info.f###.domain.format for atmospheric models. No special characters, uppercase, or dates in filenames.",
                "section": "File Naming",
                "priority": "MEDIUM"
            },
            {
                "id": "ee2_utilities",
                "title": "Production Utilities",
                "content": "Required utilities include prep_step, startmsg, postmsg, err_chk, err_exit, cpreq, cpfs, compath.py, mail.py for error handling and file operations.",
                "section": "Utilities",
                "priority": "HIGH"
            },
            {
                "id": "ee2_code_standards",
                "title": "Code Compilation Standards",
                "content": "Code must be written in C/C++ or Fortran using Intel or Cray compilers. All libraries must be approved production modules. Makefiles require all, debug, install, clean, and test targets.",
                "section": "Code Standards",
                "priority": "HIGH"
            }
        ]

    def generate_embeddings(self, documents):
        """Generate vector embeddings for documents"""
        print("🔮 Generating vector embeddings...")

        for doc in documents:
            # Combine title and content for embedding
            text = f"{doc['title']}. {doc['content']}"

            # Generate embedding
            embedding = self.model.encode(text)

            # Store embedding and metadata
            self.embeddings[doc['id']] = {
                'vector': embedding.tolist(),
                'title': doc['title'],
                'content': doc['content'],
                'section': doc['section'],
                'priority': doc['priority'],
                'dimensions': len(embedding)
            }

            print(f"  ✅ {doc['id']}: {len(embedding)} dimensions")

        return self.embeddings

    def save_embeddings(self, output_file='ee2_embeddings.json'):
        """Save embeddings to file"""
        print(f"💾 Saving embeddings to {output_file}...")

        with open(output_file, 'w') as f:
            json.dump(self.embeddings, f, indent=2)

        print(f"  ✅ Saved {len(self.embeddings)} embeddings")

        # Save summary
        summary = {
            'total_documents': len(self.embeddings),
            'model_used': 'all-MiniLM-L6-v2',
            'dimensions': 384,
            'high_priority_docs': len([e for e in self.embeddings.values() if e['priority'] == 'HIGH']),
            'sections': list(set(e['section'] for e in self.embeddings.values())),
            'created': str(Path(output_file).stat().st_mtime) if Path(output_file).exists() else 'now'
        }

        with open('ee2_embedding_summary.json', 'w') as f:
            json.dump(summary, f, indent=2)

        return summary

    def test_similarity_search(self, query="workflow standards"):
        """Test similarity search functionality"""
        print(f"\\n🔍 Testing similarity search for: '{query}'")

        # Generate query embedding
        query_embedding = self.model.encode(query)

        # Calculate similarities
        similarities = {}
        for doc_id, doc_data in self.embeddings.items():
            doc_embedding = np.array(doc_data['vector'])
            similarity = np.dot(query_embedding, doc_embedding) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(doc_embedding)
            )
            similarities[doc_id] = {
                'similarity': float(similarity),
                'title': doc_data['title'],
                'section': doc_data['section']
            }

        # Sort by similarity
        sorted_results = sorted(similarities.items(), key=lambda x: x[1]['similarity'], reverse=True)

        print("  📊 Top 3 results:")
        for i, (doc_id, data) in enumerate(sorted_results[:3]):
            print(f"    {i+1}. {data['title']} (similarity: {data['similarity']:.3f})")

        return sorted_results

def main():
    """Main execution"""
    print("🚀 === EE2 Vector Embedding Generation ===\\n")

    processor = EE2EmbeddingProcessor()

    # Fetch documentation
    documents = processor.fetch_ee2_documentation()

    # Generate embeddings
    embeddings = processor.generate_embeddings(documents)

    # Save to file
    summary = processor.save_embeddings()

    # Test search
    processor.test_similarity_search("workflow standards")
    processor.test_similarity_search("error handling")

    print(f"\\n✅ === EE2 Embedding Generation Complete ===")
    print(f"📊 Summary: {summary['total_documents']} documents, {summary['dimensions']} dimensions")
    print(f"🎯 High Priority: {summary['high_priority_docs']} documents")
    print(f"📁 Sections: {', '.join(summary['sections'])}")
    print(f"\\n💡 Next: Integrate with RAG system and PR review process")

if __name__ == "__main__":
    main()
'''

    with open('ee2_embedding_generator.py', 'w') as f:
        f.write(script_content)

    print("  ✅ Created ee2_embedding_generator.py")

def main():
    """Main setup process"""
    print("🤗 === Local Vector Embedding Setup for EE2 ===\\n")

    # Check requirements
    if not check_requirements():
        print("\\n❌ Please install missing packages first")
        return False

    # Setup embedding environment
    if not setup_local_embedding():
        print("\\n❌ Failed to setup embedding environment")
        return False

    # Create EE2 processing script
    create_ee2_embedding_script()

    print("\\n✅ === Setup Complete ===")
    print("🚀 Next steps:")
    print("  1. Run: python3 ee2_embedding_generator.py")
    print("  2. Integrate embeddings with RAG system")
    print("  3. Test with PR review process")
    print("\\n💡 No Hugging Face account needed - everything runs locally!")

    return True

if __name__ == "__main__":
    main()
