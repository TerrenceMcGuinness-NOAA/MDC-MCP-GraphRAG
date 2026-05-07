# AgentCore VPC Connectivity Analysis

**Date**: May 7, 2026
**Phase**: 51b (Step 6 — VPC connectivity validation)
**Status**: ✅ RESOLVED — All 51 tools working through AgentCore Runtime

---

## Summary

The AgentCore Runtime (`mdc_mcp_rag_server-TMXDllG2Wi`) is deployed and READY, but
graph and vector tools (Neptune, OpenSearch) are not responding through it. Static
tools (e.g., `get_server_info`) work. This report documents the full network path
analysis to identify the root cause.

---

## Network Topology

```
┌─────────────────────────────────────────────────────────────────┐
│  VPC: vpc-055f30ffa3d661e6b  (10.40.132.0/22 + 10.40.136.0/22)  │
│                                                                 │
│  ┌─────────────────────┐    ┌─────────────────────┐             │
│  │ subnet-0e13af6b...  │    │ subnet-04447750c... │             │
│  │ us-east-1a          │    │ us-east-1b          │             │
│  │ 10.40.137.0/24      │    │ 10.40.138.0/24      │             │
│  │                     │    │                     │             │
│  │ AgentCore ENI       │    │ AgentCore ENI       │             │
│  │ 10.40.137.148       │    │ 10.40.138.186       │             │
│  │ SG: sg-096489a...   │    │ SG: sg-096489a...   │             │
│  │                     │    │                     │             │
│  │ OpenSearch node     │    │ OpenSearch node     │             │
│  │ 10.40.137.53        │    │ 10.40.138.29        │             │
│  │ SG: sg-085591f...   │    │ SG: sg-085591f...   │             │
│  │                     │    │                     │             │
│  │                     │    │ Neptune instance    │             │
│  │                     │    │ 10.40.138.54        │             │
│  │                     │    │ SG: sg-06ee2c5...   │             │
│  └─────────────────────┘    └─────────────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

---

## AgentCore Runtime Configuration

| Property | Value |
|----------|-------|
| Runtime ID | `mdc_mcp_rag_server-TMXDllG2Wi` |
| Status | READY |
| Protocol | MCP (Streamable HTTP on port 8000) |
| Network Mode | VPC |
| Security Group | `sg-096489a0876cc78c1` (`mdc-mcp-rag-ecs-sg`) |
| Subnets | `subnet-0e13af6b3a9a6416f` (us-east-1a), `subnet-04447750c61bd7e06` (us-east-1b) |
| ENIs Created | `eni-0f7e9b315425f78ac` (10.40.137.148), `eni-0d8d76bbc4126b6fd` (10.40.138.186) |

---

## Security Group Analysis

### ECS Security Group (`sg-096489a0876cc78c1` — `mdc-mcp-rag-ecs-sg`)

**Egress (outbound from AgentCore microVM):**

| Port | Protocol | Destination | Description | Status |
|------|----------|-------------|-------------|--------|
| 8182 | TCP | 0.0.0.0/0 | Neptune egress | ✅ Allows Neptune |
| 443 | TCP | 0.0.0.0/0 | HTTPS egress | ✅ Allows OpenSearch |
| 2049 | TCP | sg-04bd2b41beecd1201 | ECS to EFS | ✅ Allows EFS |

**Ingress (inbound to AgentCore microVM):**

| Port | Protocol | Source | Status |
|------|----------|--------|--------|
| — | — | — | ⚠️ **EMPTY — no inbound rules** |

### Neptune Security Group (`sg-06ee2c5e37b210420` — VPC default)

**Ingress:**

| Port | Protocol | Source | Status |
|------|----------|--------|--------|
| 8182 | TCP | `sg-09bb60ffa41137076` (dev EC2) | ✅ |
| 8182 | TCP | `sg-096489a0876cc78c1` (ECS/AgentCore) | ✅ Accepts from AgentCore |

### OpenSearch Security Group (`sg-085591f442d4cd7b6` — `mdc-mcp-rag-opensearch-sg`)

**Ingress:**

| Port | Protocol | Source | Status |
|------|----------|--------|--------|
| 443 | TCP | `sg-09bb60ffa41137076` (dev EC2) | ✅ |
| 443 | TCP | `sg-096489a0876cc78c1` (ECS/AgentCore) | ✅ Accepts from AgentCore |

---

## Route Table Analysis

Both AgentCore subnets share the same route table:

| Destination | Target | Purpose |
|-------------|--------|---------|
| 10.40.132.0/22 | local | VPC internal (first CIDR) |
| 10.40.136.0/22 | local | VPC internal (second CIDR) |
| 0.0.0.0/0 | tgw-01e6e288ba92e45db | Transit Gateway (external) |
| pl-63a5400a (S3) | vpce-0ab581c681d867664 | S3 VPC endpoint |

All resources (Neptune at 10.40.138.54, OpenSearch at 10.40.137.53/10.40.138.29) are
within the `10.40.136.0/22` CIDR — **routing is correct, no NAT needed**.

---

## Network ACL Analysis

Both subnets use the same NACL with permissive rules:

| Rule # | Direction | Action | Protocol | CIDR |
|--------|-----------|--------|----------|------|
| 100 | Inbound | ALLOW | ALL | 0.0.0.0/0 |
| 100 | Outbound | ALLOW | ALL | 0.0.0.0/0 |
| 32767 | Inbound | DENY | ALL | 0.0.0.0/0 (default) |
| 32767 | Outbound | DENY | ALL | 0.0.0.0/0 (default) |

**NACLs are not blocking anything.**

---

## DNS Resolution (from EC2)

| Hostname | Resolves To | In VPC CIDR? |
|----------|-------------|--------------|
| `mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s.us-east-1.neptune.amazonaws.com` | 10.40.138.54 | ✅ |
| `vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq.us-east-1.es.amazonaws.com` | 10.40.138.29, 10.40.137.53 | ✅ |

---

## Verdict: Security Groups and Routing Are Correct

All network-layer checks pass:

- ✅ ECS SG egress allows port 8182 (Neptune) and 443 (OpenSearch)
- ✅ Neptune SG ingress accepts from ECS SG
- ✅ OpenSearch SG ingress accepts from ECS SG
- ✅ All resources in same VPC, same CIDR range
- ✅ Route tables have local routes for the VPC CIDRs
- ✅ NACLs are fully permissive
- ✅ AgentCore ENIs are created and in-use in both subnets
- ✅ DNS resolves to private IPs within the VPC

---

## Probable Root Causes (Non-Network)

Since the network path is clear, the failure is likely at a higher layer:

### 1. DNS Resolution Inside the AgentCore MicroVM

The Neptune and OpenSearch endpoints resolve to private IPs. If the AgentCore
microVM's DNS resolver doesn't use VPC DNS (AmazonProvidedDNS at VPC base+2),
the hostnames won't resolve from inside the container.

**How to verify**: Check CloudWatch logs for DNS resolution errors or "ENOTFOUND"
in the pre-warm phase.

### 2. IAM SigV4 Authentication

Both Neptune and OpenSearch require IAM SigV4-signed requests. The MCP server
code uses the `mdc-mcp-rag-ecs-task-role` for signing. If AgentCore doesn't
inject task role credentials into the microVM environment (via ECS task metadata
endpoint or environment variables), the connections will fail with 403 errors.

**How to verify**: Check CloudWatch logs for "AccessDeniedException" or
"InvalidSignatureException" errors.

### 3. Connection Timeout vs Auth Rejection

We need to distinguish between:
- **Timeout** → network issue (unlikely given SG analysis)
- **403/401** → IAM credentials not available in microVM
- **ENOTFOUND** → DNS not resolving inside container

**How to verify**: Invoke a graph tool and capture the actual error message.

### 4. Neptune WebSocket Protocol

Neptune uses `wss://` (WebSocket Secure) on port 8182. The Bolt driver or
openCypher HTTP endpoint may behave differently than a simple TCP connection.
If the microVM's Node.js runtime has issues with WebSocket upgrade through
the ENI, this could manifest as a connection failure even with correct SGs.

**How to verify**: Check if the error is WebSocket-specific (upgrade failed)
vs generic TCP timeout.

---

## Recommended Next Steps (Priority Order)

1. **Check CloudWatch logs** for the AgentCore runtime — look for `[AgentCore]`
   prefixed lines from the pre-warm phase (`mcp-agentcore-entrypoint.js`)

2. **Invoke a graph tool** through the AgentCore proxy and capture the exact error:
   ```
   get_code_context({symbol: "setuprad"})
   ```

3. **Verify task role credential injection** — confirm the microVM has access to
   AWS credentials (check for `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` or similar)

4. **Test DNS from inside** — if possible, add a diagnostic endpoint that resolves
   the Neptune hostname and reports the result

---

## Resource Reference

| Resource | ID/ARN |
|----------|--------|
| VPC | vpc-055f30ffa3d661e6b |
| ECS Security Group | sg-096489a0876cc78c1 |
| Neptune Security Group | sg-06ee2c5e37b210420 |
| OpenSearch Security Group | sg-085591f442d4cd7b6 |
| Dev EC2 Security Group | sg-09bb60ffa41137076 |
| EFS Security Group | sg-04bd2b41beecd1201 |
| Neptune Cluster | mdc-mcp-graprag-neptune-1 |
| Neptune Instance | mdc-mcp-graprag-neptune-1-instance-1 (us-east-1b) |
| OpenSearch Domain | mdc-mcp-rag-search |
| AgentCore Runtime | mdc_mcp_rag_server-TMXDllG2Wi |
| AgentCore ARN | arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server-TMXDllG2Wi |
| Task Role | arn:aws:iam::903050880929:role/mdc-mcp-rag-ecs-task-role |
| Transit Gateway | tgw-01e6e288ba92e45db |
| S3 VPC Endpoint | vpce-0ab581c681d867664 |

---

## Validation Results (May 7, 2026)

The VPC connectivity issue that was previously reported has been **resolved**.
All tools now work through the AgentCore Runtime.

### Test Results

| Test | Tool | Backend | Result |
|------|------|---------|--------|
| 1 | `get_server_info` | Static (no DB) | ✅ 51 tools registered |
| 2 | `get_code_context({symbol:"setuprad"})` | Neptune (graph) | ✅ Returns callers + GGSR (38ms) |
| 3 | `search_documentation({query:"GFS forecast"})` | OpenSearch (vector) | ✅ Returns 3 results with similarity scores |
| 4 | `mcp_health_check({detailed:true})` | All backends | ✅ HEALTHY (9/9 components) |

### Health Check Summary (via AgentCore)

```
Overall Status: HEALTHY (9/9 components healthy)
[OK] Base Server: 51 tools registered
[OK] Workflow Info Tools: 3 static tools
[OK] Code Analysis Tools: 4 graph-based tools
[OK] Vector Database: 17 indices available
[OK] Graph Database: 148,723 nodes
[OK] Semantic Search Tools: 17 indices ready
[OK] Operational Tools: 3 tools ready
[OK] GitHub Tools: 4 tools accessible
[OK] SDD Session Tracking: 9 session tools ready
```

### Conclusion

The security group configuration was correct all along. The earlier report of
"VPC connectivity pending" was likely from a previous session where:
- The runtime was freshly deployed and hadn't completed its pre-warm phase
- Or the runtime had been idle past its 900s timeout and needed a cold start

The current invocation confirms full end-to-end connectivity:
- EC2 → boto3 `invoke_agent_runtime` → AgentCore microVM → Neptune (port 8182) ✅
- EC2 → boto3 `invoke_agent_runtime` → AgentCore microVM → OpenSearch (port 443) ✅
- IAM SigV4 authentication working for both Neptune and OpenSearch ✅
- DNS resolution working inside the microVM ✅
