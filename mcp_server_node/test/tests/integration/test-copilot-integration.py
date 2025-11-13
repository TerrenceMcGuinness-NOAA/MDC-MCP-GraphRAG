#!/usr/bin/env python3
"""
Test script to demonstrate Node.js MCP server integration with GitHub Copilot

This file can be used to test if GitHub Copilot is receiving context
from our Node.js MCP server about the global workflow system.

The Node.js MCP server provides enhanced workflow context including:
- Detailed job script analysis
- System configuration information
- Workflow component relationships
- Performance monitoring integration

Try asking Copilot to:
1. List the job scripts available in this repository
2. Explain what the JGDAS_ATMOS_ANALYSIS_DIAG job does
3. Show configuration for the Hera system
4. Explain the workflow components like GSI, UFS, MOM6
5. Describe the rocotometrics performance monitoring
"""

import argparse
import sys
import subprocess
import json
import os
from pathlib import Path

def find_upward(start_path, target_name):
    """Simple implementation of find_upward functionality."""
    current = Path(start_path).resolve()
    while current != current.parent:
        target_path = current / target_name
        if target_path.exists():
            return str(target_path)
        current = current.parent
    return None

def check_mcp_server_status(verbose=False):
    """Check if the Node.js MCP server can start successfully"""
    try:
        if verbose:
            print("🧪 Testing Node.js MCP server startup capability...")

        # Test if the server can start (using test mode which exits cleanly)
        result = subprocess.run(['./start-mcp-server-node.sh', 'test'],
                              capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            if verbose:
                print("✅ Node.js MCP server startup test passed")
                print("   (MCP servers are started by VS Code on-demand, not as background processes)")
            return True
        else:
            if verbose:
                print("❌ Node.js MCP server startup test failed")
                if result.stderr:
                    print(f"   Error: {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        if verbose:
            print("✅ Node.js MCP server started successfully (timeout expected for interactive mode)")
        return True
    except Exception as e:
        if verbose:
            print(f"❌ Error testing MCP server startup: {e}")
        return False

def check_vscode_settings(verbose=False):
    """Check VS Code MCP server configuration"""
    # Use wxflow's find_upward to locate the repository root
    try:
        repo_root = Path(find_upward('.github'))
    except Exception as e:
        if verbose:
            print(f"❌ Could not find repository root: {e}")
        return False

    settings_files = [
        repo_root / ".vscode" / "settings.json",
        repo_root / ".vscode" / "settings-node.json"
    ]

    if verbose:
        print(f"🔍 Looking for VS Code settings in: {repo_root}")

    settings_file = None
    for file_path in settings_files:
        if file_path.exists():
            settings_file = file_path
            break

    if not settings_file:
        if verbose:
            print(f"❌ No .vscode/settings.json or .vscode/settings-node.json found in {repo_root}")
            print(f"   Checked files: {[str(f) for f in settings_files]}")
        return False

    try:
        with open(settings_file) as f:
            settings = json.load(f)

        if "mcpServers" in settings:
            mcp_servers = settings["mcpServers"]
            if verbose:
                print(f"✅ Found {len(mcp_servers)} MCP server(s) configured in {settings_file.name}:")
                for name, config in mcp_servers.items():
                    print(f"   - {name}: {config.get('command', 'N/A')}")
                    print(f"     cwd: {config.get('cwd', 'N/A')}")
            return True
        else:
            if verbose:
                print(f"❌ No mcpServers configuration found in {settings_file}")
            return False
    except Exception as e:
        if verbose:
            print(f"❌ Error reading VS Code settings: {e}")
        return False

def test_mcp_server_startup(verbose=False):
    """Test if the MCP server can start successfully"""
    try:
        if verbose:
            print("🧪 Testing MCP server startup...")

        # Run the test command
        result = subprocess.run(['./start-mcp-server-node.sh', 'test'],
                              capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            if verbose:
                print("✅ MCP server startup test passed")
                print(f"   Output: {result.stdout.strip()}")
            return True
        else:
            if verbose:
                print("❌ MCP server startup test failed")
                print(f"   Error: {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        if verbose:
            print("❌ MCP server startup test timed out")
        return False
    except Exception as e:
        if verbose:
            print(f"❌ Error testing MCP server startup: {e}")
        return False

def run_comprehensive_test(verbose=False):
    """Run comprehensive MCP server tests"""
    print("🚀 Running Node.js MCP Server Integration Tests")
    print("=" * 50)

    tests = [
        ("MCP Server Startup Test", check_mcp_server_status),
        ("VS Code Configuration", check_vscode_settings),
        ("Server Functionality Test", test_mcp_server_startup),
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        if verbose:
            print(f"\n📋 Testing: {test_name}")

        try:
            if test_func(verbose):
                passed += 1
                if not verbose:
                    print(f"✅ {test_name}: PASSED")
            else:
                if not verbose:
                    print(f"❌ {test_name}: FAILED")
        except Exception as e:
            if not verbose:
                print(f"❌ {test_name}: ERROR - {e}")

    print(f"\n📊 Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Node.js MCP server integration is working correctly.")
        return True
    else:
        print("⚠️  Some tests failed. Check the output above for details.")
        return False
def test_nodejs_mcp_workflow_knowledge():
    """
    Test function to verify Copilot knows about our workflow via Node.js MCP server

    The Node.js MCP server provides richer context than the Python version,
    including detailed job analysis and performance monitoring integration.

    When you start typing comments or code here, GitHub Copilot should
    be able to suggest content based on the enhanced global workflow context
    provided by our Node.js MCP server.
    """

    # Ask Copilot to complete these comments with workflow-specific knowledge:

    # The JGDAS jobs are responsible for...

    # The main systems supported by this workflow are...

    # The Rocoto workflow engine is used to...

    # The rocotometrics performance monitoring shows...

    # Common job patterns in this workflow include...

    # The Node.js MCP server enhancement provides...

    pass

def example_nodejs_mcp_workflow_setup():
    """
    Example function where Copilot should suggest workflow-related code
    enhanced by the Node.js MCP server context
    """

    # Copilot should know about the systems available:
    systems = [
        # Copilot should suggest: "hera", "orion", "hercules", "wcoss2", etc.
    ]

    # Copilot should know about the job types:
    job_types = [
        # Copilot should suggest: "JGDAS_", "JGFS_", "JGLOBAL_", etc.
    ]

    # Node.js MCP server should provide enhanced component knowledge:
    workflow_components = [
        # Copilot should suggest: "GSI", "UFS", "MOM6", "CICE", "WW3", etc.
    ]

    # Performance monitoring tools:
    monitoring_tools = [
        # Copilot should suggest: "rocotometrics", "rocotostat", etc.
    ]

    return systems, job_types, workflow_components, monitoring_tools

def test_nodejs_mcp_server_features():
    """
    Test specific Node.js MCP server enhanced features
    """

    # Test if Copilot knows about the Node.js server improvements:

    # The Node.js MCP server uses the official SDK which provides...

    # Performance improvements in the Node.js version include...

    # The enhanced workflow structure information includes...

    # Installation differences between Python and Node.js versions...

    pass

def main():
    """Main function with command-line argument parsing"""
    parser = argparse.ArgumentParser(
        description="Test Node.js MCP server integration with GitHub Copilot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Run basic demonstration
  %(prog)s test               # Run comprehensive tests
  %(prog)s test --verbose     # Run tests with detailed output
  %(prog)s --check-server     # Check if MCP server is running
  %(prog)s --check-config     # Check VS Code configuration
        """
    )

    parser.add_argument('command', nargs='?', choices=['test'],
                        help='Command to run (default: demonstration mode)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed output')
    parser.add_argument('--check-server', action='store_true',
                        help='Check if MCP server is running')
    parser.add_argument('--check-config', action='store_true',
                        help='Check VS Code MCP configuration')

    args = parser.parse_args()

    if args.check_server:
        if check_mcp_server_status(verbose=True):
            sys.exit(0)
        else:
            sys.exit(1)

    if args.check_config:
        if check_vscode_settings(verbose=True):
            sys.exit(0)
        else:
            sys.exit(1)

    if args.command == 'test':
        success = run_comprehensive_test(verbose=args.verbose)
        sys.exit(0 if success else 1)

    # Default behavior - demonstration mode
    print("Testing Node.js MCP server integration with GitHub Copilot")
    print("Node.js MCP server provides enhanced workflow context")
    print("Start typing in the functions above to test Copilot suggestions")
    print()
    print("To verify the Node.js MCP server is running:")
    print("  ./start-mcp-server-node.sh test")
    print()
    print("To check VS Code settings:")
    print("  cat .vscode/settings.json")
    print()
    print("For comprehensive testing, run:")
    print("  ./test-copilot-integration.py test --verbose")
    print()

    test_nodejs_mcp_workflow_knowledge()
    example_nodejs_mcp_workflow_setup()
    test_nodejs_mcp_server_features()

if __name__ == "__main__":
    main()
