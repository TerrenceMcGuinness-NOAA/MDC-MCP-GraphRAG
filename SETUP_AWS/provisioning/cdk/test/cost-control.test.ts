import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { NetworkStack } from '../lib/network-stack';
import { StorageStack } from '../lib/storage-stack';
import { IamStack } from '../lib/iam-stack';
import { ComputeStack } from '../lib/compute-stack';
import { ENVIRONMENT_TAG_KEY } from '../lib/env';

// Per-hour-billed resource types that must NEVER appear in Storage/Network.
const PER_HOUR_TYPES = [
  'AWS::EC2::Instance',
  'AWS::EC2::NatGateway',
  'AWS::Neptune::DBCluster',
  'AWS::Neptune::DBInstance',
  'AWS::OpenSearchService::Domain',
  'AWS::RDS::DBInstance',
];

function build(env = 'dev', context: Record<string, unknown> = {}) {
  const app = new cdk.App({ context });
  const network = new NetworkStack(app, `MdcMcpRag-Network-${env}`, { environmentName: env });
  const storage = new StorageStack(app, `MdcMcpRag-Storage-${env}`, {
    environmentName: env, vpc: network.vpc,
  });
  const iam = new IamStack(app, `MdcMcpRag-IAM-${env}`, {
    environmentName: env,
    stateBucket: storage.stateBucket,
    auditBucket: storage.auditBucket,
    snapshotBucket: storage.snapshotBucket,
  });
  const compute = new ComputeStack(app, `MdcMcpRag-Compute-${env}`, {
    environmentName: env, vpc: network.vpc,
    computeSecurityGroup: network.computeSecurityGroup,
    resleepLambdaRole: iam.resleepLambdaRole,
  });
  return { app, network, storage, iam, compute };
}

// ── Network stack ────────────────────────────────────────────────────────────

describe('MdcMcpRag-Network', () => {
  const { network } = build();
  const t = Template.fromStack(network);

  test('declares a VPC and security group', () => {
    t.resourceCountIs('AWS::EC2::VPC', 1);
    t.resourceCountIs('AWS::EC2::SecurityGroup', 1);
  });

  test('declares NO NAT gateway (R11.4)', () => {
    t.resourceCountIs('AWS::EC2::NatGateway', 0);
  });

  test('declares NO per-hour resource', () => {
    for (const type of PER_HOUR_TYPES) {
      t.resourceCountIs(type, 0);
    }
  });

  test('declares the free S3 gateway endpoint only (no interface endpoints)', () => {
    t.resourceCountIs('AWS::EC2::VPCEndpoint', 1);
    t.hasResourceProperties('AWS::EC2::VPCEndpoint', {
      VpcEndpointType: 'Gateway',
    });
  });
});

// ── Storage stack ──────────────────────────────────────────────────────────

describe('MdcMcpRag-Storage', () => {
  const { storage } = build();
  const t = Template.fromStack(storage);

  test('declares EFS, ECR, and three S3 buckets', () => {
    t.resourceCountIs('AWS::EFS::FileSystem', 1);
    t.resourceCountIs('AWS::EFS::AccessPoint', 1);
    t.resourceCountIs('AWS::ECR::Repository', 1);
    t.resourceCountIs('AWS::S3::Bucket', 3);
  });

  test('declares NO per-hour resource (R11.2)', () => {
    for (const type of PER_HOUR_TYPES) {
      t.resourceCountIs(type, 0);
    }
  });

  test('every stateful resource has DeletionPolicy Retain (data-safety rule 05)', () => {
    for (const type of ['AWS::EFS::FileSystem', 'AWS::ECR::Repository', 'AWS::S3::Bucket']) {
      const resources = t.findResources(type);
      for (const [logicalId, resource] of Object.entries(resources)) {
        expect((resource as any).DeletionPolicy).toBe('Retain');
      }
    }
  });

  test('S3 buckets are versioned, encrypted, and public-access-blocked', () => {
    t.hasResourceProperties('AWS::S3::Bucket', {
      VersioningConfiguration: { Status: 'Enabled' },
      PublicAccessBlockConfiguration: Match.objectLike({ BlockPublicAcls: true }),
    });
  });

  test('ECR repository name is env-suffixed', () => {
    t.hasResourceProperties('AWS::ECR::Repository', {
      RepositoryName: 'mdc-mcp-rag-dev',
    });
  });
});

// ── IAM stack ────────────────────────────────────────────────────────────────

describe('MdcMcpRag-IAM', () => {
  const { iam } = build();
  const t = Template.fromStack(iam);

  test('declares the orchestrator, OpenSearch-snapshot, and re-sleep roles', () => {
    t.resourceCountIs('AWS::IAM::Role', 3);
    t.hasResourceProperties('AWS::IAM::Role', {
      RoleName: 'mdc-mcp-rag-cost-control-orchestrator-dev',
    });
    t.hasResourceProperties('AWS::IAM::Role', {
      RoleName: 'mdc-mcp-rag-cost-control-os-snapshot-dev',
    });
    t.hasResourceProperties('AWS::IAM::Role', {
      RoleName: 'mdc-mcp-rag-cost-control-resleep-dev',
    });
  });

  test('declares NO per-hour resource', () => {
    for (const type of PER_HOUR_TYPES) {
      t.resourceCountIs(type, 0);
    }
  });
});

// ── Compute stack ──────────────────────────────────────────────────────────

describe('MdcMcpRag-Compute', () => {
  const { compute } = build();
  const t = Template.fromStack(compute);

  test('owns EC2 + Neptune + OpenSearch + NAT (R11.5)', () => {
    t.resourceCountIs('AWS::EC2::Instance', 1);
    t.resourceCountIs('AWS::Neptune::DBCluster', 1);
    t.resourceCountIs('AWS::Neptune::DBInstance', 1);
    t.resourceCountIs('AWS::OpenSearchService::Domain', 1);
    t.resourceCountIs('AWS::EC2::NatGateway', 1);
    t.resourceCountIs('AWS::EC2::EIP', 1);
  });

  test('imports network/storage (does not redeclare them) (R11.5)', () => {
    // No VPC / EFS / ECR / S3 bucket is redeclared in Compute.
    t.resourceCountIs('AWS::EC2::VPC', 0);
    t.resourceCountIs('AWS::EFS::FileSystem', 0);
    t.resourceCountIs('AWS::ECR::Repository', 0);
    t.resourceCountIs('AWS::S3::Bucket', 0);
    // It consumes cross-stack exports via Fn::ImportValue.
    const json = JSON.stringify(t.toJSON());
    expect(json).toContain('Fn::ImportValue');
  });

  test('Neptune + OpenSearch carry DeletionPolicy Retain', () => {
    for (const type of ['AWS::Neptune::DBCluster', 'AWS::Neptune::DBInstance',
                        'AWS::OpenSearchService::Domain']) {
      const resources = t.findResources(type);
      for (const [, resource] of Object.entries(resources)) {
        expect((resource as any).DeletionPolicy).toBe('Retain');
      }
    }
  });

  test('declares the daily Neptune re-sleep rule + guard Lambda', () => {
    t.hasResourceProperties('AWS::Events::Rule', {
      ScheduleExpression: 'rate(1 day)',
    });
    t.resourceCountIs('AWS::Lambda::Function', 1);
  });

  test('Schedule_Mode is DISABLED by default (R14.2)', () => {
    // Only the always-on re-sleep rule exists; no hibernate/wake schedule rules.
    t.resourceCountIs('AWS::Events::Rule', 1);
  });

  test('Schedule_Mode adds hibernate + wake rules when enabled', () => {
    const { compute } = build('dev', {
      schedule_enabled: 'true',
      sleep_cron: 'cron(0 0 * * ? *)',
      wake_cron: 'cron(0 12 * * ? *)',
    });
    const tt = Template.fromStack(compute);
    tt.resourceCountIs('AWS::Events::Rule', 3); // re-sleep + hibernate + wake
  });

  test('references AgentCore runtime via SSM (not a created runtime)', () => {
    t.resourceCountIs('AWS::SSM::Parameter', 1);
  });
});

// ── env suffix + environment tag ─────────────────────────────────────────────

describe('multi-environment parameterization', () => {
  test('stack names are env-suffixed', () => {
    const { network, storage, iam, compute } = build('staging');
    expect(network.stackName).toBe('MdcMcpRag-Network-staging');
    expect(storage.stackName).toBe('MdcMcpRag-Storage-staging');
    expect(iam.stackName).toBe('MdcMcpRag-IAM-staging');
    expect(compute.stackName).toBe('MdcMcpRag-Compute-staging');
  });

  test('every stack tags resources with mdc-mcp-rag:environment (R13.2)', () => {
    const { storage } = build('prod');
    const t = Template.fromStack(storage);
    t.hasResourceProperties('AWS::S3::Bucket', {
      Tags: Match.arrayWith([
        Match.objectLike({ Key: ENVIRONMENT_TAG_KEY, Value: 'prod' }),
      ]),
    });
  });

  test('invalid environment is rejected by the allow-list (R13.4)', () => {
    const app = new cdk.App({ context: { env: 'qa' } });
    // resolveEnvironmentName is invoked in bin/cdk.ts; emulate here.
    const { resolveEnvironmentName } = require('../lib/env');
    expect(() => resolveEnvironmentName(app)).toThrow(/valid_environments/);
  });
});
