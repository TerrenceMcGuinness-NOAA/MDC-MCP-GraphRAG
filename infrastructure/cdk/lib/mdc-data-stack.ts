import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as neptune from 'aws-cdk-lib/aws-neptune';
import * as opensearch from 'aws-cdk-lib/aws-opensearchservice';
import * as efs from 'aws-cdk-lib/aws-efs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as kms from 'aws-cdk-lib/aws-kms';
import { Construct } from 'constructs';

interface MdcDataStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
  ecsSecurityGroup: ec2.SecurityGroup;
}

export class MdcDataStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: MdcDataStackProps) {
    super(scope, id, props);

    const { vpc, ecsSecurityGroup } = props;
    const privateSubnets = vpc.selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_ISOLATED });

    // --- KMS key for encryption at rest ---
    const encryptionKey = new kms.Key(this, 'MdcEncryptionKey', {
      alias: 'mdc-mcp-rag-key',
      enableKeyRotation: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // --- Neptune security group ---
    const neptuneSg = new ec2.SecurityGroup(this, 'NeptuneSg', {
      vpc,
      securityGroupName: 'mdc-mcp-rag-neptune-sg',
      description: 'Neptune cluster — allow ECS on 8182',
      allowAllOutbound: false,
    });
    neptuneSg.addIngressRule(ecsSecurityGroup, ec2.Port.tcp(8182), 'ECS -> Neptune');

    // --- Neptune cluster (openCypher, IAM auth) ---
    const neptuneSubnetGroup = new neptune.CfnDBSubnetGroup(this, 'NeptuneSubnetGroup', {
      dbSubnetGroupDescription: 'MDC MCP RAG Neptune subnet group',
      subnetIds: privateSubnets.subnetIds,
      dbSubnetGroupName: 'mdc-mcp-rag-neptune-subnets',
    });

    const neptuneCluster = new neptune.CfnDBCluster(this, 'NeptuneCluster', {
      dbClusterIdentifier: 'mdc-mcp-rag-neptune',
      engineVersion: '1.3.2.1',
      dbSubnetGroupName: neptuneSubnetGroup.ref,
      vpcSecurityGroupIds: [neptuneSg.securityGroupId],
      iamAuthEnabled: true,
      storageEncrypted: true,
      kmsKeyId: encryptionKey.keyArn,
      deletionProtection: true,
    });

    new neptune.CfnDBInstance(this, 'NeptuneInstance', {
      dbInstanceClass: 'db.r6g.large',
      dbClusterIdentifier: neptuneCluster.ref,
      dbInstanceIdentifier: 'mdc-mcp-rag-neptune-instance',
    });

    // --- OpenSearch security group ---
    const opensearchSg = new ec2.SecurityGroup(this, 'OpenSearchSg', {
      vpc,
      securityGroupName: 'mdc-mcp-rag-opensearch-sg',
      description: 'OpenSearch domain — allow ECS on 443',
      allowAllOutbound: false,
    });
    opensearchSg.addIngressRule(ecsSecurityGroup, ec2.Port.tcp(443), 'ECS -> OpenSearch');

    // --- OpenSearch domain (k-NN, 768-dim) ---
    new opensearch.Domain(this, 'OpenSearchDomain', {
      domainName: 'mdc-mcp-rag-search',
      version: opensearch.EngineVersion.OPENSEARCH_2_11,
      capacity: {
        dataNodes: 2,
        dataNodeInstanceType: 'r6g.large.search',
      },
      ebs: { volumeSize: 100, volumeType: ec2.EbsDeviceVolumeType.GP3 },
      encryptionAtRest: { enabled: true, kmsKey: encryptionKey },
      nodeToNodeEncryption: true,
      enforceHttps: true,
      vpc,
      vpcSubnets: [{ subnetType: ec2.SubnetType.PRIVATE_ISOLATED }],
      securityGroups: [opensearchSg],
      zoneAwareness: { enabled: true, availabilityZoneCount: 2 },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // --- EFS filesystem (/mdc-mcp-rag persistent mount) ---
    const fileSystem = new efs.FileSystem(this, 'MdcEfs', {
      vpc,
      fileSystemName: 'mdc-mcp-rag-efs',
      encrypted: true,
      kmsKey: encryptionKey,
      lifecyclePolicy: efs.LifecyclePolicy.AFTER_30_DAYS,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
    fileSystem.connections.allowFrom(ecsSecurityGroup, ec2.Port.tcp(2049), 'ECS -> EFS');

    // --- S3 migration staging bucket ---
    new s3.Bucket(this, 'MigrationBucket', {
      bucketName: 'mdc-mcp-rag-migration',
      encryption: s3.BucketEncryption.KMS,
      encryptionKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // Outputs (no secret values)
    new cdk.CfnOutput(this, 'NeptuneClusterEndpoint', {
      value: neptuneCluster.attrEndpoint,
      description: 'Neptune cluster endpoint',
    });
    new cdk.CfnOutput(this, 'EfsFileSystemId', {
      value: fileSystem.fileSystemId,
      description: 'EFS filesystem ID for /mdc-mcp-rag',
    });
  }
}
