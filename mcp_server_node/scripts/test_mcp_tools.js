#!/usr/bin/env node
/**
 * MCP Tools Test Script
 * Tests basic functionality of MCP tools before documentation ingestion
 */

const { spawn } = require('child_process');
const path = require('path');

const MCP_SERVER = path.join(__dirname, '../mcp_server_node/src/UnifiedMCPServer.js');
const TEST_TIMEOUT = 30000; // 30 seconds

// Test cases
const TESTS = [
    {
        name: 'get_workflow_structure',
        tool: 'get_workflow_structure',
        args: {},
        expected: 'jobs'  // Should mention jobs directory
    },
    {
        name: 'list_job_scripts',
        tool: 'list_job_scripts',
        args: { category: 'all', format: 'summary' },
        expected: 'JGLOBAL'  // Should list some job scripts
    },
    {
        name: 'get_system_configs',
        tool: 'get_system_configs',
        args: { platform: 'hera', config_type: 'all' },
        expected: 'hera'  // Should mention HERA
    }
];

async function testMCPServer() {
    console.log('='.