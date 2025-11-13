#!/usr/bin/env node

/**
 * Test script to use MCP tools for explaining workflow components
 */

import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import path from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function testMCPTool(toolName, args) {
  return new Promise((resolve, reject) => {
    const mcpServerPath = path.join(__dirname, 'mcp-server-rag.js');
    const mcpProcess = spawn('node', [mcpServerPath]);
    
    let stdout = '';
    let stderr = '';
    
    mcpProcess.stdout.on('data', (data) => {
      stdout += data.toString();
    });
    
    mcpProcess.stderr.on('data', (data) => {
      stderr += data.toString();
    });
    
    mcpProcess.on('close', (code) => {
      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        reject(new Error(`Process exited with code ${code}\nStderr: ${stderr}`));
      }
    });
    
    // Send initialize request
    const initRequest = {
      "jsonrpc": "2.0",
      "id": 1,
      "method": "initialize",
      "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0.0"}
      }
    };
    
    // Send tool call request
    const toolRequest = {
      "jsonrpc": "2.0",
      "id": 2,
      "method": "tools/call",
      "params": {
        "name": toolName,
        "arguments": args
      }
    };
    
    mcpProcess.stdin.write(JSON.stringify(initRequest) + '\n');
    
    // Wait a bit for initialization, then send tool request
    setTimeout(() => {
      mcpProcess.stdin.write(JSON.stringify(toolRequest) + '\n');
      mcpProcess.stdin.end();
    }, 2000);
    
    // Timeout after 30 seconds
    setTimeout(() => {
      mcpProcess.kill();
      reject(new Error('Timeout after 30 seconds'));
    }, 30000);
  });
}

async function main() {
  try {
    console.log('🔍 Testing MCP RAG server with C48_ATM reanalysis query...\n');
    
    const result = await testMCPTool('explain_with_context', {
      component: 'C48_ATM reanalysis',
      context_level: 'intermediate',
      include_examples: true
    });
    
    console.log('📋 MCP Server Response:');
    console.log('='.repeat(80));
    console.log(result.stdout);
    
    if (result.stderr) {
      console.log('\n🔧 Server Debug Info:');
      console.log('-'.repeat(40));
      console.log(result.stderr);
    }
    
  } catch (error) {
    console.error('❌ Error testing MCP tool:', error.message);
    
    // Fallback: try the basic explain_component tool
    try {
      console.log('\n🔄 Trying basic explain_component tool...\n');
      const fallbackResult = await testMCPTool('explain_component', {
        component: 'C48_ATM'
      });
      
      console.log('📋 Fallback Response:');
      console.log('='.repeat(80));
      console.log(fallbackResult.stdout);
      
    } catch (fallbackError) {
      console.error('❌ Fallback also failed:', fallbackError.message);
    }
  }
}

main().catch(console.error);
