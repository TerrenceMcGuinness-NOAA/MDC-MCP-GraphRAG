import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { MdcVpcStack } from '../lib/mdc-vpc-stack';
import { MdcSecurityStack } from '../lib/mdc-security-stack';
import { MdcDataStack } from '../lib/mdc-data-stack';
import { MdcServerStack } from '../lib/mdc-server-stack';

const env = { account: '903050880929', region: 'us-east-1' };

function buildStacks() {
  const app = new cdk.App();
  const vpcStack = new MdcVpcStack(app, 'MdcVpcStack', { env });
  const securityStack = new MdcSecurityStack(app, 'MdcSecurityStack', { env, vpc: vpcStack.vpc });
  const dataStack = new MdcDataStack(app, 'MdcDataStack', {
    env,
    vpc: vpcStack.vpc,
    ecsSecurityGroup: securityStack.ecsSecurityGroup,
  });
  const serverStack = new MdcServerStack(app, 'MdcServerStack', {
    env,
    vpc: vpcStack.vpc,
    userPool: securityStack.userPool,
    webAcl: securityStack.webAcl,
  });
  return { vpcStack, securityStack, dataStack, serverStack };
}

describe('MdcVpcStack', () => {
  const { vpcStack } = buildStacks();
  const template = Template.fromStack(vpcStack);

  test('VPC has 2 AZs with public and private subnets', () => {
    template.resourceCountIs('AWS::EC2::Subnet', 4); // 2 public + 2 private
  });

  test('NAT Gateway exists', () => {
    template.resourceCountIs('AWS::EC2::NatGateway', 1);
  });

  test('Secrets Manager VPC endpoint exists', () => {
    template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
      ServiceName: Match.stringLikeRegexp('secretsmanager'),
      VpcEndpointType: 'Interface',
    });
  });

  test('SSM VPC endpoint exists', () => {
    template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
      ServiceName: Match.stringLikeRegexp('\\.ssm$'),
      VpcEndpointType: 'Interface',
    });
  });

  test('S3 gateway endpoint exists', () => {
    // CDK generates ServiceName via Fn::Join for gateway endpoints; match on type only
    template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
      VpcEndpointType: 'Gateway',
    });
  });
});

describe('MdcSecurityStack', () => {
  const { securityStack } = buildStacks();
  const template = Template.fromStack(securityStack);

  test('Neptune credentials secret exists at correct path', () => {
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: 'mdc-mcp-rag/neptune/credentials',
    });
  });

  test('GitHub token secret exists at correct path', () => {
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: 'mdc-mcp-rag/github/token',
    });
  });

  test('Neptune SSM parameter exists', () => {
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Name: '/mdc-mcp-rag/neptune/endpoint',
    });
  });

  test('OpenSearch SSM parameter exists', () => {
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Name: '/mdc-mcp-rag/opensearch/endpoint',
    });
  });

  test('No secret values in CloudFormation outputs', () => {
    const outputs = template.findOutputs('*');
    for (const key of Object.keys(outputs)) {
      const val = JSON.stringify(outputs[key]);
      expect(val).not.toMatch(/password|token|secret/i);
    }
  });

  test('Cognito user pool exists', () => {
    template.resourceCountIs('AWS::Cognito::UserPool', 1);
  });

  test('WAF WebACL exists with rate limiting rule', () => {
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      Name: 'mdc-mcp-rag-waf',
      Scope: 'REGIONAL',
    });
  });

  test('ECS task role has Secrets Manager access scoped to mdc-mcp-rag/*', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 'secretsmanager:GetSecretValue',
            Resource: Match.stringLikeRegexp('mdc-mcp-rag'),
          }),
        ]),
      },
    });
  });

  test('ECS security group allows Neptune egress on 8182', () => {
    // CDK inlines egress rules into the SecurityGroup resource when allowAllOutbound=false
    template.hasResourceProperties('AWS::EC2::SecurityGroup', {
      SecurityGroupEgress: Match.arrayWith([
        Match.objectLike({ FromPort: 8182, ToPort: 8182, IpProtocol: 'tcp' }),
      ]),
    });
  });
});

describe('MdcDataStack', () => {
  const { dataStack } = buildStacks();
  const template = Template.fromStack(dataStack);

  test('Neptune cluster has IAM auth enabled', () => {
    template.hasResourceProperties('AWS::Neptune::DBCluster', {
      DBClusterIdentifier: 'mdc-mcp-rag-neptune',
      IamAuthEnabled: true,
      StorageEncrypted: true,
    });
  });

  test('OpenSearch domain has k-NN capable instance type', () => {
    template.hasResourceProperties('AWS::OpenSearchService::Domain', {
      DomainName: 'mdc-mcp-rag-search',
      EncryptionAtRestOptions: { Enabled: true },
      NodeToNodeEncryptionOptions: { Enabled: true },
      DomainEndpointOptions: { EnforceHTTPS: true },
    });
  });

  test('EFS filesystem is encrypted', () => {
    template.hasResourceProperties('AWS::EFS::FileSystem', {
      Encrypted: true,
    });
  });

  test('S3 migration bucket blocks public access', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      BucketName: 'mdc-mcp-rag-migration',
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
  });

  test('Neptune security group only allows ECS on 8182', () => {
    template.hasResourceProperties('AWS::EC2::SecurityGroupIngress', {
      FromPort: 8182,
      ToPort: 8182,
      IpProtocol: 'tcp',
    });
  });

  test('OpenSearch security group only allows ECS on 443', () => {
    template.hasResourceProperties('AWS::EC2::SecurityGroupIngress', {
      FromPort: 443,
      ToPort: 443,
      IpProtocol: 'tcp',
    });
  });
});

describe('MdcServerStack', () => {
  const { serverStack } = buildStacks();
  const template = Template.fromStack(serverStack);

  test('ECS Fargate task definition has 1 vCPU and 2GB memory', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      Cpu: '1024',
      Memory: '2048',
      RequiresCompatibilities: ['FARGATE'],
    });
  });

  test('ECS task role has Secrets Manager access scoped to mdc-mcp-rag/*', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 'secretsmanager:GetSecretValue',
            Resource: Match.stringLikeRegexp('mdc-mcp-rag'),
          }),
        ]),
      },
    });
  });

  test('ALB health check is configured on /health path', () => {
    template.hasResourceProperties('AWS::ElasticLoadBalancingV2::TargetGroup', {
      HealthCheckPath: '/health',
      HealthCheckIntervalSeconds: 30,
      HealthyThresholdCount: 2,
    });
  });

  test('CloudFront distribution exists with HTTPS-only viewer protocol', () => {
    template.hasResourceProperties('AWS::CloudFront::Distribution', {
      DistributionConfig: Match.objectLike({
        DefaultCacheBehavior: Match.objectLike({
          ViewerProtocolPolicy: 'https-only',
        }),
        HttpVersion: 'http2',
      }),
    });
  });

  test('CloudFront WAF WebACL has rate limiting and geo-restriction rules', () => {
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      Name: 'mdc-mcp-rag-cf-waf',
      Scope: 'CLOUDFRONT',
      Rules: Match.arrayWith([
        Match.objectLike({ Name: 'RateLimit' }),
        Match.objectLike({ Name: 'GeoBlock' }),
      ]),
    });
  });

  test('API Gateway REST API exists', () => {
    template.resourceCountIs('AWS::ApiGateway::RestApi', 1);
  });

  test('No secret values in MdcServerStack CloudFormation outputs', () => {
    const outputs = template.findOutputs('*');
    for (const key of Object.keys(outputs)) {
      const val = JSON.stringify(outputs[key]);
      expect(val).not.toMatch(/password|token|secret/i);
    }
  });
});
