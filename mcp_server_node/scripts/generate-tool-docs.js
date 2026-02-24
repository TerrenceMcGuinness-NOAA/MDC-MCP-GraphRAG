#!/usr/bin/env node

/**
 * generate-tool-docs.js — Phase 29 Step 4
 *
 * Extracts tool schemas from all MCP tool modules by mocking registerTool(),
 * then generates a Markdown reference table that can be pasted into instruction files.
 *
 * Usage:
 *   node scripts/generate-tool-docs.js              # print to stdout
 *   node scripts/generate-tool-docs.js --json        # JSON output
 *   node scripts/generate-tool-docs.js --check       # compare against instructions file
 *
 * @version 1.0.0
 * @phase Phase 29
 */

import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Tool module files — order matches instruction file convention
const TOOL_MODULES = [
  { file: 'WorkflowInfoTools.js',   category: 'Workflow Info',     db: 'Filesystem' },
  { file: 'CodeAnalysisTools.js',   category: 'Code Analysis',     db: 'Neo4j' },
  { file: 'SemanticSearchTools.js', category: 'Semantic Search',   db: 'ChromaDB + Neo4j' },
  { file: 'EE2ComplianceTools.js',  category: 'EE2 Compliance',    db: 'ChromaDB' },
  { file: 'OperationalTools.js',    category: 'Operational',       db: 'ChromaDB' },
  { file: 'GraphRAGTools.js',       category: 'GraphRAG',          db: 'ChromaDB + Neo4j' },
  { file: 'GitHubTools.js',         category: 'GitHub',            db: 'GitHub API' },
  { file: 'SDDWorkflowTools.js',    category: 'SDD Workflows',     db: 'Filesystem' },
];

// Utility tools registered outside of the standard tool modules
const EXTRA_SOURCES = [
  { file: '../src/UnifiedMCPServer.js', category: 'Utility', db: 'Built-in' },
];

/**
 * Extract tool registrations from a module file using regex.
 * Faster and more reliable than dynamic import (avoids DB connections).
 */
function extractToolsFromSource(filePath) {
  const source = readFileSync(filePath, 'utf-8');
  const tools = [];

  // Match server.registerTool( 'name', 'description...', { schema }, handler )
  // Handle descriptions that may contain embedded double quotes inside single-quoted strings
  const lines = source.split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const regMatch = line.match(/server\.registerTool\(/);
    if (!regMatch) { i++; continue; }

    // Collect the full registerTool(...) call by tracking paren depth
    let block = '';
    let depth = 0;
    let started = false;
    for (let j = i; j < lines.length; j++) {
      block += lines[j] + '\n';
      for (const ch of lines[j]) {
        if (ch === '(') { depth++; started = true; }
        if (ch === ')') depth--;
      }
      if (started && depth <= 0) break;
    }

    // Extract tool name (first string argument)
    const nameMatch = block.match(/registerTool\(\s*['"`]([^'"`]+)['"`]/);
    if (!nameMatch) { i++; continue; }
    const name = nameMatch[1];

    // Extract description (second string — find after the name)
    const afterName = block.substring(block.indexOf(nameMatch[0]) + nameMatch[0].length);
    const descMatch = afterName.match(/,\s*'((?:[^'\\]|\\.|"[^"]*")*)'/);
    const description = descMatch ? descMatch[1].replace(/\\'/g, "'") : '';

    // Extract schema object — find the { type: 'object' ... } block
    const schemaStart = block.indexOf("type: 'object'") !== -1
      ? block.lastIndexOf('{', block.indexOf("type: 'object'"))
      : block.indexOf('type: "object"') !== -1
        ? block.lastIndexOf('{', block.indexOf('type: "object"'))
        : -1;

    let required = [];
    const properties = [];

    if (schemaStart !== -1) {
      let braceCount = 0;
      let schemaEnd = schemaStart;
      for (let k = schemaStart; k < block.length; k++) {
        if (block[k] === '{') braceCount++;
        if (block[k] === '}') braceCount--;
        if (braceCount === 0) { schemaEnd = k + 1; break; }
      }
      const schemaStr = block.substring(schemaStart, schemaEnd);

      // Parse required array
      const requiredMatch = schemaStr.match(/required:\s*\[([^\]]*)\]/);
      required = requiredMatch
        ? requiredMatch[1].match(/['"`]([^'"`]+)['"`]/g)?.map(s => s.replace(/['"`]/g, '')) || []
        : [];

      // Parse properties
      const propPattern = /(\w+):\s*\{\s*type:\s*['"`](\w+)['"`]/g;
      let propMatch;
      while ((propMatch = propPattern.exec(schemaStr)) !== null) {
        if (propMatch[1] === 'object' || propMatch[1] === 'items') continue;
        const propName = propMatch[1];
        const propType = propMatch[2];
        const defaultPattern = new RegExp(`${propName}:[^}]*default:\\s*([^,}]+)`, 's');
        const defaultMatch = schemaStr.match(defaultPattern);
        const defaultVal = defaultMatch ? defaultMatch[1].trim().replace(/['"`]/g, '') : null;

        properties.push({
          name: propName,
          type: propType,
          required: required.includes(propName),
          default: defaultVal
        });
      }
    }

    tools.push({ name, description, required, properties });
    i++;
  }

  return tools;
}

/**
 * Generate Quick Reference table (matches eib-mcp-tools.instructions.md format)
 */
function generateQuickReference(allTools) {
  let md = '## Quick Reference: Required Parameters\n\n';
  md += '| Tool | Required Param | Optional Params |\n';
  md += '|------|----------------|------------------|\n';

  for (const tool of allTools) {
    const reqStr = tool.required.length > 0
      ? tool.required.map(p => `\`${p}\``).join(', ')
      : '*(none)*';
    const optStr = tool.properties
      .filter(p => !p.required)
      .map(p => `\`${p.name}\``)
      .join(', ') || '*(none)*';
    md += `| \`${tool.name}\` | ${reqStr} | ${optStr} |\n`;
  }

  return md;
}

/**
 * Generate full tool reference grouped by module
 */
function generateFullReference(moduleTools) {
  let md = '## Tool Reference (auto-generated)\n\n';
  md += `*Generated: ${new Date().toISOString().split('T')[0]}*\n`;
  md += `*Total tools: ${moduleTools.reduce((sum, m) => sum + m.tools.length, 0)}*\n\n`;

  for (const mod of moduleTools) {
    md += `### ${mod.category} (${mod.tools.length} tools — ${mod.db})\n\n`;
    md += '| Tool | Required | Optional | Description |\n';
    md += '|------|----------|----------|-------------|\n';

    for (const tool of mod.tools) {
      const reqStr = tool.required.length > 0
        ? tool.required.map(p => `\`${p}\``).join(', ')
        : '—';
      const optStr = tool.properties
        .filter(p => !p.required)
        .map(p => `\`${p.name}\``)
        .join(', ') || '—';
      const desc = tool.description.length > 80
        ? tool.description.substring(0, 77) + '...'
        : tool.description;
      md += `| \`${tool.name}\` | ${reqStr} | ${optStr} | ${desc} |\n`;
    }
    md += '\n';
  }

  return md;
}

/**
 * Check mode: compare extracted tools against instruction file
 */
function checkAgainstInstructions(allTools) {
  const instructionsPath = resolve(__dirname, '../../.github/instructions/eib-mcp-tools.instructions.md');
  let instructions;
  try {
    instructions = readFileSync(instructionsPath, 'utf-8');
  } catch {
    console.error('[ERROR] Cannot read instructions file:', instructionsPath);
    process.exit(1);
  }

  const missing = [];
  const found = [];
  for (const tool of allTools) {
    if (instructions.includes(tool.name)) {
      found.push(tool.name);
    } else {
      missing.push(tool.name);
    }
  }

  console.log(`[OK] ${found.length}/${allTools.length} tools documented in instructions`);
  if (missing.length > 0) {
    console.log(`[WARN] ${missing.length} tools MISSING from instructions:`);
    for (const name of missing) {
      console.log(`  - ${name}`);
    }
  }

  // Check parameter accuracy
  let paramMismatches = 0;
  for (const tool of allTools) {
    for (const param of tool.required) {
      // Look for the param near ANY occurrence of the tool name in instructions
      let foundParam = false;
      let searchFrom = 0;
      while (true) {
        const idx = instructions.indexOf(tool.name, searchFrom);
        if (idx === -1) break;
        const toolSection = instructions.substring(idx, idx + 500);
        if (toolSection.includes(param)) {
          foundParam = true;
          break;
        }
        searchFrom = idx + 1;
      }
      if (!foundParam) {
        console.log(`[WARN] ${tool.name}: required param "${param}" not found near tool in instructions`);
        paramMismatches++;
      }
    }
  }

  if (paramMismatches === 0) {
    console.log('[OK] All required parameters match instructions');
  }

  return { found: found.length, missing: missing.length, paramMismatches };
}

// --- Main ---

const mode = process.argv[2] || '--markdown';
const toolsDir = resolve(__dirname, '../src/tools');

const moduleTools = [];
const allTools = [];

for (const mod of TOOL_MODULES) {
  const filePath = resolve(toolsDir, mod.file);
  try {
    const tools = extractToolsFromSource(filePath);
    moduleTools.push({ ...mod, tools });
    allTools.push(...tools);
  } catch (err) {
    console.error(`[WARN] Could not parse ${mod.file}: ${err.message}`);
    moduleTools.push({ ...mod, tools: [] });
  }
}

// Also scan extra sources (utility tools in UnifiedMCPServer.js, etc.)
for (const mod of EXTRA_SOURCES) {
  const filePath = resolve(__dirname, mod.file);
  try {
    const tools = extractToolsFromSource(filePath);
    moduleTools.push({ ...mod, tools });
    allTools.push(...tools);
  } catch (err) {
    console.error(`[WARN] Could not parse ${mod.file}: ${err.message}`);
    moduleTools.push({ ...mod, tools: [] });
  }
}

if (mode === '--json') {
  console.log(JSON.stringify(moduleTools, null, 2));
} else if (mode === '--check') {
  checkAgainstInstructions(allTools);
} else {
  // Default: markdown output
  console.log(generateFullReference(moduleTools));
  console.log('---\n');
  console.log(generateQuickReference(allTools));
}
