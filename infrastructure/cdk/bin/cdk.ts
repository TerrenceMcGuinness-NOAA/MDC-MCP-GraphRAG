#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { MdcVpcStack } from '../lib/mdc-vpc-stack';
import { MdcSecurityStack } from '../lib/mdc-security-stack';
import { MdcDataStack } from '../lib/mdc-data-stack';
import { MdcServerStack } from '../lib/mdc-server-stack';

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
  vpc:      vpcStack.vpc,
  userPool: securityStack.userPool,
  webAcl:   securityStack.webAcl,
});

securityStack.addDependency(vpcStack);
dataStack.addDependency(securityStack);
serverStack.addDependency(dataStack);
