# Phase 75 — CI Baseline Mirror-Lag Detection & Failure Provenance

**Version**: 1.0.0
**Created**: 2026-07-30
**Status**: ready (deferred — sequenced after the PR 5132 submodule fix verifies green)
**Estimated effort**: 0.5–1 day
**Depends on**: the `git submodule sync` + `GIT_SUBMODULE_DEPTH: 0` change on
`supported_repos/global-workflow_forked` completing a clean `build-gaeac6` run

---

## 1. Executive Summary

Diagnosing the PR 5132 `build-gaeac6` failure (`upload-pack: not our ref` on `sorc/gdas.cd`)
consumed a full analysis session, and the single most expensive unknown was trivial: **which commit
the pipeline actually cloned**. It turned out to be `9679b9f4e`, dated 2026-05-05 — twelve weeks
behind the PR's base branch. Nothing in the job log, the GitHub PR comment, or the failure labels
said so. Reconstructing it required a dozen GitHub API calls against `refs/pull/5132/head`,
`.gitmodules` at two refs, and GDASApp branch topology.

The baseline ref is operator-selected by design: `.github/workflows/trigger-gitlab-pipelines.yml`
posts `--form "ref=${{ github.ref_name }}"`, so the operator chooses it by picking which branch to
dispatch from. That is a supported workflow and must not be broken. But a *deliberately old*
baseline and a *silently stale GitLab mirror* are indistinguishable from the job log, and both widen
the post-checkout submodule delta that produced the failure.

This phase adds a cheap, non-fatal banner comparing the cloned commit against GitHub's tip for the
same branch name, and — the higher-leverage half — carries that provenance into the failure PR
comment so the next triage starts with it instead of deriving it.

Reference: `ERROR_LOGS/reports/report_PR5132_SUBMODULE_FETCH_FAILURE_gitlab-ci.md`

---

## 2. Scope

### 2.1 In Scope
- A **mirror-lag banner** in `.build_template`'s `script`, immediately before `git submodule status`,
  so it runs for both `pr_cases` and `nightly` paths.
- Comparison of `git rev-parse HEAD` (the actual cloned baseline) against
  `git ls-remote "${GW_REPO_URL}" "refs/heads/${CI_COMMIT_REF_NAME}"`.
- Lag quantification via the already-resolved `${GH}`: commit count behind plus the baseline's
  committer date.
- **Baseline provenance capture** to a file under the workspace, and one folded line in the existing
  `comment_body` in `.failure_cleanup_template` so failed builds report their baseline on the PR.
- An **opt-in** hard-fail threshold variable (`GFS_CI_MAX_BASELINE_LAG_DAYS`), unset by default.

### 2.2 Out of Scope
- **NO change to ref-selection semantics.** `ref=${{ github.ref_name }}` stays as-is; dispatching
  from an older branch is a supported workflow.
- **NO attempt to repair or trigger the GitLab mirror.** Detection and reporting only; mirror sync
  is a GitLab project-settings concern outside this pipeline.
- **NO submodule-level reachability pre-flight.** Verifying each gitlink is reachable from its
  pinned branch before `git submodule update` is a plausible follow-on, but it needs a per-submodule
  fetch and is not justified until the Phase-75 banner shows whether lag is the recurring signal.
- **NO retry logic.** Bounded retry around the submodule update is tracked separately; a refused
  want-by-SHA is deterministic and retrying only lengthens the feedback loop.

---

## 3. Acceptance Criteria

| # | Probe | Pass condition |
|---|-------|----------------|
| 1 | Baseline matches GitHub tip | Emits `[OK] Baseline <sha> matches GitHub <ref>`; job unaffected. |
| 2 | Baseline behind GitHub tip | Emits `[WARN] Mirror lag on '<ref>': cloned <sha> (<date>), GitHub tip <sha>, behind by <n> commits`; job still succeeds. |
| 3 | Ref absent from `GW_REPO_URL` | Emits `[INFO] ... skipping mirror-lag check`. **Not** reported as lag. |
| 4 | `CI_COMMIT_SHA` overwrite immunity | Reported baseline equals the cloned commit, not `GITHUB_COMMIT_SHA`, when `PR_NUMBER != 0`. |
| 5 | Network / API failure | `ls-remote` or `gh api` failure degrades to `?` and does not fail the job. |
| 6 | Nightly path | Banner runs for `GFS_CI_RUN_TYPE=nightly` (it sits outside the `pr_cases` conditional). |
| 7 | Failure comment provenance | A build failure on a PR produces a comment containing the baseline SHA, its date, and the lag count. |
| 8 | Opt-in threshold | With `GFS_CI_MAX_BASELINE_LAG_DAYS` unset, no job ever fails on lag. With it set below the actual lag, the job fails with a clear message. |
| 9 | YAML validity | `.gitlab-ci.yml` parses and `.build_template.variables` resolves as expected. |

---

## 4. Implementation Plan

### Step 1 — Mirror-lag banner (Implement)
- Insert the banner block in `.build_template.script` before `git submodule status`.
- Use `git rev-parse HEAD`, **not** `CI_COMMIT_SHA` — `.base_config`'s `before_script` overwrites
  `CI_COMMIT_SHA` with `GITHUB_COMMIT_SHA` when `PR_NUMBER != 0`, so by the time the build script
  runs it is the PR head, not the baseline.
- Derive the repo slug from `GW_REPO_URL` rather than hardcoding `NOAA-EMC/global-workflow`.
- Unset all locals (`_baseline`, `_ref`, `_upstream`, `_slug`, `_behind`, `_bdate`) afterwards,
  matching the existing `unset _br` convention in the PR-checkout block.
- **Test**: dispatch the forked branch from a deliberately old ref; confirm criteria 1–3.

### Step 2 — Provenance capture (Implement)
- Write the three values to a small file under `${GW_RUN_PATH}` (e.g. `baseline_provenance.txt`) so
  `after_script` can read them without recomputing. `after_script` runs in a fresh shell; exported
  variables do not survive.
- **Test**: file present and populated after both a passing and a failing build.

### Step 3 — Fold into the failure comment (Implement)
- Extend the `comment_body` `printf` in `.failure_cleanup_template` with one baseline line, guarded
  so a missing provenance file degrades to `(baseline unknown)` rather than breaking the comment.
- **Test**: force a build failure on a scratch PR; confirm criterion 7.

### Step 4 — Opt-in threshold (Configure)
- Add `GFS_CI_MAX_BASELINE_LAG_DAYS` handling: when set and exceeded, `exit 1` with a message naming
  both SHAs and the dispatched ref. Leave unset in committed config.
- **Test**: criterion 8, both directions.

### Step 5 — Document & Changelog (Document)
- `CHANGELOG.md` dated entry.
- Cross-reference from
  `ERROR_LOGS/reports/report_PR5132_SUBMODULE_FETCH_FAILURE_gitlab-ci.md` section 4.
- **Test**: CHANGELOG entry present with dated header.

---

## 5. Design & Architecture

### 5.1 Why compare against GitHub rather than inspect the mirror

Mirror sync interval, last-sync timestamp, and webhook health are all GitLab project settings —
inaccessible from a job and not what the build actually depends on. What the build depends on is the
commit it got. Comparing `git rev-parse HEAD` to GitHub's tip for the same branch name is the
ground truth, needs no new credentials (`ls-remote` is anonymous, `${GH}` is already resolved in
`before_script`), and costs roughly a second plus two API calls.

### 5.2 The banner

```bash
      # ---- mirror-lag banner (non-fatal) ----
      _baseline=$(git rev-parse HEAD)
      _ref="${CI_COMMIT_REF_NAME}"
      _upstream=$(git ls-remote "${GW_REPO_URL}" "refs/heads/${_ref}" 2>/dev/null | cut -f1)
      if [[ -z "${_upstream}" ]]; then
        echo "[INFO] Baseline ref '${_ref}' not found on ${GW_REPO_URL}; skipping mirror-lag check"
      elif [[ "${_upstream}" == "${_baseline}" ]]; then
        echo "[OK] Baseline ${_baseline:0:9} matches GitHub ${_ref}"
      else
        _slug="${GW_REPO_URL#https://github.com/}"; _slug="${_slug%.git}"
        _behind=$(${GH} api "repos/${_slug}/compare/${_baseline}...${_upstream}" --jq '.ahead_by' 2>/dev/null || echo "?")
        _bdate=$(${GH} api "repos/${_slug}/commits/${_baseline}" --jq '.commit.committer.date' 2>/dev/null || echo "?")
        echo "[WARN] Mirror lag on '${_ref}': cloned ${_baseline:0:9} (${_bdate}), GitHub tip ${_upstream:0:9}, behind by ${_behind} commits"
      fi
      unset _baseline _ref _upstream _slug _behind _bdate
```

### 5.3 Three details that decide whether this is useful or noise

1. **`git rev-parse HEAD`, not `CI_COMMIT_SHA`.** The latter is deliberately reassigned to the PR
   head for GitHub status reporting. Using it would report the PR head as the baseline and always
   show zero lag — a check that can never fire.
2. **Non-fatal by default.** Operators legitimately dispatch from older branches. A hard failure
   would break a supported workflow, and a check that blocks valid usage gets disabled.
3. **Absent branch is not lag.** Dispatching from a fork-only or GitLab-only branch yields an empty
   `ls-remote` against `GW_REPO_URL`. Reporting that as staleness would train people to ignore the
   warning, which costs more than having no warning at all.

### 5.4 Why the PR comment matters more than the log line

A `[WARN]` in a 40 MB job log is findable only by someone who already suspects the answer. The
failure comment is what a developer reads first. Putting the baseline SHA, its date, and the lag
count there converts the reconstruction that took a full session into a line of text — and it
composes with `extract_ci_error_signal` (Phase 62), which distils the crash but has no view of
which baseline produced it.

### 5.5 Sequencing rationale

Held deliberately for a second pass. The forked branch currently carries exactly one change
(`git submodule sync --recursive` plus `GIT_SUBMODULE_DEPTH: 0`). Adding observability to the same
branch means a green run does not cleanly attribute and a red run offers two suspects. Land this
once the submodule fix is verified.
