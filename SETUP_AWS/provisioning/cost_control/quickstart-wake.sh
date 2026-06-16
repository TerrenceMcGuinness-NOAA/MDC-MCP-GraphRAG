#!/bin/bash
################################################################################
# quickstart-wake.sh -- Wake the sandbox compute footprint
#
# Starts Neptune (waits for 'available') and scales OpenSearch back to its
# production multi-AZ shape (waits for Processing=False). AgentCore is
# already up; EC2 is the host you're running this from.
#
# Idempotent: re-running while already awake is a safe no-op.
#
# Usage:  ./quickstart-wake.sh [--no-wait]
#
# Wake budget: ~10-15 min for Neptune, ~30-45 min for OpenSearch. Both run
# concurrently when --no-wait is omitted (the default).
################################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/quickstart-config.sh"

NO_WAIT="${1:-}"

# ── Neptune: start ────────────────────────────────────────────────────────
neptune_status=$(aws neptune describe-db-clusters \
  --db-cluster-identifier "${NEPTUNE_CLUSTER_ID}" \
  --region "${AWS_REGION}" \
  --query 'DBClusters[0].Status' --output text)

case "${neptune_status}" in
  available)
    log_info "Neptune already available; skip."
    ;;
  stopped)
    log_info "Starting Neptune cluster ${NEPTUNE_CLUSTER_ID}..."
    aws neptune start-db-cluster \
      --db-cluster-identifier "${NEPTUNE_CLUSTER_ID}" \
      --region "${AWS_REGION}" \
      --output text >/dev/null
    log_ok "Neptune start initiated."
    ;;
  starting)
    log_info "Neptune already starting; will wait."
    ;;
  *)
    log_warn "Neptune in unexpected state '${neptune_status}'; review before proceeding."
    ;;
esac

# ── OpenSearch: scale up to production shape ──────────────────────────────
os_type=$(aws opensearch describe-domain \
  --domain-name "${OPENSEARCH_DOMAIN_NAME}" \
  --region "${AWS_REGION}" \
  --query 'DomainStatus.ClusterConfig.InstanceType' --output text)
os_count=$(aws opensearch describe-domain \
  --domain-name "${OPENSEARCH_DOMAIN_NAME}" \
  --region "${AWS_REGION}" \
  --query 'DomainStatus.ClusterConfig.InstanceCount' --output text)
os_processing=$(aws opensearch describe-domain \
  --domain-name "${OPENSEARCH_DOMAIN_NAME}" \
  --region "${AWS_REGION}" \
  --query 'DomainStatus.Processing' --output text)

if [ "${os_type}" = "${OPENSEARCH_PROD_INSTANCE_TYPE}" ] \
   && [ "${os_count}" = "${OPENSEARCH_PROD_INSTANCE_COUNT}" ] \
   && [ "${os_processing}" = "False" ]; then
  log_info "OpenSearch already at production shape; skip."
else
  log_info "Scaling OpenSearch up to ${OPENSEARCH_PROD_INSTANCE_TYPE} x ${OPENSEARCH_PROD_INSTANCE_COUNT}, multi-AZ..."
  aws opensearch update-domain-config \
    --domain-name "${OPENSEARCH_DOMAIN_NAME}" \
    --cluster-config "InstanceType=${OPENSEARCH_PROD_INSTANCE_TYPE},InstanceCount=${OPENSEARCH_PROD_INSTANCE_COUNT},DedicatedMasterEnabled=false,ZoneAwarenessEnabled=true,ZoneAwarenessConfig={AvailabilityZoneCount=2}" \
    --vpc-options "SubnetIds=${OPENSEARCH_PROD_SUBNETS},SecurityGroupIds=${OPENSEARCH_VPC_SECURITY_GROUP}" \
    --region "${AWS_REGION}" \
    --output text >/dev/null
  log_ok "OpenSearch scale-up submitted. Blue/green takes ~30-45 min; queries work during cutover."
fi

# ── Optional concurrent wait ─────────────────────────────────────────────
if [ "${NO_WAIT}" = "--no-wait" ]; then
  log_info "--no-wait given; not polling for completion."
  log_info "Run ./quickstart-status.sh later to confirm both reached awake state."
  exit 0
fi

log_info "Polling Neptune (timeout ${NEPTUNE_WAKE_TIMEOUT_S}s) and OpenSearch (timeout ${OPENSEARCH_PROCESSING_TIMEOUT_S}s)..."

# Both wakes can run concurrently; poll alternately so the operator sees
# progress on both. Use SECONDS for a simple deadline.
deadline_n=$(( SECONDS + NEPTUNE_WAKE_TIMEOUT_S ))
deadline_o=$(( SECONDS + OPENSEARCH_PROCESSING_TIMEOUT_S ))
neptune_done=0
opensearch_done=0

while true; do
  if [ "${neptune_done}" = "0" ]; then
    n=$(aws neptune describe-db-clusters \
      --db-cluster-identifier "${NEPTUNE_CLUSTER_ID}" \
      --region "${AWS_REGION}" \
      --query 'DBClusters[0].Status' --output text)
    if [ "${n}" = "available" ]; then
      log_ok "Neptune available."
      neptune_done=1
    elif [ "${SECONDS}" -ge "${deadline_n}" ]; then
      log_warn "Neptune wake timeout (still '${n}'). Check the console."
      neptune_done=1
    fi
  fi
  if [ "${opensearch_done}" = "0" ]; then
    o=$(aws opensearch describe-domain \
      --domain-name "${OPENSEARCH_DOMAIN_NAME}" \
      --region "${AWS_REGION}" \
      --query 'DomainStatus.Processing' --output text)
    if [ "${o}" = "False" ]; then
      log_ok "OpenSearch processing complete."
      opensearch_done=1
    elif [ "${SECONDS}" -ge "${deadline_o}" ]; then
      log_warn "OpenSearch wake timeout (Processing still True). Check the console."
      opensearch_done=1
    fi
  fi
  if [ "${neptune_done}" = "1" ] && [ "${opensearch_done}" = "1" ]; then
    break
  fi
  printf "    waiting %ss... (neptune_done=%s opensearch_done=%s)\n" \
    "${POLL_INTERVAL_S}" "${neptune_done}" "${opensearch_done}"
  sleep "${POLL_INTERVAL_S}"
done

cat <<EOF

[OK]   Sandbox wake complete.
[INFO] Verify the MCP server can query both stores:
       python3.12 -c "from mcp.client.stdio import stdio_client; print('OK')"

EOF
