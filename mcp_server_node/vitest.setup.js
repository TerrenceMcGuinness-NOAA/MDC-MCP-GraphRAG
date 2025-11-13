/**
 * vitest.setup.js - Vitest Setup File
 * 
 * Global setup for all tests
 */

import { beforeAll, afterAll } from 'vitest';

// Set test environment variables
process.env.NODE_ENV = 'test';
process.env.NEO4J_URI = process.env.NEO4J_URI || 'bolt://localhost:7687';
process.env.NEO4J_USERNAME = process.env.NEO4J_USERNAME || 'neo4j';
process.env.NEO4J_PASSWORD = process.env.NEO4J_PASSWORD || 'gfsworkflow2025';
process.env.CHROMADB_HOST = process.env.CHROMADB_HOST || '127.0.0.1';
process.env.CHROMADB_PORT = process.env.CHROMADB_PORT || '8080';

// Global setup
beforeAll(() => {
  console.log('🧪 Test Environment Setup');
  console.log('Neo4j URI:', process.env.NEO4J_URI);
  console.log('ChromaDB:', `${process.env.CHROMADB_HOST}:${process.env.CHROMADB_PORT}`);
});

// Global teardown
afterAll(() => {
  console.log('✅ Test Environment Teardown Complete');
});

// Handle unhandled promise rejections
process.on('unhandledRejection', (error) => {
  console.error('Unhandled Promise Rejection:', error);
});
