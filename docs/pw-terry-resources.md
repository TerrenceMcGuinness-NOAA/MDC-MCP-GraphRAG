# Parallel Works — Terry McGuinness Personal Resources
**Account:** Terry.McGuinness | **Organization:** noaademo
**Generated:** June 18, 2026

---

## Project / Group Memberships

| Group | Description | Members | Budget Total | Budget Used | Remaining | Created |
|-------|-------------|---------|-------------|-------------|-----------|---------|
| **ca-infra-mdc** | ca-infra-mdc | 3 | $150,000 | $352.35 | $149,647.65 | Apr 30, 2026 |
| ca-sfs-emc | NCEPDEV — ca-sfs-emc | 22 | $3,525 | $3,750.05 | **-$225.05** ⚠️ | Oct 16, 2023 |

> Storage resources below are billed under **ca-infra-mdc**.

---

## Owned Storage Resources (2)

### Persistent Disk

| Field | Value |
|-------|-------|
| **Name** | omdmcpgraphragpersistent |
| **Display Name** | OMD MCP GraphRAG Persistent |
| **Project / Group** | ca-infra-mdc |
| **Type** | AWS EBS gp3 |
| **Size** | 550 GB |
| **Region / AZ** | us-east-1 / us-east-1a |
| **Status** | Provisioned |
| **Ephemeral** | No (persists across cluster stop/start) |
| **Throughput** | 125 MB/s |
| **Volume ID** | vol-05eafbce9cabc0924 |
| **Restored from Snapshot** | Yes (ID: 69fbb9a4fbf3eef9bf6496c1) |
| **Currently Attached To** | 698e085eda33d9b9905b926f |
| **Shared** | No (private) |
| **Created** | May 6, 2026 |

### S3 Bucket

| Field | Value |
|-------|-------|
| **Name** | omdmcpgrappragone |
| **Display Name** | Data from AWS OMD MCP |
| **Project / Group** | ca-infra-mdc |
| **Type** | AWS S3 |
| **Actual Bucket Name** | omdmcpdata |
| **Region** | us-east-1 |
| **Status** | Provisioned |
| **Versioning** | Enabled |
| **Sessionless** | Yes (persists independently of compute sessions) |
| **Ephemeral** | No |
| **Shared** | No (private) |
| **Created** | June 16, 2026 |

---

## Owned Snapshots (1)

| Name | CSP | Region | Status | Created |
|------|-----|--------|--------|---------|
| mdceibmcpgraphragpersistentten | AWS | us-east-1 | Available | May 6, 2026 |

---

## Summary Table

| Resource | Type | Group | Size | Region | Status |
|----------|------|-------|------|--------|--------|
| omdmcpgraphragpersistent | AWS EBS gp3 disk | ca-infra-mdc | 550 GB | us-east-1 / us-east-1a | Provisioned |
| omdmcpgrappragone (omdmcpdata) | AWS S3 bucket | ca-infra-mdc | — | us-east-1 | Provisioned |
| mdceibmcpgraphragpersistentten | AWS Snapshot | ca-infra-mdc | — | us-east-1 | Available |
