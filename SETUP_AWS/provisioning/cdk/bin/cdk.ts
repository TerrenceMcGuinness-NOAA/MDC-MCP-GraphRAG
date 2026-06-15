#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { resolveEnvironmentName, stackName } from '../lib/env';
import { NetworkStack } from '../lib/network-stack';
import { StorageStack } from '../lib/storage-stack';
import { IamStack } from '../lib/iam-stack';
import { ComputeStack } from '../lib/compute-stack';
import { orchestratorPolicyStatements } from '../lib/orchestrator-policy';

const app = new cdk.App();
const environmentName = resolveEnvironmentName(app);

// Region-agnostic by default so `cdk synth` / tests run offline. A deploy
// supplies account/region via the standard CDK_DEFAULT_* env vars.
const env = process.env.CDK_DEFAULT_ACCOUNT
  ? { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION }
  : undefined;

const network = new NetworkStack(app, stackName('Network', environmentName), {
  env,
  environmentName,
});

const storage = new StorageStack(app, stackName('Storage', environmentName), {
  env,
  environmentName,
  vpc: network.vpc,
});

const iamStack = new IamStack(app, stackName('IAM', environmentName), {
  env,
  environmentName,
  stateBucket: storage.stateBucket,
  auditBucket: storage.auditBucket,
  snapshotBucket: storage.snapshotBucket,
});

// Task 16: wire the generated least-privilege orchestrator action set
// (derived from the cost_control/ source) onto the orchestrator role. The
// action set is reviewable in lib/orchestrator-policy.ts; nothing is applied
// to AWS until the operator-gated `cdk deploy` (Wave 7).
iamStack.attachOrchestratorPolicy(
  orchestratorPolicyStatements(
    environmentName,
    iamStack.account,
    iamStack.openSearchSnapshotRole.roleArn,
  ),
);

const compute = new ComputeStack(app, stackName('Compute', environmentName), {
  env,
  environmentName,
  vpc: network.vpc,
  computeSecurityGroup: network.computeSecurityGroup,
  resleepLambdaRole: iamStack.resleepLambdaRole,
  agentCoreRuntimeArn: app.node.tryGetContext('agentcore_runtime_arn'),
});

storage.addDependency(network);
iamStack.addDependency(storage);
compute.addDependency(iamStack);
compute.addDependency(storage);
compute.addDependency(network);
