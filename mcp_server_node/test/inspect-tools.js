#!/usr/bin/env node

/**
 * Tool Inspector - Lists all MCP tools and their parameters
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Read the RAG server file
const serverFile = path.join(__dirname, '..', 'mcp-server-rag.js');
const serverContent = fs.readFileSync(serverFile, 'utf8');

console.log('='.repeat(60));
console.log('🛠️  MCP TOOL PARAMETER REFERENCE');
console.log('='.repeat(60));

// Extract tool definitions from the setupTools method
const toolsMatch = serverContent.match(/const ragTools = \[([\s\S]*?)\];/);
const originalToolsMatch = serverContent.match(/const originalTools = \[([\s\S]*?)\];/);

function parseToolDefinitions(toolsString, category) {
    console.log(`\n📋 ${category.toUpperCase()} TOOLS:`);
    console.log('-'.repeat(40));
    
    // Split by tool objects
    const toolBlocks = toolsString.split(/},\s*{/).map(block => {
        if (!block.trim().startsWith('{')) block = '{' + block;
        if (!block.trim().endsWith('}')) block = block + '}';
        return block;
    });
    
    toolBlocks.forEach((block, index) => {
        // Extract tool name
        const nameMatch = block.match(/name:\s*["']([^"']+)["']/);
        const descMatch = block.match(/description:\s*["']([^"']+)["']/);
        
        if (nameMatch && descMatch) {
            console.log(`\n${index + 1}. 🔧 ${nameMatch[1]}`);
            console.log(`   Description: ${descMatch[1]}`);
            
            // Extract parameters
            const propertiesMatch = block.match(/properties:\s*{([\s\S]*?)}/);
            if (propertiesMatch) {
                console.log(`   Parameters:`);
                
                // Find parameter definitions
                const paramMatches = [...propertiesMatch[1].matchAll(/(\w+):\s*{([^}]+)}/g)];
                paramMatches.forEach(match => {
                    const paramName = match[1];
                    const paramDef = match[2];
                    
                    const typeMatch = paramDef.match(/type:\s*["']([^"']+)["']/);
                    const descMatch = paramDef.match(/description:\s*["']([^"']+)["']/);
                    const enumMatch = paramDef.match(/enum:\s*\[([^\]]+)\]/);
                    const defaultMatch = paramDef.match(/default:\s*([^,\n]+)/);
                    
                    console.log(`     • ${paramName}:`);
                    if (typeMatch) console.log(`       - Type: ${typeMatch[1]}`);
                    if (descMatch) console.log(`       - Description: ${descMatch[1]}`);
                    if (enumMatch) console.log(`       - Options: ${enumMatch[1].replace(/["']/g, '')}`);
                    if (defaultMatch) console.log(`       - Default: ${defaultMatch[1]}`);
                });
            }
            
            // Check for required parameters
            const requiredMatch = block.match(/required:\s*\[([^\]]+)\]/);
            if (requiredMatch) {
                console.log(`   Required: ${requiredMatch[1].replace(/["']/g, '')}`);
            }
        }
    });
}

if (originalToolsMatch) {
    parseToolDefinitions(originalToolsMatch[1], 'Original');
}

if (toolsMatch) {
    parseToolDefinitions(toolsMatch[1], 'RAG-Enhanced');
}

console.log('\n' + '='.repeat(60));
console.log('📖 USAGE EXAMPLES:');
console.log('='.repeat(60));

console.log(`
🔧 get_workflow_structure()
   get_workflow_structure(component="jobs")

🔧 list_job_scripts()

🔧 get_system_configs()
   get_system_configs(system="hera")

🔧 explain_component(component="rocoto")

🔧 search_documentation(query="job dependencies")
   search_documentation(query="...", doc_type="user_guide", max_results=3)

🔧 explain_with_context(component="gsi")
   explain_with_context(component="...", context_level="advanced", include_examples=true)

🔧 find_similar_code(code_snippet="#!/bin/bash")
   find_similar_code(code_snippet="...", language="bash", similarity_threshold=0.8)

🔧 get_operational_guidance(task="restart job")
   get_operational_guidance(task="...", system="hera", urgency="urgent")

🔧 analyze_dependencies(job_name="JGLOBAL_FORECAST")
   analyze_dependencies(job_name="...", direction="upstream", depth=3)
`);

console.log('\n' + '='.repeat(60));
