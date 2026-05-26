import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as opensearch from 'aws-cdk-lib/aws-opensearchservice';
import * as efs from 'aws-cdk-lib/aws-efs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

interface MdcDataStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
  ecsSecurityGroup: ec2.SecurityGroup;
}

export class MdcDataStack extends cdk.Stack {
  public readonly neptuneEndpoint: string;
  public readonly openSearchDomain: opensearch.IDomain;

  constructor(scope: Construct, id: string, props: MdcDataStackProps) {
    super(scope, id, props);

    const { vpc, ecsSecurityGroup } = props;

    // --- Neptune (import existing cluster — admin-created) ---
    // Cluster: mdc-mcp-rag-neptune (59,759 nodes, 2,633,374 rels)
    // Bulk loader role already exists (mdc-mcp-rag-neptune-s3-loader)
    this.neptuneEndpoint = 'mdc-mcp-rag-neptune.cluster-czm8iyqe6brc.us-east-1.neptune.amazonaws.com';

    // --- OpenSearch (import existing domain) ---
    this.openSearchDomain = opensearch.Domain.fromDomainEndpoint(this, 'OpenSearchDomain',
      'https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com'
    );

    // --- EFS filesystem (/mdc-mcp-rag persistent mount) ---
    const fileSystem = new efs.FileSystem(this, 'MdcEfs', {
      vpc,
      fileSystemName: 'mdc-mcp-rag-efs',
      encrypted: true,
      lifecyclePolicy: efs.LifecyclePolicy.AFTER_30_DAYS,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      // Suppress CDK's auto-generated restrictive policy so our explicit
      // `fileSystemPolicy` below is the only statement on the FS. CDK's
      // default emits an allow for ClientWrite + ClientRootAccess gated
      // by AccessedViaMountTarget but omits ClientMount, which would
      // require IAM ClientMount on every caller. Setting
      // `allowAnonymousAccess: true` lets us provide our own policy.
      allowAnonymousAccess: true,
      // Explicit file-system policy so:
      //   - operator hosts in the EFS SG ingress can mount the FS root for
      //     populate / maintenance scripts (R12 ops),
      //   - the runtime continues to be gated by IAM (its policy further
      //     scopes ClientMount via ArnEquals on the access point ARN — see
      //     infrastructure/iam/efs-clientmount-workflow-ap.json, R11.4).
      // SG-based network gating remains the perimeter (R11.9).
      fileSystemPolicy: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            sid: 'AllowMountFromVPCViaMountTarget',
            effect: iam.Effect.ALLOW,
            principals: [new iam.AnyPrincipal()],
            actions: [
              'elasticfilesystem:ClientMount',
              'elasticfilesystem:ClientWrite',
              'elasticfilesystem:ClientRootAccess',
            ],
            conditions: {
              Bool: { 'elasticfilesystem:AccessedViaMountTarget': 'true' },
            },
          }),
        ],
      }),
    });
    fileSystem.connections.allowFrom(ecsSecurityGroup, ec2.Port.tcp(2049), 'ECS to EFS');

    // --- EFS access point for AgentCore /mnt/workflow read-only mount ---
    // Pinned at the per-tenant worktree root with POSIX 1000:1000 to match
    // the container's `app` user. The bare repo at <EFS>/.git lives outside
    // this access-point root and is therefore invisible to the runtime.
    // See spec: .kiro/specs/omd-tenants-1-foundation/design.md §8 "CDK changes".
    // Implements R11.1, R12.4.
    const workflowAccessPoint = new efs.AccessPoint(this, 'WorkflowAccessPoint', {
      fileSystem,
      path: '/supported_repos/global-workflow',
      posixUser: { uid: '1000', gid: '1000' },
      createAcl: {
        ownerUid: '1000',
        ownerGid: '1000',
        permissions: '0755',
      },
    });

    // --- S3 migration staging bucket ---
    new s3.Bucket(this, 'MigrationBucket', {
      bucketName: 'mdc-mcp-rag-migration',
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // Outputs
    new cdk.CfnOutput(this, 'NeptuneClusterEndpoint', {
      value: this.neptuneEndpoint,
      description: 'Neptune cluster endpoint (imported)',
    });
    new cdk.CfnOutput(this, 'EfsFileSystemId', {
      value: fileSystem.fileSystemId,
      description: 'EFS filesystem ID for /mdc-mcp-rag',
    });
    new cdk.CfnOutput(this, 'WorkflowAccessPointId', {
      value: workflowAccessPoint.accessPointId,
      description: 'EFS access point for AgentCore /mnt/workflow mount',
    });
    new cdk.CfnOutput(this, 'WorkflowAccessPointArn', {
      value: workflowAccessPoint.accessPointArn,
      description: 'EFS access point ARN - used in the IAM policy condition',
    });
  }
}
