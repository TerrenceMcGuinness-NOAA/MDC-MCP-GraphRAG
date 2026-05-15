import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as wafv2 from 'aws-cdk-lib/aws-wafv2';
import { Construct } from 'constructs';

interface MdcSecurityStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
}

export class MdcSecurityStack extends cdk.Stack {
  public readonly ecsTaskRole: iam.IRole;
  public readonly ecsExecutionRole: iam.IRole;
  public readonly ecsSecurityGroup: ec2.SecurityGroup;
  public readonly webAcl: wafv2.CfnWebACL;

  constructor(scope: Construct, id: string, props: MdcSecurityStackProps) {
    super(scope, id, props);

    // --- Secrets Manager entries ---
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

    // --- SSM Parameter Store ---
    new ssm.StringParameter(this, 'NeptuneEndpointParam', {
      parameterName: '/mdc-mcp-rag/neptune/endpoint',
      stringValue: 'PLACEHOLDER',
      description: 'Neptune cluster endpoint',
    });

    new ssm.StringParameter(this, 'OpenSearchEndpointParam', {
      parameterName: '/mdc-mcp-rag/opensearch/endpoint',
      stringValue: 'PLACEHOLDER',
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
    this.ecsSecurityGroup.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS egress');
    this.ecsSecurityGroup.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(8182), 'Neptune egress');

    // --- IAM Roles (pre-created by admin — import by name) ---
    this.ecsExecutionRole = iam.Role.fromRoleName(this, 'EcsExecutionRole',
      'mdc-mcp-rag-ecs-execution-role');

    this.ecsTaskRole = iam.Role.fromRoleName(this, 'EcsTaskRole',
      'mdc-mcp-rag-ecs-task-role');

    // --- WAF Web ACL (REGIONAL — for API Gateway) ---
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
