import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';

/**
 * Environment_Name resolution and naming helpers for the Cost_Control_System
 * CDK app. Mirrors the orchestrator's cost_control/config.py so stack-created
 * resource names line up with what the Python orchestrator resolves.
 *
 * Requirements: 13.1 (Environment_Name via context), 13.2 (environment tag),
 * 13.4 (valid_environments allow-list), 11.1 (four env-suffixed stacks).
 */

export const VALID_ENVIRONMENTS = ['dev', 'staging', 'prod'] as const;
export type EnvironmentName = (typeof VALID_ENVIRONMENTS)[number];

export const ENVIRONMENT_TAG_KEY = 'mdc-mcp-rag:environment';

/**
 * Resolve the Environment_Name from CDK context (`-c env=...`), defaulting to
 * `dev`, and validate it against the `valid_environments` allow-list (which
 * may itself be overridden via `-c valid_environments=a,b,c`). Throws on an
 * out-of-allow-list value (R13.4).
 */
export function resolveEnvironmentName(app: cdk.App): EnvironmentName {
  const env = (app.node.tryGetContext('env') as string) || 'dev';
  const allowCtx = app.node.tryGetContext('valid_environments') as string | undefined;
  const allow = allowCtx
    ? allowCtx.split(',').map((s) => s.trim()).filter(Boolean)
    : [...VALID_ENVIRONMENTS];
  if (!allow.includes(env)) {
    throw new Error(
      `environment_name '${env}' is not in the valid_environments allow-list ` +
        `(${allow.join(', ')})`,
    );
  }
  return env as EnvironmentName;
}

/** Stack name: `MdcMcpRag-<Layer>-<env>` (R11.1). */
export function stackName(layer: string, env: string): string {
  return `MdcMcpRag-${layer}-${env}`;
}

/** Bucket name matching cost_control/config.py `_default_bucket`. */
export function bucketName(purpose: string, env: string): string {
  return `mdc-mcp-rag-cost-control-${purpose}-${env}`;
}

/** CloudWatch log group matching cost_control/config.py `log_group`. */
export function logGroupName(env: string): string {
  return `mdc-mcp-rag-cost-control-${env}`;
}

/** Apply the `mdc-mcp-rag:environment` tag to every resource in a scope (R13.2). */
export function applyEnvironmentTag(scope: Construct, env: string): void {
  cdk.Tags.of(scope).add(ENVIRONMENT_TAG_KEY, env);
}
