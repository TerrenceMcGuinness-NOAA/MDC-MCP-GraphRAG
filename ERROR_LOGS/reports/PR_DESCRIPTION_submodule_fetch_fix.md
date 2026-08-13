# Description

Fixes GitLab CI build failures where `git submodule update` dies with
`upload-pack: not our ref <sha>` after `gh pr checkout` (seen on Gaea C6, PR #5132,
`sorc/gdas.cd` at `ad5efe56`).

The commit is not missing upstream — it is the tip of GDASApp `release/gfs.v17`. The pipeline
never asks for that branch. Two causes, both fixed here:

1. **`GIT_SUBMODULE_DEPTH: 0`** — `GIT_DEPTH: 10` was propagating into submodules. A shallow
   submodule is fetched with a single-branch refspec pinned to the submodule's *default* branch,
   which cannot reach gitlinks on release branches (every v17 `gdas.cd` pointer is diverged from
   GDASApp `develop`). Git then falls back to a bare-SHA fetch, which servers and caching proxies
   may refuse — that refusal is the `not our ref` error. Full-depth submodules get a normal
   `+refs/heads/*` refspec, so the pinned branch is fetchable as an advertised ref.

2. **`git submodule sync --recursive`** — `git submodule update` reads `submodule.<name>.url` and
   `.branch` from `.git/config`, seeded during GitLab's clone phase from the *target-branch* commit,
   not the PR head. Without `sync`, the `branch =` pins the v17 tree carries
   (`gdas.cd → release/gfs.v17`) are silently ignored.

`GIT_SUBMODULE_STRATEGY: recursive` is unchanged, so the nightly path keeps its pre-clone.

Requires GitLab 15.1+ for `GIT_SUBMODULE_DEPTH`.

Full analysis (timeline, reachability evidence, deferred mirror-lag check):
[build-gaeac6 Submodule Fetch Failure Analysis — PR 5132](https://github.com/TerrenceMcGuinness-NOAA/global-workflow/wiki/build-gaeac6-Submodule-Fetch-Failure-Analysis-PR5132)

# Type of change

- [x] Bug fix (fixes something broken)

# Change characteristics

- Is this a breaking change (a change in existing functionality)? NO
- Does this change require a documentation update? NO
- Does this change require an update to any of the following submodules? NO

# How has this been tested?

- Pipeline run on Gaea C6 against a PR that previously failed at
  `git submodule update --init --recursive`.

# Checklist

- [x] My code follows the style guidelines of this project
- [x] I have performed a self-review of my own code
- [x] I have commented my code, particularly in hard-to-understand areas
- [ ] My changes generate no new warnings
- [ ] New and existing tests pass with my changes
