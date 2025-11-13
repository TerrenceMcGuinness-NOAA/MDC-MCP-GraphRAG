#!/bin/bash
# Load all required spack modules for MCP ingestion scripts
# Usage: source load_spack_modules.sh

echo "[INFO] Loading spack Python modules for MCP ingestion..."

# Load GCC compiler (required for Python packages in lmod hierarchy)
module load gcc/11.5.0 2>/dev/null

# Load Python base
module load python/3.11 2>/dev/null || echo "[WARN] python/3.11 already loaded or not needed"

# Load document processing packages
echo "[INFO] Loading document processing packages..."
module load py-beautifulsoup4/4.13.4 2>/dev/null && echo "  [OK] py-beautifulsoup4"
module load py-lxml/6.0.1 2>/dev/null && echo "  [OK] py-lxml"
module load py-requests/2.32.5 2>/dev/null && echo "  [OK] py-requests"
module load py-aiohttp/3.12.15 2>/dev/null && echo "  [OK] py-aiohttp"
module load py-nltk/3.9.1 2>/dev/null && echo "  [OK] py-nltk"
module load py-h11 2>/dev/null && echo "  [OK] py-h11"

# Check if numpy/torch/transformers are available (may still be installing)
if module avail py-numpy 2>&1 | grep -q "py-numpy"; then
    echo "[INFO] Loading ML/RAG packages..."
    module load py-numpy 2>/dev/null && echo "  [OK] py-numpy"
    module load py-torch 2>/dev/null && echo "  [OK] py-torch"
    module load py-transformers 2>/dev/null && echo "  [OK] py-transformers"
else
    echo "[WARN] ML/RAG packages (numpy, torch, transformers) not yet available"
    echo "       These are still being compiled. Check back later with:"
    echo "       spack find py-numpy py-torch py-transformers"
fi

echo ""
echo "[INFO] Modules loaded. pip packages (chromadb, sentence-transformers) are"
echo "       automatically available from ~/.local/lib/python3.11/site-packages/"
echo ""
echo "[INFO] To verify all imports work:"
echo "       python3 -c 'from bs4 import BeautifulSoup; import lxml; import requests; print(\"[OK]\")'"
