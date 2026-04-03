# CDK Bootstrap Request — Account 903050880929

**Date:** April 3, 2026
**Requestor:** Terry McGuinness (terry.mcguinness@noaa.gov)
**Account:** 903050880929
**Region:** us-east-1
**Project:** MDC MCP RAG Server — AWS Infrastructure Port

## Request

Please run the AWS CDK bootstrap command for account 903050880929 in us-east-1. This is a one-time setup that creates the resources CDK needs to deploy CloudFormation stacks.

## Command

```bash
cdk bootstrap aws://903050880929/us-east-1
```

If CDK CLI is not installed, it can be run via npx:

```bash
npx aws-cdk bootstrap aws://903050880929/us-east-1
```

## Pre-Requisite

A previous failed bootstrap attempt left a `CDKToolkit` stack in `ROLLBACK_COMPLETE` state. Please delete it first:

```bash
aws cloudformation delete-stack --stack-name CDKToolkit --region us-east-1
```

Then run the bootstrap command above.

## Why This Requires Admin

CDK bootstrap creates 4 IAM roles at the account root path. The PowerUser group policy does not allow `iam:CreateRole` outside of `service-role/*` and `aws-service-role/*` paths. The roles CDK needs:

| Role | Purpose |
|------|---------|
| `cdk-hnb659fds-cfn-exec-role-903050880929-us-east-1` | CloudFormation execution role |
| `cdk-hnb659fds-lookup-role-903050880929-us-east-1` | Cross-account resource lookups |
| `cdk-hnb659fds-image-publishing-role-903050880929-us-east-1` | ECR image publishing |
| `cdk-hnb659fds-file-publishing-role-903050880929-us-east-1` | S3 asset publishing |

It also creates an S3 bucket (`cdk-hnb659fds-assets-903050880929-us-east-1`) for CloudFormation template staging.

## What This Enables

Once bootstrapped, the PowerUser account can deploy CDK stacks for:
- Amazon Neptune (graph database)
- Amazon OpenSearch (vector search)
- Amazon ECS Fargate (MCP server hosting)
- Amazon S3 (data migration staging)
- Amazon EFS (persistent storage)
- API Gateway + CloudFront (internet-facing MCP endpoint)

## Impact

- One-time operation, no recurring maintenance
- No changes to existing resources
- No impact on other users or workloads in the account
- Estimated cost: ~$0.03/month (S3 bucket for CDK assets)

## Contact

Terry McGuinness — terry.mcguinness@noaa.gov
Project: NOAA NWS POCAI Software Engineering — MDC MCP RAG Server
