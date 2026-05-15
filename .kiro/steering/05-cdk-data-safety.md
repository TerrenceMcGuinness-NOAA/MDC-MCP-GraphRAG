---
inclusion: auto
---

# CDK Data Safety — Mandatory Guardrails

## Origin

This steering rule was created after the April 22, 2026 incident where a CDK stack
update deleted the Neptune cluster containing 59,759 nodes and 2,633,374 relationships.
See `docs/postmortem/2026-04-22-neptune-data-loss.md` for the full post-mortem.

## Rule 1: Every Stateful Resource MUST Have `removalPolicy: RETAIN`

Any CDK resource that stores data MUST include:

```typescript
removalPolicy: cdk.RemovalPolicy.RETAIN,
```

This applies to (at minimum):
- `AWS::Neptune::DBCluster` / `AWS::Neptune::DBInstance`
- `AWS::OpenSearchService::Domain`
- `AWS::EFS::FileSystem`
- `AWS::S3::Bucket`
- `AWS::KMS::Key`
- `AWS::RDS::DBCluster` / `AWS::RDS::DBInstance`
- `AWS::DynamoDB::Table`
- `AWS::DocDB::DBCluster`

**No exceptions.** CDK's default is `DESTROY`. Relying on the default for any
data-bearing resource is a data loss incident waiting to happen.

## Rule 2: CDK Tests MUST Assert `DeletionPolicy: Retain` on Stateful Resources

Every CDK test suite MUST include assertions verifying that stateful resources
have `DeletionPolicy: Retain` in the synthesized CloudFormation template.

Pattern:
```typescript
test('Stateful resources have DeletionPolicy Retain', () => {
  const statefulTypes = [
    'AWS::EFS::FileSystem',
    'AWS::S3::Bucket',
    // add all stateful types present in the stack
  ];
  for (const type of statefulTypes) {
    const resources = template.findResources(type);
    for (const [logicalId, resource] of Object.entries(resources)) {
      expect((resource as any).DeletionPolicy).toBe('Retain');
    }
  }
});
```

## Rule 3: Two-Step Pattern for CDK Resource Migration

When converting a CDK-managed resource to an imported resource (or removing it
from CDK management entirely), you MUST follow this two-step deployment:

**Step 1 — Deploy RETAIN**: Add `removalPolicy: cdk.RemovalPolicy.RETAIN` to the
existing CDK resource. Deploy this change. CloudFormation updates the resource's
`DeletionPolicy` to `Retain`.

**Step 2 — Remove from CDK**: Remove the CDK resource construct and replace with
an import (e.g., `Domain.fromDomainEndpoint()`). Deploy this change. CloudFormation
sees the resource removed from the template but retains it because of Step 1.

**Skipping Step 1 will result in data loss.** There is no safe shortcut.

## Rule 4: Mandatory `cdk diff` Before Every `cdk deploy`

Before running `cdk deploy` on any stack, you MUST:

1. Run `cdk diff <StackName>`
2. Review the output for any resource deletions (lines starting with `[-]`)
3. If ANY stateful resource shows as being deleted, STOP and investigate
4. Only proceed with `cdk deploy` after confirming no unintended deletions

This is the last line of defense. `cdk diff` would have shown:
```
[-] AWS::Neptune::DBCluster MdcNeptuneCluster destroy
```
...which would have prevented the April 22 incident.

## Rule 5: Pre-Deploy Checklist for Stack Modifications

Before deploying any CDK stack change that modifies data resources:

- [ ] All stateful resources have `removalPolicy: RETAIN`
- [ ] CDK assertion tests verify `DeletionPolicy: Retain` for all stateful resources
- [ ] `cdk diff` reviewed — no unintended resource deletions
- [ ] If migrating resources out of CDK: two-step pattern followed (Rule 3)
- [ ] `cdk synth` succeeds without errors
- [ ] CDK assertion tests pass (`npx jest`)
