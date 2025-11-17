/**
 * SpecificationParser.js - SDD Workflow Specification Parser
 * 
 * Extracts implementation details from SDD workflow markdown files.
 * Converts natural language specifications into structured code generation
 * instructions for the SelfModificationEngine.
 * 
 * Features:
 * - Parse code_generation steps into file specifications
 * - Extract code_modification operations
 * - Identify tool registration requirements
 * - Parse validation and testing criteria
 * - Generate structured modification plans
 * 
 * @version 4.0.0
 * @author NOAA EMC Global Workflow Team
 */

export class SpecificationParser {
  constructor() {
    this.currentSpec = null;
  }

  /**
   * Parse workflow content into modification specifications
   */
  parseWorkflow(workflowContent) {
    const steps = this.extractSteps(workflowContent);
    const modifications = [];

    for (const step of steps) {
      const mod = this.parseStep(step);
      if (mod) {
        modifications.push(mod);
      }
    }

    return {
      title: this.extractTitle(workflowContent),
      description: this.extractDescription(workflowContent),
      modifications,
      validations: this.extractValidations(steps),
      tests: this.extractTests(steps)
    };
  }

  /**
   * Extract steps from workflow markdown
   */
  extractSteps(content) {
    const steps = [];
    const stepRegex = /###\s+Step\s+\d+:\s+(.+?)\n([\s\S]*?)(?=###|$)/g;
    let match;

    while ((match = stepRegex.exec(content)) !== null) {
      const title = match[1].trim();
      const body = match[2].trim();
      const metadata = this.parseStepMetadata(body);

      steps.push({
        title,
        body,
        ...metadata
      });
    }

    return steps;
  }

  /**
   * Parse step metadata (Type, Target, etc.)
   */
  parseStepMetadata(body) {
    const metadata = {};
    const lines = body.split('\n');

    for (const line of lines) {
      const metaMatch = line.match(/^\*\*(\w+)\*\*:\s*(.+)$/);
      if (metaMatch) {
        const key = metaMatch[1].toLowerCase();
        const value = metaMatch[2].trim();
        metadata[key] = value;
      }
    }

    return metadata;
  }

  /**
   * Parse individual step into modification spec
   */
  parseStep(step) {
    const type = step.type?.toLowerCase();

    switch (type) {
      case 'code_generation':
        return this.parseCodeGeneration(step);
      
      case 'code_modification':
        return this.parseCodeModification(step);
      
      case 'tool_registration':
        return this.parseToolRegistration(step);
      
      case 'method_addition':
        return this.parseMethodAddition(step);
      
      case 'validation':
      case 'command':
        // These are handled by existing workflow execution
        return null;
      
      default:
        console.warn(`[WARN] Unknown step type: ${type}`);
        return null;
    }
  }

  /**
   * Parse code generation step
   */
  parseCodeGeneration(step) {
    return {
      type: 'generate_file',
      spec: {
        filePath: step.target || step.file,
        template: step.template,
        content: this.extractCodeBlock(step.body),
        variables: this.extractVariables(step),
        description: step.title
      }
    };
  }

  /**
   * Parse code modification step
   */
  parseCodeModification(step) {
    const operations = [];

    // Parse action
    const action = step.action?.toLowerCase();
    if (action) {
      if (action.includes('import') || action.includes('add import')) {
        operations.push({
          type: 'insert',
          position: 'after-imports',
          content: this.extractImportStatement(step)
        });
      } else if (action.includes('register')) {
        operations.push({
          type: 'insert',
          position: 'constructor-end',
          content: this.extractRegistrationCode(step)
        });
      } else if (action.includes('add') || action.includes('create')) {
        operations.push({
          type: 'append',
          content: this.extractCodeBlock(step.body)
        });
      }
    }

    // Parse method if specified
    if (step.method) {
      operations.push({
        type: 'insert',
        position: 'class-end',
        content: this.generateMethodStub(step.method, step.returns)
      });
    }

    return {
      type: 'modify_file',
      spec: {
        filePath: step.file || step.target,
        operations,
        description: step.title
      }
    };
  }

  /**
   * Parse tool registration step
   */
  parseToolRegistration(step) {
    return {
      type: 'register_tool',
      spec: {
        toolClassName: step.tool || this.extractClassName(step.body),
        toolFilePath: step.file || step.path,
        description: step.title
      }
    };
  }

  /**
   * Parse method addition step
   */
  parseMethodAddition(step) {
    return {
      type: 'add_method',
      spec: {
        filePath: step.file || step.target,
        className: step.class || this.extractClassName(step.body),
        methodName: step.method,
        methodCode: this.extractCodeBlock(step.body),
        position: step.position || 'end',
        description: step.title
      }
    };
  }

  /**
   * Extract code block from markdown
   */
  extractCodeBlock(text) {
    const codeBlockMatch = text.match(/```(?:javascript|js)?\n([\s\S]*?)```/);
    return codeBlockMatch ? codeBlockMatch[1].trim() : null;
  }

  /**
   * Extract variables from step metadata
   */
  extractVariables(step) {
    const variables = {};
    
    // Common variables
    if (step.name) variables.name = step.name;
    if (step.class) variables.className = step.class;
    if (step.method) variables.methodName = step.method;
    if (step.description) variables.description = step.description;

    return variables;
  }

  /**
   * Extract class name from text
   */
  extractClassName(text) {
    const classMatch = text.match(/class\s+(\w+)/);
    return classMatch ? classMatch[1] : null;
  }

  /**
   * Extract import statement from step
   */
  extractImportStatement(step) {
    const codeBlock = this.extractCodeBlock(step.body);
    if (codeBlock && codeBlock.startsWith('import')) {
      return codeBlock;
    }
    
    // Generate import statement
    if (step.class && step.file) {
      return `import { ${step.class} } from '${step.file}';`;
    }
    
    return '';
  }

  /**
   * Extract registration code from step
   */
  extractRegistrationCode(step) {
    const codeBlock = this.extractCodeBlock(step.body);
    if (codeBlock) {
      return codeBlock;
    }

    // Generate registration code
    if (step.tool || step.class) {
      const className = step.tool || step.class;
      const instanceName = className.charAt(0).toLowerCase() + className.slice(1);
      return `this.${instanceName} = new ${className}();\nthis.${instanceName}.registerWith(this.server);`;
    }

    return '';
  }

  /**
   * Generate method stub
   */
  generateMethodStub(methodName, returnType) {
    const returns = returnType || 'void';
    return `
  /**
   * ${methodName}
   * @returns {${returns}}
   */
  async ${methodName}() {
    // TODO: Implement ${methodName}
    throw new Error('Not implemented');
  }`;
  }

  /**
   * Extract validations from steps
   */
  extractValidations(steps) {
    return steps
      .filter(s => s.type?.toLowerCase() === 'validation')
      .map(s => ({
        target: s.target,
        checks: this.parseValidationChecks(s.body),
        required: s.required?.toLowerCase() === 'yes'
      }));
  }

  /**
   * Parse validation checks from step body
   */
  parseValidationChecks(body) {
    const checks = [];
    const lines = body.split('\n');

    for (const line of lines) {
      if (line.includes('must') || line.includes('should') || line.includes('ensure')) {
        checks.push({
          description: line.trim(),
          type: 'custom'
        });
      }
    }

    return checks;
  }

  /**
   * Extract test commands from steps
   */
  extractTests(steps) {
    return steps
      .filter(s => s.type?.toLowerCase() === 'command' && 
                   (s.command?.includes('test') || s.command?.includes('npm test')))
      .map(s => ({
        command: s.command,
        required: s.required?.toLowerCase() === 'yes',
        timeout: s.timeout ? parseInt(s.timeout) : 30000
      }));
  }

  /**
   * Extract title from markdown
   */
  extractTitle(content) {
    const match = content.match(/^#\s+(.+)$/m);
    return match ? match[1].trim() : 'Untitled';
  }

  /**
   * Extract description from markdown
   */
  extractDescription(content) {
    const lines = content.split('\n');
    let description = '';
    let inDescription = false;

    for (const line of lines) {
      if (line.startsWith('# ')) {
        inDescription = true;
        continue;
      }
      if (line.startsWith('## ')) {
        break;
      }
      if (inDescription && line.trim()) {
        description += line.trim() + ' ';
      }
    }

    return description.trim();
  }

  /**
   * Generate modification plan summary
   */
  generatePlan(spec) {
    const plan = {
      title: spec.title,
      description: spec.description,
      steps: [],
      estimatedTime: 0
    };

    for (const mod of spec.modifications) {
      plan.steps.push({
        type: mod.type,
        target: mod.spec.filePath || mod.spec.file,
        description: mod.spec.description
      });
      
      // Estimate time (rough)
      plan.estimatedTime += this.estimateStepTime(mod.type);
    }

    plan.validationCount = spec.validations.length;
    plan.testCount = spec.tests.length;

    return plan;
  }

  /**
   * Estimate step execution time (seconds)
   */
  estimateStepTime(type) {
    const times = {
      'generate_file': 5,
      'modify_file': 3,
      'add_method': 4,
      'register_tool': 2
    };
    return times[type] || 2;
  }
}
