# Task 14 — the Verification_Record

Implement **Task 14 (14.1 and 14.2) from tasks.md.** This is the last step in the
harness. Everything after it is operator work.

**One file, no code.** You are producing the artifact someone will trust six months
from now to know what was actually verified and what was not.

## Files you own

- NEW `docs/reports/2026-08-19-shared-scope-query-routing-verification.md`

Modify nothing else. Not `src/`, not `tests/`, not `scripts/`, not the spec.

## The one rule that governs this whole step

**You have no AWS credentials, no MCP tools, and the AgentCore runtime deploy has
not happened.** All three of R13.4-R13.6's live-invocation entries are therefore
**blocked**, and that is the expected outcome, not a failure of your step.

Your job is to record that accurately. Do **not** fabricate a live result, do not
infer one from a unit test, and do not soften "blocked" into language that reads
like partial success. A reader must be able to tell at a glance which claims rest
on executed evidence and which do not.

## 14.1 — structure and the entries you can actually fill

ASCII characters only. No credentials. No document body text from any indexed
document.

**Test-suite entries — you can and must produce these.** Run the suite and record,
per entry: count of passed tests, count of failed tests, the `DB_BACKEND` value the
suite ran under, and the revision identifier of the code under test. Get the
revision from `git rev-parse HEAD`, and report the `DB_BACKEND` value that was
actually in the environment rather than assuming one. Name the four known
pre-existing failures explicitly so a reader does not read `4 failed` as damage
from this change.

**Live-invocation entries — write the rows, mark them blocked.** Each row's schema
per R13.8 is: UTC timestamp, `DB_BACKEND`, Form_Factor, Embedding_Profile, tool
name, complete argument list including `tenant_id`, resolved tenant attribution
header, every Physical_Collection named in the Routing_Diagnostic with its
Collection_Scope, returned hit count, and at least one returned hit identifier.

Lay the three required rows out with those fields present and unfilled, so the
operator's post-deploy session has a form to complete rather than a format to
invent:

1. `search_ee2_standards(tenant_id="gw_v17")` on `aws` / `agentcore` / `titan1024`
   — expects at least one standard, with the diagnostic naming unprefixed
   `mdc-ee2-standards-titan1024` as `shared`.
2. `search_documentation(tenant_id="gw_v17")` on the same stack — expects at least
   one hit naming `mdc-workflow-docs-titan1024` and at least one naming
   `gw_v17_mdc-workflow-docs-titan1024`, each read from the attached
   `physical_collection`.
3. One tool on `cots` / `container` / `mpnet768` with a prefixed tenant — expects at
   least one hit from an unprefixed shared `mpnet768` collection, with every absent
   prefixed member reported unprovisioned rather than as a query failure.

_Requirements: 13.4, 13.5, 13.6, 13.8_

## 14.2 — the substitution analysis, stated without inflation

For each blocked invocation: mark the criterion **unmet**, name the blocking
condition, and identify the unit or property test covering the same
`(Logical_Collection, Tenant, Embedding_Profile)` triple in its place.

For the COTS entry the substitutes are P3, P4, the R4.3/R4.6 classification tests
over the ChromaDB exception family, and the R4.4 Skip_Block identity test.

**Do not present a substitution as equivalent to a live run.** State what it does
demonstrate — the routing algebra on the COTS adapter — and what it does not: that
the COTS deployment is reachable and populated. Those are different claims and the
record must not blur them.

Note the COTS nuance, because it is easy to mis-record as a failure: the COTS
ChromaDB deployment is `mpnet768` and `gw_v17`'s `mpnet768` collections were never
ingested, so four of six members are *expected* absent. That state **satisfies**
R13.6 as written, since the criterion asks for a hit from an unprefixed shared
collection plus a diagnostic reporting absent prefixed members as unprovisioned. It
is blocked only if the shared `mpnet768` collections are themselves unpopulated or
the container is unreachable.

_Requirements: 13.9_

## Also record these, because the record is the honest summary

Three spec amendments were made after implementation, and the record should carry
them so it does not read as if the spec was satisfied as originally written:

- **Property 8 narrowed** (`design.md`) to tenants with a non-empty `index_prefix`.
  R6.3 byte-equivalence and Task 11.1's per-member reporting cannot both hold for
  the Default_Tenant, and preservation won per the standing rule.
- **R10.5 amended** (`requirements.md`) for the same conflict. Consequence to state
  plainly: `gw` integrity findings remain unscoped, describing a mixture across
  every tenant's data.
- **Task 11.2 struck** (`tasks.md`). `fortran-coverage-gap-path-fix` had already
  replaced `_check_coverage_gap`'s vector document count with an on-disk vs
  graph-node comparison, so the sub-task had no target.

And two implementation deviations worth a reader's attention:

- **`resolve_tenant_index` retained on both adapters** though uncalled by
  production. It is the subject of `omd-tenants-1-foundation`'s Property 3 at
  `tests/properties/test_tenancy.py:608`. Removing it is that spec's decision.
- **The `gw` status total still includes `mdc-content-sha-registry`.** Preserved
  deliberately for byte-equivalence.

## The follow-up section: name the common cause

Four items are deferred. List them, and note what three of them share:

1. RRF or normalized score fusion across either merge layer.
2. Dropping `mdc-content-sha-registry` from the `gw` status total.
3. Scoping the Default_Tenant integrity sampler.
4. `DEFAULT_SEMANTIC_COLLECTION`'s profile pinning (independent of the others).

Items 1-3 are blocked by the same thing: the default tenant is frozen byte-for-byte,
so every improvement that would move `gw` output is deferred. That freeze was the
right call here — it is what made a read-path refactor of this size safe to land —
but it now concentrates debt in one identifiable place, and three separate specs
would each have to re-litigate it. Recommend one spec that retires the freeze
deliberately under a quality-benchmark gate.

## What the record must let a reader conclude

State it explicitly near the top: **no re-ingestion is required.** P7 establishes
that every collection the write path created is reachable by the read path for the
tenant that owns it. Also state the configuration-level rollback, since the runtime
redeploy is gated: setting `MCP_COLLECTION_SCOPE_JSON` to a document classifying
all five collections as `tenant` with an empty `hybrid_domains` reproduces the
pre-change routing exactly, with no code change.
