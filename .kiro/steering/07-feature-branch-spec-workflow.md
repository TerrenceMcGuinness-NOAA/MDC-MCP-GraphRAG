---
inclusion: auto
---

# Feature Branch + Spec Workflow

When a Kiro spec drives multi-day implementation work, separate the **spec** (what we
intend) from the **implementation** (the work in progress) using two branches.

## Branch Pattern

| Branch | Purpose | Lifetime |
|--------|---------|----------|
| `develop_aws` | Integration branch. Specs live here. | Permanent |
| `feature/<spec-name>` | Implementation branch for one spec. | Until merged or abandoned |

## Lifecycle

### 1. Spec authoring on `develop_aws`

Specs are written, reviewed, and committed to `develop_aws` first:

```bash
git checkout develop_aws
# author .kiro/specs/<spec-name>/{requirements.md, design.md, tasks.md}
git add .kiro/specs/<spec-name>/
git commit -m "spec: add <spec-name>"
git push origin develop_aws
```

This means a spec can be refined or rejected without ever touching implementation
code. A teammate can open a PR against `develop_aws` to refine requirements while
implementation continues in parallel on the feature branch.

### 2. Feature branch creation

Once the spec is committed to `develop_aws`, branch from it:

```bash
git checkout -b feature/<spec-name>
git push -u origin feature/<spec-name>
```

The feature branch starts with the spec already in place because it was branched
from `develop_aws`.

### 3. Implementation on the feature branch

All code changes for the spec happen on the feature branch:

```bash
git checkout feature/<spec-name>
# ... implement tasks ...
git commit -m "feat(<area>): implement task N.M"
git push origin feature/<spec-name>
```

Mark `tasks.md` checkboxes complete as work progresses on this branch — those
edits stay on the feature branch and merge back with the implementation when
done.

### 4. Periodic spec sync

When the spec is refined on `develop_aws` (e.g. requirements clarification, task
re-scoping), pull those changes into the feature branch:

```bash
git checkout feature/<spec-name>
git fetch origin
git merge origin/develop_aws
# resolve any conflicts (usually only in tasks.md checkbox state)
git push origin feature/<spec-name>
```

Use `git rebase origin/develop_aws` instead of `merge` if you prefer linear
history. Force-push with `--force-with-lease` after rebase.

### 5. Final merge

When all tasks are complete and verified:

```bash
git checkout develop_aws
git merge --no-ff feature/<spec-name>
git push origin develop_aws
git branch -d feature/<spec-name>
git push origin --delete feature/<spec-name>
```

`--no-ff` preserves the feature-branch commit history as a discrete unit in the
log, making the spec's implementation easy to identify or revert as a unit.

### 6. Abandonment (if the feature is dropped)

The spec stays on `develop_aws` as documented intent. The feature branch is
deleted. A short addendum in `.kiro/specs/<spec-name>/` (or the spec's CHANGELOG
section) records the decision not to implement.

```bash
git branch -D feature/<spec-name>
git push origin --delete feature/<spec-name>
```

## When to Use This Pattern

Use it when **any** of these are true:
- Implementation will span more than a single coding session
- The spec might evolve during implementation
- Multiple people will touch the work
- You want to be able to abandon partially-done work without polluting `develop_aws`

For trivial fixes (single-commit bug fixes, doc updates), commit directly to
`develop_aws` — no feature branch needed.

## Quick Reference

```bash
# Start:        git checkout -b feature/<spec-name> develop_aws
# Sync:         git checkout feature/<spec-name> && git merge develop_aws
# Finish:       git checkout develop_aws && git merge --no-ff feature/<spec-name>
# Abandon:      git branch -D feature/<spec-name>
```

## Rationale

This pattern emerged from `feature/backend-agnostic-refactor` (May 2026). The
key insight: **the spec is documentation of intent and survives whether or not
the feature ships**. Putting it on `develop_aws` separates intent from execution
and gives us:

- Spec refinements as discrete reviewable commits
- Implementation isolated from spec-only churn
- Clean abandonment path — drop the branch, keep the spec
- Audit trail for organizational decisions ("we considered X, here's the spec, we
  chose not to ship")
