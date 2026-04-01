#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { MdcVpcStack } from '../lib/mdc-vpc-stack';
import { MdcSecurityStack } from '../lib/mdc-security-stack';
import { MdcDataStack } from '../lib/mdc-data-stack';

const app = new cdk.App();

const env = { account: '903050880929', region: 'us-east-1' };

const vpcStack = new MdcVpcStack(app, 'MdcVpcStack', { env });
const securityStack = new MdcSecurityStack(app, 'MdcSecurityStack', { env, vpc: vpcStack.vpc });
const dataStack = new MdcDataStack(app, 'MdcDataStack', {
  env,
  vpc: vpcStack.vpc,
  ecsSecurityGroup: securityStack.ecsSecurityGroup,
});

securityStack.addDependency(vpcStack);
dataStack.addDependency(securityStack);
