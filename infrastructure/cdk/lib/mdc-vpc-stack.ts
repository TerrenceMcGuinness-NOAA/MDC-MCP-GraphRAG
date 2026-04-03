import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';

/**
 * MdcVpcStack — imports the existing NOAA VPC instead of creating a new one.
 *
 * The existing VPC (vpc-055f30ffa3d661e6b) has:
 * - 3 usable private subnets across 3 AZs (no public subnets, no IGW, no NAT)
 * - 10 VPC endpoints (S3, Secrets Manager, SSM, Logs, ECR, Bedrock, SageMaker, Execute API)
 * - All AWS service traffic routes through VPC endpoints
 *
 * PowerUserRestrictions policy denies VPC/subnet/gateway creation,
 * so we import rather than create.
 */
export class MdcVpcStack extends cdk.Stack {
  public readonly vpc: ec2.IVpc;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Import the existing VPC by ID
    this.vpc = ec2.Vpc.fromLookup(this, 'ExistingVpc', {
      vpcId: 'vpc-055f30ffa3d661e6b',
    });

    new cdk.CfnOutput(this, 'VpcId', { value: this.vpc.vpcId });
    new cdk.CfnOutput(this, 'VpcCidr', {
      value: 'Imported VPC — see AWS console for CIDR details',
    });
  }
}
