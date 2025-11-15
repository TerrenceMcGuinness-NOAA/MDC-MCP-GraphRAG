#!/usr/bin/env python3
"""
Simple embeddings API server for LangFlow
Serves all-mpnet-base-v2 embeddings via HTTP
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from typing import List
import uvicorn

app = FastAPI(title="Embeddings API", version="1.0.0")

# Enable CORS for LangFlow access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load model once at startup
MODEL_NAME = "all-mpnet-base-v2"
print(f"Loading model: {MODEL_NAME}...")
model = SentenceTransformer(MODEL_NAME)
print("Model loaded successfully!")

class EmbeddingRequest(BaseModel):
    texts: List[str]

class EmbeddingResponse(BaseModel):
    embeddings: List[List[float]]
    model: str
    dimension: int

@app.get("/")
def root():
    return {
        "service": "Embeddings API",
        "model": MODEL_NAME,
        "dimension": 768,
        "status": "ready"
    }

@app.get("/health")
def health():
    return {"status": "healthy", "model": MODEL_NAME}

@app.post("/embed", response_model=EmbeddingResponse)
def embed_texts(request: EmbeddingRequest):
    """Generate embeddings for a list of texts"""
    if not request.texts:
        raise HTTPException(status_code=400, detail="No texts provided")
    
    try:
        # Generate embeddings
        embeddings = model.encode(request.texts, convert_to_numpy=True)
        
        return EmbeddingResponse(
            embeddings=embeddings.tolist(),
            model=MODEL_NAME,
            dimension=embeddings.shape[1]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/embed_query")
def embed_query(request: dict):
    """Single text embedding (for compatibility with LangChain format)"""
    text = request.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="No text provided")
    
    try:
        embedding = model.encode([text], convert_to_numpy=True)[0]
        return {"embedding": embedding.tolist()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/embeddings")
@app.post("/embeddings")
def openai_compatible_embeddings(request: dict):
    """OpenAI-compatible embeddings endpoint for LangFlow"""
    input_text = request.get("input", "")
    
    # Handle both string and list inputs
    if isinstance(input_text, str):
        texts = [input_text]
    elif isinstance(input_text, list):
        texts = input_text
    else:
        raise HTTPException(status_code=400, detail="Invalid input format")
    
    try:
        embeddings = model.encode(texts, convert_to_numpy=True)
        
        # Return OpenAI-compatible format
        # Calculate token count (approximate)
        token_count = sum(len(str(t).split()) for t in texts)
        
        return {
            "object": "list",
            "data": [
                {
                    "object": "embedding",
                    "embedding": emb.tolist(),
                    "index": i
                }
                for i, emb in enumerate(embeddings)
            ],
            "model": MODEL_NAME,
            "usage": {
                "prompt_tokens": token_count,
                "total_tokens": token_count
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
