#!/usr/bin/env node

/**
 * Simulate Cursor's MCP tool usage for get_workflow_structure
 * This shows how Cursor would call the tool
 */

import { spawn } from 'child_process';
import path from 'path';

const mcpServerPath = path.join(__dirname, '..', 'mcp-server-rag.js');

async function simulateCursorUsage() {
  console.log("🎯 Simulating Cursor's MCP tool usage for get_workflow_structure\n");
  
  const server = spawn('node', [mcpServerPath], {
    stdio: ['pipe', 'pipe', 'pipe']
  });

  // Wait for server to initialize
  await new Promise(resolve => setTimeout(resolve, 2000));

  console.log("📝 Cursor would send this request:");
  const request = {
    jsonrpc: "2.0",
    id: 1,
    method: "tools/call",
    params: {
      name: "get_workflow_structure",
      arguments: { component: "jobs" }
    }
  };
  console.log(JSON.stringify(request, null, 2));

  console.log("\n🔄 Sending request to MCP server...");
  
  return new Promise((resolve, reject) => {
    let responseData = '';
    
    server.stdout.on('data', (data) => {
      responseData += data.toString();
      
      try {
        const response = JSON.parse(responseData);
        if (response.jsonrpc === "2.0" && response.result) {
          console.log("\n✅ MCP Server Response:");
          console.log(JSON.stringify(response, null, 2));
          
          console.log("\n📋 Extracted Content:");
          console.log(response.result.content[0].text);
          
          server.kill();
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
    
    setTimeout(() => {
      server.kill();
      reject(new Error('Timeout'));
    }, 10000);
  });
}

simulateCursorUsage()
  .then(() => console.log("\n✅ Demo completed successfully!"))
  .catch(error => console.error("❌ Error:", error.message));
