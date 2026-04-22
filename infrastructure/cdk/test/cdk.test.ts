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
    webAcl: securityStack.webAcl,
  });
  return { vpcStack, securityStack, dataStack, serverStack };
}

// ── MdcVpcStack ──────────────────────────────────────────────────────────────

describe('MdcVpcStack', () => {
  const { vpcStack } = buildStacks();
  const template = Template.fromStack(vpcStack);

  test('VPC outputs exist', () => {
    template.hasOutput('VpcId', {});
  });
});

// ── MdcSecurityStack ─────────────────────────────────────────────────────────

describe('MdcSecurityStack', () => {
  const { securityStack } = buildStacks();
  const template = Template.fromStack(securityStack);

  test('No Cognito user pool exists (removed for private access)', () => {
    template.resourceCountIs('AWS::Cognito::UserPool', 0);
  });

  test('WAF WebACL exists with REGIONAL scope', () => {
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      Name: 'mdc-mcp-rag-waf',
      Scope: 'REGIONAL',
    });
  });

  test('Neptune credentials secret exists', () => {
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: 'mdc-mcp-rag/neptune/credentials',
    });
  });

  test('ECS security group exists', () => {
    template.hasResourceProperties('AWS::EC2::SecurityGroup', {
      GroupDescription: 'Security group for MDC MCP RAG ECS tasks',
    });
  });

  test('SSM parameters exist', () => {
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Name: '/mdc-mcp-rag/neptune/endpoint',
    });
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Name: '/mdc-mcp-rag/opensearch/endpoint',
    });
  });

  test('No secret values in outputs', () => {
    const outputs = template.findOutputs('*');
    for (const key of Object.keys(outputs)) {
      const val = JSON.stringify(outputs[key]);
      expect(val).not.toMatch(/password|token|secret/i);
    }
  });
});

// ── MdcDataStack ─────────────────────────────────────────────────────────────

describe('MdcDataStack', () => {
  const { dataStack } = buildStacks();
  const template = Template.fromStack(dataStack);

  test('No Neptune cluster created (imported instead)', () => {
    template.resourceCountIs('AWS::Neptune::DBCluster', 0);
  });

  test('No OpenSearch domain created (imported instead)', () => {
    template.resourceCountIs('AWS::OpenSearchService::Domain', 0);
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
});

// ── MdcServerStack ───────────────────────────────────────────────────────────

describe('MdcServerStack', () => {
  const { serverStack } = buildStacks();
  const template = Template.fromStack(serverStack);

  test('No CloudFront distribution exists', () => {
    template.resourceCountIs('AWS::CloudFront::Distribution', 0);
  });

  test('No CLOUDFRONT-scoped WAF exists', () => {
    const webAcls = template.findResources('AWS::WAFv2::WebACL');
    for (const [, resource] of Object.entries(webAcls)) {
      expect((resource as any).Properties?.Scope).not.toBe('CLOUDFRONT');
    }
  });

  test('No Cognito authorizer exists', () => {
    template.resourceCountIs('AWS::ApiGateway::Authorizer', 0);
  });

  test('API Gateway endpoint type is PRIVATE', () => {
    template.hasResourceProperties('AWS::ApiGateway::RestApi', {
      EndpointConfiguration: { Types: ['PRIVATE'] },
    });
  });

  test('API Gateway resource policy restricts to VPC endpoint', () => {
    template.hasResourceProperties('AWS::ApiGateway::RestApi', {
      Policy: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Effect: 'Deny',
            Condition: Match.objectLike({
              StringNotEquals: Match.objectLike({
                'aws:sourceVpce': Match.anyValue(),
              }),
            }),
          }),
        ]),
      }),
    });
  });

  test('/health endpoint exists with no auth', () => {
    template.hasResourceProperties('AWS::ApiGateway::Method', {
      AuthorizationType: 'NONE',
      HttpMethod: 'ANY',
    });
  });

  test('VPC Link exists for API Gateway', () => {
    template.resourceCountIs('AWS::ApiGateway::VpcLink', 1);
  });

  test('WAF associated with API Gateway stage', () => {
    template.resourceCountIs('AWS::WAFv2::WebACLAssociation', 1);
  });

  test('PrivateApiEndpoint output exists', () => {
    template.hasOutput('PrivateApiEndpoint', {});
  });

  test('No CloudFrontDomain output exists', () => {
    const outputs = template.findOutputs('*');
    expect(outputs).not.toHaveProperty('CloudFrontDomain');
    expect(outputs).not.toHaveProperty('McpEndpoint');
  });

  test('ECS Fargate task definition has 1 vCPU and 2GB memory', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      Cpu: '1024',
      Memory: '2048',
      RequiresCompatibilities: ['FARGATE'],
    });
  });

  test('NLB health check on /health path', () => {
    template.hasResourceProperties('AWS::ElasticLoadBalancingV2::TargetGroup', {
      HealthCheckPath: '/health',
    });
  });

  test('NLB is internal (not public)', () => {
    template.hasResourceProperties('AWS::ElasticLoadBalancingV2::LoadBalancer', {
      Scheme: 'internal',
    });
  });

  test('ECS assignPublicIp is DISABLED', () => {
    template.hasResourceProperties('AWS::ECS::Service', {
      NetworkConfiguration: Match.objectLike({
        AwsvpcConfiguration: Match.objectLike({
          AssignPublicIp: 'DISABLED',
        }),
      }),
    });
  });

  test('API Gateway REST API exists', () => {
    template.resourceCountIs('AWS::ApiGateway::RestApi', 1);
  });

  test('No secret values in outputs', () => {
    const outputs = template.findOutputs('*');
    for (const key of Object.keys(outputs)) {
      const val = JSON.stringify(outputs[key]);
      expect(val).not.toMatch(/password|token|secret/i);
    }
  });
});
