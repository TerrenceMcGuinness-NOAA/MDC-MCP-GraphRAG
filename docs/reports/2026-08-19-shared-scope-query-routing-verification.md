# shared-scope-query-routing -- Verification Record

Date: 2026-08-19
Spec: .kiro/specs/shared-scope-query-routing/
Revision under test: 99e76884b378a37d38dfbc148ed4e631a9a68565
Branch: update_shared_scoping

## What this record lets a reader conclude

**No re-ingestion is required.** Property P7 (Write-read round trip,
tests/properties/test_scope_write_read.py) establishes that every physical
collection the write path created is reachable by the read path for the
tenant that owns it, for every manifest source and every tenant it was
ingested under. Nothing under mcp_server_python/scripts/ was read,
written, or otherwise touched by this change (Requirement 12.2, enforced
by tests/unit/test_write_path_frozen.py), and nothing on any new or
modified read path creates, deletes, or writes a Physical_Collection
(Requirement 12.5, enforced by tests/properties/test_scope_no_writes.py).

**A configuration-level rollback exists without a code change.** Setting
MCP_COLLECTION_SCOPE_JSON to a document that classifies all five logical
collections as "tenant" with an empty hybrid_domains list reproduces the
pre-change (prefix-everything) routing exactly, because the Read_Router's
override transport replaces both scope tables wholesale (design.md,
"Configuration surface for scope and hybridity"). This is useful on a
runtime whose redeploy is gated, as the AgentCore runtime is here.

**Three live invocations required by Requirement 13 were BLOCKED when this
record was first written, and that was the expected state of that session,
not a defect.** That session had no AWS credentials, no MCP tools, and the
AgentCore runtime had not been redeployed with the code under test.
Section 2 records exactly which requirement criteria were unmet as a
result, names the blocking condition for each, and names the test that
covers the same (Logical_Collection, Tenant, Embedding_Profile) triple in
the live invocation's place. No live result is fabricated or inferred from
a unit test result presented as if it were one.

**AMENDED 2026-08-26: two of the three are now VERIFIED against live
infrastructure.** The runtime was redeployed (version 38 -> 39, image tag
`python-tenants-v14`) from branch `update_shared_scoping` at revision
3fcc725, and rows 2.1 and 2.2 were filled from real invocations against it.
Row 2.3 remains BLOCKED and is expected to stay so on this host: it targets
the COTS/ChromaDB container deployment, which is a different platform. The
original blocked text of each row is preserved above its filled values so
the record still shows what was and was not known when. Section 3's
substitution analyses are retained as written and marked with their
resolution, rather than deleted -- what a substitute did and did not
demonstrate remains the reason the live run was worth doing.

**One deployment prerequisite was discovered while doing this and is
recorded because it is not obvious.** The runtime carried no
`MCP_EMBEDDING_PROFILE` variable, and `DEFAULT_EMBEDDING_PROFILE` in
`src/data/collection_namer.py` is `"mpnet768"`. Deploying the Read_Router
without pinning the profile would therefore have resolved gw_v17's
tenant-scoped collections to `gw_v17_mdc-code-context-mpnet768` and
`gw_v17_mdc-jjobs-mpnet768`, neither of which exists -- the refactor would
have reported unprovisioned and read as a regression on arrival. The deploy
added `MCP_EMBEDDING_PROFILE=titan1024` as a seventh environment variable.
This is configuration, not code, and it is a precondition for any runtime
serving titan1024 data.

## 1. Test-suite entries (executed, evidence-backed)

### 1.1 Full unit + property suite

Command:

```
cd mcp_server_python && python3.12 -m pytest tests/unit tests/properties -q
```

| Field | Value |
|---|---|
| Revision under test | 99e76884b378a37d38dfbc148ed4e631a9a68565 |
| DB_BACKEND (environment, actually observed) | unset in the shell environment. ServerConfig's documented default (src/config/environment.py, load_config) resolves an unset DB_BACKEND to "aws". No test in this run set DB_BACKEND explicitly at the shell level; individual unit tests construct their own ServerConfig / adapter doubles and are hermetic with respect to this variable. |
| Passed | 1783 |
| Failed | 4 |
| Skipped | 1 |
| Warnings | 261 |
| Wall time | 110.32s |

Failed tests (all four are pre-existing and out of scope for this spec;
none touches shared-scope-query-routing's surface):

```
FAILED tests/unit/test_environment.py::test_known_modules_covers_nine_tool_modules
FAILED tests/unit/test_error_analysis.py::test_extract_ci_error_signal_tool
FAILED tests/unit/test_workflow_info_tools.py::test_resolve_workflow_root_default_when_envs_empty
FAILED tests/properties/test_tenancy.py::TestP6WorkflowRootContainment::test_workflow_root_is_contained
```

The first three are environment-dependent (module count / CI-signal
fixture / workflow-root default drift on this instance's checked-out
submodule name) and were independently confirmed failing before any
shared-scope-query-routing code existed. The fourth is a bug in the
Hypothesis test's own assertion (a substring check, `".." not in
str(workflow_root)`, where a path-component check, `".." not in
path.parts`, is the correct test); `_SUBDIR_RE` legitimately accepts
`workflow_subdir="a.."`, and `/mnt/workflow/a..` does not escape its
parent -- it resolves to itself. This failure is filed against the
tenancy surface, not scope routing, and because Hypothesis's example
search is randomized it may not reproduce on every invocation. This run
reproduced all four; a rerun reproducing three of the four (with the
fourth simply not found by the random search) would be an equally clean
result.

**Result: 0 collection errors. Every failure outside the four named
above: none observed. Pass condition met.**

### 1.2 One backend-labelled run under DB_BACKEND=cots

The design's Testing Strategy section calls for running the suite twice,
once per DB_BACKEND value, because the adapters() fixture parameterizes
over both adapter implementations already, but the tool-layer backend
label (used by a small number of tests that branch on
ServerConfig.is_aws()/is_cots()) reads the DB_BACKEND environment
variable directly.

| Field | Value |
|---|---|
| Revision under test | 99e76884b378a37d38dfbc148ed4e631a9a68565 |
| DB_BACKEND (environment, actually observed) | cots |
| Passed | 1783 |
| Failed | 4 |
| Skipped | 1 |

Same four pre-existing failures as 1.1; no new failure introduced by
setting DB_BACKEND=cots. Command:

```
cd mcp_server_python && DB_BACKEND=cots python3.12 -m pytest tests/unit tests/properties -q
```

### 1.3 One backend-labelled run under DB_BACKEND=aws

| Field | Value |
|---|---|
| Revision under test | 99e76884b378a37d38dfbc148ed4e631a9a68565 |
| DB_BACKEND (environment, actually observed) | aws |
| Passed | 1783 |
| Failed | 4 |
| Skipped | 1 |

Same four pre-existing failures as 1.1; no new failure introduced by
setting DB_BACKEND=aws. Command:

```
cd mcp_server_python && DB_BACKEND=aws python3.12 -m pytest tests/unit tests/properties -q
```

## 2. Live-invocation entries (Requirement 13.4-13.6)

Per Requirement 13.8, each row's schema is: UTC timestamp, DB_BACKEND,
Form_Factor, Embedding_Profile, tool name, complete argument list
including tenant_id, resolved tenant attribution header, every
Physical_Collection named in the Routing_Diagnostic with its
Collection_Scope, returned hit count, and at least one returned hit
identifier.

All three rows below are laid out with every required field present and
UNFILLED, so the operator's post-deploy session has a form to complete
rather than a format to invent. No field in this section was measured,
inferred, or fabricated in this session.

### 2.1 Row 1 -- search_ee2_standards, tenant_id=gw_v17, aws/agentcore/titan1024

| Field | Value |
|---|---|
| UTC timestamp | 2026-08-26T20:24:49Z (agentcore invocation at 2026-08-26T20:20Z; the corroborating direct read below is the timestamped one) |
| DB_BACKEND | aws |
| Form_Factor | agentcore |
| Embedding_Profile | titan1024 (from the `MCP_EMBEDDING_PROFILE` variable added by the 2026-08-26 deploy) |
| Tool name | search_ee2_standards |
| Complete argument list | query="err_chk err_exit error handling requirements", tenant_id="gw_v17", max_results=3 |
| Resolved tenant attribution header | `*Tenant: gw_v17*` / `*Branch: dev/gfs.v17*` |
| Physical_Collection(s) named in Routing_Diagnostic, with Collection_Scope | mdc-ee2-standards-titan1024 (shared, unprefixed, condition=provisioned-populated at 34 documents). Exactly one member -- ee2-standards-v5-0-0-enhanced is `shared` and NOT a Hybrid_Domain, so no prefixed member is addressed. |
| Returned hit count | 3 via the agentcore tool invocation (max_results=3); 5 via the corroborating direct read at k=5 |
| At least one returned hit identifier | `standards_7`, plus `standards_27`, `standards_17`, `standards_8`, `standards_28`. Every one carries `physical_collection='mdc-ee2-standards-titan1024'`. |

**Status: VERIFIED 2026-08-26.** Requirement 13.4 is MET.

Two evidence sources are recorded here and are deliberately not conflated.
The **live agentcore invocation** through the redeployed runtime returned the
attribution header and three real EE2 standards (the `err_chk` / `err_exit`
production-utility text, `cpreq`, `cpfs`, and the ex-script error-checking
example). That is the invocation Requirement 13.4 asks for. It does **not**
render document identifiers, so the **hit identifiers and per-hit
`physical_collection` values above come from a direct in-process read of the
same logical collection, at the same revision, against the same OpenSearch
index**, which does expose them. The two agree on collection, scope, and
content; only the identifier field required the second source.

Why this row matters beyond satisfying a criterion: before this change
gw_v17 addressed only `gw_v17_mdc-ee2-standards-titan1024`, which held 0
documents, so this query returned nothing. The shared-scope fallthrough is
what makes it answerable. That empty prefixed index was deleted on
2026-08-26 after confirming the router does not address it under any of the
three profiles.

### 2.2 Row 2 -- search_documentation, tenant_id=gw_v17, aws/agentcore/titan1024

| Field | Value |
|---|---|
| UTC timestamp | 2026-08-26T20:24:49Z (agentcore invocation at 2026-08-26T20:23Z) |
| DB_BACKEND | aws |
| Form_Factor | agentcore |
| Embedding_Profile | titan1024 |
| Tool name | search_documentation |
| Complete argument list | query="coupled model ocean ice configuration", tenant_id="gw_v17", max_results=4, include_graph=false |
| Resolved tenant attribution header | `*Tenant: gw_v17*` / `*Branch: dev/gfs.v17*` |
| Physical_Collection(s) named in Routing_Diagnostic, with Collection_Scope | mdc-workflow-docs-titan1024 (shared, unprefixed member of the Hybrid_Domain, first in the ordered set, 35,980 documents) AND gw_v17_mdc-workflow-docs-titan1024 (shared logical scope, prefixed member of the Hybrid_Domain, second, 28,459 documents). Both provisioned-populated. |
| Returned hit count | 4 via the agentcore tool invocation, rendered as "Found 4 results (multi-collection search)"; 5 via the corroborating direct read at k=5, split 3 / 2 across the two members |
| At least one returned hit identifier | **Per originating member, as the criterion requires.** From mdc-workflow-docs-titan1024: `0ac74b25165882d7`, `11b726f3a82754ba`, `doc_a8b2fedbc2a2`. From gw_v17_mdc-workflow-docs-titan1024: `doc_262a1fdd1fa5`, `doc_8dfa8e52e501`. Each hit's `physical_collection` field names its originating member. |

**Status: VERIFIED 2026-08-26.** Requirement 13.5 is MET, including the
"both Hybrid_Domain members" clause.

The two members are distinguishable in the rendered output by their
**Source** field, which is the strongest available evidence at the tool
layer: hits from the shared member cite external documentation sources
(`mom6`, `cice` -- URL-crawled ReadTheDocs content), while hits from the
prefixed member cite absolute repo-local paths under the v17 worktree,
specifically
`.../supported_repos/dev-v17/sorc/ufs_model.fd/doc/UsersGuide/source/InputsOutputs.rst`
and
`.../supported_repos/dev-v17/sorc/ufs_model.fd/CICE-interface/CICE/doc/source/intro/about.rst`.
Those two documents are v17 coupled-model documentation that does not exist
on the `develop` baseline, which is the concrete demonstration that the
Hybrid_Domain is doing work no single collection could.

**Recorded limitation, because it constrains what this row can prove from
the rendered text alone.** The rendered `**Collection:**` field carries the
**logical** collection name (`global-workflow-docs-v8-0-0`) for hits from
both members, so which physical member produced a hit is NOT recoverable
from the rendered response. That is why the per-member identifiers above are
taken from the hit objects' `physical_collection` field via a direct
in-process read rather than parsed out of the tool's text. The same property
is the reason `default-tenant-freeze-retirement` defines its query-tool gate
as an addressed-set-plus-provenance relation instead of a text comparison.
The two `doc_...` identifiers appear in **both** the agentcore rendering and
the direct read, which cross-validates the two paths against each other.

### 2.3 Row 3 -- one Requirement-2.6-listed tool, prefixed tenant, cots/container/mpnet768

| Field | Value |
|---|---|
| UTC timestamp | NOT RECORDED -- pending live invocation |
| DB_BACKEND | cots |
| Form_Factor | container |
| Embedding_Profile | mpnet768 |
| Tool name | <operator to select from: search_ee2_standards, search_architecture, get_operational_guidance, explain_workflow_component, search_documentation, explain_with_context, find_related_files, get_code_context> |
| Complete argument list | <operator to fill>, tenant_id=<a tenant with non-empty index_prefix, e.g. "gw_v17"> |
| Resolved tenant attribution header | NOT RECORDED -- pending live invocation |
| Physical_Collection(s) named in Routing_Diagnostic, with Collection_Scope | NOT RECORDED -- expected: at least one unprefixed shared mpnet768 collection (Collection_Scope=shared, condition=provisioned-populated), and every absent {prefix}_ prefixed member reported with condition=unprovisioned, not as a query failure |
| Returned hit count | NOT RECORDED -- expected: >= 1, drawn from the unprefixed shared collection |
| At least one returned hit identifier | NOT RECORDED |

**Status: BLOCKED.** See 3.3 for the substitution analysis and an
important nuance about what "blocked" does and does not mean for this
row.

## 3. Substitution analysis (Requirement 13.9)

For each row above, this section marks the corresponding acceptance
criterion unmet, names the specific blocking condition, and names the
test that covers the same (Logical_Collection, Tenant, Embedding_Profile)
triple in the live invocation's place. A substitution is not presented as
equivalent to a live run anywhere in this section: each entry states what
the substitute test does demonstrate and, separately and explicitly, what
it does not.

### 3.1 Requirement 13.4 (search_ee2_standards, gw_v17, aws/agentcore/titan1024) -- RESOLVED 2026-08-26, was UNMET

**RESOLUTION.** Row 2.1 is now filled from a live invocation and the
criterion is MET. The analysis below is retained as written, because the
gap between what the substitute demonstrated and what it did not is
exactly what the live run closed -- and the live run confirmed the "does
NOT demonstrate" list item by item: mdc-ee2-standards-titan1024 is
populated (34 documents), the deployed runtime does run this Read_Router
(version 39, `python-tenants-v14`), the attribution header does render
correctly end to end, and the call does return real standards.

**Blocking condition.** This session has no AWS credentials and no MCP
tool access, and the AgentCore Runtime has not been redeployed with the
revision under test (99e7688). The runtime deploy is an operator-gated
step per workspace convention (see .kiro/steering/02-development-workflow.md
and design.md's "Runtime deploy is a gated operator step") and is
explicitly out of scope for this implementing step.

**Covering test in its place.**
tests/unit/test_read_router.py's R13.1 matrix case for
ee2-standards-v5-0-0-enhanced under tenant gw_v17 at profile titan1024,
asserting resolve_read_targets returns exactly
{"mdc-ee2-standards-titan1024"} with Collection_Scope "shared" and no
prefix. Also tests/properties/test_scope_routing.py's P6 (Universal
reachability of shared scope), which asserts resolve_index(c, p) is a
member of the resolved set for every tenant and every shared collection
including this one.

**What the substitute demonstrates.** That the routing algebra correctly
computes the unprefixed mdc-ee2-standards-titan1024 as the sole member
for gw_v17 at titan1024, as a pure function with no network access.

**What it does NOT demonstrate.** That mdc-ee2-standards-titan1024 is
actually populated on the live OpenSearch domain, that the deployed
AgentCore runtime is running code containing this Read_Router, that the
tool-layer attribution header renders correctly end-to-end, or that a
live search_ee2_standards call against that runtime returns a real
standard. Those are infrastructure and deployment facts this session
cannot observe.

### 3.2 Requirement 13.5 (search_documentation, gw_v17, aws/agentcore/titan1024, both Hybrid_Domain members) -- RESOLVED 2026-08-26, was UNMET

**RESOLUTION.** Row 2.2 is now filled and the criterion is MET. Retained
for the same reason as 3.1. The live run confirmed both items this
substitute could not reach: the two indices are populated at the document
counts the requirements predicted (35,980 and 28,459 -- unchanged since
that baseline was taken), and a live call does return hits from both,
3 / 2 across the members.

**Blocking condition.** Same as 3.1 -- no AWS credentials, no MCP tools,
runtime not yet redeployed with this revision.

**Covering test in its place.**
tests/unit/test_read_router.py's R13.2 case: the Hybrid_Domain
global-workflow-docs-v8-0-0 under gw_v17 at titan1024 resolves to exactly
two members, mdc-workflow-docs-titan1024 (unprefixed, first) and
gw_v17_mdc-workflow-docs-titan1024 (prefixed, second), and a read against
that set issues one query per member. Also
tests/properties/test_scope_merge.py's P10 (result cap, provenance, and
total ordering), exercised through the adapters() fixture against both
ChromaDBAdapter and OpenSearchAdapter, which asserts every returned hit
carries exactly one physical_collection name drawn from the addressed
set, and tests/unit/test_default_tenant_byte_equivalence.py's Hybrid_Domain
merge cases which confirm the inner-merge ordering and de-duplication
rules against fixture data.

**What the substitute demonstrates.** That the inner two-member fan-out,
merge, tie-break, de-duplication, and provenance-attachment algorithm is
correct against recorded/fixture response data for both adapter
implementations.

**What it does NOT demonstrate.** That the two named indices,
mdc-workflow-docs-titan1024 (35,980 documents per the requirements'
empirically confirmed baseline) and
gw_v17_mdc-workflow-docs-titan1024 (28,459 documents), are both actually
populated and reachable on the live OpenSearch domain today, or that a
live search_documentation call against the redeployed runtime returns
hits from both.

### 3.3 Requirement 13.6 (one Requirement-2.6 tool, prefixed tenant, cots/container/mpnet768) -- UNMET

**Blocking condition.** This session has no access to the Parallel Works
Docker container service running the COTS ChromaDB deployment, and no
MCP tools to invoke it.

**Covering tests in its place.** P3 (Backend invariance,
tests/properties/test_scope_routing.py) -- establishes that
resolve_read_targets returns the same physical-name set under
DB_BACKEND=aws and DB_BACKEND=cots for the same
(Logical_Collection, Tenant, Embedding_Profile) triple, including
mpnet768. P4 (Form-factor and transport invariance,
tests/properties/test_scope_transport.py) -- establishes the same
invariance across the agentcore/container Form_Factor simulation and
across the env/file Configuration_Transport pair. The R4.3/R4.6
classification tests over the ChromaDB exception family
(tests/unit/test_vector_errors_normalization.py) -- establish that a
missing ChromaDB collection is classified CollectionNotProvisionedError
(not a generic query failure) regardless of which concrete exception
type the installed chromadb release raises. The R4.4 Skip_Block identity
test (the cross-backend Skip_Block test added under Task 4.4) --
establishes that the rendered Skip_Block text is character-for-character
identical between the ChromaDB and OpenSearch code paths for the same
(tool, Logical_Collection, tenant_id) triple.

**What the substitute demonstrates.** That the routing algebra, the
missing-collection classification, and the Skip_Block rendering are
correct and backend-symmetric on the COTS (ChromaDB) adapter, exercised
against a stubbed client -- i.e., that IF the COTS mpnet768 deployment is
reachable and has the expected shared collections populated, the
described behavior (a hit from the unprefixed shared collection, absent
prefixed members reported as unprovisioned) will occur.

**What it does NOT demonstrate.** That the COTS container service is
currently running, that its shared mpnet768 collections
(mdc-ee2-standards-mpnet768, mdc-community-summaries-mpnet768,
mdc-workflow-docs-mpnet768, etc.) are actually populated, or that a live
call against that deployment succeeds. Those are infrastructure facts
this session cannot observe.

**The COTS nuance, recorded so it is not mis-read as a failure.** Per
design.md's "The COTS / mpnet768 case, concretely" section, the COTS
ChromaDB deployment is mpnet768, and gw_v17's mpnet768 collections were
never ingested (Gap tracker Gap I records the v17 vector reindex work as
titan1024-only). Under the design's own resolution table for this exact
scenario, four of the six physical collections gw_v17 addresses at
mpnet768 are EXPECTED absent:
gw_v17_mdc-workflow-docs-mpnet768 (unprovisioned, branch-local half of
the Hybrid_Domain), gw_v17_mdc-code-context-mpnet768 (unprovisioned),
and gw_v17_mdc-jjobs-mpnet768 (unprovisioned) are all expected-absent by
design, while mdc-ee2-standards-mpnet768, mdc-community-summaries-mpnet768,
and the unprefixed half of the Hybrid_Domain, mdc-workflow-docs-mpnet768,
are expected populated. **That state SATISFIES Requirement 13.6 as
written** -- the criterion asks for a hit from an unprefixed shared
collection plus a diagnostic reporting absent prefixed members as
unprovisioned, which is exactly the expected shape here, not an error
condition. Row 2.3 is genuinely blocked only if the COTS shared mpnet768
collections are themselves unpopulated, or the container service itself
is unreachable -- not merely because gw_v17's own prefixed mpnet768
collections don't exist. This session cannot distinguish those two cases
because it cannot reach the container service at all; the operator's
post-deploy session must record which one obtains.

## 4. Spec amendments made after implementation

Three amendments were made to the spec documents after Task 10/11
implementation revealed a structural conflict. Recorded here so this
record does not read as if the spec was satisfied exactly as originally
written.

1. **Property 8 narrowed** (design.md, "Property 8: Reporting agreement").
   Originally stated over any tenant. Requirement 6.3's byte-equivalence
   for the Default_Tenant and Task 11.1's per-member reporting cannot
   both hold for the Default_Tenant -- per-member reporting necessarily
   moves the rendered bytes. Narrowed to tenants with a non-empty
   index_prefix. Preservation won per the standing default-tenant rule.

2. **Requirement 10.5 amended** (requirements.md, Requirement 10
   criterion 5). Same structural conflict, stated for the Integrity_Checker
   specifically. The amendment note records the consequence plainly: gw
   integrity findings remain unscoped, describing a mixture across every
   tenant's data. The Default_Tenant retains the legacy unscoped
   sample_metadata(collection=None) call.

3. **Task 11.2 struck** (tasks.md, Task 11.2). fortran-coverage-gap-path-fix
   had already replaced _check_coverage_gap's vector document count with
   an on-disk-source vs graph-node comparison before this spec began, so
   the sub-task's original target (a vector ingested-document count to
   re-scope) did not exist in the code. Requirement 10.4 is satisfied by
   the existing tenant-scoped graph comparison instead.

## 5. Implementation deviations worth a reader's attention

1. **resolve_tenant_index retained on both adapters** even though no
   production code path calls it after this change. It remains the
   subject of omd-tenants-1-foundation's Property 3 at
   tests/properties/test_tenancy.py:608. Removing it is that spec's
   decision to make, not this one's.

2. **The gw status total still includes mdc-content-sha-registry.**
   Preserved deliberately for Requirement 6.3 byte-equivalence, even
   though it is an ingestion dedupe ledger, not searchable content. See
   the Requirement 9 criterion 7 asymmetry recorded in requirements.md's
   "Adjacent findings recorded, not addressed."

## 6. Follow-up items deferred by this spec, and their common cause

Four items are deferred, and three of them share a single blocking cause.

1. RRF or normalized score fusion across either merge layer (the inner
   Hybrid_Domain merge or the outer cross-logical-collection merge).
2. Dropping mdc-content-sha-registry from the gw status total.
3. Scoping the Default_Tenant integrity sampler (the Property 8 /
   Requirement 10.5 amendment above).
4. DEFAULT_SEMANTIC_COLLECTION's profile pinning in
   src/graphrag/graph_guided_retrieval.py (independent of the other three).

**Items 1-3 share a common cause: the Default_Tenant is frozen
byte-for-byte (Requirement 6), so every improvement that would move gw
output is deferred by the same freeze.** That freeze was the correct
call for this spec -- it is what made a read-path refactor of this size
and blast radius (twelve query call sites, four vector-adapter code
paths, three reporting tools) safe to land without a quality-benchmark
gate. But it now concentrates unrelated debt behind one identifiable
gate, and three separate future specs would each have to re-litigate the
same freeze independently. The recommendation is one spec that retires
the byte-equivalence freeze deliberately, under a quality-benchmark
comparison gate, rather than three specs each re-opening the question.

Item 4 is independent of the freeze -- it is a layering violation
(a physical name substituted for a logical one) that happens to be
latent rather than live today, and can be fixed on its own schedule.

## 6a. The deploy that unblocked rows 2.1 and 2.2 (2026-08-26)

Recorded so the rows above are reproducible and reversible.

| Field | Value |
|---|---|
| Runtime | mdc_mcp_rag_server_python-v5K2F8BGrN (us-east-1) |
| Version | 38 -> 39 |
| Image | 903050880929.dkr.ecr.us-east-1.amazonaws.com/mdc-mcp-rag:python-tenants-v14 |
| Image digest | sha256:af3dc7526b88191300f07b6d06474c7eae0085eac8db4d0043d5697d0a433146 |
| Built from | branch update_shared_scoping at 3fcc725, native aarch64, --platform linux/arm64 |
| Rollback target | python-tenants-v13 (version 38), preserved in ECR |
| Status after update | READY |

**Payload fields carried, verified field-by-field against the pre-update
capture.** roleArn, protocolConfiguration, lifecycleConfiguration,
metadataConfiguration (`requireMMDSV2: true`), networkConfiguration
(including `requireServiceS3Endpoint: true`), and filesystemConfigurations
(EFS access point fsap-03e641f056b341f29 at /mnt/workflow) were all
compared before and after and are unchanged. These are easy to drop from an
`update-agent-runtime` call, and dropping the filesystem configuration in
particular would silently remove /mnt/workflow and with it every tenant
worktree.

**Environment variables 6 -> 7.** The only change is the addition of
`MCP_EMBEDDING_PROFILE=titan1024`, for the reason given in the amendment
note at the top of this record.

**Post-deploy observations beyond rows 2.1 and 2.2.**

- `get_knowledge_base_status(tenant_id="gw_v17")` went from 3 collections /
  81,213 documents to **6 collections / 119,340 documents**, now
  scope-labelled and including the shared members gw_v17 genuinely reads.
  This is Requirement 10's reporting convergence observed live: the listing
  is built from `tenant_collection_set` rather than the deleted prefix scan,
  which is why shared collections can appear at all.
- The Default_Tenant listing is unchanged: 16 collections / 268,100
  documents, still including `mdc-content-sha-registry` and all three
  embedding profiles. That asymmetry is the deliberate Requirement 6.3
  preservation, and the registry over-count is follow-up item 2 in section 6.
- `mcp_health_check` reports HEALTHY 4/4 with all five catalog tenants'
  `workflow_root` reachable under /mnt/workflow, which independently
  confirms the EFS configuration survived the update.

**One cosmetic finding, not a defect.** The status listing labels
`gw_v17_mdc-workflow-docs-titan1024` as `(shared)`. That is correct --
Collection_Scope is a property of the Logical_Collection, and the prefixed
index is the branch-local member of a `shared` Hybrid_Domain -- but it reads
oddly beside a tenant-prefixed name and may invite a bug report.

**Two indices deleted 2026-08-26, after the scope change made them
unreachable.** `gw_v17_mdc-ee2-standards-titan1024` and
`gw_v17_mdc-community-summaries-titan1024`, both 0 documents. Both logical
collections are `shared` and neither is a Hybrid_Domain, so the router
addresses only the unprefixed member for every tenant at every profile --
confirmed across titan1024, mpnet768, and nova1024 before deleting. Their
mappings were captured first. The empty `*-nova1024` indices were
deliberately left in place: they are correctly named and mapped for an
unused profile, and the Read_Router distinguishes provisioned-empty from
unprovisioned, so a present-but-empty index is better signal than an absent
one.

## 7. Runtime rollback note (informational, not a substitute for the deploy)

Per design.md's "Migration and rollout" / "Rollback" section: code
rollback of the atomic Task 7.3/7.5/7.6 unit is `git revert` of that
commit; this change creates, deletes, and writes nothing, so no data
migration is involved in either direction. Separately, and without any
code change, setting MCP_COLLECTION_SCOPE_JSON to
`{"schema_version": 1, "scopes": {"global-workflow-docs-v8-0-0": "tenant", "ee2-standards-v5-0-0-enhanced": "tenant", "community-summaries": "tenant", "code-with-context-v8-0-0": "tenant", "jjobs-v8-0-0": "tenant"}, "hybrid_domains": []}`
reproduces the pre-change prefix-everything routing exactly, because the
override transport replaces both scope tables wholesale rather than
merging with the built-in ones.
