# Requirements Document

## Introduction

`shared-scope-query-routing` (SDD Phase 79) froze Default_Tenant output
byte-for-byte through its Requirement 6 criteria 2 and 3. The freeze was the
correct instrument for a 1,635-insertion read-path refactor: it gave a reviewer
who could not read all of it a yes-or-no answer to "did you break the production
default path". It is a bad permanent fixture, and it now blocks three
improvements, one of which preserves a document total that is known to be wrong.

This feature retires the freeze as a **standing rule** while keeping the capture
machinery available as a **tool**. It does so in an order that never leaves the
Default_Tenant read path ungated: the replacement instrument is built and shown
to work before either frozen criterion is relaxed.

The reasoning, the eight caveats, and the ten exit criteria behind this feature
are settled in `sdd_framework/workflows/phase80_default_tenant_freeze_retirement.md`,
which is the point of record. This document translates that record into testable
acceptance criteria and does not reopen it.

Three facts establish the shape of the work. The Nightly_Wrapper drives the
Node_Harness (`run_benchmark_nightly.sh` line 54). No Python benchmark harness
exists — `mcp_server_python/scripts/` holds only that wrapper. The Node_Harness
contains zero occurrences of `tenant` and has no tenant concept. The nightly
benchmark therefore exercises none of the Python read path Phase 79 rewrote and
cannot express a tenant-scoped query even in principle. Building the
Benchmark_Harness is construction, not confirmation, and it is the bulk of this
work.

Two problems are open and carry requirements of their own. Three regression
thresholds are declared across two files, and an acceptance criterion cannot be
satisfied by citing a configuration that disagrees with its consumer.
Separately, the Quality_Metrics_Log holds Node_Harness runs, so a Python
Benchmark_Run_Record that scores the shared corpus differently would read as a
step change against a trailing median for reasons unrelated to quality.

This feature changes no runtime behaviour. It changes which evidence is required
to change runtime behaviour.

## Glossary

- **Benchmark_Harness**: The new `mcp_server_python/scripts/run_benchmark.py`.
  Loads the Ground_Truth_Corpus, invokes Python Tool_Closures, computes quality
  metrics, and emits a Benchmark_Run_Record.
- **Node_Harness**: The existing `mcp_server_node/scripts/run_benchmark.js`,
  dated 2026-03-19, which predates the Python port and has no tenant concept.
- **Nightly_Wrapper**: `mcp_server_python/scripts/run_benchmark_nightly.sh`.
  Invokes a benchmark command, normalises its freshest result file into one
  Quality_Metrics_Log line, rotates snapshots, and runs the Regression_Check.
- **Benchmark_Command_Seam**: The `MCP_BENCHMARK_CMD` environment variable read
  at `run_benchmark_nightly.sh` line 54, whose default is the Node_Harness. The
  seam by which a different harness is substituted without editing the
  Nightly_Wrapper.
- **Ground_Truth_Corpus**: `mcp_server_node/test/benchmark/ground_truth.json`.
  Holds `version`, `created`, `description`, `metrics_config`, and `categories`.
  `categories` maps each of the six Benchmark_Category names to a list of
  Benchmark_Cases.
- **Benchmark_Category**: One of `code_structure`, `semantic_search`,
  `architecture`, `ee2_compliance`, `operational`, `cross_language`.
- **Benchmark_Case**: One corpus entry, an object carrying `id`, `question`,
  `tool`, `tool_args`, `expected_results`, `expected_min_results`, `category`,
  and `notes`.
- **Corpus_Baseline_Set**: The 60 Benchmark_Cases present in the
  Ground_Truth_Corpus at corpus `version` `1.0.0`, ten in each
  Benchmark_Category, exercising 13 distinct tool names.
- **Tenant_Scoped_Case**: A Benchmark_Case whose `tool_args` carries a
  `tenant_id` key naming a Prefixed_Tenant.
- **Tool_Closure**: The `async def` function a Python tool module registers
  under a `@mcp.tool(...)` decorator inside its module-level `register(mcp,
  data, *, catalog=...)` function. The Tool_Closure is where `tenant_id` enters
  and where `run_tenant_scoped(tenant_id, catalog, lambda: _tool_*(...))` binds
  the tenancy ContextVar.
- **Tool_Internal**: A module-level `_tool_*` coroutine a Tool_Closure calls
  inside its `run_tenant_scoped` lambda. A Tool_Internal accepts no `tenant_id`
  and binds no ContextVar.
- **Registration_Shim**: A stand-in for a `FastMCP` server that the
  Benchmark_Harness passes to each tool module's `register` function in order to
  collect the Tool_Closures the module registers, keyed by registered tool name.
- **Benchmark_Run_Record**: The JSON document the Benchmark_Harness writes for
  one benchmark run, carrying `timestamp`, `overall`, `categories`, and the
  per-case detail. The Nightly_Wrapper compacts one Benchmark_Run_Record into
  one Quality_Metrics_Log line.
- **Quality_Metric**: One of `precision_at_k`, `recall_at_k`, `mrr`,
  `coverage`, `latency_p50_ms`, `latency_p95_ms`.
- **Gated_Metric**: One of `mrr`, `precision_at_k`, `coverage` — the three
  Quality_Metrics the Regression_Check evaluates.
- **Quality_Metrics_Log**: `sdd_framework/execution_state/quality_metrics.jsonl`.
  One JSON line per benchmark run. Read by `get_quality_metrics`.
- **Regression_Check**: The Nightly_Wrapper step that compares each
  Benchmark_Category's Gated_Metrics in the newest Quality_Metrics_Log line
  against that category's median over the Median_Window of preceding lines and
  emits a structured ERROR line per exceedance.
- **Median_Window**: The count of preceding Quality_Metrics_Log lines the
  Regression_Check takes its median over, read from
  `MCP_BENCHMARK_MEDIAN_WINDOW`.
- **Governing_Threshold**: The single percentage drop that, when exceeded by a
  Gated_Metric, fails a proposed change to Default_Tenant output.
- **Byte_Equivalence**: Exact character-for-character equality of two rendered
  responses outside an earned volatility mask. The instrument Phase 79
  Requirement 6 criteria 2, 3, and 5 impose.
- **Structural_Equivalence**: The relation defined in Requirement 9 of this
  document, which constrains the set of Physical_Collections listed, the
  per-collection document count, and the per-check verdict, and leaves rendering
  free.
- **Check_Verdict**: One of pass, fail, or skip, as reported for one named check
  by the Integrity_Checker or the Health_Reporter.
- **Query_Tool**: Any tool named in Phase 79 Requirement 2 criterion 6, plus
  `find_similar_code`, `get_job_details`, and `list_job_scripts` — the set whose
  responses Phase 79 Requirement 6 criterion 2 freezes.
- **Status_Reporter**: The `get_knowledge_base_status` rendering path.
- **Integrity_Checker**: The `check_knowledge_integrity` rendering path.
- **Health_Reporter**: The `mcp_health_check` rendering path.
- **Baseline_Capture_Mechanism**: `mcp_server_python/tests/baselines/` in full —
  `capture.py`, `recorded_backend/*.json`, `pre_change/*`, and the earned-mask
  helpers `derive_masks`, `verify_masks_earned`, and `matches_baseline`.
- **Reference_Revision**: The named git revision from which a comparison
  baseline was recorded. Phase 79's Reference_Revision is
  `4eb422915bdf2728466e6ff5df449b7a539cdede`.
- **Retirement_Record**: A single ASCII markdown document under `docs/reports/`
  created by this feature, holding the Consumer_Audit findings, the threshold
  reconciliation decision, the changeover decision, and the named new
  Reference_Revision.
- **Consumer_Audit**: The enumeration of code that pattern-matches on rendered
  MCP response text, partitioned into in-repo consumers and out-of-repo
  consumers.
- **Follow_Up_Sequence**: The ordered list of three Default_Tenant convergence
  changes this feature unblocks: first the `mdc-content-sha-registry`
  over-count in the `gw` status total, second the Default_Tenant
  Integrity_Checker sampler scoping, third cross-member score fusion.
- **Default_Tenant**: The `gw` tenant, whose `index_prefix` and `label_prefix`
  are both empty.
- **Prefixed_Tenant**: Any tenant in the Tenant_Catalog whose `index_prefix` is
  non-empty, for example `gw_v17`.
- **Tenant_Catalog**: `mcp_server_python/src/config/tenants.yaml`.
- **Logical_Collection**, **Physical_Collection**, **Hybrid_Domain**,
  **Resolved_Collection_Set**, **Read_Router**: as defined in
  `.kiro/specs/shared-scope-query-routing/requirements.md`.

## Requirements

### Requirement 1: The Python benchmark harness

**User Story:** As an operator who needs a gate on the Python read path, I want a
benchmark harness that drives the Python tool layer the way a consumer does, so
that a retrieval regression in that layer is detectable at all.

#### Acceptance Criteria

1. THE Benchmark_Harness SHALL exist at
   `mcp_server_python/scripts/run_benchmark.py`.
2. WHEN the Benchmark_Harness prepares to execute Benchmark_Cases, THE
   Benchmark_Harness SHALL obtain each invocable target by passing a
   Registration_Shim to the `register` function of each tool module that owns a
   tool named by a Benchmark_Case, and SHALL collect from that Registration_Shim
   the Tool_Closure registered under each `@mcp.tool(name=...)` value.
3. WHEN the Benchmark_Harness executes one Benchmark_Case, THE
   Benchmark_Harness SHALL invoke the Tool_Closure collected for that case's
   `tool` value, passing that case's `tool_args` as keyword arguments.
4. THE Benchmark_Harness SHALL contain no call to a Tool_Internal and no call to
   `run_tenant_scoped`, so that every Benchmark_Case traverses the tenancy
   ContextVar binding a consumer traverses.
5. WHEN the Benchmark_Harness receives the return value of a Tool_Closure, THE
   Benchmark_Harness SHALL treat that return value as a single response text
   without unwrapping a `content` list, because a Python Tool_Closure returns
   `str` directly.
6. IF a Benchmark_Case names a tool for which the Registration_Shim collected no
   Tool_Closure, THEN THE Benchmark_Harness SHALL record that case with a
   `precision` of 0, a `recall` of 0, an `mrr` of 0, a `covered` value of false,
   and an `error` field naming the absent tool, and SHALL execute the remaining
   Benchmark_Cases.
7. WHERE the `--dry-run` option is supplied, THE Benchmark_Harness SHALL
   validate the Ground_Truth_Corpus, print the per-category case plan and the
   set of required tool names, invoke no Tool_Closure, and write no
   Benchmark_Run_Record.
8. WHERE the `--category` option is supplied with a Benchmark_Category name,
   THE Benchmark_Harness SHALL execute only the Benchmark_Cases carrying that
   `category` value.
9. IF the `--category` option is supplied with a value that is not a
   Benchmark_Category name, THEN THE Benchmark_Harness SHALL emit a message
   naming the six available Benchmark_Category names and SHALL exit with status
   1.
10. THE Benchmark_Harness SHALL emit only ASCII characters on its standard
    output and standard error streams.

### Requirement 2: Corpus reuse and tenant-scoped coverage

**User Story:** As a reviewer, I want the corpus reused rather than rewritten and
extended with tenant-scoped cases, so that the harness gates both the default
path the freeze protects and the prefixed-tenant path the follow-ups change.

#### Acceptance Criteria

1. THE Benchmark_Harness SHALL read its cases from the Ground_Truth_Corpus at
   `mcp_server_node/test/benchmark/ground_truth.json` and SHALL define no
   second corpus file.
2. THE Ground_Truth_Corpus SHALL contain, after this feature, every
   Benchmark_Case of the Corpus_Baseline_Set with its `id`, `question`, `tool`,
   `tool_args`, `expected_results`, `expected_min_results`, `category`, and
   `notes` values unchanged.
3. THE Ground_Truth_Corpus SHALL express every Tenant_Scoped_Case using the
   Benchmark_Case field set named in the Glossary, carrying the tenant selection
   as a `tenant_id` key inside `tool_args`, and SHALL introduce no additional
   Benchmark_Case field.
4. THE `tenant_id` value of every Tenant_Scoped_Case SHALL equal the
   `tenant_id` of a Prefixed_Tenant present in the Tenant_Catalog.
5. THE Ground_Truth_Corpus SHALL contain at least one Tenant_Scoped_Case in each
   of the six Benchmark_Categories.
6. THE Ground_Truth_Corpus SHALL contain at least one Tenant_Scoped_Case naming
   the tool `get_knowledge_base_status`, at least one naming the tool
   `check_knowledge_integrity`, and at least one naming a Query_Tool whose read
   of a Hybrid_Domain Logical_Collection resolves to a Resolved_Collection_Set of
   more than one member, so that each of the three Follow_Up_Sequence changes has
   a case that exercises it.
7. WHEN the Benchmark_Harness executes a Tenant_Scoped_Case, THE
   Benchmark_Harness SHALL pass that case's `tenant_id` value to the
   Tool_Closure as a keyword argument rather than setting the tenancy ContextVar
   directly.
8. WHEN the Benchmark_Harness aggregates a Benchmark_Category, THE
   Benchmark_Harness SHALL report the Quality_Metrics of the Default_Tenant
   cases of that category separately from the Quality_Metrics of the
   Tenant_Scoped_Cases of that category, so that a Default_Tenant regression and
   a Prefixed_Tenant regression are distinguishable.
9. WHEN the Benchmark_Harness writes the `categories` object of a
   Benchmark_Run_Record, THE Benchmark_Harness SHALL use the six
   Benchmark_Category names as its keys and SHALL compute each value from the
   Default_Tenant cases of that category, so that the `categories` object
   remains comparable with the Node_Harness records already in the
   Quality_Metrics_Log.

### Requirement 3: Hermetic operation and absent-backend behaviour

**User Story:** As a developer with no AWS credentials, I want the harness and
its tests to run without a live backend, so that the gate is verifiable in the
environment where the change is written.

#### Acceptance Criteria

1. THE Benchmark_Harness SHALL accept an injected data-access facade in place of
   the facade it constructs by default, so that a test drives the full scoring
   path against recorded adapter responses.
2. WHEN the Benchmark_Harness is invoked with an injected data-access facade,
   THE Benchmark_Harness SHALL issue no OpenSearch request, no Neptune request,
   no Bedrock request, and no ChromaDB or Neo4j request.
3. IF invoking a Tool_Closure raises an exception, THEN THE Benchmark_Harness
   SHALL record that Benchmark_Case with a `precision` of 0, a `recall` of 0, an
   `mrr` of 0, a `covered` value of false, an `error` field carrying the
   exception message, and the elapsed time in `latency_ms`, and SHALL execute
   the remaining Benchmark_Cases.
4. IF every Benchmark_Case records an `error` field, THEN THE
   Benchmark_Harness SHALL write a Benchmark_Run_Record whose `overall` object
   reports a `coverage` of 0 and SHALL exit with status 1, so that a wholly
   unreachable backend is distinguishable from a scored run.
5. WHEN the Benchmark_Harness writes a Benchmark_Run_Record, THE
   Benchmark_Harness SHALL write it under the directory named by the
   `MCP_BENCHMARK_RESULTS_DIR` environment variable when that variable holds a
   non-empty value.
6. THE Benchmark_Harness SHALL write no file into a directory other than the
   Benchmark_Run_Record output directory.
7. THE automated tests this feature adds SHALL pass with no AWS credential
   present in the environment and with no MCP server reachable.

### Requirement 4: Metric computation and record shape

**User Story:** As a consumer of `get_quality_metrics`, I want the Python
harness to emit the record shape the existing reader and wrapper already
contract for, so that neither has to change.

#### Acceptance Criteria

1. WHEN the Benchmark_Harness scores one Benchmark_Case, THE Benchmark_Harness
   SHALL count an entry of that case's `expected_results` as matched when that
   entry occurs as a substring of the response text under a case-insensitive
   comparison.
2. WHEN the Benchmark_Harness aggregates a set of Benchmark_Cases, THE
   Benchmark_Harness SHALL compute `precision_at_k` as the mean over those cases
   of the matched-entry count divided by the lesser of the `k` value in
   `metrics_config` and the `expected_results` length, each per-case value
   constrained to the range 0 to 1 inclusive.
3. WHEN the Benchmark_Harness aggregates a set of Benchmark_Cases, THE
   Benchmark_Harness SHALL compute `recall_at_k` as the mean over those cases of
   the matched-entry count divided by the `expected_results` length, each
   per-case value constrained to the range 0 to 1 inclusive.
4. WHEN the Benchmark_Harness aggregates a set of Benchmark_Cases, THE
   Benchmark_Harness SHALL compute `coverage` as the count of those cases whose
   matched-entry count is 1 or greater divided by the count of those cases.
5. WHEN the Benchmark_Harness scores one Benchmark_Case, THE Benchmark_Harness
   SHALL compute `mrr` as the reciprocal of the 1-based position of the first
   response text containing a matched entry, and 0 when no response text
   contains a matched entry.
6. IF the `expected_results` list of a Benchmark_Case is empty, THEN THE
   Benchmark_Harness SHALL record a `precision` of 0 and a `recall` of 0 for
   that case.
7. THE Benchmark_Harness SHALL round every reported `precision_at_k`,
   `recall_at_k`, `mrr`, and `coverage` value to 4 decimal places, and SHALL
   report `latency_p50_ms` and `latency_p95_ms` as integers.
8. THE Benchmark_Run_Record SHALL carry a `timestamp` field, an `overall`
   object, and a `categories` object, and each of `overall` and every value of
   `categories` SHALL carry the keys `precision_at_k`, `recall_at_k`, `mrr`,
   `coverage`, `latency_p50_ms`, and `latency_p95_ms`.
9. THE Benchmark_Run_Record SHALL carry a `harness` field whose value identifies
   the Benchmark_Harness, so that the provenance of a Quality_Metrics_Log line
   is recoverable after the changeover.
10. THE Benchmark_Run_Record SHALL carry a `corpus_version` field equal to the
    `version` field of the Ground_Truth_Corpus.

### Requirement 5: Score comparability across the harness changeover

**User Story:** As an operator reading the Regression_Check output, I want the
first Python run compared against a meaningful median, so that a harness
changeover does not present itself as a quality regression.

#### Acceptance Criteria

1. THE Retirement_Record SHALL state, for each of `precision_at_k`,
   `recall_at_k`, `coverage`, and `mrr`, whether the Benchmark_Harness computes
   that Quality_Metric by the same formula as the Node_Harness, and SHALL name
   each formula difference it finds.
2. THE Retirement_Record SHALL state that every one of the 147 scope
   observations across the 21 Node_Harness runs present in the
   Quality_Metrics_Log reports an `mrr` value equal to its `coverage` value, and
   SHALL state that a Python Tool_Closure returns exactly one response text and
   therefore yields a per-case `mrr` of either 0 or 1, so that equality of `mrr`
   and `coverage` is a property of both harnesses rather than a coincidence of
   one.
3. WHEN a Benchmark_Harness run and a Node_Harness run over the
   Corpus_Baseline_Set are compared, THE Retirement_Record SHALL either record
   that no Gated_Metric differs by more than the Governing_Threshold, or record
   that comparability was not demonstrated together with the reason.
4. IF the Retirement_Record records that comparability was not demonstrated,
   THEN the Node_Harness lines of the Quality_Metrics_Log SHALL be moved to the
   Nightly_Wrapper archive directory before the first Benchmark_Harness line is
   appended, and THE Retirement_Record SHALL name the archive file and state
   that the Median_Window restarts.
5. WHILE the Quality_Metrics_Log holds fewer than 2 lines, THE Regression_Check
   SHALL report an insufficient-history status and SHALL emit no regression
   ERROR line.
6. THE Retirement_Record SHALL name the decision of criterion 3 or criterion 4
   as a dated entry, so that a later reader can tell which median window a given
   Quality_Metrics_Log line belongs to.

### Requirement 6: Threshold reconciliation

**User Story:** As a reviewer applying the benchmark gate, I want one number
that decides pass or fail, so that a criterion cannot be satisfied by citing a
configuration that disagrees with its consumer.

#### Acceptance Criteria

1. THE Retirement_Record SHALL name every regression threshold declared before
   this feature, comprising the `regression_threshold_pct` value 5 and the
   `critical_threshold_pct` value 15 in the Ground_Truth_Corpus
   `metrics_config`, and the `MCP_BENCHMARK_REGRESSION_PCT` default 10 in the
   Nightly_Wrapper, and SHALL state the comparison basis each governs.
2. THE Retirement_Record SHALL name exactly one Governing_Threshold as a
   percentage, and SHALL name the comparison basis over which that percentage is
   evaluated.
3. THE `MCP_BENCHMARK_REGRESSION_PCT` default in the Nightly_Wrapper SHALL equal
   the Governing_Threshold named by criterion 2.
4. THE Retirement_Record SHALL name the Median_Window count and the
   `minimum_coverage_pct` floor that apply alongside the Governing_Threshold.
5. WHERE a proposed change alters Default_Tenant output, THE Governing_Threshold
   SHALL be the single percentage against which that change's Gated_Metric
   drops are judged.
6. THE Retirement_Record SHALL state whether the Ground_Truth_Corpus
   `metrics_config` values remain in force for the Node_Harness, so that
   reconciliation does not silently alter the Node_Harness gate.

### Requirement 7: Nightly wrapper integration

**User Story:** As an operator, I want the Python harness to slot in behind the
existing wrapper, so that the append, rotation, and alerting logic is reused
rather than reimplemented.

#### Acceptance Criteria

1. WHEN the Nightly_Wrapper is invoked with `MCP_BENCHMARK_CMD` naming the
   Benchmark_Harness, THE Nightly_Wrapper SHALL append exactly one
   Quality_Metrics_Log line derived from the Benchmark_Run_Record the
   Benchmark_Harness wrote.
2. THE Nightly_Wrapper SHALL retain its snapshot rotation behaviour, its
   per-category Regression_Check over the Gated_Metrics against the trailing
   Median_Window median, and its structured ERROR emission, unchanged by this
   feature.
3. THE Nightly_Wrapper SHALL differ from its pre-change content only in the
   default value of `MCP_BENCHMARK_REGRESSION_PCT` and in comment text.
4. WHEN `get_quality_metrics` reads a Quality_Metrics_Log whose newest line
   derives from a Benchmark_Run_Record, THE `get_quality_metrics` tool SHALL
   render the overall block and the per-category block without reporting a
   missing field.
5. WHEN `get_quality_metrics` is invoked with `compare` set to true over a
   Quality_Metrics_Log whose two newest lines both derive from
   Benchmark_Run_Records, THE `get_quality_metrics` tool SHALL render a
   regression comparison between those two lines.

### Requirement 8: Gate continuity

**User Story:** As a reviewer, I want the replacement gate proven before the
existing one is removed, so that the Default_Tenant read path is never
ungated.

#### Acceptance Criteria

1. WHILE the Benchmark_Harness does not exist, THE Byte_Equivalence criteria of
   Phase 79 Requirement 6 criteria 2 and 3 SHALL remain in force unmodified.
2. THE supersession of Phase 79 Requirement 6 criterion 3 required by
   Requirement 10 of this document SHALL be accompanied, in the same change,
   by a Structural_Equivalence criterion and by the tests that enforce it, so
   that no revision exists in which criterion 3 is relaxed and no replacement
   check is present.
3. THE supersession of Phase 79 Requirement 6 criterion 2 required by
   Requirement 11 of this document SHALL be accompanied, in the same change, by
   both the structural check and the benchmark comparison that criterion
   requires, so that no revision exists in which criterion 2 is relaxed and
   either replacement is absent.
4. THE Retirement_Record SHALL name the two conditions that prevented the
   Phase 79 freeze from being retired earlier, comprising the absence of a
   Python benchmark harness and the absence of live-invocation access, and SHALL
   state for each whether this feature clears it.
5. THE Retirement_Record SHALL state that the three live-invocation entries of
   the Phase 79 Verification_Record are unmet and operator-gated, and SHALL name
   the hermetic tests that stand in for each, so that retirement does not
   implicitly claim live verification that has not occurred.
6. WHEN the automated test suite runs after the supersessions of Requirements 10
   and 11 land, THE test suite SHALL report a count of failures no greater than
   the count of pre-existing failures named in Requirement 15 criterion 4.

### Requirement 9: The structural equivalence relation

**User Story:** As a reviewer, I want structural equivalence defined as a
checkable relation, so that it does not degrade into permitting any change at
all.

#### Acceptance Criteria

1. THE Structural_Equivalence relation SHALL hold between two rendered
   responses when, and only when, all three of the following hold: the set of
   Physical_Collection names each response lists is equal; the document count
   each response reports for each listed Physical_Collection is equal; and the
   Check_Verdict each response reports for each named check is equal.
2. THE Structural_Equivalence relation SHALL be insensitive to line order,
   label text, field wording, whitespace, and the presence of a line that names
   no Physical_Collection, no document count, and no Check_Verdict.
3. WHEN two rendered responses list unequal sets of Physical_Collection names,
   THE Structural_Equivalence relation SHALL fail and the failure message SHALL
   name each Physical_Collection present in one response and absent from the
   other.
4. WHEN two rendered responses report unequal document counts for a
   Physical_Collection listed by both, THE Structural_Equivalence relation SHALL
   fail and the failure message SHALL name that Physical_Collection and both
   counts.
5. WHEN two rendered responses report unequal Check_Verdicts for a check named
   by both, THE Structural_Equivalence relation SHALL fail and the failure
   message SHALL name that check and both Check_Verdicts.
6. THE component that evaluates the Structural_Equivalence relation SHALL derive
   the Physical_Collection names, the document counts, and the Check_Verdicts
   from the rendered response text, so that the relation is evaluable against a
   recorded baseline as well as against a live render.

### Requirement 10: Retirement of the reporting freeze

**User Story:** As an operator reading `gw` diagnostics, I want the reporting
freeze replaced by structural equivalence, so that the registry over-count can
be corrected and `gw` integrity findings can be scoped.

#### Acceptance Criteria

1. THE `.kiro/specs/shared-scope-query-routing/requirements.md` document SHALL
   record Requirement 6 criterion 3 as superseded, SHALL name this feature as
   the superseding authority, and SHALL state that Structural_Equivalence as
   defined in Requirement 9 of this document replaces Byte_Equivalence for the
   Status_Reporter, the Integrity_Checker, and the Health_Reporter.
2. THE superseding criterion recorded in
   `.kiro/specs/shared-scope-query-routing/requirements.md` SHALL carry the
   three conditions of Requirement 9 criterion 1 as its own text rather than by
   reference alone.
3. THE `.kiro/specs/shared-scope-query-routing/requirements.md` document SHALL
   state Requirement 10 criterion 5 in the form that requires the
   no-`tenant_id` Integrity_Checker sample to be drawn from the union of the
   Default_Tenant's Resolved_Collection_Sets across the five
   Logical_Collections, and SHALL replace its 2026-08-19 amendment note with a
   note that names this feature as the resolution of the structural conflict.
4. THE `.kiro/specs/shared-scope-query-routing/design.md` document SHALL state
   Property 8 over any Tenant rather than over any Tenant whose `index_prefix`
   is non-empty, and SHALL replace its 2026-08-19 amendment note with a note
   that names this feature as the resolution.
5. THE `mcp_server_python/tests/unit/test_default_tenant_byte_equivalence.py`
   test module SHALL compare each Status_Reporter, Integrity_Checker, and
   Health_Reporter scenario against its recorded baseline under the
   Structural_Equivalence relation rather than under Byte_Equivalence.
6. THE `mcp_server_python/tests/unit/test_default_tenant_byte_equivalence.py`
   test module SHALL retain a test asserting that a scenario covering each of
   `get_knowledge_base_status`, `check_knowledge_integrity`, and
   `mcp_health_check` is present, so that relaxing the comparison does not
   shrink coverage.
7. WHEN a Follow_Up_Sequence change alters the set of Physical_Collections the
   Status_Reporter lists for the Default_Tenant, THE
   `mcp_server_python/tests/baselines/` recorded baseline for the
   `get_knowledge_base_status` scenario SHALL be re-recorded to the corrected
   set in that same change, and THE Retirement_Record SHALL name the altered
   Physical_Collection, so that the registry over-count correction is
   expressible under the Structural_Equivalence relation rather than blocked by
   it.

### Requirement 11: Retirement of the query-result freeze

**User Story:** As a reviewer of a change to retrieval, I want a paired
structural and benchmark gate, so that neither a dropped collection nor a
degraded ranking passes unnoticed.

#### Acceptance Criteria

1. THE `.kiro/specs/shared-scope-query-routing/requirements.md` document SHALL
   record Requirement 6 criterion 2 as superseded, SHALL name this feature as
   the superseding authority, and SHALL require both a structural check and a
   benchmark comparison in place of Byte_Equivalence.
2. THE structural check required by criterion 1 SHALL require that a Query_Tool
   invoked without a `tenant_id` addresses the same set of Physical_Collections
   as before the proposed change, and that every returned hit carries a
   non-empty `physical_collection` value.
3. THE benchmark comparison required by criterion 1 SHALL require that no
   Gated_Metric of any Benchmark_Category, and no Gated_Metric of the `overall`
   object, drops below its trailing Median_Window median by more than the
   Governing_Threshold.
4. THE superseding criterion SHALL state that the benchmark comparison measures
   retrieval quality rather than correctness, and SHALL state that the
   structural check of criterion 2 is required in addition to, rather than in
   place of, the benchmark comparison.
5. IF a proposed change to Default_Tenant Query_Tool output passes the benchmark
   comparison and fails the structural check of criterion 2, THEN that change
   SHALL be treated as failing the gate.
6. THE `mcp_server_python/tests/unit/test_default_tenant_byte_equivalence.py`
   test module SHALL assert, for each Query_Tool scenario, that the set of
   Physical_Collections addressed under the Default_Tenant is unchanged and that
   every returned hit carries a non-empty `physical_collection` value.

### Requirement 12: Consumer audit

**User Story:** As a maintainer of anything that parses MCP response text, I
want the consumers enumerated before formatting is relaxed, so that a
formatting change is not a silent break.

#### Acceptance Criteria

1. THE Retirement_Record SHALL name every file within this repository that
   pattern-matches on rendered MCP response text, and SHALL name for each the
   response element that file matches on.
2. THE Consumer_Audit recorded under criterion 1 SHALL include
   `mcp_server_python/tests/parity/parity_runner.py`,
   `mcp_server_python/tests/parity/test_self_parity.py`,
   `mcp_server_python/tests/unit/test_tenant_resolver.py`,
   `mcp_server_python/tests/unit/test_config_file_writes.py`,
   `mcp_server_python/tests/unit/test_tenant_tool_exposure.py`, and
   `mcp_server_python/tests/unit/test_attribution_branch.py`.
3. THE Retirement_Record SHALL state that consumers outside this repository,
   comprising Kiro sessions, CI pipelines, and Tier B and Tier C agent
   wrappers, cannot be enumerated from this repository, and SHALL record that
   limit as a bounded finding rather than as a completed enumeration.
4. THE Retirement_Record SHALL state that the `**Collection:**` field rendered
   by `src/tools/semantic_search.py` carries the Logical_Collection name, and
   SHALL state that Phase 79 added `physical_collection` as a new result key
   rather than repurposing `collection` in order to leave that rendered field
   unmoved.
5. WHERE the Consumer_Audit identifies a consumer that matches on a response
   element a Follow_Up_Sequence change would alter, THE Retirement_Record SHALL
   name that consumer alongside the Follow_Up_Sequence entry that would alter
   it.

### Requirement 13: Retention of the capture mechanism

**User Story:** As the author of the next high-surface refactor, I want the
capture machinery kept and its status stated, so that the instrument that made
Phase 79 safe remains available.

#### Acceptance Criteria

1. THE Baseline_Capture_Mechanism SHALL remain present in the repository after
   this feature, comprising `capture.py`, every `recorded_backend/*.json`
   scenario file, and the `derive_masks`, `verify_masks_earned`, and
   `matches_baseline` helpers.
2. THE `mcp_server_python/tests/baselines/README.md` document SHALL state that
   the Baseline_Capture_Mechanism is an instrument available to a high-surface
   refactor rather than a standing gate, and SHALL name this feature as the
   authority for that status.
3. THE `mcp_server_python/tests/baselines/README.md` document SHALL retain the
   Phase 79 Reference_Revision `4eb422915bdf2728466e6ff5df449b7a539cdede` as
   the provenance of the `pre_change/` captures.
4. THE `mcp_server_python/tests/unit/test_default_tenant_byte_equivalence.py`
   test module SHALL retain the tests that reject a mask over two identical
   runs and a mask broader than the volatile span, so that the earned-mask
   guarantee survives the relaxation.
5. THE Retirement_Record SHALL name the git revision from which any baseline
   recorded by this feature was captured, and SHALL state that a baseline
   recorded before a Default_Tenant output change is void as a reference after
   that change.
6. THE `mcp_server_python/tests/baselines/README.md` document SHALL state that
   a Structural_Equivalence baseline is re-recordable from any revision, in
   contrast to a Byte_Equivalence baseline, which is valid only from the
   revision immediately preceding the change it gates.

### Requirement 14: Follow-up sequencing

**User Story:** As the author of one of the three unblocked changes, I want the
order fixed and the authority named, so that the three do not invalidate each
other's reference point.

#### Acceptance Criteria

1. THE Retirement_Record SHALL name the Follow_Up_Sequence in the order given
   in the Glossary, and SHALL state for each entry which of Phase 79
   Requirement 6 criterion 2 or criterion 3 governed it before this feature.
2. THE Retirement_Record SHALL state that the three Follow_Up_Sequence entries
   are performed one after another rather than concurrently, and SHALL state
   that a Default_Tenant output change voids every baseline recorded before it
   as a reference.
3. THE Retirement_Record SHALL state that each Follow_Up_Sequence entry cites
   `sdd_framework/workflows/phase80_default_tenant_freeze_retirement.md` as the
   authority for changing Default_Tenant output.
4. THE Retirement_Record SHALL state, for the third Follow_Up_Sequence entry,
   that the benchmark gate has been exercised by the first two entries before
   that entry relies on it.
5. THE Retirement_Record SHALL state that the `DEFAULT_SEMANTIC_COLLECTION`
   profile pinning is a fourth Phase 79 follow-up that this feature does not
   gate and that may proceed independently.

### Requirement 15: No runtime behaviour change

**User Story:** As an operator of the deployed runtime, I want this feature to
change only the evidence requirements, so that no redeploy and no behavioural
risk follows from it.

#### Acceptance Criteria

1. THE `mcp_server_python/src/` tree SHALL contain no import of the
   Benchmark_Harness.
2. THE Benchmark_Harness SHALL register no tool on the served `FastMCP`
   instance, so that the tool count the server reports is unchanged.
3. THE files under `mcp_server_python/src/` that this feature modifies SHALL be
   limited to the modules that evaluate the Structural_Equivalence relation and
   the structural check of Requirement 11 criterion 2, and this feature SHALL
   modify no rendering path.

   **Amended 2026-08-26 -- one named exception, admitted after the first live
   run.** This criterion now additionally permits modification of exactly three
   files, for the sole purpose of removing four Neo4j-APOC call sites:
   `src/tools/semantic_search.py`, `src/tools/graph_rag.py`, and
   `src/graphrag/ggsr_traversal.py`. No other `src/` file may change, and the
   no-rendering-path clause above is unaffected -- the edit replaces a `WHERE`
   predicate, touching no rendered output.

   Reason. `apoc.convert.toList` and `apoc.text.join` are functions of the APOC
   *server plugin*, which is a Neo4j add-on. Amazon Neptune has no plugin
   mechanism and no APOC, so every query carrying them returned
   `400 Unknown function: 'toList'` against the platform this server actually
   runs on. The predicate becomes `toLower(toString(n.name)) CONTAINS
   toLower($x)`, verified against live Neptune at 0.04s before the edit;
   `toString` is a built-in and preserves the multi-valued tolerance APOC was
   providing, since a scalar stringifies to itself and a list to its bracketed
   rendering, either of which the `CONTAINS` test still matches.

   Why admitted here rather than deferred. The defect is pre-existing, with
   identical APOC reference counts at this feature's base revision `c5b2ea7`, at
   the branch merge-base `48a3d987`, and at HEAD, introduced by `0dac1e0`
   (SDD Phases 60/61). Deferring it to its own change was the initial
   recommendation. The first live benchmark run overrode that: the APOC failure
   is the direct cause of five zero-scoring Default_Tenant cases and of every
   GGSR enrichment failure in the run, so the replacement gate this feature
   exists to build cannot be calibrated while it stands. A gate that cannot be
   calibrated is not a gate, and Requirement 8 criterion 4 makes the working
   benchmark a precondition of the retirement rather than a follow-on to it.

   Enforcement. `tests/unit/test_no_runtime_change.py` compares the changed
   `src/` path set against a three-entry allowlist rather than asserting
   emptiness, so any other `src/` file still fails, and it additionally asserts
   that no `apoc.` call survives anywhere under `src/` -- the allowlist permits
   the edit, and that assertion pins that the edit achieved its purpose instead
   of merely touching the files.
4. WHEN the automated test suite runs after this feature, THE test suite SHALL
   report failures only among
   `test_environment.py::test_known_modules_covers_nine_tool_modules`,
   `test_error_analysis.py::test_extract_ci_error_signal_tool`,
   `test_workflow_info_tools.py::test_resolve_workflow_root_default_when_envs_empty`,
   and
   `test_tenancy.py::TestP6WorkflowRootContainment::test_workflow_root_is_contained`.
5. THE tests this feature adds SHALL carry only the `unit`, `property`, and
   `parity` pytest markers.
6. THE Python files this feature adds or modifies SHALL produce no `pycodestyle`
   finding.

   **Amended 2026-08-26 -- narrowed for the three APOC-remediation files only.**
   For the three files criterion 3 admits as a named exception
   (`src/tools/semantic_search.py`, `src/tools/graph_rag.py`,
   `src/graphrag/ggsr_traversal.py`), the standard is that this feature
   introduces **no new** `pycodestyle` finding, not that the files become
   finding-free. Every file this feature *adds*, and every other file it
   modifies, remains held to the original zero-finding standard.

   Reason: a direct conflict between this criterion and criterion 3 as amended.
   These three files carried `pycodestyle` findings before this feature — eight
   in total, on lines unrelated to the APOC predicates — and criterion 3's
   amendment permits editing them "for the sole purpose of removing four
   Neo4j-APOC call sites". Making them finding-free would require editing
   unrelated lines, which exceeds that stated purpose; leaving them non-compliant
   would violate this criterion as originally written. Narrowing this criterion
   resolves the conflict in the direction that keeps the diff scoped to the
   defect being fixed.

   Recorded because it is a reduction: the six surviving findings
   (`semantic_search.py:1142`; `graph_rag.py:469`, `:710`, `:715`, `:717`,
   `:718`) are pre-existing and are not repaired by this feature. The APOC edit
   did reduce the count from eight to six, because the two APOC predicates were
   themselves over-length lines (124 and 140 characters) and the replacement is
   shorter — so the net movement is an improvement, but it is incidental rather
   than an attempt at compliance.
7. THE Retirement_Record SHALL state that the Phase 79 configuration-level
   rollback, setting `MCP_COLLECTION_SCOPE_JSON` to a document classifying all
   five Logical_Collections as `tenant` with an empty hybrid-domain list,
   remains available without a code change and without a redeploy.
