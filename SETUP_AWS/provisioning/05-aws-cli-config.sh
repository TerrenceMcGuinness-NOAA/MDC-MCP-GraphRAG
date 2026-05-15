#!/bin/bash
################################################################################
# 05-aws-cli-config.sh — Configure AWS CLI defaults (region, output format)
# Idempotent: aws configure set is safe to re-run
################################################################################
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
require_root

log_section "AWS CLI Configuration"

OWNER=$(get_actual_user)
REGION="${AWS_REGION:-us-east-1}"
OUTPUT="${AWS_OUTPUT_FORMAT:-json}"

# AWS CLI v2 is pre-installed on Amazon Linux 2023; verify
if ! command_exists aws; then
  log_info "AWS CLI not found — installing v2..."
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
  unzip -q /tmp/awscliv2.zip -d /tmp/awscliv2
  /tmp/awscliv2/aws/install
  rm -rf /tmp/awscliv2 /tmp/awscliv2.zip
  log_success "AWS CLI installed: $(aws --version)"
else
  log_info "AWS CLI present: $(aws --version)"
fi

# Set defaults for the target user
sudo -u "${OWNER}" bash -c "
  aws configure set default.region \"${REGION}\"
  aws configure set default.output \"${OUTPUT}\"
  echo '[OK]    AWS CLI defaults: region=${REGION}, output=${OUTPUT}'
"

log_success "AWS CLI configured"
