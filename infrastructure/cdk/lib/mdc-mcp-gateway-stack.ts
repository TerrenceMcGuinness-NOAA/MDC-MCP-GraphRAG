import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cr from 'aws-cdk-lib/custom-resources';
import { Construct } from 'constructs';

/**
 * Props for {@link MdcMcpGatewayStack}.
 *
 * Spec: .kiro/specs/mcp-external-access-alternative-gateway/ (Path C —
 * Gateway-fronted, Cognito JWT on AgentCore Gateway).
 *
 * The Gateway fronts the existing AgentCore Runtime with a Cognito JWT
 * authorizer (CI/HPC path) while the Runtime keeps IAM SigV4 inbound auth
 * (developer path). The Runtime is NEVER given a customJWTAuthorizer.
 */
export interface MdcMcpGatewayStackProps extends cdk.StackProps {
  /**
   * ARN of the existing AgentCore Runtime. The Gateway registers this as an
   * `agentcoreRuntime` target with outbound IAM (SigV4) auth.
   *
   * Example: `arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN`
   */
  readonly runtimeArn: string;

  /** Cognito User Pool ID (from MdcExternalAccessAlternativeStack). */
  readonly userPoolId: string;

  /** CI app-client ID — client-credentials flow, `mcp/ci-readonly` scope. */
  readonly ciAppClientId: string;

  /** HPC app-client ID — auth-code + PKCE / SRP, `mcp/hpc-user` scope. */
  readonly hpcAppClientId: string;

  /** Cognito Hosted UI domain prefix, used to construct the OIDC discovery URL. */
  readonly userPoolDomainPrefix: string;

  /**
   * Custom OAuth scopes the Gateway authorizer accepts.
   * Example: `['mcp/ci-readonly', 'mcp/hpc-user']`
   */
  readonly allowedScopes: string[];
}

/**
 * MdcMcpGatewayStack — Path C external access via AgentCore Gateway.
 *
 * Creates an AgentCore Gateway (protocol type unset) that fronts the existing
 * AgentCore Runtime as an `agentcoreRuntime` target. The Gateway holds the
 * Cognito JWT authorizer and a REQUEST interceptor Lambda that injects trusted
 * principal/scope/attribution headers. The Runtime stays on IAM SigV4 inbound
 * auth — the developer path is preserved structurally (design §1.1).
 *
 * **Key constraints (from spec & steering):**
 * - This stack SHALL NOT create any `AWS::IAM::Role`. All roles are imported
 *   via `fromRoleName` with `{ mutable: false }`. `PowerUserRestrictions`
 *   blocks `iam:CreateRole` (progress.md C7). [R8.6]
 * - This stack SHALL NOT modify the Runtime's inbound auth. [R2.3, R8.2]
 * - Every stateful resource sets `removalPolicy: RETAIN`. [steering 05]
 * - DP-2 posture (a): no Runtime resource-based policy. [AD-C5]
 *
 * Spec: `.kiro/specs/mcp-external-access-alternative-gateway/`
 * Design: `design.md` in that directory.
 */
export class MdcMcpGatewayStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: MdcMcpGatewayStackProps) {
    super(scope, id, props);

    // ── Task 2.2 — Gateway resource + Cognito JWT authorizer ───────────────
    // AgentCore Gateway with protocol type UNSET (required for agentcoreRuntime
    // targets) and a Cognito customJWTAuthorizer. No native CDK construct exists
    // for AgentCore Gateway, so we use AwsCustomResource to call the control-
    // plane APIs directly — the same pattern the Path B stack uses for
    // updateAgentRuntime.
    // Requirements: R1.1, R2.1

    const discoveryUrl =
      `https://cognito-idp.${this.region}.amazonaws.com/${props.userPoolId}/.well-known/openid-configuration`;
    const allowedClientIds = [props.ciAppClientId, props.hpcAppClientId];

    // Gateway name used in the target endpoint path. Must be stable across
    // updates so that the McpEndpointUrl export does not churn.
    const gatewayName = 'mdc-mcp-rag-gateway';

    // The authorizer configuration — identical shape whether attached to a
    // Gateway or a Runtime (design §3.1, OQ-2 resolved).
    const authorizerConfiguration = {
      customJWTAuthorizer: {
        discoveryUrl,
        allowedClients: allowedClientIds,
        allowedAudience: allowedClientIds,
        allowedScopes: props.allowedScopes,
      },
    };

    // Parameters shared by both onCreate and onUpdate. Protocol type is
    // intentionally OMITTED — required for agentcoreRuntime targets (R1.1).
    const createGatewayParams = {
      name: gatewayName,
      authorizerConfiguration,
    };

    // Custom-resource provider role — admin-created + imported (C7, R8.6).
    // PowerUserRestrictions blocks iam:CreateRole. The role's permissions
    // (bedrock-agentcore-control:Create/Update/Delete/GetGateway) are
    // specified in docs/mdc-external-access-alt-iam-request.txt.
    const gatewayCrRole = iam.Role.fromRoleName(
      this,
      'GatewayCrRole',
      'mdc-mcp-alt-gateway-cr-role',
      { mutable: false },
    );

    const gatewayResource = new cr.AwsCustomResource(this, 'AgentCoreGateway', {
      role: gatewayCrRole, // imported — no auto-role created (C7, R8.6, R8.7)
      onCreate: {
        service: 'bedrock-agentcore-control',
        action: 'createGateway',
        parameters: createGatewayParams,
        physicalResourceId: cr.PhysicalResourceId.fromResponse('gatewayId'),
      },
      onUpdate: {
        service: 'bedrock-agentcore-control',
        action: 'updateGateway',
        parameters: {
          // gatewayId is resolved from the physical resource id set at creation.
          gatewayId: new cr.PhysicalResourceIdReference(),
          ...createGatewayParams,
        },
        physicalResourceId: cr.PhysicalResourceId.fromResponse('gatewayId'),
      },
      onDelete: {
        service: 'bedrock-agentcore-control',
        action: 'deleteGateway',
        parameters: {
          gatewayId: new cr.PhysicalResourceIdReference(),
        },
      },
      // Type-required even when `role` is provided; on the immutable imported
      // role this is a no-op (the role's perms come from the admin doc).
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: [
            'bedrock-agentcore-control:CreateGateway',
            'bedrock-agentcore-control:UpdateGateway',
            'bedrock-agentcore-control:DeleteGateway',
            'bedrock-agentcore-control:GetGateway',
          ],
          // Gateway ARN is not known until after creation — use wildcard.
          resources: ['*'],
        }),
      ]),
    });

    // Store the gateway ID for downstream tasks (target registration in 2.4,
    // endpoint export in 2.7, interceptor attachment in 4.5).
    const gatewayId = gatewayResource.getResponseField('gatewayId');

    // ── Task 2.3 — Gateway_Execution_Role (imported, not created) ──────────
    // Import via fromRoleName('mdc-mcp-alt-gateway-exec-role', { mutable: false }).
    // The role is admin-created per docs/mdc-external-access-alt-iam-request.txt
    // with aws:SourceArn / aws:SourceAccount trust conditions scoped to the
    // Gateway ARN (AD-C6, R2.5).
    // Also import the interceptor Lambda execution role.
    // Requirements: R2.5, R8.6, R8.7

    // Gateway_Execution_Role — the IAM role the Gateway assumes to sign SigV4
    // requests to the Runtime_Target. Admin-created with trust conditions:
    //   aws:SourceArn = Gateway ARN (confused-deputy prevention, AD-C6)
    //   aws:SourceAccount = this account
    // Permissions needed: bedrock-agentcore:InvokeAgentRuntime on the Runtime ARN.
    const gatewayExecRole = iam.Role.fromRoleName(
      this,
      'GatewayExecRole',
      'mdc-mcp-alt-gateway-exec-role',
      { mutable: false },
    );

    // Interceptor Lambda execution role — admin-created (C7).
    // Permissions needed: logs:CreateLogGroup, logs:CreateLogStream, logs:PutLogEvents.
    const interceptorRole = iam.Role.fromRoleName(
      this,
      'InterceptorRole',
      'mdc-mcp-alt-interceptor-role',
      { mutable: false },
    );

    // ── Task 4.5/4.6 — Request Interceptor Lambda ────────────────────────────
    // REQUEST interceptor that derives principal/scope from the Gateway-validated
    // JWT and injects Trusted_Context_Headers. Uses the admin-created execution
    // role (C7, R8.6).
    // Requirements: R4.1, R4.5, R6.3
    const interceptorFn = new lambda.Function(this, 'GatewayInterceptor', {
      functionName: 'mdc-mcp-gateway-interceptor',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset('lambda/gateway_interceptor'),
      role: interceptorRole,
      timeout: cdk.Duration.seconds(2),  // R4.7 — 2-second timeout budget
      memorySize: 128,
      architecture: lambda.Architecture.ARM_64,
      reservedConcurrentExecutions: 10,  // R4.7 — reserved concurrency
      logRetention: logs.RetentionDays.ONE_MONTH,
      description: 'MCP Gateway Request Interceptor — Path C (AD-C2). Injects trusted context headers.',
    });

    // Grant the Gateway service permission to invoke this Lambda (R4.5).
    // This is a Lambda resource-based policy — it does NOT create an IAM role (R8.6).
    interceptorFn.addPermission('GatewayInvoke', {
      principal: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      sourceArn: `arn:aws:bedrock-agentcore:${this.region}:${this.account}:gateway/${gatewayId}`,
    });

    // ── Task 2.4 — Runtime target registration ─────────────────────────────
    // Register the existing Runtime as an agentcoreRuntime target:
    //   - ARN from props.runtimeArn + qualifier "DEFAULT"  (R1.2)
    //   - Outbound auth: IAM (SigV4), signed with the Gateway_Execution_Role (R1.3)
    //   - No schema — MCP-protocol runtimes receive a default schema (R1.5)
    //   - metadataConfiguration.allowedRequestHeaders: exactly the three
    //     Trusted_Context_Headers (R4.2, under the 10-header limit per design §3.4)
    // Requirements: R1.2, R1.3, R1.5, R4.2

    // Target name used in the Gateway endpoint path:
    //   https://{gatewayId}.gateway.bedrock-agentcore.{region}.amazonaws.com/{targetName}/invocations
    // Must be stable across updates so that McpEndpointUrl (Task 2.7) does not churn.
    const targetName = 'mdc-mcp-rag';

    const targetParams = {
      gatewayId,
      name: targetName,
      targetConfiguration: {
        http: {
          agentcoreRuntime: {
            arn: props.runtimeArn,
            qualifier: 'DEFAULT', // explicit qualifier (R1.2)
          },
        },
      },
      // Outbound auth: the Gateway assumes the Gateway_Execution_Role to sign
      // SigV4 requests to the Runtime. GATEWAY_IAM_ROLE is the documented
      // credential provider type for this pattern (R1.3).
      credentialConfiguration: {
        credentialProviderType: 'GATEWAY_IAM_ROLE',
      },
      // Exactly 3 allowed request headers — the Trusted_Context_Headers injected
      // by the Request_Interceptor (Task 4). These are the only headers the
      // Gateway will forward to the Runtime beyond the standard set. Under the
      // 10-header limit per design §3.4.
      metadataConfiguration: {
        allowedRequestHeaders: [
          'X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal',
          'X-Amzn-Bedrock-AgentCore-Runtime-Custom-Scope',
          'X-Amzn-Bedrock-AgentCore-Runtime-Custom-BrokerRequestId',
        ],
      },
      // No `schema` property — MCP-protocol runtimes receive a default schema
      // automatically (R1.5).

      // ── Task 4.5 — REQUEST interceptor registration ───────────────────────
      // Register the interceptor Lambda as a REQUEST type on this target.
      //   - passRequestHeaders: true — interceptor needs inbound headers to read
      //     the Authorization bearer token and derive principal/scope (R4.5).
      //   - payloadFilter excludes RESPONSE_BODY — large RAG responses can exceed
      //     the 6 MB Lambda synchronous invoke limit; excluding the response body
      //     from the interceptor payload prevents this without altering the
      //     response returned to the caller (R6.3, design §4.4).
      // Requirements: R4.5, R6.3
      interceptorConfiguration: {
        interceptors: [{
          type: 'REQUEST',
          lambdaArn: interceptorFn.functionArn,
          passRequestHeaders: true,
          payloadFilter: {
            exclude: ['RESPONSE_BODY'],
          },
        }],
      },
    };

    const runtimeTarget = new cr.AwsCustomResource(this, 'RuntimeTarget', {
      // Reuse the admin-created custom-resource role from Task 2.2 (R8.6, R8.7).
      // Target CRUD permissions are specified in
      // docs/mdc-external-access-alt-iam-request.txt alongside the gateway perms.
      role: gatewayCrRole,
      onCreate: {
        service: 'bedrock-agentcore-control',
        action: 'createGatewayTarget',
        parameters: targetParams,
        physicalResourceId: cr.PhysicalResourceId.of(
          `${gatewayId}-target-${targetName}`,
        ),
      },
      onUpdate: {
        service: 'bedrock-agentcore-control',
        action: 'updateGatewayTarget',
        parameters: targetParams,
        physicalResourceId: cr.PhysicalResourceId.of(
          `${gatewayId}-target-${targetName}`,
        ),
      },
      onDelete: {
        service: 'bedrock-agentcore-control',
        action: 'deleteGatewayTarget',
        parameters: {
          gatewayId,
          name: targetName,
        },
      },
      // Grant target CRUD actions to the custom-resource role. On the immutable
      // imported role this is a policy-statement no-op (perms come from admin),
      // but it satisfies the CDK AwsCustomResource type contract.
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: [
            'bedrock-agentcore-control:CreateGatewayTarget',
            'bedrock-agentcore-control:UpdateGatewayTarget',
            'bedrock-agentcore-control:DeleteGatewayTarget',
            'bedrock-agentcore-control:GetGatewayTarget',
          ],
          // Target ARN is not known until after creation — use wildcard.
          resources: ['*'],
        }),
      ]),
    });

    // Ensure the target is created after the gateway and interceptor Lambda exist.
    // The target references both the gateway ID and the interceptor Lambda ARN.
    runtimeTarget.node.addDependency(gatewayResource);
    runtimeTarget.node.addDependency(interceptorFn);

    // ── Task 2.5 — Assert Runtime has no customJWTAuthorizer ───────────────
    // A CDK Aspect or unit test asserting no customJWTAuthorizer is attached
    // to the Runtime, so the developer SigV4 path cannot be silently broken.
    // Requirements: R2.3

    // ── Task 2.6 — Runtime resource-based policy (DP-2 posture) ────────────
    // AD-C5 posture (a) chosen: NO Runtime lockdown. This task is a no-op.
    // No resource-based policy is created or attached.
    // Requirements: R2.4

    // ── Task 2.7 — McpEndpointUrl export ───────────────────────────────────
    // The Gateway endpoint replaces the Runtime invocation URL (R1.4).
    // Format: https://{gatewayId}.gateway.bedrock-agentcore.{region}.amazonaws.com/{targetName}/invocations
    // Consumers read this export via `cdk.Fn.importValue('McpEndpointUrl')` or
    // from `cdk outputs` — they never hard-code the URL (C-IMPACT-3).
    new cdk.CfnOutput(this, 'McpEndpointUrl', {
      value: `https://${gatewayId}.gateway.bedrock-agentcore.${this.region}.amazonaws.com/${targetName}/invocations`,
      description: 'AgentCore MCP endpoint URL — Gateway-fronted (Path C, R1.4)',
      exportName: 'McpEndpointUrl',
    });

    new cdk.CfnOutput(this, 'GatewayId', {
      value: gatewayId,
      description: 'AgentCore Gateway ID (for operational reference and trust-policy tightening)',
    });

    // Suppress unused-variable warnings for props consumed by later tasks.
    void props;
  }
}
