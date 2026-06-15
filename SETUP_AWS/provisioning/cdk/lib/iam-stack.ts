import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';
import { applyEnvironmentTag, stackName } from './env';

export interface IamStackProps extends cdk.StackProps {
  environmentName: string;
  stateBucket: s3.IBucket;
  auditBucket: s3.IBucket;
  snapshotBucket: s3.IBucket;
}

/**
 * MdcMcpRag-IAM-{env} (R11.3) -- every IAM role/policy referenced by the other
 * stacks or the orchestrator itself. Never destroyed.
 *
 * The orchestrator role ships in Task 14 with a deliberately minimal
 * placeholder policy (state/audit/snapshot S3 + logs only); Task 16 replaces
 * the action set with the least-privilege policy generated from the finished
 * cost_control/ source and reviewed by the operator. The
 * `attachOrchestratorPolicy()` method is the single wiring point for that.
 */
export class IamStack extends cdk.Stack {
  public readonly orchestratorRole: iam.Role;
  public readonly openSearchSnapshotRole: iam.Role;
  public readonly resleepLambdaRole: iam.Role;

  constructor(scope: Construct, id: string, props: IamStackProps) {
    super(scope, id, { ...props, stackName: stackName('IAM', props.environmentName) });
    const env = props.environmentName;
    const { stateBucket, auditBucket, snapshotBucket } = props;

    // --- Orchestrator execution role (operator CLI / CI / Schedule_Mode Lambda) ---
    this.orchestratorRole = new iam.Role(this, 'OrchestratorRole', {
      roleName: `mdc-mcp-rag-cost-control-orchestrator-${env}`,
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal('lambda.amazonaws.com'),
        new iam.AccountRootPrincipal(),
      ),
      description: 'Cost_Control_System orchestrator role (placeholder policy; '
        + 'refined in Task 16 from the generated least-privilege action set)',
    });
    // Placeholder baseline: only the State_File / audit / snapshot S3 access
    // and CloudWatch Logs the orchestrator always needs. Compute mutation
    // actions are added by attachOrchestratorPolicy() in Task 16.
    this.orchestratorRole.addToPolicy(new iam.PolicyStatement({
      sid: 'StateAuditSnapshotS3',
      actions: ['s3:GetObject', 's3:PutObject', 's3:ListBucket', 's3:GetBucketVersioning'],
      resources: [
        stateBucket.bucketArn, `${stateBucket.bucketArn}/*`,
        auditBucket.bucketArn, `${auditBucket.bucketArn}/*`,
        snapshotBucket.bucketArn, `${snapshotBucket.bucketArn}/*`,
      ],
    }));
    this.orchestratorRole.addToPolicy(new iam.PolicyStatement({
      sid: 'CloudWatchLogs',
      actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
      resources: [`arn:aws:logs:*:${this.account}:log-group:mdc-mcp-rag-cost-control-${env}*`],
    }));

    // --- OpenSearch manual-snapshot role (assumed by OpenSearch to write S3) ---
    this.openSearchSnapshotRole = new iam.Role(this, 'OpenSearchSnapshotRole', {
      roleName: `mdc-mcp-rag-cost-control-os-snapshot-${env}`,
      assumedBy: new iam.ServicePrincipal('es.amazonaws.com'),
      description: 'Role OpenSearch assumes to write manual snapshots to the S3 repo',
    });
    this.openSearchSnapshotRole.addToPolicy(new iam.PolicyStatement({
      actions: ['s3:ListBucket'],
      resources: [snapshotBucket.bucketArn],
    }));
    this.openSearchSnapshotRole.addToPolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject', 's3:PutObject', 's3:DeleteObject'],
      resources: [`${snapshotBucket.bucketArn}/*`],
    }));

    // --- Neptune re-sleep guard Lambda role ---
    this.resleepLambdaRole = new iam.Role(this, 'ResleepLambdaRole', {
      roleName: `mdc-mcp-rag-cost-control-resleep-${env}`,
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Neptune 7-day re-sleep guard Lambda execution role',
    });
    this.resleepLambdaRole.addToPolicy(new iam.PolicyStatement({
      sid: 'NeptuneResleepStop',
      actions: ['rds:StopDBCluster'],
      resources: [`arn:aws:rds:*:${this.account}:cluster:mdc-mcp-graprag-neptune-${env}*`],
    }));
    // DescribeDBClusters does not support resource-level permissions, so it
    // must use '*' (the single, documented cfn-guard exception). See
    // SETUP_AWS/provisioning/cdk/CFN_GUARD_EXCEPTIONS.md.
    this.resleepLambdaRole.addToPolicy(new iam.PolicyStatement({
      sid: 'NeptuneResleepDescribe',
      actions: ['rds:DescribeDBClusters'],
      resources: ['*'],
    }));
    this.resleepLambdaRole.addToPolicy(new iam.PolicyStatement({
      sid: 'ReadState',
      actions: ['s3:GetObject'],
      resources: [`${stateBucket.bucketArn}/*`],
    }));
    this.resleepLambdaRole.addToPolicy(new iam.PolicyStatement({
      sid: 'ResleepLogs',
      actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
      resources: [`arn:aws:logs:*:${this.account}:log-group:/aws/lambda/mdc-mcp-rag-cost-control-resleep-${env}*`],
    }));

    new cdk.CfnOutput(this, 'OrchestratorRoleArnExport', {
      value: this.orchestratorRole.roleArn,
      exportName: `MdcMcpRag-IAM-${env}-OrchestratorRoleArn`,
    });
    new cdk.CfnOutput(this, 'OpenSearchSnapshotRoleArnExport', {
      value: this.openSearchSnapshotRole.roleArn,
      exportName: `MdcMcpRag-IAM-${env}-OpenSearchSnapshotRoleArn`,
    });
    new cdk.CfnOutput(this, 'ResleepLambdaRoleArnExport', {
      value: this.resleepLambdaRole.roleArn,
      exportName: `MdcMcpRag-IAM-${env}-ResleepLambdaRoleArn`,
    });

    applyEnvironmentTag(this, env);
  }

  /**
   * Attach the reviewed least-privilege orchestrator policy (Task 16). Called
   * from bin/cdk.ts with the action set generated from the cost_control/
   * source and approved by the operator. Kept as a method so the generated
   * policy is the single wiring point and the placeholder above stays minimal.
   */
  public attachOrchestratorPolicy(statements: iam.PolicyStatement[]): void {
    for (const stmt of statements) {
      this.orchestratorRole.addToPolicy(stmt);
    }
  }
}
