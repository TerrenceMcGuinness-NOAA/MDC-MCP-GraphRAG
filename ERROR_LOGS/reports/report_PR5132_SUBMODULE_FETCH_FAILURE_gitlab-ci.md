# build-gaeac6 (PR 5132) Submodule Fetch Failure — Failure Analysis and Best Practices

**Date**: 2026-07-30
**Failed Job**: `build-gaeac6`, pipeline for PR [NOAA-EMC/global-workflow#5132](https://github.com/NOAA-EMC/global-workflow/pull/5132) (`GFS_CI_RUN_TYPE=pr_cases`, `PR_NUMBER=5132`, machine `gaeac6`)
**Source Log**: pasted job log excerpt (no on-disk log path supplied; GitLab cleaned the project directory at job end)
**Taxonomy**: `SUBMODULE_FETCH_FAILURE` (git plumbing / CI environment — not a code or compile error)
**Tooling Used**: `agentcore-mcp-rag` MCP server, with `gh` CLI fallback for ground truth

---

## Executive Summary

The `build-gaeac6` job for PR 5132 failed at `git submodule update --init --recursive -j 8`, immediately
after `gh pr checkout 5132`. Git could not obtain the `sorc/gdas.cd` gitlink commit
`ad5efe56de8f48be9a5a568dcaf44859c04601d5`: the in-submodule `git fetch` did not produce it, and the
fallback bare-SHA request was refused by the server with `upload-pack: not our ref`. The job exited 128
before any build work started.

The commit is not missing upstream. It is the exact tip of `release/gfs.v17` in NOAA-EMC/GDASApp and has
been since 2026-07-28 12:15:37Z. The pipeline is failing because it never asks for that branch. GitLab's
clone phase populates submodules against a **twelve-week-stale baseline** (`9679b9f4e`, 2026-05-05) whose
`.gitmodules` has no `branch =` pins, and `GIT_DEPTH: 10` propagates into the submodules — so `sorc/gdas.cd`
ends up a shallow clone tracking GDASApp's *default* branch (`develop`). Every v17 `gdas.cd` pointer,
old and new, is diverged from `develop`, so resolving the gitlink always degrades to a bare-SHA
(want-by-SHA) request. That is the single most refusable git operation there is, and nothing in the
pipeline ever runs `git submodule sync`, so the stale baseline config is never repaired after checkout.

Two things made triage harder: GitLab's end-of-job `Cleaning up project directory` removed the failed
workspace before the submodule config could be inspected, and the `unable to rmdir 'sorc/nexus.fd'`
warning looks like cross-pipeline contamination but is not — see Sequence of Events.

---

## What Happened

### Sequence of Events

1. GitLab runner (shell executor, `--shell bash`) cloned the superproject into
   `${CI_BUILDS_DIR}/${WORKSPACE_ID}/global-workflow` on Gaea's F6 shared filesystem
   (`/gpfs/f6/drsa-precip3/world-shared/global/CI/GITLAB`), at `GIT_DEPTH: 10`, detached at
   `9679b9f4e`, dated **2026-05-05**. That ref is the branch the operator dispatched the trigger workflow
   from (`ref=${{ github.ref_name }}`), resolved against the GitLab mirror — an intended input, not a fault.
2. With `GIT_SUBMODULE_STRATEGY: recursive` (line 126) the runner initialised submodules from that
   May-era `.gitmodules`, which carries **no `branch =` entries**. `GIT_DEPTH` propagated
   (no `GIT_SUBMODULE_DEPTH` is set), so `sorc/gdas.cd` became a shallow clone tracking GDASApp
   `develop`. `sorc/nexus.fd` was populated, because the May tree still declared it.
3. The job script ran `git submodule status`, then entered the `pr_cases` branch: added the `github`
   remote, `git fetch github`, `gh pr checkout 5132`.
4. `gh` fetched `refs/pull/5132/head` from NOAA-EMC and created local branch `feature/gfsv17-reloc`.
   Checkout tried to remove `sorc/nexus.fd` — absent from the PR tree's `.gitmodules` — and could not,
   because untracked content sat in it. This is a **same-pipeline** transition artefact, not leftover
   state from an earlier run: `GIT_CLONE_PATH` embeds `CI_PIPELINE_ID`, so each pipeline gets a fresh
   directory.
5. The origin re-pin block (lines 167-175, from PR #4865) ran as intended.
6. `git submodule update --init --recursive -j 8` reached `sorc/gdas.cd`, which needed
   `ad5efe56…` per the PR tree. The submodule's own `git fetch` (develop-tracking, shallow) did not
   yield it. Git retried as a bare-SHA fetch. The server refused. Exit 128.

### The Failing Line

```bash
M	sorc/gdas.cd
M	sorc/gfs_utils.fd
M	sorc/gsi_monitor.fd
M	sorc/ufs_model.fd
M	sorc/ufs_utils.fd
M	sorc/verif-global.fd
M	sorc/wxflow
fatal: remote error: upload-pack: not our ref ad5efe56de8f48be9a5a568dcaf44859c04601d5
fatal: Fetched in submodule path 'sorc/gdas.cd', but it did not contain ad5efe56de8f48be9a5a568dcaf44859c04601d5. Direct fetching of that commit failed.
ERROR: Job failed: exit status 128
```

The two `fatal:` lines are one event in two halves: the first is the server declining the bare-SHA
want, the second is git reporting that neither the refspec fetch nor the SHA fallback worked.

---

## Root Cause Analysis

### Established timeline (GitHub API, verified)

| Timestamp (UTC) | Event |
| :--- | :--- |
| 2026-05-05 14:56:42 | `9679b9f4e` — the commit the pipeline cloned as its baseline |
| 2026-07-28 12:15:37 | GDASApp PR #2183 squash-merged into `release/gfs.v17`, creating `ad5efe56…` |
| 2026-07-28 14:37:45 | global-workflow #5068 bumps `sorc/gdas.cd` → `ad5efe56…` on `dev/gfs.v17` |
| 2026-07-30 15:31:34 | current `dev/gfs.v17` tip `4aa8f68f2` |

### A publish-order race is ruled out

The submodule commit was published **2h22m before** any superproject tree referenced it, and it has been
a plain, advertised branch tip continuously since. A cross-repo publish race would be a window of minutes
on 2026-07-28; failures repeating on 07-29 and 07-30 against the same SHA cannot be that window. (If other
failing jobs cite *different* SHAs, that conclusion should be revisited per-SHA.)

### Reachability facts

- `ad5efe56…` is the tip of NOAA-EMC/GDASApp `release/gfs.v17` (`compare` status: `identical`).
- GDASApp's default branch is `develop`; `develop...ad5efe56…` → **`diverged`**. The commit is a squash
  of a fork branch onto the release branch, so it is not in `develop`'s history at all.
- The May-era pointer `32d2cce8…` is **also** `diverged` from `develop`.
- From an internet-connected host, `git fetch --depth 1 origin ad5efe56…` against NOAA-EMC/GDASApp
  succeeds anonymously.

That third bullet is the one that disciplines the diagnosis. Both the old and new `gdas.cd` pointers are
unreachable from the branch the submodule tracks, so the bare-SHA fallback is not a new condition
introduced on 07-28 — it is how this pipeline has always resolved `gdas.cd`, including successfully during
the clone phase of this very job, minutes before the failure. The shallow/wrong-branch setup is therefore
the **standing fragility**, not the trigger.

### Conclusion

The pipeline's dependence on want-by-SHA is the defect. It is the request most likely to be refused —
`uploadpack.allowReachableSHA1InWant` is a server-side opt-in, and caching proxies and repository mirrors
commonly decline it or answer from a stale object view. `upload-pack: not our ref` is exactly that refusal.
Everything the pipeline controls conspires to require it:

1. Submodules are populated against a baseline **twelve weeks** behind the PR's base branch. That baseline
   is operator-selected by design (see Suggested Fix section 4), so the pipeline must tolerate an
   arbitrarily wide gap here rather than assume a near-current ref.
2. That baseline's `.gitmodules` predates the `branch =` pins, so the submodule tracks `develop`, which
   provably cannot contain any v17 `gdas.cd` pointer.
3. `GIT_DEPTH: 10` propagates into submodules (`GIT_SUBMODULE_DEPTH` is unset), narrowing the fetch further.
4. No `git submodule sync` ever runs, so the post-checkout `git submodule update` keeps using the URL and
   branch configuration written from the May tree rather than the PR tree.

What flipped on 2026-07-28 — a server-side or proxy-side change in willingness to serve that particular
bare SHA — is not determinable from this host. See Open Verification.

### Open Verification (runner-side, not answerable remotely)

Run as the runner account on Gaea C6:

```bash
git ls-remote https://github.com/NOAA-EMC/GDASApp.git release/gfs.v17
git config --list --show-origin | grep -Ei 'insteadOf|url\.|http\.|proxy'
```

Expect `ad5efe56de8f48be9a5a568dcaf44859c04601d5`. Anything else, or any `insteadOf` rewrite, means a stale
mirror sits in the fetch path — the pipeline fix below still corrects the refspecs, but will not turn the
build green on its own.

---

## Code-Level Tracing (GraphRAG Insights)

Tracing was run live during this analysis. Results, including the negative ones:

**`find_env_dependencies("GFS_CI_RUN_TYPE", tenant_id="gw_v17")`** → 0 dependents, 0 exporters.
**`find_env_dependencies("PR_NUMBER", tenant_id="gw_v17")`** → 0 dependents, 0 exporters, but the GGSR
weighted-context pass surfaced one neighbour: `run_check_gitlab_ci.sh` via `DEPENDS_ON_ENV` (weight 0.80).

Both variables are defined and consumed **inside `.gitlab-ci.yml`**, which is YAML and is not ingested as a
shell script, so the `DEPENDS_ON_ENV` edges that would connect the pipeline definition to the CI helper
scripts do not exist in the graph. The GGSR hit on `run_check_gitlab_ci.sh` is the only bridge, and it is a
consumer of the variable rather than part of the failing path. This is a genuine coverage gap for CI-config
failures, not a tool defect: the graph models shell/Fortran/Python execution, and this failure lives in
pipeline YAML plus git plumbing.

`search_issues` supplied the decisive institutional context that the graph could not:
[PR #4865 "Hotfix pipeline clone pr"](https://github.com/NOAA-EMC/global-workflow/pull/4865) (closed,
labels `bug`, `CI/CD`) is a prior fix for *this same error class* on Gaea, quoting an
`upload-pack: not our ref e454a2324fc0bd8e…` failure. Its remedy is the origin re-pin block now at lines
167-175 — which addressed `gh pr checkout` leaving the branch upstream on the author's fork, a
**different** mechanism from the one in this failure. `get_pull_requests` confirmed PR 5132's live state
(`CI-Gaeac6-Failed`, base `dev/gfs.v17`, cross-repository from `AntonMFernando-NOAA`).

Ground-truth tracing that produced the actual root cause was done through the GitHub API and on-disk
inspection:

- PR 5132 changes 17 files; **`sorc/gdas.cd` is not among them.** The pointer comes from `dev/gfs.v17`
  itself, so this is not a contributor error and re-pushing the PR branch will not clear it.
- `.gitmodules` at `9679b9f4e` vs at `refs/pull/5132/head`: identical URL for `gdas.cd`
  (`https://github.com/NOAA-EMC/GDASApp.git`), but the newer tree adds `branch = release/gfs.v17`.
  Every v17 submodule gained a `branch` pin (`ufs_model.fd → production/GFS.v17`,
  `gsi_enkf.fd → release/gfsda.v17`, and so on). The develop-branch tree has no such pins — this is a
  v17-specific shape.
- `.gitlab-ci.yml`: `GIT_DEPTH: 10` (line 44, global), `GIT_STRATEGY: clone` /
  `GIT_SUBMODULE_STRATEGY: recursive` (lines 125-126, job-scoped), `GIT_SUBMODULE_DEPTH` **absent**.
- Repository-wide grep across all five checked-out branches: **`git submodule sync` appears nowhere.**

Architectural relationship that failed: the v17 branch expresses submodule identity through
`.gitmodules` `branch` pins, but the pipeline resolves submodules from `.git/config` state seeded at a
pre-pin baseline. Those two views are only reconciled by `git submodule sync`, which the pipeline does
not call — so the newer, more precise submodule declaration is inert on Gaea.

---

## Suggested Fix / Best Practices That Prevent This

### 1. Repair submodule config after checkout (required)

In `.gitlab-ci.yml`, inside the `pr_cases` block, immediately before the existing
`git submodule update` at line 176:

```bash
        git submodule sync --recursive
        git submodule update --init --recursive -j 8
```

`sync` rewrites `submodule.<name>.url` and the branch configuration in `.git/config` from the
*checked-out* `.gitmodules`, installing `branch = release/gfs.v17` for `gdas.cd`.

### 2. Stop `GIT_DEPTH` propagating into submodules (required)

Add to the job-scoped `variables` block at lines 125-126:

```yaml
    GIT_SUBMODULE_DEPTH: 0
```

Requires GitLab 15.1+. Combined with (1), the submodule gets a normal `+refs/heads/*` refspec and
`release/gfs.v17` is fetchable as an **advertised ref**. The bare-SHA request that is being refused is then
never issued. This is the pairing that actually removes the failure mode; either change alone leaves the
want-by-SHA dependency in place.

### 3. Do not set `GIT_SUBMODULE_STRATEGY: none` as a blanket variable

Tempting, because it avoids creating the bad intermediate state at all (no May-era submodules, no
`nexus.fd` warning, no wasted recursive clone). But the `nightly` path never calls `gh pr checkout` and
never reaches the block in (1), so a global `none` would leave nightly pipelines with empty submodule
directories. It also discards object reuse the pre-clone already paid for. If it is wanted later, scope it
with `rules:variables` on `PR_NUMBER != 0` and add an explicit `else` branch performing the same
sync + update for nightly.

### 4. The stale baseline is operator-selected, not a defect (context, no change required)

An earlier draft of this report treated the 2026-05-05 baseline as a bug. It is not.
`.github/workflows/trigger-gitlab-pipelines.yml` posts `--form "ref=${{ github.ref_name }}"` to the GitLab
trigger, so the pipeline ref is whichever branch the authorised operator ran `workflow_dispatch` from,
resolved against the GitLab mirror's copy of that branch. `PR_NUMBER` and `GITHUB_COMMIT_SHA` (the PR head
OID) are passed as variables alongside it. Baseline selection is therefore deliberate and by design.

The consequence still matters for this failure, though it reframes it. The wider the gap between the
dispatched ref and the PR's base branch, the more submodule commits the post-checkout
`git submodule update` must obtain that the clone phase never fetched. That makes sections 1-2 *more*
necessary, not less: the fix has to be correct for an arbitrarily wide gap, because the pipeline is
designed to let an operator choose one. `gsi_enkf.fd`, `ufs_model.fd`, `verif-global.fd` and
`gsi_monitor.fd` carry the same v17 `branch =` pins and will exercise the same path.

Two things remain worth an operator's attention, neither a code change: whether the GitLab mirror's copy
of the dispatched branch is syncing (a mirror stuck at May would look identical to dispatching from a May
branch), and that dispatching from a ref close to the PR's base branch keeps the post-checkout submodule
delta small.

Making the first of those visible is specified as **Phase 75** —
`sdd_framework/workflows/phase75_ci_mirror_lag_detection.md`. It adds a non-fatal banner comparing the
cloned commit against GitHub's tip for the dispatched branch, and carries the baseline SHA, date and lag
count into the failure PR comment. Deliberately deferred to a second pass so the submodule fix on the
forked branch can be attributed cleanly.

### 5. Preserve the workspace on failure (operational)

`Cleaning up project directory and file based variables` destroyed the evidence needed to inspect
`submodule.sorc/gdas.cd.url`, `sorc/gdas.cd`'s remote and refspec, and
`.git/modules/sorc/gdas.cd/shallow`. A `KEEPDATA_ON_FAILURE`-style guard in `after_script` (skip cleanup
when `CI_JOB_STATUS == failed`, with a TTL sweep so F6 world-shared does not accumulate orphans) would
have made this a single-pass diagnosis.

### 6. Bounded retry, not unbounded (defensive)

Once (1) and (2) are in, a genuine transient (mirror replication lag, HPSS/Lustre hiccup) is the only
remaining cause. Wrap the submodule update in a bounded retry — 3 attempts, backoff — and let it fail
loudly after that. Do not retry the current configuration: a refused want-by-SHA is deterministic and
retrying only lengthens the feedback loop.

---

## MCP Tool Effectiveness Tally

| Tool Invoked | Parameters | Accuracy & Effectiveness Rating | Notes & Recommendations |
| :--- | :--- | :--- | :--- |
| `extract_ci_error_signal` | `log_path: (n/a)` | **Unavailable** | Not present in this session's active toolset, and the log arrived pasted into chat rather than as a file on disk. Signal extraction was done by hand. The 8KB excerpt was already high-entropy, so the loss was small here; for full multi-MB Gaea build logs this tool would matter. |
| `search_issues` | `query: "submodule not our ref upload-pack gdas.cd CI checkout"`, `repository: global-workflow`, `state: all` | **High** — decisive | Surfaced PR #4865, the prior fix for this exact error class on Gaea, as hit #1. That single result explained the otherwise cryptic re-pin block at lines 167-175 and correctly told me it addresses a *different* mechanism. Best value-per-call of the session. |
| `search_issues` | `query: "Hotfix pipeline clone pr gh pr checkout fork remote submodule"`, `state: closed` | **High** | Confirmed #4865 as the sole match, precise recall on a narrow query. |
| `get_pull_requests` | `repository: global-workflow`, `state: all`, `limit: 10` | **High** | Returned PR 5132 with the live `CI-Gaeac6-Failed` label, base branch, author and fork status. Also gave useful adjacent context (#5166, "pipeline scripts were out of sync with develop"). |
| `find_env_dependencies` | `variable_name: GFS_CI_RUN_TYPE`, `tenant_id: gw_v17` | **Low (correct but empty)** | 0 results. Tenant attribution correct (`gw_v17` / `dev/gfs.v17`). The variable lives only in `.gitlab-ci.yml`, which is not ingested as shell. Recommend ingesting CI YAML as a first-class source so pipeline variables gain `DEPENDS_ON_ENV` edges — CI-config failures are currently invisible to the graph. |
| `find_env_dependencies` | `variable_name: PR_NUMBER`, `tenant_id: gw_v17` | **Low-Medium** | 0 direct edges, but GGSR weighted context surfaced `run_check_gitlab_ci.sh` (`DEPENDS_ON_ENV`, weight 0.80). The fallback scoring earned its keep — it produced the only graph-side signal in the session, though not on the failing path. |
| `grep_search` | `submodule sync\|update\|GIT_SUBMODULE...` over `supported_repos/**` | **Medium** | Found `launch_gitlab_runner.sh` across five branch checkouts (confirming `--executor shell --shell bash`), but silently missed `.gitlab-ci.yml`: dotfile-leading paths appear to be excluded from the include-glob match. Worth flagging — a search that returns "No matches found" for a file that plainly contains the pattern is a correctness trap. Fell back to `grep` via bash. |
| `gh` CLI (fallback, permitted) | `pr view 5132`, `api .../contents/sorc/gdas.cd?ref=…`, `api .../compare/…`, `api GDASApp/pulls/2183`, `git fetch --depth 1` probe | **Decisive** | Every load-bearing fact — the timeline, `develop...ad5efe56 = diverged`, `release/gfs.v17 = identical`, the `.gitmodules` branch-pin delta, PR 5132 not touching `sorc/gdas.cd` — came from here. The MCP layer framed the problem; ground truth required the API. |

### Session note on tooling reliability

The integrated terminal reported `Exit Code: 1` for commands that plainly succeeded, and intermittently
swallowed stdout — including two `compare` API calls that had to be re-run. `read_files` and
`list_directory` returned empty objects for paths that exist. Working pattern: one short command per call,
output trimmed with `head`/`tail`, exit codes disregarded. This cost several redundant round-trips and is
worth fixing before the next log-triage session.

### Honest limits of this analysis

The fix in sections 1-2 is reasoned from verified repository and API state; it has **not** been validated
against a live pipeline run. The runner-side question in Open Verification is unresolved — if Gaea's git
reaches a stale mirror rather than github.com, correct refspecs alone will not produce a green build.
No reproduction of the failure was achieved; the local probe demonstrated the *opposite* (successful fetch)
and only served to rule out upstream unreachability.
