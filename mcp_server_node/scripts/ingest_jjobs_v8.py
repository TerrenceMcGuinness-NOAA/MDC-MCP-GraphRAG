#!/usr/bin/env python3
"""
J-Job ChromaDB Ingestion v8.0.0
Phase 27C: Ingest Global Workflow J-Jobs with structured metadata

Creates ChromaDB collection 'jjobs-v8-1-0' with:
- Full J-Job content as searchable documents
- Structured metadata (inputs, outputs, calls, configs, env vars)
- Semantic chunking by script sections

Author: NOAA EMC Global Workflow MCP Team
Version: 8.0.0
Date: February 4, 2026
Phase: 27C
"""

import os
import re
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Set, Tuple
from collections import defaultdict

try:
    import chromadb
    from chromadb.config import Settings
    from chromadb.utils import embedding_functions
except ImportError as e:
    print(f"[ERROR] Missing chromadb: {e}")
    print("Install: pip install chromadb")
    sys.exit(1)

try:
    from sentence_transformers import SentenceTransformer
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False
    print("[WARN] sentence-transformers not available, using ChromaDB default embeddings")

# Embedding configuration
EMBEDDING_MODEL = "all-mpnet-base-v2"  # 768 dimensions, best quality
EMBEDDING_DIMENSIONS = 768


# ============================================================================
# V8 CONFIGURATION
# ============================================================================

VERSION = "8.0.0"
COLLECTION_NAME = os.getenv("JJOB_COLLECTION", "jjobs-v8-1-0")
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8080"))

# Source paths
WORKFLOW_ROOT = os.getenv("WORKFLOW_ROOT", 
    "/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow")

# J-Job directories (primary and fallback)
JJOB_DIRECTORIES = [
    "dev/jobs",      # Current structure
    "jobs",          # Legacy fallback
]

# J-Job file pattern: starts with J, followed by uppercase letters
JJOB_PATTERN = re.compile(r'^J[A-Z][A-Z0-9_]+$')


# ============================================================================
# J-JOB METADATA PATTERNS
# ============================================================================

class JJobPatterns:
    """Regex patterns for extracting J-Job metadata"""
    
    # jjob_header.sh source line: -e "job_name" -c "config1 config2 ..."
    JJOB_HEADER = re.compile(
        r'source\s+["\']?\$\{?HOMEgfs\}?/ush/jjob_header\.sh["\']?\s+'
        r'-e\s+["\']([^"\']+)["\']\s+'
        r'-c\s+["\']([^"\']+)["\']',
        re.MULTILINE
    )
    
    # Export statements: export VAR=value or export VAR=${expr}
    EXPORT_VAR = re.compile(
        r'^export\s+([A-Z_][A-Z0-9_]*)=(.+?)$',
        re.MULTILINE
    )
    
    # Variable assignments: VAR=value (without export)
    VAR_ASSIGN = re.compile(
        r'^([A-Z_][A-Z0-9_]*)=([^#\n]+)',
        re.MULTILINE
    )
    
    # Script execution: ${SCRIPTS...}/script.sh or "/path/to/script.sh"
    SCRIPT_EXEC = re.compile(
        r'["\']?\$\{?([A-Z_]+)\}?/([^"\'\s]+\.sh)["\']?',
        re.MULTILINE
    )
    
    # Direct script path execution
    SCRIPT_PATH = re.compile(
        r'^\s*["\']?(/[^\s"\']+\.sh)["\']?\s*$',
        re.MULTILINE
    )
    
    # Source statements (other than jjob_header)
    SOURCE_STMT = re.compile(
        r'^\s*(?:source|\.)\s+["\']?([^"\'#\n]+)["\']?',
        re.MULTILINE
    )
    
    # COM/COMIN/COMOUT directory templates
    COM_TEMPLATE = re.compile(
        r'declare_from_tmpl\s+.*?([A-Z_]+):([A-Z_]+_TMPL)',
        re.MULTILINE
    )
    
    # Input file references (common patterns)
    INPUT_FILE = re.compile(
        r'\$\{?(COMIN[A-Z_]*|DATA|DMPDIR)\}?/([^\s\}]+)',
        re.MULTILINE
    )
    
    # Output directory creation: mkdir ... ${VAR}
    OUTPUT_DIR = re.compile(
        r'mkdir\s+.*?\$\{?([A-Z_]+)\}?',
        re.MULTILINE
    )
    
    # File existence check: [[ -f "${FILE}" ]]
    FILE_CHECK = re.compile(
        r'\[\[\s+-[fde]\s+["\']?\$\{?([A-Z_]+)\}?["\']?\s*\]\]',
        re.MULTILINE
    )
    
    # Module load statements
    MODULE_LOAD = re.compile(
        r'module\s+load\s+(\S+)',
        re.MULTILINE
    )
    
    # Section comments (### or ## or # -----)
    SECTION_HEADER = re.compile(
        r'^#+\s*[-=]{3,}\s*$|^#+\s+[A-Z].*$',
        re.MULTILINE
    )


# ============================================================================
# J-JOB METADATA EXTRACTOR
# ============================================================================

class JJobMetadataExtractor:
    """Extract structured metadata from J-Job scripts"""
    
    def __init__(self, workflow_root: str = WORKFLOW_ROOT):
        self.patterns = JJobPatterns()
        self.workflow_root = workflow_root
        self.stats = defaultdict(int)
    
    def extract(self, file_path: str, content: str) -> Dict:
        """Extract all metadata from a J-Job file"""
        
        name = Path(file_path).name
        
        # Parse jjob_header for job name and configs
        job_name, configs = self._parse_jjob_header(content)
        
        # Categorize the job
        category, subcategory, system = self._categorize_job(name)
        
        metadata = {
            "document_type": "j-job",
            "name": name,
            "job_name": job_name or name.replace("J", "").lower(),
            "category": category,
            "subcategory": subcategory,
            "system": system,
            
            # Extracted components
            "config_files": configs,
            "inputs": self._extract_inputs(content),
            "outputs": self._extract_outputs(content),
            "calls": self._extract_script_calls(content),
            "sources": self._extract_sources(content),
            "environment_variables": self._extract_env_vars(content),
            "modules": self._extract_modules(content),
            "com_templates": self._extract_com_templates(content),
            
            # File metadata
            "source_file": str(Path(file_path).relative_to(self.workflow_root)) if self.workflow_root in file_path else file_path,
            "source_repo": "global-workflow",
            "line_count": len(content.splitlines()),
            "last_indexed": datetime.now().isoformat() + "Z",
            "version": VERSION,
        }
        
        self.stats['jobs_processed'] += 1
        return metadata
    
    def _parse_jjob_header(self, content: str) -> Tuple[Optional[str], List[str]]:
        """Parse jjob_header.sh source line"""
        match = self.patterns.JJOB_HEADER.search(content)
        if match:
            job_name = match.group(1)
            configs = [c.strip() for c in match.group(2).split()]
            return job_name, configs
        return None, []
    
    def _categorize_job(self, name: str) -> Tuple[str, str, str]:
        """Categorize job by name pattern"""
        
        # System detection (JGDAS, JGFS, JGLOBAL, JGEFS)
        if name.startswith("JGDAS"):
            system = "gdas"
        elif name.startswith("JGFS"):
            system = "gfs"
        elif name.startswith("JGLOBAL"):
            system = "global"
        elif name.startswith("JGEFS"):
            system = "gefs"
        else:
            system = "unknown"
        
        # Category detection based on name components
        name_lower = name.lower()
        
        category_mapping = {
            "analysis": ["analysis", "chgres"],
            "forecast": ["forecast", "fcst"],
            "post": ["post", "products", "grib"],
            "verification": ["verif", "verfozn", "verfrad", "fit2obs", "tracker"],
            "archive": ["archive", "cleanup"],
            "wave": ["wave"],
            "ocean": ["ocean", "ice"],
            "atmosphere": ["atmos"],
            "aerosol": ["aero"],
            "enkf": ["enkf"],
            "gempak": ["gempak"],
            "awips": ["awips"],
            "cyclone": ["cyclone", "genesis"],
        }
        
        category = "general"
        subcategory = ""
        
        for cat, patterns in category_mapping.items():
            for pattern in patterns:
                if pattern in name_lower:
                    if category == "general":
                        category = cat
                    else:
                        subcategory = cat
                    break
        
        return category, subcategory, system
    
    def _extract_inputs(self, content: str) -> List[Dict]:
        """Extract input file references"""
        inputs = []
        seen = set()
        
        # From file existence checks
        for match in self.patterns.FILE_CHECK.finditer(content):
            var = match.group(1)
            if var not in seen:
                seen.add(var)
                inputs.append({
                    "variable": var,
                    "type": "file_check"
                })
        
        # From input file patterns
        for match in self.patterns.INPUT_FILE.finditer(content):
            var = match.group(1)
            path_part = match.group(2)
            key = f"{var}/{path_part}"
            if key not in seen:
                seen.add(key)
                inputs.append({
                    "variable": var,
                    "path": path_part,
                    "type": "input_file"
                })
        
        self.stats['inputs_found'] += len(inputs)
        return inputs
    
    def _extract_outputs(self, content: str) -> List[Dict]:
        """Extract output directory references"""
        outputs = []
        seen = set()
        
        for match in self.patterns.OUTPUT_DIR.finditer(content):
            var = match.group(1)
            if var not in seen and "COMIN" not in var:
                seen.add(var)
                outputs.append({
                    "variable": var,
                    "type": "directory"
                })
        
        self.stats['outputs_found'] += len(outputs)
        return outputs
    
    def _extract_script_calls(self, content: str) -> List[Dict]:
        """Extract external script calls"""
        calls = []
        seen = set()
        
        for match in self.patterns.SCRIPT_EXEC.finditer(content):
            var = match.group(1)
            script = match.group(2)
            key = f"{var}/{script}"
            if key not in seen:
                seen.add(key)
                
                # Determine package from variable name
                package = "unknown"
                if "fit2obs" in var.lower():
                    package = "Fit2Obs"
                elif "gsi" in var.lower():
                    package = "GSI"
                elif "ufs" in var.lower():
                    package = "UFS"
                elif "SCRIPTS" in var:
                    package = "global-workflow"
                
                calls.append({
                    "script": script,
                    "variable": var,
                    "package": package,
                    "type": "external"
                })
        
        self.stats['calls_found'] += len(calls)
        return calls
    
    def _extract_sources(self, content: str) -> List[Dict]:
        """Extract sourced scripts (other than jjob_header)"""
        sources = []
        seen = set()
        
        for match in self.patterns.SOURCE_STMT.finditer(content):
            path = match.group(1).strip()
            if "jjob_header" not in path and path not in seen:
                seen.add(path)
                sources.append({
                    "path": path,
                    "type": "source"
                })
        
        self.stats['sources_found'] += len(sources)
        return sources
    
    def _extract_env_vars(self, content: str) -> List[Dict]:
        """Extract exported environment variables"""
        env_vars = []
        seen = set()
        
        for match in self.patterns.EXPORT_VAR.finditer(content):
            var = match.group(1)
            value = match.group(2).strip()
            if var not in seen:
                seen.add(var)
                env_vars.append({
                    "name": var,
                    "value_pattern": value[:100] if len(value) > 100 else value
                })
        
        self.stats['env_vars_found'] += len(env_vars)
        return env_vars
    
    def _extract_modules(self, content: str) -> List[str]:
        """Extract module load statements"""
        modules = []
        for match in self.patterns.MODULE_LOAD.finditer(content):
            modules.append(match.group(1))
        return modules
    
    def _extract_com_templates(self, content: str) -> List[Dict]:
        """Extract COM directory templates"""
        templates = []
        seen = set()
        
        for match in self.patterns.COM_TEMPLATE.finditer(content):
            var = match.group(1)
            template = match.group(2)
            if var not in seen:
                seen.add(var)
                templates.append({
                    "variable": var,
                    "template": template
                })
        
        return templates


# ============================================================================
# CHROMADB INGESTION
# ============================================================================

class JJobIngester:
    """Ingest J-Jobs into ChromaDB with MPNet embeddings"""
    
    def __init__(self, host: str = CHROMADB_HOST, port: int = CHROMADB_PORT, 
                 workflow_root: str = WORKFLOW_ROOT):
        self.client = chromadb.HttpClient(host=host, port=port)
        self.workflow_root = workflow_root
        self.extractor = JJobMetadataExtractor(self.workflow_root)
        self.stats = defaultdict(int)
        
        # Initialize embedding model
        if HAS_SENTENCE_TRANSFORMERS:
            print(f"[OK] Loading embedding model: {EMBEDDING_MODEL}")
            self.model = SentenceTransformer(EMBEDDING_MODEL)
            self.embedding_fn = None  # We'll compute manually
        else:
            self.model = None
            # Use ChromaDB's SentenceTransformerEmbeddingFunction
            self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=EMBEDDING_MODEL
            )
    
    def create_collection(self, delete_existing: bool = False) -> any:
        """Create or get ChromaDB collection with MPNet embeddings"""
        
        if delete_existing:
            try:
                self.client.delete_collection(COLLECTION_NAME)
                print(f"[OK] Deleted existing collection: {COLLECTION_NAME}")
            except Exception:
                pass
        
        # Use embedding function for collection
        if self.embedding_fn:
            collection = self.client.get_or_create_collection(
                name=COLLECTION_NAME,
                embedding_function=self.embedding_fn,
                metadata={
                    "description": "Global Workflow J-Job scripts with MPNet embeddings",
                    "version": VERSION,
                    "embedding_model": EMBEDDING_MODEL,
                    "embedding_dimensions": EMBEDDING_DIMENSIONS,
                    "source": "global-workflow/dev/jobs",
                    "indexed_date": datetime.now().isoformat(),
                    "hnsw:space": "cosine"
                }
            )
        else:
            # If using SentenceTransformer directly, we'll add embeddings manually
            collection = self.client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={
                    "description": "Global Workflow J-Job scripts with MPNet embeddings",
                    "version": VERSION,
                    "embedding_model": EMBEDDING_MODEL,
                    "embedding_dimensions": EMBEDDING_DIMENSIONS,
                    "source": "global-workflow/dev/jobs",
                    "indexed_date": datetime.now().isoformat(),
                    "hnsw:space": "cosine"
                }
            )
        
        print(f"[OK] Collection ready: {COLLECTION_NAME} (embeddings: {EMBEDDING_MODEL})")
        return collection
    
    def discover_jjobs(self) -> List[Path]:
        """Discover all J-Job files"""
        jjobs = []
        
        for jobs_dir in JJOB_DIRECTORIES:
            full_path = Path(self.workflow_root) / jobs_dir
            if not full_path.exists():
                continue
            
            for file_path in full_path.iterdir():
                if file_path.is_file() and JJOB_PATTERN.match(file_path.name):
                    jjobs.append(file_path)
        
        print(f"[OK] Discovered {len(jjobs)} J-Jobs")
        return sorted(jjobs)
    
    def generate_doc_id(self, name: str, chunk_idx: int = 0) -> str:
        """Generate unique document ID"""
        content = f"{name}|chunk{chunk_idx}|{VERSION}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def chunk_content(self, content: str, name: str) -> List[Dict]:
        """Split J-Job content into semantic chunks"""
        chunks = []
        lines = content.splitlines()
        
        # First chunk: full document for complete matches
        chunks.append({
            "id": self.generate_doc_id(name, 0),
            "content": content,
            "chunk_type": "full",
            "chunk_index": 0
        })
        
        # Find section boundaries
        sections = []
        current_section = {"start": 0, "header": "Header", "lines": []}
        
        for i, line in enumerate(lines):
            # Check for section markers (### or ## with meaningful content)
            if re.match(r'^#+\s*[-=]{3,}', line) or re.match(r'^#+\s+[A-Z]', line):
                if current_section["lines"]:
                    sections.append(current_section)
                current_section = {
                    "start": i,
                    "header": line.strip('#- \n')[:50] or f"Section_{i}",
                    "lines": [line]
                }
            else:
                current_section["lines"].append(line)
        
        # Add last section
        if current_section["lines"]:
            sections.append(current_section)
        
        # Create section chunks
        for idx, section in enumerate(sections, 1):
            section_content = "\n".join(section["lines"])
            if len(section_content.strip()) > 50:  # Skip tiny sections
                chunks.append({
                    "id": self.generate_doc_id(name, idx),
                    "content": section_content,
                    "chunk_type": "section",
                    "chunk_index": idx,
                    "section_header": section["header"]
                })
        
        return chunks
    
    def ingest_jjob(self, collection, file_path: Path) -> int:
        """Ingest a single J-Job file"""
        try:
            content = file_path.read_text()
        except Exception as e:
            print(f"[WARN] Cannot read {file_path}: {e}")
            return 0
        
        # Extract metadata
        metadata = self.extractor.extract(str(file_path), content)
        
        # Create chunks
        chunks = self.chunk_content(content, file_path.name)
        
        # Prepare for batch add
        ids = []
        documents = []
        metadatas = []
        
        for chunk in chunks:
            # Combine base metadata with chunk-specific fields
            chunk_metadata = {
                **metadata,
                "chunk_type": chunk["chunk_type"],
                "chunk_index": chunk["chunk_index"],
            }
            
            # Add section header for section chunks
            if "section_header" in chunk:
                chunk_metadata["section_header"] = chunk["section_header"]
            
            # Flatten ALL list fields to JSON strings for ChromaDB
            # ChromaDB only accepts str, int, float, bool, or None
            keys_to_process = list(chunk_metadata.keys())
            for key in keys_to_process:
                value = chunk_metadata[key]
                if isinstance(value, list):
                    # Convert empty lists to None, non-empty to JSON
                    chunk_metadata[key] = json.dumps(value) if value else None
                elif isinstance(value, dict):
                    # Convert dicts to JSON strings
                    chunk_metadata[key] = json.dumps(value) if value else None
            
            # Remove None values to avoid ChromaDB issues
            chunk_metadata = {k: v for k, v in chunk_metadata.items() if v is not None}
            
            ids.append(chunk["id"])
            documents.append(chunk["content"])
            metadatas.append(chunk_metadata)
        
        # Compute embeddings if using SentenceTransformer directly
        embeddings = None
        if self.model is not None:
            embeddings = self.model.encode(documents).tolist()
        
        # Add to collection
        try:
            if embeddings:
                collection.add(
                    ids=ids,
                    documents=documents,
                    embeddings=embeddings,
                    metadatas=metadatas
                )
            else:
                # Let ChromaDB compute embeddings via embedding_function
                collection.add(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas
                )
            self.stats['documents_added'] += len(ids)
            self.stats['jjobs_ingested'] += 1
            return len(ids)
        except Exception as e:
            print(f"[ERROR] Failed to add {file_path.name}: {e}")
            self.stats['errors'] += 1
            return 0
    
    def run(self, delete_existing: bool = False) -> Dict:
        """Run full ingestion pipeline"""
        print(f"\n{'='*60}")
        print(f"J-Job ChromaDB Ingestion v{VERSION}")
        print(f"{'='*60}\n")
        
        # Create collection
        collection = self.create_collection(delete_existing)
        
        # Discover J-Jobs
        jjobs = self.discover_jjobs()
        
        if not jjobs:
            print("[ERROR] No J-Jobs found")
            return {"status": "error", "message": "No J-Jobs found"}
        
        # Ingest each J-Job
        total_docs = 0
        for i, jjob_path in enumerate(jjobs, 1):
            docs_added = self.ingest_jjob(collection, jjob_path)
            total_docs += docs_added
            
            # Progress indicator
            if i % 10 == 0 or i == len(jjobs):
                print(f"[PROGRESS] {i}/{len(jjobs)} J-Jobs processed, {total_docs} documents")
        
        # Final stats
        print(f"\n{'='*60}")
        print(f"Ingestion Complete")
        print(f"{'='*60}")
        print(f"  J-Jobs ingested: {self.stats['jjobs_ingested']}")
        print(f"  Documents added: {self.stats['documents_added']}")
        print(f"  Errors: {self.stats['errors']}")
        print(f"  Extraction stats:")
        for key, value in self.extractor.stats.items():
            print(f"    - {key}: {value}")
        print(f"{'='*60}\n")
        
        return {
            "status": "success",
            "collection": COLLECTION_NAME,
            "jjobs_ingested": self.stats['jjobs_ingested'],
            "documents_added": self.stats['documents_added'],
            "errors": self.stats['errors'],
            "extractor_stats": dict(self.extractor.stats)
        }


# ============================================================================
# CLI INTERFACE
# ============================================================================

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Ingest Global Workflow J-Jobs into ChromaDB"
    )
    parser.add_argument(
        "--delete-existing",
        action="store_true",
        help="Delete existing collection before ingestion"
    )
    parser.add_argument(
        "--host",
        default=CHROMADB_HOST,
        help=f"ChromaDB host (default: {CHROMADB_HOST})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=CHROMADB_PORT,
        help=f"ChromaDB port (default: {CHROMADB_PORT})"
    )
    parser.add_argument(
        "--workflow-root",
        default=WORKFLOW_ROOT,
        help=f"Global Workflow root path"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and parse but don't write to ChromaDB"
    )
    
    args = parser.parse_args()
    
    # Use provided workflow root
    workflow_root = args.workflow_root
    
    if args.dry_run:
        print("[DRY RUN] Discovering and parsing J-Jobs without ChromaDB write\n")
        ingester = JJobIngester(args.host, args.port, workflow_root)
        jjobs = ingester.discover_jjobs()
        
        for jjob_path in jjobs[:5]:  # Sample first 5
            print(f"\n--- {jjob_path.name} ---")
            content = jjob_path.read_text()
            metadata = ingester.extractor.extract(str(jjob_path), content)
            print(json.dumps(metadata, indent=2, default=str))
        
        print(f"\n[DRY RUN] Would process {len(jjobs)} J-Jobs")
        return
    
    # Run full ingestion
    ingester = JJobIngester(args.host, args.port, workflow_root)
    result = ingester.run(delete_existing=args.delete_existing)
    
    # Exit code based on result
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
