# Post-Mortem: Neptune Cluster Deletion During CDK Stack Update

**Date of Incident**: April 22, 2026
**Severity**: HIGH — Complete loss of production graph database (59,759 nodes, 2,633,374 relationships)
**Author**: AI Assistant + Terry McGuinness
**Status**: Recovery in progress (Phase 53)

---

## Timeline

| Date | Event |
|------|-------|
| Apr 7 | Phase 50: Graph data exported from legacy Parallel Works system to S3 |
| Apr 9 | Phase 50b: Neptune bulk load completed — 59,759 nodes, 2,633,374 rels, 0 errors |
| Apr 10 | Phase 48 validation: All 45 non-GitHub tools pass with `DB_BACKEND=aws` |
| Apr 22 | Phase 51 CDK deploy: `MdcDataStack` update replaces Neptune creation with import |
| Apr 22 | CloudFormation deletes Neptune cluster `mdc-mcp-rag-neptune` (removalPolicy: DESTROY) |
| Apr 22 | OpenSearch survives (removalPolicy: RETAIN). S3 bulk load CSVs survive. |
| Apr 22 | Phase 53 spec written. Admin role reattachment request filed. |

## What Happened

The Phase 51 "Private MCP Deployment" spec (`.kiro/specs/private-mcp-deployment/`)
called for converting `MdcDataStack` from creating Neptune and OpenSearch resources
to importing existing ones. The intent was correct — stop CDK from managing these
resources so they wouldn't be affected by future stack changes.

The implementation in task 5.1 removed the Neptune `CfnDBCluster`, `CfnDBInstance`,
`CfnDBSubnetGroup`, and associated resources from the CDK stack and replaced them
with a hardcoded endpoint string:

```typescript
// What was deployed — no CDK resource, just a string
this.neptuneEndpoint = 'mdc-mcp-rag-neptune.cluster-czm8iyqe6brc.us-east-1.neptune.amazonaws.com';
```

CloudFormation interpreted the removal of the `AWS::Neptune::DBCluster` resource
from the template as an instruction to delete it. Because the Neptune cluster had
CDK's default `removalPolicy: DESTROY` (which maps to CloudFormation's
`DeletionPolicy: Delete`), CloudFormation deleted the cluster, its instance, its
subnet group, and its security group.

OpenSearch survived because it had been explicitly set to `removalPolicy: RETAIN`
in an earlier deployment. EFS and S3 also had `RETAIN`.

## Root Cause Analysis

### The Proximate Cause

Neptune's `removalPolicy` was never set to `RETAIN`. When the resource was removed
from the CDK template, CloudFormation's default behavior (delete) took effect.

### The Deeper Failures

**1. The spec identified the risk but the implementation didn't enforce it.**

Requirement 9 of the spec explicitly stated:

> **Requirement 9.4**: THE MdcDataStack SHALL set `removalPolicy: RETAIN` on both
> the Neptune cluster and OpenSearch domain

The design document also stated:

> `removalPolicy: RETAIN` on the imported reference

But the tasks list (task 5.1) said:

> Set `removalPolicy: RETAIN` on imported references **where applicable**

The qualifier "where applicable" introduced ambiguity. When the Neptune resource was
replaced with a plain string (not a CDK construct), there was no construct to set
`removalPolicy` on. The implementer interpreted this as "not applicable" and moved on.

**2. The CDK tests verified the wrong thing.**

The test suite included this assertion:

```typescript
test('No Neptune cluster created (imported instead)', () => {
  template.resourceCountIs('AWS::Neptune::DBCluster', 0);
});
```

This test verified that Neptune was NOT in the template — which is exactly the
condition that causes CloudFormation to delete it. The test passed, giving false
confidence that the change was correct.

What was missing: a test asserting that if Neptune IS in the template, it has
`DeletionPolicy: Retain`. Or better: a pre-deployment check that no stateful
resources are being removed without `RETAIN`.

**3. No `removalPolicy: RETAIN` assertion existed anywhere in the test suite.**

A grep for `removalPolicy`, `RETAIN`, or `DeletionPolicy` across the entire CDK
test file returns zero matches. The test suite had 27 assertions covering API
Gateway configuration, security groups, WAF, CloudFront removal, and ECS settings —
but zero assertions protecting stateful data resources from deletion.

**4. The two-step deployment pattern was not followed.**

The safe pattern for converting CDK-managed resources to imports is:

1. **Deploy 1**: Add `removalPolicy: RETAIN` to the existing CDK resource
2. **Deploy 2**: Remove the CDK resource (CloudFormation retains it due to Deploy 1)

Phase 51 skipped Deploy 1 and went straight to Deploy 2. The spec's design document
mentioned this pattern in passing but did not make it a blocking prerequisite or
a separate task.

**5. No pre-deployment diff review caught the deletion.**

`cdk diff` would have shown the Neptune cluster being destroyed. There was no
step in the task list requiring `cdk diff` review before `cdk deploy`, and no
hook or automation enforcing it.

## Impact

- **Data lost**: 59,759 graph nodes, 2,633,374 relationships (entire Neptune graph)
- **Recovery path**: S3 bulk load CSVs from Phase 50b are intact — recovery is possible
  but blocked on admin IAM role reattachment to the surviving cluster
- **Data staleness**: S3 dump is from April 7 — 15 days of source tree drift not captured
- **Downstream**: AWS MCP server graph tools non-functional until recovery completes

## What Went Right

- OpenSearch had `removalPolicy: RETAIN` — 85,921 documents survived
- S3 migration bucket had `removalPolicy: RETAIN` — bulk load CSVs survived
- EFS had `removalPolicy: RETAIN` — persistent storage survived
- The Phase 53 recovery spec was written same-day with a clear 3-track plan
- The admin role reattachment request was filed immediately

## Corrective Actions

### Immediate (Phase 53 Track A — Recovery)

1. Admin reattaches `mdc-mcp-rag-neptune-s3-loader` role to surviving cluster
2. Bulk load S3 CSVs into `mdc-mcp-graprag-neptune-1`
3. Verify counts and parity

### Immediate (CDK Hardening)

4. Add `removalPolicy: cdk.RemovalPolicy.RETAIN` to ALL stateful resources in ALL stacks
5. Add CDK assertion tests for `DeletionPolicy: Retain` on every stateful resource
6. Add a pre-deployment hook requiring `cdk diff` review

### Process (Preventing Recurrence)

7. Add a steering rule: "Never remove a CDK-managed stateful resource without first
   deploying `removalPolicy: RETAIN`"
8. Add a CDK assertion test pattern: "All resources of type X must have DeletionPolicy: Retain"
   for Neptune, OpenSearch, EFS, S3, KMS, and RDS resource types
9. Add a pre-deploy checklist to the development workflow steering file
10. Require `cdk diff` output review as a mandatory step before any `cdk deploy`

## Lessons Learned

1. **CDK's default `removalPolicy` is `DESTROY`** — this is the most dangerous default
   in the entire CDK framework. Every stateful resource must explicitly set `RETAIN`.

2. **Tests that verify absence can mask deletion** — "No Neptune cluster in template"
   is a valid test for the import pattern, but without a companion test for
   `DeletionPolicy: Retain`, it becomes a false-confidence trap.

3. **Spec requirements need enforcement, not just documentation** — Requirement 9.4
   explicitly called for `RETAIN`, but no test, hook, or checklist enforced it.

4. **The two-step pattern for CDK resource migration is non-negotiable** — there is
   no safe shortcut. Deploy RETAIN first, then remove.

5. **`cdk diff` is the last line of defense** — it would have clearly shown
   `[-] AWS::Neptune::DBCluster` with `destroy` action. A mandatory diff review
   step would have caught this.
