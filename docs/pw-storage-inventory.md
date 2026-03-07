# Parallel Works Storage Inventory — Terry McGuinness
**Account:** Terry.McGuinness | **Organization:** noaademo | **Group:** ca-sfs-emc
**Generated:** March 6, 2026

---

## Persistent Disks (1)

| Name | Display Name | Type | Size | Region / AZ | Status | Created |
|------|-------------|------|------|-------------|--------|---------|
| emceibmcpgraphragpersistenttwo | EIB MCP GraphRAG Persistent II | AWS EBS (gp2) | 500 GB | us-east-1 / us-east-1a | Provisioned | Feb 20, 2026 |

**Details:**
- Ephemeral: No (persistent across cluster stop/start)
- Restored from snapshot: Yes (ID: 69986e604abf6cb2981f59b4)
- Currently attached to: (not attached)

---

## Snapshots (2)

| Name | Size | CSP | Region | Status | Created |
|------|------|-----|--------|--------|---------|
| emceibmcpgraphragpersistentthree | 500 GB | AWS | us-east-1 | Provisioned | Feb 26, 2026 |
| mdceibmcpgraphragpersistentthree | 500 GB | AWS | us-east-1 | Provisioned | Mar 4, 2026 |

---

## Platform Snapshots Available (49)

### Rocky 8 Legacy (350 GB each)

| Region | AWS | Google | Azure |
|--------|-----|--------|-------|
| us-east-1 / eastus | Yes | Yes | Yes |
| us-east-2 / eastus2 | Yes | — | Yes |
| us-central1 | — | Yes | — |
| us-west1 | — | Yes | — |
| us-west2 | — | Yes | — |
| us-west3 | — | Yes | — |
| us-west4 | — | Yes | — |
| northcentralus | — | — | Yes |
| southcentralus | — | — | Yes |

### Rocky 8 Latest (500 GB each)

| Region | AWS | Google | Azure |
|--------|-----|--------|-------|
| us-east-1 / eastus | Yes | Yes | Yes |
| us-east-2 / eastus2 | Yes | — | Yes |
| us-central1 | — | Yes | — |
| us-west1 | — | Yes | — |
| us-west2 | — | Yes | — |
| us-west3 | — | Yes | — |
| us-west4 | — | Yes | — |
| northcentralus | — | — | Yes |
| southcentralus | — | — | Yes |

### Rocky 9 Latest (300 GB each)

| Region | AWS | Google | Azure |
|--------|-----|--------|-------|
| us-east-1 / eastus | Yes | Yes | Yes |
| us-east-2 / eastus2 | Yes | — | Yes |
| us-central1 | — | Yes | — |
| us-west1 | — | Yes | — |
| us-west2 | — | Yes | — |
| us-west3 | — | Yes | — |
| us-west4 | — | Yes | — |
| northcentralus | — | — | Yes |
| southcentralus | — | — | Yes |

### PW Custom Images (128 GB each)

| Name | CSP | Region | Owner |
|------|-----|--------|-------|
| pw-apps-rocky8-aws-20250606-us-east2 | AWS | us-east-2 | Matt.Long |
| pw-apps-rocky8-aws-20250606-us-east1 | AWS | us-east-1 | Matt.Long |
| pw-apps-rocky8-gcp-20250606-us-central1 | Google | us-central1 | Matt.Long |
| pw-apps-rocky8-az-20250606-us-east1 | Azure | eastus | Matt.Long |
| pw-apps-rocky8-az-20250606-us-east2 | Azure | eastus2 | Matt.Long |
| pw-apps-rocky9-gcp-20251124-us-central1 | Google | us-central1 | noaamaster |
| pw-apps-rocky9-aws-20251124-us-east1 | AWS | us-east-1 | noaamaster |
| pw-apps-rocky9-aws-20251124-us-east2 | AWS | us-east-2 | noaamaster |
| pw-apps-rocky9-az-20251124-us-east1 | Azure | eastus | noaamaster |
| pw-apps-rocky9-az-20251124-us-southcentralus | Azure | southcentralus | noaamaster |

---

## Summary

| Resource Type | Count | Total Size |
|--------------|-------|------------|
| Persistent Disks (mine) | 1 | 500 GB |
| Snapshots (mine) | 2 | 1,000 GB |
| Platform Snapshots (shared) | 49 | ~15 TB |
