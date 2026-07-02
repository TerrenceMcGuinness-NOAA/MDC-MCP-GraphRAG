# Phase 65 — Dev/Ingest Host ARM Upsize via IaC (r7g.2xlarge)

**Version**: 1.0.0
**Created**: 2026-07-02
**Status**: planned (deferred to week of 2026-07-06)
**Estimated effort**: 0.5–1 day (spin-up + validation), plus a short soak before decommission
**Depends on**: `docs/NIH-AWS-OMD-Extension-ROM.md` (EC2 upsize funded 2026-06-25); Phase 48 (aws-infrastructure-port); `SETUP_AWS/provisioning/cdk`
**Owner**: Terry McGuinness (OMD CAT)

---

## 1. Executive Summary

The current dev/ingest host — `c6g.xlarge` (4 vCPU / **8 GB RAM**), ARM64, `10.40.136.39`,
Amazon Linux 2023 — hits OOM during three now-routine operations (full Bedrock Titan re-ingest
~12 GB, Leiden community detection ~10 GB, side-by-side parity runs). The funded ROM
(`docs/NIH-AWS-OMD-Extension-ROM.md`) approves upsizing it to **`r7g.2xlarge`** (8 vCPU /
**64 GB RAM**, Graviton3, +~$240/mo).

**Key finding from investigation (2026-07-02):** the running box was **stood up by hand from the
console** (SG `launch-wizard-1`), so it is **NOT** managed by any CDK stack. The
`SETUP_AWS/provisioning/cdk` `ComputeStack` defines a *different* `t3.large` compute host bundled
with its own cost-control Neptune/OpenSearch — deploying that stack wholesale would duplicate the
data tier, which we do **not** want. This phase therefore stands up a **new, additive,
EC2-only stack** that references the existing VPC / subnet / EFS / data-tier services, then cuts
over and retires the console box.

This phase is **planned only** — deferred to next week. The companion CLI fix (glibc/musl) was
completed on 2026-07-02 and is captured in §8 as resolved context.

---

## 2. Scope

### 2.1 In Scope

- **New additive CDK stack** (working name `DevHostStack`) that creates **only**:
  - One `r7g.2xlarge` EC2 instance, `ec2.MachineImage.latestAmazonLinux2023({ cpuType: ARM_64 })`,
    root **gp3** (bump to ~100 GB), `requireImdsv2`, `ebsOptimized`, `detailedMonitoring`, encrypted.
  - An instance profile / role mirroring `mdc-mcp-rag-ecs-task-role` permissions
    (Bedrock `InvokeModel`, Neptune, OpenSearch, EFS, SSM, CloudWatch Logs).
  - A security group (or reuse of the existing data-plane SG) that is allowed into
    Neptune (8182) and OpenSearch (443).
  - User-data that mounts the **existing EFS access point** `fsap-03e641f056b341f29` at the
    persistent mount point (confirm `/mnt/workflow` vs `/mdc-mcp-rag`).
- References (does NOT create) the existing VPC `vpc-055f30ffa3d661e6b`, the `us-east-1d` private
  subnet (`10.40.136.0/24`), the data tier (`db.r8g.xlarge` Neptune, 2× `r6g.large.search`
  OpenSearch), and reads endpoints from existing SSM params.
- Post-deploy validation gate (see §3) before any decommission.
- Install the **musl aarch64 Kiro CLI** on the new host (same fix as §8).
- CHANGELOG entry + architecture-doc refresh (`MDC-MCP-RAG-AWS-Architecture-v3`, `AWS_ARCHITECTURE_v3.md`)
  to reflect the new instance type and that the dev host is now IaC-managed.

### 2.2 Out of Scope

- Deploying `SETUP_AWS/provisioning/cdk` `ComputeStack` as-is — it bundles a duplicate
  cost-control Neptune/OpenSearch/NAT and its EC2 is `t3.large` x86. Not the goal.
- Fallback plumbing / dual-box architecture. The new stack is additive; no fallback logic is built.
  (We keep the *old box* stopped-but-alive through the validation gate — an operational choice,
  not a design requirement.)
- Changing the OS off AL2023 to chase a newer glibc — unnecessary (see §8).
- Any change to Neptune / OpenSearch / EFS / VPC.

---

## 3. Acceptance Criteria (validation gate before decommission)

| # | Probe | Pass condition |
|---|-------|----------------|
| 1 | Stack synth + validate | `cdk synth` clean; IaC-power `validate_cloudformation_template` + `check_cloudformation_template_compliance` pass (or documented exceptions) |
| 2 | Additive only | Change set creates 1 `AWS::EC2::Instance` (+ role/SG/outputs); **zero** Neptune/OpenSearch/VPC/EFS resources created |
| 3 | Instance up | `r7g.2xlarge` reaches `running` / 2/2 status checks; ARM64 AMI booted |
| 4 | Persistent disk | EFS AP `fsap-03e641f056b341f29` mounted at the agreed mount point; existing tenant worktrees visible |
| 5 | Services reachable | Neptune (8182) + OpenSearch (443) + Bedrock `InvokeModel` reachable from the new host |
| 6 | Memory headroom | A full Titan re-ingest OR Leiden run completes without OOM (the original driver) |
| 7 | Toolchain restored | repos + `ltm/` present; Kiro CLI (musl aarch64) installed and `kiro-cli version` runs |
| 8 | IDE reconnect | Kiro IDE SSH-remote connects cleanly to the new host |
| 9 | Decommission | Only after 1–8 pass: **stop** the old `c6g.xlarge`, soak, then `terminate` |

---

## 4. Implementation Plan

### Step 1 — Gather account facts (needs AWS creds on the host or provided IDs)
`aws ec2 describe-subnets` (us-east-1d private subnet id), the data-tier security group id(s),
EFS mount-target/AP + intended mount point, and confirm `mdc-mcp-rag-ecs-task-role` is reusable
as an instance role (or mirror it). Tag: `research`.

### Step 2 — Decide stack home
Evaluate `infrastructure/cdk/` (production stack set: `MdcVpcStack` / `MdcSecurityStack` /
`MdcDataStack`) vs `SETUP_AWS/provisioning/cdk/` as the home for `DevHostStack`. Prefer the
production app if that is where VPC/data live. Tag: `design`.

### Step 3 — Author `DevHostStack`
Additive EC2-only stack. Confirmed CDK constructs (verified via IaC-power CDK docs 2026-07-02):

```typescript
instanceType: ec2.InstanceType.of(ec2.InstanceClass.R7G, ec2.InstanceSize.XLARGE2), // r7g.2xlarge
machineImage: ec2.MachineImage.latestAmazonLinux2023({
  cpuType: ec2.AmazonLinuxCpuType.ARM_64,                                            // REQUIRED for Graviton
}),
```
Reference existing VPC/subnet/SG/EFS via `fromLookup` / context. Tag: `implement`.

### Step 4 — Synth + validate
`cdk synth` → IaC-power `validate_cloudformation_template` + `check_cloudformation_template_compliance`
→ create change set (pre-deploy validation). Confirm AC 2 (additive only). Tag: `validate`.

### Step 5 — Deploy + bootstrap
`cdk deploy` the new stack. User-data mounts EFS; install musl Kiro CLI; restore repo checkout /
`ltm/`. Tag: `implement`.

### Step 6 — Validate + cut over
Run the §3 gate (EFS, service reachability, an OOM-scenario re-ingest, IDE reconnect). Repoint SSH
remote to the new host. Tag: `validate`.

### Step 7 — Decommission + document
Only after the gate passes: **stop** the old `c6g.xlarge`, soak, then `terminate`. Update CHANGELOG
and the architecture docs (instance type + "dev host now IaC-managed"). Tag: `document`.

---

## 5. Design & Architecture

### 5.1 Why additive, not a resize of the console box
The running host is not under CloudFormation (console-created, SG `launch-wizard-1`), so there is no
stack to `cdk deploy` against it. Rather than import it (fragile), we stand up a clean IaC-managed
box and cut over. This also converts a hand-built pet into managed cattle.

### 5.2 Why not the bundled `ComputeStack`
`SETUP_AWS/provisioning/cdk/lib/compute-stack.ts` intentionally bundles EC2 + Neptune + OpenSearch +
NAT as the cost-control "destruction boundary." Its Neptune (`db.r5.large`) and single-node
OpenSearch are cost-control variants, **not** the production data tier (`db.r8g.xlarge`,
2× `r6g.large.search`). Deploying it would create a second, disconnected data plane (~$500+/mo waste).

### 5.3 Persistent disk = EFS, not the root volume
The persistent, instance-independent store is EFS (`fsap-03e641f056b341f29`). The local root EBS is
per-instance and ephemeral across replacements. The new box mounts the same EFS AP, so tenant
worktrees and shared state survive the cutover. This is why the console box's local root contents
(home dir, prior `~/.local/bin/kiro-cli`, etc.) must be re-provisioned on the new host, not assumed.

### 5.4 Keep the old box stopped-but-alive through the gate
Not a design requirement — cheap operational insurance. A **stopped** instance bills only EBS
(cents/mo), no compute. Since the current box also hosts this IDE session, we do not `terminate` it
until AC 1–8 pass. Trivial cost, removes the "locked out with no working environment" failure mode.

---

## 6. Artifacts Produced

| Artifact | Path | Purpose |
|---|---|---|
| New CDK stack | `infrastructure/cdk/lib/dev-host-stack.ts` (or provisioning app) | Additive r7g.2xlarge dev host |
| App wiring | corresponding `bin/*.ts` | Register `DevHostStack` |
| CHANGELOG entry | `CHANGELOG.md` | Records dev-host migration |
| Architecture refresh | `docs/AWS_ARCHITECTURE_v3.md`, wiki `MDC-MCP-RAG-AWS-Architecture-v3` | Instance type + IaC-managed note |

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| x86→ARM/AMI arch mismatch on boot | Explicitly set `AmazonLinuxCpuType.ARM_64` on the AL2023 image (AC 3) |
| SG not actually allowed into Neptune/OpenSearch | AC 5 gates on live reachability before cutover |
| EFS mount point ambiguity (`/mnt/workflow` vs `/mdc-mcp-rag`) | Step 1 confirms the AP + mount target before bootstrap |
| Losing local-disk state on the old box | EFS holds persistent data; re-provision toolchain via user-data (AC 4, 7) |
| No AWS creds on host for lookups/deploy | Step 1 confirms creds; otherwise parameterize via context and hand off deploy commands |
| Deleting old box too early | AC 9: stop-and-soak, terminate only after gate passes |

---

## 8. Resolved Context — Kiro CLI glibc fix (2026-07-02)

Investigation established (AWS docs + Kiro docs + Arm Learning Paths):

- **AL2023 is pinned to glibc 2.34** for the entire release lifecycle (AWS toolchain docs; latest
  AL2023 still `glibc-2.34-231`; glibc 2.38 is an open, unfulfilled package request). A bigger box
  or a fresh AL2023 spin-up does **not** change this — the `r7g.2xlarge` will also be glibc 2.34.
- The **Kiro IDE** requires glibc **2.39+**; the built-in `kiro-cli update` pulled a build aligned
  to that newer baseline, which is why it failed on our 2.34 with `GLIBC_2.38/2.39 not found`.
- **Fix applied:** installed the **musl aarch64 Kiro CLI** build
  (`kirocli-aarch64-linux-musl.zip` from the official release CDN) — statically linked, **no glibc
  dependency**, so it runs on AL2023 regardless of glibc version. This is Arm's documented
  recommendation for older-glibc / non-glibc systems.
- **Operational note:** do **not** use `kiro-cli update` on AL2023 (it re-pulls the glibc-2.39
  build). Reinstall the musl zip to upgrade. The new r7g.2xlarge host must use the same musl build.
- The Kiro **IDE remote-server** binary (v1.0.0) was unaffected throughout — it is a separate
  binary and continued to power the IDE session.

### 8.1 "Latest" clarification + stay-current helper

- The musl build is **NOT a downgrade or fallback fork.** Both the glibc and musl packages are
  published together under the CDN `/latest/` path, so the musl zip is the *same current release*
  (2.11.0 as of 2026-07-02), statically linked — full feature/version parity with the glibc build.
- **Stay-current helper:** `SETUP/update-kiro-cli-musl.sh` re-installs the newest musl `/latest/`
  release (arch-detecting aarch64/x86_64). Re-run it to upgrade. This replaces `kiro-cli update`,
  which must not be used on AL2023.

### 8.2 CLI 3.0 Early Access (agentic harness)

- CLI 3.0 EA is **not a separate binary/download** — it is a runtime opt-in flag,
  `kiro-cli --v3`, on the existing 2.x install. Per Kiro docs, V3 "runs alongside your existing
  2.x install," so the 2.x behavior is unchanged until you pass `--v3`. Introduced ~CLI 2.8; our
  2.11.0 build includes it.
- Because the opt-in lives inside the musl binary we already installed, `--v3` runs on AL2023
  (glibc 2.34) without the glibc-2.39 problem that blocks the standalone glibc build and the
  Kiro **IDE** (which does require glibc 2.39+). Installing 3.0 "in another location on disk"
  is unnecessary and would not help — glibc compatibility is a system-level property, not a
  function of install path.
- **To early-adopt:** run `kiro-cli --v3` interactively. If the V3 harness ever surfaces a
  runtime dependency that needs newer glibc, that is a separate investigation — but the opt-in
  mechanism itself is bundled in the musl binary.
