# Design Document

## Overview

This document describes the technical design for the PDF ingestion pipeline — a standalone Python script (`mcp_server_node/scripts/ingest_pdf_sources.py`) that downloads PDF documents declared in the unified manifest, extracts text via pypdf, chunks at 512-token windows with 64-token overlap, embeds with Amazon Titan Text Embeddings v2 (1024 dimensions), and indexes to the `mdc-workflow-docs-titan1024` OpenSearch index. The script reuses the existing `BedrockProvider` and `OpenSearchVectorClient` infrastructure without modifying the HTML crawler.

## Architecture

The PDF ingestion pipeline is a single-file CLI script that follows the same manifest-driven pattern as other ingestion scripts in the project. It operates independently from `ingestion_base.py` (the HTML crawler) and routes exclusively on `crawl_type == "pdf_download"` manifest entries.

```
┌─────────────────────────────────────────────────────────────────┐
│                  ingest_pdf_sources.py                           │
├─────────────────────────────────────────────────────────────────┤
│  CLI Layer (argparse)                                           │
│    --manifest, --region, --source, --dry-run                    │
├─────────────────────────────────────────────────────────────────┤
│  Manifest Loader                                                │
│    Load JSON → filter crawl_type=="pdf_download" + enabled      │
├─────────────────────────────────────────────────────────────────┤
│  PDF Processor (per source)                                     │
│    Download → Extract (pypdf) → Concatenate → Chunk → Embed     │
├─────────────────────────────────────────────────────────────────┤
│  Indexer                                                        │
│    OpenSearchVectorClient.upsert() → mdc-workflow-docs-titan1024│
├─────────────────────────────────────────────────────────────────┤
│  Manifest Writeback                                             │
│    Update last_ingested + doc_count → atomic write              │
└─────────────────────────────────────────────────────────────────┘

External Dependencies:
  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────┐
  │  pypdf       │  │  BedrockProvider  │  │ OpenSearchVector  │
  │  (extract)   │  │  (titan1024)      │  │ Client (aws)      │
  └──────────────┘  └──────────────────┘  └───────────────────┘
```

## Components and Interfaces

### Components

### 1. CLI Interface (`parse_args`)

Parses command-line arguments using `argparse`:

```python
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest PDF sources from unified manifest into OpenSearch"
    )
    parser.add_argument(
        "--manifest",
        default="mcp_server_python/src/config/unified_manifest.json",
        help="Path to unified manifest JSON",
    )
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--source", help="Process only this named source")
    parser.add_argument("--dry-run", action="store_true", help="Skip embed/index")
    return parser.parse_args()
```

**Validates: Requirements 8.1, 8.2, 8.3, 8.4**

### 2. Manifest Loader (`load_pdf_sources`)

Loads the unified manifest and filters for actionable PDF sources:

```python
def load_pdf_sources(
    manifest_path: str, source_filter: Optional[str] = None
) -> Tuple[List[dict], dict]:
    """Load manifest, return (filtered_sources, full_manifest_data).

    Raises SystemExit if --source doesn't match any enabled pdf_download entry.
    """
    with open(manifest_path) as f:
        manifest = json.load(f)

    pdf_sources = [
        s for s in manifest["sources"]
        if s.get("crawl_type") == "pdf_download" and s.get("enabled", False)
    ]

    if source_filter:
        matched = [s for s in pdf_sources if s["name"] == source_filter]
        if not matched:
            print(f"ERROR: source '{source_filter}' not found among enabled "
                  f"pdf_download entries", file=sys.stderr)
            sys.exit(1)
        pdf_sources = matched

    return pdf_sources, manifest
```

**Validates: Requirements 1.1, 1.2, 1.3**

### 3. PDF Downloader (`download_pdf`)

Downloads a PDF from a URL with timeout and error handling:

```python
def download_pdf(url: str, source_name: str) -> Optional[bytes]:
    """Download PDF bytes. Returns None on failure (logs and skips)."""
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content
    except (requests.RequestException, requests.HTTPError) as exc:
        print(f"[ERROR] Failed to download {source_name} from {url}: {exc}",
              file=sys.stderr)
        return None
```

**Validates: Requirements 2.1, 2.4**

### 4. Text Extractor (`extract_text`)

Extracts text from PDF bytes using pypdf, concatenating pages with markers:

```python
def extract_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF, concatenating pages with boundary markers.

    Skips pages that yield empty text.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text()
        if text and text.strip():
            parts.append(f"\n\n--- Page {i} ---\n\n{text}")
    return "".join(parts)
```

**Validates: Requirements 2.2, 2.3, 2.5**

### 5. Token-Based Chunker (`chunk_text`)

Splits text into 512-token chunks with 64-token overlap using whitespace tokenization:

```python
def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> List[str]:
    """Split text into token-based chunks with sliding window overlap.

    Uses whitespace splitting for token approximation.
    If the final remainder is < overlap tokens, appends to last chunk.
    """
    tokens = text.split()
    if not tokens:
        return []

    chunks = []
    start = 0
    while start < len(tokens):
        end = start + chunk_size
        chunk_tokens = tokens[start:end]

        # Check if remainder after this chunk is too small
        remaining = len(tokens) - end
        if 0 < remaining < overlap:
            # Absorb remainder into this chunk
            chunk_tokens = tokens[start:]
            chunks.append(" ".join(chunk_tokens))
            break

        chunks.append(" ".join(chunk_tokens))
        if end >= len(tokens):
            break
        start = end - overlap

    return chunks
```

**Validates: Requirements 3.1, 3.2, 3.3**

### 6. Embedding Wrapper (`embed_chunks`)

Embeds chunks using the existing BedrockProvider with error handling per chunk:

```python
def embed_chunks(
    chunks: List[str], provider: BedrockProvider, source_name: str
) -> List[Tuple[int, List[float]]]:
    """Embed chunks, returning (chunk_index, vector) pairs.

    Skips chunks that fail embedding (logs error, continues).
    """
    results = []
    for i, chunk in enumerate(chunks):
        try:
            vectors = provider.embed([chunk])
            results.append((i, vectors[0]))
        except EmbeddingError as exc:
            print(f"[ERROR] Embedding failed for {source_name} chunk {i}: {exc}",
                  file=sys.stderr)
            continue
    return results
```

**Validates: Requirements 4.1, 4.2, 4.3**

### 7. Indexer (`index_chunks`)

Indexes embedded chunks to OpenSearch with deterministic IDs and full metadata:

```python
def index_chunks(
    source: dict,
    chunks: List[str],
    embeddings: List[Tuple[int, List[float]]],
    collection: "_OpenSearchCollection",
) -> int:
    """Index embedded chunks to OpenSearch. Returns count of indexed docs."""
    source_name = source["name"]
    ids = []
    documents = []
    vectors = []
    metadatas = []

    for chunk_idx, vector in embeddings:
        doc_id = f"{source_name}-chunk-{chunk_idx}"
        ids.append(doc_id)
        documents.append(chunks[chunk_idx])
        vectors.append(vector)
        metadatas.append({
            "source": source_name,
            "url": source["url"],
            "page": _estimate_page(chunks[chunk_idx]),
            "chunk_index": chunk_idx,
            "tier": source.get("tier", ""),
            "crawl_type": "pdf_download",
        })

    if ids:
        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=vectors,
            metadatas=metadatas,
        )
    return len(ids)
```

**Validates: Requirements 5.1, 5.2, 5.3, 5.4**

### 8. Page Estimator (`_estimate_page`)

Determines which page a chunk originated from by scanning for page markers:

```python
def _estimate_page(chunk_text: str) -> int:
    """Extract page number from the most recent page marker in chunk text."""
    matches = re.findall(r"--- Page (\d+) ---", chunk_text)
    return int(matches[-1]) if matches else 1
```

### 9. Manifest Writeback (`update_manifest`)

Atomically updates the manifest with ingestion results:

```python
def update_manifest(manifest_path: str, manifest_data: dict) -> None:
    """Write manifest atomically (temp file + rename)."""
    tmp_path = manifest_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(manifest_data, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, manifest_path)
```

**Validates: Requirements 6.1, 6.2, 6.3**

### 10. Main Orchestrator (`main`)

Coordinates the full pipeline with dry-run support and summary reporting:

```python
def main() -> None:
    args = parse_args()
    start_time = time.time()

    pdf_sources, manifest_data = load_pdf_sources(args.manifest, args.source)

    # Set up embedding + indexing (unless dry-run)
    provider = None
    collection = None
    if not args.dry_run:
        os.environ["AWS_REGION"] = args.region
        profile = EmbeddingModelRegistry().get_profile("titan1024")
        provider = create_provider(profile)
        os_client = get_vector_client()
        collection = os_client.get_or_create_collection("mdc-workflow-docs-titan1024")

    total_chunks = 0
    sources_processed = 0

    for source in pdf_sources:
        pdf_bytes = download_pdf(source["url"], source["name"])
        if pdf_bytes is None:
            continue

        text = extract_text(pdf_bytes)
        chunks = chunk_text(text)
        sources_processed += 1

        if args.dry_run:
            print(f"\n[DRY-RUN] {source['name']}")
            print(f"  PDF size: {len(pdf_bytes) / 1024 / 1024:.1f} MB")
            print(f"  Pages extracted: {text.count('--- Page ')}")
            print(f"  Chunks produced: {len(chunks)}")
            if chunks:
                print(f"  First chunk sample: {chunks[0][:200]}")
            continue

        embeddings = embed_chunks(chunks, provider, source["name"])
        indexed = index_chunks(source, chunks, embeddings, collection)
        total_chunks += indexed

        # Update manifest entry
        for entry in manifest_data["sources"]:
            if entry["name"] == source["name"]:
                entry["last_ingested"] = datetime.utcnow().isoformat() + "Z"
                entry["doc_count"] = indexed
                break

    # Write manifest (unless dry-run)
    if not args.dry_run and sources_processed > 0:
        update_manifest(args.manifest, manifest_data)

    elapsed = time.time() - start_time
    print(f"\nDone: {sources_processed} sources, {total_chunks} chunks indexed, "
          f"{elapsed:.1f}s elapsed")
```

**Validates: Requirements 7.1, 7.2, 7.3, 8.5**

### Interfaces

### Input Interface

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--manifest` | str | `mcp_server_python/src/config/unified_manifest.json` | Path to unified manifest |
| `--region` | str | `us-east-1` | AWS region for Bedrock/OpenSearch |
| `--source` | str | None | Limit to single named source |
| `--dry-run` | flag | False | Skip embedding and indexing |

### External Dependencies

| Dependency | Module | Usage |
|------------|--------|-------|
| `pypdf` | `pypdf.PdfReader` | PDF text extraction |
| `requests` | `requests.get` | HTTP download |
| `BedrockProvider` | `embedding_provider.py` | Titan embedding |
| `EmbeddingModelRegistry` | `embedding_registry.py` | Model profile lookup |
| `OpenSearchVectorClient` | `aws_backend.py` | Vector indexing |

### Output

- Indexed documents in `mdc-workflow-docs-titan1024` OpenSearch index
- Updated `unified_manifest.json` with `last_ingested` and `doc_count`
- Console summary of processing results

## Data Models

### Manifest Source Entry (input)

```json
{
  "name": "esmf-ref-pdf",
  "source_type": "url_crawl",
  "collection_target": "global-workflow-docs-v8-0-0",
  "embedding_profile": "titan1024",
  "enabled": true,
  "description": "ESMF Fortran API Reference (PDF)",
  "last_ingested": null,
  "doc_count": 0,
  "url": "https://earthsystemmodeling.org/docs/release/latest/ESMF_refdoc.pdf",
  "crawl_type": "pdf_download",
  "max_pages": 1,
  "tier": "tier1_critical",
  "priority": 1
}
```

### Indexed Document (output)

```json
{
  "_id": "esmf-ref-pdf-chunk-42",
  "content": "... chunk text ...",
  "embedding": [0.012, -0.034, ...],
  "metadata": {
    "source": "esmf-ref-pdf",
    "url": "https://earthsystemmodeling.org/docs/release/latest/ESMF_refdoc.pdf",
    "page": 15,
    "chunk_index": 42,
    "tier": "tier1_critical",
    "crawl_type": "pdf_download"
  }
}
```

## Error Handling

| Error Condition | Behavior |
|----------------|----------|
| PDF download fails (network/HTTP error) | Log error, skip source, continue |
| Page yields empty text | Skip page, continue extraction |
| Titan embedding fails for a chunk | Log error, skip chunk, continue |
| `--source` name not found | Exit with non-zero status + error message |
| Manifest file not found | Exit with non-zero status (argparse/IOError) |
| OpenSearch bulk index partial failure | Log warning (handled by `_OpenSearchCollection`) |

## Independence from HTML Crawler

The script is fully standalone:
- Does **not** import from `ingestion_base.py`
- Routes on `crawl_type == "pdf_download"` only
- The `.pdf` exclusion in `ingestion_base.py` line 617 remains intact
- Both pipelines can run concurrently without interference

## Testing Strategy

The PDF ingestion pipeline uses a dual testing approach:

**Property-based tests** (via Hypothesis) validate the pure logic functions:
- `load_pdf_sources` — source filtering correctness
- `chunk_text` — chunking invariants (size, overlap, remainder absorption)
- `extract_text` — page concatenation format
- Document ID generation — determinism and format

**Example-based unit tests** validate integration points and specific behaviors:
- CLI argument parsing defaults
- Dry-run mode output format
- Manifest writeback atomicity (temp file + rename)
- Error handling paths (download failure, embedding failure)

**No new unit test files are required** per the implementation plan — the correctness properties below define what would be tested if a test suite were added later.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Source Selection Correctness

*For any* unified manifest containing a mix of source entries with various `crawl_type` values and `enabled` flags, the `load_pdf_sources` function SHALL return exactly those entries where `crawl_type == "pdf_download"` AND `enabled == true`. When a `--source` filter is provided, the result SHALL contain at most one entry matching that name.

**Validates: Requirements 1.1, 1.2**

### Property 2: Invalid Source Rejection

*For any* source name string that does not match any enabled `pdf_download` entry in the manifest, the script SHALL exit with a non-zero status code and the error output SHALL contain the unrecognized source name.

**Validates: Requirements 1.3**

### Property 3: Page Concatenation Format

*For any* list of page texts (where some may be empty), the `extract_text` function SHALL produce output containing `--- Page N ---` markers only for non-empty pages, with N being the correct 1-based page number from the original PDF, and empty pages SHALL not appear in the output.

**Validates: Requirements 2.3, 2.5**

### Property 4: Chunking Invariants

*For any* non-empty input text, the `chunk_text` function SHALL produce chunks where: (a) each chunk contains at most 512 whitespace-delimited tokens, (b) consecutive chunks overlap by exactly 64 tokens (except the final chunk which may be larger if it absorbed a small remainder), (c) no chunk exists with fewer than 64 tokens unless the entire input is fewer than 64 tokens, and (d) concatenating all chunks (accounting for overlap) reconstructs the original token sequence.

**Validates: Requirements 3.1, 3.2, 3.3**

### Property 5: Fault Tolerance

*For any* list of sources or chunks where some fail (download errors or embedding errors), the script SHALL successfully process all non-failing items — the failure of item at position K SHALL not prevent processing of items at positions K+1, K+2, etc.

**Validates: Requirements 2.4, 4.3**

### Property 6: Metadata Completeness

*For any* indexed document produced by the pipeline, the metadata SHALL contain all six required fields: `source` (non-empty string), `url` (valid URL), `page` (positive integer), `chunk_index` (non-negative integer), `tier` (string), and `crawl_type` (value `"pdf_download"`).

**Validates: Requirements 5.2**

### Property 7: Deterministic Document IDs

*For any* source name and chunk index, the generated document ID SHALL equal `"{source_name}-chunk-{chunk_index}"`, and calling the ID generation function twice with the same inputs SHALL produce identical results (idempotent re-ingestion).

**Validates: Requirements 5.4**

### Property 8: Doc Count Consistency

*For any* successfully processed source, the `doc_count` written to the manifest SHALL equal the exact number of chunks that were successfully embedded and indexed for that source.

**Validates: Requirements 6.2**

### Property 9: Dry-Run Safety

*For any* execution with the `--dry-run` flag, the script SHALL NOT call the embedding provider, SHALL NOT call the OpenSearch indexer, and SHALL NOT modify the manifest file on disk — while still producing chunks from downloaded PDFs.

**Validates: Requirements 7.1, 7.3**
