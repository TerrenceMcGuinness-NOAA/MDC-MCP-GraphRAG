#!/bin/bash
# Shared configuration for AWS user-provisioning scripts.
# Sourced by SETUP_AWS/provisioning/provision-user-accounts.sh after common.sh.
#
# SPOT boundary: this file holds provisioning *knobs*. The list of users who get
# provisioned stays in users.conf (username:full_name:email) — that remains the
# single source of truth for WHO, this file is the source of truth for HOW.
#
# Spec: .kiro/specs/aws-user-provisioning-drift-remediation/

# Scratch workspace root for provisioned users. Leaf directories are CamelCase
# (First.Last) derived from the users.conf full-name field, NOT from the
# lowercase login name — "mcguinness" cannot be capitalised back to "McGuinness".
SCRATCH_ROOT="${PERSISTENT_ROOT}/SCRATCH"

# Shared repository checkout. On AWS every developer works from this one
# group-readable tree; there is no per-user clone (contrast the COTS host, where
# each user gets their own clone under scratch).
WORKSPACE="${PERSISTENT_ROOT}/eib-mcp-rag-server"

# Shared group granting access to ${WORKSPACE}.
SHARED_GROUP="developers"

# Supplementary groups every provisioned user is expected to belong to.
# Groups absent from the host are skipped with a [WARN], never a failure.
PROVISION_SUPP_GROUPS=(
  "${SHARED_GROUP}"
)

# Primary group for provisioned users.
#
# EMPTY IS THE AWS DEFAULT AND IS CORRECT: `useradd -m -s /bin/bash -G developers`
# gives each user their own private primary group (alice.smith:alice.smith), with
# `developers` as a supplementary group. An empty value means resolve_ownership
# falls through to each user's private group, no primary-group drift is ever
# reported, and no `usermod -g` is ever issued.
#
# Set this to an existing group name only if this host adopts a shared primary
# group (the COTS host uses "pwuser"). The field name is deliberately shared with
# SETUP/provisioning/user_config.sh so both platforms read the same way.
PROVISION_PRIMARY_GROUP="${PROVISION_PRIMARY_GROUP:-}"

# When "yes", the scratch-owner fix chowns pre-existing content under
# ${SCRATCH_ROOT}/<Scratch.Name> to the target user. Default "no" preserves
# operator- or peer-staged files: only the top-level directory is re-owned and
# every child that belongs to someone else is reported as [PRESERVED].
PROVISION_ADOPT_PRESTAGED="${PROVISION_ADOPT_PRESTAGED:-no}"

# Users who manage their own ~/.kiro configuration. For these, a missing
# mcp.json / steering bundle is intentional, not drift, and no ~/.kiro rows
# appear in the integrity report. Typically an operator running a hand-tuned
# Kiro setup.
PROVISION_KIRO_EXEMPT_USERS=(
)

# Expected AWS profile in each user's ~/.kiro/settings/mcp.json. Mirrors
# user-templates/mcp.json and RUNBOOK_developer_aws_credentials.md, which
# instructs users to create an [agentcore-rag] profile in ~/.aws/credentials.
#
# Set to "" to invert the check to "expect NO AWS_PROFILE key", i.e. let boto3
# fall through to the EC2 instance profile.
PROVISION_AWS_PROFILE="agentcore-rag"

# Literal placeholder written into a fresh ~/.aws/credentials. Its presence means
# the user has not yet pasted a real IAM access key, which only they can do
# (see RUNBOOK_developer_aws_credentials.md) — reported as [PENDING user action],
# never remediated by the operator.
PROVISION_AWS_CRED_PLACEHOLDER="PASTE_YOUR_ACCESS_KEY_ID_HERE"
