import * as iam from 'aws-cdk-lib/aws-iam';

/**
 * Generated least-privilege orchestrator action set (Task 16).
 *
 * Derived by static analysis of the finished cost_control/ orchestrator source
 * (the AWS calls every tier + primitive issues), the role the
 * `iam-policy-autopilot` power fills. The exact source call -> IAM action
 * mapping:
 *
 *   ec2:  DescribeInstances, StopInstances, StartInstances, DescribeSnapshots,
 *         CreateSnapshot, CreateTags, DescribeNatGateways, DeleteNatGateway,
 *         ReleaseAddress
 *   rds:  DescribeDBClusters, CreateDBClusterSnapshot,
 *         DescribeDBClusterSnapshots, StopDBCluster, StartDBCluster
 *                                  (Neptune is an RDS-family service; tags are
 *                                   passed inline via Tags= on snapshot create
 *                                   and do not require AddTagsToResource)
 *   es:   DescribeDomain, UpdateDomainConfig, ESHttpGet/Put/Post
 *         (manual snapshot + status via the OpenSearch _snapshot REST API)
 *   bedrock-agentcore: GetAgentRuntime, UpdateAgentRuntime
 *   ecr:  DescribeImages              (runtime image digest for drift)
 *
 * Note: iam:PassRole is intentionally NOT granted here. The orchestrator
 * does not register the OpenSearch snapshot repository — it only creates
 * snapshots in an already-registered repo via the data-plane REST API.
 * PassRole on the OpenSearch snapshot role belongs on whatever IAM principal
 * does the one-time register (operator step or CDK custom resource), not on
 * the orchestrator runtime role.
 *
 * Resources are ARN-scoped wherever the API supports resource-level
 * permissions. Describe/list APIs (ec2:Describe*, rds:DescribeDBClusters, NAT
 * delete / EIP release) do not support resource-level scoping and therefore
 * use `*` -- this is the documented `IAM_POLICYDOCUMENT_NO_WILDCARD_RESOURCE`
 * exception (CFN_GUARD_EXCEPTIONS.md). The action set itself is minimal.
 *
 * The S3 (state/audit/snapshot) and CloudWatch Logs statements live on the
 * placeholder policy in iam-stack.ts; this module adds only the compute-tier
 * mutation surface.
 */
export function orchestratorPolicyStatements(
  env: string,
  account: string,
): iam.PolicyStatement[] {
  const neptunePrefix = `mdc-mcp-graprag-neptune-${env}`;
  return [
    // EC2 describe + NAT/EIP teardown (no resource-level support -> '*').
    new iam.PolicyStatement({
      sid: 'Ec2DescribeAndNat',
      actions: [
        'ec2:DescribeInstances',
        'ec2:DescribeSnapshots',
        'ec2:DescribeNatGateways',
        'ec2:DeleteNatGateway',
        'ec2:ReleaseAddress',
      ],
      resources: ['*'],
    }),
    // EC2 instance stop/start (instance-scoped).
    new iam.PolicyStatement({
      sid: 'Ec2StopStart',
      actions: ['ec2:StopInstances', 'ec2:StartInstances'],
      resources: [`arn:aws:ec2:*:${account}:instance/*`],
    }),
    // EBS root snapshot create + tag (volume/snapshot-scoped).
    new iam.PolicyStatement({
      sid: 'Ec2Snapshot',
      actions: ['ec2:CreateSnapshot', 'ec2:CreateTags'],
      resources: [
        `arn:aws:ec2:*:${account}:volume/*`,
        `arn:aws:ec2:*:${account}:snapshot/*`,
      ],
    }),
    // Neptune (RDS family) describe (no resource-level -> '*').
    new iam.PolicyStatement({
      sid: 'NeptuneDescribe',
      actions: ['rds:DescribeDBClusters', 'rds:DescribeDBClusterSnapshots'],
      resources: ['*'],
    }),
    // Neptune cluster stop/start/snapshot (cluster + snapshot scoped). Tags
    // are passed inline via Tags= on create_db_cluster_snapshot, which is
    // covered by rds:CreateDBClusterSnapshot itself — no separate
    // rds:AddTagsToResource is required.
    new iam.PolicyStatement({
      sid: 'NeptuneLifecycle',
      actions: [
        'rds:StopDBCluster',
        'rds:StartDBCluster',
        'rds:CreateDBClusterSnapshot',
      ],
      resources: [
        `arn:aws:rds:*:${account}:cluster:${neptunePrefix}*`,
        `arn:aws:rds:*:${account}:cluster-snapshot:cc-${env}-*`,
      ],
    }),
    // OpenSearch scale-down/up + manual snapshot REST (domain-scoped).
    new iam.PolicyStatement({
      sid: 'OpenSearchControl',
      actions: [
        'es:DescribeDomain',
        'es:UpdateDomainConfig',
        'es:ESHttpGet',
        'es:ESHttpPut',
        'es:ESHttpPost',
      ],
      resources: [
        `arn:aws:es:*:${account}:domain/mdc-mcp-rag-search-${env}`,
        `arn:aws:es:*:${account}:domain/mdc-mcp-rag-search-${env}/*`,
      ],
    }),
    // AgentCore runtime read + re-point (runtime-scoped).
    new iam.PolicyStatement({
      sid: 'AgentCoreRuntime',
      actions: ['bedrock-agentcore:GetAgentRuntime', 'bedrock-agentcore:UpdateAgentRuntime'],
      resources: [`arn:aws:bedrock-agentcore:*:${account}:runtime/*`],
    }),
    // ECR image digest read for drift detection (repo-scoped).
    new iam.PolicyStatement({
      sid: 'EcrDescribe',
      actions: ['ecr:DescribeImages'],
      resources: [`arn:aws:ecr:*:${account}:repository/mdc-mcp-rag-${env}`],
    }),
  ];
}
