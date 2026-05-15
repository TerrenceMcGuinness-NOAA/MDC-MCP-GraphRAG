# Requirements Document

## Introduction

Deploy the MDC MCP RAG Server (51 tools, Node.js) to production on AWS using a fully private architecture. The deployment replaces the hand-rolled `mcp-http-server.js` development bridge with a managed ECS Fargate service fronted by a Private API Gateway. All traffic remains within the VPC — no Internet Gateway, no CloudFront, no public endpoints. IAM roles that CDK cannot create (due to PowerUserRestrictions on the CloudFormation execution role) are pre-created by an admin following a documented request pattern.

## Glossary

- **MCP_Server**: The MDC MCP RAG Server — a Node.js application exposing 51 AI-powered tools via the Model Context Protocol (MCP) Streamable HTTP transport
- **Private_API_Gateway**: An Amazon API Gateway REST API configured with PRIVATE endpoint type, accessible only from within the VPC via the `execute-api` VPC endpoint
- **Internal_ALB**: An internal Application Load Balancer deployed in private subnets, routing traffic from the API Gateway VPC Link to ECS Fargate tasks
- **ECS_Service**: An Amazon ECS Fargate service running the MCP_Server container image in private subnets with no public IP assignment
- **ECR_Repository**: An Amazon Elastic Container Registry repository storing the MCP_Server Docker image
- **VPC_Endpoint**: An interface VPC endpoint enabling private connectivity to AWS services without an Internet Gateway
- **Admin_Request_Document**: A plaintext document requesting an NIH account administrator to create narrowly-scoped IAM roles that PowerUser accounts cannot create
- **ECS_Task_Role**: An IAM role assumed by the running ECS container, granting access to Neptune, OpenSearch, Secrets Manager, and SSM Parameter Store
- **ECS_Execution_Role**: An IAM role assumed by the ECS agent to pull container images from ECR and write logs to CloudWatch
- **Dev_Bridge**: The current `mcp-http-server.js` process running on port 3000 on the EC2 instance, serving as a temporary MCP transport during development
- **CDK_Execution_Role**: The CloudFormation execution role (`cdk-hnb659fds-cfn-exec-role-903050880929-us-east-1`) used internally by CDK during stack deployments
- **WAF_WebACL**: An AWS WAF Web Access Control List providing rate limiting and managed rule protection
- **Resource_Policy**: An API Gateway resource policy restricting invoke access to requests originating from the VPC endpoint

## Requirements

### Requirement 1: Admin IAM Role Request Document

**User Story:** As a developer with PowerUser permissions, I want a clear admin request document for the two ECS IAM roles, so that an administrator can create them without ambiguity and I can proceed with CDK deployment.

#### Acceptance Criteria

1. THE Admin_Request_Document SHALL include the exact IAM trust policy JSON for both the ECS_Task_Role and the ECS_Execution_Role, with `ecs-tasks.amazonaws.com` as the trusted service principal
2. THE Admin_Request_Document SHALL include the exact IAM permission policy JSON for the ECS_Task_Role, granting access to Secrets Manager secrets under `mdc-mcp-rag/*`, SSM parameters under `/mdc-mcp-rag/*`, Neptune database connections, and OpenSearch HTTP operations on the `mdc-mcp-rag-search` domain
3. THE Admin_Request_Document SHALL specify that the ECS_Execution_Role uses the AWS managed policy `AmazonECSTaskExecutionRolePolicy`
4. THE Admin_Request_Document SHALL include a "What This Does NOT Do" section confirming no internet exposure, no new network resources, and no changes to user permissions
5. THE Admin_Request_Document SHALL reference the successful Neptune bulk loader role request (`mdc-mcp-rag-neptune-s3-loader`) as precedent for the admin workflow
6. THE Admin_Request_Document SHALL explain why PowerUser cannot create these roles, citing the `PowerUserRestrictions` policy denial of `iam:CreateRole`
7. THE Admin_Request_Document SHALL follow the same plaintext format as `docs/neptune-bulk-loader-role-request.txt`

### Requirement 2: Private API Gateway Configuration

**User Story:** As a platform engineer, I want the API Gateway configured as a PRIVATE endpoint, so that the MCP service is accessible only from within the VPC and complies with the no-IGW security policy.

#### Acceptance Criteria

1. THE Private_API_Gateway SHALL use endpoint type PRIVATE instead of REGIONAL
2. THE Private_API_Gateway SHALL include a Resource_Policy that allows `execute-api:Invoke` only from the existing `execute-api` VPC_Endpoint (`vpce` for `com.amazonaws.us-east-1.execute-api`)
3. THE Private_API_Gateway SHALL route requests on the `/mcp` path to the Internal_ALB via an HTTP proxy integration
4. WHEN a request originates from outside the VPC, THE Private_API_Gateway SHALL deny the request
5. THE Private_API_Gateway SHALL include a `/health` endpoint that proxies to the ECS_Service health check without requiring authentication
6. THE Private_API_Gateway SHALL associate the WAF_WebACL with scope REGIONAL for rate limiting and managed rule protection

### Requirement 3: CloudFront Removal

**User Story:** As a security-conscious operator in an NIH environment, I want CloudFront removed from the deployment architecture, so that no internet-facing CDN component exists.

#### Acceptance Criteria

1. THE MdcServerStack SHALL NOT include a CloudFront distribution resource
2. THE MdcServerStack SHALL NOT include a CLOUDFRONT-scoped WAF WebACL
3. THE MdcServerStack SHALL NOT export a CloudFront domain name output
4. THE MdcServerStack SHALL export the Private_API_Gateway endpoint URL as the primary MCP endpoint output

### Requirement 4: ECS Fargate Service Deployment

**User Story:** As a platform engineer, I want the MCP server running as an ECS Fargate service behind an internal ALB, so that the application is managed, scalable, and operates entirely within private subnets.

#### Acceptance Criteria

1. THE ECS_Service SHALL run in private subnets with `assignPublicIp` set to false
2. THE ECS_Service SHALL use the admin-created ECS_Task_Role (imported by name `mdc-mcp-rag-ecs-task-role`)
3. THE ECS_Service SHALL use the admin-created ECS_Execution_Role (imported by name `mdc-mcp-rag-ecs-execution-role`)
4. THE Internal_ALB SHALL be configured as internal (not internet-facing)
5. THE ECS_Service SHALL configure a health check on the `/health` path with a 200 response code expectation
6. THE ECS_Service SHALL set environment variables `DB_BACKEND=aws`, `NODE_ENV=production`, and `AWS_REGION=us-east-1`
7. THE ECS_Service SHALL pull the container image from the ECR_Repository via the existing ECR VPC endpoints (`ecr.api` and `ecr.dkr`)
8. THE ECS_Service SHALL auto-scale between 1 and 4 tasks based on request count

### Requirement 5: Docker Image Build and ECR Push

**User Story:** As a developer, I want to build the MCP server Docker image and push it to ECR, so that ECS Fargate can pull and run the container from a private registry.

#### Acceptance Criteria

1. THE ECR_Repository SHALL be created with the name `mdc-mcp-rag`
2. THE ECR_Repository SHALL have a lifecycle policy retaining the 10 most recent images
3. WHEN the Docker image is built, THE build process SHALL use the existing Dockerfile pattern from `SETUP/dockerfiles/Dockerfile.mcp-server` adapted for the AWS environment (removing Docker-specific host references)
4. WHEN the Docker image is pushed, THE push process SHALL target the ECR_Repository in account 903050880929, region us-east-1
5. THE container image SHALL expose port 3000 and start the MCP_Server in production mode

### Requirement 6: CDK Stack Deployment Sequence

**User Story:** As a developer, I want a defined CDK deployment sequence that respects stack dependencies and imports existing resources, so that the deployment succeeds without recreating manually provisioned infrastructure.

#### Acceptance Criteria

1. THE deployment sequence SHALL follow the order: MdcVpcStack, MdcSecurityStack, MdcDataStack, MdcServerStack
2. THE MdcVpcStack SHALL import the existing VPC (`vpc-055f30ffa3d661e6b`) by lookup, not create a new VPC
3. THE MdcSecurityStack SHALL import the admin-created ECS roles by name using `iam.Role.fromRoleName`
4. THE MdcDataStack SHALL import existing Neptune cluster (`mdc-mcp-rag-neptune`) and OpenSearch domain (`mdc-mcp-rag-search`) rather than creating new instances
5. IF a CDK stack deployment fails due to a missing IAM role, THEN the deployment process SHALL output a clear error message referencing the Admin_Request_Document
6. THE MdcSecurityStack SHALL delete the existing ROLLBACK_COMPLETE stack before redeployment

### Requirement 7: Kiro MCP Client Configuration Update

**User Story:** As a developer using Kiro, I want the MCP client configuration updated to point to the Private API Gateway endpoint, so that Kiro connects to the production MCP service instead of the Dev_Bridge.

#### Acceptance Criteria

1. WHEN the Private_API_Gateway is deployed, THE Kiro MCP configuration for `mdc-mcp-rag-aws` SHALL be updated with the Private_API_Gateway endpoint URL
2. THE Kiro MCP configuration SHALL use HTTP transport type with the endpoint URL in the format `https://{api-id}-{vpce-id}.execute-api.us-east-1.amazonaws.com/prod/mcp`
3. WHEN the Kiro MCP client connects to the Private_API_Gateway, THE MCP_Server SHALL respond with all 51 tools available

### Requirement 8: Dev Bridge Retirement

**User Story:** As a platform engineer, I want the development bridge retired after production deployment is validated, so that no unnecessary network exposure or manual processes remain.

#### Acceptance Criteria

1. WHEN all 51 MCP tools are verified working through the Private_API_Gateway, THE Dev_Bridge process (`mcp-http-server.js` on port 3000) SHALL be stopped
2. WHEN the Dev_Bridge is retired, THE security group rule allowing inbound traffic on port 3000 SHALL be removed
3. THE Dev_Bridge retirement SHALL occur only after the Kiro MCP client is confirmed working against the Private_API_Gateway endpoint

### Requirement 9: Data Preservation During Deployment

**User Story:** As a data steward, I want existing Neptune and OpenSearch data preserved during CDK deployment, so that the 59,759 graph nodes, 2.6M relationships, and 85,921 search documents are not lost.

#### Acceptance Criteria

1. THE MdcDataStack SHALL use CDK resource import (not create) for the existing Neptune cluster (`mdc-mcp-rag-neptune` with 59,759 nodes and 2,633,374 relationships)
2. THE MdcDataStack SHALL use CDK resource import (not create) for the existing OpenSearch domain (`mdc-mcp-rag-search` with 85,921 documents across 10 indices)
3. IF a CDK deployment would result in replacement of the Neptune cluster or OpenSearch domain, THEN the deployment SHALL fail with a clear error rather than proceeding
4. THE MdcDataStack SHALL set `removalPolicy: RETAIN` on both the Neptune cluster and OpenSearch domain

### Requirement 10: Network Security Compliance

**User Story:** As a security officer, I want the deployment to comply with NIH no-IGW policy, so that all traffic stays within the VPC or traverses VPC endpoints exclusively.

#### Acceptance Criteria

1. THE deployment architecture SHALL NOT include an Internet Gateway, NAT Gateway, or public subnet
2. THE ECS_Service SHALL communicate with AWS services (ECR, CloudWatch Logs, Secrets Manager, SSM) exclusively through existing VPC endpoints
3. THE ECS_Service SHALL communicate with Neptune and OpenSearch through direct VPC connectivity (same VPC, private subnets)
4. THE Private_API_Gateway SHALL be accessible only through the `execute-api` VPC_Endpoint
5. WHEN a network path audit is performed, THE deployment SHALL show zero routes to the public internet

### Requirement 11: Tool Functional Parity

**User Story:** As an MCP tool consumer, I want all 51 tools to work identically after deployment, so that the migration from the Dev_Bridge to the production service is transparent.

#### Acceptance Criteria

1. WHEN the MCP_Server is deployed to ECS Fargate, THE MCP_Server SHALL register all 51 tools with identical names and input schemas as the Dev_Bridge
2. WHEN any of the 51 tools is invoked through the Private_API_Gateway, THE tool SHALL return results consistent with the Dev_Bridge responses
3. IF a tool invocation fails due to a connectivity issue (Neptune timeout, OpenSearch unreachable), THEN THE MCP_Server SHALL return a structured error message identifying the failing backend
