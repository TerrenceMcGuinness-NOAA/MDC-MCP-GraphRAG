#!/usr/bin/env node

/**
 * Quick test for get_workflow_structure tool
 */

// Import the tool function directly from the MCP server
import { RAGEnhancedMCPServer } from '../mcp-server-rag.js';

async function testGetWorkflowStructure() {
  console.log("🔧 Testing get_workflow_structure tool directly...\n");
  
  const server = new RAGEnhancedMCPServer();
  
  // Test cases
  const testCases = [
    { name: "General Overview", params: {} },
    { name: "Jobs Component", params: { component: "jobs" } },
    { name: "Scripts Component", params: { component: "scripts" } },
    { name: "Configs Component", params: { component: "configs" } }
  ];

  for (const testCase of testCases) {
    console.log(`📋 ${testCase.name}:`);
    console.log(`Parameters: ${JSON.stringify(testCase.params)}`);
    
    try {
      const result = await server.getWorkflowStructure(testCase.params.component);
      console.log("Response:");
      console.log(result.content[0].text);
      console.log("─".repeat(60));
    } catch (error) {
      console.log("❌ Error:", error.message);
    }
  }
}

testGetWorkflowStructure().catch(console.error);
