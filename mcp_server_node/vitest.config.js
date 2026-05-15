/**
 * vitest.config.js - Vitest Configuration
 * 
 * Simplified configuration for unit and integration tests
 * No imports needed - plain JavaScript export
 */

export default {
  test: {
    // Test environment
    environment: 'node',
    
    // Global test timeout (30 seconds for DB operations)
    testTimeout: 30000,
    
    // Coverage configuration
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: ['src/**/*.js'],
      exclude: [
        'src/**/__tests__/**',
        'src/**/*.test.js',
        'src/**/*.spec.js',
        'node_modules/**'
      ],
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 75,
        statements: 80
      }
    },
    
    // Setup files - disabled for now to avoid circular import
    // setupFiles: ['./src/__tests__/setup.js'],
    
    // Global configuration
    globals: true,
    
    // Isolated tests
    isolate: true,
    
    // Parallel execution
    poolOptions: {
      threads: {
        singleThread: false,
        maxThreads: 4,
        minThreads: 1
      }
    },
    
    // Reporter configuration
    reporters: ['verbose'],
    
    // Test file patterns
    include: ['src/**/*.test.js', 'src/**/__tests__/**/*.js', 'test/**/*.test.js'],
    exclude: ['node_modules', 'dist']
  }
};
