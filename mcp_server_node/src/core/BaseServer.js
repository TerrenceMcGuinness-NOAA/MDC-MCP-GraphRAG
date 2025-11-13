#!/usr/bin/env node

/**
 * Base MCP Server for Global Workflow
 * 
 * Provides core MCP server functionality with clean separation of concerns.
 * This is the foundation that other specialized servers extend.
 * 
 * @version 2.0.0
 * @author NOAA EMC Global Workflow Team
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from '@modelcontextprotocol/sdk/types.js';

export class BaseServer {
  constructor(name, version, capabilities = {}) {
    this.serverName = name;
    this.serverVersion = version;
    this.tools = new Map();
    this.server = new Server(
      {
        name: this.serverName,
        version: this.serverVersion,
      },
      {
        capabilities: {
          tools: {},
          ...capabilities
        },
      }
    );
    
    this.setupBaseHandlers();
  }

  /**
   * Register a tool with the server
   */
  registerTool(name, description, inputSchema, handler) {
    this.tools.set(name, {
      name,
      description,
      inputSchema,
      handler
    });
  }

  /**
   * Setup base MCP handlers
   */
  setupBaseHandlers() {
    // List tools handler
    this.server.setRequestHandler(ListToolsRequestSchema, async () => {
      const toolList = Array.from(this.tools.values()).map(tool => ({
        name: tool.name,
        description: tool.description,
        inputSchema: tool.inputSchema
      }));
      
      return { tools: toolList };
    });

    // Call tool handler
    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;
      
      if (!this.tools.has(name)) {
        throw new McpError(
          ErrorCode.MethodNotFound,
          `Tool not found: ${name}`
        );
      }

      try {
        const tool = this.tools.get(name);
        const result = await tool.handler(args);
        
        // Check if result is already in MCP format (has 'content' array)
        if (result && typeof result === 'object' && Array.isArray(result.content)) {
          return result;
        }
        
        // Otherwise wrap string result in MCP format
        return {
          content: [
            {
              type: 'text',
              text: typeof result === 'string' ? result : JSON.stringify(result)
            }
          ]
        };
      } catch (error) {
        throw new McpError(
          ErrorCode.InternalError,
          `Tool execution failed: ${error.message}`
        );
      }
    });
  }

  /**
   * Start the server with stdio transport
   */
  async start() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    
    console.error(`[START] ${this.serverName} v${this.serverVersion} started`);
    console.error(`[INFO] Registered ${this.tools.size} tools`);
  }

  /**
   * Get server stats
   */
  getStats() {
    return {
      name: this.serverName,
      version: this.serverVersion,
      toolCount: this.tools.size,
      tools: Array.from(this.tools.keys())
    };
  }
}