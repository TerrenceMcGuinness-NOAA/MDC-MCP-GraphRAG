# VPC Endpoint Provisioning Request

**Date:** April 2, 2026
**Requestor:** Terry McGuinness (terry.mcguinness@noaa.gov)
**Account:** 903050880929
**Region:** us-east-1
**Project:** MDC MCP RAG Server — AWS Infrastructure Port (Phase 48/49)

## Summary

The NWS POCAI Software Engineering team is porting the MDC MCP RAG Server from Docker-based Parallel Works VMs to AWS-native services (OpenSearch, Neptune, ECS Fargate, SageMaker, Bedrock). The application runs entirely within the existing VPC (`vpc-055f30ffa3d661e6b`) on private subnets with no Internet Gateway or NAT Gateway.

To enable private connectivity to AWS managed services, we are requesting the creation of 9 VPC Interface Endpoints. No changes to the VPC topology, routing tables, subnets, or gateways are required.

## Existing VPC Configuration

| Resource | Value |
|----------|-------|
| VPC ID | `vpc-055f30ffa3d661e6b` |
| VPC Name | `nihacio-nwspocaisofteng-vpc` |
| CIDR | `10.40.132.0/22` |
| Internet Gateway | None |
| NAT Gateway | None |
| Existing Endpoints | S3 Gateway (`vpce-0ab581c681d867664`) |
| Endpoints Security Group | `sg-054437d2d5ea5ece9` (`nihacio-nwspocaisofteng-endpoints-sg`) |

### Usable Private Subnets

| Subnet Name | Subnet ID | AZ | CIDR |
|-------------|-----------|-----|------|
| PrivateSubnet1 | `subnet-024fd9b597b3075a5` | us-east-1d | 10.40.136.0/24 |
| PrivateSubnet2 | `subnet-0e13af6b3a9a6416f` | us-east-1a | 10.40.137.0/24 |
| PrivateSubnet3 | `subnet-04447750c61bd7e06` | us-east-1b | 10.40.138.0/24 |

## Requested VPC Endpoints

All endpoints should be:
- **Type:** Interface
- **VPC:** `vpc-055f30ffa3d661e6b`
- **Subnets:** All 3 private subnets listed above (for HA across AZs)
- **Security Group:** `sg-054437d2d5ea5ece9` (existing endpoints SG)
- **Private DNS:** Enabled

### Priority 1 — Required for Core Deployment

| # | Service Name | Purpose |
|---|-------------|---------|
| 1 | `com.amazonaws.us-east-1.secretsmanager` | Application config resolution — fetches database credentials and API tokens from Secrets Manager at startup |
| 2 | `com.amazonaws.us-east-1.ssm` | Parameter Store — fetches Neptune/OpenSearch endpoints and runtime configuration |
| 3 | `com.amazonaws.us-east-1.logs` | CloudWatch Logs — ECS task logging, SageMaker job logging, application monitoring |
| 4 | `com.amazonaws.us-east-1.ecr.api` | ECR API — ECS Fargate pulls container images from private ECR repository |
| 5 | `com.amazonaws.us-east-1.ecr.dkr` | ECR Docker — ECS Fargate pulls container image layers from ECR |

### Priority 2 — Required for Embedding Generation and ML Workloads

| # | Service Name | Purpose |
|---|-------------|---------|
| 6 | `com.amazonaws.us-east-1.bedrock-runtime` | Bedrock Runtime — generates vector embeddings using Amazon Titan and Nova Multimodal models for the RAG knowledge base |
| 7 | `com.amazonaws.us-east-1.sagemaker.api` | SageMaker API — submits and manages Processing Jobs for batch ingestion and model fine-tuning |
| 8 | `com.amazonaws.us-east-1.sagemaker.runtime` | SageMaker Runtime — inference endpoints for custom fine-tuned embedding models |

### Priority 3 — Required for Internet-Facing MCP Service

| # | Service Name | Purpose |
|---|-------------|---------|
| 9 | `com.amazonaws.us-east-1.execute-api` | API Gateway — enables VPC Link connectivity so API Gateway can route external requests to the internal ALB/ECS service |

## Architecture Context

The application exposes an MCP (Model Context Protocol) server that serves 51 AI-powered tools for code analysis, documentation search, and workflow understanding. The architecture uses private-only networking:

```
External Clients
       ↓
CloudFront (AWS-managed, no VPC)
       ↓
API Gateway (AWS-managed, no VPC)
       ↓
VPC Link (ENI in private subnets)  ← requires execute-api endpoint
       ↓
Internal ALB (private subnets)
       ↓
ECS Fargate Tasks (private subnets)
       ↓
┌──────────────┬──────────────┐
│  OpenSearch   │   Neptune    │  ← deployed in same VPC
│  (vectors)    │   (graph)    │
└──────────────┴──────────────┘
```

No Internet Gateway, NAT Gateway, or public subnets are required. All AWS service communication flows through VPC endpoints.

## Security Group Requirements

The existing endpoints security group (`sg-054437d2d5ea5ece9`) should allow:
- **Inbound:** TCP 443 from `10.40.132.0/22` (VPC CIDR)
- **Outbound:** TCP 443 to `0.0.0.0/0` (AWS service endpoints)

Please verify these rules are in place. If not, the following inbound rule is needed:

| Type | Protocol | Port | Source | Description |
|------|----------|------|--------|-------------|
| HTTPS | TCP | 443 | 10.40.132.0/22 | Allow VPC traffic to endpoints |

## What We Do NOT Need

- No Internet Gateway
- No NAT Gateway
- No public subnets
- No VPC peering
- No Transit Gateway
- No changes to existing route tables
- No changes to existing subnets

## Estimated Cost

VPC Interface Endpoints are billed per AZ-hour plus data processing. With 9 endpoints across 3 AZs:
- Endpoint hours: 9 endpoints × 3 AZs × 730 hrs/month = ~19,710 AZ-hours
- At $0.01/AZ-hour = ~$197/month for endpoint availability
- Data processing: $0.01/GB (minimal for API calls, higher for ECR image pulls)
- Estimated total: ~$200-250/month

## Timeline

- **Priority 1 (endpoints 1-5):** Needed before first CDK deployment and ECS service launch
- **Priority 2 (endpoints 6-8):** Needed before embedding experimentation and SageMaker job execution
- **Priority 3 (endpoint 9):** Needed before exposing MCP service to external clients

## Contact

For questions about this request, contact:
- Terry McGuinness — terry.mcguinness@noaa.gov
- Project: NOAA NWS POCAI Software Engineering — MDC MCP RAG Server
