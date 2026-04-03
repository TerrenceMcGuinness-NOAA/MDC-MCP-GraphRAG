import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as wafv2 from 'aws-cdk-lib/aws-wafv2';
import { Construct } from 'constructs';

interface MdcSecurityStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
}

export class MdcSecurityStack extends cdk.Stack {
  public readonly ecsTaskRole: iam.Role;
  public readonly ecsExecutionRole: iam.Role;
  public readonly ecsSecurityGroup: ec2.SecurityGroup;
  public readonly userPool: cognito.UserPool;
  public readonly webAcl: wafv2.CfnWebACL;

  constructor(scope: Construct, id: string, props: MdcSecurityStackProps) {
    super(scope, id, props);

    // --- Secrets Manager entries (no values in CloudFormation outputs) ---
    new secretsmanager.Secret(this, 'NeptuneCredentials', {
      secretName: 'mdc-mcp-rag/neptune/credentials',
      description: 'Neptune cluster credentials for MDC MCP RAG',
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ username: 'neptune' }),
        generateStringKey: 'password',
        excludePunctuation: true,
      },
    });

    new secretsmanager.Secret(this, 'GithubToken', {
      secretName: 'mdc-mcp-rag/github/token',
      description: 'GitHub personal access token for MDC MCP RAG ingestion',
    });

    // --- SSM Parameter Store (endpoints populated post-deploy) ---
    new ssm.StringParameter(this, 'NeptuneEndpointParam', {
      parameterName: '/mdc-mcp-rag/neptune/endpoint',
      stringValue: 'PLACEHOLDER',  // updated after Neptune cluster is created
      description: 'Neptune cluster endpoint',
    });

    new ssm.StringParameter(this, 'OpenSearchEndpointParam', {
      parameterName: '/mdc-mcp-rag/opensearch/endpoint',
      stringValue: 'PLACEHOLDER',  // updated after OpenSearch domain is created
      description: 'OpenSearch domain endpoint',
    });

    new ssm.StringParameter(this, 'DbBackendParam', {
      parameterName: '/mdc-mcp-rag/db-backend',
      stringValue: 'legacy',
      description: 'Database backend selector: legacy | aws',
    });

    // --- ECS Security Group ---
    this.ecsSecurityGroup = new ec2.SecurityGroup(this, 'EcsSecurityGroup', {
      vpc: props.vpc,
      securityGroupName: 'mdc-mcp-rag-ecs-sg',
      description: 'Security group for MDC MCP RAG ECS tasks',
      allowAllOutbound: false,
    });
    // Allow HTTPS out (Secrets Manager, SSM, OpenSearch)
    this.ecsSecurityGroup.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS egress');
    // Allow Neptune out
    this.ecsSecurityGroup.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(8182), 'Neptune egress');

    // --- IAM Roles ---
    this.ecsExecutionRole = new iam.Role(this, 'EcsExecutionRole', {
      roleName: 'mdc-mcp-rag-ecs-execution-role',
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    this.ecsTaskRole = new iam.Role(this, 'EcsTaskRole', {
      roleName: 'mdc-mcp-rag-ecs-task-role',
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });
    this.ecsTaskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [`arn:aws:secretsmanager:${this.region}:${this.account}:secret:mdc-mcp-rag/*`],
    }));
    this.ecsTaskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['ssm:GetParameter', 'ssm:GetParameters'],
      resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter/mdc-mcp-rag/*`],
    }));
    this.ecsTaskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['neptune-db:connect'],
      resources: [`arn:aws:neptune-db:${this.region}:${this.account}:*/*`],
    }));
    this.ecsTaskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['es:ESHttpGet', 'es:ESHttpPost', 'es:ESHttpPut'],
      resources: [`arn:aws:es:${this.region}:${this.account}:domain/mdc-mcp-rag-search/*`],
    }));

    // --- Cognito User Pool ---
    this.userPool = new cognito.UserPool(this, 'MdcUserPool', {
      userPoolName: 'mdc-mcp-rag-users',
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      passwordPolicy: { minLength: 16, requireSymbols: true },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    this.userPool.addResourceServer('McpResourceServer', {
      identifier: 'mcp-api',
      scopes: [{ scopeName: 'tools', scopeDescription: 'Access MCP tools' }],
    });

    // --- WAF Web ACL (REGIONAL — for ALB/API Gateway) ---
    this.webAcl = new wafv2.CfnWebACL(this, 'MdcWebAcl', {
      name: 'mdc-mcp-rag-waf',
      scope: 'REGIONAL',
      defaultAction: { allow: {} },
      visibilityConfig: {
        cloudWatchMetricsEnabled: true,
        metricName: 'mdc-mcp-rag-waf',
        sampledRequestsEnabled: true,
      },
      rules: [
        {
          name: 'RateLimit',
          priority: 1,
          action: { block: {} },
          statement: {
            rateBasedStatement: { limit: 2000, aggregateKeyType: 'IP' },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: 'RateLimit',
            sampledRequestsEnabled: true,
          },
        },
        {
          name: 'AWSManagedRulesCommonRuleSet',
          priority: 2,
          overrideAction: { none: {} },
          statement: {
            managedRuleGroupStatement: { vendorName: 'AWS', name: 'AWSManagedRulesCommonRuleSet' },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: 'CommonRuleSet',
            sampledRequestsEnabled: true,
          },
        },
      ],
    });
  }
}
