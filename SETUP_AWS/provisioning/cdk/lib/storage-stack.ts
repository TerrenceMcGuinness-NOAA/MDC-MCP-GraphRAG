import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as efs from 'aws-cdk-lib/aws-efs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';
import { applyEnvironmentTag, bucketName, stackName } from './env';

export interface StorageStackProps extends cdk.StackProps {
  environmentName: string;
  vpc: ec2.IVpc;
}

/**
 * MdcMcpRag-Storage-{env} (R11.2) -- the never-destroyed data tier: EFS file
 * system + access point, the ECR repository (RETAIN), and the versioned S3
 * state / audit / snapshot buckets (the OpenSearch manual-snapshot repository
 * target). Declares no per-hour resource. Every stateful resource carries
 * RemovalPolicy.RETAIN (CDK data-safety rule 05).
 */
export class StorageStack extends cdk.Stack {
  public readonly fileSystem: efs.FileSystem;
  public readonly workflowAccessPoint: efs.AccessPoint;
  public readonly repository: ecr.Repository;
  public readonly stateBucket: s3.Bucket;
  public readonly auditBucket: s3.Bucket;
  public readonly snapshotBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: StorageStackProps) {
    super(scope, id, { ...props, stackName: stackName('Storage', props.environmentName) });
    const env = props.environmentName;

    // --- EFS workflow file system + access point (storage GB-month only) ---
    // Dedicated SG with no egress (EFS mount targets need no outbound).
    const efsSecurityGroup = new ec2.SecurityGroup(this, 'EfsSecurityGroup', {
      vpc: props.vpc,
      securityGroupName: `mdc-mcp-rag-efs-${env}`,
      description: 'EFS mount-target security group (no egress)',
      allowAllOutbound: false,
    });
    this.fileSystem = new efs.FileSystem(this, 'WorkflowEfs', {
      vpc: props.vpc,
      fileSystemName: `mdc-mcp-rag-${env}`,
      encrypted: true,
      securityGroup: efsSecurityGroup,
      lifecyclePolicy: efs.LifecyclePolicy.AFTER_30_DAYS,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
    this.workflowAccessPoint = new efs.AccessPoint(this, 'WorkflowAccessPoint', {
      fileSystem: this.fileSystem,
      path: '/supported_repos/global-workflow',
      posixUser: { uid: '1000', gid: '1000' },
      createAcl: { ownerUid: '1000', ownerGid: '1000', permissions: '0755' },
    });

    // --- ECR repository (image storage GB-month; RETAIN, never pruned by sleep) ---
    this.repository = new ecr.Repository(this, 'EcrRepository', {
      repositoryName: `mdc-mcp-rag-${env}`,
      imageScanOnPush: true,
      imageTagMutability: ecr.TagMutability.IMMUTABLE,
      encryption: ecr.RepositoryEncryption.AES_256,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // --- S3 buckets (state, audit, snapshots) ---
    const makeBucket = (idSuffix: string, purpose: string): s3.Bucket =>
      new s3.Bucket(this, `${idSuffix}Bucket`, {
        bucketName: bucketName(purpose, env),
        encryption: s3.BucketEncryption.S3_MANAGED,
        blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
        enforceSSL: true,
        versioned: true,
        removalPolicy: cdk.RemovalPolicy.RETAIN,
        lifecycleRules: [
          {
            // Retain every prior version for at least the retention window.
            noncurrentVersionExpiration: cdk.Duration.days(365),
            abortIncompleteMultipartUploadAfter: cdk.Duration.days(7),
          },
        ],
      });

    this.stateBucket = makeBucket('State', 'state');
    this.auditBucket = makeBucket('Audit', 'audit');
    this.snapshotBucket = makeBucket('Snapshot', 'snapshots');

    // Cross-stack exports consumed by IAM + Compute (R11.5).
    const out = (name: string, value: string) =>
      new cdk.CfnOutput(this, `${name}Export`, {
        value,
        exportName: `MdcMcpRag-Storage-${env}-${name}`,
      });
    out('EfsId', this.fileSystem.fileSystemId);
    out('WorkflowAccessPointId', this.workflowAccessPoint.accessPointId);
    out('EcrRepositoryArn', this.repository.repositoryArn);
    out('StateBucketArn', this.stateBucket.bucketArn);
    out('AuditBucketArn', this.auditBucket.bucketArn);
    out('SnapshotBucketArn', this.snapshotBucket.bucketArn);

    applyEnvironmentTag(this, env);
  }
}
