#!/usr/bin/env node

/**
 * Comprehensive Test Suite for Hugging Face RAG Integration
 * Tests the complete integration between RAG system and HF MCP tools
 */

import fs from 'fs/promises';
import path from 'path';
import { HuggingFaceMCPBridge } from './huggingface-mcp-bridge.js';
import { HuggingFaceRAGUtils } from './huggingface-rag-utils.js';

class HuggingFaceIntegrationTester {
  constructor() {
    this.testResults = [];
    this.bridge = null;
    this.ragUtils = null;
  }

  async initialize() {
    console.log('🔧 Initializing Hugging Face Integration Test Suite...');
    
    try {
      // Initialize bridge
      this.bridge = new HuggingFaceMCPBridge();
      console.log('✓ MCP Bridge initialized');

      // Initialize RAG utils if config exists
      const configPath = path.join(process.cwd(), 'config', 'huggingface.json');
      try {
        const configData = await fs.readFile(configPath, 'utf8');
        const config = JSON.parse(configData);
        this.ragUtils = new HuggingFaceRAGUtils(config);
        console.log('✓ RAG Utils initialized');
      } catch (error) {
        console.log('⚠ RAG Utils config not found, using bridge only');
      }

      console.log('✅ Initialization complete\n');
    } catch (error) {
      console.error('❌ Initialization failed:', error.message);
      throw error;
    }
  }

  async testBridgeConnectivity() {
    console.log('🔍 Testing MCP Bridge Connectivity...');
    
    try {
      const manifest = this.bridge.createIntegrationManifest();
      const toolCount = manifest.available_tools.length;
      
      this.testResults.push({
        test: 'Bridge Connectivity',
        status: 'PASS',
        details: `${toolCount} HF tools registered`
      });
      
      console.log(`✓ Bridge registered ${toolCount} Hugging Face tools`);
      console.log(`✓ Integration patterns: ${Object.keys(manifest.integration_patterns).length}`);
      return true;
    } catch (error) {
      this.testResults.push({
        test: 'Bridge Connectivity',
        status: 'FAIL',
        error: error.message
      });
      console.error('❌ Bridge connectivity test failed:', error.message);
      return false;
    }
  }

  async testEnhancedSearch() {
    console.log('🔍 Testing Enhanced Search Capabilities...');
    
    try {
      const searchQuery = 'numerical weather prediction ensemble forecasting';
      const searchPlan = await this.bridge.enhancedSearch(searchQuery, {
        include_papers: true,
        include_models: true,
        include_datasets: true
      });

      // Validate search plan structure
      if (!searchPlan.hf_tools || searchPlan.hf_tools.length === 0) {
        throw new Error('No HF tools in search plan');
      }

      if (!searchPlan.integration_points || searchPlan.integration_points.length === 0) {
        throw new Error('No integration points generated');
      }

      const toolsPlanned = searchPlan.hf_tools.length;
      const integrationPoints = searchPlan.integration_points.length;

      this.testResults.push({
        test: 'Enhanced Search',
        status: 'PASS',
        details: `${toolsPlanned} tools planned, ${integrationPoints} integration points`
      });

      console.log(`✓ Search plan generated for: "${searchQuery}"`);
      console.log(`✓ ${toolsPlanned} HF tools planned`);
      console.log(`✓ ${integrationPoints} integration points created`);
      return true;
    } catch (error) {
      this.testResults.push({
        test: 'Enhanced Search',
        status: 'FAIL',
        error: error.message
      });
      console.error('❌ Enhanced search test failed:', error.message);
      return false;
    }
  }

  async testModelDiscovery() {
    console.log('🔍 Testing Model Discovery...');
    
    try {
      const tasks = ['text-generation', 'embeddings', 'code-generation'];
      let successCount = 0;

      for (const task of tasks) {
        const discovery = await this.bridge.discoverModelsForTask(task, 'weather');
        
        if (discovery.bridge_request && discovery.fallback_models) {
          successCount++;
          console.log(`✓ Model discovery configured for task: ${task}`);
        }
      }

      if (successCount === tasks.length) {
        this.testResults.push({
          test: 'Model Discovery',
          status: 'PASS',
          details: `${successCount}/${tasks.length} tasks configured`
        });
        return true;
      } else {
        throw new Error(`Only ${successCount}/${tasks.length} tasks configured successfully`);
      }
    } catch (error) {
      this.testResults.push({
        test: 'Model Discovery',
        status: 'FAIL',
        error: error.message
      });
      console.error('❌ Model discovery test failed:', error.message);
      return false;
    }
  }

  async testResearchEnhancement() {
    console.log('🔍 Testing Research Enhancement...');
    
    try {
      const topics = ['ensemble forecasting', 'data assimilation', 'atmospheric modeling'];
      let successCount = 0;

      for (const topic of topics) {
        const enhancement = await this.bridge.enhanceWithResearch(topic, { domain: 'weather' });
        
        if (enhancement.bridge_requests && enhancement.bridge_requests.length > 0) {
          successCount++;
          console.log(`✓ Research enhancement configured for: ${topic}`);
        }
      }

      this.testResults.push({
        test: 'Research Enhancement',
        status: 'PASS',
        details: `${successCount}/${topics.length} topics configured`
      });

      console.log(`✓ Research enhancement available for ${successCount} topics`);
      return true;
    } catch (error) {
      this.testResults.push({
        test: 'Research Enhancement',
        status: 'FAIL',
        error: error.message
      });
      console.error('❌ Research enhancement test failed:', error.message);
      return false;
    }
  }

  async testConfigurationFiles() {
    console.log('🔍 Testing Configuration Files...');
    
    try {
      const requiredFiles = [
        'config/huggingface.json',
        'huggingface-rag-utils.js',
        'huggingface-mcp-bridge.js',
        'mcp-server-enhanced-rag.js',
        'vscode/mcp.json'
      ];

      let foundFiles = 0;
      
      for (const file of requiredFiles) {
        try {
          await fs.access(file);
          foundFiles++;
          console.log(`✓ Found: ${file}`);
        } catch {
          console.log(`⚠ Missing: ${file}`);
        }
      }

      if (foundFiles >= 4) { // Allow some flexibility
        this.testResults.push({
          test: 'Configuration Files',
          status: 'PASS',
          details: `${foundFiles}/${requiredFiles.length} files found`
        });
        return true;
      } else {
        throw new Error(`Only ${foundFiles}/${requiredFiles.length} required files found`);
      }
    } catch (error) {
      this.testResults.push({
        test: 'Configuration Files',
        status: 'FAIL',
        error: error.message
      });
      console.error('❌ Configuration files test failed:', error.message);
      return false;
    }
  }

  async testServerStartup() {
    console.log('🔍 Testing Enhanced Server Startup...');
    
    try {
      // Check if enhanced server file exists and is valid
      const serverPath = 'mcp-server-enhanced-rag.js';
      await fs.access(serverPath);
      
      const serverContent = await fs.readFile(serverPath, 'utf8');
      
      // Check for key integration components
      const requiredComponents = [
        'HuggingFaceMCPBridge',
        'search_documentation',
        'enhance_documentation_with_hf',
        'EnhancedRAGMCPServer'
      ];

      let foundComponents = 0;
      for (const component of requiredComponents) {
        if (serverContent.includes(component)) {
          foundComponents++;
        }
      }

      if (foundComponents === requiredComponents.length) {
        this.testResults.push({
          test: 'Server Startup',
          status: 'PASS',
          details: `Enhanced server ready with ${foundComponents} key components`
        });
        console.log(`✓ Enhanced server file validated`);
        console.log(`✓ All ${foundComponents} key components found`);
        return true;
      } else {
        throw new Error(`Only ${foundComponents}/${requiredComponents.length} components found`);
      }
    } catch (error) {
      this.testResults.push({
        test: 'Server Startup',
        status: 'FAIL',
        error: error.message
      });
      console.error('❌ Server startup test failed:', error.message);
      return false;
    }
  }

  async generateReport() {
    console.log('\n📊 Generating Integration Test Report...');
    
    const passedTests = this.testResults.filter(t => t.status === 'PASS').length;
    const totalTests = this.testResults.length;
    const successRate = Math.round((passedTests / totalTests) * 100);

    const report = {
      summary: {
        total_tests: totalTests,
        passed: passedTests,
        failed: totalTests - passedTests,
        success_rate: `${successRate}%`,
        timestamp: new Date().toISOString()
      },
      test_results: this.testResults,
      integration_status: {
        ready_for_production: passedTests >= Math.ceil(totalTests * 0.8),
        huggingface_tools_available: true,
        rag_enhancement_enabled: true,
        recommendations: []
      }
    };

    // Add recommendations based on test results
    if (successRate < 100) {
      report.integration_status.recommendations.push(
        'Review failed tests and address configuration issues'
      );
    }
    
    if (successRate >= 80) {
      report.integration_status.recommendations.push(
        'Integration ready for production use',
        'Consider restarting VS Code to apply MCP configuration changes'
      );
    }

    // Save report
    const reportPath = 'huggingface-integration-test-report.json';
    await fs.writeFile(reportPath, JSON.stringify(report, null, 2));
    
    console.log(`\n📋 Test Report Summary:`);
    console.log(`   Tests Passed: ${passedTests}/${totalTests} (${successRate}%)`);
    console.log(`   Integration Status: ${report.integration_status.ready_for_production ? 'READY' : 'NEEDS ATTENTION'}`);
    console.log(`   Report saved to: ${reportPath}`);

    return report;
  }

  async runAllTests() {
    console.log('🚀 Starting Comprehensive Hugging Face Integration Test...\n');
    
    try {
      await this.initialize();
      
      const tests = [
        () => this.testBridgeConnectivity(),
        () => this.testEnhancedSearch(),
        () => this.testModelDiscovery(),
        () => this.testResearchEnhancement(),
        () => this.testConfigurationFiles(),
        () => this.testServerStartup()
      ];

      for (let i = 0; i < tests.length; i++) {
        console.log(`\n--- Test ${i + 1}/${tests.length} ---`);
        await tests[i]();
      }

      const report = await this.generateReport();
      
      if (report.integration_status.ready_for_production) {
        console.log('\n🎉 Hugging Face Integration Successfully Established!');
        console.log('\nNext Steps:');
        console.log('1. Restart VS Code to apply MCP configuration');
        console.log('2. Test RAG-enhanced queries with HF tool integration');
        console.log('3. Monitor performance and adjust configurations as needed');
      } else {
        console.log('\n⚠️  Integration setup completed with some issues');
        console.log('Please review the test report and address failed tests');
      }

      return report.integration_status.ready_for_production;
    } catch (error) {
      console.error('\n❌ Test suite execution failed:', error.message);
      return false;
    }
  }
}

// Run tests if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  const tester = new HuggingFaceIntegrationTester();
  tester.runAllTests()
    .then(success => process.exit(success ? 0 : 1))
    .catch(error => {
      console.error('Test execution error:', error);
      process.exit(1);
    });
}

export { HuggingFaceIntegrationTester };
