#!/usr/bin/env bash
# authorizer-drift-detector.sh — MCP External Access (Path B), R2.8 / R9.9.
#
# Compares the LIVE AgentCore Runtime JWT authorizer config against the expected
# config built from the MdcExternalAccessAlternativeStack CloudFormation outputs
# and puts the CloudWatch metric MdcMcpExternalAccessAlt/AuthorizerDrift
# (0 = in sync, 1 = drift). The `mdc-mcp-alt-authorizer-drift` alarm watches it.
#
# Intended to run nightly (cron / CodeBuild). Every `cdk deploy` re-applies the
# CDK-defined authorizer, restoring the intended state.
#
# Usage:  authorizer-drift-detector.sh
# Env:    RUNTIME_ID (default mdc_mcp_rag_server_python-v5K2F8BGrN),
#         STACK_NAME (default MdcExternalAccessAlternativeStack),
#         AWS_REGION (default us-east-1)

set -o errexit
set -o nounset
set -o pipefail

RUNTIME_ID="${RUNTIME_ID:-mdc_mcp_rag_server_python-v5K2F8BGrN}"
STACK_NAME="${STACK_NAME:-MdcExternalAccessAlternativeStack}"
REGION="${AWS_REGION:-us-east-1}"
NAMESPACE="MdcMcpExternalAccessAlt"

output() {
  aws cloudformation describe-stacks --stack-name "${STACK_NAME}" --region "${REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='${1}'].OutputValue" --output text
}

pool_id="$(output HpcUserPoolId)"
ci_client="$(output CiAppClientId)"
hpc_client="$(output HpcAppClientId)"

expected="$(jq -n \
  --arg disc "https://cognito-idp.${REGION}.amazonaws.com/${pool_id}/.well-known/openid-configuration" \
  --arg ci "${ci_client}" \
  --arg hpc "${hpc_client}" \
  '{customJWTAuthorizer:{discoveryUrl:$disc,allowedAudience:[$ci,$hpc],allowedClients:[$ci,$hpc]}}' \
  | jq -S .)"

live="$(aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id "${RUNTIME_ID}" --region "${REGION}" \
  | jq -S '.authorizerConfiguration')"

if [ "${expected}" = "${live}" ]; then
  drift=0
  echo "[OK] authorizer config in sync"
else
  drift=1
  echo "[WARN] authorizer drift detected — next cdk deploy will restore"
  diff <(printf '%s\n' "${expected}") <(printf '%s\n' "${live}") || true
fi

aws cloudwatch put-metric-data --region "${REGION}" \
  --namespace "${NAMESPACE}" --metric-name AuthorizerDrift --value "${drift}"

exit 0
