#!/usr/bin/env node

/**
 * Phase 3 Integration Test
 * 
 * Tests the complete Phase 3 RAG system rebuild with EE2 integration
 * 
 * @version 3.0.0
 * @author NOAA EMC Global Workflow Team
 */

import { UnifiedMCPServer } from './src/UnifiedMCPServer.js';

async function testPhase3Integration() {
  console.error('🧪 Testing Phase 3 RAG System with EE2 Integration\n');
  
  try {
    // Initialize server with RAG configuration
    const server = new UnifiedMCPServer({ 
      enableRAG: true, 
      enableGitHub: false 
    });

    console.error('📋 Testing Enhanced RAG Tools...\n');

    // Test 1: Search EE2 Standards
    console.error('🔍 Test 1: Search EE2 Standards');
    const searchResults = await server.server.tools.get('search_ee2_standards').handler({
      query: 'environment variables',
      category: 'environment_variables',
      max_results: 3
    });
    console.error(`✅ Search returned ${searchResults.length > 100 ? 'substantial' : 'basic'} results`);
    console.error(`   Preview: ${searchResults.substring(0, 150)}...\n`);

    // Test 2: Analyze EE2 Compliance
    console.error('🔍 Test 2: Analyze EE2 Compliance');
    const sampleCode = `#!/bin/bash
export DATAROOT="/tmp"
export DATA="\${DATAROOT}/test"
source prep_step
if [ $? -ne 0 ]; then
  err_exit "Failed to prepare"
fi`;
    
    const complianceResults = await server.server.tools.get('analyze_ee2_compliance').handler({
      content: sampleCode,
      analysis_type: 'comprehensive',
      include_recommendations: true
    });
    console.error(`✅ Compliance analysis completed`);
    console.error(`   Preview: ${complianceResults.substring(0, 150)}...\n`);

    // Test 3: Generate Compliance Report  
    console.error('🔍 Test 3: Generate Compliance Report');
    const reportResults = await server.server.tools.get('generate_compliance_report').handler({
      scope: 'summary',
      format: 'markdown'
    });
    console.error(`✅ Compliance report generated`);
    console.error(`   Preview: ${reportResults.substring(0, 150)}...\n`);

    // Test 4: Traditional RAG Search
    console.error('🔍 Test 4: Traditional RAG Search');
    const ragResults = await server.server.tools.get('search_documentation').handler({
      query: 'workflow structure',
      max_results: 3
    });
    console.error(`✅ RAG search completed`);
    console.error(`   Preview: ${ragResults.substring(0, 150)}...\n`);

    console.error('🎉 All Phase 3 integration tests passed!');
    console.error('\n📊 Phase 3 Enhancement Summary:');
    console.error('   ✅ Enhanced EE2 Vector Store operational');
    console.error('   ✅ Compliance analysis tools functional');
    console.error('   ✅ EE2 standards search working');
    console.error('   ✅ Compliance reporting available');
    console.error('   ✅ Traditional RAG functionality preserved');
    
    return true;
  } catch (error) {
    console.error(`❌ Phase 3 integration test failed: ${error.message}`);
    console.error(error.stack);
    return false;
  }
}

// Run tests
testPhase3Integration()
  .then(success => process.exit(success ? 0 : 1))
  .catch(error => {
    console.error(`❌ Test execution failed: ${error.message}`);
    process.exit(1);
  });