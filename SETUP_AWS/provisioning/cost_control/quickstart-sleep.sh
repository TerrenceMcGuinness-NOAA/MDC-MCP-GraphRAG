#!/bin/bash
################################################################################
# quickstart-sleep.sh -- Hibernate the sandbox compute footprint
#
# Snapshots Neptune, stops it, then scales OpenSearch down to t3.small x 1.
# Manual OpenSearch snapshot to customer S3 is skipped when the snapshot role
# is absent (PowerUserRestrictions); the AWS-managed automated daily snapshot
# is the fallback. AgentCore and EC2 are left untouched -- AgentCore bills
# zero when idle, EC2 is the host you're running this from.
#
# Idempotent: re-running while already asleep is a safe no-op.
#
# Usage:  ./quickstart-sleep.sh [--yes]
#
# Cost impact (sandbox): ~$50/day awake -> ~$5-10/day asleep (~$45 saved).
################################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/quickstart-config.sh"

YES="${1:-}"
TIMESTAMP=$(date -u +%Y%m%d-%H%M%S)

# ── Confirmation gate ─────────────────────────────────────────────────────
if [ "${YES}" != "--yes" ]; then
  cat <<EOF

[WARN]  About to hibernate the sandbox compute footprint:
  - Snapshot Neptune cluster '${NEPTUNE_CLUSTER_ID}' and stop it
  - Scale OpenSearch '${OPENSEARCH_DOMAIN_NAME}' down to ${OPENSEARCH_SLEEP_INSTANCE_TYPE} x ${OPENSEARCH_SLEEP_INSTANCE_COUNT}, single-AZ

[WARN]  Type 'sleep' to proceed (or anything else to cancel):
EOF
  read -r answer
  if [ "${answer}" != "sleep" ]; then
    log_warn "Cancelled by operator."
    exit 1
  fi
fi

# ── Neptune: snapshot then stop ───────────────────────────────────────────
neptune_status=$(aws neptune describe-db-clusters \
  --db-cluster-identifier "${NEPTUNE_CLUSTER_ID}" \
  --region "${AWS_REGION}" \
  --query 'DBClusters[0].Status' --output text)

if [ "${neptune_status}" = "stopped" ] || [ "${neptune_status}" = "stopping" ]; then
  log_info "Neptune already ${neptune_status}; skip."
else
  snap_id="prehibernate-${NEPTUNE_CLUSTER_ID}-${TIMESTAMP}"
  log_info "Creating Neptune snapshot ${snap_id}..."
  aws neptune create-db-cluster-snapshot \
    --db-cluster-snapshot-identifier "${snap_id}" \
    --db-cluster-identifier "${NEPTUNE_CLUSTER_ID}" \
    --region "${AWS_REGION}" \
    --output text >/dev/null

  # Wait for the snapshot to reach 'available' before the destructive stop.
  log_info "Waiting for snapshot to become available..."
  while true; do
    snap_status=$(aws neptune describe-db-cluster-snapshots \
      --db-cluster-snapshot-identifier "${snap_id}" \
      --region "${AWS_REGION}" \
      --query 'DBClusterSnapshots[0].Status' --output text 2>/dev/null || echo "unknown")
    if [ "${snap_status}" = "available" ]; then
      log_ok "Snapshot ${snap_id} available."
      break
    fi
    if [ "${snap_status}" = "failed" ]; then
      log_error "Snapshot ${snap_id} failed. Aborting -- cluster left awake."
      exit 1
    fi
    printf "    snapshot %s; waiting %ss...\n" "${snap_status}" "${POLL_INTERVAL_S}"
    sleep "${POLL_INTERVAL_S}"
  done

  log_info "Stopping Neptune cluster ${NEPTUNE_CLUSTER_ID}..."
  aws neptune stop-db-cluster \
    --db-cluster-identifier "${NEPTUNE_CLUSTER_ID}" \
    --region "${AWS_REGION}" \
    --output text >/dev/null
  log_ok "Neptune stop initiated. Snapshot kept: ${snap_id}"
fi

# ── OpenSearch: scale down ────────────────────────────────────────────────
os_type=$(aws opensearch describe-domain \
  --domain-name "${OPENSEARCH_DOMAIN_NAME}" \
  --region "${AWS_REGION}" \
  --query 'DomainStatus.ClusterConfig.InstanceType' --output text)
os_count=$(aws opensearch describe-domain \
  --domain-name "${OPENSEARCH_DOMAIN_NAME}" \
  --region "${AWS_REGION}" \
  --query 'DomainStatus.ClusterConfig.InstanceCount' --output text)

if [ "${os_type}" = "${OPENSEARCH_SLEEP_INSTANCE_TYPE}" ] && [ "${os_count}" = "${OPENSEARCH_SLEEP_INSTANCE_COUNT}" ]; then
  log_info "OpenSearch already scaled down (${os_type} x ${os_count}); skip."
else
  log_info "Scaling OpenSearch down to ${OPENSEARCH_SLEEP_INSTANCE_TYPE} x ${OPENSEARCH_SLEEP_INSTANCE_COUNT}, single-AZ..."
  aws opensearch update-domain-config \
    --domain-name "${OPENSEARCH_DOMAIN_NAME}" \
    --cluster-config "InstanceType=${OPENSEARCH_SLEEP_INSTANCE_TYPE},InstanceCount=${OPENSEARCH_SLEEP_INSTANCE_COUNT},DedicatedMasterEnabled=false,ZoneAwarenessEnabled=false" \
    --vpc-options "SubnetIds=${OPENSEARCH_SLEEP_SUBNET},SecurityGroupIds=${OPENSEARCH_VPC_SECURITY_GROUP}" \
    --auto-tune-options 'DesiredState=DISABLED' \
    --region "${AWS_REGION}" \
    --output text >/dev/null
  log_ok "OpenSearch scale-down submitted. Blue/green takes ~30-45 min; queries continue during cutover."
fi

cat <<EOF

[OK]   Sandbox hibernation initiated.
[INFO] Neptune is stopping; OpenSearch blue/green is in flight.
[INFO] Run ./quickstart-status.sh in ~45 min to verify both reached the asleep state.
[INFO] Day-7 caveat: AWS auto-restarts stopped Neptune clusters. If still asleep,
       re-stop on day 6 with ./quickstart-sleep.sh --yes.

EOF
