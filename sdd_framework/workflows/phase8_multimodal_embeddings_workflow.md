# Phase 8: Multimodal Embeddings Upgrade Workflow

**Version**: 1.0.0
**Date**: December 3, 2025
**Status**: Planned (Pending Gemini 2.5 Pro API Key)
**Priority**: High
**Dependencies**: Gemini 2.5 Pro API access

## Executive Summary

Upgrade the MCP RAG system from text-only embeddings to multimodal embeddings, enabling semantic search across diagrams, charts, workflow visualizations, and other visual content in NOAA/GFS documentation.

## Current State

### Text-Only Embedding Pipeline
| Component | Current Value |
|-----------|---------------|
| **Embedding Model** | `all-mpnet-base-v2` (Sentence Transformers) |
| **Dimensions** | 768 |
| **Modality** | Text-only |
| **Provider** | Local (HuggingFace/SentenceTransformers) |
| **Image Handling** | ❌ Excluded from crawling |
| **Alt Text Extraction** | ❌ Not implemented |

### Known Limitations
1. **Diagrams Lost**: GFS workflow diagrams, data flow charts excluded
2. **No Visual Context**: Architecture diagrams not searchable
3. **Alt Text Ignored**: Image descriptions in HTML not extracted
4. **Figure Captions**: May or may not be captured depending on HTML structure

## Proposed Solution: Gemini 2.5 Pro Multimodal Embeddings

### Why Gemini 2.5 Pro?
| Feature | Benefit |
|---------|---------|
| **Native Multimodal** | Single model handles text + images |
| **High Quality** | State-of-the-art embedding quality |
| **API-Based** | No local GPU requirements |
| **Unified Vector Space** | Text and image embeddings are directly comparable |
| **Context Window** | 1M+ tokens for large document understanding |

### Target Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                    Ingestion Pipeline v8                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   Text      │    │   Images    │    │   Mixed     │     │
│  │  Content    │    │  (PNG/JPG)  │    │  (HTML+img) │     │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘     │
│         │                  │                  │             │
│         ▼                  ▼                  ▼             │
│  ┌─────────────────────────────────────────────────┐       │
│  │           Gemini 2.5 Pro Embedding API           │       │
│  │     (text-embedding-004 / multimodal model)     │       │
│  └─────────────────────────────────────────────────┘       │
│                          │                                  │
│                          ▼                                  │
│  ┌─────────────────────────────────────────────────┐       │
│  │              Unified Vector Space               │       │
│  │           768/1536-dim embeddings               │       │
│  └─────────────────────────────────────────────────┘       │
│                          │                                  │
│                          ▼                                  │
│  ┌─────────────────────────────────────────────────┐       │
│  │                   ChromaDB                       │       │
│  │          (multimodal-docs-v8-0-0)               │       │
│  └─────────────────────────────────────────────────┘       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Phases

### Phase 8.1: API Integration Setup (Week 1)
- [ ] Obtain Gemini 2.5 Pro API key
- [ ] Create `GeminiEmbeddingClient.js` wrapper
- [ ] Add API key management to `mcp-config.env`
- [ ] Implement rate limiting and retry logic
- [ ] Add cost tracking/monitoring

### Phase 8.2: Image Extraction Pipeline (Week 1-2)
- [ ] Update `WebCrawler.js` to download images (not skip)
- [ ] Update `ContentExtractor.js` to extract:
  - `<img alt="...">` alt text
  - `<figcaption>` caption text
  - `<figure>` context preservation
- [ ] Create `ImageProcessor.js` for:
  - Image validation (size, format)
  - Thumbnail generation (for storage efficiency)
  - Base64 encoding for API submission

### Phase 8.3: Multimodal Ingestion Scripts (Week 2)
- [ ] Create `ingest_multimodal_v8.py` with:
  - Text chunk embedding (Gemini text-embedding)
  - Image embedding (Gemini multimodal)
  - Combined text+image context chunks
- [ ] Update `ingestion_base.py` with `MultimodalChunker` class
- [ ] Add image metadata to chunk records

### Phase 8.4: Query Enhancement (Week 2-3)
- [ ] Update `UnifiedDataAccess.js` for multimodal queries
- [ ] Add image-to-text query support
- [ ] Implement cross-modal similarity search
- [ ] Update MCP tools for multimodal results

### Phase 8.5: Testing & Validation (Week 3)
- [ ] Create test cases with known diagrams
- [ ] Validate diagram searchability
- [ ] Benchmark retrieval quality vs text-only
- [ ] Document API costs and performance

## API Configuration

### Environment Variables (Future)
```bash
# mcp-config.env additions for Phase 8
GEMINI_API_KEY=<your-api-key>
EMBEDDING_PROVIDER=gemini          # gemini | local | openai
EMBEDDING_MODEL_TEXT=text-embedding-004
EMBEDDING_MODEL_MULTIMODAL=gemini-2.5-pro
EMBEDDING_DIMENSIONS=768           # or 1536 for higher quality
MULTIMODAL_ENABLED=true
IMAGE_MAX_SIZE_MB=10
IMAGE_FORMATS=png,jpg,jpeg,gif,svg
```

### Cost Estimation
| Content Type | Est. Volume | Cost/1K tokens | Monthly Est. |
|--------------|-------------|----------------|--------------|
| Text chunks | ~10,000 | $0.00025 | ~$2.50 |
| Images | ~500 | $0.002/image | ~$1.00 |
| Queries | ~5,000/mo | $0.00025 | ~$1.25 |
| **Total** | - | - | **~$5/month** |

## Collection Naming

| Version | Collection Name | Content |
|---------|-----------------|---------|
| v7 (current) | `global-workflow-docs-v7-0-0` | Text-only |
| v8 (planned) | `multimodal-docs-v8-0-0` | Text + Images |
| v8 (planned) | `multimodal-code-v8-0-0` | Code + Diagrams |

## Interim Solution (Before API Key)

While waiting for Gemini API access, implement **Phase 8.2 partially**:
1. ✅ Extract alt text and captions (text-only, no API needed)
2. ✅ Store image URLs/paths as metadata
3. ✅ Index alt text with current MPNet embeddings
4. ⏳ Upgrade to multimodal embeddings when API available

## Success Criteria

1. **Diagram Searchability**: Query "GFS data flow" returns relevant diagrams
2. **Cross-Modal Retrieval**: Text query finds related images
3. **Quality Metrics**: Retrieval precision ≥ 0.8 for visual content
4. **Cost Efficiency**: Monthly API costs < $10
5. **Latency**: Embedding generation < 500ms per item

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| API costs exceed budget | Implement caching, batch processing |
| Rate limiting | Exponential backoff, request queuing |
| Image size limits | Resize/compress before embedding |
| API availability | Fallback to text-only embeddings |

## References

- [Gemini API Documentation](https://ai.google.dev/docs)
- [Multimodal Embeddings Best Practices](https://cloud.google.com/vertex-ai/docs/generative-ai/embeddings/get-multimodal-embeddings)
- Current embedding implementation: [ingestion_base.py](../../mcp_server_node/scripts/ingestion_base.py#L39)
- WebCrawler image exclusion: [WebCrawler.js](../../mcp_server_node/src/ingestion/WebCrawler.js#L37)
