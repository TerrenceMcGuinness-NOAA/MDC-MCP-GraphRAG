import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
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
    });
    fileSystem.connections.allowFrom(ecsSecurityGroup, ec2.Port.tcp(2049), 'ECS to EFS');

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
  }
}
