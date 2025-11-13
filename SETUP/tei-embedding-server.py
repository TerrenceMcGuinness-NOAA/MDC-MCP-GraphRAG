#!/usr/bin/env python3
"""
Hugging Face TEI-compatible Embedding Server
Provides embeddings via HTTP API for LangFlow integration
Port: 8081
"""

from flask import Flask, request, jsonify
from sentence_transformers import SentenceTransformer
import sys

app = Flask(__name__)

# Load the same model ChromaDB uses
print("🔄 Loading embedding model: sentence-transformers/all-MiniLM-L6-v2", file=sys.stderr)
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
print("✅ Model loaded successfully", file=sys.stderr)

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"}), 200

@app.route('/embed', methods=['POST'])
def embed():
    """TEI-compatible embedding endpoint"""
    try:
        data = request.json
        inputs = data.get('inputs')
        
        if inputs is None:
            return jsonify({"error": "Missing 'inputs' field"}), 400
        
        # Handle single string or list of strings
        if isinstance(inputs, str):
            inputs = [inputs]
        
        # Generate embeddings
        embeddings = model.encode(inputs)
        
        # Return in TEI format (list of lists)
        return jsonify(embeddings.tolist())
        
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return jsonify({"error": str(e)}), 500

@app.route('/info', methods=['GET'])
def info():
    """Model information endpoint"""
    return jsonify({
        "model_id": "sentence-transformers/all-MiniLM-L6-v2",
        "model_type": "embedding",
        "max_input_length": 512,
        "embedding_dimension": 384
    })

if __name__ == '__main__':
    print("🚀 Starting TEI-compatible Embedding Server on http://0.0.0.0:8081", file=sys.stderr)
    print("   Health: http://localhost:8081/health", file=sys.stderr)
    print("   Embed:  POST http://localhost:8081/embed", file=sys.stderr)
    app.run(host='0.0.0.0', port=8081, debug=False)
