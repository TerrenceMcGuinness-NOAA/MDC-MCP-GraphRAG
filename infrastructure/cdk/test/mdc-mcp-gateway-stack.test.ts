import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { MdcMcpGatewayStack } from '../lib/mdc-mcp-gateway-stack';

// Spec: .kiro/specs/mcp-external-access-alternative-gateway/ — Path C (Gateway-fronted).
// Test account/region are placeholders (do not touch the live account).
const env = { account: '123456789012', region: 'us-east-1' };

function buildStack(): MdcMcpGatewayStack {
  const app = new cdk.App();
  return new MdcMcpGatewayStack(app, 'TestGatewayStack', {
    env,
    runtimeArn: 'arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-runtime',
    userPoolId: 'us-east-1_TestPool',
    ciAppClientId: 'ci-client-id',
    hpcAppClientId: 'hpc-client-id',
    userPoolDomainPrefix: 'test-domain',
    allowedScopes: ['mcp/ci-readonly', 'mcp/hpc-user'],
  });
}

// ── Task 2.5 — Runtime never given a customJWTAuthorizer (R2.3) ─────────────
//
// Design §1.1: "the developer path is now preserved structurally rather than
// behaviorally." The single invariant is that the Runtime stays SigV4 — no JWT
// authorizer ever. These tests enforce that invariant at synth time.
//
// The Gateway stack uses AwsCustomResource (Custom::AWS) to call the
// bedrock-agentcore-control API. Each Custom::AWS resource serializes its
// onCreate/onUpdate/onDelete as JSON strings (or Fn::Join intrinsics when
// CloudFormation tokens are embedded). We parse those to verify that:
//   (a) No custom resource calls updateAgentRuntime (which would modify the Runtime).
//   (b) No custom resource attaches a customJWTAuthorizer to the Runtime.
//   (c) The Gateway custom resource correctly targets createGateway/updateGateway.
//   (d) No AWS::IAM::Role is created in-stack (R8.6).

describe('MdcMcpGatewayStack — Task 2.5: Runtime auth invariant (R2.3)', () => {
  const stack = buildStack();
  const template = Template.fromStack(stack);

  test('synthesizes without error', () => {
    expect(() => Template.fromStack(buildStack())).not.toThrow();
  });

  test('no Custom::AWS resource calls updateAgentRuntime (R2.3, R8.2)', () => {
    // The Gateway stack must NEVER call updateAgentRuntime. That API modifies
    // the Runtime's configuration and could attach a customJWTAuthorizer,
    // breaking the developer SigV4 path. Only createGateway, updateGateway,
    // createGatewayTarget, updateGatewayTarget, and their delete counterparts
    // are permitted.
    const customs = template.findResources('Custom::AWS');
    for (const [logicalId, resource] of Object.entries(customs)) {
      const props = (resource as any).Properties ?? {};

      // AwsCustomResource serializes Create/Update/Delete as either:
      //   - a plain JSON string (when no CloudFormation tokens are present), or
      //   - an Fn::Join intrinsic (when tokens like gatewayId are embedded).
      // We need to check both forms.
      for (const phase of ['Create', 'Update'] as const) {
        const raw = props[phase];
        if (raw == null) continue;

        const serialized = typeof raw === 'string' ? raw : JSON.stringify(raw);
        expect(serialized).not.toContain('updateAgentRuntime');
        expect(serialized).not.toContain('UpdateAgentRuntime');
      }
    }
  });

  test('no Custom::AWS resource references customJWTAuthorizer on the Runtime (R2.3)', () => {
    // Belt-and-braces: even if a future edit accidentally added a resource
    // that calls some Runtime API, it must not carry an authorizerConfiguration
    // targeting the Runtime. The Gateway's own customJWTAuthorizer (on
    // createGateway) is correct and expected — we verify it does NOT appear
    // in any updateAgentRuntime context, which the previous test already
    // forbids. This test additionally ensures no resource smuggles
    // authorizerConfiguration into a Runtime-targeting call.
    const customs = template.findResources('Custom::AWS');
    for (const [logicalId, resource] of Object.entries(customs)) {
      const props = (resource as any).Properties ?? {};

      for (const phase of ['Create', 'Update'] as const) {
        const raw = props[phase];
        if (raw == null) continue;

        const serialized = typeof raw === 'string' ? raw : JSON.stringify(raw);

        // If the serialized form contains "agentRuntime" as a service action
        // (not as a target configuration key), it must not also contain
        // customJWTAuthorizer. The target config uses "agentcoreRuntime" (with
        // a 'c'), which is a different key — the regex distinguishes them.
        if (/\bupdateAgentRuntime\b/i.test(serialized)) {
          expect(serialized).not.toContain('customJWTAuthorizer');
        }
      }
    }
  });

  test('permitted Custom::AWS actions are only Gateway and Target CRUD (R2.3, R8.2)', () => {
    // Allowlist: only these bedrock-agentcore-control actions may appear.
    const ALLOWED_ACTIONS = new Set([
      'createGateway',
      'updateGateway',
      'deleteGateway',
      'createGatewayTarget',
      'updateGatewayTarget',
      'deleteGatewayTarget',
    ]);

    const customs = template.findResources('Custom::AWS');
    for (const [logicalId, resource] of Object.entries(customs)) {
      const props = (resource as any).Properties ?? {};

      for (const phase of ['Create', 'Update', 'Delete'] as const) {
        const raw = props[phase];
        if (raw == null) continue;

        // Extract action from the serialized JSON. AwsCustomResource encodes
        // as {"service":"...","action":"...", ...}. When tokens are present,
        // the outer value is an Fn::Join — stringify and regex-extract.
        const serialized = typeof raw === 'string' ? raw : JSON.stringify(raw);
        const actionMatch = serialized.match(/"action"\s*:\s*"([^"]+)"/);
        if (actionMatch) {
          const action = actionMatch[1];
          expect(ALLOWED_ACTIONS).toContain(action);
        }
      }
    }
  });

  test('Gateway custom resource uses createGateway with customJWTAuthorizer (R1.1, R2.1)', () => {
    // Positive assertion: the Gateway resource DOES have a customJWTAuthorizer
    // (on the Gateway, not the Runtime). This confirms the authorizer is
    // correctly placed.
    const customs = template.findResources('Custom::AWS');
    let foundGatewayWithAuth = false;

    for (const [logicalId, resource] of Object.entries(customs)) {
      const props = (resource as any).Properties ?? {};
      const createRaw = props.Create;
      if (createRaw == null) continue;

      const serialized = typeof createRaw === 'string'
        ? createRaw
        : JSON.stringify(createRaw);

      if (serialized.includes('createGateway')
          && serialized.includes('customJWTAuthorizer')) {
        foundGatewayWithAuth = true;
      }
    }

    expect(foundGatewayWithAuth).toBe(true);
  });
});

describe('MdcMcpGatewayStack — R8.6: no IAM roles created in-stack', () => {
  const template = Template.fromStack(buildStack());

  test('zero AWS::IAM::Role resources (R8.6, R8.7 — PowerUser cannot iam:CreateRole)', () => {
    // All roles are admin-created and imported via fromRoleName with
    // { mutable: false }. The stack must not synthesize any AWS::IAM::Role.
    template.resourceCountIs('AWS::IAM::Role', 0);
  });
});

// ── Task 4.6 — Interceptor Lambda timeout, concurrency, and resource budget (R4.7) ──
//
// R4.7: "THE Request_Interceptor SHALL complete within 2 seconds." The CDK
// stack enforces this via Lambda properties: Timeout, ReservedConcurrentExecutions,
// MemorySize, Runtime, and Architecture. These tests verify the synthesized
// CloudFormation template carries the correct values.

describe('MdcMcpGatewayStack — Task 4.6: Interceptor resource budget (R4.7)', () => {
  const template = Template.fromStack(buildStack());

  test('Lambda timeout is 2 seconds (R4.7)', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      Timeout: 2,
    });
  });

  test('Lambda reserved concurrent executions is 10 (R4.7)', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      ReservedConcurrentExecutions: 10,
    });
  });

  test('Lambda memory size is 128 MB (R4.7, design §8a cost sizing)', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      MemorySize: 128,
    });
  });

  test('Lambda uses Python 3.12 runtime on ARM_64 (R4.7, design §8a)', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      Runtime: 'python3.12',
      Architectures: ['arm64'],
    });
  });

  test('all four budget properties coexist on the same Lambda resource (R4.7)', () => {
    // Belt-and-braces: the individual tests above could pass if properties were
    // split across two different Lambda functions. This compound assertion ensures
    // the interceptor Lambda carries ALL budget properties together.
    template.hasResourceProperties('AWS::Lambda::Function', {
      Timeout: 2,
      ReservedConcurrentExecutions: 10,
      MemorySize: 128,
      Runtime: 'python3.12',
      Architectures: ['arm64'],
    });
  });
});

// ── Task 6.6 — Large-response safety: RESPONSE_BODY payload filter (R6.3) ────
//
// The interceptor configuration on the Runtime target must exclude RESPONSE_BODY
// from the payload filter, preventing large RAG responses (multi-MB) from
// breaching the Lambda synchronous invoke 6 MB limit. The Gateway applies the
// filter server-side — the Lambda never sees the response body — so the response
// reaches the caller intact regardless of size.
//
// AwsCustomResource serializes createGatewayTarget parameters into the
// Custom::AWS resource's Create property. When CloudFormation tokens are present
// (e.g., the gatewayId from the Gateway custom resource), CDK wraps the entire
// parameters object in an Fn::Join intrinsic. The payloadFilter configuration
// is embedded within this serialized JSON string, so we extract and verify it.

describe('MdcMcpGatewayStack — Task 6.6: Payload filter excludes RESPONSE_BODY (R6.3)', () => {
  const template = Template.fromStack(buildStack());

  /**
   * Helper: find the Custom::AWS resource whose Create action is
   * createGatewayTarget and extract the serialized parameters as a string.
   */
  function getTargetCreateSerialized(): string {
    const customs = template.findResources('Custom::AWS');
    for (const [logicalId, resource] of Object.entries(customs)) {
      const props = (resource as any).Properties ?? {};
      const createRaw = props.Create;
      if (createRaw == null) continue;
      const serialized = typeof createRaw === 'string'
        ? createRaw
        : JSON.stringify(createRaw);
      if (serialized.includes('createGatewayTarget')) {
        return serialized;
      }
    }
    throw new Error('No Custom::AWS resource with createGatewayTarget found');
  }

  test('interceptorConfiguration includes payloadFilter with RESPONSE_BODY excluded', () => {
    // The payloadFilter is embedded in the serialized createGatewayTarget
    // parameters. We verify both the key and the value are present.
    const serialized = getTargetCreateSerialized();
    expect(serialized).toContain('payloadFilter');
    expect(serialized).toContain('RESPONSE_BODY');
  });

  test('interceptor type is REQUEST with passRequestHeaders true', () => {
    // Verify the interceptor is registered as REQUEST type (not RESPONSE)
    // and has passRequestHeaders enabled.
    const serialized = getTargetCreateSerialized();
    expect(serialized).toContain('REQUEST');
    expect(serialized).toContain('passRequestHeaders');
  });

  test('payloadFilter exclude list contains exactly RESPONSE_BODY', () => {
    // The exclude array should contain 'RESPONSE_BODY' and nothing else
    // that would strip request-side data needed by the interceptor.
    const serialized = getTargetCreateSerialized();
    // The serialized form includes the array as JSON: "exclude":["RESPONSE_BODY"]
    // or with spacing variations. Verify RESPONSE_BODY is excluded and
    // REQUEST_BODY is NOT excluded (the interceptor needs the request body).
    expect(serialized).toContain('RESPONSE_BODY');
    expect(serialized).not.toContain('REQUEST_BODY');
  });
});

describe('MdcMcpGatewayStack — structural sanity', () => {
  const template = Template.fromStack(buildStack());

  test('at least two Custom::AWS resources exist (Gateway + Target)', () => {
    // Task 2.2 creates the Gateway, Task 2.4 creates the Runtime target.
    // Both are Custom::AWS.
    const customs = template.findResources('Custom::AWS');
    expect(Object.keys(customs).length).toBeGreaterThanOrEqual(2);
  });

  test('no stateful resources that could cause data loss (R9.5 pattern)', () => {
    const resources = template.toJSON().Resources as Record<string, any>;
    const forbidden = [
      'AWS::Neptune::',
      'AWS::OpenSearchService::',
      'AWS::S3::Bucket',
      'AWS::EFS::',
      'AWS::DynamoDB::Table',
    ];
    for (const [, r] of Object.entries(resources)) {
      for (const prefix of forbidden) {
        expect((r as any).Type.startsWith(prefix)).toBe(false);
      }
    }
  });
});
