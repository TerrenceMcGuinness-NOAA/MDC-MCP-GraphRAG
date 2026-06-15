# cfn-guard exceptions -- nih-sandbox-cost-control CDK

Validation tooling: the `aws-infrastructure-as-code` power
(`awslabs.aws-iac-mcp-server` 1.0.16) -- `validate_cloudformation_template`
(cfn-lint 1.48.1) and `check_cloudformation_template_compliance`
(cfn-guard / guardpycfn, AWS Guard Rules default rule set).

Run against all four synthesized templates (`cdk synth --all -c env=dev`).

## cfn-lint: CLEAN

| Template | Errors | Warnings |
|----------|--------|----------|
| MdcMcpRag-Network-dev  | 0 | 1 (W3005, framework) |
| MdcMcpRag-Storage-dev  | 0 | 0 |
| MdcMcpRag-IAM-dev      | 0 | 0 |
| MdcMcpRag-Compute-dev  | 0 | 0 |

The single Network W3005 ("dependency already enforced by a GetAtt") is on the
CDK-generated `CustomVpcRestrictDefaultSGCustomResourceProvider` role -- a
framework artifact of `restrictDefaultSecurityGroup: true` (a security best
practice), not authored code.

## cfn-guard: fixed vs accepted

Findings fixed during Wave 4:
- `EBS_OPTIMIZED_INSTANCE`, `EC2_INSTANCE_DETAILED_MONITORING_ENABLED`
  (EC2: `ebsOptimized` + `detailedMonitoring` set true)
- `SECURITY_GROUP_EGRESS_ALL_PROTOCOLS_RULE` (compute SG egress scoped to
  specific TCP ports instead of all-protocols `-1`)
- `SUBNET_AUTO_ASSIGN_PUBLIC_IP_DISABLED` (public subnets
  `mapPublicIpOnLaunch: false`)
- 1 of 2 IAM wildcard findings (re-sleep `StopDBCluster` scoped to the cluster
  ARN; logs scoped to the function's log group)
- Compute is now fully cfn-guard clean (0 violations).

Accepted (justified) residuals:

| Rule | Stack | Justification |
|------|-------|---------------|
| `S3_BUCKET_DEFAULT_LOCK_ENABLED` | Storage | **Must not enable.** The orchestrator rewrites `state.json` on every transition (R8.3) and appends per-op audit objects; S3 Object Lock would make those writes immutable and break the state machine. Intentionally off. |
| `S3_BUCKET_REPLICATION_ENABLED` | Storage | Cross-region replication is cost + ops overhead counter to the funding-preservation goal of this feature for sandbox state/audit/snapshot buckets. Buckets are already versioned (RETAIN). |
| `S3_BUCKET_LOGGING_ENABLED` | Storage | Server access logging needs a separate log bucket (bootstrap recursion); CloudTrail data events cover access auditing where required. |
| `S3_BUCKET_SSL_REQUESTS_ONLY` | Storage | **False association.** `enforceSSL: true` emits the deny-non-SSL bucket policy (3 `AWS::S3::BucketPolicy` with `aws:SecureTransport: false` deny present in the template); guardpycfn does not link the separate `BucketPolicy` resource to the bucket. |
| `S3_BUCKET_NO_PUBLIC_RW_ACL` | Storage | **False positive.** All three buckets set `BlockPublicAccess.BLOCK_ALL`; guardpycfn does not read the `PublicAccessBlockConfiguration` association. |
| `SECURITY_GROUP_EGRESS_PORT_RANGE_RULE` | Storage | CDK's `allowAllOutbound: false` placeholder egress rule on the EFS mount-target SG. EFS needs no egress; the rule denies all traffic. Framework artifact. |
| `EC2_SECURITY_GROUP_EGRESS_OPEN_TO_WORLD_RULE` | Network | The compute host needs HTTPS (443) egress to AWS service / Bedrock endpoints; `0.0.0.0/0` on 443 is the standard, scoped internet egress for a private host. |
| `NO_UNRESTRICTED_ROUTE_TO_IGW` | Network | The public subnet's `0.0.0.0/0 -> IGW` route is required so the (Compute-stack) NAT Gateway can provide egress. Inherent to any NAT architecture. |
| `IAM_NO_INLINE_POLICY_CHECK` | Network | CDK-framework `restrictDefaultSecurityGroup` custom-resource provider role (inline policy). Not authored code; the security benefit (closing the default SG) outweighs the finding. Our own roles use managed (`AWS::IAM::Policy`) attachments, not inline `Policies`. |
| `IAM_POLICYDOCUMENT_NO_WILDCARD_RESOURCE` | IAM | `rds:DescribeDBClusters` does not support resource-level permissions, so it must use `Resource: "*"`. All other actions (`StopDBCluster`, S3, logs) are ARN-scoped. The orchestrator role's compute-mutation policy is generated + reviewed in Task 16. |

These residuals are best-practice / framework / false-positive items; none
represents a security or data-safety regression. The data-safety contract
(every stateful resource `DeletionPolicy: Retain`) is asserted by the CDK
test suite and verified clean.
