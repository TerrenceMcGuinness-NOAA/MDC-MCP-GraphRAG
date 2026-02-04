#!/usr/bin/env node

/**
 * GraphSchema - Neo4j Graph Schema Definitions
 *
 * Defines the complete graph schema for the Global Workflow knowledge graph:
 * - Node labels and properties
 * - Relationship types and properties
 * - Constraints and indexes
 * - Schema application and validation
 *
 * This schema implements the architecture from ENHANCED_INGESTION_ARCHITECTURE.md
 *
 * @version 1.0.0
 * @author NOAA EMC Global Workflow Team
 */

/**
 * Node type definitions
 */
export const NODE_TYPES = {
  // Code Structure Nodes
  Component: {
    label: 'Component',
    description: 'A repository or submodule (e.g., FV3, GSI, GDAS)',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      name: { type: 'STRING', required: true },
      path: { type: 'STRING', required: true, unique: true },
      url: { type: 'STRING', required: false },
      language: { type: 'STRING', required: false },
      description: { type: 'STRING', required: false },
      loc: { type: 'INTEGER', required: false },
      createdAt: { type: 'DATETIME', required: true },
      updatedAt: { type: 'DATETIME', required: true }
    }
  },

  Module: {
    label: 'Module',
    description: 'A code module or package (Fortran module, Python module, imported package)',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      name: { type: 'STRING', required: true },
      file: { type: 'STRING', required: false },
      language: { type: 'STRING', required: false },
      exports: { type: 'LIST', required: false },
      isExternal: { type: 'BOOLEAN', required: false }
    }
  },

  Function: {
    label: 'Function',
    description: 'A function or subroutine',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      name: { type: 'STRING', required: true },
      language: { type: 'STRING', required: true },
      lineNumber: { type: 'INTEGER', required: true },
      endLine: { type: 'INTEGER', required: false },
      parameters: { type: 'LIST', required: false },
      returnType: { type: 'STRING', required: false },
      isAsync: { type: 'BOOLEAN', required: false },
      isMethod: { type: 'BOOLEAN', required: false },
      className: { type: 'STRING', required: false },
      decorators: { type: 'LIST', required: false },
      docstring: { type: 'STRING', required: false },
      isExternal: { type: 'BOOLEAN', required: false },
      signature: { type: 'STRING', required: false },
      complexity: { type: 'INTEGER', required: false }
    }
  },

  Class: {
    label: 'Class',
    description: 'A class definition',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      name: { type: 'STRING', required: true },
      language: { type: 'STRING', required: true },
      lineNumber: { type: 'INTEGER', required: true },
      endLine: { type: 'INTEGER', required: false },
      baseClasses: { type: 'LIST', required: false },
      decorators: { type: 'LIST', required: false },
      docstring: { type: 'STRING', required: false }
    }
  },

  File: {
    label: 'File',
    description: 'A source code file',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      path: { type: 'STRING', required: true },
      absolutePath: { type: 'STRING', required: true },
      language: { type: 'STRING', required: true },
      loc: { type: 'INTEGER', required: false },
      lastUpdated: { type: 'DATETIME', required: false }
    }
  },

  // Build System Nodes
  BuildOrchestrator: {
    label: 'BuildOrchestrator',
    description: 'A build orchestration script (e.g., build_all.sh)',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      name: { type: 'STRING', required: true },
      path: { type: 'STRING', required: true },
      type: { type: 'STRING', required: true }, // parallel_orchestrator, sequential, etc.
      systemsManaged: { type: 'LIST', required: false },
      componentsManaged: { type: 'LIST', required: false },
      lastUpdated: { type: 'DATETIME', required: true }
    }
  },

  CMakeTarget: {
    label: 'CMakeTarget',
    description: 'A CMake build target',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      name: { type: 'STRING', required: true },
      type: { type: 'STRING', required: true }, // EXECUTABLE, LIBRARY, etc.
      output: { type: 'STRING', required: false },
      createdAt: { type: 'DATETIME', required: true }
    }
  },

  Executable: {
    label: 'Executable',
    description: 'A compiled executable binary',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      name: { type: 'STRING', required: true },
      type: { type: 'STRING', required: false }, // binary, script, etc.
      sourceFiles: { type: 'LIST', required: false },
      cmakeFile: { type: 'STRING', required: false },
      lastUpdated: { type: 'DATETIME', required: true }
    }
  },

  Library: {
    label: 'Library',
    description: 'A compiled library',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      name: { type: 'STRING', required: true },
      path: { type: 'STRING', required: false },
      version: { type: 'STRING', required: false },
      type: { type: 'STRING', required: false }, // STATIC, SHARED, static_or_shared
      sourceFiles: { type: 'LIST', required: false },
      cmakeFile: { type: 'STRING', required: false },
      createdAt: { type: 'DATETIME', required: true },
      lastUpdated: { type: 'DATETIME', required: false }
    }
  },

  Dependency: {
    label: 'Dependency',
    description: 'An external dependency',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      name: { type: 'STRING', required: true },
      type: { type: 'STRING', required: true }, // GIT, PACKAGE, SYSTEM
      version: { type: 'STRING', required: false },
      url: { type: 'STRING', required: false },
      createdAt: { type: 'DATETIME', required: true }
    }
  },

  // Development & Error Nodes
  Developer: {
    label: 'Developer',
    description: 'A code contributor',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      name: { type: 'STRING', required: true },
      email: { type: 'STRING', required: true, unique: true },
      expertiseAreas: { type: 'LIST', required: false },
      commitCount: { type: 'INTEGER', required: false },
      createdAt: { type: 'DATETIME', required: true }
    }
  },

  Commit: {
    label: 'Commit',
    description: 'A git commit',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      hash: { type: 'STRING', required: true, unique: true },
      message: { type: 'STRING', required: true },
      timestamp: { type: 'DATETIME', required: true },
      author: { type: 'STRING', required: true },
      createdAt: { type: 'DATETIME', required: true }
    }
  },

  Issue: {
    label: 'Issue',
    description: 'A GitHub issue',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      number: { type: 'INTEGER', required: true },
      title: { type: 'STRING', required: true },
      labels: { type: 'LIST', required: false },
      status: { type: 'STRING', required: true },
      resolution: { type: 'STRING', required: false },
      createdAt: { type: 'DATETIME', required: true },
      closedAt: { type: 'DATETIME', required: false }
    }
  },

  Error: {
    label: 'Error',
    description: 'An error occurrence',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      signature: { type: 'STRING', required: true, indexed: true },
      message: { type: 'STRING', required: true },
      severity: { type: 'STRING', required: true },
      frequency: { type: 'INTEGER', required: false },
      firstSeen: { type: 'DATETIME', required: true },
      lastSeen: { type: 'DATETIME', required: true }
    }
  },

  Fix: {
    label: 'Fix',
    description: 'A fix for an error',
    properties: {
      id: { type: 'STRING', required: true, indexed: true },
      commitHash: { type: 'STRING', required: true },
      description: { type: 'STRING', required: true },
      successRate: { type: 'FLOAT', required: false },
      applicationCount: { type: 'INTEGER', required: false },
      createdAt: { type: 'DATETIME', required: true }
    }
  }
};

/**
 * Relationship type definitions
 */
export const RELATIONSHIP_TYPES = {
  // Code Relationships
  CONTAINS: {
    type: 'CONTAINS',
    description: 'Component contains Module/File',
    properties: {}
  },

  DEPENDS_ON: {
    type: 'DEPENDS_ON',
    description: 'Component/Target depends on Component/Library',
    properties: {
      version: { type: 'STRING', required: false },
      type: { type: 'STRING', required: false }
    }
  },

  CALLS: {
    type: 'CALLS',
    description: 'Function calls another Function',
    properties: {
      lineNumber: { type: 'INTEGER', required: false },
      numArgs: { type: 'INTEGER', required: false },
      numKwargs: { type: 'INTEGER', required: false },
      callCount: { type: 'INTEGER', required: false }
    }
  },

  IMPORTS: {
    type: 'IMPORTS',
    description: 'File/Module imports another Module',
    properties: {
      type: { type: 'STRING', required: false },
      alias: { type: 'STRING', required: false },
      itemName: { type: 'STRING', required: false },
      lineNumber: { type: 'INTEGER', required: false },
      level: { type: 'INTEGER', required: false }
    }
  },

  SOURCES: {
    type: 'SOURCES',
    description: 'Shell script sources another file',
    properties: {
      type: { type: 'STRING', required: false },
      lineNumber: { type: 'INTEGER', required: false },
      callerFunction: { type: 'STRING', required: false }
    }
  },

  // v8: J-Job execution relationship
  EXECUTES: {
    type: 'EXECUTES',
    description: 'J-Job executes an ex-script',
    properties: {
      lineNumber: { type: 'INTEGER', required: false },
      callerFunction: { type: 'STRING', required: false }
    }
  },

  DEFINES: {
    type: 'DEFINES',
    description: 'File defines Function/Class',
    properties: {}
  },

  INCLUDES: {
    type: 'INCLUDES',
    description: 'File includes another File',
    properties: {}
  },

  DEFINED_IN: {
    type: 'DEFINED_IN',
    description: 'Function/Module defined in File',
    properties: {}
  },

  BELONGS_TO: {
    type: 'BELONGS_TO',
    description: 'File belongs to Component',
    properties: {}
  },

  // Build Relationships
  BUILD_ORCHESTRATES: {
    type: 'BUILD_ORCHESTRATES',
    description: 'Build orchestrator manages component build',
    properties: {
      systemName: { type: 'STRING', required: false },
      buildScript: { type: 'STRING', required: false },
      buildOptions: { type: 'STRING', required: false },
      parallelJobs: { type: 'INTEGER', required: false },
      lastUpdated: { type: 'DATETIME', required: false }
    }
  },

  BUILT_BY: {
    type: 'BUILT_BY',
    description: 'Library/Executable built by Component',
    properties: {
      lastUpdated: { type: 'DATETIME', required: false }
    }
  },

  BUILDS: {
    type: 'BUILDS',
    description: 'CMakeTarget builds Component',
    properties: {}
  },

  LINKS_TO: {
    type: 'LINKS_TO',
    description: 'Target links to Library',
    properties: {
      linkType: { type: 'STRING', required: false }
    }
  },

  REQUIRED_BY: {
    type: 'REQUIRED_BY',
    description: 'Library required by Component',
    properties: {}
  },

  // Development Relationships
  CONTRIBUTED_TO: {
    type: 'CONTRIBUTED_TO',
    description: 'Developer contributed to Component',
    properties: {
      commits: { type: 'INTEGER', required: false },
      linesChanged: { type: 'INTEGER', required: false }
    }
  },

  AUTHORED: {
    type: 'AUTHORED',
    description: 'Developer authored Commit',
    properties: {}
  },

  MODIFIES: {
    type: 'MODIFIES',
    description: 'Commit modifies File',
    properties: {
      linesAdded: { type: 'INTEGER', required: false },
      linesRemoved: { type: 'INTEGER', required: false }
    }
  },

  REPORTS: {
    type: 'REPORTS',
    description: 'Issue reports Error',
    properties: {}
  },

  FIXES: {
    type: 'FIXES',
    description: 'Commit/Fix fixes Issue/Error',
    properties: {}
  },

  // Error Relationships
  OCCURS_IN: {
    type: 'OCCURS_IN',
    description: 'Error occurs in Function/Component',
    properties: {
      count: { type: 'INTEGER', required: false }
    }
  },

  CAUSED_BY: {
    type: 'CAUSED_BY',
    description: 'Error caused by Commit',
    properties: {}
  },

  RESOLVES: {
    type: 'RESOLVES',
    description: 'Fix resolves Error',
    properties: {}
  },

  SIMILAR_TO: {
    type: 'SIMILAR_TO',
    description: 'Error similar to another Error',
    properties: {
      similarity: { type: 'FLOAT', required: false }
    }
  }
};

/**
 * Apply schema to Neo4j database
 * Creates indexes and constraints
 */
export async function applySchema(neo4jClient) {
  console.error('\n[BUILD]  Applying Graph Schema to Neo4j...\n');

  let constraintsCreated = 0;
  let indexesCreated = 0;

  // Create uniqueness constraints
  // Note: Component.name is NOT unique (e.g., rte-rrtmgp appears twice)
  // Component.path IS unique (full filesystem path)
  const uniqueConstraints = [
    { label: 'Component', property: 'path' },
    { label: 'File', property: 'path' },
    { label: 'Developer', property: 'email' },
    { label: 'Commit', property: 'hash' }
  ];

  for (const constraint of uniqueConstraints) {
    try {
      await neo4jClient.createUniqueConstraint(constraint.label, constraint.property);
      constraintsCreated++;
    } catch (error) {
      console.error(`[WARN]  Constraint ${constraint.label}.${constraint.property}: ${error.message}`);
    }
  }

  // Create indexes for commonly queried properties
  const indexes = [
    { label: 'Component', property: 'id' },
    { label: 'Module', property: 'id' },
    { label: 'Function', property: 'id' },
    { label: 'Function', property: 'name' },
    { label: 'File', property: 'id' },
    { label: 'File', property: 'language' },
    { label: 'Error', property: 'signature' },
    { label: 'Error', property: 'severity' },
    { label: 'CMakeTarget', property: 'name' },
    { label: 'Library', property: 'name' }
  ];

  for (const index of indexes) {
    try {
      await neo4jClient.createIndex(index.label, index.property);
      indexesCreated++;
    } catch (error) {
      console.error(`[WARN]  Index ${index.label}.${index.property}: ${error.message}`);
    }
  }

  console.error(`\n[OK] Schema Applied:`);
  console.error(`   Constraints: ${constraintsCreated}`);
  console.error(`   Indexes: ${indexesCreated}`);
  console.error(`   Node Types: ${Object.keys(NODE_TYPES).length}`);
  console.error(`   Relationship Types: ${Object.keys(RELATIONSHIP_TYPES).length}\n`);

  return {
    constraintsCreated,
    indexesCreated,
    nodeTypes: Object.keys(NODE_TYPES).length,
    relationshipTypes: Object.keys(RELATIONSHIP_TYPES).length
  };
}

/**
 * Validate schema against database
 */
export async function validateSchema(neo4jClient) {
  console.error('[SEARCH] Validating schema...');

  const stats = await neo4jClient.getDatabaseStats();

  console.error(`\n[STATS] Database Statistics:`);
  console.error(`   Total Nodes: ${stats.totalNodes}`);
  console.error(`   Total Relationships: ${stats.totalRelationships}`);

  if (Object.keys(stats.nodesByLabel).length > 0) {
    console.error(`\n   Nodes by Label:`);
    Object.entries(stats.nodesByLabel).forEach(([label, count]) => {
      console.error(`     ${label}: ${count}`);
    });
  }

  if (Object.keys(stats.relationshipsByType).length > 0) {
    console.error(`\n   Relationships by Type:`);
    Object.entries(stats.relationshipsByType).forEach(([type, count]) => {
      console.error(`     ${type}: ${count}`);
    });
  }

  return stats;
}

/**
 * Helper to generate unique ID
 */
export function generateNodeId(label, uniqueValue) {
  return `${label.toLowerCase()}_${uniqueValue}`.replace(/[^a-z0-9_]/g, '_');
}
