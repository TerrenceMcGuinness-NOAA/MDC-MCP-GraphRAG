#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { MdcVpcStack } from '../lib/mdc-vpc-stack';
import { MdcSecurityStack } from '../lib/mdc-security-stack';
import { MdcDataStack } from '../lib/mdc-data-stack';
import { MdcServerStack } from '../lib/mdc-server-stack';
import { MdcExternalAccessAlternativeStack } from '../lib/mdc-external-access-alternative-stack';

const app = new cdk.App();

const env = { account: '903050880929', region: 'us-east-1' };

const vpcStack      = new MdcVpcStack(app, 'MdcVpcStack', { env });
const securityStack = new MdcSecurityStack(app, 'MdcSecurityStack', { env, vpc: vpcStack.vpc });
const dataStack     = new MdcDataStack(app, 'MdcDataStack', {
  env,
  vpc: vpcStack.vpc,
  ecsSecurityGroup: securityStack.ecsSecurityGroup,
});
const serverStack   = new MdcServerStack(app, 'MdcServerStack', {
  env,
  vpc:    vpcStack.vpc,
  webAcl: securityStack.webAcl,
});

securityStack.addDependency(vpcStack);
dataStack.addDependency(securityStack);
serverStack.addDependency(dataStack);

// External access (Path B) — Cognito JWT authorizer on the AgentCore Runtime.
// Spec: .kiro/specs/mcp-external-access-revised/. Correction C1: the active
// runtime is the PYTHON runtime (52 tools), so this ARN is the Python runtime.
const externalAccessStack = new MdcExternalAccessAlternativeStack(app, 'MdcExternalAccessAlternativeStack', {
  env,
  runtimeArn: 'arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN',
  mcpServerTaskRole: securityStack.ecsTaskRole,
  allowedGithubSubPatterns: [
    'repo:NOAA-EMC/global-workflow:ref:refs/heads/*',
    'repo:NOAA-EMC/mdc-mcp-rag:ref:refs/heads/*',
  ],
});
externalAccessStack.addDependency(serverStack);
