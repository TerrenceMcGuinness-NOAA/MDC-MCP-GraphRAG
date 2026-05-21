---
inclusion: auto
---

# Git Operation Policy

Defines what git operations the agent may run autonomously and which
require an explicit user request. The goal is to keep the human in the
loop on the two operations that move the repo forward (commit, push)
while still letting the agent stage work for review.

## Rules

| Operation | Autonomous? | Notes |
|-----------|-------------|-------|
| `git status` | Yes | Read-only |
| `git diff` (any form) | Yes | Read-only |
| `git log` | Yes | Read-only |
| `git branch` (list / show-current) | Yes | Read-only |
| `git fetch` | Yes | No local mutation beyond `.git/` |
| `git add <paths>` | **Yes** | Staging is encouraged so the user can review staged hunks |
| `git restore --staged <paths>` | Yes | Inverse of `git add`; needed to unstage during review |
| `git stash` (push / pop / list) | Yes | Local-only |
| `git commit` | **No — requires direct user request** | Including amend, fixup, squash |
| `git push` (any remote) | **No — requires direct user request** | Including `-u`, `--force-with-lease`, etc. |
| `git push --force` | **No — never, even on request without confirmation** | High-risk per the safety_guardrails |
| `git checkout` / `switch` to a different branch | **No — requires direct user request** | Branch context is operator-managed |
| `git merge` / `git rebase` | **No — requires direct user request** | History-altering |
| `git reset --hard` | **No — never, even on request without confirmation** | Destructive |
| `git clean -f` | **No — never, even on request without confirmation** | Destructive |
| `git tag` (push / delete) | **No — requires direct user request** | Release surface |

### What "direct user request" means

The user has typed words like "commit", "push", "merge", "checkout
branch X" — or has explicitly approved a proposed plan that names that
operation. Implicit phrasing such as "wrap this up", "we're done", or
"finish the task" does **not** authorize commit or push.

When the user's request implies a commit (e.g. "let's check this in"),
the operation is authorized; when it doesn't (e.g. "this looks good"),
ask before committing.

## Default Workflow

1. Make file edits via fs_write / str_replace / etc.
2. Run any verification (build, tests, validators).
3. **Stage with `git add <specific paths>`** so the user can review the
   exact files in `git status` / `git diff --cached`.
   - Prefer staging specific files over `git add .` to avoid pulling in
     unrelated changes (per the always-on git_safety guidance).
4. Summarize what was changed and what is staged.
5. **Stop.** Wait for the user to say commit / push / amend.

## Phrasing in Agent Replies

- After completing work, say something like:
  > Staged the following: `<files>`. Ready for your review. Let me know
  > when to commit (and whether to push).

- Do **not** say "I'll commit and push that" without an explicit
  request, even if the work is complete and verified.

- If the user asks "is everything saved?" — clarify: file edits are
  written to disk, changes are staged, but nothing has been committed
  or pushed.

## Rationale

Keeps the human as the gate on the two operations that produce a
durable, shareable record of work. Staging is non-destructive and
gives the reviewer a clean view of "what would be in the next commit"
without making a commit. This aligns with the broader Spec-First
posture: code lands when the user agrees it should, not when the
agent decides it's ready.
