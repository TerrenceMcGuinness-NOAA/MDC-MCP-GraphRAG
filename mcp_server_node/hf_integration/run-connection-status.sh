#!/bin/bash

# Hugging Face Integration Connection Status
# ==========================================
# This script checks the connection status and integration readiness

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "🚀 Checking Hugging Face Integration Connection Status"
echo "====================================================="
echo

# Check if we're in the correct directory
if [[ ! -f "package.json" ]]; then
    echo "❌ Error: package.json not found in current directory"
    echo "   Please run this script from the hf_integration directory"
    exit 1
fi

# Check if node_modules exists
if [[ ! -d "node_modules" ]]; then
    echo "📦 Installing dependencies..."
    npm install
    echo
fi

# Run the architecture demonstration
echo "🏗️  Checking Integration Architecture..."
echo "----------------------------------------"
node integration-architecture-status.js
echo

# Run the live integration demo
echo "🔴 Testing Live Integration Connection..."
echo "----------------------------------"
node live-integration-status.js
echo

# Run the complete integration test
echo "🧪 Running Integration Connection Tests..."
echo "-------------------------------------"
node test-complete-hf-integration.js
echo

echo "✅ Connection status check completed successfully!"
echo
echo "📚 For more information:"
echo "   - README.md - Overview and setup instructions"
echo "   - INTEGRATION_QA_ANSWERS.md - Common questions and answers"
echo "   - MCP_INTEGRATION_ARCHITECTURE.md - Technical architecture details"
