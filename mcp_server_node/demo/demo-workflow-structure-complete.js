#!/usr/bin/env node

/**
 * Comprehensive demo for get_workflow_structure tool
 * Shows the actual implementation and responses
 */

// Simulate the actual getWorkflowStructure function
async function getWorkflowStructure(component) {
  const structure = {
    overview: `
Global Workflow - NOAA's Operational Weather Prediction System

Key Components:
- Jobs: Batch job scripts for various workflow tasks
- Scripts: Shell scripts that implement job functionality
- USH: Utility shell scripts and common functions
- Parm: Parameter files and configuration templates
- Fix: Fixed input data files and tables
- Sorc: Source code for models and utilities
- Modulefiles: Environment modules for different systems

Workflow Management:
- Uses Rocoto XML workflow engine
- Supports multiple HPC systems (Hera, Orion, WCOSS2, etc.)
- Runs GFS, GDAS, and GEFS forecast systems
`,
    jobs: `
Job Scripts (jobs/ directory):
- JGDAS_* : GDAS (Global Data Assimilation System) jobs
- JGFS_* : GFS (Global Forecast System) jobs
- JGEFS_* : GEFS (Global Ensemble Forecast System) jobs
- Each job sets up environment and calls corresponding script
`,
    scripts: `
Scripts (scripts/ directory):
- exgdas_* : GDAS execution scripts
- exgfs_* : GFS execution scripts
- Implement the actual workflow logic called by jobs
`,
    configs: `
Configuration Files (parm/ directory):
- config/ : System-specific configuration files
- globus/ : Globus data transfer configurations
- product/ : Product generation parameters
- wave/ : Wave model configurations
`
  };

  const content = component && structure[component]
    ? structure[component]
    : structure.overview;

  return {
    content: [
      {
        type: 'text',
        text: content.trim()
      }
    ]
  };
}

async function demonstrateGetWorkflowStructure() {
  console.log("🔧 Demonstrating get_workflow_structure tool\n");
  console.log("=".repeat(60));
  
  // Test cases
  const testCases = [
    { name: "General Overview (default)", component: null },
    { name: "Jobs Component", component: "jobs" },
    { name: "Scripts Component", component: "scripts" },
    { name: "Configs Component", component: "configs" },
    { name: "Invalid Component", component: "invalid" }
  ];

  for (const testCase of testCases) {
    console.log(`\n📋 Test Case: ${testCase.name}`);
    console.log(`🔧 Parameters: component = ${testCase.component || 'undefined'}`);
    console.log("─".repeat(40));
    
    try {
      const result = await getWorkflowStructure(testCase.component);
      console.log("✅ Response:");
      console.log(result.content[0].text);
    } catch (error) {
      console.log("❌ Error:", error.message);
    }
    
    console.log("=".repeat(60));
  }

  console.log("\n🎯 Tool Summary:");
  console.log("- Purpose: Provides system architecture overview");
  console.log("- Parameters: component (optional) - 'jobs', 'scripts', 'configs', 'overview'");
  console.log("- Default: Returns general overview when no component specified");
  console.log("- Invalid components: Fall back to overview");
  console.log("- Use cases: Understanding system structure, component relationships");
}

// Run the demonstration
demonstrateGetWorkflowStructure().catch(console.error);
