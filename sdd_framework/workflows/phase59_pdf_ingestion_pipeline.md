# Phase 59 — PDF Ingestion Pipeline Enhancement

**Version**: 1.0.0  
**Created**: 2026-05-19  
**Status**: ready  
**Estimated effort**: 3–4 hours  
**Depends on**: Phase 58 (HTML crawl gap closure — validates the ingest pipeline is working)

---

## Problem Statement

The ingest pipeline (`mcp_server_node/scripts/ingestion_base.py`) explicitly
excludes `.pdf` URLs (line 617, URL skip list). Four SME-requested sources
are PDF documents containing critical ESMF/NUOPC/ESMPy API references that
have no HTML equivalent:

| Source | URL | Content |
|--------|-----|---------|
| `esmf-ref-pdf` | https://earthsystemmodeling.org/docs/release/latest/ESMF_refdoc.pdf | ESMF Fortran API — complete subroutine/type reference |
| `esmc-ref-pdf` | https://earthsystemmodeling.org/docs/release/latest/ESMC_crefdoc.pdf | ESMF C API — C language bindings |
| `nuopc-ref-pdf` | https://earthsystemmodeling.org/docs/release/latest/NUOPC_refdoc.pdf | NUOPC layer — full generic component API |
| `esmpy-pdf` | https://earthsystemmodeling.org/esmpy_doc/release/latest/ESMPy.pdf | ESMPy — Python bindings for ESMF regridding |

These are large reference PDFs (likely 200–1000+ pages each). The Titan
Text Embeddings v2 model handles text input up to 8,192 tokens per chunk,
so the pipeline needs to:

1. Download the PDF
2. Extract text (page by page)
3. Chunk the extracted text (respecting section boundaries where possible)
4. Embed each chunk with Titan and index to OpenSearch

---

## Existing Infrastructure

- **`pypdf`** is already available in the project (`supported_repos/activate-rag-vllm/indexer.py` uses `PdfReader`)
- **`ingestion_base.py`** has the chunking + embedding logic for HTML text
- **Manifest entries** already exist with `crawl_type: "pdf_download"` and `max_pages: 1`
- **Titan embedding** path is proven working (Phase C-3 confirmed Bedrock InvokeModel access)

---

## Implementation Plan

### Option A: Extend `ingest_documentation_v8.py` (preferred)

Add a `pdf_download` handler alongside the existing `readthedocs` / `github_pages` / `single_page` handlers:

```python
if source["crawl_type"] == "pdf_download":
    pdf_bytes = requests.get(source["url"]).content
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages_text = [page.extract_text() or "" for page in reader.pages]
    full_text = "\n\n".join(pages_text)
    # Chunk using existing chunker (section-aware or fixed-size)
    chunks = chunk_text(full_text, max_tokens=512)
    # Embed + index as usual
```

### Option B: Standalone `ingest_pdf.py` script

A separate script that:
1. Reads the manifest for `crawl_type: "pdf_download"` entries
2. Downloads each PDF
3. Extracts text via `pypdf`
4. Chunks (512-token windows with 64-token overlap)
5. Embeds via Bedrock Titan
6. Indexes to OpenSearch (`mdc-workflow-docs-titan1024`)
7. Updates manifest `last_ingested` + `doc_count`

---

## Steps

### Step 1 — Verify PDF accessibility and content quality

Download each PDF and check text extraction quality:

```bash
python3 -c "
import requests, io
from pypdf import PdfReader

urls = [
    'https://earthsystemmodeling.org/docs/release/latest/ESMF_refdoc.pdf',
    'https://earthsystemmodeling.org/docs/release/latest/ESMC_crefdoc.pdf',
    'https://earthsystemmodeling.org/docs/release/latest/NUOPC_refdoc.pdf',
    'https://earthsystemmodeling.org/esmpy_doc/release/latest/ESMPy.pdf',
]
for url in urls:
    r = requests.get(url, timeout=60)
    reader = PdfReader(io.BytesIO(r.content))
    sample = reader.pages[5].extract_text()[:200] if len(reader.pages) > 5 else 'too short'
    print(f'{len(reader.pages):4d} pages  {len(r.content)/1024/1024:.1f}MB  {url.split(\"/\")[-1]}')
    print(f'     Sample: {sample[:100]}...')
    print()
"
```

**Test**: All 4 PDFs download successfully, have extractable text (not scanned images), and produce meaningful content from `extract_text()`.

---

### Step 2 — Implement PDF ingestion handler

Create `scripts/ingest_pdf_sources.py`:

- Loads manifest, filters for `crawl_type == "pdf_download"` + `enabled == True`
- For each source:
  - Downloads PDF to memory
  - Extracts text page-by-page via `pypdf.PdfReader`
  - Concatenates with page markers (`\n\n--- Page N ---\n\n`)
  - Chunks using 512-token sliding window (64-token overlap)
  - Adds metadata: `source_name`, `page_number`, `url`, `tier`
  - Embeds via Bedrock Titan (`amazon.titan-embed-text-v2:0`, 1024 dims)
  - Indexes to `mdc-workflow-docs-titan1024`
- Calls `ManifestRegistry.update_source_from_ingest()` on success
- Supports `--dry-run` (download + extract + chunk, skip embed/index)
- Supports `--source <name>` to target a single PDF

**Test**: `--dry-run` shows chunk count and sample text for each PDF.

---

### Step 3 — Remove `.pdf` from the URL exclusion list in `ingestion_base.py`

Update line ~617 of `mcp_server_node/scripts/ingestion_base.py` to remove
`.pdf` from the skip list (or gate it behind a flag). This prevents the
existing HTML crawler from accidentally trying to parse PDFs as HTML, while
allowing the new PDF handler to process them.

**Test**: Existing HTML ingestion still works (no regression).

---

### Step 4 — Run PDF ingestion for all 4 sources

```bash
python3 scripts/ingest_pdf_sources.py \
    --manifest mcp_server_python/src/config/unified_manifest.json \
    --region us-east-1
```

**Test**: 
- `search_documentation("ESMF_FieldCreate Fortran API")` returns hits from `esmf-ref-pdf`
- `search_documentation("ESMPy regrid")` returns hits from `esmpy-pdf`
- `search_documentation("NUOPC_CompSetEntryPoint")` returns hits from `nuopc-ref-pdf`
- `list_all_sources` shows `doc_count > 0` and `last_ingested` set for all 4

---

### Step 5 — Update CHANGELOG + rebuild image

Add `[8.24.0]` CHANGELOG entry. Rebuild and deploy `python-all-tools-v5`
so the runtime manifest reflects the new doc counts.

**Test**: `get_server_info` on the live runtime shows updated version.

---

## Acceptance Criteria

- All 4 PDF sources ingested with `doc_count > 0`
- `search_documentation` returns relevant hits for ESMF/ESMC/NUOPC/ESMPy API queries
- Text extraction quality is good (not garbled, preserves code examples and API signatures)
- Manifest `last_ingested` updated for all 4 sources
- No regression in existing HTML ingestion pipeline
- Chunk metadata includes `page_number` for traceability

---

## Technical Notes

### Titan Embedding Constraints
- Max input: 8,192 tokens (~32,000 characters)
- Output: 1024-dimension vector
- Chunking at 512 tokens with 64-token overlap keeps well within limits
- Cost: ~$0.00002 per 1000 tokens — 4 large PDFs ≈ $0.50–$2.00 total

### PDF Text Quality Risks
- ESMF docs are generated from LaTeX → PDF, so text extraction should be clean
- Mathematical formulas may extract poorly — acceptable for RAG (context is sufficient)
- Tables may lose structure — consider preserving as markdown-formatted text

### Chunk Metadata Schema
```json
{
  "source": "esmf-ref-pdf",
  "url": "https://earthsystemmodeling.org/docs/release/latest/ESMF_refdoc.pdf",
  "page": 42,
  "chunk_index": 3,
  "tier": "tier1_critical",
  "crawl_type": "pdf_download"
}
```

---

## Files Touched

**Created**:
- `scripts/ingest_pdf_sources.py`

**Modified**:
- `mcp_server_node/scripts/ingestion_base.py` (remove .pdf from skip list)
- `mcp_server_python/src/config/unified_manifest.json` (doc_count + last_ingested updated)
- `CHANGELOG.md`
