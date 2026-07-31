# Implementation Plan — Kiro Web MCP Power (Plan A)

## Overview

This plan delivers the MDC_Power as a Power directory (`powers/mdc-mcp-rag/`), one CDK IAM stack
(`infrastructure/cdk/lib/mdc-kiro-web-access-stack.ts`), one runbook
(`docs/runbooks/kiro-web-mcp-power.md`), and Python tests under `mcp_server_python/tests/`.
The implementation languages are fixed by design section 1 and are **not** open questions:
**Python 3.12** for the adapter and its tests (`boto3 >= 1.34.0`, `hypothesis==6.152.2`), and
**TypeScript AWS CDK v2** with Jest for the IAM artifact. No task introduces another runtime,
SDK, or IaC tool.

The ordering is: freeze the invariants first (baseline commit, proxy byte-identity guard), then
the CDK artifact, then the adapter built up one concern at a time, then the manifest and steering
bundle, then the diagnostic action, then documentation, with each sandbox-testable property test
placed immediately after the code it validates. Everything that needs AWS credentials or a live
runtime, and everything that depends on server-side work this spec does not own, is isolated in
task group 14 and marked blocked.

**Hard constraints every task inherits:**

- Zero changes under `.kiro/specs/mcp-external-access-revised/` (R10 AC 2). No task reads it as
  an input, modifies it, or depends on Path B work.
- Zero modified lines in `tools/agentcore-kiro-proxy.py` (R2 AC 3, R7 AC 1) and zero changes to
  `.kiro/settings/mcp.json` (R7 AC 3, OQ-6).
- No task provisions Amazon Cognito, a JWT authorizer, a Token_Broker, a GitHub OIDC federated
  role, an AgentCore Gateway, or a Cedar policy (R10 AC 7, AC 8).
- No task changes an MCP tool signature, input schema, or `tenant_id` handling in
  `mcp_server_python/src/tools/` (R7 AC 6).

## Tasks

- [ ] 1. Freeze the invariants before any other code is written

  - [ ] 1.1 Record the baseline commit and the Proxy_Bridge digest
    - Create `powers/mdc-mcp-rag/baseline.json` holding: the baseline commit identifier on the
      implementation branch, the SHA-256 digest of `tools/agentcore-kiro-proxy.py`, the SHA-256
      digest of `.kiro/settings/mcp.json`, and the tool-registry baseline (`53` tools,
      `10` modules, `24` tenant-scoped) from design section 4 OQ-5.
    - This is verification item V-10 and must be the first thing done, because tasks 1.2 and the
      P4 guard both read it.
    - Note in the file that mirroring the baseline commit into design.md section 14.4 (V-10) is a
      spec-document edit owned by the design review, not by this task.
    - _Requirements: 7.8, 2.4, 7.2_

  - [ ] 1.2 Write the invariant guard script and wire it into CI
    - Create `scripts/ci/check-power-invariants.sh`, exiting non-zero on any violation:
      (a) `git diff --numstat <baseline> -- tools/agentcore-kiro-proxy.py` reports zero lines and
      the file's SHA-256 matches `baseline.json`; (b) a repository-wide content search for the
      Proxy_Bridge's distinguishing symbols (`parse_sse`, `generate_session_id`,
      `AgentCoreClient`) returns exactly one path; (c) `.kiro/settings/mcp.json` is byte-identical
      to its recorded digest; (d) `git diff --name-only <baseline>` contains zero paths under
      `.kiro/specs/mcp-external-access-revised/`; (e) the diff contains zero paths under
      `mcp_server_python/src/tools/`.
    - Register the script as a job in the existing CI workflow so the guard runs on every push.
    - This is property **P4** implemented as a CI check rather than a property test, per design
      section 13.2.
    - _Requirements: 2.3, 2.4, 7.1, 7.2, 7.3, 7.6, 10.2, 12.9_

- [ ] 2. IAM authorization artifact in CDK

  - [ ] 2.1 Create `MdcKiroWebAccessStack` and register it
    - New file `infrastructure/cdk/lib/mdc-kiro-web-access-stack.ts` exporting
      `MdcKiroWebAccessStack`, taking the runtime ARN as a **required stack prop** so the single
      literal lives only in `bin/cdk.ts`.
    - Exactly one construct: an `iam.ManagedPolicy` named `mdc-mcp-rag-kiro-web-invoke` with one
      `iam.PolicyStatement` — `effect: ALLOW`, action `bedrock-agentcore:InvokeAgentRuntime`,
      resource `arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN`.
      No `bedrock-agentcore:*`, no `ListAgentRuntimes`, no `logs:*`, no Neptune or OpenSearch action.
    - Export the policy ARN as a `CfnOutput` for the administrator attachment step.
    - Register the stack in `infrastructure/cdk/bin/cdk.ts` alongside the existing VPC, security,
      and data stacks. Add a code comment stating that this stack contains zero stateful
      resources, so `.kiro/steering/05-cdk-data-safety.md` Rule 1 (`RemovalPolicy.RETAIN`) is
      satisfied vacuously rather than by omission.
    - _Requirements: 4.1, 4.2, 3.13, 12.7, 12.8, 10.7_

  - [ ]* 2.2 Write the CDK assertion tests for the policy shape
    - **Property 7: IAM policy resource scoping**
    - **Validates: Requirements 4.1, 4.2, 12.7, 10.7**
    - New file `infrastructure/cdk/test/mdc-kiro-web-access-stack.test.ts` using
      `aws-cdk-lib/assertions.Template`: one `AWS::IAM::ManagedPolicy`; zero
      `AWS::Neptune::DBCluster`, `AWS::OpenSearchService::Domain`, `AWS::S3::Bucket`,
      `AWS::EFS::FileSystem`, `AWS::SecretsManager::Secret`, `AWS::KMS::Key`, and
      `AWS::Logs::LogGroup`; exactly one statement with `Effect: Allow`, one action string, one
      resource string; the resource split on `:` has no `*` in the account, region, or
      `runtime/<id>` segment, asserted segment by segment; and zero `AWS::Cognito::*`,
      `AWS::BedrockAgentCore::Gateway`, and `AWS::VerifiedPermissions::*` resources.

- [ ] 3. Adapter foundation — configuration validation, preflight, and the child process

  - [ ] 3.1 Create the adapter entry point and validate every external input
    - New file `powers/mdc-mcp-rag/bin/mdc_power_adapter.py`. Argument parser accepting
      `--proxy`, `--runtime-arn`, `--region`, and an optional profile, per design section 5.2.
    - Implement the section 8.6 validation table: `MDC_AGENTCORE_RUNTIME_ARN` against
      `^arn:aws:bedrock-agentcore:[a-z0-9-]{1,30}:\d{12}:runtime/[A-Za-z0-9_-]{1,128}$` with the
      region segment equal to `AWS_REGION` and no `*`; `AWS_REGION` against
      `^[a-z]{2}(-[a-z]+)+-\d$`; `MDC_AWS_PROFILE` against `^[A-Za-z0-9_.-]+$`, 1–64 chars;
      inbound JSON-RPC framing (`jsonrpc == "2.0"`, string/number `id`, object `params`,
      ≤ 10 MiB) returning `-32600`/`-32700` without forwarding.
    - Every failure fails activation with stage `power-activation` naming the configuration key
      and the rule that failed. No child is launched and no credential is resolved.
    - Do **not** validate `tenant_id` — it is opaque payload per design section 8.6.
    - _Requirements: 2.14, 1.10, 9.1, 9.16_

  - [ ] 3.2 Implement the dependency and interpreter preflight
    - `shutil.which("python3.12")` check; `import boto3` in the launching interpreter with a
      version comparison against `1.34.0`; on failure exactly **one**
      `pip install 'boto3>=1.34.0'` attempt, then one re-check.
    - Failures map to stage `proxy-launch` with category `dependency-provisioning` (import or
      version) or `interpreter-missing` (`python3.12` absent), and report the resolved boto3
      version on success.
    - _Requirements: 2.5, 2.6, 2.7, 9.16_

  - [ ]* 3.3 Write unit tests for configuration validation and preflight
    - Table-driven cases for each rule in the section 8.6 table, including a region mismatch
      between the ARN segment and `AWS_REGION`, a wildcard ARN, an over-length inbound message,
      and a malformed profile name; assert stage `power-activation` and the named key in each
      message.
    - _Requirements: 2.14, 1.10, 9.1, 9.16_

  - [ ] 3.4 Launch exactly one Proxy_Bridge child and run the three-thread process model
    - Spawn one child: `python3.12 <proxy> --runtime-id <arn> --region <region>`, adding
      `--verbose` only when `LOG_LEVEL=DEBUG`. Never more than one child per session.
    - Main thread: read newline-delimited JSON-RPC from own stdin, forward to child stdin.
      Reader thread: parse child stdout onto a correlation table keyed by JSON-RPC `id`.
      Stderr thread: redact, forward, and scan for the four known state patterns.
    - Parse the `Runtime_Session_Id` out of the child's startup banner and hold it for
      diagnostics and `_meta` only. The adapter must **never** generate, inject, or override a
      session identifier (DD-3). Update the held value when the child announces a regeneration.
    - No banner within 10 seconds → stage `proxy-launch`, category `process-exit` if the child
      already exited, otherwise the launch-failure category of section 8.3.
    - Contain zero SigV4 signing, zero SSE parsing, and zero retry logic for
      `InvokeAgentRuntime` — all of that stays in the frozen child.
    - _Requirements: 2.1, 2.2, 2.9, 2.13, 1.8_

  - [ ]* 3.5 Write unit tests for session-banner handling against the fake child
    - **Property 3: Runtime_Session_Id reuse**
    - **Validates: Requirements 2.9**
    - Build the reusable fake child described in design section 13.1 (banner with a synthetic
      `session=kiro-proxy-<hex>`, newline-delimited JSON in, canned responses out, the exact
      `-32603` shapes and stderr lines of sections 8.1 and 13.1) as a shared test fixture used by
      tasks 3.5, 4.6, 5.2, 5.3, 5.6, 7.2, 7.5, and 8.2.
    - Assert the held session value is byte-identical across a call sequence and updates exactly
      once when the fake emits a session-expired stderr line.

- [ ] 4. Credential lifecycle

  - [ ] 4.1 Resolve credentials and enforce the lifetime bounds
    - Write the `[profile mdc-kiro-web]` stanza (`sso_start_url`, `sso_region`, `sso_account_id`,
      `sso_role_name`, `region`) to `~/.aws/config` if absent, creating `~/.aws` mode `0700` and
      the file mode `0600`. The stanza carries no credential material.
    - Resolve through `botocore.session.Session().get_credentials()` +
      `get_frozen_credentials()`. Require a session token and an expiration; require remaining
      lifetime ≥ 900 s and ≤ 43200 s. Do not call STS directly and do not implement the device
      flow.
    - Nothing resolved, no token, or no expiration → stage `credential-resolution`, category
      `credentials-absent`, message naming the literal refresh command
      `aws sso login --profile mdc-kiro-web` (or the env-var instruction when `AWS_PROFILE` is
      unset).
    - **Depends on amendment A-2** for the `$HOME/.aws` carve-out; if A-2 is rejected, the
      env-var fallback becomes primary and this task changes shape.
    - _Requirements: 3.1, 3.2, 3.3, 3.9, 3.7_

  - [ ] 4.2 Implement the 900-second pre-expiry warning and forced refresh
    - Before forwarding each `tools/call`, re-freeze the credentials and recompute remaining
      lifetime. Below 900 s: force a refresh by re-freezing, then emit **exactly one** warning per
      threshold crossing to stderr and to the non-fatal notice channel, naming the remaining
      seconds and the refresh command — and send the request anyway. Reset the one-shot counter
      when remaining lifetime rises back above the threshold.
    - _Requirements: 3.4, 3.5_

  - [ ] 4.3 Implement the credential redactor as the single output chokepoint
    - Every line the adapter writes to stdout or stderr — its own output, shaped errors,
      diagnostics, and forwarded child stderr — passes through a fixed-needle sliding-window scan
      over the held secret access key and session token, replacing any surviving substring of
      **9 or more** characters with `***REDACTED***`.
    - Route the task 3.4 stderr thread and every error-shaping path through this one function so
      the invariant holds by construction.
    - _Requirements: 3.6, 9.14_

  - [ ]* 4.4 Write the redaction property test
    - **Property 5: Credential redaction across every outcome**
    - **Validates: Requirements 3.6, 9.14**
    - New file `mcp_server_python/tests/properties/test_power_redaction_props.py`, Hypothesis,
      ≥ 100 iterations, tagged
      `# Feature: kiro-web-mcp-power, Property 5: no 9-or-more-character substring of the secret key or session token survives in any output`.
      Generate arbitrary secret keys and session tokens, inject them into every error shape,
      the diagnostic payload, and forwarded stderr lines, and assert no 9-character substring
      survives.

  - [ ] 4.5 Classify credential expiry, reshape the message, and resend once
    - Read the child's structured `data.exception` only — never string-match its raw text — and
      classify `ExpiredTokenException`, `ExpiredToken`, `InvalidClientTokenId`, and
      `UnrecognizedClientException` as `credential-expiry`; classify the child's
      `AWS credentials not available` message as `credentials-absent`.
    - Replace the error object with one naming stage `credential-resolution`, the category, the
      held credentials' expiration timestamp, and the refresh command. **Drop** `data.detail`
      so no botocore representation and no traceback reaches the session.
    - On `credential-expiry`, attempt one refresh; if it yields a later expiration, resend the
      same method and params **once** with the same JSON-RPC `id`. A second failure returns the
      shaped error with no further resend.
    - _Requirements: 3.10, 3.11, 3.12_

  - [ ]* 4.6 Write unit tests for expiry classification and messaging
    - **Property 6: Expiry classification and messaging**
    - **Validates: Requirements 3.10, 3.11, 3.12**
    - Drive each expiry error code through the fake child; assert stage
      `credential-resolution`, the literal refresh command present, no `Traceback`, no
      `botocore` or `ClientError` substring, and at most one resend.

- [ ] 5. Failure taxonomy, error shaping, and the timeout budgets

  - [ ] 5.1 Implement the seven stages, the categories, and the first-match rule
    - One module-level ordered rule table implementing design section 8.2 rules 1–7 exactly, with
      rule 7 (`tool-execution`) as the catch-all so the set is exhaustive.
    - Emit `stage` and `category` as **separate** fields; never write a category value into the
      stage field. Shape errors as the section 8.2 payload (`stage`, `category`, `tool`,
      `attempts`, `elapsedSeconds`, `recoverable`, `requiresReactivate`, `refreshCommand`).
    - Declare the botocore message needles (`EndpointConnectionError`,
      `Could not connect to the endpoint URL`, `ConnectTimeoutError`, `ConnectionRefusedError`,
      `SSLError`, `SSLCertVerificationError`, `CERTIFICATE_VERIFY_FAILED`, `ReadTimeoutError`) in
      **one** module constant. Separate `dns-resolution` from `tcp-connection` with the confirming
      `socket.getaddrinfo(host, 443)` probe.
    - Register `stream-idle-timeout` as **reserved and never emitted**, with an inline comment
      citing amendment A-3 and the blocking full-body read in the frozen child.
    - _Requirements: 9.1, 9.2, 9.4, 9.9, 9.10, 9.13, 9.16, 2.13, 2.15_

  - [ ]* 5.2 Write the stage-labelling exhaustiveness property test
    - **Property 11: Error stage labelling exhaustiveness**
    - **Validates: Requirements 9.9, 9.10, 9.11**
    - New file `mcp_server_python/tests/properties/test_power_stage_props.py`, Hypothesis,
      ≥ 100 iterations, tagged
      `# Feature: kiro-web-mcp-power, Property 11: every failure carries exactly one of the seven stages, no category value ever appears in the stage field, and requiresReactivate is true only for power-activation and proxy-launch`.
      Generate every child error shape and every adapter-internal failure.

  - [ ]* 5.3 Write the botocore needle regression tests
    - Assert each needle from task 5.1's constant against a message produced by constructing the
      **real** botocore exception instance, so a botocore upgrade fails a test rather than
      silently degrading `dns-resolution`, `tcp-connection`, and `tls-handshake` into the
      catch-all. This is the mitigation for delivery risk DR-3.
    - _Requirements: 9.4, 9.10_

  - [ ] 5.4 Implement the retry and timeout budgets, including the draining channel
    - Connection failures (not retried by the child): resend the same JSON-RPC object to the same
      child, at most 3 total attempts, a uniform 2-second wait before each subsequent attempt, and
      a hard 15-second cumulative wall-clock cap.
    - Add **no** adapter retry layer for throttling and transient service errors — the child
      already does four attempts with 0.5/1.0/2.0-second delays. Reshape its
      `AgentCore invocation failed after 3 retries` into stage `tool-execution` with
      `attempts: 4` and the last AWS error code. **Depends on amendment A-1.**
    - Enforce the 60-second per-attempt deadline in the adapter (the child's boto3
      `read_timeout` is 300). On expiry: return `request-timeout` immediately, record the
      abandoned `id` in a timed-out-id set, keep the child alive, discard the late response with
      one DEBUG line, and never kill the child for a slow call.
    - Enforce the 120-second cumulative per-invocation budget while the channel drains, naming
      the cumulative elapsed seconds.
    - _Requirements: 9.3, 9.5, 9.6, 9.7, 9.12_

  - [ ] 5.5 Carry per-stage recoverability in the error payload
    - Set `recoverable` and `requiresReactivate` from the section 8.5 table: `requiresReactivate`
      true only for `power-activation` and `proxy-launch`; the Runtime_Session_Id is retained for
      `credential-resolution`, `endpoint-invocation`, `authorization`, `tool-execution`, and
      `response-parsing`.
    - State the re-activation requirement in the message text for the two non-recoverable stages
      and name the absent configuration value or failing dependency.
    - _Requirements: 9.11, 9.16_

  - [ ]* 5.6 Write unit tests for the draining channel and the budgets
    - Fake child that never answers one `id` then answers the next: assert the timeout error is
      returned at 60 s, the child is still alive, the late response is discarded rather than
      mis-correlated, the connection-failure resend stops at 3 attempts and 15 s, and the
      cumulative 120-second budget produces `tool-execution` / `request-timeout`.
    - _Requirements: 9.3, 9.7, 9.12_

- [ ] 6. Checkpoint — adapter core
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Attribution metadata, non-fatal teardown paths, and shutdown

  - [ ] 7.1 Generate the Kiro_Web_Session_Id and attach it as `params._meta`
    - Generate `kiroweb-` + `uuid4().hex` once at startup, hold it for the process lifetime, log
      it once to stderr.
    - Insert into `params._meta` of every forwarded request exactly two namespaced keys:
      `mdc/kiroWebSessionId` and `mdc/consumerClass` with the literal value `kiro-web`. Insert at
      `params` level, never inside `params.arguments`, so no tool input schema is affected.
    - **Depends on amendment A-4** for the R12 AC 3 reading.
    - _Requirements: 8.5, 8.7, 8.9, 7.6, 12.3_

  - [ ]* 7.2 Write unit tests for the `_meta` annotation
    - **Property 10 (adapter half): Request_Metadata is attached on every forwarded request**
    - **Validates: Requirements 8.5**
    - Assert both keys are present on every forwarded `tools/call`, that the value is stable
      within a process and distinct across two processes, that `params.arguments` is untouched
      byte-for-byte, and that no third `_meta` key is added.

  - [ ] 7.3 Treat the `stop_runtime_session` authorization denial as non-fatal
    - Detect the child's `stop_runtime_session failed` stderr line, emit exactly one log entry
      recording that the denial is expected because the IAM policy grants only
      `InvokeAgentRuntime`, and do not propagate it as a session error.
    - _Requirements: 4.13, 4.12_

  - [ ] 7.4 Implement teardown
    - On stdin EOF, SIGTERM, or SIGINT: close the child's stdin, wait for the child to exit (its
      own `finally` calls `stop_session()`), then drop every reference to the credential values
      and rebind to a sentinel, unset `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` /
      `AWS_SESSION_TOKEN` from the adapter's environment mapping, and delete `~/.aws/sso/cache`
      and `~/.aws/cli/cache`.
    - Escalate to SIGTERM then SIGKILL if the child has not exited within 5 seconds so the
      process count reaches zero inside the required window.
    - Add a comment stating that Python cannot overwrite a `str` in place, which is why the
      on-disk caches are removed as well. **Depends on amendment A-2.**
    - _Requirements: 2.11, 2.12, 3.7, 3.8_

  - [ ]* 7.5 Write unit tests for teardown
    - Assert child stdin closure, the 5-second SIGTERM/SIGKILL escalation, zero surviving child
      processes, the three environment variables unset, and both cache directories removed.
    - _Requirements: 2.11, 3.8_

- [ ] 8. The diagnostic action

  - [ ] 8.1 Implement the nine-field diagnostic
    - Expose it as the Powers_Interface diagnostic action, not as an MCP tool, so it stays
      callable when the MCP channel is broken.
    - Return **exactly** these fields: `runtimeArn`, `region`, `credentialsResolved`,
      `credentialsRemainingSeconds` (integer or `null`), `runtimeSessionIdHeld` (boolean, never
      the value), `boto3Importable`, `healthCallOutcome`, `healthCallElapsedMs`, and `failingStage`
      present only on failure.
    - Probe with one `tools/call` of `mcp_health_check` using default arguments
      (`detailed=false, deep=false, functional=false`), under its own 60-second deadline. On
      expiry return `healthCallOutcome: "failure"`, `failingStage: "tool-execution"`, and **every
      other field**.
    - Serialize through the task 4.3 redactor so no access key identifier, secret key, or session
      token can appear.
    - _Requirements: 9.13, 9.14, 9.15_

  - [ ]* 8.2 Write unit tests for the diagnostic contract
    - Assert the returned key set equals the nine-field contract exactly (no extra keys, no
      missing keys on the failure path), that `runtimeSessionIdHeld` is a boolean and never the
      identifier, that `credentialsRemainingSeconds` is a duration and never a timestamp, and
      that an injected session token does not survive serialization.
    - _Requirements: 9.13, 9.14, 9.15_

- [ ] 9. Tenant passthrough fidelity

  - [ ] 9.1 Forward `tenant_id` unmodified and inject nothing
    - Confirm in code and comment that the adapter performs no case folding, trimming, aliasing,
      prefixing, defaulting, or injection of `tenant_id`, and holds no copy of the 24-tool
      tenant-scoped list. Tenant declaration is the per-call argument only.
    - Record in the comment that **R5 AC 11 is withdrawn** under its own second clause per design
      section 11.2 (amendment A-5), and that the usability gap is closed by steering prompting in
      task 11.2, not by adapter state.
    - _Requirements: 5.4, 5.11_

  - [ ]* 9.2 Write the tenant passthrough property test
    - **Property 8 (adapter half): Tenant passthrough fidelity**
    - **Validates: Requirements 5.4**
    - New file `mcp_server_python/tests/properties/test_power_tenant_passthrough_props.py`,
      Hypothesis, ≥ 100 iterations, tagged
      `# Feature: kiro-web-mcp-power, Property 8: the forwarded bytes for tenant_id are character-identical to the value supplied`.
      Generators must include the empty string, whitespace-only, unicode, and 64+ character
      values. The server-side resolution half is task 14.2 and is blocked.

- [ ] 10. SSE reassembly property

  - [ ]* 10.1 Write the SSE reassembly round-trip property test
    - **Property 1: SSE reassembly round-trip**
    - **Validates: Requirements 2.8**
    - New file `mcp_server_python/tests/properties/test_power_sse_framing_props.py` that
      **imports** `parse_sse` from the unmodified `tools/agentcore-kiro-proxy.py` (import only —
      zero modified lines) and asserts, over arbitrary frame partitions of payloads up to 10 MiB,
      that reassembly reproduces the original JSON-RPC object. Hypothesis, ≥ 100 iterations,
      tagged
      `# Feature: kiro-web-mcp-power, Property 1: for any partition of a JSON-RPC payload into text/event-stream frames, reassembly reproduces the original object`.
    - The test must **not** assert on inter-frame timing, which design section 8.3 shows is
      unobservable (amendment A-3).

- [ ] 11. Power manifest, steering bundle, and the tool-count reconciliation

  - [ ] 11.1 Write `powers/mdc-mcp-rag/power.json`
    - Exactly the design section 5.2 manifest: name `mdc-mcp-rag`, version `0.1.0`, status
      `prototype`, a one-sentence description under 200 characters, 9 keywords including
      `global-workflow`, `graphrag`, `mdc-mcp`, `tenant`, and `ee2`, 2 steering entries, and
      exactly one MCP server with one command string and one argument vector naming
      `${REPO_ROOT}/tools/agentcore-kiro-proxy.py` as `--proxy`.
    - `MDC_AGENTCORE_RUNTIME_ARN`, `AWS_REGION`, and `MDC_AWS_PROFILE` as configuration inputs —
      no literal ARN anywhere in the manifest.
    - `autoApprove` lists exactly the **47** tools of design section 4 OQ-5 minus the six
      deliberate mutators (`mark_as_modified`, `checkpoint_state`, `restore_checkpoint`,
      `start_sdd_session`, `record_sdd_step`, `complete_sdd_session`); `get_code_context` and
      `get_sdd_session` are included. All 53 tools remain callable — `autoApprove` restricts
      nothing.
    - Zero AWS access key identifier, secret access key, or session token anywhere in the file.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 1.8, 1.9, 1.10, 4.3, 4.4, 4.5, 4.6_

  - [ ] 11.2 Write `powers/mdc-mcp-rag/steering/01-consumer-guide.md`
    - Copy `.kiro/steering/09-agentcore-mcp-for-global-workflow.md` and apply only the bounded
      edits of design section 5.3: drop the `inclusion:` front matter; `52 tools / 9 modules` →
      `53 tools / 10 modules`; **remove** the literal runtime ARN and reference the
      `MDC_AGENTCORE_RUNTIME_ARN` configuration value instead; rewrite the connection section for
      `kiro_powers activate` plus the `aws sso login --profile mdc-kiro-web` prerequisite; retain
      the production-safety warning about Global Workflow verbatim.
    - Add the prototype/mutation section: status `prototype`, the full 53-tool surface including
      all 8 Mutation_Tool_Set members, `autoApprove` described as a bypassable convenience filter
      and explicitly not a security control, the incidental writes in `get_code_context` and
      `get_sdd_session(resume=true)`, and the runbook section name holding the accepted risk.
    - Add the tenant guidance: carry the user's stated branch forward in agent context and pass
      `tenant_id` explicitly on every tenant-scoped call; default `gw`; every response states
      `*Tenant:*` and `*Branch:*` so drift is visible. State plainly that an unpopulated tenant
      index and an empty result set are different conditions and that the server does not
      currently distinguish them (design section 11.1).
    - Non-empty, and zero credential material.
    - _Requirements: 1.5, 1.6, 4.11, 5.10, 6.9, 6.10, 11.11_

  - [ ] 11.3 Write `powers/mdc-mcp-rag/steering/02-tool-guide.md`
    - Copy `.kiro/steering/10-agentcore-mcp-tool-guide.md`, drop the front matter, and regenerate
      the tool table from the design section 4 OQ-5 enumeration so the shipped guide and the
      manifest cannot drift: 53 tools, 10 modules, 24 tenant-scoped.
    - State for each of the 8 Mutation_Tool_Set members what it writes and where, keeping the
      M1/M2 tiering: `mark_as_modified` writes `_dirty` flags into **shared Neptune** state and
      must not be called unless the user explicitly asks, naming the paths first; the seven M2
      tools write only ephemeral session state on the runtime filesystem.
    - Non-empty, and zero credential material.
    - _Requirements: 1.5, 1.6, 4.6, 11.11, 11.13_

  - [ ] 11.4 Write the tool-registry enumeration script
    - `scripts/verify_tool_registry.py` counting `@mcp.tool(` decorators across
      `mcp_server_python/src/tools/*.py`, handling **both** the explicit `name="..."` form and the
      bare `@mcp.tool()` form used by `error_analysis.py` (a script that handles only the first
      under-counts by one and lands on 52). Emit the total, the module count, the tenant-scoped
      count, and the tool name list, and exit non-zero on a mismatch against `baseline.json`.
    - _Requirements: 11.13, 1.3_

  - [ ]* 11.5 Write manifest and bundle conformance tests
    - Assert: the manifest parses; the field budgets of R1 AC 1 hold; the five mandated keywords
      are present case-insensitively; exactly one MCP server with one command and one argument
      vector; the argument vector names `tools/agentcore-kiro-proxy.py`; `autoApprove` has exactly
      47 entries and excludes exactly the six deliberate mutators; the manifest and both steering
      files contain zero matches for an AWS access key identifier, secret access key, or session
      token pattern; both steering files exist and are non-empty; and the tool names in the
      manifest and `02-tool-guide.md` equal the task 11.4 script's output exactly.
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.8, 1.9, 4.3, 11.13_

  - [ ] 11.6 Correct the repository steering tool counts (proposed, single-line change)
    - Update the `52 tools / 9 modules` claims in `.kiro/steering/09-agentcore-mcp-for-global-workflow.md`
      (two occurrences) and `.kiro/steering/10-agentcore-mcp-tool-guide.md` to `53 tools / 10
      modules`, and `24 of 52` to `24 of 53`. The `24` figure is already correct.
    - Do **not** touch `README.md` (34-tool claim, maintainer-owned) and do **not** touch
      `.kiro/specs/mcp-external-access-revised/design.md` (51-tool claim, read-only under R10 AC 2).
    - _Requirements: 11.13, 7.4_

- [ ] 12. Runbook and Power documentation

  - [ ] 12.1 Write `powers/mdc-mcp-rag/RUNBOOK.md`
    - Include a section named exactly `Prototype Status and Accepted Risk` containing the design
      section 12.1 risk record verbatim in substance: authorization is enforced only at the
      `InvokeAgentRuntime` API boundary, IAM cannot read the MCP payload, all 53 tools including
      all 8 mutators are reachable, no control in this design prevents that reachability,
      `autoApprove` is a bypassable convenience filter and not a security control.
    - Include the four compensating controls (named human via CAC SSO, CloudTrail attribution,
      the one-action/one-resource IAM boundary, prototype scope) each with its verification method.
    - Include the migration trigger stated identically to design section 12.3, and the note that
      re-pointing the runtime ARN requires changing the manifest configuration value and the IAM
      policy `Resource` in the same commit.
    - The literal `prototype` must appear here, in `power.json`, and in the `activate` output —
      three places, character-for-character.
    - Record `stream-idle-timeout` as reserved and never emitted, so an operator who reads the
      taxonomy knows why they will not see it.
    - _Requirements: 4.7, 4.8, 4.9, 4.11, 10.3, 10.4, 10.5, 12.12_

  - [ ] 12.2 Write `docs/runbooks/kiro-web-mcp-power.md`
    - The seven named sections in the required order, following the structure of the existing
      `docs/runbooks/onboard-pillar-tenant.md`.
    - Prerequisites: `aws sso login --profile mdc-kiro-web`, the one-time administrator step
      (attach `mdc-mcp-rag-kiro-web-invoke` to the Kiro Web permission set, assign it for account
      `903050880929`, confirm max session duration ≤ 12 hours), and the note that a login may be
      required once per Kiro Web session.
    - An executable First Query: one `search_documentation` call with an explicit `tenant_id`,
      and the expectation that the response's `*Tenant:*` header matches the value supplied.
    - The full 53-tool surface with the 24 tenant-scoped ones marked and the 8 mutators flagged.
    - Troubleshooting keyed by the seven stages and their categories, including: the keepalive
      cadence (a `ping` every 45 seconds plus a startup `initialize` warmup produce
      `InvokeAgentRuntime` CloudTrail events with no corresponding tool call, so CloudTrail counts
      exceed Audit_Log tool entries by roughly one per 45 seconds); the expected
      `stop_runtime_session` denial; and `stream-idle-timeout` never appearing.
    - Credential lifetimes: 900–43200 seconds, the 900-second warning threshold, the single
      resend, and the refresh command.
    - A steering summary of **≤ 150 words**.
    - The reconciled tool count citing `mcp_server_python/src/tools/` as the authority, and the
      CloudTrail join procedure of design section 9.3 (runtime ARN + `eventTime` matched to the
      Audit_Log `timestamp` within ≤ 5 seconds, disambiguated by `Kiro_Web_Session_Id` and tool
      name) stated as the primary join until verification item V-4 confirms a field.
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 11.10, 11.11, 11.12, 11.13, 8.8_

  - [ ]* 12.3 Write documentation conformance tests
    - Assert the seven runbook section names appear in the required order; the First Query block
      is a parseable tool call naming an explicit `tenant_id`; the steering summary is ≤ 150
      words; the literal `prototype` appears in `power.json`, `RUNBOOK.md`, and the `activate`
      output path; the runbook's tool list matches the task 11.4 script's output; and no AWS
      credential pattern appears in either document.
    - _Requirements: 11.1, 11.6, 11.12, 10.4_

- [ ] 13. Checkpoint — all sandbox-testable work complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 14. Blocked verification work — requires AWS credentials, a live runtime, or server-side changes this spec does not own

  Every sub-task below is written now and marked optional so the gap stays visible in the suite
  rather than disappearing from the plan. **None of them can pass in the sandbox.** Do not fold
  the server-side work into this spec's change set.

  - [ ]* 14.1 Write the SigV4 single-target test, live half **[BLOCKED — needs AWS credentials]**
    - **Property 2: SigV4 correctness, single target**
    - **Validates: Requirements 2.10, 2.15, 4.1**
    - Sandbox-testable half (write and run now): the child's argument vector contains exactly the
      one configured ARN and never another. Live half (write, mark as requiring credentials, and
      skip by default): a real `InvokeAgentRuntime` call over TLS 1.2+ returns non-error, and a
      call naming a different runtime is denied. Signature acceptance is an AWS-side fact.

  - [ ]* 14.2 Write the live integration and attribution checks **[BLOCKED — needs a live runtime and CloudTrail]**
    - One `mcp_health_check` through the Power returning non-error within 60 seconds; one
      `search_documentation` with an explicit `tenant_id` whose response `*Tenant:*` header
      matches the supplied value (the server-side half of Property 8); and retrieval of the
      CloudTrail `InvokeAgentRuntime` event carrying the IAM principal identifier for that call.
    - The CloudTrail item is simultaneously R4 AC 10, the attribution compensating control, and
      verification item V-4; it may require an explicit data-event selector rather than a default
      management-event trail, which must be confirmed by producing a call and finding the event.
    - _Requirements: 4.10, 5.6, 5.7, 11.5, 8.8_

  - [ ]* 14.3 Write the empty-versus-unpopulated distinguishability test, expected to fail **[BLOCKED — server-side, delivery risk DR-1]**
    - **Property 9: Empty-versus-unpopulated distinguishability**
    - **Validates: Requirements 6.1, 6.2, 6.7**
    - Cannot pass today: no structured index-coverage field exists in the MCP server response
      (design section 11.1). Write it, mark it expected-to-fail, and reference the server-side
      dependency `.kiro/specs/tenant-status-honesty/` (unstarted, all seven tasks unchecked).
    - **R6 AC 1–8 are not this spec's to deliver** (amendment A-6). This spec delivers only R6
      AC 9 and AC 10, in task 11.2.

  - [ ]* 14.4 Write the Audit_Log well-formedness test, expected to fail **[BLOCKED — server-side, delivery risk DR-2]**
    - **Property 10 (server-side half): Audit entry well-formedness and joinability**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    - No audit emitter matching R8 AC 2's field list exists in `mcp_server_python/src` today, and
      whether the server reads `params._meta` at all is unverified. Write the test, mark it
      expected-to-fail, and record that R8 AC 1, 2, 3, 4, 6, 10, 11, and 12 require an MCP server
      change and an AgentCore image rebuild that this spec does not contain and should be raised
      as its own spec.
    - This spec delivers only R8 AC 5 (task 7.1), AC 7 (the unmodified child sends the
      `Runtime_Session_Id`), AC 8 (the join procedure, task 12.2), and AC 9 (no Cognito
      pre-token-generation trigger and no custom claim — satisfied by construction).

- [ ] 15. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Sub-tasks marked `*` are optional and can be skipped for a faster MVP. Every task in group 14
  is marked optional **and** blocked; skipping them does not close the gap they record.
- The implementation languages are Python 3.12 (adapter and tests, `hypothesis==6.152.2` under
  `mcp_server_python/tests/{unit,properties,integration}/`) and TypeScript CDK v2 with Jest
  (`infrastructure/cdk/`). No language question is open — design section 1 fixes both.
- The fake Proxy_Bridge child built in task 3.5 is the shared fixture for every adapter test.
  Its canned strings are the coupling to the frozen file, which is why task 5.3 asserts them
  against real botocore exception instances.
- Five of the eleven correctness properties are fully sandbox-testable (P1, P4, P5, P7, P11), two
  are partly testable (P2, P8), and four need AWS or server-side work (P2 live half, P9, P10,
  and the live half of P8).
- Task 1.1 and 1.2 must come first: every later task's compliance with R7 AC 1 and AC 3 is
  measured against the baseline they record.

## Requirements amendments the design review must accept or reject

Several tasks above depend on these. If any is rejected, the tasks naming it must be re-planned
before implementation starts.

| ID | Criterion | Amendment | Tasks that depend on it |
|---|---|---|---|
| **A-1** | R9 AC 5 | Lower the first-retry delay floor from 1 s to 0.5 s to match the frozen Proxy_Bridge's `BASE_DELAY = 0.5`. Attempt count (4), the doubling rule, and the 10-second cumulative ceiling already hold. | 5.4 |
| **A-2** | R3 AC 7 | Narrow "no credential material on disk" to the repository working tree, persisted Power configuration, the manifest, the steering bundle, and the chat transcript; carve out `$HOME/.aws` on the conditions of mode `0600`/`0700`, location outside the work tree, and deletion at teardown. | 4.1, 7.4 |
| **A-3** | R2 AC 15, R9 AC 7 | Record `stream-idle-timeout` as reserved and never emitted while the Proxy_Bridge reads the response body in one blocking call. | 5.1, 10.1, 12.1 |
| **A-4** | R12 AC 3 | Clarify that AC 3's prohibition targets smuggled file content and admits two bounded namespaced `_meta` keys totalling under 100 bytes. | 7.1 |
| **A-5** | R5 AC 11 | Record AC 11 as **withdrawn** under its own second clause; tenant declaration is the per-call `tenant_id` argument. | 9.1, 11.2 |
| **A-6** | R6 AC 1–8; R8 AC 1, 2, 3, 4, 6, 10, 11, 12 | Re-scope these as dependencies on server-side specs (R6 AC 1, 2, 7 onto `.kiro/specs/tenant-status-honesty/`; the rest onto new server-side specs). This spec keeps R6 AC 9, 10 and R8 AC 5, 7, 8, 9. | 14.3, 14.4, and the completability of this spec overall |

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0,  "tasks": ["1.1", "1.2", "2.1", "3.1"] },
    { "id": 1,  "tasks": ["3.2", "2.2"] },
    { "id": 2,  "tasks": ["3.4", "3.3"] },
    { "id": 3,  "tasks": ["4.1", "3.5", "11.4"] },
    { "id": 4,  "tasks": ["4.2", "11.1"] },
    { "id": 5,  "tasks": ["4.3", "11.2"] },
    { "id": 6,  "tasks": ["4.5", "11.3"] },
    { "id": 7,  "tasks": ["5.1", "4.4", "11.6"] },
    { "id": 8,  "tasks": ["5.4", "4.6", "11.5"] },
    { "id": 9,  "tasks": ["5.5", "5.2"] },
    { "id": 10, "tasks": ["7.1", "5.3"] },
    { "id": 11, "tasks": ["7.3", "5.6"] },
    { "id": 12, "tasks": ["7.4", "7.2", "10.1"] },
    { "id": 13, "tasks": ["8.1", "12.1"] },
    { "id": 14, "tasks": ["9.1", "12.2"] },
    { "id": 15, "tasks": ["8.2", "9.2", "7.5", "12.3"] },
    { "id": 16, "tasks": ["14.1", "14.2", "14.3", "14.4"] }
  ]
}
```
