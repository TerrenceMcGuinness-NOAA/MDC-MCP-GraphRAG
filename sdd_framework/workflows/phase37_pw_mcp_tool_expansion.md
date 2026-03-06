# Phase 37: Parallel Works MCP Server — Tool Expansion

**Version**: 1.0.0
**Status**: Planned
**Created**: 2026-03-06
**Target**: `supported_repos/parallel-works-mcp/src/index.js`
**Branch**: `adding_local_mcptools`

## Overview

Expand the Parallel Works MCP server from 19 tools to **29 tools** by adding coverage for 4 newly discovered API endpoints, enhancing 3 existing tools with filters, and creating 3 composite/derived tools. All additions follow the established handler pattern in `src/index.js`.

### Motivation

A live API survey of `noaa.parallel.works` (v7.15.1) on March 6, 2026, probed 40 endpoint patterns and discovered 4 responsive endpoints with no MCP tool coverage:

| Endpoint | Returns | Items | Value |
|----------|---------|-------|-------|
| `GET /api/resources` | Unified resource list (all clusters + rich metadata) | 23 | 39+ fields per item |
| `GET /api/ips` | Static/Elastic IP addresses | 1 | Infrastructure inventory |
| `GET /api/networks` | VPC networks across 3 clouds | 4 | Multi-cloud networking |
| `GET /api/settings` | Platform config, version, features | 1 object | Health/status |

Additionally, existing tools like `list_clusters`, `list_sessions`, and `get_groups` lack filters that would make them substantially more useful for AI-assisted workflows.

### Related Work
- **Phase 36** — PW VNC port fix upstream PR (separate)
- **Pre-phase work** — `list_snapshots` and `list_storage` already added to branch `adding_local_mcptools` (117 insertions, syntax validated, `list_snapshots` tested live)

### Architecture Constraint

The PW MCP server is a **single-file Node.js application** (`src/index.js`, currently 817 lines). It uses:
- `@modelcontextprotocol/sdk` for MCP protocol
- `axios` for HTTP calls to `https://noaa.parallel.works`
- Bearer JWT authentication via `PARALLEL_WORKS_TOKEN` env var
- `apiCall(method, path, data, params)` helper for all HTTP requests
- Tool definitions in `ListToolsRequestSchema` handler (schema array)
- Tool implementations in `CallToolRequestSchema` handler (switch/case)

Each new tool requires exactly **two code blocks**: a schema definition and a case handler.

### Server Configuration

```json
// .vscode/mcp.json — parallelworks server entry
{
  "command": "node",
  "args": ["/mcp_rag_eib/eib-mcp-rag-server/supported_repos/parallel-works-mcp/src/index.js"],
  "type": "stdio",
  "env": {
    "PARALLEL_WORKS_API_URL": "https://noaa.parallel.works",
    "PARALLEL_WORKS_TOKEN": "<JWT token>"
  }
}
```

After modifying `src/index.js`, restart the MCP server from VS Code: Command Palette → "MCP: List Servers" → parallelworks → Restart.

---

## API Reference (Discovered Endpoints)

### GET /api/resources — Unified Resource List

Returns ALL compute resources (clusters, pcluster, existing HPC connections) with rich metadata. This is a **superset** of `/api/clusters` with 39+ fields per item.

**Sample response item keys:**
```
id, name, displayName, namespace, user, organization, group, description,
tags, visibility, status, updateStatus, state, type, collapse, key, network,
mfa, imageUrl, variables, sshpid, info, permissions, controllerIp, favorite,
runTimeAlert, shared, hosts, agent, ansible, allocationThreshold,
providerVersion, attachedStorages, accessKey, multiUser, userBootstrap,
healthCheck, currentSessionNumber, agentVersion
```

**Key fields for filtering:**
- `status`: `"active"`, `"off"`, `"starting"`, `"error"`
- `type`: `"aws-slurm"`, `"google-slurm"`, `"azure-slurm"`, `"existing"`, `"pclusterv2"`
- `user` / `namespace`: owner username
- `group`: group name (e.g., `"ca-sfs-emc"`)

**Observed data (March 6, 2026):** 23 resources, including 5 Terry.McGuinness clusters (all `existing` type, status `off`).

### GET /api/ips — Static/Elastic IP Addresses

Returns provisioned static IPs across cloud providers.

**Sample response item:**
```json
{
  "id": "66ec4866c22047e54e7aa96f",
  "user": "Terry.McGuinness",
  "provisionStatus": "provisioned",
  "ip": "3.13.140.91",
  "provisioned": true,
  "name": "gitlabserver",
  "csp": "aws",
  "region": "us-east-2",
  "tags": ["gitlab"],
  "description": "IP to gitlab server running in docker on EC2 host provisioned with Rocky 8",
  "group": "",
  "network": ""
}
```

### GET /api/networks — VPC Networks

Returns virtual networks across all cloud providers.

**Sample response item:**
```json
{
  "id": "6944c4817c2683d4c3b477d7",
  "name": "google-controller-nat",
  "csp": "google",
  "organization": "5f922918b6de4f2d4da0b13d",
  "cloudAccount": "6944c47e7c2683d4c3b477d6",
  "tags": null,
  "description": "",
  "provisioned": true,
  "currentlyProvisioning": false,
  "createdAt": "2025-12-19T03:20:33.97Z",
  "regions": ["us-central1", "us-east4", "us-west2", "us-west1", "us-west3", "us-west4", "us-east1"],
  "transitGatewayId": "",
  "provisioningMode": "controller-nat",
  "dnszoneName": "",
  "cspId": "4094306968295294014",
  "networkName": "default"
}
```

**Observed data:** 4 networks (Google controller-nat, AWS, Azure, and one more).

### GET /api/settings — Platform Settings

Returns platform configuration (no auth required beyond token).

**Response keys:**
```
statusUrl, features, version, maintenanceMode, maintenanceMessage,
singleOrgPlatform, singleOrgName, availableAuthMethods, enforceMaxTTL,
orgTheme, legacyTheme, topBannerMessage, forgotPasswordEnabled,
platformName, theme, terminalTheme, terminalFontSize
```

**Observed values:** Platform v7.15.1, "RDHPCS Hybrid Cloud", not in maintenance mode, single-org "noaademo".

### GET /api/groups — Group Budget Data (Enhancement)

Already covered by `get_groups` tool but the response includes rich allocation data NOT exposed by the current tool. Each group returns:
```json
{
  "allocations": {
    "total": 3525,
    "used": 2328.87,
    "estimatedUsed": 2328.87
  },
  "members": 22
}
```

**Observed data (8 groups):**
| Group | Members | Budget | Used | Remaining |
|-------|---------|--------|------|-----------|
| ca-sfs-emc | 22 | $3,525 | $2,329 | $1,196 |
| ca-ufs-cpldcld | 17 | $939,912 | $87,319 | $852,593 |
| cg-ufs-cpldcld | 19 | $150 | $150 | $0 |
| cz-ufs-cpldcld | 14 | $1,825 | $1,825 | $0 |
| (4 others) | — | $0 | $0 | $0 |

### Confirmed 404 Endpoints (NOT available)

These were probed and confirmed to NOT exist on this platform version:
`/api/runs`, `/api/instances`, `/api/disks`, `/api/cost`, `/api/reports`, `/api/jobs`, `/api/marketplace`, `/api/terminals`, `/api/images`, `/api/pools`, `/api/accounts`, `/api/cspaccounts`, `/api/tags`, `/api/users`, `/api/monitor`, `/api/events`, `/api/audit`, `/api/billing`, `/api/explorer`, `/api/keys`, `/api/sshkeys`, `/api/vnc`, `/api/datasets`, `/api/volumes`, `/api/logs`, `/api/metrics`, `/api/usage`, `/api/quotas`, `/api/preferences`

### Admin-Only Endpoints (403 for non-admin users)

| Endpoint | Error |
|----------|-------|
| `/api/organizations/noaademo/users` | Requires `org:users` or `platform:admin` |
| `/api/organizations/noaademo/cloud-accounts` | Requires `org:admin` or `platform:admin` |
| `/api/organizations/noaademo/allocations` | Requires `org:admin` or `platform:admin` |

---

## Tool Specifications

### Phase 37A: New Endpoint Tools (4 tools)

#### Tool 20: `list_resources`
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js`

Calls `GET /api/resources`. Returns unified list of all compute resources with rich metadata. Derive `createdAt` from MongoDB ObjectID (same pattern as `list_snapshots`/`list_storage`).

**Schema:**
```javascript
{
  name: 'list_resources',
  description: 'List all compute resources (clusters, pcluster, existing HPC) with rich metadata including status, attached storage, health checks, and provider config. Superset of list_clusters.',
  inputSchema: {
    type: 'object',
    properties: {
      status: {
        type: 'string',
        description: 'Filter by resource status',
        enum: ['active', 'off', 'starting', 'error'],
      },
      type: {
        type: 'string',
        description: 'Filter by resource type',
        enum: ['aws-slurm', 'google-slurm', 'azure-slurm', 'existing', 'pclusterv2'],
      },
      user: {
        type: 'string',
        description: 'Filter by owner username (namespace)',
      },
      group: {
        type: 'string',
        description: 'Filter by group name (e.g. ca-sfs-emc)',
      },
    },
  },
}
```

**Handler:**
```javascript
case 'list_resources': {
  const result = await apiCall('GET', '/api/resources');
  if (result.success && Array.isArray(result.data)) {
    result.data = result.data.map(item => {
      if (item.id && item.id.length >= 8) {
        const ts = parseInt(item.id.substring(0, 8), 16);
        item.createdAt = new Date(ts * 1000).toISOString();
      }
      return item;
    });
    if (args.status) {
      result.data = result.data.filter(r => r.status === args.status);
    }
    if (args.type) {
      result.data = result.data.filter(r => r.type === args.type);
    }
    if (args.user) {
      result.data = result.data.filter(r => r.namespace === args.user || r.user === args.user);
    }
    if (args.group) {
      result.data = result.data.filter(r => r.group === args.group);
    }
  }
  return {
    content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
  };
}
```

---

#### Tool 21: `list_ips`
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js`

Calls `GET /api/ips`. Returns static/elastic IP addresses.

**Schema:**
```javascript
{
  name: 'list_ips',
  description: 'List static/elastic IP addresses provisioned across cloud providers.',
  inputSchema: {
    type: 'object',
    properties: {
      csp: {
        type: 'string',
        description: 'Filter by cloud provider',
        enum: ['aws', 'google', 'azure'],
      },
      provisioned: {
        type: 'boolean',
        description: 'Filter by provisioned status',
      },
      user: {
        type: 'string',
        description: 'Filter by owner username',
      },
    },
  },
}
```

**Handler:**
```javascript
case 'list_ips': {
  const result = await apiCall('GET', '/api/ips');
  if (result.success && Array.isArray(result.data)) {
    if (args.csp) {
      result.data = result.data.filter(ip => ip.csp === args.csp);
    }
    if (args.provisioned !== undefined) {
      result.data = result.data.filter(ip => ip.provisioned === args.provisioned);
    }
    if (args.user) {
      result.data = result.data.filter(ip => ip.user === args.user);
    }
  }
  return {
    content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
  };
}
```

---

#### Tool 22: `list_networks`
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js`

Calls `GET /api/networks`. Returns VPC networks across cloud providers.

**Schema:**
```javascript
{
  name: 'list_networks',
  description: 'List VPC networks across cloud providers. Shows regions, provisioning mode, transit gateways, and DNS zones.',
  inputSchema: {
    type: 'object',
    properties: {
      csp: {
        type: 'string',
        description: 'Filter by cloud provider',
        enum: ['aws', 'google', 'azure'],
      },
      provisioned: {
        type: 'boolean',
        description: 'Filter by provisioned status',
      },
    },
  },
}
```

**Handler:**
```javascript
case 'list_networks': {
  const result = await apiCall('GET', '/api/networks');
  if (result.success && Array.isArray(result.data)) {
    if (args.csp) {
      result.data = result.data.filter(n => n.csp === args.csp);
    }
    if (args.provisioned !== undefined) {
      result.data = result.data.filter(n => n.provisioned === args.provisioned);
    }
  }
  return {
    content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
  };
}
```

---

#### Tool 23: `get_platform_settings`
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js`

Calls `GET /api/settings`. Returns platform configuration, version, and maintenance status.

**Schema:**
```javascript
{
  name: 'get_platform_settings',
  description: 'Get platform configuration including version, maintenance mode, enabled features, org theme, and authentication methods.',
  inputSchema: {
    type: 'object',
    properties: {},
  },
}
```

**Handler:**
```javascript
case 'get_platform_settings': {
  const result = await apiCall('GET', '/api/settings');
  return {
    content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
  };
}
```

---

### Phase 37B: Enhanced Existing Tools (3 enhancements)

#### Enhancement 1: `list_clusters` — Add Filters
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js` (schema ~line 136, handler ~line 500)

Add `status`, `type`, and `user` filters to the existing `list_clusters` tool. Currently returns raw unfiltered array.

**Updated schema (replace existing):**
```javascript
{
  name: 'list_clusters',
  description: 'List all clusters the user can access. Optionally filter by status, type, or owner.',
  inputSchema: {
    type: 'object',
    properties: {
      status: {
        type: 'string',
        description: 'Filter by cluster status',
        enum: ['active', 'off', 'starting', 'error'],
      },
      type: {
        type: 'string',
        description: 'Filter by cluster type',
        enum: ['aws-slurm', 'google-slurm', 'azure-slurm', 'existing', 'pclusterv2'],
      },
      user: {
        type: 'string',
        description: 'Filter by owner username',
      },
    },
  },
}
```

**Updated handler (replace existing):**
```javascript
case 'list_clusters': {
  const result = await apiCall('GET', '/api/clusters');
  if (result.success && Array.isArray(result.data)) {
    if (args.status) {
      result.data = result.data.filter(c => c.status === args.status);
    }
    if (args.type) {
      result.data = result.data.filter(c => c.type === args.type);
    }
    if (args.user) {
      result.data = result.data.filter(c => c.namespace === args.user || c.user === args.user);
    }
  }
  return {
    content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
  };
}
```

---

#### Enhancement 2: `list_sessions` — Add Status Filter
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js` (schema ~line 342, handler ~line 680)

Add `status` filter (running/stopped) to the existing tool.

**Updated schema (replace existing):**
```javascript
{
  name: 'list_sessions',
  description: 'List sessions for the authenticated user. Filter by type, status, or subdomain.',
  inputSchema: {
    type: 'object',
    properties: {
      type: {
        type: 'string',
        description: 'Filter by session type (tunnel, link)',
        enum: ['tunnel', 'link'],
      },
      status: {
        type: 'string',
        description: 'Filter by session status (running, stopped)',
        enum: ['running', 'stopped'],
      },
      subdomain: {
        type: 'string',
        description: 'Filter by subdomain/domain name',
      },
    },
  },
}
```

**Updated handler (replace existing):**
```javascript
case 'list_sessions': {
  const params = {};
  if (args.type) params.type = args.type;
  if (args.subdomain) params.subdomain = args.subdomain;

  const result = await apiCall('GET', '/api/sessions', null, params);
  if (result.success && Array.isArray(result.data) && args.status) {
    result.data = result.data.filter(s => s.status === args.status);
  }
  return {
    content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
  };
}
```

---

#### Enhancement 3: `get_groups` — Surface Allocation Budget Data
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js` (schema ~line 116, handler ~line 486)

Add `include_budgets` option that returns a budget summary when set. The allocation data is already in the response but gets lost in the noise of a large JSON array.

**Updated schema (replace existing):**
```javascript
{
  name: 'get_groups',
  description: 'Get groups for the authenticated user. Includes allocation budgets (total, used, remaining) per group.',
  inputSchema: {
    type: 'object',
    properties: {
      provider: {
        type: 'string',
        description: 'Filter by provider (aws-slurm, google-slurm, azure-slurm, existing)',
        enum: ['aws-slurm', 'google-slurm', 'azure-slurm', 'existing'],
      },
      network: {
        type: 'string',
        description: 'Filter by network name',
      },
      budget_summary: {
        type: 'boolean',
        description: 'When true, append a budget summary table showing total/used/remaining per group',
      },
    },
  },
}
```

**Updated handler (replace existing):**
```javascript
case 'get_groups': {
  const params = {};
  if (args.provider) params.provider = args.provider;
  if (args.network) params.network = args.network;

  const result = await apiCall('GET', '/api/groups', null, params);
  let text = JSON.stringify(result, null, 2);

  if (args.budget_summary && result.success && Array.isArray(result.data)) {
    const lines = ['', '--- Budget Summary ---', 'Group | Members | Total | Used | Remaining'];
    let grandTotal = 0, grandUsed = 0;
    for (const g of result.data) {
      const a = g.allocations || {};
      const total = a.total || 0;
      const used = a.used || 0;
      const remaining = (total - used).toFixed(2);
      grandTotal += total;
      grandUsed += used;
      lines.push(`${g.name} | ${g.members} | $${total} | $${used.toFixed(2)} | $${remaining}`);
    }
    lines.push(`TOTAL | — | $${grandTotal} | $${grandUsed.toFixed(2)} | $${(grandTotal - grandUsed).toFixed(2)}`);
    text += '\n' + lines.join('\n');
  }

  return {
    content: [{ type: 'text', text }],
  };
}
```

---

### Phase 37C: Composite/Derived Tools (3 tools)

#### Tool 24: `get_resource_detail`
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js`

Single resource deep-dive by name. Calls `/api/resources` and filters client-side. Returns full metadata including attached storages, provider config variables, health check status, and agent version.

**Schema:**
```javascript
{
  name: 'get_resource_detail',
  description: 'Get detailed information about a specific compute resource by name. Returns attached storages, provider config, health check status, agent version, and full metadata.',
  inputSchema: {
    type: 'object',
    properties: {
      name: {
        type: 'string',
        description: 'Resource name (e.g. emcmcpawsrocky9functionalii, noaaheracluster)',
      },
    },
    required: ['name'],
  },
}
```

**Handler:**
```javascript
case 'get_resource_detail': {
  const result = await apiCall('GET', '/api/resources');
  if (result.success && Array.isArray(result.data)) {
    const match = result.data.find(
      r => r.name === args.name || r.displayName === args.name
    );
    if (match) {
      if (match.id && match.id.length >= 8) {
        const ts = parseInt(match.id.substring(0, 8), 16);
        match.createdAt = new Date(ts * 1000).toISOString();
      }
      result.data = match;
    } else {
      return {
        content: [{
          type: 'text',
          text: JSON.stringify({
            success: false,
            error: `Resource '${args.name}' not found. Use list_resources to see available resources.`,
            available: result.data.map(r => r.name),
          }, null, 2),
        }],
      };
    }
  }
  return {
    content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
  };
}
```

---

#### Tool 25: `get_cluster_status`
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js`

Quick status check for a specific cluster. Returns a concise summary: name, status, IP, type, health, sessions.

**Schema:**
```javascript
{
  name: 'get_cluster_status',
  description: 'Quick status check for a specific cluster. Returns name, status, controllerIp, type, health check, active sessions, and attached storages.',
  inputSchema: {
    type: 'object',
    properties: {
      name: {
        type: 'string',
        description: 'Cluster name',
      },
    },
    required: ['name'],
  },
}
```

**Handler:**
```javascript
case 'get_cluster_status': {
  const result = await apiCall('GET', '/api/resources');
  if (result.success && Array.isArray(result.data)) {
    const match = result.data.find(
      r => r.name === args.name || r.displayName === args.name
    );
    if (match) {
      result.data = {
        name: match.name,
        displayName: match.displayName,
        status: match.status,
        type: match.type,
        controllerIp: match.controllerIp || '(none)',
        user: match.namespace,
        group: match.group,
        healthCheck: match.healthCheck || false,
        agentVersion: match.agentVersion || 'unknown',
        activeSessions: match.currentSessionNumber || 0,
        attachedStorages: match.attachedStorages || [],
        shared: match.shared || false,
      };
    } else {
      return {
        content: [{
          type: 'text',
          text: JSON.stringify({
            success: false,
            error: `Cluster '${args.name}' not found.`,
            available: result.data.map(r => ({ name: r.name, status: r.status })),
          }, null, 2),
        }],
      };
    }
  }
  return {
    content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
  };
}
```

---

#### Tool 26: `get_cost_summary`
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js`

Aggregate budget/cost summary across all groups. Derives from `/api/groups` allocation data.

**Schema:**
```javascript
{
  name: 'get_cost_summary',
  description: 'Get budget/cost summary across all groups. Shows total budget, used, remaining, and per-group breakdown from allocation data.',
  inputSchema: {
    type: 'object',
    properties: {},
  },
}
```

**Handler:**
```javascript
case 'get_cost_summary': {
  const result = await apiCall('GET', '/api/groups');
  if (result.success && Array.isArray(result.data)) {
    let grandTotal = 0, grandUsed = 0;
    const groups = result.data.map(g => {
      const a = g.allocations || {};
      const total = a.total || 0;
      const used = a.used || 0;
      grandTotal += total;
      grandUsed += used;
      return {
        name: g.name,
        members: g.members,
        budget: total,
        used: parseFloat(used.toFixed(2)),
        remaining: parseFloat((total - used).toFixed(2)),
        percentUsed: total > 0 ? parseFloat(((used / total) * 100).toFixed(1)) : 0,
      };
    });
    result.data = {
      summary: {
        totalBudget: grandTotal,
        totalUsed: parseFloat(grandUsed.toFixed(2)),
        totalRemaining: parseFloat((grandTotal - grandUsed).toFixed(2)),
        percentUsed: grandTotal > 0 ? parseFloat(((grandUsed / grandTotal) * 100).toFixed(1)) : 0,
        groupCount: groups.length,
      },
      groups: groups.sort((a, b) => b.budget - a.budget),
    };
  }
  return {
    content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
  };
}
```

---

## Execution Steps

### Step 1: Add Phase 37A tool schemas
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js` (ListToolsRequestSchema handler)

Insert 4 new tool schemas (list_resources, list_ips, list_networks, get_platform_settings) into the tools array alongside the existing storage/snapshot tools.

### Step 2: Add Phase 37A tool handlers
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js` (CallToolRequestSchema handler)

Insert 4 new case handlers matching the schemas from Step 1.

### Step 3: Enhance list_clusters schema and handler
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js` (schema ~line 136, handler ~line 500)

Replace existing `list_clusters` schema with version that includes `status`, `type`, `user` filters. Update handler to apply client-side filtering.

### Step 4: Enhance list_sessions schema and handler
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js` (schema ~line 342, handler ~line 680)

Add `status` filter (running/stopped) to schema and handler.

### Step 5: Enhance get_groups schema and handler
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js` (schema ~line 116, handler ~line 486)

Add `budget_summary` boolean option. When true, append a pipe-delimited budget summary table to the JSON output.

### Step 6: Add Phase 37C composite tool schemas
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js` (ListToolsRequestSchema handler)

Insert 3 composite tool schemas (get_resource_detail, get_cluster_status, get_cost_summary).

### Step 7: Add Phase 37C composite tool handlers
**Tag**: implement
**Target**: `supported_repos/parallel-works-mcp/src/index.js` (CallToolRequestSchema handler)

Insert 3 composite case handlers.

### Step 8: Validate syntax
**Tag**: validate
**Target**: `supported_repos/parallel-works-mcp/src/index.js`

```bash
cd supported_repos/parallel-works-mcp && node -c src/index.js && echo "[OK] Syntax valid"
```

### Step 9: Restart MCP server and verify tool count
**Tag**: validate

Restart the parallelworks MCP server from VS Code. Verify 29 tools are listed. Call `get_auth_session` to confirm the server is responsive.

### Step 10: Test list_resources
**Tag**: validate

Call `list_resources` with no filters — expect 23 items. Then test with `status: "off"` and `user: "Terry.McGuinness"` filters.

### Step 11: Test list_ips
**Tag**: validate

Call `list_ips` — expect 1 item (gitlabserver, 3.13.140.91, aws, us-east-2).

### Step 12: Test list_networks
**Tag**: validate

Call `list_networks` — expect 4 items. Test `csp: "aws"` filter.

### Step 13: Test get_platform_settings
**Tag**: validate

Call `get_platform_settings` — expect version v7.15.1, platformName "RDHPCS Hybrid Cloud", maintenanceMode false.

### Step 14: Test enhanced list_clusters with filters
**Tag**: validate

Call `list_clusters` with `status: "active"` — compare count to unfiltered. Call with `user: "Terry.McGuinness"` — expect 2 clusters.

### Step 15: Test enhanced list_sessions with status filter
**Tag**: validate

Call `list_sessions` with `status: "running"` — expect at least the active Desktop session.

### Step 16: Test get_groups with budget_summary
**Tag**: validate

Call `get_groups` with `budget_summary: true` — verify the pipe-delimited budget table appears appended to the JSON, with correct totals.

### Step 17: Test get_resource_detail
**Tag**: validate

Call `get_resource_detail` with `name: "noaaheracluster"` — expect full metadata for Terry's Hera cluster. Call with a bogus name — expect error with available names list.

### Step 18: Test get_cluster_status
**Tag**: validate

Call `get_cluster_status` with `name: "noaaheracluster"` — expect concise status summary. Test with an active cluster name if one exists.

### Step 19: Test get_cost_summary
**Tag**: validate

Call `get_cost_summary` — expect summary with grandTotal ~$945,412, broken down by 8 groups sorted by budget descending. Verify percentUsed calculations.

### Step 20: Test list_storage (from pre-phase work)
**Tag**: validate

Call `list_storage` with no args — expect 33 items. Test `type: "aws-disk"` filter — expect 1 item (emceibmcpgraphragpersistenttwo). This validates the pre-phase work that was syntax-checked but not live-tested.

### Step 21: Git diff and commit
**Tag**: validate

```bash
cd supported_repos/parallel-works-mcp
git diff --stat
git add src/index.js
git commit -m "Phase 37: Expand PW MCP tools from 19 to 29 (4 new endpoints + 3 enhancements + 3 composite)"
```

### Step 22: Update README.md with new tools
**Tag**: document
**Target**: `supported_repos/parallel-works-mcp/README.md`

Add documentation for all 10 new/enhanced tools to the README, following the existing format with example JSON payloads.

### Step 23: Update CHANGELOG.md
**Tag**: document
**Target**: `CHANGELOG.md`

Add Phase 37 entry with version bump, listing all new tools and enhancements.

---

## Success Criteria

- [ ] `node -c src/index.js` passes (syntax valid)
- [ ] MCP server restarts and lists 29 tools
- [ ] All 4 new endpoint tools return expected data
- [ ] All 3 enhanced tools accept and correctly apply new filters
- [ ] All 3 composite tools return properly formatted derived data
- [ ] `list_storage` (pre-phase) confirmed working via live test
- [ ] Git commit on branch `adding_local_mcptools`
- [ ] README.md updated with all new tools
- [ ] CHANGELOG.md updated

## Tool Count Progression

| Phase | Tools | Delta | Description |
|-------|-------|-------|-------------|
| Baseline | 17 | — | Original PW MCP server |
| Pre-37 | 19 | +2 | `list_snapshots`, `list_storage` |
| 37A | 23 | +4 | `list_resources`, `list_ips`, `list_networks`, `get_platform_settings` |
| 37B | 23 | +0 | Enhanced `list_clusters`, `list_sessions`, `get_groups` (filter upgrades) |
| 37C | 26 | +3 | `get_resource_detail`, `get_cluster_status`, `get_cost_summary` |
| **Total** | **26** | **+7** | Plus 3 enhanced existing tools = 10 changes |

> **Note**: Final tool count is 26 (not 29) because Phase 37B enhances existing tools rather than adding new ones. The server will report 26 tools total after all phases.
