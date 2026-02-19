# Phase 26: Docker MCP Gateway Systemd Service Fix

**Description**: Diagnose and fix the Docker MCP Gateway systemd service failure (exit code 216/GROUP) and restore HTTP gateway functionality for multi-client MCP access.

**Rationale**: The `mcp-gateway.service` is failing on startup with `status=216/GROUP` due to systemd group configuration mismatch. This prevents the gateway from providing HTTP transport for AI clients (VS Code, n8n, Claude Desktop) to access MCP tools.

**Created**: January 27, 2026  
**Completed**: January 27, 2026  
**Status**: ✅ COMPLETE  
**Priority**: High  
**Actual Effort**: 30 minutes

---

## Problem Analysis

### Failure Symptoms

```
● mcp-gateway.service - Docker MCP Gateway (Dynamic Tools + Full Catalog Search)
     Active: activating (auto-restart) (Result: exit-code)
    Process: ExecStart=... (code=exited, status=216/GROUP)
```

### Root Causes Found

**Issue 1: Non-existent Group**
The systemd service file specifies:
```ini
User=Terry.McGuinness
Group=Terry.McGuinness  # ← This group does NOT exist
```

But the actual user configuration is:
```
uid=25007(Terry.McGuinness) gid=9001(pwuser) groups=9001(pwuser),233(docker),235(kasmvnc-cert),9002(pwsudo)
```

**Exit code 216** = systemd couldn't find the specified group.

**Issue 2: Docker Desktop Secrets Dependency**
After fixing the group, a second error appeared:
```
reading secrets exit status 1: Error: open /.s0: file does not exist
```

The `--additional-catalog docker-mcp.yaml` and `--enable-all-servers` flags were causing the gateway to load the official Docker MCP catalog which requires Docker Desktop's secrets store (`/.s0` socket) - unavailable on headless Linux.

### Secondary Issues to Verify

1. Gateway can start manually with correct permissions
2. Port 18888 is available and not blocked
3. Bearer token authentication works
4. Tool discovery completes (35 tools expected)

---

## Architecture Reference

```
┌────────────────────────────────────────────────────────────────┐
│                     AI Clients                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │   n8n    │  │ VS Code  │  │  Claude  │  │  Cursor  │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│       └─────────────┴──────┬──────┴─────────────┘              │
│                            │ HTTP POST /mcp                    │
│                   ┌────────▼────────┐                          │
│                   │  Docker MCP     │ Port 18888               │
│                   │    Gateway      │ Bearer Auth              │
│                   └────────┬────────┘                          │
│                            │ stdio spawn                       │
│                   ┌────────▼────────┐                          │
│                   │ eib-mcp-rag     │                          │
│                   │ Container       │                          │
│                   │ (35 tools)      │                          │
│                   └────────┬────────┘                          │
│                            │                                   │
│           ┌────────────────┼────────────────┐                  │
│           ▼                ▼                ▼                  │
│      ChromaDB          Neo4j          Filesystem               │
│     (8080)            (7687)        (supported_repos)          │
└────────────────────────────────────────────────────────────────┘
```

---

## Phase 26A: Fix Systemd Service Configuration

### Step 1: Update Service File Group
**Type**: file_modification  
**Target**: `/etc/systemd/system/mcp-gateway.service`  
**Description**: Change Group from non-existent `Terry.McGuinness` to actual group `pwuser`

```diff
[Service]
Type=simple
User=Terry.McGuinness
-Group=Terry.McGuinness
+Group=pwuser
Environment=HOME=/home/Terry.McGuinness
```

**Command**:
```bash
sudo sed -i 's/^Group=Terry\.McGuinness$/Group=pwuser/' /etc/systemd/system/mcp-gateway.service
```

### Step 2: Reload Systemd and Restart Service
**Type**: command_execution  
**Description**: Apply the configuration change

```bash
sudo systemctl daemon-reload
sudo systemctl restart mcp-gateway
sudo systemctl status mcp-gateway
```

### Step 3: Verify Gateway Startup
**Type**: validation  
**Description**: Confirm the gateway is running and accepting connections

```bash
# Check port is listening
ss -tlnp | grep 18888

# Test endpoint with bearer auth
curl -s -X POST http://localhost:18888/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eib-mcp-gateway-token-2025" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

**Expected**: 35 tools listed in response

---

## Phase 26B: Update Provisioning Template (SPOT Compliance)

### Step 4: Update Service Template
**Type**: file_modification  
**Target**: `SETUP/systemd/mcp-gateway.service.template`  
**Description**: Fix the template to use dynamic group detection or safe default

The template should be updated to either:
1. Use the user's primary group dynamically
2. Use a common group like `docker` that gateway users must be in
3. Omit Group= and let systemd use the user's default group

**Recommended approach** - Omit Group= line (systemd defaults to user's primary group):

```ini
[Service]
Type=simple
User=Terry.McGuinness
# Group omitted - systemd uses user's primary group automatically
Environment=HOME=/home/Terry.McGuinness
```

### Step 5: Update Provisioning Script
**Type**: file_modification  
**Target**: `SETUP/provisioning/12-static-mode-gateway.sh`  
**Description**: Ensure provisioning script generates correct service file

---

## Phase 26C: VS Code MCP Configuration Update

### Step 6: Re-enable Gateway in mcp.json
**Type**: file_modification  
**Target**: `.vscode/mcp.json`  
**Description**: Uncomment the eib-mcp-gateway server configuration once service is running

```jsonc
// GATEWAY MODE: Docker container with full 35 tools via Streamable HTTP
"eib-mcp-gateway": {
  "type": "http",
  "url": "http://localhost:18888/mcp",
  "headers": {
    "Authorization": "Bearer eib-mcp-gateway-token-2025"
  }
}
```

### Step 7: Verify Gateway Tools in VS Code
**Type**: validation  
**Description**: Confirm VS Code discovers gateway tools alongside stdio tools

**Expected behavior**:
- Both `eib-mcp-rag-full` (stdio) and `eib-mcp-gateway` (http) work
- Tools from gateway prefixed with `mcp_eib-mcp-gatew_*`
- No "disabled by user" errors for gateway tools

---

## Phase 26D: Documentation Updates

### Step 8: Update CHANGELOG.md
**Type**: file_modification  
**Target**: `CHANGELOG.md`  
**Description**: Document the fix

```markdown
## [7.x.x] - Docker MCP Gateway Systemd Fix (January 2026)

### Fixed
- **Systemd service group error** - Changed `Group=Terry.McGuinness` to `Group=pwuser`
  - Exit code 216/GROUP was caused by non-existent group in service file
  - Root cause: Username does not have a matching group name
  
### Changed
- `SETUP/systemd/mcp-gateway.service.template` - Removed explicit Group= line
  - Systemd now uses user's primary group automatically
  - More portable across different user configurations
```

### Step 9: Update Copilot Instructions
**Type**: file_modification  
**Target**: `.github/copilot-instructions.md`  
**Description**: Add troubleshooting note for systemd GROUP errors

---

## Verification Checklist

- [x] `systemctl status mcp-gateway` shows `Active: active (running)`
- [x] Port 18888 is LISTENING (`ss -tlnp | grep 18888`)
- [x] `curl http://localhost:18888/mcp` returns valid JSON-RPC response
- [x] `docker mcp tools ls` shows 35 EIB tools (gateway tools not available without Docker Desktop)
- [x] VS Code can call gateway tools without "disabled" errors
- [ ] n8n can connect to gateway endpoint (not tested)

---

## Impact on Dynamic Tools Feature (v7.1.6)

This fix **reverts the dynamic tools capability** that was added in CHANGELOG v7.1.6:

### What Was Lost
- `mcp-find` - Search for MCP servers in Docker catalog
- `mcp-add` - Dynamically add MCP servers at runtime
- `mcp-remove` - Remove MCP servers
- `mcp-config-set` - Configure server settings
- `mcp-exec` - Execute commands on servers
- `mcp-create-profile` - Create server profiles
- `code-mode` - Toggle code execution mode

### Why It Doesn't Work on Headless Linux
The dynamic tools require:
1. `--additional-catalog docker-mcp.yaml` - Loads official Docker MCP catalog (hundreds of servers)
2. `--enable-all-servers` - Auto-enables all servers from catalogs
3. Docker Desktop secrets store (`/.s0` socket) - Required to read API keys for third-party servers

On headless Linux (no Docker Desktop GUI), the `/.s0` socket doesn't exist, causing:
```
reading secrets exit status 1: Error: open /.s0: file does not exist
```

### Future Work Needed
A future phase should explore alternatives for dynamic MCP server discovery on headless Linux:
1. **Local secrets file** - Configure secrets via environment variables or file instead of Docker Desktop
2. **Filtered catalog** - Create a subset of docker-mcp.yaml with only servers that don't require secrets
3. **On-demand catalog loading** - Only load server definitions when explicitly requested, skip secrets
4. **Standalone secrets manager** - Use HashiCorp Vault or similar for secrets on headless systems

See: Future Phase "Headless Dynamic MCP Server Discovery"

---

## Rollback Plan

If issues persist after fix:

```bash
# Stop the service
sudo systemctl stop mcp-gateway

# Revert to manual gateway startup for development
docker mcp gateway run --servers eib-mcp-rag --transport streaming --port 18888 --verbose

# Keep VS Code on stdio-only (eib-mcp-rag-full) for stability
```

---

## Related Documents

- [Phase 11: Docker MCP Gateway Integration](phase11_docker_mcp_gateway_langflow.md)
- [Phase 23: Static Mode Multiuser Gateway](phase23_static_mode_multiuser_gateway.md)
- [DOCKER_MCP_GATEWAY_ARCHITECTURE.md](../docs/DOCKER_MCP_GATEWAY_ARCHITECTURE.md)
- [CHANGELOG.md](../../CHANGELOG.md)

---

## Execution Notes

**Execution Mode**: ISD (Interactive Supervised Development)  
**Approval Gates**: Steps 1, 4, 6 (system configuration changes)

**Pre-flight Checks**:
1. Confirm current user's primary group: `id -gn`
2. Verify docker group membership: `groups | grep docker`
3. Ensure ChromaDB and Neo4j are running: `docker ps`
