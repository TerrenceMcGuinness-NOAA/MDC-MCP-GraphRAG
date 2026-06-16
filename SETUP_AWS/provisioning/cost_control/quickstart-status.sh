#!/bin/bash
################################################################################
# quickstart-status.sh -- Read-only state of the sandbox compute footprint
#
# Reports current state of Neptune, OpenSearch, AgentCore, and EC2 with
# per-resource hourly cost estimates so you can see the burn rate at a glance.
# No mutation.
#
# Usage:  ./quickstart-status.sh
################################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/quickstart-config.sh"

echo
echo "================================================================"
echo "  MDC MCP-RAG sandbox -- quickstart status"
echo "  Region: ${AWS_REGION}    Account: ${AWS_ACCOUNT_ID}"
echo "================================================================"
echo

# ── Neptune ─────────────────────────────────────────────────────────────
neptune_status=$(aws neptune describe-db-clusters \
  --db-cluster-identifier "${NEPTUNE_CLUSTER_ID}" \
  --region "${AWS_REGION}" \
  --query 'DBClusters[0].Status' --output text 2>/dev/null || echo "missing")

case "${neptune_status}" in
  available) neptune_cost="~\$39/day  (running)";;
  starting)  neptune_cost="~\$39/day  (waking up)";;
  stopping)  neptune_cost="~\$0/day   (going to sleep)";;
  stopped)   neptune_cost="~\$0/day   (asleep, day-7 auto-restart applies)";;
  *)         neptune_cost="(unknown)";;
esac
printf "  Neptune       %-20s %-12s %s\n" "${NEPTUNE_CLUSTER_ID}" "${neptune_status}" "${neptune_cost}"

# ── OpenSearch ──────────────────────────────────────────────────────────
os_json=$(aws opensearch describe-domain \
  --domain-name "${OPENSEARCH_DOMAIN_NAME}" \
  --region "${AWS_REGION}" \
  --query 'DomainStatus.[Processing,ClusterConfig.InstanceType,ClusterConfig.InstanceCount,ClusterConfig.ZoneAwarenessEnabled]' \
  --output text 2>/dev/null || echo "missing missing missing missing")
os_proc=$(echo "${os_json}" | awk '{print $1}')
os_type=$(echo "${os_json}" | awk '{print $2}')
os_count=$(echo "${os_json}" | awk '{print $3}')
os_az=$(echo "${os_json}" | awk '{print $4}')

if [ "${os_type}" = "${OPENSEARCH_SLEEP_INSTANCE_TYPE}" ] && [ "${os_count}" = "${OPENSEARCH_SLEEP_INSTANCE_COUNT}" ]; then
  os_state="asleep"
  os_cost="~\$1/day   (scaled-down)"
elif [ "${os_type}" = "${OPENSEARCH_PROD_INSTANCE_TYPE}" ] && [ "${os_count}" = "${OPENSEARCH_PROD_INSTANCE_COUNT}" ]; then
  os_state="awake"
  os_cost="~\$8/day   (production)"
else
  os_state="custom"
  os_cost="(non-standard config)"
fi
[ "${os_proc}" = "True" ] && os_state="${os_state}/processing"
printf "  OpenSearch    %-20s %-12s %s\n" "${OPENSEARCH_DOMAIN_NAME}" "${os_state}" "${os_cost}"
printf "    shape: %s x %s, multi-AZ=%s\n" "${os_type}" "${os_count}" "${os_az}"

# ── AgentCore ───────────────────────────────────────────────────────────
ac_status=$(aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id "${AGENTCORE_RUNTIME_ID}" \
  --region "${AWS_REGION}" \
  --query 'status' --output text 2>/dev/null || echo "missing")
case "${ac_status}" in
  READY)  ac_cost="~\$0/day   (idle = ~zero; per-session-second when called)";;
  *)      ac_cost="(${ac_status})";;
esac
printf "  AgentCore     %-20s %-12s %s\n" "${AGENTCORE_RUNTIME_ID:0:20}" "${ac_status}" "${ac_cost}"

# ── EC2 (this box) ──────────────────────────────────────────────────────
ec2_state=$(aws ec2 describe-instances \
  --instance-ids "${EC2_INSTANCE_ID}" \
  --region "${AWS_REGION}" \
  --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null || echo "missing")
case "${ec2_state}" in
  running) ec2_cost="~\$1.43/day (this dev host)";;
  stopped) ec2_cost="~\$0/day    (stopped; EBS still bills)";;
  *)       ec2_cost="(${ec2_state})";;
esac
printf "  EC2 host      %-20s %-12s %s\n" "${EC2_INSTANCE_ID}" "${ec2_state}" "${ec2_cost}"

echo
echo "  Latest snapshots in s3://${SNAPSHOT_BUCKET}/:"
aws s3 ls "s3://${SNAPSHOT_BUCKET}/" --region "${AWS_REGION}" 2>/dev/null \
  | awk '{print "    " $0}' || echo "    (none or bucket missing)"
echo
echo "  Tip: ./quickstart-sleep.sh   to hibernate"
echo "       ./quickstart-wake.sh    to resume"
echo
