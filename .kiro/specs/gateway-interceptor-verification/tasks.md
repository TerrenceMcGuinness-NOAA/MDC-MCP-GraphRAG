# Implementation Plan: Gateway Interceptor Verification (Path C Task 0)

## Overview

Single-session infrastructure verification of the two unverified AWS platform behaviors
gating all of Path C's external authentication system:

- **DP-7:** Do REQUEST interceptor Lambdas fire for an `agentcoreRuntime` target on a
  Gateway when the MCP server responds with `Content-Type: application/json`?
- **DP-1:** Do headers injected by the interceptor
  (`X-Amzn-Bedrock-AgentCore-Runtime-Custom-*`) arrive at the MCP container?

Nine steps execute in strict sequence. Failure at any step triggers rollback (Task 9).
All AWS CLI commands use region `us-east-1`, account `903050880929`.

### Environment Constants

| Constant | Value |
|---|---|
| Runtime ID | `mdc_mcp_rag_server_python-v5K2F8BGrN` |
| Runtime ARN | `arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN` |
| Runtime Role | `arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role` |
| Container Image | `903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-tenants-v16` |
| Subnets | `subnet-0e13af6b3a9a6416f`, `subnet-04447750c61bd7e06` |
| Security Group | `sg-096489a0876cc78c1` |
| EFS Access Point | `fsap-03e641f056b341f29` at `/mnt/workflow` |

## Tasks

- [x] 1. Pre-flight — Capture pre-verification baseline
  - [x] 1.1 Snapshot current Runtime configuration via GetAgentRuntime
    - Run `aws bedrock-agentcore-control get-agent-runtime --region us-east-1 --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN` and save the full JSON response to a local variable or file for rollback comparison
    - Confirm status is `READY` and the environment variables are exactly: `DB_BACKEND=aws`, `NEPTUNE_ENDPOINT=https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182`, `OPENSEARCH_ENDPOINT=https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com`, `AWS_REGION=us-east-1`, `MCP_STATELESS_HTTP=true`, `MCP_WORKFLOW_ROOT=/mnt/workflow`
    - Verify Runtime health via `mcp_health_check()` — expect HEALTHY 4/4 components
    - Verify `get_server_info()` reports 53 registered tools
    - Record the actual `fastmcp` and `mcp` library versions reported by `get_server_info` (expected: `fastmcp 3.4.1` / `mcp 1.27.2` per design §3.2)
    - _Requirements: 1.6, 7.3, 7.5, P5 (pre-verification baseline for rollback fidelity)_

  - [x] 1.2 Pre-flight IAM check — locate a Lambda execution role
    - Run `aws iam list-roles --region us-east-1 --query "Roles[?contains(RoleName, 'ambda')].{Name:RoleName,Arn:Arn}" --output table` to find an existing basic Lambda execution role
    - If a suitable role exists (one with `AWSLambdaBasicExecutionRole` policy), record its ARN as `LAMBDA_ROLE_ARN`
    - If NO suitable role exists, add the admin request to `docs/mdc-external-access-alt-iam-request.txt` with: Role Name `mdc-gateway-verification-lambda-role`, Trust Policy `lambda.amazonaws.com`, Managed Policy `arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole`, Purpose "Temporary — Echo Interceptor Lambda for gateway verification probe"
    - The Echo Interceptor Lambda role SHALL have minimal permissions: only CloudWatch Logs write access — no Runtime invoke, no Neptune/OpenSearch access
    - _Requirements: 8.5 (minimal interceptor permissions), design §2.2 (IAM strategy)_

- [x] 2. Step 1 — Enable FASTMCP_JSON_RESPONSE=true on the Runtime
  - [x] 2.1 Update Runtime environment variables via full-replacement API
    - Run the exact `update-agent-runtime` command from design §3.1. **CRITICAL**: this is a full-replacement API — every field must be present or it gets wiped. The ONLY change from the baseline is adding `"FASTMCP_JSON_RESPONSE": "true"` to the environment variables:
    - ```bash
      aws bedrock-agentcore-control update-agent-runtime \
        --region us-east-1 \
        --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN \
        --agent-runtime-artifact '{"containerConfiguration":{"containerUri":"903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-tenants-v16"}}' \
        --role-arn arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role \
        --network-configuration '{"networkMode":"VPC","networkModeConfig":{"subnets":["subnet-0e13af6b3a9a6416f","subnet-04447750c61bd7e06"],"securityGroups":["sg-096489a0876cc78c1"]}}' \
        --protocol-configuration '{"serverProtocol":"MCP"}' \
        --lifecycle-configuration '{"idleRuntimeSessionTimeout":900,"maxLifetime":28800}' \
        --metadata-configuration '{"requireMMDSV2":true}' \
        --environment-variables '{"DB_BACKEND":"aws","NEPTUNE_ENDPOINT":"https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182","OPENSEARCH_ENDPOINT":"https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com","AWS_REGION":"us-east-1","MCP_STATELESS_HTTP":"true","MCP_WORKFLOW_ROOT":"/mnt/workflow","FASTMCP_JSON_RESPONSE":"true"}' \
        --filesystem-configurations '[{"efsAccessPoint":{"accessPointArn":"arn:aws:elasticfilesystem:us-east-1:903050880929:access-point/fsap-03e641f056b341f29","mountPath":"/mnt/workflow"}}]'
      ```
    - Do NOT remove or change `MCP_STATELESS_HTTP=true` — stateless mode is mandatory for AgentCore MCP protocol mode
    - Do NOT modify `networkConfiguration`, `protocolConfiguration`, `roleArn`, `agentRuntimeArtifact`, `lifecycleConfiguration`, or `filesystemConfigurations`
    - _Requirements: 1.1, 1.2, 1.3, 8.2, P6 (full-replacement payload completeness)_

  - [x] 2.2 Poll Runtime until READY and verify health
    - Poll with `aws bedrock-agentcore-control get-agent-runtime --region us-east-1 --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN --query '{Status:status,EnvVars:environmentVariables}'` until status is `READY` (typically 60-120 seconds, max 10 minutes per design §6.1)
    - Confirm `environmentVariables` includes all 7 keys (the original 6 plus `FASTMCP_JSON_RESPONSE=true`)
    - Verify `mcp_health_check()` reports HEALTHY 4/4 (Base, Utility, Vector, Graph DB)
    - Verify `get_server_info()` reports 53 registered tools
    - **IF Runtime enters FAILED state**: check Runtime CloudWatch logs for startup errors and trigger immediate rollback (Task 9). Record failure in the Verification Report
    - **IF health check returns < 4/4 and `NEPTUNE_ENDPOINT` or `OPENSEARCH_ENDPOINT` are missing from env vars**: the full-replacement API wiped them — rollback immediately
    - _Requirements: 1.4, 1.5, P1 (health invariant)_

- [x] 3. Step 2 — Verify developer proxy works with JSON framing
  - [x] 3.1 Test three tool calls through the developer SigV4 proxy
    - Call `get_server_info()` via the MCP tools — expect 53 tools, 10 active modules. Record the actual `fastmcp` and `mcp` library versions
    - Call `mcp_health_check()` — expect HEALTHY 4/4 components
    - Call `find_callers_callees(function_name="setuprad")` — expect a non-empty graph result (confirms the graph-backed tool path works under JSON framing)
    - Confirm NO `-32603 "Empty SSE response"` errors from any call. If this error appears, the proxy's framing tolerance is broken — record as a blocking regression in the Verification Report and HALT before proceeding
    - The `.kiro/settings/mcp.json` entry SHALL remain byte-identical to pre-verification state
    - The `tools/agentcore-kiro-proxy.py` file SHALL NOT be modified — it is already framing-tolerant at v1.2.0
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, P2 (developer path invariant)_

- [x] 4. Checkpoint — Confirm framing switch is safe before creating infrastructure
  - Ensure the Runtime is HEALTHY with JSON framing and the developer proxy works. If either Task 2 or Task 3 failed, halt and execute Task 9 (rollback). Ask the user if questions arise.

- [ ] 5. Step 3 — Create Echo Interceptor Lambda and Gateway
  - [x] 5.1 Commit the Echo Interceptor Lambda source code
    - Create the file `infrastructure/cdk/lambda/gateway_echo_interceptor/index.py` with the exact source code from design §3.3.1
    - The Lambda SHALL: (a) log event structure with header NAMES only, never values (R4.2, R8.3), (b) inject `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal: probe` overwriting any client-supplied value (R4.3), (c) pass the request body through unchanged (R4.4), (d) return `interceptorOutputVersion: "1.0"` (R4.5), (e) on error, log event keys (never full body) and return HTTP 500 via `transformedGatewayResponse` (R4.7)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.7, 4.8, 8.3_

  - [x] 5.2 Deploy the Echo Interceptor Lambda to AWS
    - Zip the Lambda code:
      ```bash
      cd infrastructure/cdk/lambda/gateway_echo_interceptor && zip -j /tmp/echo_interceptor.zip index.py
      ```
    - Create the Lambda function using `LAMBDA_ROLE_ARN` from Task 1.2:
      ```bash
      aws lambda create-function \
        --region us-east-1 \
        --function-name mdc-gateway-echo-interceptor \
        --runtime python3.12 \
        --handler index.handler \
        --role "${LAMBDA_ROLE_ARN}" \
        --zip-file fileb:///tmp/echo_interceptor.zip \
        --timeout 10 \
        --memory-size 128 \
        --description "Temporary: Path C Task 0 gateway interceptor verification probe"
      ```
    - Capture `INTERCEPTOR_ARN` from `aws lambda get-function --region us-east-1 --function-name mdc-gateway-echo-interceptor --query 'Configuration.FunctionArn' --output text`
    - Add resource-based policy allowing AgentCore to invoke the Lambda:
      ```bash
      aws lambda add-permission \
        --region us-east-1 \
        --function-name mdc-gateway-echo-interceptor \
        --statement-id AllowAgentCoreGateway \
        --action lambda:InvokeFunction \
        --principal bedrock-agentcore.amazonaws.com \
        --source-account 903050880929
      ```
    - **IF** `create-function` fails with `AccessDeniedException`: check PowerUserRestrictions and Lambda role existence. Add to admin IAM request if needed
    - _Requirements: 4.1, 4.6 (RESPONSE_BODY exclusion configured at Gateway level in 5.3), 8.5_

  - [-] 5.3 Create the temporary Gateway with interceptor attached
    - Use `mdc-mcp-rag-ecs-task-role` as the Gateway execution role (it already trusts `bedrock-agentcore.amazonaws.com` and has `InvokeAgentRuntime` permission):
      ```bash
      aws bedrock-agentcore-control create-gateway \
        --region us-east-1 \
        --name "mdc-verification-gateway" \
        --description "Temporary: Path C Task 0 interceptor verification" \
        --role-arn "arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role" \
        --authorizer-type NONE \
        --exception-level DEBUG \
        --interceptor-configurations "[{\"interceptor\":{\"lambda\":{\"arn\":\"${INTERCEPTOR_ARN}\"}},\"interceptionPoints\":[\"REQUEST\"],\"inputConfiguration\":{\"passRequestHeaders\":true,\"payloadFilter\":{\"exclude\":[{\"field\":\"RESPONSE_BODY\"}]}}}]"
      ```
    - Capture `GATEWAY_ID` and `GATEWAY_URL` from the response
    - Poll until READY: `aws bedrock-agentcore-control get-gateway --region us-east-1 --gateway-id "${GATEWAY_ID}" --query '{Status:status,Url:gatewayUrl}'`
    - The Gateway SHALL have `authorizer-type NONE` — no `customJWTAuthorizer` at any point
    - The interceptor `payloadFilter` SHALL exclude `RESPONSE_BODY` to prevent 6 MB Lambda payload limit breaches with large RAG responses
    - **IF** `create-gateway` fails because `mdc-mcp-rag-ecs-task-role` is not assumable by the Gateway: record the error in the Verification Report, add `mdc-gateway-verification-exec-role` to admin IAM request (`docs/mdc-external-access-alt-iam-request.txt`), and wait for admin
    - **IF** `create-gateway` fails with `ServiceQuotaExceededException`: delete any leftover test gateways first
    - Record Gateway ID and Gateway URL in the Verification Report
    - _Requirements: 3.1, 3.2, 3.4, 3.6, 3.7, 4.6, 8.1, P6_

- [ ] 6. Step 4 — Create Runtime Target on the Gateway
  - [~] 6.1 Attach the live Runtime as an agentcoreRuntime target
    - Create the target:
      ```bash
      aws bedrock-agentcore-control create-gateway-target \
        --region us-east-1 \
        --gateway-id "${GATEWAY_ID}" \
        --name "mdc-mcp-rag-runtime" \
        --description "Runtime target for interceptor verification" \
        --target-configuration '{"http":{"agentcoreRuntime":{"arn":"arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN","qualifier":"DEFAULT"}}}'
      ```
    - Capture `TARGET_ID` from the response
    - Poll until READY: `aws bedrock-agentcore-control get-gateway-target --region us-east-1 --gateway-id "${GATEWAY_ID}" --target-id "${TARGET_ID}" --query '{Status:status,Name:name}'`
    - The target `metadataConfiguration.allowedRequestHeaders` SHALL include at least `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal` — if the API supports setting this on the target, include it; otherwise record whether the default allows custom headers
    - The Gateway endpoint for invocation will be: `${GATEWAY_URL}/mdc-mcp-rag-runtime/invocations`
    - _Requirements: 3.2, 3.3, 3.5_

- [ ] 7. Step 5 — Invoke through the Gateway
  - [~] 7.1 Send a `tools/list` JSON-RPC request through the Gateway via SigV4
    - Use a Python boto3 SigV4-signing script (design §3.5, Method 2) to POST `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}` to `${GATEWAY_URL}/mdc-mcp-rag-runtime/invocations` with `Content-Type: application/json` and `Accept: application/json`, signing against service `bedrock-agentcore` in region `us-east-1`
    - Record: HTTP status code, response `Content-Type`, response body (first 2000 chars), whether the response is valid JSON-RPC with a `tools/list` result
    - **IF HTTP 401/403**: the Gateway may require specific auth. Check that the signing service is `bedrock-agentcore`, not `execute-api`. Retry with the correct service name. Record the rejection reason in the Verification Report
    - **IF HTTP 500**: check interceptor CloudWatch logs and Gateway CloudWatch logs for crash details
    - **IF HTTP 502/504**: check Runtime health — the Gateway timeout may be shorter than the response time
    - **IF empty response body**: record this — it may indicate interceptors don't fire for this framing mode
    - _Requirements: 5.1, 5.5_

  - [~] 7.2 Send a second request with a forged Custom-Principal header
    - Repeat the invocation from 7.1 but add the header `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Principal: attacker-forged` to the request (design §3.5, forged header test)
    - This tests the interceptor's overwrite property — the Echo_Interceptor MUST strip any client-supplied `Custom-*` headers and replace with `probe`
    - Record whether the observed header value at the container is `probe` (not `attacker-forged`)
    - _Requirements: 4.3, 5.6, P3 (header fidelity)_

- [ ] 8. Steps 6–7 — Check CloudWatch for Q1 (interceptor fired) and Q2 (header arrived)
  - [~] 8.1 Q1 / DP-7: Check whether the Echo Interceptor Lambda executed
    - Query the interceptor Lambda's log group for recent entries:
      ```bash
      aws logs filter-log-events \
        --region us-east-1 \
        --log-group-name "/aws/lambda/mdc-gateway-echo-interceptor" \
        --start-time $(python3 -c "import time; print(int((time.time() - 900) * 1000))") \
        --filter-pattern "EVENT_KEYS" \
        --query 'events[*].{Time:timestamp,Message:message}' \
        --output table
      ```
    - **Q1 = YES** if at least one log entry contains `EVENT_KEYS` with `["http"]` shape
    - **Q1 = NO** if the log group is empty or does not exist
    - Record the answer and raw CloudWatch log excerpt as evidence
    - _Requirements: 5.2, 6.1_

  - [~] 8.2 Q2 / DP-1: Check whether the injected header arrived at the MCP container
    - Discover the Runtime's log group: `aws logs describe-log-groups --region us-east-1 --log-group-name-prefix "/aws/bedrock-agentcore" --query 'logGroups[*].logGroupName'`
    - Search for the injected header name in Runtime logs:
      ```bash
      aws logs filter-log-events \
        --region us-east-1 \
        --log-group-name "${RUNTIME_LOG_GROUP}" \
        --start-time $(python3 -c "import time; print(int((time.time() - 900) * 1000))") \
        --filter-pattern "Custom-Principal" \
        --query 'events[*].{Time:timestamp,Message:message}' \
        --output table
      ```
    - **Q2 = YES** if CloudWatch logs show `Custom-Principal` in the request context. If value is visible, confirm it is exactly `probe` (byte-for-byte — P3 header fidelity)
    - **Q2 = INCONCLUSIVE** if Runtime logs do not include header-level detail (the server may not log request headers at DEBUG level)
    - **Q2 = NO** if Runtime logs show the request arrived but without the injected header
    - Record the answer and evidence
    - _Requirements: 5.3, 5.4, 5.6, P3 (header fidelity)_

- [ ] 9. Step 8 — Write Verification Report and record decision branch
  - [~] 9.1 Write the Verification Report to `docs/reports/mcp-external-access-gateway-verification.md`
    - Use the exact schema from design §4.1 — the report MUST include: date, runtime version, container image tag, fastmcp/mcp library versions, Gateway ID, Gateway URL, Echo Interceptor Lambda ARN, pre-verification state, all step results, Q1 and Q2 answers with raw evidence, exact CLI commands used, and unexpected observations
    - Include the **decision branch** based on the Q1/Q2 results from the decision matrix (design §3.8):
      - **IF Q1=YES AND Q2=YES**: record "**Path C Runtime-target architecture CONFIRMED viable.** Proceed with `.kiro/specs/mcp-external-access-alternative-gateway/` Tasks 1–9. AD-C1 validated."
      - **IF Q1=YES AND Q2=NO**: record "**Header injection FAILED.** Interceptor fires but injected headers do not reach the container. Investigate `metadataConfiguration.allowedRequestHeaders` and target configuration before proceeding."
      - **IF Q1=YES AND Q2=INCONCLUSIVE**: record "Interceptor fires (good). Header arrival unconfirmed because Runtime logs lack header detail. **Proceed with cautious optimism** — add temporary debug logging, rebuild, and re-verify header arrival before full Path C implementation."
      - **IF Q1=NO (regardless of Q2)**: record "**Interceptors do NOT fire for Runtime targets with JSON framing.** AD-C1 invalidated. Evaluate DP-8: the MCP-target architecture. Amend `design.md` AD-C1 before any further work."
    - Include the resource inventory table for cleanup traceability (design §4.2)
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [~] 9.2 Update the Gate Register in the parent spec
    - Update `.kiro/specs/mcp-external-access-alternative-gateway/design.md` §9.2 Gate 1 with the verification outcome, using the templates from design Appendix A
    - Cross-reference the Verification Report path: `docs/reports/mcp-external-access-gateway-verification.md`
    - _Requirements: 6.5_

- [~] 10. Checkpoint — Confirm report is written and decision branch is recorded
  - Ensure the Verification Report exists at `docs/reports/mcp-external-access-gateway-verification.md` with all required sections. Ensure the Gate Register is updated. Ask the user if questions arise before proceeding to rollback.

- [ ] 11. Step 9 — Rollback (delete Gateway, Lambda, restore Runtime)
  - [~] 11.1 Delete the Gateway Target
    - ```bash
      aws bedrock-agentcore-control delete-gateway-target \
        --region us-east-1 \
        --gateway-id "${GATEWAY_ID}" \
        --target-id "${TARGET_ID}"
      ```
    - Each rollback step is independent — if one fails, continue with the remaining steps
    - _Requirements: 7.1_

  - [~] 11.2 Delete the Gateway
    - ```bash
      aws bedrock-agentcore-control delete-gateway \
        --region us-east-1 \
        --gateway-id "${GATEWAY_ID}"
      ```
    - The Gateway SHALL be deleted so it cannot be mistaken for a production resource or accrue cost
    - _Requirements: 7.1_

  - [~] 11.3 Delete the Echo Interceptor Lambda
    - ```bash
      aws lambda delete-function \
        --region us-east-1 \
        --function-name mdc-gateway-echo-interceptor
      ```
    - If any IAM role was created specifically for the Echo Interceptor (`mdc-gateway-verification-lambda-role`), document it in the Verification Report for admin cleanup (PowerUserRestrictions may prevent operator deletion)
    - _Requirements: 7.2, 7.7_

  - [~] 11.4 Restore Runtime environment variables to pre-verification state
    - Issue the full-replacement update with the ORIGINAL 6 env vars (no `FASTMCP_JSON_RESPONSE`), unless the operator explicitly chooses to keep it for Path C readiness:
      ```bash
      aws bedrock-agentcore-control update-agent-runtime \
        --region us-east-1 \
        --agent-runtime-id mdc_mcp_rag_server_python-v5K2F8BGrN \
        --agent-runtime-artifact '{"containerConfiguration":{"containerUri":"903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-tenants-v16"}}' \
        --role-arn arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role \
        --network-configuration '{"networkMode":"VPC","networkModeConfig":{"subnets":["subnet-0e13af6b3a9a6416f","subnet-04447750c61bd7e06"],"securityGroups":["sg-096489a0876cc78c1"]}}' \
        --protocol-configuration '{"serverProtocol":"MCP"}' \
        --lifecycle-configuration '{"idleRuntimeSessionTimeout":900,"maxLifetime":28800}' \
        --metadata-configuration '{"requireMMDSV2":true}' \
        --environment-variables '{"DB_BACKEND":"aws","NEPTUNE_ENDPOINT":"https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com:8182","OPENSEARCH_ENDPOINT":"https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com","AWS_REGION":"us-east-1","MCP_STATELESS_HTTP":"true","MCP_WORKFLOW_ROOT":"/mnt/workflow"}' \
        --filesystem-configurations '[{"efsAccessPoint":{"accessPointArn":"arn:aws:elasticfilesystem:us-east-1:903050880929:access-point/fsap-03e641f056b341f29","mountPath":"/mnt/workflow"}}]'
      ```
    - **CRITICAL**: Full-replacement API — all 8 fields must be present. Compare the resulting env vars against the Task 1.1 baseline snapshot to confirm byte-for-byte match
    - _Requirements: 7.3, 7.5, 8.2, P5 (rollback fidelity), P6 (full-replacement payload completeness)_

  - [~] 11.5 Post-rollback verification
    - Poll `get-agent-runtime` until `READY` with exactly 6 env vars (no `FASTMCP_JSON_RESPONSE`)
    - Compare the full GetAgentRuntime response against the Task 1.1 baseline snapshot — same container image, same env vars, same network config, same EFS mount, same lifecycle settings
    - Call `mcp_health_check()` — expect HEALTHY 4/4
    - Call `get_server_info()` — expect 53 tools
    - Call `get_server_info()` through the developer proxy — expect valid JSON-RPC response
    - Confirm `GetAgentRuntime` shows NO `customJWTAuthorizer` on the Runtime (standing constraint)
    - _Requirements: 7.4, 7.6, P1 (health invariant), P5 (rollback fidelity), P6 (no JWT authorizer — P6 in requirements is "No JWT Authorizer")_

- [~] 12. Final checkpoint — Verification complete
  - Ensure the Verification Report is complete with all sections from design §4.1
  - Ensure all verification resources are deleted (Gateway, Target, Lambda)
  - Ensure the Runtime is in pre-verification state (HEALTHY 4/4, 53 tools, 6 env vars)
  - Ensure the Gate Register in the parent spec is updated
  - Confirm the entire verification completed within the 4-hour safety window (R8.6)
  - Ask the user if questions arise.

## Notes

- This is an **infrastructure verification spec**, not application code. All "tests" are operational probes against live AWS resources. Property-based testing does not apply — the inputs are fixed and the outputs are binary (design §7.1).
- Each task references specific requirements for traceability. Requirements are from `requirements.md` (R1–R8, P1–P6).
- Checkpoints ensure the verification is safe to continue at critical junctures (post-framing-switch, pre-rollback).
- The time budget is ~70 minutes total (design §7.3), well within the 4-hour safety window (R8.6).
- **Failure at any step triggers rollback (Task 11).** The rollback procedure is independent per step — if one cleanup step fails, continue with the rest.
- The full-replacement API (`update-agent-runtime`) is the single most dangerous operation in this verification. Every call MUST carry all 8 fields. A partial payload silently wipes omitted fields.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["3.1"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["7.1"] },
    { "id": 8, "tasks": ["7.2"] },
    { "id": 9, "tasks": ["8.1", "8.2"] },
    { "id": 10, "tasks": ["9.1"] },
    { "id": 11, "tasks": ["9.2"] },
    { "id": 12, "tasks": ["11.1", "11.2", "11.3"] },
    { "id": 13, "tasks": ["11.4"] },
    { "id": 14, "tasks": ["11.5"] }
  ]
}
```
