import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';
import { applyEnvironmentTag, stackName } from './env';

export interface NetworkStackProps extends cdk.StackProps {
  environmentName: string;
}

/**
 * MdcMcpRag-Network-{env} (R11.4) -- VPC, subnets, route tables, security
 * groups, and the S3 *gateway* endpoint (free). The NAT Gateway is
 * deliberately NOT declared here (it bills per hour and lives in the Compute
 * stack). No compute resource and no per-hour resource exist in this stack.
 * Never destroyed by the orchestrator.
 */
export class NetworkStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly computeSecurityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: NetworkStackProps) {
    super(scope, id, { ...props, stackName: stackName('Network', props.environmentName) });
    const env = props.environmentName;

    // VPC with public + isolated-private subnets and NO NAT gateways
    // (`natGateways: 0`). Public subnets exist so the Compute stack can place
    // its (per-hour) NAT Gateway; private subnets are isolated.
    this.vpc = new ec2.Vpc(this, 'Vpc', {
      vpcName: `mdc-mcp-rag-${env}`,
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24, mapPublicIpOnLaunch: false },
        { name: 'private', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
      restrictDefaultSecurityGroup: true,
    });

    // Free S3 gateway endpoint (no hourly charge) so private subnets can reach
    // S3 without egress through the NAT. Interface endpoints are intentionally
    // omitted from Network because they bill per hour.
    this.vpc.addGatewayEndpoint('S3GatewayEndpoint', {
      service: ec2.GatewayVpcEndpointAwsService.S3,
    });

    this.computeSecurityGroup = new ec2.SecurityGroup(this, 'ComputeSecurityGroup', {
      vpc: this.vpc,
      securityGroupName: `mdc-mcp-rag-compute-${env}`,
      description: 'Compute-tier security group (EC2, Neptune, OpenSearch)',
      allowAllOutbound: false,
    });
    // Scoped egress: HTTPS to the internet (AWS APIs / Bedrock) and the
    // intra-VPC service ports. Specific protocols/ports avoid the
    // all-protocols (-1) egress finding; the HTTPS-to-world rule is the
    // standard, justified egress for a private compute host.
    this.computeSecurityGroup.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS egress');
    this.computeSecurityGroup.addEgressRule(
      ec2.Peer.ipv4(this.vpc.vpcCidrBlock), ec2.Port.tcp(8182), 'Neptune intra-VPC');
    this.computeSecurityGroup.addEgressRule(
      ec2.Peer.ipv4(this.vpc.vpcCidrBlock), ec2.Port.tcp(2049), 'EFS intra-VPC');

    // Cross-stack exports consumed by Storage + Compute (R11.5).
    new cdk.CfnOutput(this, 'VpcIdExport', {
      value: this.vpc.vpcId,
      exportName: `MdcMcpRag-Network-${env}-VpcId`,
    });
    new cdk.CfnOutput(this, 'ComputeSecurityGroupIdExport', {
      value: this.computeSecurityGroup.securityGroupId,
      exportName: `MdcMcpRag-Network-${env}-ComputeSgId`,
    });

    applyEnvironmentTag(this, env);
  }
}
