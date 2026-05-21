# Implementation Plan: Private MCP Deployment

## Overview

Deploy the MDC MCP RAG Server to production on AWS ECS Fargate behind a Private API Gateway, eliminating all internet-facing components. The implementation follows a test-first approach for CDK stacks: write CDK assertion tests for the target state, then modify the stacks to pass those tests. The admin request document is a blocking dependency — CDK deployment cannot proceed until the admin creates the two ECS IAM roles.

## Tasks

- [x] 1. Create admin IAM role request document
  - [x] 1.1 Create `docs/ecs-roles-request.txt` following the format of `docs/neptune-bulk-loader-role-request.txt`
    - Include exact trust policy JSON for both `mdc-mcp-rag-ecs-task-role` and `mdc-mcp-rag-ecs-execution-role` with `ecs-tasks.amazonaws.com` as trusted principal
    - Include exact permission policy JSON for the task role (Secrets Manager, SSM, Neptune, OpenSearch access)
    - Specify that the execution role uses the AWS managed `AmazonECSTaskExecutionRolePolicy`
    - Include "What This Does NOT Do" section, "Why This Requires Admin" section citing `PowerUserRestrictions`, and reference the Neptune bulk loader role as precedent
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

- [x] 2. Write CDK assertion tests for target state (test-first)
  - [x] 2.1 Update `infrastructure/cdk/test/cdk.test.ts` — MdcServerStack tests for private architecture
    - Replace the CloudFront distribution test with a test asserting zero `AWS::CloudFront::Distribution` resources
    - Replace the CloudFront WAF test with a test asserting zero CLOUDFRONT-scoped `AWS::WAFv2::WebACL` resources
    - Add test: API Gateway endpoint type is PRIVATE
    - Add test: API Gateway resource policy restricts to VPC endpoint (`aws:sourceVpce` condition)
    - Add test: `/mcp` route has HTTP_PROXY integration with VPC_LINK connection type
    - Add test: `/health` endpoint exists with `AuthorizationType: NONE`
    - Add test: WAF associated with API Gateway stage via `AWS::WAFv2::WebACLAssociation`
    - Add test: `PrivateApiEndpoint` output exists (no `CloudFrontDomain` output)
    - Add test: No Cognito authorizer resource exists
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4_

  - [x] 2.2 Update `infrastructure/cdk/test/cdk.test.ts` — MdcSecurityStack tests for Cognito removal
    - Replace the `Cognito user pool exists` test with a test asserting zero `AWS::Cognito::UserPool` resources
    - Verify WAF WebACL still exists with REGIONAL scope
    - Verify ECS security group, Secrets Manager secrets, and SSM parameters still exist
    - _Requirements: 3.1_

  - [x] 2.3 Update `infrastructure/cdk/test/cdk.test.ts` — MdcDataStack tests for resource import
    - Replace Neptune cluster creation test with a test verifying no `AWS::Neptune::DBCluster` resource is created (imported instead)
    - Replace OpenSearch domain creation test with a test verifying no `AWS::OpenSearchService::Domain` resource is created (imported instead)
    - Verify EFS and S3 migration bucket are still created
    - _Requirements: 9.1, 9.2, 9.4_

  - [x] 2.4 Update `infrastructure/cdk/test/cdk.test.ts` — update `buildStacks()` helper
    - Remove `userPool` from `MdcServerStack` props in the test helper
    - Ensure the test helper matches the new stack interfaces after Cognito removal
    - _Requirements: 3.1_

- [x] 3. Checkpoint — Ensure tests compile and fail for the right reasons
  - Run `npx jest` in `infrastructure/cdk` to confirm tests compile but fail (since stacks haven't been modified yet). Ask the user if questions arise.

- [x] 4. Modify MdcSecurityStack — remove Cognito, keep WAF and role imports
  - [x] 4.1 Modify `infrastructure/cdk/lib/mdc-security-stack.ts`
    - Remove `cognito` import and `UserPool` creation (user pool + resource server)
    - Remove `public readonly userPool: cognito.UserPool` property
    - Keep: ECS IAM role imports (`fromRoleName`), ECS security group, Secrets Manager secrets, SSM parameters, REGIONAL WAF WebACL
    - _Requirements: 3.1, 6.3_

- [x] 5. Modify MdcDataStack — import existing Neptune and OpenSearch
  - [x] 5.1 Modify `infrastructure/cdk/lib/mdc-data-stack.ts`
    - Replace Neptune cluster/instance/subnet-group creation with import of existing cluster by identifier
    - Replace OpenSearch domain creation with `Domain.fromDomainEndpoint` import
    - Remove Neptune bulk loader role creation (already exists, admin-created)
    - Remove KMS key creation (already exists with the cluster)
    - Remove Neptune and OpenSearch security group creation (already exist)
    - Set `removalPolicy: RETAIN` on imported references where applicable
    - Keep: EFS filesystem creation, S3 migration bucket creation
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 6. Modify MdcServerStack — Private API Gateway, remove CloudFront
  - [x] 6.1 Modify `infrastructure/cdk/lib/mdc-server-stack.ts` — remove CloudFront and Cognito
    - Remove all CloudFront imports (`cloudfront`, `cloudfront-origins`)
    - Remove `cloudfront.Distribution` resource and `MdcCfWebAcl` CLOUDFRONT-scoped WAF
    - Remove `CognitoUserPoolsAuthorizer` and `cognito` import
    - Remove `distribution` public property
    - Remove `CloudFrontDomain` and `McpEndpoint` CfnOutputs
    - Remove `userPool` from props interface
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 6.2 Modify `infrastructure/cdk/lib/mdc-server-stack.ts` — Private API Gateway with VPC Link
    - Change API Gateway endpoint type from `REGIONAL` to `PRIVATE`
    - Replace Cognito authorizer with a resource policy restricting `execute-api:Invoke` to the VPC endpoint (Deny-first pattern with `aws:sourceVpce` condition)
    - Create a `VpcLink` pointing to the Internal ALB
    - Change `/mcp` integration from `HttpIntegration` to `Integration` with type `HTTP_PROXY` and connection type `VPC_LINK`
    - Add `/health` endpoint with `AuthorizationType: NONE` that proxies to ALB `/health`
    - Associate REGIONAL WAF with the API Gateway stage using `wafv2.CfnWebACLAssociation`
    - Add `PrivateApiEndpoint` CfnOutput with the Private API Gateway URL
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.4_

- [x] 7. Update CDK app entry point
  - [x] 7.1 Modify `infrastructure/cdk/bin/cdk.ts`
    - Remove `userPool` from `MdcServerStack` props
    - Keep dependency chain: VpcStack → SecurityStack → DataStack → ServerStack
    - _Requirements: 6.1_

- [x] 8. Checkpoint — CDK assertion tests pass
  - Run `npx jest` in `infrastructure/cdk` to confirm all CDK assertion tests pass. Ensure `npx cdk synth` succeeds. Ask the user if questions arise.

- [x] 9. Create Docker image and ECR configuration
  - [x] 9.1 Create `infrastructure/docker/Dockerfile`
    - Adapt from `SETUP/dockerfiles/Dockerfile.mcp-server` for the AWS environment
    - Remove Docker-specific host references (`CHROMADB_HOST`, `NEO4J_URI`, etc.)
    - Set `DB_BACKEND=aws`, `NODE_ENV=production`, `AWS_REGION=us-east-1`
    - Use `node src/mcp-http-server.js 3000 full` as CMD (Streamable HTTP transport)
    - Add health check hitting `http://localhost:3000/health`
    - Expose port 3000
    - _Requirements: 5.3, 5.5_

- [x] 10. Update Kiro MCP client configuration
  - [x] 10.1 Modify `.kiro/settings/mcp.json`
    - Update `mdc-mcp-rag-aws` entry: change `url` from `http://localhost:3000/mcp` to `https://{api-id}-{vpce-id}.execute-api.us-east-1.amazonaws.com/prod/mcp` (placeholder — actual URL from `cdk deploy` output)
    - Keep `type: "http"` and existing `autoApprove` list
    - _Requirements: 7.1, 7.2_

- [x] 11. Final checkpoint — Ensure all tests pass
  - Run `npx jest` in `infrastructure/cdk` to confirm all CDK assertion tests pass. Run `npx cdk synth` to verify all four stacks synthesize without errors. Ask the user if questions arise.

## Notes

- The admin request document (task 1) is a BLOCKING dependency — tasks 4-7 modify CDK stacks that import the admin-created roles, but actual `cdk deploy` cannot succeed until the admin creates them
- CDK assertion tests (task 2) are written BEFORE stack modifications (tasks 4-7) following a test-first approach
- The design explicitly states property-based testing does not apply to this IaC feature — all tests are CDK assertion tests (unit) and post-deployment integration tests
- Task 10 uses a placeholder URL — the actual Private API Gateway URL is only known after `cdk deploy MdcServerStack` completes
- The deployment sequence (delete ROLLBACK_COMPLETE stacks → admin creates roles → build Docker → cdk deploy → verify → update Kiro → retire bridge) is documented in the design and executed manually, not as coding tasks
