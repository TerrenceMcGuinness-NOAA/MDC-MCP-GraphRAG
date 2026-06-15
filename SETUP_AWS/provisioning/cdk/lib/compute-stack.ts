import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as neptune from 'aws-cdk-lib/aws-neptune';
import * as opensearch from 'aws-cdk-lib/aws-opensearchservice';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import { applyEnvironmentTag, stackName } from './env';

export interface ComputeStackProps extends cdk.StackProps {
  environmentName: string;
  vpc: ec2.IVpc;
  computeSecurityGroup: ec2.ISecurityGroup;
  resleepLambdaRole: iam.IRole;
  /** AgentCore runtime ARN to reference (not created here). */
  agentCoreRuntimeArn?: string;
}

/**
 * MdcMcpRag-Compute-{env} (R11.5) -- every per-hour-billed resource: the EC2
 * instance, the Neptune cluster + instance, the OpenSearch domain, and the NAT
 * Gateway. Plus the AgentCore runtime *reference* (an SSM parameter, not a
 * created runtime), the daily EventBridge re-sleep rule + guard Lambda, and an
 * optional Schedule_Mode (off by default; gated on `-c schedule_enabled=true`).
 *
 * This is the destruction boundary -- the only stack the orchestrator's
 * destructive paths touch. It imports the network/storage/IAM exports rather
 * than redeclaring them (R11.5).
 */
export class ComputeStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ComputeStackProps) {
    super(scope, id, { ...props, stackName: stackName('Compute', props.environmentName) });
    const env = props.environmentName;
    const { vpc, computeSecurityGroup } = props;

    const privateSubnets = vpc.selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_ISOLATED });
    const publicSubnets = vpc.selectSubnets({ subnetType: ec2.SubnetType.PUBLIC });

    // --- EC2 compute host (per-hour) ---
    const instance = new ec2.Instance(this, 'ComputeHost', {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.LARGE),
      machineImage: ec2.MachineImage.latestAmazonLinux2023(),
      securityGroup: computeSecurityGroup,
      requireImdsv2: true,
      ebsOptimized: true,
      detailedMonitoring: true,
      blockDevices: [
        {
          deviceName: '/dev/xvda',
          volume: ec2.BlockDeviceVolume.ebs(60, {
            encrypted: true,
            volumeType: ec2.EbsDeviceVolumeType.GP3,
          }),
        },
      ],
    });
    cdk.Tags.of(instance).add('Name', `mdc-mcp-rag-compute-${env}`);

    // --- Neptune cluster + instance (per-hour; RETAIN, data-safety rule) ---
    const neptuneSubnetGroup = new neptune.CfnDBSubnetGroup(this, 'NeptuneSubnetGroup', {
      dbSubnetGroupDescription: 'Cost-control Neptune subnet group',
      subnetIds: privateSubnets.subnetIds,
      dbSubnetGroupName: `mdc-mcp-rag-neptune-${env}`,
    });
    const neptuneCluster = new neptune.CfnDBCluster(this, 'NeptuneCluster', {
      dbClusterIdentifier: `mdc-mcp-graprag-neptune-${env}`,
      dbSubnetGroupName: neptuneSubnetGroup.dbSubnetGroupName,
      vpcSecurityGroupIds: [computeSecurityGroup.securityGroupId],
      storageEncrypted: true,
      iamAuthEnabled: true,
    });
    neptuneCluster.addDependency(neptuneSubnetGroup);
    neptuneCluster.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN);
    const neptuneInstance = new neptune.CfnDBInstance(this, 'NeptuneInstance', {
      dbInstanceClass: 'db.r5.large',
      dbClusterIdentifier: neptuneCluster.ref,
      dbInstanceIdentifier: `mdc-mcp-graprag-neptune-${env}-1`,
    });
    neptuneInstance.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN);

    // --- OpenSearch domain (per-hour; RETAIN) ---
    const domain = new opensearch.Domain(this, 'OpenSearchDomain', {
      version: opensearch.EngineVersion.OPENSEARCH_2_11,
      domainName: `mdc-mcp-rag-search-${env}`,
      vpc,
      vpcSubnets: [{ subnetType: ec2.SubnetType.PRIVATE_ISOLATED, availabilityZones: vpc.availabilityZones.slice(0, 1) }],
      securityGroups: [computeSecurityGroup],
      capacity: { dataNodes: 1, dataNodeInstanceType: 'r6g.large.search' },
      ebs: { volumeSize: 100, volumeType: ec2.EbsDeviceVolumeType.GP3 },
      zoneAwareness: { enabled: false },
      encryptionAtRest: { enabled: true },
      nodeToNodeEncryption: true,
      enforceHttps: true,
      tlsSecurityPolicy: opensearch.TLSSecurityPolicy.TLS_1_2,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // --- NAT Gateway + Elastic IP (per-hour; recreated on wake by CDK) ---
    const eip = new ec2.CfnEIP(this, 'NatEip', { domain: 'vpc' });
    const natGateway = new ec2.CfnNatGateway(this, 'NatGateway', {
      subnetId: publicSubnets.subnetIds[0],
      allocationId: eip.attrAllocationId,
    });

    // --- AgentCore runtime REFERENCE (not created here) ---
    new ssm.StringParameter(this, 'AgentCoreRuntimeArnParam', {
      parameterName: `/mdc-mcp-rag/cost-control/${env}/agentcore-runtime-arn`,
      stringValue: props.agentCoreRuntimeArn
        ?? 'arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/PLACEHOLDER',
      description: 'AgentCore runtime ARN referenced by the cost-control wake probe',
    });

    // --- Neptune 7-day re-sleep guard Lambda + daily EventBridge rule ---
    const resleepFn = new lambda.Function(this, 'NeptuneResleepFunction', {
      functionName: `mdc-mcp-rag-cost-control-resleep-${env}`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      role: props.resleepLambdaRole,
      timeout: cdk.Duration.minutes(2),
      // Placeholder code; the deploy step packages cost_control/lambdas/
      // neptune_resleep.py (and the cost_control package) as the asset.
      code: lambda.Code.fromInline(
        'def handler(event, context):\n'
        + '    # Replaced at deploy time by the packaged cost_control resleep handler.\n'
        + '    return {"resleep_triggered": False}\n',
      ),
      environment: { COST_CONTROL_ENV: env },
    });
    new events.Rule(this, 'NeptuneResleepRule', {
      ruleName: `mdc-mcp-rag-cost-control-resleep-${env}`,
      description: 'Daily Neptune re-sleep guard (7-day auto-restart mitigation)',
      schedule: events.Schedule.rate(cdk.Duration.days(1)),
      targets: [new targets.LambdaFunction(resleepFn)],
    });

    // --- Optional Schedule_Mode (OFF by default; R14.2) ---
    const scheduleEnabled = this.node.tryGetContext('schedule_enabled') === 'true'
      || this.node.tryGetContext('schedule_enabled') === true;
    if (scheduleEnabled) {
      const sleepCron = this.node.tryGetContext('sleep_cron') as string;
      const wakeCron = this.node.tryGetContext('wake_cron') as string;
      if (!sleepCron || !wakeCron) {
        throw new Error('schedule_enabled=true requires sleep_cron and wake_cron context values');
      }
      new events.Rule(this, 'ScheduledHibernateRule', {
        ruleName: `mdc-mcp-rag-cost-control-hibernate-${env}`,
        description: 'Scheduled hibernate (Schedule_Mode)',
        schedule: events.Schedule.expression(sleepCron),
        targets: [new targets.LambdaFunction(resleepFn)],
      });
      new events.Rule(this, 'ScheduledWakeRule', {
        ruleName: `mdc-mcp-rag-cost-control-wake-${env}`,
        description: 'Scheduled wake (Schedule_Mode)',
        schedule: events.Schedule.expression(wakeCron),
        targets: [new targets.LambdaFunction(resleepFn)],
      });
    }

    // Reference exports for the orchestrator config / audit.
    new cdk.CfnOutput(this, 'Ec2InstanceIdExport', {
      value: instance.instanceId,
      exportName: `MdcMcpRag-Compute-${env}-Ec2InstanceId`,
    });
    new cdk.CfnOutput(this, 'NatGatewayIdExport', {
      value: natGateway.ref,
      exportName: `MdcMcpRag-Compute-${env}-NatGatewayId`,
    });
    new cdk.CfnOutput(this, 'OpenSearchDomainNameExport', {
      value: domain.domainName,
      exportName: `MdcMcpRag-Compute-${env}-OpenSearchDomainName`,
    });

    applyEnvironmentTag(this, env);
  }
}
