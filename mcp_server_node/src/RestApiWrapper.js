/**
 * REST API Wrapper for MCP Tools
 * 
 * Exposes MCP tools as simple HTTP endpoints for integration with
 * workflow tools like n8n that don't support the MCP protocol natively.
 * 
 * Usage:
 *   node src/RestApiWrapper.js
 *   
 * Endpoints:
 *   GET  /health          - Health check
 *   GET  /tools           - List available tools
 *   POST /tools/:toolName - Execute a tool
 */

import express from 'express';
import cors from 'cors';

// Import tool modules
import { WorkflowInfoTools } from './tools/WorkflowInfoTools.js';
import { SemanticSearchTools } from './tools/SemanticSearchTools.js';
import { EE2ComplianceTools } from './tools/EE2ComplianceTools.js';
import { CodeAnalysisTools } from './tools/CodeAnalysisTools.js';
import { SDDWorkflowTools } from './tools/SDDWorkflowTools.js';
import { OperationalTools } from './tools/OperationalTools.js';
import { GitHubTools } from './tools/GitHubTools.js';

const app = express();
const PORT = process.env.REST_API_PORT || 3001;

// Middleware
app.use(cors());
app.use(express.json());

// Simple bearer token auth
const AUTH_TOKEN = process.env.MCP_REST_TOKEN || 'eib-mcp-rest-2025';

function authMiddleware(req, res, next) {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Missing or invalid authorization header' });
  }
  const token = authHeader.split(' ')[1];
  if (token !== AUTH_TOKEN) {
    return res.status(403).json({ error: 'Invalid token' });
  }
  next();
}

// Initialize tool modules
const toolModules = {};

async function initializeTools() {
  console.log('[REST] Initializing tool modules...');
  
  try {
    toolModules.workflow = new WorkflowInfoTools();
    await toolModules.workflow.initialize?.();
    console.log('[REST] WorkflowInfoTools loaded');
  } catch (e) {
    console.log('[REST] WorkflowInfoTools skipped:', e.message);
  }
  
  try {
    toolModules.semantic = new SemanticSearchTools();
    await toolModules.semantic.initialize?.();
    console.log('[REST] SemanticSearchTools loaded');
  } catch (e) {
    console.log('[REST] SemanticSearchTools skipped:', e.message);
  }
  
  try {
    toolModules.ee2 = new EE2ComplianceTools();
    await toolModules.ee2.initialize?.();
    console.log('[REST] EE2ComplianceTools loaded');
  } catch (e) {
    console.log('[REST] EE2ComplianceTools skipped:', e.message);
  }
  
  try {
    toolModules.code = new CodeAnalysisTools();
    await toolModules.code.initialize?.();
    console.log('[REST] CodeAnalysisTools loaded');
  } catch (e) {
    console.log('[REST] CodeAnalysisTools skipped:', e.message);
  }
  
  try {
    toolModules.sdd = new SDDWorkflowTools();
    await toolModules.sdd.initialize?.();
    console.log('[REST] SDDWorkflowTools loaded');
  } catch (e) {
    console.log('[REST] SDDWorkflowTools skipped:', e.message);
  }
  
  try {
    toolModules.ops = new OperationalTools();
    await toolModules.ops.initialize?.();
    console.log('[REST] OperationalTools loaded');
  } catch (e) {
    console.log('[REST] OperationalTools skipped:', e.message);
  }
  
  try {
    toolModules.github = new GitHubTools();
    await toolModules.github.initialize?.();
    console.log('[REST] GitHubTools loaded');
  } catch (e) {
    console.log('[REST] GitHubTools skipped:', e.message);
  }
  
  console.log('[REST] Tool initialization complete');
}

// Build tool registry
function getToolRegistry() {
  const tools = {};
  
  for (const [moduleName, module] of Object.entries(toolModules)) {
    if (module && module.tools) {
      for (const tool of module.tools) {
        tools[tool.name] = {
          module: moduleName,
          definition: tool,
          handler: module
        };
      }
    }
  }
  
  return tools;
}

// Routes

// Health check
app.get('/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    service: 'MCP REST API Wrapper',
    timestamp: new Date().toISOString()
  });
});

// List tools (no auth required)
app.get('/tools', (req, res) => {
  const registry = getToolRegistry();
  const tools = Object.entries(registry).map(([name, info]) => ({
    name,
    description: info.definition.description,
    inputSchema: info.definition.inputSchema
  }));
  res.json({ tools, count: tools.length });
});

// Execute tool (auth required)
app.post('/tools/:toolName', authMiddleware, async (req, res) => {
  const { toolName } = req.params;
  const args = req.body || {};
  
  const registry = getToolRegistry();
  const toolInfo = registry[toolName];
  
  if (!toolInfo) {
    return res.status(404).json({ 
      error: `Tool '${toolName}' not found`,
      availableTools: Object.keys(registry)
    });
  }
  
  try {
    console.log(`[REST] Executing tool: ${toolName}`);
    console.log(`[REST] Arguments:`, JSON.stringify(args));
    
    // Find and execute the handler
    const handler = toolInfo.handler;
    const handlerMethod = handler[toolName] || handler.handleToolCall;
    
    let result;
    if (typeof handlerMethod === 'function') {
      result = await handlerMethod.call(handler, args);
    } else if (typeof handler.handleToolCall === 'function') {
      result = await handler.handleToolCall(toolName, args);
    } else {
      throw new Error(`No handler found for tool: ${toolName}`);
    }
    
    console.log(`[REST] Tool ${toolName} completed successfully`);
    res.json({ 
      success: true, 
      tool: toolName,
      result 
    });
    
  } catch (error) {
    console.error(`[REST] Tool ${toolName} error:`, error.message);
    res.status(500).json({ 
      success: false,
      tool: toolName,
      error: error.message 
    });
  }
});

// Start server
async function start() {
  await initializeTools();
  
  app.listen(PORT, '0.0.0.0', () => {
    console.log(`[REST] MCP REST API Wrapper running on http://0.0.0.0:${PORT}`);
    console.log(`[REST] Auth token: ${AUTH_TOKEN}`);
    console.log('[REST] Endpoints:');
    console.log('  GET  /health       - Health check');
    console.log('  GET  /tools        - List available tools');
    console.log('  POST /tools/:name  - Execute a tool (requires auth)');
  });
}

start().catch(console.error);
