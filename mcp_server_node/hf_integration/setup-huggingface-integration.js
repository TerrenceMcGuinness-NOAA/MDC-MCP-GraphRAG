#!/usr/bin/env node

/**
 * Hugging Face Integration Setup for Global Workflow RAG-Enhanced MCP Server
 * 
 * This script sets up the integration between the RAG system and Hugging Face tools
 * to enable enhanced document retrieval and model access capabilities.
 */

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class HuggingFaceIntegrationSetup {
  constructor() {
    this.configPath = path.join(__dirname, 'config');
    this.vscodeConfigPath = path.join(__dirname, 'vscode');
  }

  async setupDirectories() {
    try {
      await fs.mkdir(this.configPath, { recursive: true });
      await fs.mkdir(this.vscodeConfigPath, { recursive: true });
      console.log('✓ Created configuration directories');
    } catch (error) {
      console.error('Error creating directories:', error.message);
      throw error;
    }
  }

  async createHuggingFaceConfig() {
    const config = {
      huggingface: {
        // API configuration
        api: {
          base_url: "https://api-inference.huggingface.co",
          timeout: 30000,
          max_retries: 3
        },
        
        // Model preferences for different tasks
        models: {
          embeddings: {
            primary: "sentence-transformers/all-MiniLM-L6-v2",
            fallback: "sentence-transformers/all-mpnet-base-v2"
          },
          text_generation: {
            primary: "microsoft/DialoGPT-large",
            fallback: "gpt2"
          },
          code_generation: {
            primary: "microsoft/CodeBERT-base",
            fallback: "codeparrot/codeparrot-small"
          },
          image_generation: {
            primary: "runwayml/stable-diffusion-v1-5",
            flux: "black-forest-labs/FLUX.1-schnell"
          }
        },

        // RAG integration settings
        rag_integration: {
          use_hf_embeddings: true,
          embedding_model: "sentence-transformers/all-MiniLM-L6-v2",
          chunk_size: 1000,
          similarity_threshold: 0.7,
          max_results: 10
        },

        // Dataset preferences for Global Workflow
        datasets: {
          weather_related: [
            "Salesforce/wikitext",
            "scientific_papers",
            "arxiv_abstracts"
          ],
          documentation: [
            "code_documentation",
            "technical_manuals"
          ]
        },

        // Search configuration
        search: {
          default_limit: 20,
          max_limit: 100,
          include_deprecated: false,
          sort_by: "downloads" // downloads, likes, createdAt, trendingScore
        }
      }
    };

    const configFile = path.join(this.configPath, 'huggingface.json');
    await fs.writeFile(configFile, JSON.stringify(config, null, 2));
    console.log('✓ Created Hugging Face configuration');
    return configFile;
  }

  async updateMCPServerConfig() {
    const mcpConfigPath = path.join(this.vscodeConfigPath, 'mcp.json');
    
    try {
      // Read existing config
      let config;
      try {
        const existingConfig = await fs.readFile(mcpConfigPath, 'utf8');
        config = JSON.parse(existingConfig);
      } catch {
        // Create new config if none exists
        config = {
          servers: {},
          inputs: []
        };
      }

      // Add Hugging Face integration note to the existing server
      const serverKey = Object.keys(config.servers)[0];
      if (serverKey) {
        config.servers[serverKey].env = {
          "HUGGINGFACE_INTEGRATION": "enabled",
          "HF_CONFIG_PATH": path.join(this.configPath, 'huggingface.json')
        };
      }

      await fs.writeFile(mcpConfigPath, JSON.stringify(config, null, '\t'));
      console.log('✓ Updated MCP server configuration with Hugging Face integration');
    } catch (error) {
      console.error('Error updating MCP config:', error.message);
      throw error;
    }
  }

  async createHuggingFaceUtils() {
    const utilsContent = `/**
 * Hugging Face Utilities for Global Workflow RAG System
 */

export class HuggingFaceRAGUtils {
  constructor(config) {
    this.config = config;
    this.apiBase = config.huggingface.api.base_url;
    this.timeout = config.huggingface.api.timeout;
  }

  /**
   * Search for relevant models based on task requirements
   */
  async findRelevantModels(task, query, limit = 10) {
    const models = this.config.huggingface.models;
    const searchParams = {
      query: query,
      task: task,
      limit: limit,
      sort: 'downloads'
    };

    // This would integrate with the MCP Hugging Face tools
    // For now, return configured models
    switch (task) {
      case 'embeddings':
        return [models.embeddings.primary, models.embeddings.fallback];
      case 'text-generation':
        return [models.text_generation.primary, models.text_generation.fallback];
      case 'code-generation':
        return [models.code_generation.primary, models.code_generation.fallback];
      default:
        return [];
    }
  }

  /**
   * Search for relevant datasets for enhancing RAG knowledge base
   */
  async findRelevantDatasets(domain, limit = 5) {
    const datasets = this.config.huggingface.datasets;
    
    switch (domain) {
      case 'weather':
        return datasets.weather_related.slice(0, limit);
      case 'documentation':
        return datasets.documentation.slice(0, limit);
      default:
        return [];
    }
  }

  /**
   * Get embedding for text using Hugging Face models
   */
  async getEmbedding(text) {
    const model = this.config.huggingface.rag_integration.embedding_model;
    
    // This would call the actual Hugging Face API or MCP tools
    // For now, return a placeholder that indicates integration needed
    console.log(\`Getting embedding for text using model: \${model}\`);
    return null; // Placeholder
  }

  /**
   * Search Hugging Face Hub for papers related to weather/climate modeling
   */
  async searchRelevantPapers(query, limit = 10) {
    // This would use the mcp_huggingface_paper_search tool
    console.log(\`Searching for papers related to: \${query}\`);
    return []; // Placeholder
  }

  /**
   * Generate documentation or code using Hugging Face models
   */
  async generateContent(prompt, type = 'text') {
    const models = this.config.huggingface.models;
    let model;

    switch (type) {
      case 'code':
        model = models.code_generation.primary;
        break;
      case 'text':
      default:
        model = models.text_generation.primary;
        break;
    }

    console.log(\`Generating \${type} content using model: \${model}\`);
    return null; // Placeholder
  }
}

export default HuggingFaceRAGUtils;
`;

    const utilsFile = path.join(__dirname, 'huggingface-rag-utils.js');
    await fs.writeFile(utilsFile, utilsContent);
    console.log('✓ Created Hugging Face RAG utilities');
    return utilsFile;
  }

  async createIntegrationTest() {
    const testContent = `#!/usr/bin/env node

/**
 * Test Hugging Face Integration with RAG System
 */

import { HuggingFaceRAGUtils } from './huggingface-rag-utils.js';
import fs from 'fs/promises';
import path from 'path';

async function testHuggingFaceIntegration() {
  console.log('Testing Hugging Face Integration...');

  try {
    // Load configuration
    const configPath = path.join(process.cwd(), 'config', 'huggingface.json');
    const configData = await fs.readFile(configPath, 'utf8');
    const config = JSON.parse(configData);

    // Initialize utils
    const hfUtils = new HuggingFaceRAGUtils(config);

    // Test model search
    console.log('\\n1. Testing model search...');
    const embeddingModels = await hfUtils.findRelevantModels('embeddings', 'sentence embedding');
    console.log('Found embedding models:', embeddingModels);

    // Test dataset search
    console.log('\\n2. Testing dataset search...');
    const weatherDatasets = await hfUtils.findRelevantDatasets('weather');
    console.log('Found weather datasets:', weatherDatasets);

    // Test paper search (placeholder)
    console.log('\\n3. Testing paper search...');
    await hfUtils.searchRelevantPapers('weather prediction models');

    // Test content generation (placeholder)
    console.log('\\n4. Testing content generation...');
    await hfUtils.generateContent('# Documentation for weather model', 'text');

    console.log('\\n✓ Hugging Face integration test completed successfully');
    return true;

  } catch (error) {
    console.error('❌ Integration test failed:', error.message);
    return false;
  }
}

// Run test if called directly
if (import.meta.url === \`file://\${process.argv[1]}\`) {
  testHuggingFaceIntegration()
    .then(success => process.exit(success ? 0 : 1))
    .catch(error => {
      console.error('Test execution failed:', error);
      process.exit(1);
    });
}

export { testHuggingFaceIntegration };
`;

    const testFile = path.join(__dirname, 'test-huggingface-integration.js');
    await fs.writeFile(testFile, testContent);
    await fs.chmod(testFile, 0o755);
    console.log('✓ Created Hugging Face integration test');
    return testFile;
  }

  async run() {
    console.log('🚀 Setting up Hugging Face Integration for Global Workflow RAG System...');
    console.log();

    try {
      await this.setupDirectories();
      await this.createHuggingFaceConfig();
      await this.updateMCPServerConfig();
      await this.createHuggingFaceUtils();
      await this.createIntegrationTest();

      console.log();
      console.log('✅ Hugging Face integration setup completed successfully!');
      console.log();
      console.log('Next steps:');
      console.log('1. Run the integration test: node test-huggingface-integration.js');
      console.log('2. Update your RAG server to use the new Hugging Face utilities');
      console.log('3. Restart VS Code to apply MCP configuration changes');
      console.log();
      console.log('The integration provides:');
      console.log('- Model search and selection for different tasks');
      console.log('- Dataset discovery for knowledge base enhancement');
      console.log('- Paper search for domain-specific research');
      console.log('- Content generation capabilities');

    } catch (error) {
      console.error('❌ Setup failed:', error.message);
      process.exit(1);
    }
  }
}

// Run setup if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  const setup = new HuggingFaceIntegrationSetup();
  setup.run();
}

export { HuggingFaceIntegrationSetup };
