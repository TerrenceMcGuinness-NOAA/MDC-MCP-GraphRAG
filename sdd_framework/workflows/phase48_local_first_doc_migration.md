# Phase 48: Local-First Documentation Migration

**Version**: 1.0.0
**Status**: Complete
**Created**: 2026-05-14
**Updated**: 2026-05-14 (promoted from 0.1.0 DRAFT after v8-1-0 cutover landed; baseline measured against `global-workflow-docs-v8-1-0` @ 20511 chunks)
**Author**: GitHub Copilot + Terry McGuinness
**Dependency**: v8-1-0 ChromaDB cutover — **COMPLETE** (see `CHANGELOG.md` [8.4.0])
**Target Collection**: `global-workflow-docs-v8-2-0`
**Related**: Phase 41 (external framework docs, URL-based), Phase 42 (JEDI submodule docs, established the local-first principle), Phase 46 (rate-limit retries — band-aid this phase replaces)
**Gap Analysis**: [docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md](../../docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md)

---

## 1. Executive Summary

Generalize the **Local-First Documentation Strategy** (named in [Phase 42, §1](phase42_jedi_deep_submodule_coverage.md), proven by `ee2-standards`) to every documentation source in [documentation_sources_config.py](../../mcp_server_node/scripts/documentation_sources_config.py) that has an on-disk equivalent under `supported_repos/`.

Today the SPOT config crawls **35+ web URLs**. A subset of those URLs render content from repositories we already have checked out as git submodules — meaning we are paying for rate limits, 404s on dead version-page graveyards (e.g., ESMF), and embedding drift on rendered HTML when the source RST sits one `cd` away.

Only **two sources** currently use the local-first pattern: `ee2-standards` (Phase 1/Week 3) and JEDI sub-submodule docs (Phase 42). This phase migrates the rest.

### Symptoms motivating this phase

- **404 storms** during ESMF crawl (observed 2026-05-14 in [/tmp/reingest_docs.log](file:///tmp/reingest_docs.log) — dozens of dead `release/ESMF_<version>/` URLs hit per run).
- **Rate-limit retries** — Phase 46 §46-2 lists 6 ReadTheDocs sources requiring `--delay 5` band-aids (MOM6, CICE, GOCART, CCPP, UPP, METplus).
- **Stale renders** — `global-workflow.readthedocs.io` lags the `develop` branch in `supported_repos/global-workflow/docs/`; integrity tool drift is partly an artifact of crawling an older render.
- **Missing wiki content** — `supported_repos/global-workflow.wiki/` is checked out but never ingested. Pure win.

### Out of scope (stay URL-based)

URLs whose source repos are **not** checked out as submodules: ESMF, NUOPC, CMEPS, MOM6, CICE, WW3, CCPP, UPP, METplus, GOCART, FV3, JEDI top-level RTD, NCEPLIBS-* GitHub Pages, spack/spack-stack, wxflow, pyflow, ufs-utils, ufs-weather-model. (Adding them as submodules is a separate, much larger decision — many are >1GB.)

---

## 2. Source Audit (URL → local submodule mapping)

Cross-reference of [documentation_sources_config.py](../../mcp_server_node/scripts/documentation_sources_config.py) against `.gitmodules` and `supported_repos/` (verified 2026-05-14).

### 2.1 Migration candidates (URL has on-disk equivalent) — LOCKED

Layouts confirmed against working tree on 2026-05-14 (Step 48-1 discovery output).

| Config `name` | Current URL | Local submodule (`supported_repos/...`) | `paths` (relative to submodule) | `extensions` | Files on disk | v8-1-0 chunks (URL) | Notes |
|---|---|---|---|---|---|---|---|
| `global-workflow` | `https://global-workflow.readthedocs.io/en/latest/` | `global-workflow/` @ `3b1607e9` | `['docs/']` | `['.rst', '.md']` | 21 .rst | **219** | RTD render auto-built from this exact tree; local is fresher. **HIGH ROI.** |
| `rocoto` | `https://christopherwharrop.github.io/rocoto/` | `rocoto/` @ `a1b5f7a` (`feature/dryrun_nodaemon`) | `['README.md', 'RELEASE_NOTES.md', 'TESTING.md', 'INSTALL', 'man/']` | `['.md', '.1', '']` | 3 root .md + manpages | **0** | URL crawl returned zero useful chunks. Net new coverage. Manpages parsed as plain text. |
| `ecflow` | `https://ecflow.readthedocs.io/en/latest/` | `ECFLOW/ecflow/` @ `8759eec97` | `['docs/']` | `['.rst']` | 398 .rst | **298** | Includes `docs/python_api/`, `docs/ug/`, `docs/release_notes/`, `docs/tutorial/`. |

### 2.2 New local-only sources (not in URL list today) — LOCKED

| Proposed `name` | Local path | Format | Files | Decision | Rationale |
|---|---|---|---|---|---|
| `global-workflow-wiki` | `supported_repos/global-workflow.wiki/` @ `15054dd` | Flat Markdown (wiki-link normalization required) | 108 .md | **IN (v1.0.0)** | Operator knowledge: run-books, post-mortems, platform notes, architecture proposals. Zero current coverage. Pure win. |
| `evs-docs` | `supported_repos/EVS/` | Markdown | 7 .md | DEFER (v1.x) | Mostly EE2 compliance reports — overlaps `ee2-standards-v5-0-0-enhanced` collection. |
| `mcp-gateway-docs` | `supported_repos/mcp-gateway/docs/` | Markdown | 362 .md | DEFER (v1.x) | Docker MCP infrastructure — off-mission for NOAA forecasting users. |
| `parallel-works-mcp-docs` | `supported_repos/parallel-works-mcp/` | Markdown | 2 .md | DEFER (v1.x) | Trivial size; revisit when PW integration matures. |

### 2.3 Already migrated (precedent — do not re-touch)

| `name` | Local script | Status |
|---|---|---|
| `ee2-standards` | [`ingest_ee2_v7.py`](../../mcp_server_node/scripts/ingest_ee2_v7.py) | URL `enabled: False`; local ingest in production. |
| JEDI sub-submodule docs (no URL entry) | covered under Phase 42 | 200+ chunks across READMEs/RST/YAML in `gdas.cd/sorc/`. |

### 2.4 Stays URL-based (no submodule available)

`ufs-utils`, `esmf-user-guide`, `nuopc-layer-reference`, `wxflow`, `pyflow`, `ufs-weather-model`, `jedi-docs`, `cmeps`, `mom6`, `cice`, `ww3-wiki`, `fv3-docs`, `gocart`, `pyioda`, `fms`, `cmaq`, `spack-stack`, `spack`, all `nceplibs-*`, `wgrib2`, `ccpp-techdoc`, `google-shell-style`, `pep8`, `numpy-docstrings`, `fortran-best-practices`, `upp`, `metplus`.

These keep the existing crawler with whatever rate-limit / delay tuning Phase 46 settled on.

---

## 3. Technical Specification

### 3.1 SPOT config extension

Add a new top-level dict to [documentation_sources_config.py](../../mcp_server_node/scripts/documentation_sources_config.py) — **alongside**, not inside, `DOCUMENTATION_SOURCES`:

```python
LOCAL_DOCUMENTATION_SOURCES = {
    'tier1_critical': [
        {
            'name': 'global-workflow-local',
            'submodule': 'global-workflow',
            'paths': ['docs/'],
            'extensions': ['.rst', '.md'],
            'parser': 'sphinx_rst',
            'priority': 1,
            'description': 'Global workflow Sphinx source (replaces RTD crawl)',
            'replaces_url': 'global-workflow',
            'enabled': True,
        },
        {
            'name': 'rocoto-local',
            'submodule': 'rocoto',
            'paths': ['README.md', 'RELEASE_NOTES.md', 'TESTING.md', 'INSTALL', 'man/'],
            'extensions': ['.md', '.1', ''],
            'parser': 'markdown',                             # manpages dispatched via 'plain_text' fallback
            'priority': 1,
            'description': 'Rocoto README + manpages (URL crawl returns 0 chunks)',
            'replaces_url': 'rocoto',
            'enabled': True,
        },
        {
            'name': 'ecflow-local',
            'submodule': 'ECFLOW/ecflow',
            'paths': ['docs/'],
            'extensions': ['.rst'],
            'parser': 'sphinx_rst',
            'priority': 1,
            'description': 'ecFlow Sphinx source (replaces RTD crawl)',
            'replaces_url': 'ecflow',
            'enabled': True,
        },
    ],
    'tier2_new_coverage': [
        {
            'name': 'global-workflow-wiki',
            'submodule': 'global-workflow.wiki',
            'paths': ['./'],                                  # flat layout, all .md at root
            'extensions': ['.md'],
            'parser': 'wiki_markdown',                        # MD with wiki-link normalization
            'priority': 2,
            'description': 'Operator knowledge: run-books, post-mortems, platform notes',
            'replaces_url': None,                             # net new
            'enabled': True,
        },
        # DEFERRED to v1.x: evs-docs, mcp-gateway-docs, parallel-works-mcp-docs (see SDD §2.2)
    ],
}
```

**SPOT rule**: ingestion scripts read both dicts but **never** define sources inline.

**Disable migrated URL entries** with the `ee2-standards` pattern:
```python
'enabled': False  # Disabled - use local <submodule> via Phase 48 / ingest_local_docs_v8.py
```

### 3.2 New ingestion script

| File | Purpose |
|---|---|
| `mcp_server_node/scripts/ingest_local_docs_v8.py` | **CREATE** — generalization of [`ingest_local_docs_v4.py`](../../mcp_server_node/scripts/ingest_local_docs_v4.py) and [`ingest_ee2_v7.py`](../../mcp_server_node/scripts/ingest_ee2_v7.py) that consumes `LOCAL_DOCUMENTATION_SOURCES`. |

Behavior:
1. Read `LOCAL_DOCUMENTATION_SOURCES` from the SPOT config.
2. For each enabled entry, walk `<MCP_WORKFLOW_ROOT>/../<submodule>/<paths...>` matching `extensions`.
3. Dispatch to a parser by `parser` key (reuse the existing RST/MD/YAML chunkers — do not invent new ones).
4. Generate 768-dim MPNet embeddings (same model as URL ingest).
5. Write to the **same versioned collection** the URL ingest targets (`global-workflow-docs-v8-X-0`, controlled by `DOCS_COLLECTION` env var per the Phase 47-era patch to [`ingest_documentation_v8.py`](../../mcp_server_node/scripts/ingest_documentation_v8.py)).
6. Metadata schema:
   ```json
   {
     "source_type": "local",
     "source_name": "global-workflow-local",
     "submodule": "global-workflow",
     "submodule_commit": "<git rev-parse HEAD>",
     "file_path": "<repo-relative path>",
     "url": null
   }
   ```
   `source_type` lets queries filter local-vs-web; `submodule_commit` enables drift detection without the integrity tool's git-source comparison hack.

### 3.3 Wrapper / orchestration

Update `mcp_server_node/scripts/run_full_doc_ingest.sh` (or create one if missing) to chain:
1. `ingest_documentation_v8.py` (URL sources only — local migrations now disabled there)
2. `ingest_ee2_v7.py` (existing local script — keep until folded into `_v8`)
3. `ingest_local_docs_v8.py` (new — covers everything in §2.1 and §2.2)

All three write into the same `DOCS_COLLECTION`.

### 3.4 Parser inventory

| Format on disk | Parser to reuse | Source script |
|---|---|---|
| Sphinx RST | `parse_rst_to_chunks` | `ingest_ee2_v7.py` |
| Markdown | `parse_markdown_to_chunks` | `ingest_local_docs_v4.py` |
| YAML (config-as-doc) | `parse_yaml_to_chunks` | Phase 42 work |
| GitHub Wiki MD | `parse_markdown_to_chunks` (with wiki-link normalization) | new — small wrapper |

If a parser needs a new feature (e.g., wiki-link rewriting), extract it into `mcp_server_node/scripts/lib/doc_parsers.py` rather than copy-pasting.

---

## 4. Implementation Steps

> Baseline locked against `global-workflow-docs-v8-1-0` (20511 chunks total) on 2026-05-14.

### Step 48-1: Confirm submodule doc layouts — **DONE 2026-05-14**
**Tag**: discover
**Target**: Terminal

```bash
for sub in global-workflow rocoto ECFLOW/ecflow global-workflow.wiki EVS mcp-gateway parallel-works-mcp; do
  echo "=== $sub ==="
  find supported_repos/$sub -maxdepth 4 \( -name '*.rst' -o -name '*.md' \) \
    -not -path '*/.git/*' -not -path '*/node_modules/*' | head -25
  find supported_repos/$sub \( -name '*.rst' -o -name '*.md' \) \
    -not -path '*/.git/*' -not -path '*/node_modules/*' | wc -l
done
```
**Result**: §2.1 / §2.2 `paths`/`extensions`/`Files on disk` columns locked. Per-source v8-1-0 chunk counts captured via direct ChromaDB v2 query (sampled 20511/20511 chunks): `global-workflow`=219, `rocoto`=0, `ecflow`=298.

### Step 48-2: Add `LOCAL_DOCUMENTATION_SOURCES` to SPOT config
**Tag**: configure
**Target**: [documentation_sources_config.py](../../mcp_server_node/scripts/documentation_sources_config.py)

Add the new dict. **Do not yet** flip `enabled: False` on the URL entries it replaces — that happens after the local script ingests successfully (Step 48-5).

### Step 48-3: Implement `ingest_local_docs_v8.py`
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_local_docs_v8.py`

Per §3.2. Reuse parsers; do not duplicate. Honor `DOCS_COLLECTION` env var.

### Step 48-4: Dry-run against scratch collection
**Tag**: validate
**Target**: Terminal

```bash
DOCS_COLLECTION=phase48-scratch python3 scripts/ingest_local_docs_v8.py
```
**Expected chunk yield** (rough projection; ee2-standards@119 chunks gives ~6 chunks per RST file as the calibration constant):

| Source | Files | Projected chunks | v8-1-0 URL chunks | Δ |
|---|---|---|---|---|
| `global-workflow-local` | 21 .rst | ~125 | 219 | -94 (URL has autodoc API pages — see §6 risk) |
| `rocoto-local` | 3 .md + manpages | ~15 | 0 | **+15 net new** |
| `ecflow-local` | 398 .rst | ~2400 | 298 | **+2100 net new** (URL crawl was incomplete) |
| `global-workflow-wiki` | 108 .md | ~325 | 0 | **+325 net new** |
| **Total** | **530+ files** | **~2865** | **517** | **+2348** |

Spot-check 5 random chunks per source for content fidelity (RST directive stripping, wiki-link normalization, manpage roff handling).

### Step 48-5: Cutover — disable migrated URLs, run full chain
**Tag**: execute
**Target**: SPOT config + `global-workflow-docs-v8-2-0`

Flip `enabled: False` on `global-workflow`, `rocoto`, `ecflow` entries in `DOCUMENTATION_SOURCES` with the `ee2-standards`-style comment. Set `DOCS_COLLECTION=global-workflow-docs-v8-2-0`. Run the chain (§3.3). Compare chunk counts against the v8-1-0 baseline (20511) and against §2.1 / Step 48-4 projections.

### Step 48-6: Rebuild Docker image, cycle gateway
**Tag**: deploy
**Target**: `eib-mcp-rag:latest`

Per the project's [Docker MCP Gateway rebuild ritual](../../.github/copilot-instructions.md). Required because `documentation_sources_config.py` and `scripts/` are baked into the image.

### Step 48-7: Validate retrieval quality
**Tag**: validate
**Target**: MCP tools

```
search_documentation({ query: "global-workflow setup_expt.py", k: 5 })
search_documentation({ query: "rocoto dryrun mode", k: 5 })
search_documentation({ query: "ecflow trigger expressions", k: 5 })
```
**Acceptance**: Top-3 results carry `source_type=local` metadata; content matches current `develop` branch (not stale RTD render).

### Step 48-8: Update gap analysis + CHANGELOG
**Tag**: document
**Target**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md`, `CHANGELOG.md`

Note the migration, count of URL sources retired, count of new local sources added, and the wiki content gain.

---

## 5. Validation Criteria

Baseline column measured against `global-workflow-docs-v8-1-0` on 2026-05-14.

| Criterion | Before (v8-1-0) | After (v8-2-0 target) | Method |
|---|---|---|---|
| URL sources fetching submodule-mirrored content | 3 (`global-workflow`=219, `rocoto`=0, `ecflow`=298 chunks) | 0 | grep `enabled: True` for those names in SPOT config |
| Local-source chunks in docs collection | 119 (`ee2-standards` only; JEDI lives in code-with-context) | ≥ 2865 (per §4 Step 48-4 projection) | ChromaDB `where source_type=local` count |
| Wiki content (any collection) | 0 chunks | ~325 chunks (108 .md files) | `where submodule=global-workflow.wiki` |
| Total docs collection size | 20511 chunks | ~22800 chunks (+11%) | `collection.count()` |
| 404s in ingest log for migrated sources | many (ESMF, RTD release graveyards) | 0 for the 3 migrated names | `grep -c ERROR /tmp/reingest_docs.log` |
| Drift between collection and `develop` branch | observed (Phase 47-era integrity check) | ≤ 1 commit (per `submodule_commit` metadata) | `check_knowledge_integrity` MCP tool |
| Total ingest wall-clock time | URL chain dominated by rate-limit `--delay 5` | expected ≥ 30% lower for migrated 3 | timing the chain wrapper |

## 6. Risk Assessment

| Risk | Impact | Mitigation |
|---|---|---|
| Submodule doc tree differs from RTD render (e.g., RTD includes auto-generated API pages from source) | Lose some content | Step 48-1 verifies layout; if RTD has unique content (autodoc), keep URL `enabled: True` for that subset only |
| Sphinx RST with custom directives (`:autoclass:`, etc.) doesn't render via our parser | Chunks are noisy | Reuse the EE2 parser which already handles this; add directive stripping if needed |
| `global-workflow.wiki` is huge / contains scratch pages | Embedding budget wasted | Add a `paths`/`exclude` filter; preview chunk count in Step 48-4 |
| Bumping collection version disrupts active queries | Search degraded briefly | Same cutover pattern as v8-0-0 → v8-1-0; alias swap if implemented by then |
| Submodule not initialized on a deployment target | Local ingest finds nothing | Script asserts `git -C <submodule> rev-parse HEAD` succeeds; fail loud, do not silently skip |
| `parser` dispatch grows into a spaghetti switch | Maintenance burden | Single `lib/doc_parsers.py` registry; one function per format |

## 7. Cross-References

- **Establishing principle**: [Phase 42 §1 "Local-First Documentation Strategy"](phase42_jedi_deep_submodule_coverage.md)
- **Original URL-first plan**: [Phase 41](phase41_external_framework_documentation.md)
- **Pain that this fixes**: [Phase 46 §46-2 rate-limit retries](phase46_knowledge_base_gap_closure.md)
- **Existing local-first scripts (templates)**: [`ingest_ee2_v7.py`](../../mcp_server_node/scripts/ingest_ee2_v7.py), [`ingest_local_docs_v4.py`](../../mcp_server_node/scripts/ingest_local_docs_v4.py)
- **SPOT config**: [`documentation_sources_config.py`](../../mcp_server_node/scripts/documentation_sources_config.py)
- **Gateway rebuild ritual**: [`.github/copilot-instructions.md`](../../.github/copilot-instructions.md)

## 8. Finalization Checklist — **PROMOTED TO v1.0.0 (2026-05-14)**

- [x] Replace all **TBD** chunk-count cells with measured values. *(§2.1 baseline column, §4 Step 48-4 projection table, §5 validation table populated from `global-workflow-docs-v8-1-0` direct query.)*
- [x] Confirm Step 48-1 results and lock the `paths` / `extensions` columns in §2.1 / §2.2. *(Discovery script run 2026-05-14; layout columns LOCKED.)*
- [x] Decide whether `evs-docs`, `mcp-gateway-docs`, `parallel-works-mcp-docs` make the cut for v1 or defer to a follow-up. *(All three DEFERRED to v1.x; only `global-workflow-wiki` scoped IN for v1.0.0.)*
- [x] Set the target collection name and document the cutover script. *(`global-workflow-docs-v8-2-0`; cutover follows the v8-0-0 → v8-1-0 ritual logged in `CHANGELOG.md` [8.4.0].)*
- [x] Record SDD session ID once execution begins. *(Phase 48-2 through 48-8 executed in a single chat-context run on 2026-05-14; cutover landed in CHANGELOG `[8.5.0]`. v8-2-0 collection live at 23,624 chunks, all four `check_knowledge_integrity` checks PASS, 12/12 unit tests PASS.)*
- [x] Update `Status` to `In Progress`, `Version` to `1.0.0`, and add `Updated:` line. *(Header bumped this commit.)*
