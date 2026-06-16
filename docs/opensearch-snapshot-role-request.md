# OpenSearch Manual Snapshot Role Request

**Date**: 2026-06-15
**Requester**: terry.mcguinness@noaa.gov
**Account**: 903050880929 (us-east-1)
**Purpose**: Enable OpenSearch manual snapshots to a customer-owned S3 bucket
for two purposes:

1. Pre-hibernation insurance snapshot before scaling down the production
   OpenSearch domain `mdc-mcp-rag-search` (immediate, this week — funding
   preservation under the NIH Sandbox AWS envelope).
2. Long-term portable export of the vector embeddings to S3 for the
   `cross-platform-data-persistence` feature, which lets the knowledge base
   be rehydrated into either AWS or a COTS Docker stack from a single
   self-describing S3 artifact (ongoing, COB tomorrow).

## Why this is blocked today

The user has the `PowerUserRestrictions` SCP attached, which denies
`iam:CreateRole`, `iam:UpdateAssumeRolePolicy`, and other IAM write
operations. Verbatim denial:

```
$ aws iam create-role --role-name mdc-mcp-rag-opensearch-snapshot-role ...
[ERROR] An error occurred (AccessDenied) when calling the CreateRole
operation: User: arn:aws:iam::903050880929:user/terry.mcguinness@noaa.gov is
not authorized to perform: iam:CreateRole on resource:
arn:aws:iam::903050880929:role/mdc-mcp-rag-opensearch-snapshot-role because
no identity-based policy allows the iam:CreateRole action
```

The bucket itself (`mdc-mcp-rag-snapshots-903050880929`) was created
successfully today and is configured per AWS best practices: versioning
enabled, public access blocked, SSE-S3 default encryption.

OpenSearch's automated daily snapshots into AWS-managed S3 work without
this role and were not affected. **Manual** snapshots into a customer S3
bucket are the only operation that requires this role. Ingestion / query /
domain administration all worked without it (the domain was originally
brought up purely via data-plane SigV4 calls).

## Request

Create a single-purpose IAM role that the OpenSearch service can assume to
read and write objects in the existing snapshot bucket.

### Role name

```
mdc-mcp-rag-opensearch-snapshot-role
```

### Trust policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowOpenSearchAssume",
      "Effect": "Allow",
      "Principal": {
        "Service": "es.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### Inline policy (least privilege, scoped to the one bucket)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListBucket",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::mdc-mcp-rag-snapshots-903050880929"
    },
    {
      "Sid": "ReadWriteObjects",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::mdc-mcp-rag-snapshots-903050880929/*"
    }
  ]
}
```

### PassRole grant on the existing user

After the role exists, the requester needs `iam:PassRole` on the new role
ARN so they can issue the `_snapshot/<repo>` PUT registration call to
OpenSearch (which embeds the role ARN in the request body, requiring
PassRole on the caller). Suggested addition to the user's existing
permissions or as a standalone managed policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PassOpenSearchSnapshotRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::903050880929:role/mdc-mcp-rag-opensearch-snapshot-role"
    }
  ]
}
```

## CLI commands (for admin)

```bash
# 1. Save the trust and inline policy documents
cat > /tmp/os-snapshot-trust.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "es.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF

cat > /tmp/os-snapshot-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect":"Allow","Action":["s3:ListBucket"],"Resource":"arn:aws:s3:::mdc-mcp-rag-snapshots-903050880929"},
    {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],"Resource":"arn:aws:s3:::mdc-mcp-rag-snapshots-903050880929/*"}
  ]
}
EOF

# 2. Create the role
aws iam create-role \
  --role-name mdc-mcp-rag-opensearch-snapshot-role \
  --assume-role-policy-document file:///tmp/os-snapshot-trust.json

# 3. Attach the inline policy
aws iam put-role-policy \
  --role-name mdc-mcp-rag-opensearch-snapshot-role \
  --policy-name s3-snapshot-bucket-access \
  --policy-document file:///tmp/os-snapshot-policy.json

# 4. Grant PassRole on the new role to the requester
cat > /tmp/passrole-os-snapshot.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "iam:PassRole",
    "Resource": "arn:aws:iam::903050880929:role/mdc-mcp-rag-opensearch-snapshot-role"
  }]
}
EOF

aws iam put-user-policy \
  --user-name terry.mcguinness@noaa.gov \
  --policy-name pass-opensearch-snapshot-role \
  --policy-document file:///tmp/passrole-os-snapshot.json
```

## Verification (requester will run after the role exists)

```bash
# Confirm role exists
aws iam get-role --role-name mdc-mcp-rag-opensearch-snapshot-role

# Register the snapshot repository on the OpenSearch domain
# (signed PUT to https://<domain>/_snapshot/mdc-snapshots)
# Expected response: {"acknowledged":true}

# Take a manual snapshot
# (signed PUT to .../_snapshot/mdc-snapshots/prehibernate-20260616)

# Verify snapshot lands in s3://mdc-mcp-rag-snapshots-903050880929/
aws s3 ls s3://mdc-mcp-rag-snapshots-903050880929/
```

## Rollback

```bash
# To remove (if the role is no longer needed)
aws iam delete-role-policy \
  --role-name mdc-mcp-rag-opensearch-snapshot-role \
  --policy-name s3-snapshot-bucket-access

aws iam delete-role \
  --role-name mdc-mcp-rag-opensearch-snapshot-role

aws iam delete-user-policy \
  --user-name terry.mcguinness@noaa.gov \
  --policy-name pass-opensearch-snapshot-role
```

## Context

This is the same pattern as the other two roles already in the account:

- `mdc-mcp-rag-ecs-task-role` — created previously to let
  `bedrock-agentcore.amazonaws.com` assume a role for the AgentCore
  Runtime.
- `mdc-mcp-rag-neptune-s3-loader` — created previously to let Neptune
  bulk-loader (`rds.amazonaws.com`) read from S3.

This new role is the OpenSearch counterpart for manual snapshots — same
"AWS service assumes a role to access customer S3" pattern, scoped to the
single bucket it needs.

The role unlocks two related workstreams:

- **Tonight / tomorrow**: pre-hibernation insurance snapshot of the live
  domain before scaling it down for the prototype-extension shutdown
  (~$37/day savings while asleep).
- **Tomorrow**: the `cross-platform-data-persistence` Vector_Export phase,
  which lands at `SETUP_AWS/provisioning/portable_export/` per the spec.
  That phase produces a self-describing S3 artifact readable by both
  ChromaDB+Neo4j (offline / COTS) and OpenSearch+Neptune (re-import to
  AWS) — funding-resilience insurance against AWS account loss.
