#!/bin/bash

# Hugging Face Integration Demo Runner
# Demonstrates the complete MCP + HF integration for Global Workflow

set -e

echo "🚀 Global Workflow - Hugging Face MCP Integration Demo"
echo "=================================================="
echo ""

# Check if we're in the demo directory
if [[ ! -f "package.json" ]] || [[ ! -f "demo-integration-architecture.js" ]]; then
    echo "❌ Error: Please run this script from the demo directory"
    echo "Expected files: package.json, demo-integration-architecture.js"
    exit 1
fi

# Check Node.js version
if ! command -v node >/dev/null 2>&1; then
    echo "❌ Error: Node.js is not installed"
    echo "Please install Node.js version 18.0.0 or higher"
    exit 1
fi

NODE_VERSION=$(node --version | sed 's/v//')
MAJOR_VERSION=$(echo "${NODE_VERSION}" | cut -d. -f1)

if [[ "${MAJOR_VERSION}" -lt 18 ]]; then
    echo "❌ Error: Node.js version ${NODE_VERSION} is too old"
    echo "Please install Node.js version 18.0.0 or higher"
    exit 1
fi

echo "✓ Node.js version ${NODE_VERSION} detected"
echo ""

# Function to run demo component
run_demo() {
    local demo_name="$1"
    local demo_file="$2"
    local description="$3"
    
    echo "--- ${demo_name} ---"
    echo "${description}"
    echo ""
    
    if [[ -f "${demo_file}" ]]; then
        echo "Running: node ${demo_file}"
        echo ""
        node "${demo_file}"
        echo ""
        echo "✅ ${demo_name} completed successfully"
    else
        echo "❌ Error: ${demo_file} not found"
        return 1
    fi
    
    echo ""
    echo "Press Enter to continue..."
    read -r
    echo ""
}

# Main demo menu
show_menu() {
    echo "Available Demos:"
    echo "1. Architecture Overview Demo"
    echo "2. Live Integration Demo"
    echo "3. Integration Test Suite"
    echo "4. Complete Integration Test" 
    echo "5. Run All Demos"
    echo "6. Exit"
    echo ""
    echo -n "Select demo (1-6): "
}

# Main loop
while true; do
    show_menu
    read -r choice
    echo ""
    
    case "${choice}" in
        1)
            run_demo "Architecture Overview" "demo-integration-architecture.js" \
                "Shows the integration architecture and file structure"
            ;;
        2)
            run_demo "Live Integration Demo" "live-integration-demo.js" \
                "Demonstrates how Local RAG + HF tools work together"
            ;;
        3)
            run_demo "Basic Integration Test" "test-huggingface-integration.js" \
                "Tests basic Hugging Face integration components"
            ;;
        4)
            run_demo "Complete Integration Test" "test-complete-hf-integration.js" \
                "Comprehensive test of all integration components"
            ;;
        5)
            echo "🔄 Running All Demos..."
            echo ""
            run_demo "Architecture Overview" "demo-integration-architecture.js" \
                "Shows the integration architecture and file structure"
            run_demo "Live Integration Demo" "live-integration-demo.js" \
                "Demonstrates how Local RAG + HF tools work together"
            run_demo "Basic Integration Test" "test-huggingface-integration.js" \
                "Tests basic Hugging Face integration components"
            echo "🎉 All demos completed successfully!"
            ;;
        6)
            echo "👋 Thanks for trying the Hugging Face MCP Integration Demo!"
            exit 0
            ;;
        *)
            echo "❌ Invalid choice. Please select 1-6."
            echo ""
            ;;
    esac
done
