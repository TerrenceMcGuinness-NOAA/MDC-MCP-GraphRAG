# Phase 58 — URL Crawl Gap Closure (12 Pending Sources)

**Version**: 1.0.0  
**Created**: 2026-05-18  
**Status**: ready  
**Estimated effort**: 4–6 hours (crawl time dominates)  
**Depends on**: Phase 57 (manifest status writeback) — run backfill after ingestion

---

## Objective

Ingest the 12 `url_crawl` sources in the unified manifest that have
`doc_count: 0` and `last_ingested: null`. These are either pre-existing
entries that never successfully crawled, or newly added sources from the
2026-05-18 manifest expansion (Phase 57 session).

---

## Sources to Ingest

### Pre-existing (3) — may have crawl issues

| # | Source | URL | Crawl Type | Max Pages | Notes |
|---|--------|-----|-----------|-----------|-------|
| 1 | **cmeps** | https://escomp.github.io/CMEPS/ | github_pages | 50 | May have minimal content |
| 2 | **nceplibs-sfcio** | https://noaa-emc.github.io/NCEPLIBS-sfcio/ | github_pages | 20 | Very small lib |
| 3 | **kokkos-api** | https://kokkos.org/kokkos-core-wiki/api-references.html | github_pages | 150 | JS-heavy, may need rendered mode |

### Newly added (9) — first-time crawl

| # | Source | URL | Crawl Type | Max Pages | Tier |
|---|--------|-----|-----------|-----------|------|
| 4 | **mpas-atmosphere** | https://www2.mmm.ucar.edu/projects/mpas/site/index.html | readthedocs | 150 | tier3_models |
| 5 | **catchem** | https://ufs-community.github.io/CATChem | github_pages | 100 | tier3_models |
| 6 | **cece** | https://ufs-community.github.io/CECE | github_pages | 100 | tier3_models |
| 7 | **cdeps** | https://escomp.github.io/CDEPS/versions/master/html/index.html | github_pages | 100 | tier3_models |
| 8 | **land-da** | https://land-da.readthedocs.io/en/stable/ | readthedocs | 100 | tier3_models |
| 9 | **uwtools** | https://uwtools.readthedocs.io/en/latest/ | readthedocs | 150 | tier2_workflow |
| 10 | **ufs-srweather-app** | https://ufs-srweather-app.readthedocs.io/en/develop/ | readthedocs | 200 | tier3_models |
| 11 | **gsi-user-guide** | https://dtcenter.org/sites/default/files/community-code/gsi/docs/users-guide/html_v3.7/ | readthedocs | 100 | tier1_critical |
| 12 | **hafs** | https://hafsdoc.readthedocs.io/en/latest/ | readthedocs | 100 | tier3_models |

---

## Steps

### Step 1 — Verify crawl reachability (smoke test)

For each of the 12 URLs, do a quick HTTP HEAD / curl check to confirm
the site is up and returns HTML content. Flag any that are down or
redirect unexpectedly.

```bash
for url in \
  "https://escomp.github.io/CMEPS/" \
  "https://noaa-emc.github.io/NCEPLIBS-sfcio/" \
  "https://kokkos.org/kokkos-core-wiki/api-references.html" \
  "https://www2.mmm.ucar.edu/projects/mpas/site/index.html" \
  "https://ufs-community.github.io/CATChem" \
  "https://ufs-community.github.io/CECE" \
  "https://escomp.github.io/CDEPS/versions/master/html/index.html" \
  "https://land-da.readthedocs.io/en/stable/" \
  "https://uwtools.readthedocs.io/en/latest/" \
  "https://ufs-srweather-app.readthedocs.io/en/develop/" \
  "https://dtcenter.org/sites/default/files/community-code/gsi/docs/users-guide/html_v3.7/" \
  "https://hafsdoc.readthedocs.io/en/latest/"; do
  status=$(curl -sL -o /dev/null -w "%{http_code}" "$url")
  echo "$status $url"
done
```

**Test**: All return 200. Any 404/5xx → disable that source and note in session.

---

### Step 2 — Run ingest for tier1_critical + tier2_workflow sources first

Priority order: `gsi-user-guide` (tier1), `uwtools` (tier2).

```bash
cd /mdc-mcp-rag/eib-mcp-rag-server
python3 mcp_server_node/scripts/ingest_documentation_v8.py \
  --source gsi-user-guide \
  --model titan1024 \
  --collection global-workflow-docs-v8-0-0
```

Repeat for `uwtools`.

**Test**: `search_documentation("GSI gridpoint statistical interpolation")`
returns hits from the new source.

---

### Step 3 — Run ingest for tier3_models batch (7 sources)

Run in sequence (to avoid rate-limiting):
`mpas-atmosphere`, `catchem`, `cece`, `cdeps`, `land-da`,
`ufs-srweather-app`, `hafs`.

**Test**: `search_documentation("MPAS unstructured mesh")` returns hits.
`search_documentation("HAFS hurricane vortex initialization")` returns hits.

---

### Step 4 — Retry pre-existing failures (3 sources)

`cmeps`, `nceplibs-sfcio`, `kokkos-api`. These may need special handling:
- `kokkos-api`: Try with rendered/JS-enabled crawl if standard fails
- `cmeps` / `nceplibs-sfcio`: Accept 0 docs if site truly has no content

**Test**: Check doc_count after ingest. If 0, verify manually that the
site has no crawlable documentation and mark as expected.

---

### Step 5 — Update manifest with results + CHANGELOG

After all ingests complete:
1. Run `scripts/backfill_manifest_status.py` (from Phase 57) to update
   `last_ingested` and `doc_count` for all sources.
2. Add CHANGELOG entry noting the 9 new sources and gap closure results.
3. Verify with `list_all_sources(include_gaps=True)` — PENDING count
   should drop to 0 (or only the legitimately-empty sites remain).

**Test**: `list_all_sources` gap table shows improved coverage.

---

## Acceptance Criteria

- All 12 sources attempted; at least 9 successfully ingested with `doc_count > 0`
- `search_documentation` returns relevant hits for MPAS, CATChem, CECE,
  CDEPS, Land-DA, uwtools, SRW, GSI, and HAFS
- Manifest `last_ingested` updated for all successfully ingested sources
- No regression in existing knowledge base (total docs ≥ 27,222 in
  `mdc-workflow-docs-titan1024`)

---

## Files Touched

**Modified**:
- `mcp_server_python/src/config/unified_manifest.json` (already done — 9 new entries added 2026-05-18)
- `CHANGELOG.md` (after ingestion)
