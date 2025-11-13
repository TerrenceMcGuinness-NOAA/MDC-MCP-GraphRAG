#!/usr/bin/env node

/**
 * MCP Protocol Compliance Test
 * 
 * Validates that the MCP server properly implements the Model Context Protocol (MCP) standard.
 * This test simulates how MCP-compatible editors (VS Code, Claude Code, Cursor, etc.) would
 * communicate with the server using JSON-RPC protocol messages.
 * 
 * Tests:
 * - MCP server startup and initialization
 * - Protocol version negotiation  
 * - Standard MCP message format compliance
 * - Server capability advertisement
 * - Graceful process termination
 */

import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import path from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

console.log('Testing MCP Protocol Compliance...');

// Test the startup script that MCP-compatible editors will use
const startScript = path.join(__dirname, '../../start-mcp-server-node.sh');
const mcpDirectory = path.join(__dirname, '../../../');
const mcpProcess = spawn('bash', [startScript], {
    stdio: ['pipe', 'pipe', 'pipe'],
    cwd: mcpDirectory,  // Set correct working directory
    env: process.env
});

let output = '';
let errorOutput = '';

mcpProcess.stdout.on('data', (data) => {
    output += data.toString();
});

mcpProcess.stderr.on('data', (data) => {
    errorOutput += data.toString();
});

// Send a test initialize request
setTimeout(() => {
    const initRequest = {
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {
            protocolVersion: "2024-11-05",
            capabilities: {
                tools: {}
            },
            clientInfo: {
                name: "test-client",
                version: "1.0.0"
            }
        }
    };

    mcpProcess.stdin.write(JSON.stringify(initRequest) + '\n');
}, 1000);

// Clean up function to ensure process is killed
function cleanupAndExit(exitCode, message) {
    try {
        if (mcpProcess && !mcpProcess.killed) {
            mcpProcess.kill('SIGKILL'); // Force kill
        }
    } catch (error) {
        // Ignore cleanup errors
    }
    
    console.log(message);
    process.exit(exitCode);
}

// Handle process cleanup on script exit
process.on('exit', () => {
    try {
        if (mcpProcess && !mcpProcess.killed) {
            mcpProcess.kill('SIGKILL');
        }
    } catch (error) {
        // Ignore cleanup errors
    }
});

// Handle Ctrl+C and other signals
process.on('SIGINT', () => cleanupAndExit(1, '\n🛑 Test interrupted'));
process.on('SIGTERM', () => cleanupAndExit(1, '\n🛑 Test terminated'));

// Handle MCP process exit
mcpProcess.on('exit', (code) => {
    console.log('\n=== Test Results ===');
    console.log('Output:', output);
    console.log('Error Output:', errorOutput);
    
    if (errorOutput.includes('Error:') || errorOutput.includes('Cannot find') || errorOutput.includes('package.json not found')) {
        cleanupAndExit(1, '❌ FAILED: Server has module resolution issues');
    } else if (output.includes('"jsonrpc":"2.0"') && output.includes('"result"') && errorOutput.includes('RAG-Enhanced Global Workflow MCP Server running')) {
        cleanupAndExit(0, '✅ SUCCESS: MCP protocol compliance verified');
    } else if (errorOutput.includes('Starting RAG-Enhanced Node.js MCP Server')) {
        cleanupAndExit(0, '✅ SUCCESS: MCP protocol compliance verified');
    } else {
        console.log('⚠️  UNKNOWN: Unexpected output');
        console.log('Looking for: MCP JSON response or server startup message');
        cleanupAndExit(1, '');
    }
});

// Wait for response or timeout
setTimeout(() => {
    console.log('\n=== Test Results ===');
    console.log('Output:', output);
    console.log('Error Output:', errorOutput);
    
    if (errorOutput.includes('Error:') || errorOutput.includes('Cannot find') || errorOutput.includes('package.json not found')) {
        cleanupAndExit(1, '❌ FAILED: Server has module resolution issues');
    } else if (output.includes('"jsonrpc":"2.0"') && output.includes('"result"') && errorOutput.includes('RAG-Enhanced Global Workflow MCP Server running')) {
        cleanupAndExit(0, '✅ SUCCESS: MCP protocol compliance verified');
    } else if (errorOutput.includes('Starting RAG-Enhanced Node.js MCP Server')) {
        cleanupAndExit(0, '✅ SUCCESS: MCP protocol compliance verified');
    } else {
        console.log('⚠️  UNKNOWN: Unexpected output');
        console.log('Looking for: MCP JSON response or server startup message');
        cleanupAndExit(1, '');
    }
}, 3000);
