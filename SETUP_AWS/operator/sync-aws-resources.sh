#!/bin/bash
################################################################################
# sync-aws-resources.sh — Sync AWS-side resources that are NOT yet in CDK
#
# Run as your **operator user** (the AWS principal with PowerUser-style
# permissions — typically your IAM user, NOT the EC2 instance role). This
# script makes AWS API calls with describe and authorize/revoke EC2
# permissions; the EC2 instance role on this host (e.g. SSMrole) does not
# have those permissions, so do NOT run this with sudo.
#
# Usage:
#   ./SETUP_AWS/operator/sync-aws-resources.sh         # idempotent sync
#   ./SETUP_AWS/operator/sync-aws-resources.sh --check # dry-run, report only
#
# Scope (as of 2026-05-27):
#   - EFS security-group ingress rule allowing this operator host
#     (sg-09bb60ffa41137076 — "launch-wizard-1") to mount the workflow EFS
#     (sg-04bd2b41beecd1201) on TCP 2049. Required for any operator-side
#     EFS populate script (see mcp_server_python/scripts/populate_workflow_efs*.sh).
#
# Why this is not in the bootstrap dispatcher (SETUP_AWS/provisioning/):
#   The provisioning dispatcher runs as root for OS setup. AWS API calls
#   under sudo use the EC2 instance role, which does not have the EC2
#   ingress permissions. This script must run as the operator user with
#   their own AWS credentials. Keeping the auth boundary explicit avoids
#   confusion.
#
# Why this is interim:
#   The CDK MdcDataStack (infrastructure/cdk/lib/mdc-data-stack.ts) is the
#   right long-term home for the EFS SG ingress rule. Until the construct
#   is updated, this script captures the rule so the operator host's
#   ability to populate EFS is reproducible.
#
# Reversibility:
#   To revoke (return to CDK-declared state):
#     aws ec2 revoke-security-group-ingress \
#       --group-id sg-04bd2b41beecd1201 \
#       --security-group-rule-ids sgr-04b3d7802002780ce \
#       --region us-east-1
#
# See SETUP_AWS/DRIFT_REGISTER.md for the full register and remediation plan.
################################################################################

set -euo pipefail

# ── Logging helpers (avoid sourcing common.sh which expects root) ────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info()    { echo -e "${CYAN}[INFO]${NC}  $1"; }
log_success() { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
log_section() { echo ""; echo -e "${CYAN}════════════════════════════════════════${NC}"; echo -e "${CYAN}  $1${NC}"; echo -e "${CYAN}════════════════════════════════════════${NC}"; }

# ── Parse args ──────────────────────────────────────────────────────────
DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case $1 in
    --check|--dry-run) DRY_RUN=true; shift ;;
    --help|-h)
      sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    *) log_error "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Configuration ─────────────────────────────────────────────────────────
AWS_REGION="${AWS_REGION:-us-east-1}"
EFS_SG="${EFS_SG:-sg-04bd2b41beecd1201}"            # MdcDataStack EFS SG
OPERATOR_SG="${OPERATOR_SG:-sg-09bb60ffa41137076}"   # this EC2 host's SG (launch-wizard-1)
NFS_PORT=2049
RULE_DESCRIPTION="Operator host populate (Phase 0 omd-tenants-1-foundation)"

log_section "AWS Resource Sync (interim — pending CDK promotion)"

# ── Pre-flight: must NOT be root (auth model is operator-user) ──────────
if [[ "${EUID}" -eq 0 ]]; then
  log_error "Do not run this script as root."
  log_error "Run as your operator user — the AWS principal with EC2 SG describe/authorize permissions."
  log_error "Under sudo, AWS calls use the EC2 instance role, which does not have these permissions."
  exit 1
fi

# ── Pre-flight: aws CLI authenticated ──────────────────────────────────
if ! command -v aws >/dev/null 2>&1; then
  log_error "aws CLI not found. Install via SETUP_AWS/provisioning/05-aws-cli-config.sh first."
  exit 1
fi

CALLER_ARN=$(aws sts get-caller-identity --region "${AWS_REGION}" --query Arn --output text 2>/dev/null || echo "FAILED")
if [[ "${CALLER_ARN}" == "FAILED" ]]; then
  log_error "aws sts get-caller-identity failed. Configure operator credentials before running."
  exit 1
fi
log_info "AWS identity: ${CALLER_ARN}"
log_info "Region: ${AWS_REGION}"
[[ "${DRY_RUN}" == true ]] && log_warning "DRY-RUN: no changes will be made"

# ── Step 1: EFS SG ingress for operator host ──────────────────────────────
log_info "Checking SG ${EFS_SG} for existing ingress from ${OPERATOR_SG} on TCP ${NFS_PORT}"

existing_rule_id=$(
  aws ec2 describe-security-group-rules \
    --filters "Name=group-id,Values=${EFS_SG}" \
    --region "${AWS_REGION}" \
    --query "SecurityGroupRules[?IsEgress==\`false\` && IpProtocol=='tcp' && FromPort==\`${NFS_PORT}\` && ReferencedGroupInfo.GroupId=='${OPERATOR_SG}'].SecurityGroupRuleId | [0]" \
    --output text 2>/dev/null || echo "None"
)

if [[ "${existing_rule_id}" != "None" && -n "${existing_rule_id}" ]]; then
  log_success "EFS SG ingress rule already present: ${existing_rule_id}"
else
  if [[ "${DRY_RUN}" == true ]]; then
    log_warning "DRY-RUN: would add EFS SG ingress: ${OPERATOR_SG} -> ${EFS_SG}:${NFS_PORT}"
  else
    log_info "Adding EFS SG ingress rule: ${OPERATOR_SG} -> ${EFS_SG}:${NFS_PORT}"
    aws ec2 authorize-security-group-ingress \
      --group-id "${EFS_SG}" \
      --region "${AWS_REGION}" \
      --ip-permissions "IpProtocol=tcp,FromPort=${NFS_PORT},ToPort=${NFS_PORT},UserIdGroupPairs=[{GroupId=${OPERATOR_SG},Description=\"${RULE_DESCRIPTION}\"}]"
    log_success "EFS SG ingress rule added"
  fi
fi

# ── Future steps go here ──────────────────────────────────────────────────
# As we discover more ad-hoc AWS-side state we want to capture (and have
# not yet promoted to CDK), add idempotent blocks below this comment.
# Each block:
#   1. Self-contained (own check + add)
#   2. Logged with log_info / log_success
#   3. Documented with a comment block explaining what and why
#   4. Mirrored in SETUP_AWS/DRIFT_REGISTER.md
#   5. Honors --check / --dry-run

log_success "AWS resource sync complete"
