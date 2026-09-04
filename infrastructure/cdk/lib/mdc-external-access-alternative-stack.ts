import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as path from 'path';
import { Construct } from 'constructs';

/**
 * Props for {@link MdcExternalAccessAlternativeStack}.
 *
 * Spec: .kiro/specs/mcp-external-access-revised/ (Path B — Cognito JWT on the
 * AgentCore Runtime). Design §12.1, AD-4.
 */
export interface MdcExternalAccessAlternativeStackProps extends cdk.StackProps {
  /**
   * ARN of the existing AgentCore Runtime the JWT authorizer is attached to.
   * NOTE (Correction C1): the active runtime is the PYTHON runtime
   * `mdc_mcp_rag_server_python-v5K2F8BGrN` (52 tools), not the Node runtime the
   * design text sometimes cites.
   */
  readonly runtimeArn: string;

  /**
   * The MCP_Server task role (imported from MdcSecurityStack). Used to attach
   * the audit log-group write policy in a later task without redefining the
   * role. May be undefined in unit tests.
   */
  readonly mcpServerTaskRole?: iam.IRole;

  /**
   * Allowlist of GitHub OIDC `sub` patterns permitted to assume the federated
   * CI role (R3.1). Example:
   *   ['repo:NOAA-EMC/global-workflow:ref:refs/heads/*', ...]
   */
  readonly allowedGithubSubPatterns: string[];
}

/**
 * MdcExternalAccessAlternativeStack — Path B external access.
 *
 * Attaches a Cognito-backed JWT authorizer to the existing AgentCore Runtime
 * and provisions the CI (client-credentials) and HPC (auth-code + PKCE / SRP)
 * consumer paths. The developer SigV4 path is preserved (R7).
 *
 * This is the scoped ALTERNATIVE stack (AD-4) — named distinctly from the
 * original `MdcExternalAccessStack` so both can coexist without logical-ID or
 * stack-name collisions.
 *
 * Data-safety posture (steering 05 / R9): every stateful construct sets
 * removalPolicy: RETAIN. This stack contains NO DynamoDB table and NO
 * Cognito Pre-Token-Generation trigger (AD-3, R9.10).
 */
export class MdcExternalAccessAlternativeStack extends cdk.Stack {
  /** Cognito user pool that issues the CI/HPC JWTs (R1.1). */
  public readonly userPool: cognito.UserPool;
  /** Hosted UI domain serving the HPC auth-code + PKCE pages (R1.6). */
  public readonly userPoolDomain: cognito.UserPoolDomain;
  /** CI machine-to-machine client (client-credentials, mcp/ci-readonly) (R1.4). */
  public readonly ciAppClient: cognito.UserPoolClient;
  /** HPC client (auth-code + PKCE primary, SRP fallback, mcp/hpc-user) (R1.5). */
  public readonly hpcAppClient: cognito.UserPoolClient;
  /** Secrets Manager secret holding the CI client id + secret (R9.3). */
  public readonly ciAppClientSecret: secretsmanager.Secret;
  /**
   * GitHub-OIDC federated CI role (R3.1). Imported, NOT created here: the
   * account has no `token.actions.githubusercontent.com` OIDC provider (C10)
   * and PowerUser cannot `iam:CreateRole` (C7). The role + its trust policy
   * are admin-created per docs/mdc-external-access-alt-iam-request.txt and
   * referenced here by name.
   */
  public readonly ciOidcRole: iam.IRole;
  /** Token_Broker Lambda — GitHub OIDC → Cognito CI JWT exchange (R3.2, R3.3). */
  public readonly tokenBroker: lambda.Function;

  constructor(scope: Construct, id: string, props: MdcExternalAccessAlternativeStackProps) {
    super(scope, id, props);

    // ── Cognito user pool (R1.1, R1.2) ─────────────────────────────────────
    // NOTE: intentionally NO lambdaTriggers.preTokenGeneration — the M2M
    // Pre-Token-Generation trigger from the original design is removed
    // (AD-3, R9.10). CI attribution is the Token_Broker log-join instead.
    this.userPool = new cognito.UserPool(this, 'McpUserPool', {
      userPoolName: 'mdc-mcp-external-access-alt',
      selfSignUpEnabled: false, // admin-only provisioning of HPC users
      signInAliases: { email: true, username: true },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      passwordPolicy: {
        minLength: 14,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
        tempPasswordValidity: cdk.Duration.days(1),
      },
      mfa: cognito.Mfa.OPTIONAL,
      mfaSecondFactor: { sms: false, otp: true },
      advancedSecurityMode: cognito.AdvancedSecurityMode.ENFORCED,
      removalPolicy: cdk.RemovalPolicy.RETAIN, // R1.2, R9.2 — steering 05
    });

    // ── Hosted UI domain (R1.6) ────────────────────────────────────────────
    // → mdc-mcp-external-alt.auth.us-east-1.amazoncognito.com
    this.userPoolDomain = this.userPool.addDomain('McpUserPoolDomain', {
      cognitoDomain: { domainPrefix: 'mdc-mcp-external-alt' },
    });

    // ── Resource server + the two custom scopes (R1.3) ─────────────────────
    const ciReadonlyScope = new cognito.ResourceServerScope({
      scopeName: 'ci-readonly',
      scopeDescription: 'CI read-only access to MCP server analysis tools',
    });
    const hpcUserScope = new cognito.ResourceServerScope({
      scopeName: 'hpc-user',
      scopeDescription: 'HPC user access including GraphRAG and GitHub integration',
    });
    const resourceServer = this.userPool.addResourceServer('McpResourceServer', {
      identifier: 'mcp',
      userPoolResourceServerName: 'MCP Server Scopes',
      scopes: [ciReadonlyScope, hpcUserScope], // exactly these two custom scopes
    });
    // Fully-qualified scope strings: mcp/ci-readonly and mcp/hpc-user.

    // ── CI app client — client-credentials ONLY (R1.4, R1.8, R3.8) ─────────
    this.ciAppClient = this.userPool.addClient('CiAppClient', {
      userPoolClientName: 'mdc-mcp-ci',
      generateSecret: true, // R1.4 — generated client secret
      oAuth: {
        flows: {
          clientCredentials: true,
          authorizationCodeGrant: false,
          implicitCodeGrant: false,
        },
        scopes: [cognito.OAuthScope.resourceServer(resourceServer, ciReadonlyScope)],
      },
      // All non-OAuth auth flows disabled — plain M2M token, no ROPC/SRP.
      authFlows: {
        adminUserPassword: false,
        userPassword: false,
        userSrp: false,
        custom: false,
      },
      accessTokenValidity: cdk.Duration.minutes(60), // R1.8, R3.8 (300–3600 s)
      // NOTE: no access-token-customization trigger — plain M2M token (AD-3).
    });

    // ── HPC app client — auth-code + PKCE primary, SRP fallback (R1.5) ─────
    this.hpcAppClient = this.userPool.addClient('HpcAppClient', {
      userPoolClientName: 'mdc-mcp-hpc',
      generateSecret: false, // public client → Cognito enforces PKCE on the code exchange
      oAuth: {
        flows: {
          clientCredentials: false, // R1.5 — disabled
          authorizationCodeGrant: true, // R1.5 — primary (PKCE enforced for public client)
          implicitCodeGrant: false,
        },
        scopes: [cognito.OAuthScope.resourceServer(resourceServer, hpcUserScope)],
        callbackUrls: [
          'http://127.0.0.1:8765/callback', // RFC 8252 loopback (primary transport)
          'http://localhost:8765/callback', // loopback alias; manual-paste reuses this redirect
        ],
      },
      authFlows: {
        userSrp: true, // R1.5 — USER_SRP_AUTH fallback enabled
        userPassword: false, // R1.5 — ROPC / USER_PASSWORD_AUTH disabled
        adminUserPassword: false,
        custom: false,
      },
      enableTokenRevocation: true,
      accessTokenValidity: cdk.Duration.minutes(60), // R1.8, R4.11 (300–3600 s)
    });

    // ── CI client secret in Secrets Manager (R9.3) ─────────────────────────
    // The Token_Broker reads {client_id, client_secret} at runtime; the
    // MCP_Server task role has no access to this secret.
    //
    // Correction C12: we intentionally do NOT pull `ciAppClient.userPoolClientSecret`
    // into the secret here. Doing so makes CDK emit a
    // `Custom::DescribeCognitoUserPoolClient` resource backed by an
    // AUTO-CREATED Lambda role — which requires iam:CreateRole at deploy and
    // is blocked for PowerUser (C7). Instead the secret is a RETAIN shell
    // holding the (non-secret) client_id plus a placeholder; the real
    // client_secret is injected out-of-band by the documented one-time step
    // in docs/mdc-external-access-alt-iam-request.txt. This also keeps the
    // client secret out of CloudFormation/custom-resource state entirely
    // (defence in depth).
    this.ciAppClientSecret = new secretsmanager.Secret(this, 'CiAppClientSecret', {
      secretName: 'mdc-mcp-external-access-alt/ci-app-client',
      description: 'Cognito CI app-client id + secret for the MCP Token_Broker (client_secret populated out-of-band — see admin doc)',
      secretObjectValue: {
        client_id: cdk.SecretValue.unsafePlainText(this.ciAppClient.userPoolClientId),
        client_secret: cdk.SecretValue.unsafePlainText('REPLACE_VIA_PUT_SECRET_VALUE'),
      },
    });
    this.ciAppClientSecret.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN); // R9.3 — stateful

    // ── GitHub OIDC federated CI role (R3.1) — IMPORTED (C7, C10, C11) ─────
    // The GitHub Actions OIDC provider (token.actions.githubusercontent.com)
    // does NOT exist in this account (only a GitLab provider is present), and
    // PowerUser cannot create IAM roles or OIDC providers. Admin creates both
    // per docs/mdc-external-access-alt-iam-request.txt with the trust policy:
    //   Federated: <account>:oidc-provider/token.actions.githubusercontent.com
    //   aud (StringEquals): sts.amazonaws.com
    //   sub (StringLike): props.allowedGithubSubPatterns  (R3.1 allowlist)
    // We reference the role by name; its ARN feeds the composite-action input
    // and the Token_Broker invoke resource policy (Task 4).
    this.ciOidcRole = iam.Role.fromRoleName(this, 'CiOidcRole', 'mdc-mcp-alt-gh-oidc-ci', {
      mutable: false,
    });

    // ── Token_Broker Lambda (R3.2, R3.3) — simplified, NO DynamoDB ─────────
    // Log group is a stateful resource → RETAIN, 90-day retention (R9.3).
    const tokenBrokerLogGroup = new logs.LogGroup(this, 'TokenBrokerLogGroup', {
      logGroupName: '/mdc-mcp-rag-alt/token-broker',
      retention: logs.RetentionDays.THREE_MONTHS,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // Execution role is admin-created + imported (C7, C11): PowerUser cannot
    // iam:CreateRole. Passing `role` here prevents CDK from auto-creating one.
    const tokenBrokerRole = iam.Role.fromRoleName(
      this,
      'TokenBrokerRole',
      'mdc-mcp-alt-token-broker-role',
      { mutable: false },
    );

    // Convert the GitHub `sub` allowlist globs into anchored regexes for the
    // handler's ALLOWED_SUB_PATTERNS_JSON (R3.10). Only `*` is a wildcard.
    const subPatternRegexes = props.allowedGithubSubPatterns.map(
      (glob) => '^' + glob.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\\\*/g, '.*') + '$',
    );

    this.tokenBroker = new lambda.Function(this, 'TokenBroker', {
      functionName: 'mdc-mcp-alt-token-broker',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', 'lambda', 'token_broker')),
      role: tokenBrokerRole, // imported — no auto-role created (C7)
      logGroup: tokenBrokerLogGroup,
      timeout: cdk.Duration.seconds(10),
      memorySize: 256,
      reservedConcurrentExecutions: 10, // bursty but low-volume CI (design §4.6)
      environment: {
        ALLOWED_SUB_PATTERNS_JSON: JSON.stringify(subPatternRegexes),
        COGNITO_TOKEN_ENDPOINT: `https://${this.userPoolDomain.domainName}.auth.${this.region}.amazoncognito.com/oauth2/token`,
        CI_CLIENT_SECRET_ARN: this.ciAppClientSecret.secretArn,
      },
    });

    // R3.2: the function resource policy permits invocation only by the
    // GitHub-OIDC federated role. (grantInvoke would no-op on the immutable
    // imported role; a resource-based permission is the correct instrument.)
    this.tokenBroker.addPermission('AllowCiOidcRoleInvoke', {
      principal: new iam.ArnPrincipal(this.ciOidcRole.roleArn),
      action: 'lambda:InvokeFunction',
    });

    // ── AgentCore Runtime JWT authorizer (R2.1, R2.8) ──────────────────────
    //
    // *** DUAL-AUTH RISK — Correction C8 — DO NOT DEPLOY UNVERIFIED ***
    // The spec (R2.9/R7.2) assumes AgentCore accepts SigV4 *alongside* a JWT
    // authorizer on the same Runtime. The Task 0 gate returned HTTP 403
    // "Authorization method mismatch ... (OAuth or SigV4)", which suggests an
    // AgentCore Runtime enforces a SINGLE inbound auth mode. If so, attaching
    // this authorizer BREAKS the developer SigV4 path (R7/C6). This must be
    // verified (throwaway runtime or AWS confirmation) BEFORE `cdk deploy`; if
    // single-mode is confirmed, pivot to the Path C Gateway fallback (design
    // §11.3 / R8.6). This resource is authored per spec but the stack is NOT
    // deployed in this engagement.
    //
    // *** FULL-REPLACEMENT PAYLOAD — Correction C9 ***
    // update-agent-runtime REQUIRES agent-runtime-id, agent-runtime-artifact,
    // role-arn, and network-configuration. Passing only authorizerConfiguration
    // would wipe them. We carry the complete config captured live 2026-07-27
    // PLUS the new authorizerConfiguration.
    const runtimeId = props.runtimeArn.split('/').pop() as string;
    const discoveryUrl = `https://cognito-idp.${this.region}.amazonaws.com/${this.userPool.userPoolId}/.well-known/openid-configuration`;
    const allowedClientIds = [this.ciAppClient.userPoolClientId, this.hpcAppClient.userPoolClientId];

    // Custom-resource provider role is admin-created + imported (C7): passing
    // `role` prevents CDK from auto-creating one. Its perms
    // (bedrock-agentcore-control:UpdateAgentRuntime/GetAgentRuntime on this
    // runtime only) are in docs/mdc-external-access-alt-iam-request.txt (role #4).
    const authorizerCrRole = iam.Role.fromRoleName(
      this,
      'AuthorizerCrRole',
      'mdc-mcp-alt-authorizer-cr-role',
      { mutable: false },
    );

    const updateRuntimeParams = {
      agentRuntimeId: runtimeId,
      // --- carried losslessly (C9) ---
      agentRuntimeArtifact: {
        containerConfiguration: {
          containerUri: '903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-tenants-v11',
        },
      },
      roleArn: 'arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role',
      networkConfiguration: {
        networkMode: 'VPC',
        networkModeConfig: {
          securityGroups: ['sg-096489a0876cc78c1'],
          subnets: ['subnet-0e13af6b3a9a6416f', 'subnet-04447750c61bd7e06'],
          requireServiceS3Endpoint: true,
        },
      },
      protocolConfiguration: { serverProtocol: 'MCP' },
      lifecycleConfiguration: { idleRuntimeSessionTimeout: 900, maxLifetime: 28800 },
      environmentVariables: {
        AWS_REGION: 'us-east-1',
        DB_BACKEND: 'aws',
        MCP_STATELESS_HTTP: 'true',
        MCP_WORKFLOW_ROOT: '/mnt/workflow',
        NEPTUNE_ENDPOINT:
          'https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182',
        OPENSEARCH_ENDPOINT:
          'https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com',
      },
      // --- the new authorizer (R2.1, R2.3) ---
      authorizerConfiguration: {
        customJWTAuthorizer: {
          discoveryUrl,
          allowedAudience: allowedClientIds,
          allowedClients: allowedClientIds,
        },
      },
    };

    const authorizerUpdate = new cr.AwsCustomResource(this, 'AgentCoreAuthorizerUpdate', {
      role: authorizerCrRole, // imported — no auto-role (C7)
      onUpdate: {
        service: 'bedrock-agentcore-control',
        action: 'updateAgentRuntime',
        parameters: updateRuntimeParams,
        physicalResourceId: cr.PhysicalResourceId.of(`AgentCoreAuthorizerUpdate-${runtimeId}`),
      },
      // Type-required even when `role` is provided; on the immutable imported
      // role this is a no-op (the role's perms come from the admin doc).
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: [
            'bedrock-agentcore-control:UpdateAgentRuntime',
            'bedrock-agentcore-control:GetAgentRuntime',
          ],
          resources: [props.runtimeArn],
        }),
      ]),
    });
    authorizerUpdate.node.addDependency(this.userPoolDomain, this.ciAppClient, this.hpcAppClient);

    // ── Drift detector alarm (R2.8, R9.9) ──────────────────────────────────
    // The nightly drift script (infrastructure/cdk/scripts/authorizer-drift-detector.sh)
    // diffs the live authorizer config against snapshots/authorizer-config.json
    // and puts the metric below. Every `cdk deploy` re-applies updateAgentRuntime,
    // restoring the CDK-defined state (R2.8).
    const driftMetric = new cloudwatch.Metric({
      namespace: 'MdcMcpExternalAccessAlt',
      metricName: 'AuthorizerDrift',
      period: cdk.Duration.hours(24),
      statistic: 'Maximum',
    });
    new cloudwatch.Alarm(this, 'AuthorizerDriftAlarm', {
      alarmName: 'mdc-mcp-alt-authorizer-drift',
      alarmDescription:
        'AgentCore Runtime JWT authorizer config drifted from the CDK snapshot. Next cdk deploy restores it.',
      metric: driftMetric,
      threshold: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      evaluationPeriods: 1,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    // ── Outputs (design §12.3) ─────────────────────────────────────────────
    new cdk.CfnOutput(this, 'HpcUserPoolId', {
      value: this.userPool.userPoolId,
      description: 'Cognito user pool id (HPC Runbook, HPC_CLI_Helper config)',
    });
    new cdk.CfnOutput(this, 'HpcAppClientId', {
      value: this.hpcAppClient.userPoolClientId,
      description: 'HPC app client id (auth-code + PKCE / SRP)',
    });
    new cdk.CfnOutput(this, 'CiAppClientId', {
      value: this.ciAppClient.userPoolClientId,
      description: 'CI app client id (client-credentials)',
    });
    new cdk.CfnOutput(this, 'HpcUserPoolDomain', {
      value: `${this.userPoolDomain.domainName}.auth.${this.region}.amazoncognito.com`,
      description: 'Cognito Hosted UI domain (PKCE flow)',
    });
    new cdk.CfnOutput(this, 'CiAppClientSecretArn', {
      value: this.ciAppClientSecret.secretArn,
      description: 'Secrets Manager ARN of the CI app-client secret',
    });
    new cdk.CfnOutput(this, 'CiOidcRoleArn', {
      value: this.ciOidcRole.roleArn,
      description: 'GitHub-OIDC federated CI role ARN (imported; admin-created)',
    });
    new cdk.CfnOutput(this, 'CiTokenBrokerFunctionName', {
      value: this.tokenBroker.functionName,
      description: 'Token_Broker Lambda name (composite action default)',
    });
    // NOTE: The canonical McpEndpointUrl export now lives in MdcMcpGatewayStack
    // (Path C), pointing at the Gateway endpoint. This output is retained for
    // reference but uses a distinct export name to avoid CloudFormation conflict.
    new cdk.CfnOutput(this, 'McpRuntimeDirectUrl', {
      value: `https://bedrock-agentcore.${this.region}.amazonaws.com/runtimes/${encodeURIComponent(props.runtimeArn)}/invocations?qualifier=DEFAULT`,
      description: 'AgentCore Runtime direct URL (developer SigV4 path — bypasses Gateway)',
      exportName: 'McpRuntimeDirectUrl',
    });

    void props;
  }
}
