# Default-Tenant Freeze Retirement -- Retirement Record

Feature: default-tenant-freeze-retirement (SDD Phase 80)
Point of record: sdd_framework/workflows/phase80_default_tenant_freeze_retirement.md
Record date: 2026-08-19
Scope: this document records findings and decisions only. It changes no
runtime behaviour. It is ASCII only, carries no credentials, and carries no
query result body text.

This record accompanies the retirement of the Phase 79
(shared-scope-query-routing) Default_Tenant byte-freeze -- Requirement 6
criteria 2 and 3 -- as a standing rule. The freeze was the correct instrument
for a 1,635-insertion read-path refactor, but as a permanent fixture it blocked
three convergence follow-ups, one of which preserves a document total known to
be wrong. The replacement gate (a Python benchmark harness plus a
Structural_Equivalence relation plus an addressed-set check) was built and shown
to work before either frozen criterion was relaxed, so the Default_Tenant read
path was never ungated. The staged ordering is recorded in the phase document
and enforced by the atomic sub-tasks 6.3 and 8.3.


## 1. Threshold reconciliation

Three regression thresholds were declared before this feature. They are not in
conflict as numbers; they govern different comparison bases, and that is the
disagreement Requirement 6 criterion 1 names.

| Declared value | Where | Comparison basis | Consumer |
|---|---|---|---|
| regression_threshold_pct = 5 | corpus metrics_config | previous single run | run_benchmark.js::detectRegressions, warn level |
| critical_threshold_pct = 15 | corpus metrics_config | previous single run | run_benchmark.js::detectRegressions, error level; sets the Node exit code |
| MCP_BENCHMARK_REGRESSION_PCT = 10 | Nightly_Wrapper (run_benchmark_nightly.sh) | trailing 7-run median | the wrapper's own Regression_Check, structured ERROR log lines |

The Governing_Threshold -- the single percentage that decides whether a proposed
change to Default_Tenant output passes -- is 10 percent, evaluated as a relative
drop against the trailing Median_Window median, per Benchmark_Category and for
the overall object, with a strict comparison: a drop of exactly 10.00 percent
passes and a drop greater than 10.00 percent fires. The comparison the wrapper
performs is cur_v < med * (1 - pct / 100.0). Requirement 11 criterion 3 gates a
proposed change on the trailing Median_Window median, which is the wrapper's
basis, so the Governing_Threshold is necessarily the wrapper's number, and
Requirement 6 criterion 3 then requires the wrapper's default equal it. It
already does (MCP_BENCHMARK_REGRESSION_PCT default 10), so this reconciliation is
a no-op on the wrapper's functional content; only comment text moved (Task 4.1).

Accompanying values, per Requirement 6 criterion 4:

- Median_Window: 7 (MCP_BENCHMARK_MEDIAN_WINDOW).
- minimum_coverage_pct floor: 80 (corpus metrics_config).

Why 10 and not 5 or 15. Each Benchmark_Category holds exactly ten Default_Tenant
cases, so category coverage moves in 0.1 steps; every distinct category coverage
value across the 21 recorded runs is a multiple of 0.1. Four of the six
categories sit at a median coverage of 1.0. Under the strict comparison, a
single case going dark in one of those categories is a relative drop of exactly
10.00 percent, which passes at 10 and fires at two flips -- tolerate one case
going dark, catch two, which is the sensitivity this gate wants.

- At 5, four of six categories become single-flip tripwires. Four of the 21
  recorded runs are backend outages (coverage 0.30 and 0.6167), so a nightly job
  at 5 would generate false positives faster than signal.
- At 15, coverage behaviour at 1.0 is identical to 10 (0.9 passes, 0.8 fires at
  20 percent), so 15 buys nothing for the two coarse categories, and it pays for
  that by loosening the overall block from firing at six flips of 60 to firing
  at nine, and by waving through a 14 percent relative precision drop (0.125
  absolute at ee2_compliance's 0.89). Not a trade worth making.

Two consequences recorded rather than hidden. First, code_structure (median 0.7)
and cross_language (median 0.9) fire on a single case flip; the overall block,
whose 60-case granularity is six times finer, is the primary instrument and the
per-category blocks are the coarse localisers. Second, the Gated_Metric triple
{mrr, precision_at_k, coverage} has rank two -- see section 2 -- so the
Regression_Check evaluates {coverage, precision_at_k}, two independent signals,
not three. A reviewer counting three signals would overestimate the gate.

Requirement 6 criterion 6: the corpus metrics_config values
(regression_threshold_pct 5, critical_threshold_pct 15) remain in force for the
Node_Harness's own in-process check and its exit code, against the previous
single run, via run_benchmark.js::detectRegressions. Reconciliation names which
number governs a Default_Tenant output change; it does not reach inside the
Node_Harness. Three thresholds over two comparison bases, kept distinct.


## 2. Score comparability across the harness changeover

### 2.1 Formula equality: demonstrated

For each of precision_at_k, recall_at_k, coverage, and mrr, the Benchmark_Harness
computes the metric by the same formula as the Node_Harness. No formula
difference was found. This is not a prose assertion: Property 7
(tests/unit/test_benchmark_node_parity.py) re-derives every recorded value from
the committed Quality_Metrics_Log and asserts exact equality -- 1,260 per-case
rows and 147 aggregate scopes across 21 runs, latency percentiles included.

Every one of the 147 scope observations reports an mrr value equal to its
coverage value, with zero deviations. The mechanism is structural in both
harnesses, not a coincidence of one: an MCP text response carries exactly one
response text, and a Python Tool_Closure returns str, so the response-text
sequence has length one and the reciprocal rank of the first matching text is
the covered flag -- per-case mrr is 1.0 when covered and 0.0 otherwise, which is
coverage. That is why the Gated_Metric triple has rank two.

### 2.2 Score comparability: not demonstrated, and cannot be here

Formula equality is not score equality. Scores depend on store content, and the
implementation environment has no live backend (Requirement 3 criterion 7 is a
constraint, not a preference). Equal formulas over different stores are not equal
scores. Comparability between a Benchmark_Harness run and the Node_Harness runs
already in the Quality_Metrics_Log was therefore not demonstrated. Per
Requirement 5 criterion 3's second arm, that is recorded here with the reason:
no live backend, so no scored run to compare.

### 2.3 Changeover decision (dated entry, 2026-08-19)

Because comparability was not demonstrated, Requirement 5 criterion 4 triggers:
the Node_Harness lines of the Quality_Metrics_Log are archived before the first
Benchmark_Harness line is appended, and the Median_Window restarts from zero.

The archive is a one-time operator step. It is not a call to the wrapper's
rotate(): rotate() fires only when the log exceeds KEEP_RUNS (default 90), and
the log holds 21 lines, so no code path reaches it -- and Requirement 7 criterion
3 forbids adding one. The operator step is a hand-run equivalent that archives
the whole log and truncates it, reusing rotate()'s own directory,
filename pattern, and timestamp format verbatim:

    STATE="${MCP_HOST_STATE_DIR:-/mcp_rag_eib/data/mcp-server/state}"
    ARCHIVE="${MCP_BENCHMARK_ARCHIVE_DIR:-${STATE}/benchmark-archive}"
    STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
    mkdir -p "${ARCHIVE}"
    gzip -c "${STATE}/quality_metrics.jsonl" \
      > "${ARCHIVE}/quality_metrics_${STAMP}.jsonl.gz"
    : > "${STATE}/quality_metrics.jsonl"

The archive file is named quality_metrics_${STAMP}.jsonl.gz under the
benchmark-archive directory, where ${STAMP} is date -u +%Y%m%dT%H%M%SZ,
compressed with gzip -c. After the step the log is empty and the Median_Window
restarts from zero. This decision is dated 2026-08-19 so a later reader can tell
which median window a given Quality_Metrics_Log line belongs to (Requirement 5
criterion 6).

### 2.4 The arming subtlety -- the single most consequential sentence here

The archive and the arming behaviour must be read as one consequence, because
read separately they understate what they jointly mean.

After the archive the log is empty. Run 1 leaves one line, and the wrapper's
outer len(rows) < 2 guard blocks evaluation. Run 2 leaves two lines, which
satisfies the outer guard, so the wrapper logs two lines and reports status: ok
-- while the per-metric len(vals) < 2 guard still means no metric is evaluated.
Run 3 is the first real comparison.

So the gate is blind for the first two Python runs and announces success on the
second. The arming date is the third run, not the second. A reader who takes
status: ok on run 2 as a passing gate has been misled by a true statement, which
is the worst kind. "The check reported ok" and "the gate is armed" are different
statements on the second night after the changeover.


## 3. Gate continuity

### 3.1 The two conditions that prevented earlier retirement (R8.4)

| Condition | Cleared by this feature? |
|---|---|
| Absence of a Python benchmark harness -- the nightly benchmark drove the Node_Harness, which has no tenant concept and never touched the Python read path Phase 79 rewrote | Yes. The Benchmark_Harness (mcp_server_python/scripts/run_benchmark.py) was built, drives Python Tool_Closures through the tenancy ContextVar, and scores by formulas proven identical to the incumbent's over 1,260 recorded cases. |
| Absence of live-invocation access -- no AWS credentials and no reachable backend in the implementation environment | No. This remains operator-gated. The replacement gate is proven hermetically; the live confirmation is not available here. |

### 3.2 The three unmet live-invocation entries, and their hermetic stand-ins (R8.5)

The three live-invocation entries of the Phase 79 Verification_Record (that
document's Requirement 13 criteria 4, 5, and 6) remain unmet and operator-gated.
Retirement does not imply a live verification that has not occurred. Each is
named below with the hermetic test that stands in for it:

1. Phase 79 R13.4 -- search_ee2_standards(tenant_id="gw_v17") on aws /
   agentcore / titan1024, returning at least one standard from the unprefixed
   shared collection mdc-ee2-standards-titan1024. Hermetic stand-in: the
   Tenant_Scoped_Case ee_t01 (search_ee2_standards, gw_v17), which scores near
   1.0 when shared-scope routing works and 0 when it regresses to
   prefix-everything, together with Property 13
   (tests/properties/test_addressed_sets.py) asserting the addressed set for
   the shared EE2 domain.
2. Phase 79 R13.5 -- search_documentation(tenant_id="gw_v17") on aws /
   agentcore / titan1024, returning at least one hit from
   mdc-workflow-docs-titan1024 and at least one from
   gw_v17_mdc-workflow-docs-titan1024. Hermetic stand-in: the Tenant_Scoped_Case
   ss_t01, which names the Hybrid_Domain collection explicitly and exercises the
   two-member Resolved_Collection_Set merge layer, together with Property 13's
   provenance clause asserting every returned hit carries a non-empty
   physical_collection.
3. Phase 79 R13.6 -- one Query_Tool on cots / container / mpnet768 with a
   prefixed tenant, returning a hit from the unprefixed shared mpnet768
   collection and reporting absent prefixed members as unprovisioned rather than
   as a query failure. Hermetic stand-in: Property 13, whose provenance clause
   sweeps both ChromaDBAdapter and OpenSearchAdapter through the adapters()
   fixture and whose addressed_set clause is profile-swept over titan1024 and
   mpnet768, so the cots/mpnet768 routing is checked without a live cots
   backend.


## 4. Consumer audit

### 4.1 In-repo consumers of rendered MCP response text (R12.1, R12.2)

Every file in this repository that pattern-matches on rendered MCP response
text, with the response element each matches on:

| File | Response element matched |
|---|---|
| mcp_server_python/tests/parity/parity_runner.py | the *Tenant: <id>* attribution header, via the regex _TENANT_HEADER_RE in strip_tenant_header |
| mcp_server_python/tests/parity/test_self_parity.py | the leading *Tenant: gw* attribution header (startswith) |
| mcp_server_python/tests/unit/test_tenant_resolver.py | the *Tenant: <id>* attribution header (substring) |
| mcp_server_python/tests/unit/test_config_file_writes.py | the graph label prefix token in emitted Cypher (for example `GW_V17_ConfigFile`, `ConfigFile`) |
| mcp_server_python/tests/unit/test_tenant_tool_exposure.py | the *Tenant: <id>* and *Branch: <branch>* attribution headers |
| mcp_server_python/tests/unit/test_attribution_branch.py | the *Tenant: <id>* / *Branch: <branch>* attribution header lines, including the [STALE] suffix |

### 4.2 Out-of-repo consumers -- a bounded finding, not a completed audit (R12.3)

Consumers outside this repository -- Kiro sessions, CI pipelines, and Tier B and
Tier C agent wrappers -- cannot be enumerated from this repository. This is
recorded as a bounded finding, not as a completed enumeration. It is the reason
the audit exists at all: the query-tool formatting is now ungated (see 4.4), so
an out-of-repo consumer that matches on a relabelled field or a changed separator
would break silently, and this record cannot list those consumers.

### 4.3 The Collection field is the Logical name, unmoved by design (R12.4)

The **Collection:** field rendered by mcp_server_python/src/tools/semantic_search.py
carries the Logical_Collection name. Phase 79 added physical_collection as a new
result key rather than repurposing collection, specifically to leave that
rendered field unmoved. So a consumer matching on the rendered Collection field
sees the same Logical name after Phase 79 as before it.

### 4.4 What a reviewer would otherwise overestimate: query-tool output is ungated (R12.5)

Carried from step 9's recorded reduction: neither replacement gate reads rendered
bytes for a Query_Tool. The Structural_Equivalence relation gates the three
reporters (Status_Reporter, Integrity_Checker, Health_Reporter), and the
addressed-set plus provenance check gates Query_Tool routing -- but neither gates
the rendered text of a Query_Tool hit. A relabelled field or a changed separator
in Query_Tool output passes both halves. This is placed next to the consumer
audit deliberately: the audit exists to bound exactly this exposure.

None of the six in-repo consumers enumerated in 4.1 matches on an element a
Follow_Up_Sequence change (section 5) alters. The attribution-header consumers
match the Tenant / Branch header, which no follow-up changes; the config-file
writer matches a graph label prefix on the write path, which no follow-up
changes. So there is no in-repo consumer to name alongside a Follow_Up_Sequence
entry under Requirement 12 criterion 5; the exposure is entirely in the
out-of-repo, unenumerable set of 4.2.


## 5. Follow-up sequencing

### 5.1 The Follow_Up_Sequence, in order (R14.1)

The three Default_Tenant convergence changes this feature unblocks, in the
Glossary order, with the Phase 79 Requirement 6 criterion that governed each
before this feature:

1. The mdc-content-sha-registry over-count in the gw status total. Governed
   before this feature by Phase 79 Requirement 6 criterion 3 (the reporting
   freeze), because it flows through the Status_Reporter default branch.
2. The Default_Tenant Integrity_Checker sampler scoping. Governed before this
   feature by Phase 79 Requirement 6 criterion 3 (the reporting freeze).
3. Cross-member score fusion. Governed before this feature by Phase 79
   Requirement 6 criterion 2 (the query-result freeze), because it changes
   retrieval ranking.

### 5.2 Serial, not concurrent, and each voids prior baselines (R14.2)

The three entries are performed one after another, not concurrently. A
Default_Tenant output change voids every baseline recorded before it as a
reference -- which is why the sequence runs one at a time and each entry
re-records the affected Structural_Equivalence baseline in the same change that
alters the output (Requirement 10 criterion 7).

### 5.3 Authority (R14.3)

Each Follow_Up_Sequence entry cites
sdd_framework/workflows/phase80_default_tenant_freeze_retirement.md as the
authority for changing Default_Tenant output.

### 5.4 The third entry relies on an exercised gate (R14.4)

By the time the third entry (cross-member score fusion) relies on the benchmark
gate, that gate has already been exercised by the first two entries. The first
two changes pass through the benchmark comparison before the third depends on it.

### 5.5 A fourth follow-up this feature does not gate (R14.5)

The DEFAULT_SEMANTIC_COLLECTION profile pinning is a fourth Phase 79 follow-up.
This feature does not gate it, and it may proceed independently of the three
above.


## 6. Baseline provenance (R13.5)

The baselines this feature records, and the git revision each was captured from:

- The corpus categories digest
  (mcp_server_python/tests/baselines/expected/corpus_categories_digest.json) was
  captured at commit f0dd4a9 (Task 1.2), from the Ground_Truth_Corpus categories
  object at corpus version 1.0.0, before the tenant_categories sibling container
  was added. The categories object it pins is byte-identical to Phase 80 base
  revision c5b2ea7.
- The Default_Tenant addressed-set expectations
  (mcp_server_python/tests/baselines/expected/addressed_sets.json) were captured
  at commit 28aaae4 (Task 8.1) by calling addressed_set() over
  src.data.read_router.resolve_read_targets for every (tool, profile) pair.
- The Structural_Equivalence comparison reuses Phase 79's pre_change/*.md byte
  baselines, captured at Reference_Revision
  4eb422915bdf2728466e6ff5df449b7a539cdede.

A baseline recorded before a Default_Tenant output change is void as a reference
after that change. This is exactly why the Follow_Up_Sequence runs one at a time
(section 5.2): each output change invalidates the reference the next change would
otherwise compare against, and a Structural_Equivalence baseline, unlike a
Byte_Equivalence baseline, is re-recordable from any revision (see
tests/baselines/README.md).

The two supersession commits -- the ones that relaxed the Phase 79 criteria --
are the commits touching
mcp_server_python/tests/unit/test_default_tenant_byte_equivalence.py: 9d638d3
(Requirement 6 criterion 3, the reporting freeze) and b623644 (Requirement 6
criterion 2, the query-result freeze). Phase 80's base is c5b2ea7.


## 7. Rollback (R15.7)

The Phase 79 configuration-level rollback remains available without a code change
and without a redeploy: setting MCP_COLLECTION_SCOPE_JSON to a document
classifying all five Logical_Collections as tenant with an empty hybrid-domain
list restores the pre-Phase-79 prefix-everything routing. This feature does not
alter that rollback path.


## 8. Calibration section -- deliberately incomplete, operator-filled

Per Design Decision 2, the retrieval-category Tenant_Scoped_Case expectations
cannot be validated in an environment with no live backend. The first live run is
therefore a calibration run. The operator records, for each of the eight
Tenant_Scoped_Cases, whether it scored 0 on that run, and distinguishes an
expected zero from a miscalibration.

| Case id | Tool | First-live-run score (operator fills) | Expected zero? |
|---|---|---|---|
| cs_t01 | analyze_code_structure | (pending live run) | no |
| ss_t01 | search_documentation | (pending live run) | no |
| ar_t01 | search_architecture | (pending live run) | yes -- pending Gap J |
| ee_t01 | search_ee2_standards | (pending live run) | no |
| op_t01 | get_job_details | (pending live run) | no |
| kb_t01 | get_knowledge_base_status | (pending live run) | no |
| ki_t01 | check_knowledge_integrity | (pending live run) | no |
| cl_t01 | trace_full_execution_chain | (pending live run) | no |

The one expected zero is ar_t01: gw_v17_mdc-community-summaries-titan1024 holds
zero documents while Gap J is open, so search_architecture returns an
[INFO] Skip_Block and the case scores 0 by design. It flips to non-zero when the
community-summaries pipeline runs. Any other case scoring 0 on the first live run
is a miscalibration -- a corpus expected-value bug to fix, not a routing defect.

The mitigation that makes this safe: Requirement 2 criterion 9 computes the
categories object -- the object Requirement 11 criterion 3 gates a Default_Tenant
change on -- from Default_Tenant cases only. A wrong tenant expectation shows up
in the tenant-scoped block (tenant_overall / tenant_categories), where it is a
corpus bug to fix, not a false failure on someone else's Default_Tenant change.


## 9. The four pre-existing test failures

Four tests fail before and after this feature, and they are not this feature's to
fix. They are named in Requirement 15 criterion 4 and touch neither the read
path, the benchmark, nor the baselines:

- tests/unit/test_environment.py::test_known_modules_covers_nine_tool_modules
- tests/unit/test_error_analysis.py::test_extract_ci_error_signal_tool
- tests/unit/test_workflow_info_tools.py::test_resolve_workflow_root_default_when_envs_empty
- tests/properties/test_tenancy.py::TestP6WorkflowRootContainment::test_workflow_root_is_contained

The suite comparison is a set, not a count: the failing node-id set after this
feature equals exactly these four. A fifth failure, or the disappearance of one
of these while a new one appears, is attributable to this feature.
