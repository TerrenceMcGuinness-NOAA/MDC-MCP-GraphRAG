# VPC Endpoint Status — All Provisioned

**Date:** April 3, 2026
**VPC:** `vpc-055f30ffa3d661e6b` (`nihacio-nwspocaisofteng-vpc`)
**Account:** 903050880929 | **Region:** us-east-1

## Endpoint Inventory

| # | Service | Endpoint ID | Type | Status |
|---|---------|-------------|------|--------|
| 1 | `com.amazonaws.us-east-1.s3` | `vpce-0ab581c681d867664` | Gateway | ✅ available |
| 2 | `com.amazonaws.us-east-1.secretsmanager` | `vpce-018e1004620e0809c` | Interface | ✅ available |
| 3 | `com.amazonaws.us-east-1.ssm` | `vpce-0c3ddd72bf3b4741f` | Interface | ✅ available |
| 4 | `com.amazonaws.us-east-1.logs` | `vpce-031fee84d40760076` | Interface | ✅ available |
| 5 | `com.amazonaws.us-east-1.ecr.api` | `vpce-002b6dad8b52f8164` | Interface | ✅ available |
| 6 | `com.amazonaws.us-east-1.ecr.dkr` | `vpce-0c3ccaa8273b227bd` | Interface | ✅ available |
| 7 | `com.amazonaws.us-east-1.bedrock-runtime` | `vpce-0c0435f6f4d8ed75d` | Interface | ✅ available |
| 8 | `com.amazonaws.us-east-1.sagemaker.api` | `vpce-0d382ef244f4d03c7` | Interface | ✅ available |
| 9 | `com.amazonaws.us-east-1.sagemaker.runtime` | `vpce-0126e0900563b3167` | Interface | ✅ available |
| 10 | `com.amazonaws.us-east-1.execute-api` | `vpce-0b2f402157c32c1c8` | Interface | ✅ available |

## What This Unblocks

| Capability | Required Endpoints | Status |
|---|---|---|
| CDK Bootstrap + Deploy | S3, Secrets Manager, SSM, Logs, ECR | ✅ Ready |
| Bedrock Embedding Generation | Bedrock Runtime | ✅ Ready |
| SageMaker Processing/Training Jobs | SageMaker API, SageMaker Runtime, ECR, S3, Logs | ✅ Ready |
| Internet-Facing MCP Service | Execute API (VPC Link) | ✅ Ready |
| ECS Fargate Container Pulls | ECR API, ECR Docker, S3 | ✅ Ready |
| Config Resolution (resolveConfig) | Secrets Manager, SSM | ✅ Ready |
| CloudWatch Monitoring | Logs | ✅ Ready |

## Next Steps

1. `cdk bootstrap aws://903050880929/us-east-1` — provision CDK toolkit stack
2. Refactor `MdcVpcStack` to import existing VPC (`vpc-055f30ffa3d661e6b`) instead of creating one — DONE
3. `cdk deploy --all` — provision Neptune, OpenSearch, ECS, S3 migration bucket
4. `create-opensearch-indices.js --model mpnet768` — create target indices
5. Go to Parallel Works for S3 export (`migrate-to-aws.js --phase export-vectors/export-graph`)

## Additional Admin Request: CDK Bootstrap

CDK bootstrap requires creating IAM roles at the account root path, which `PowerUserRestrictions` denies. The admin needs to either:

**Option A:** Run `cdk bootstrap aws://903050880929/us-east-1` with admin credentials (one-time setup)

**Option B:** Manually create these 4 IAM roles (CDK standard bootstrap roles):
- `cdk-hnb659fds-cfn-exec-role-903050880929-us-east-1`
- `cdk-hnb659fds-lookup-role-903050880929-us-east-1`
- `cdk-hnb659fds-image-publishing-role-903050880929-us-east-1`
- `cdk-hnb659fds-file-publishing-role-903050880929-us-east-1`

Plus the CDK staging S3 bucket: `cdk-hnb659fds-assets-903050880929-us-east-1`

**Note:** The failed CDKToolkit stack is in `ROLLBACK_COMPLETE` state and needs to be deleted from the CloudFormation console before retrying.
