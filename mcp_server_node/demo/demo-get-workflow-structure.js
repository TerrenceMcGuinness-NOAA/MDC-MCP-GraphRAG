#!/usr/bin/env node

/**
 * Demo script for get_workflow_structure tool
 * This demonstrates how to call the MCP tool directly
 */

import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// MCP server path
const mcpServerPath = path.join(__dirname, '..', 'mcp-server-rag.js');

// Test cases for get_workflow_structure
const testCases = [
  {
    name: "General Overview",
    params: {}
  },
  {
    name: "Jobs Component",
    params: { component: "jobs" }
  },
  {
    name: "Scripts Component", 
    params: { component: "scripts" }
  },
  {
    name: "Configs Component",
    params: { component: "configs" }
  }
];

async function testGetWorkflowStructure() {
  console.log("🔄 Starting MCP server for get_workflow_structure demo...\n");
  
  const server = spawn('node', [mcpServerPath], {
    stdio: ['pipe', 'pipe', 'pipe']
  });

  // Wait a moment for server to initialize
  await new Promise(resolve => setTimeout(resolve, 2000));

  console.log("📋 Testing get_workflow_structure tool:\n");

  for (const testCase of testCases) {
    console.log(`🔧 Test: ${testCase.name}`);
    console.log(`📝 Parameters: ${JSON.stringify(testCase.params)}`);
    
    const request = {
      jsonrpc: "2.0",
      id: Date.now(),
      method: "tools/call",
      params: {
        name: "get_workflow_structure",
        arguments: testCase.params
      }
    };

    try {
      const response = await sendRequest(server, request);
      console.log("✅ Response:");
      console.log(response.result.content[0].text.substring(0, 200) + "...");
      console.log("─".repeat(50));
    } catch (error) {
      console.log("❌ Error:", error.message);
    }
  }

  server.kill();
  console.log("\n✅ Demo completed!");
}

async function sendRequest(server, request) {
  return new Promise((resolve, reject) => {
    let responseData = '';
    
    server.stdout.on('data', (data) => {
      responseData += data.toString();
      
      try {
        const response = JSON.parse(responseData);
        if (response.jsonrpc === "2.0" && response.result) {
          resolve(response);
        }
      } catch (e) {
        // Incomplete JSON, continue reading
      }
    });

    server.stderr.on('data', (data) => {
      // Ignore stderr for this demo
    });

    server.on('error', (error) => {
      reject(error);
    });

    // Send the request
    server.stdin.write(JSON.stringify(request) + '\n');
    
    // Timeout after 5 seconds
    setTimeout(() => {
      reject(new Error('Request timeout'));
    }, 5000);
  });
}

// Run the demo
testGetWorkflowStructure().catch(console.error);
