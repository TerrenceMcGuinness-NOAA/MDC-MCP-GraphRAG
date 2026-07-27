import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as fs from 'fs';
import * as path from 'path';
import { MdcExternalAccessAlternativeStack } from '../lib/mdc-external-access-alternative-stack';

// Spec: .kiro/specs/mcp-external-access-revised/ — Path B (Cognito JWT).
// Test account/region are placeholders (do not touch the live account).
const env = { account: '123456789012', region: 'us-east-1' };

function buildStack(): cdk.Stack {
  const app = new cdk.App();
  // A concrete (unimported) role stand-in so the mcpServerTaskRole prop is a
  // real IRole in tests without pulling in the whole stack graph.
  const roleApp = new cdk.Stack(app, 'RoleHolder', { env });
  const taskRole = iam.Role.fromRoleArn(
    roleApp,
    'TaskRole',
    'arn:aws:iam::123456789012:role/mdc-mcp-rag-ecs-task-role',
    { mutable: false },
  );
  return new MdcExternalAccessAlternativeStack(app, 'TestStack', {
    env,
    runtimeArn: 'arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-runtime',
    mcpServerTaskRole: taskRole,
    allowedGithubSubPatterns: ['repo:NOAA-EMC/global-workflow:ref:refs/heads/*'],
  });
}

describe('MdcExternalAccessAlternativeStack — Task 1 scaffold', () => {
  test('synthesizes without error', () => {
    expect(() => Template.fromStack(buildStack())).not.toThrow();
  });

  // R9.10 — these negative assertions must hold at EVERY task stage: the stack
  // never introduces a DynamoDB claims-stash table nor a Pre-Token-Generation
  // trigger (AD-3). They pass trivially on the empty skeleton and continue to
  // pass as Cognito is added in Task 2.
  test('R9.10: no DynamoDB table exists', () => {
    Template.fromStack(buildStack()).resourceCountIs('AWS::DynamoDB::Table', 0);
  });
});

describe('MdcExternalAccessAlternativeStack — Task 2 Cognito', () => {
  const template = Template.fromStack(buildStack());

  test('exactly one Cognito user pool with DeletionPolicy Retain (R1.1, R1.2, R9.4)', () => {
    template.resourceCountIs('AWS::Cognito::UserPool', 1);
    const pools = template.findResources('AWS::Cognito::UserPool');
    for (const [, pool] of Object.entries(pools)) {
      expect((pool as any).DeletionPolicy).toBe('Retain');
    }
  });

  test('user pool has NO Pre-Token-Generation trigger (R9.10, AD-3)', () => {
    const pools = template.findResources('AWS::Cognito::UserPool');
    for (const [, pool] of Object.entries(pools)) {
      const triggers = (pool as any).Properties?.LambdaConfig ?? {};
      expect(triggers.PreTokenGeneration).toBeUndefined();
      expect(triggers.PreTokenGenerationConfig).toBeUndefined();
    }
  });

  test('Hosted UI domain is provisioned (R1.6)', () => {
    template.hasResourceProperties('AWS::Cognito::UserPoolDomain', {
      Domain: 'mdc-mcp-external-alt',
    });
  });

  test('resource server declares exactly the two custom scopes (R1.3)', () => {
    template.resourceCountIs('AWS::Cognito::UserPoolResourceServer', 1);
    template.hasResourceProperties('AWS::Cognito::UserPoolResourceServer', {
      Identifier: 'mcp',
      Scopes: Match.arrayWith([
        Match.objectLike({ ScopeName: 'ci-readonly' }),
        Match.objectLike({ ScopeName: 'hpc-user' }),
      ]),
    });
    // Exactly two scopes — no more.
    const servers = template.findResources('AWS::Cognito::UserPoolResourceServer');
    for (const [, srv] of Object.entries(servers)) {
      expect((srv as any).Properties.Scopes).toHaveLength(2);
    }
  });

  test('CI app client is client-credentials only, generates a secret (R1.4)', () => {
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
      ClientName: 'mdc-mcp-ci',
      GenerateSecret: true,
      AllowedOAuthFlows: ['client_credentials'],
      AllowedOAuthScopes: Match.arrayWith([
        Match.objectLike({ 'Fn::Join': Match.arrayWith([Match.arrayWith(['/ci-readonly'])]) }),
      ]),
      // client-credentials clients carry no interactive ExplicitAuthFlows.
    });
  });

  test('HPC app client is auth-code + SRP, no secret, no client-credentials (R1.5)', () => {
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
      ClientName: 'mdc-mcp-hpc',
      GenerateSecret: false,
      AllowedOAuthFlows: ['code'],
      AllowedOAuthScopes: Match.arrayWith([
        Match.objectLike({ 'Fn::Join': Match.arrayWith([Match.arrayWith(['/hpc-user'])]) }),
      ]),
      ExplicitAuthFlows: Match.arrayWith(['ALLOW_USER_SRP_AUTH', 'ALLOW_REFRESH_TOKEN_AUTH']),
      CallbackURLs: Match.arrayWith([
        'http://127.0.0.1:8765/callback',
        'http://localhost:8765/callback',
      ]),
    });
    // Assert the HPC client does NOT enable client-credentials or ROPC.
    const clients = template.findResources('AWS::Cognito::UserPoolClient');
    for (const [, c] of Object.entries(clients)) {
      const props = (c as any).Properties;
      if (props.ClientName === 'mdc-mcp-hpc') {
        expect(props.AllowedOAuthFlows).not.toContain('client_credentials');
        expect(props.ExplicitAuthFlows ?? []).not.toContain('ALLOW_USER_PASSWORD_AUTH');
      }
    }
  });

  test('CI client secret stored in Secrets Manager with DeletionPolicy Retain (R9.3, R9.4)', () => {
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: 'mdc-mcp-external-access-alt/ci-app-client',
    });
    const secrets = template.findResources('AWS::SecretsManager::Secret');
    for (const [, s] of Object.entries(secrets)) {
      expect((s as any).DeletionPolicy).toBe('Retain');
    }
  });

  test('R9.5: no existing stateful resource types are present in this stack', () => {
    const resources = template.toJSON().Resources as Record<string, any>;
    const forbidden = ['AWS::Neptune::', 'AWS::OpenSearchService::', 'AWS::S3::Bucket', 'AWS::EFS::'];
    for (const [, r] of Object.entries(resources)) {
      for (const prefix of forbidden) {
        expect(r.Type.startsWith(prefix)).toBe(false);
      }
    }
  });

  test('R9.10: still no DynamoDB table after Cognito is added', () => {
    template.resourceCountIs('AWS::DynamoDB::Table', 0);
  });
});

describe('MdcExternalAccessAlternativeStack — Task 3 GitHub OIDC role (imported per C7/C11)', () => {
  const template = Template.fromStack(buildStack());

  test('no IAM roles are created in-stack (C7, C11, C12) — PowerUser cannot iam:CreateRole', () => {
    // The federated CI role, the Token_Broker execution role, and the
    // authorizer custom-resource role are ALL admin-created and imported.
    // The stack must not synthesize any AWS::IAM::Role (which would require
    // iam:CreateRole at deploy). C12: the CI secret is populated out-of-band
    // so no Custom::DescribeCognitoUserPoolClient auto-role appears either.
    template.resourceCountIs('AWS::IAM::Role', 0);
  });

  test('no federated GitHub role principal is declared in-stack (C11)', () => {
    const roles = template.findResources('AWS::IAM::Role');
    for (const [, r] of Object.entries(roles)) {
      const doc = JSON.stringify((r as any).Properties?.AssumeRolePolicyDocument ?? {});
      expect(doc).not.toContain('token.actions.githubusercontent.com');
    }
  });

  test('CiOidcRoleArn output references the admin-created federated role name', () => {
    template.hasOutput('CiOidcRoleArn', {
      Value: Match.objectLike({
        'Fn::Join': Match.arrayWith([
          Match.arrayWith([Match.stringLikeRegexp('role/mdc-mcp-alt-gh-oidc-ci')]),
        ]),
      }),
    });
  });
});

describe('MdcExternalAccessAlternativeStack — Task 4 Token_Broker Lambda', () => {
  const template = Template.fromStack(buildStack());

  test('Python 3.12 broker function with reserved concurrency and no DynamoDB (R3.3, R9.10)', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'mdc-mcp-alt-token-broker',
      Runtime: 'python3.12',
      Handler: 'index.handler',
      ReservedConcurrentExecutions: 10,
      Timeout: 10,
    });
    template.resourceCountIs('AWS::DynamoDB::Table', 0); // AD-3, R9.10
  });

  test('broker environment carries the allowlist, token endpoint, and secret ARN (R3.10)', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      Environment: {
        Variables: Match.objectLike({
          // globs converted to anchored regexes
          ALLOWED_SUB_PATTERNS_JSON: Match.stringLikeRegexp('refs/heads/\\.\\*'),
          COGNITO_TOKEN_ENDPOINT: Match.objectLike({
            'Fn::Join': Match.arrayWith([Match.arrayWith([Match.stringLikeRegexp('/oauth2/token$')])]),
          }),
        }),
      },
    });
  });

  test('broker uses the imported execution role — no in-stack role created (C7)', () => {
    template.resourceCountIs('AWS::IAM::Role', 0);
    template.hasResourceProperties('AWS::Lambda::Function', {
      Role: Match.objectLike({
        'Fn::Join': Match.arrayWith([
          Match.arrayWith([Match.stringLikeRegexp('role/mdc-mcp-alt-token-broker-role')]),
        ]),
      }),
    });
  });

  test('function resource policy grants invoke only to the federated OIDC role (R3.2)', () => {
    template.hasResourceProperties('AWS::Lambda::Permission', {
      Action: 'lambda:InvokeFunction',
      Principal: Match.objectLike({
        'Fn::Join': Match.arrayWith([
          Match.arrayWith([Match.stringLikeRegexp('role/mdc-mcp-alt-gh-oidc-ci')]),
        ]),
      }),
    });
  });

  test('Token_Broker log group is RETAIN with 90-day retention (R9.3)', () => {
    template.hasResource('AWS::Logs::LogGroup', {
      Properties: Match.objectLike({
        LogGroupName: '/mdc-mcp-rag-alt/token-broker',
        RetentionInDays: 90,
      }),
      DeletionPolicy: 'Retain',
    });
  });
});

describe('MdcExternalAccessAlternativeStack — Task 5 authorizer + drift', () => {
  const template = Template.fromStack(buildStack());

  // The AwsCustomResource `Update` prop is an Fn::Join (it embeds Cognito
  // tokens); assert literal substrings live inside one of its chunks.
  const updateContains = (needle: string) =>
    template.hasResourceProperties('Custom::AWS', {
      Update: Match.objectLike({
        'Fn::Join': Match.arrayWith([Match.arrayWith([Match.stringLikeRegexp(needle)])]),
      }),
    });

  test('a Custom::AWS resource calls updateAgentRuntime with a customJWTAuthorizer (R2.1, R2.8)', () => {
    template.resourceCountIs('Custom::AWS', 1);
    updateContains('updateAgentRuntime');
    updateContains('customJWTAuthorizer');
  });

  test('C9: the update payload is lossless — network, artifact, role, protocol, env carried', () => {
    for (const needle of [
      'agentRuntimeId',
      'agentRuntimeArtifact',
      'python-tenants-v11',
      'mdc-mcp-rag-ecs-task-role',
      'networkConfiguration',
      'sg-096489a0876cc78c1',
      'subnet-0e13af6b3a9a6416f',
      'requireServiceS3Endpoint',
      'serverProtocol',
      'MCP_WORKFLOW_ROOT',
      'NEPTUNE_ENDPOINT',
    ]) {
      updateContains(needle);
    }
  });

  test('C7: authorizer custom resource uses the imported role — still zero in-stack roles', () => {
    template.resourceCountIs('AWS::IAM::Role', 0);
  });

  test('drift-detector alarm watches the AuthorizerDrift metric (R2.8, R9.9)', () => {
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: 'mdc-mcp-alt-authorizer-drift',
      Namespace: 'MdcMcpExternalAccessAlt',
      MetricName: 'AuthorizerDrift',
      Threshold: 1,
      ComparisonOperator: 'GreaterThanOrEqualToThreshold',
    });
  });

  test('McpEndpointUrl output is a well-formed AgentCore invocation URL', () => {
    // buildStack uses a placeholder runtime ARN; bin/cdk.ts uses the real
    // Python runtime ARN (C1). Assert the URL structure + encoded ARN here.
    template.hasOutput('McpEndpointUrl', {
      Value: Match.stringLikeRegexp('https://bedrock-agentcore\\..*/runtimes/.*runtime.*/invocations\\?qualifier=DEFAULT'),
    });
  });

  test('the authorizer config snapshot artifact exists on disk (R2.8)', () => {
    const snap = path.join(__dirname, '..', 'snapshots', 'authorizer-config.json');
    expect(fs.existsSync(snap)).toBe(true);
    const parsed = JSON.parse(fs.readFileSync(snap, 'utf8'));
    expect(parsed.customJWTAuthorizer).toBeDefined();
    expect(parsed.customJWTAuthorizer.allowedClients).toHaveLength(2);
  });
});
