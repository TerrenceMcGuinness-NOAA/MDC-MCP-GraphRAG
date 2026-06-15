# Implementation Plan — `agentcore-creds-provisioning`

## Overview

Implement `tools/provision-agentcore-creds.py` per the design — a Python 3.12
stdlib-only provisioning tool that runs as `ec2-user` and brings every eligible
per-user OS account up to spec for the `agentcore-mcp-rag` MCP server. For each
target user it ensures a `[agentcore-rag]` profile in `~/.aws/credentials`
(sourced from `/home/ec2-user/.aws/credentials [default]`) and an
`agentcore-mcp-rag` server entry in `~/.kiro/settings/mcp.json` whose `env`
references that profile. Idempotent, atomic, never logs the master keys, and
emits a Run_Summary classifying each user as `created`/`updated`/`skipped`/`failed`.

The work is one production file (~800 lines including module-internal classes)
plus tests and a runbook. No AWS infra changes, no new IAM, no container rebuild,
no runtime deploy. The only host-level change is an optional sudoers tightening
documented in the runbook.

Implementation is organized into nine waves: data models and redactor first,
then the independent components (identity gate, config resolver, source-creds
loader, user discovery), then the file writers (with byte-preservation), then
orchestration (UserProvisioner, Idempotency, VerificationProbe), then the
top-level (CLI dispatch, RunSummary), then tests in parallel, then the runbook
and gated rollout.

## Tasks

- [x] 1. Scaffold the script and shared data models
  - Create `mcp_server_python/tools/provision-agentcore-creds.py` (mode 0750,
    owner `ec2-user:ec2-user`, shebang `#!/usr/bin/env python3.12`) with the
    module docstring and stdlib-only imports declared in design §"Implementation
    language and packaging".
  - Add the dataclasses from design §"Data Models": `Disposition` (Literal alias),
    `Config`, `IamCreds` (frozen), `TargetUser` (frozen), `RunRecord`, `FileChange`,
    `Section`. Field types and immutability flags exactly per design.
  - Define module constants: `NOLOGIN_SHELLS`, `AWS_PROFILE_NAME = "agentcore-rag"`,
    `MIN_UID = 1000`, `BUILTIN_EXCLUSIONS = {"ec2-user", "root"}`, the
    AgentCore_Runtime_ARN default, the AWS_Region default `us-east-1`, the
    Proxy_Path default.
  - _Requirements: 6.4, 6.5, 6.6, 6.7, design §"Module decomposition"_

- [x] 2. Implement `SecretRedactor` and `Logger`
  - `SecretRedactor` per design §"Secret redaction (R12)": `register(value, label)`,
    `scrub(text)`. Scrub returns the same string when no tokens are registered or
    none are present. Empty-string registrations are no-ops.
  - `Logger` writes to `sys.stderr` through the redactor. Single global instance
    used by every other module.
  - Install `sys.excepthook` to format the traceback into a string, scrub it, and
    write through `Logger`.
  - Install SIGINT and SIGTERM handlers that flush a partial Run_Summary through
    the redactor before re-raising for clean exit.
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

  - [x]* 2.1 Unit tests for `SecretRedactor` and `Logger`
    - Scrubs literal access-key and secret values from arbitrary text including
      JSON, INI, and traceback formats.
    - Empty / unset values do not register (don't replace empty substrings).
    - Subprocess argv echoes routed through `Logger.write` are scrubbed.
    - `sys.excepthook` produces a redacted traceback string.
    - File: `mcp_server_python/tests/unit/test_provision_redactor.py` (new)
    - _Validates: 12.1, 12.4, 12.5, 12.6_

- [x] 3. Implement `IdentityGate`
  - Per design §"Identity gate (R1)". Determine `euid`, `euser` via
    `pwd.getpwuid(os.geteuid())`, and `SUDO_USER` env var.
  - Refuse with `Logger` error and exit code 3 when running as anything other than
    `ec2-user` (or root with `SUDO_USER=ec2-user`).
  - Must be called before any filesystem read of source creds or target homes.
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x]* 3.1 Unit tests for `IdentityGate`
    - Parametrize over (euid, euser, SUDO_USER) tuples covering: ec2-user direct,
      root+SUDO_USER=ec2-user, root+empty SUDO_USER, root+wrong SUDO_USER, other
      non-root user.
    - Assert exit code 3 for refusals and no exception for accepts.
    - Assert no filesystem access happens before the gate.
    - File: `mcp_server_python/tests/unit/test_provision_identity.py` (new)
    - _Validates: 1.1, 1.2, 1.3_

- [x] 4. Implement `ConfigResolver` (CLI parser + validation)
  - `argparse` setup for every flag in design §"CLI surface": `--all`, `--user`,
    `--exclude-file`, `--verify`, `--verbose`, `--dry-run`, `--format`,
    `--runtime-arn`, `--region`, `--proxy-path`.
  - Resolution precedence per design §"Configuration validation": CLI > env (vars
    `AGENTCORE_RUNTIME_ARN`, `AWS_REGION`, `AGENTCORE_PROXY_PATH`) > built-in
    default. Record source per field on `Config`.
  - Validate runtime ARN against
    `^arn:aws:bedrock-agentcore:[a-z0-9-]+:\d{12}:runtime/[A-Za-z0-9_-]+$`,
    region against `^[a-z]{2,4}(-[a-z]+)+-\d+$`, proxy path is a regular file
    (after `os.path.realpath` resolution) readable by `ec2-user`.
  - Mutual exclusion enforcement: `--all` and `--user` together → exit 2;
    neither → exit 2.
  - Read `--exclude-file` lines, strip whitespace, drop comments / empty lines,
    union into `Config.exclusions`. Missing/unreadable file → exit code as per R2.5.
  - _Requirements: 2.4, 2.5, 9.4, 10.1, 10.4, 10.5, 13.1, 13.2, 13.3, 13.6, 13.7, 13.8_

  - [x]* 4.1 Unit tests for `ConfigResolver`
    - Each precedence path (CLI / env / default) for ARN, region, proxy path.
    - Regex passes and fails for ARN and region.
    - Proxy path: existing regular file, missing path, symlink to regular file,
      symlink to non-existent target.
    - `--all`+`--user` and neither: exit 2.
    - `--exclude-file` round-trip with comments and blanks; missing file exit code.
    - File: `mcp_server_python/tests/unit/test_provision_config.py` (new)
    - _Validates: 2.4, 2.5, 10.4, 10.5, 13.1–13.3, 13.6–13.8_

- [x] 5. Implement `CredentialsLoader`
  - Per design §"Source credential loading (R3)". Use
    `configparser.ConfigParser(interpolation=None, comment_prefixes=("#", ";"))`.
    Strip surrounding whitespace and a single matching pair of `'` or `"`.
  - Return an `IamCreds`. Immediately call `redactor.register(creds.access_key_id,
    "aws-access-key-id")` and likewise for the secret and (if present) the session
    token, before the function returns.
  - Errors: missing/unreadable file, missing `[default]` section, missing
    `aws_access_key_id`/`aws_secret_access_key` field, empty value after stripping
    → exit code 4 with diagnostic that does not include any credential value.
  - Treat missing `aws_session_token` as non-fatal (per R3.6).
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x]* 5.1 Unit tests for `CredentialsLoader`
    - Source files with quoted values (single/double), comments (`#` and `;`),
      missing section, missing field, empty field.
    - Optional `aws_session_token` round-trip and absence (no error).
    - Assert `redactor.scrub` masks the loaded values immediately after load.
    - File: `mcp_server_python/tests/unit/test_provision_creds_loader.py` (new)
    - _Validates: 3.1, 3.2, 3.3, 3.4, 3.6_

- [x] 6. Implement `UserDiscovery` and `Eligibility`
  - `Eligibility.is_eligible(pwd_entry, exclusions) -> (bool, reason)` — pure
    predicate per design §"User discovery (R2)": UID ≥ 1000, shell not in
    `NOLOGIN_SHELLS`, `pw_dir == /home/<pw_name>`, not in
    `BUILTIN_EXCLUSIONS | exclusions`.
  - `Eligibility.check_or_die(name, exclusions)` — used by Single_User_Mode (R9):
    looks up the name via `pwd.getpwnam` (raises if missing → exit non-zero per
    R9.3), runs the predicate, surfaces the failing clause as the error message
    per R9.4–R9.7.
  - `UserDiscovery.eligible(exclusions)` — `pwd.getpwall()` + `is_eligible` filter
    + sort by `name.encode("ascii")` (C-locale order). Logs the resulting names
    in sorted order before any side effect.
  - _Requirements: 2.1, 2.2, 2.3, 2.6, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [x]* 6.1 Unit tests for eligibility
    - Synthetic passwd entries that pass and fail every predicate clause:
      UID < 1000, nologin shells, mismatched `pw_dir`, in builtin exclusions, in
      `--exclude-file` exclusions.
    - `check_or_die` produces specific messages per R9.4–R9.7.
    - C-locale sort with mixed-case names (e.g. `Alice`, `alice`, `bob`).
    - File: `mcp_server_python/tests/unit/test_provision_eligibility.py` (new)
    - _Validates: 2.2, 2.3, 9.3–9.7_

- [x] 7. Implement `AwsConfigDir`
  - Per design §"Filesystem write protocol". `ensure(target)` creates the dir if
    absent via `sudo install -d -m 0700 -o <u> -g <u> /home/<u>/.aws`; otherwise
    runs `sudo chmod 0700 ...` and `sudo chown <u>:<g> ...` to re-assert.
  - Pre-checks: refuse if `/home/<u>/.aws` exists and is a symlink or non-dir
    (lstat-based) → return `failed` with the specific reason; refuse if home dir
    missing/not-a-dir/wrong-owner per R4.6 → `failed`.
  - Same logic, factored, for `/home/<u>/.kiro/settings`.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 6.1_

- [x] 8. Implement `AwsCredsWriter` (section-aware INI editor)
  - Per design §"Credentials file write (R5, R7, R14)". Tokenize into ordered
    `Section[]` preserving every comment, blank line, and section ordering.
    Replace exactly the `[agentcore-rag]` section (or append if absent) with
    three lines: header + `aws_access_key_id = …` + `aws_secret_access_key = …`.
    Discard any other fields previously inside `[agentcore-rag]` per R5.8.
  - Atomic write protocol: stage bytes in `/tmp` (ec2-user-owned, 0600);
    `sudo install -m 0600 -o <u> -g <u> /tmp/<staged> /home/<u>/.aws/credentials.tmp.<pid>`;
    `sudo python3.12 -c "<atomic_rename_snippet>"` to perform `os.rename` +
    `os.fsync(dirfd)` of the parent dir.
  - Capture `(st_dev, st_ino, st_size, st_mtime_ns)` on read, re-stat after the
    rename — if the snapshot diverges in a way inconsistent with our write,
    classify `failed` "concurrent modification detected" per R14.3.
  - Re-assert mode 0600 and ownership on every run including byte-equal cases
    (R7.5).
  - Return `FileChange` with disposition: `created` (file did not exist),
    `updated` (existed and bytes changed), `skipped` (existed and bytes equal).
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 7.1, 7.5, 14.1, 14.2, 14.3_

  - [x]* 8.1 Unit tests for `AwsCredsWriter` (use `pyfakefs`)
    - Pre-existing files with multiple sections, comments, blank lines: assert
      every section other than `[agentcore-rag]` is byte-preserved.
    - `[agentcore-rag]` already present with extra fields: assert extras are
      removed, only the two managed fields remain, other sections untouched.
    - Pre-existing file byte-equal to target output: returns `skipped`, mode
      and ownership are still re-asserted.
    - Mock `subprocess.run` for sudo atomic-rename helper; assert correct argv
      shape and ordering.
    - File: `mcp_server_python/tests/unit/test_provision_creds_writer.py` (new)
    - _Validates: 5.6, 5.7, 5.8, 5.9, 7.1, 7.5_

- [x] 9. Implement `McpConfigWriter` (JSON editor)
  - Per design §"MCP config file write (R6, R7, R14)". `json.loads` strict.
    Invalid JSON → `failed` per R6.11 (do not modify file).
  - Mutate `obj["mcpServers"]["agentcore-mcp-rag"]`'s four `Managed_Keys` only:
    `command="python3.12"`, `args=[proxy_path, "--runtime-id", runtime_arn]`,
    `env.AWS_REGION`, `env.AWS_PROFILE="agentcore-rag"`. Use `setdefault` for
    `env` so other env vars are preserved.
  - Serialize with `json.dumps(obj, indent=2, ensure_ascii=False)` + trailing
    `\n`. Atomic write same as creds writer.
  - Idempotency: re-parse new bytes; assert non-managed keys parse to the same
    canonical-form JSON value as the input (defense-in-depth bug check). If a
    non-managed key changed unexpectedly, classify `failed` and abort that user.
  - Pre-existing key order is preserved by mutating-in-place on the parsed
    dict; new Managed_Keys appended at end of their object level (R6.13).
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 6.11, 6.12, 6.13, 7.2, 7.6, 14.1, 14.2, 14.3_

  - [x]* 9.1 Unit tests for `McpConfigWriter`
    - Pre-existing files with `powers`, multiple servers, custom `autoApprove`,
      `disabledTools`, and other env vars: assert preservation and key ordering.
    - Managed_Keys written with correct types; verify `args` is a list of three
      strings in the documented order.
    - Invalid JSON pre-existing: returns `failed`, file unchanged.
    - Pre-existing file already in target state: returns `skipped`, mode and
      ownership re-asserted.
    - File: `mcp_server_python/tests/unit/test_provision_mcp_writer.py` (new)
    - _Validates: 6.8, 6.9, 6.10, 6.11, 7.2, 7.6_

- [x] 10. Implement `Idempotency` cross-file invariant check
  - After both file writes succeed, parse the written `[agentcore-rag]` section
    header and the written `mcp.json` `agentcore-mcp-rag.env.AWS_PROFILE` and
    assert byte equality. Mismatch is a contract bug → `failed`
    "cross-file profile name mismatch" per R14.1, R14.2.
  - Used by `UserProvisioner` after each per-user write pair.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 14.1, 14.2_

- [x] 11. Implement `VerificationProbe` (`--verify`)
  - Per design §"Verification probe (R8)". Two AWS calls under target user via
    `sudo -n -u <name> -H env AWS_PROFILE=agentcore-rag AWS_REGION=<region>
    HOME=/home/<name> PATH=/usr/local/bin:/usr/bin:/bin aws ...`.
  - Call 1: `aws sts get-caller-identity`. Call 2:
    `aws bedrock-agentcore-control list-agent-runtimes --region <region>`.
  - Each call: `subprocess.run(..., timeout=30)`. On `TimeoutExpired` →
    classify `failed` with reason "<label> timeout after 30s". On non-zero
    return code → classify `failed` with reason "<label> exit <rc>".
  - Stdout captured but not echoed unless `--verbose`. Stdout passes through
    `Logger` (so `SecretRedactor` scrubs it) when verbose.
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x]* 11.1 Unit tests for `VerificationProbe`
    - Mock `subprocess.run`. Assert timeout=30 honored.
    - Distinguish timeout-failure reason vs exit-code-failure reason in the
      `RunRecord.reason` field.
    - `--verbose` echoes stdout; default does not.
    - File: `mcp_server_python/tests/unit/test_provision_verify.py` (new)
    - _Validates: 8.3, 8.4, 8.5_

- [x] 12. Implement `UserProvisioner` (per-user driver)
  - Orchestrates per target: pre-checks (home dir validity), `AwsConfigDir.ensure`,
    `AwsCredsWriter.write`, `AwsConfigDir.ensure` for `~/.kiro/settings/`,
    `McpConfigWriter.write`, `Idempotency.cross_file_check`. Returns a
    `RunRecord` with the merged disposition (worst of `created`/`updated`/`skipped`
    where `failed` outranks any other; `created` outranks `updated` outranks
    `skipped` per R7.4).
  - Honors `--dry-run`: each writer reports the disposition it *would* assign
    without writing; the per-user disposition reflects the union per R10.6.
  - _Requirements: 4.5, 4.6, 7.4, 10.6_

- [x] 13. Implement `RunSummary` and exit-code mapping
  - Per design §"Run_Summary table form" / "JSON form". Truncate reason strings
    to 200 ASCII chars with `...` suffix per R11.2.
  - Aggregate counts for every disposition including zero-counts.
  - Exit codes per design §"Exit codes": 0 success, 2 argument error, 3 identity
    gate, 4 source creds, 5 config validation, 6 at least one user `failed`.
  - JSON output schema exactly as documented.
  - _Requirements: 10.7, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_

- [x] 14. Wire `main()` and CLI dispatch
  - Per design §"Single-user vs bulk dispatch (R9, R10)". Order: argparse →
    `IdentityGate.gate()` → `ConfigResolver.resolve()` → `CredentialsLoader.load()`
    → branch on `--all` vs `--user` for `UserDiscovery` vs `Eligibility.check_or_die`
    → loop `provision_one` → optional `VerificationProbe` for non-failed users
    → `RunSummary.render_and_exit`.
  - Empty Eligible_User_Set in Bulk_Mode: emit zero-row summary and exit 0
    per R11.6.
  - _Requirements: 9.1, 9.2, 10.1, 10.2, 10.3, 10.6, 10.7_

  - [x]* 14.1 Unit tests for `main()` orchestration
    - `--all` resolves to full eligible set, processes each exactly once.
    - `--user <name>` validates eligibility before any side effect.
    - `--dry-run` produces a Run_Summary with no filesystem changes (assert via
      `pyfakefs` no path was created).
    - Exit-code mapping for each documented case.
    - File: `mcp_server_python/tests/unit/test_provision_main.py` (new)
    - _Validates: 9.2, 10.1, 10.6, 10.7, 11.4, 11.5_

- [x]* 15. Property-based tests (Hypothesis, R17)
  - Property 1 (Idempotency, R17.1): generate 1–32 fake target users + fake home
    fs (pyfakefs); run script twice with identical inputs; assert byte-equality
    of every produced file across the two runs.
  - Property 2 (Preservation, R17.2): generate arbitrary valid `mcp.json` shapes
    (≤32 servers, depth ≤4, including `powers`, extra top-level keys, custom
    `autoApprove`, `disabledTools`); run writer; assert every non-managed key
    parses to the same canonical-form JSON value as before.
  - Property 3 (No-leak, R17.3): generate access keys (16–128 chars) and
    secrets (1–256 chars including `"`, `\`, `\n`); capture stdout/stderr/log
    for an entire run; assert neither value appears as a contiguous byte sequence.
  - Property 4 (Cross-file profile-name match, R17.4): for every successful
    user outcome, parse both files and assert the credentials section header
    equals the mcp.json `AWS_PROFILE` field.
  - Property 5 (Single-user isolation, R17.5): generate `--user <name>` over
    many fake homes; assert no path under any other home was created, modified,
    or deleted.
  - File: `mcp_server_python/tests/properties/test_provision_props.py` (new)
  - _Validates: 7.1, 7.2, 7.3, 12.1, 14.1, 14.2, 9.2, 17.1, 17.2, 17.3, 17.4, 17.5_

- [x]* 16. Fixed corner-case corpus tests (R17.6)
  - Empty creds file, malformed JSON mcp.json, max-length OS user name (32 char),
    secret containing JSON-significant chars (`"`, `\`, `\n`), absent credentials
    file, absent mcp.json, mcp.json already in target state.
  - Append to `tests/unit/test_provision_main.py` or a dedicated
    `test_provision_corner_cases.py`.
  - _Validates: 5.6, 6.11, 7.1, 7.2, 12.1_

- [x] 17. Runbook + sudoers fragment
  - `SETUP_AWS/provisioning/RUNBOOK_agentcore_creds.md` documents:
    - Operator workflow (`sudo -u ec2-user python3.12 tools/provision-agentcore-creds.py --all --verify`).
    - Master-key rotation: replace `/home/ec2-user/.aws/credentials [default]`
      and re-run; idempotency means unchanged users land as `skipped`.
    - Single-user onboarding: `--user <name>`.
    - Reading the Run_Summary table and JSON forms.
    - Exit-code reference.
  - `SETUP_AWS/provisioning/sudoers-agentcore-creds.example` shows the narrow
    NOPASSWD allow-list (install/chown/chmod/python `-c` with rename) per
    design §"Sudo strategy". Document both the narrow form and the wider
    fallback.
  - _Requirements: design §"Sudo strategy", §"Open Questions"_

- [x] 18. Phase A — host smoke validation (gated, no live AWS calls)
  - `python3.12 tools/provision-agentcore-creds.py --all --dry-run --format table`
    on the live host as `ec2-user`. Assert the Run_Summary lists every eligible
    user and reports the disposition each *would* receive. No filesystem
    modification.
  - Repeat with `--format json` and validate against the documented JSON schema.
  - DONE 2026-06-09. Dry-run produced clean plan for all 8 eligible users; `ssm-user` correctly excluded via the exclude list.
  - _Validates: 10.6, 11.6, 11.7_

- [x] 19. Phase B — single-user live run (gated, STOP-AND-CONFIRM)
  - STOP-AND-CONFIRM: writes to a real user home dir and modifies their AWS
    credentials. Per the AWS write-safety policy.
  - First run on the user known to have the broken `AWS_PROFILE` line
    (`terry.mcguinness`) so the verification probe exercises both the new
    credentials and the corrected `mcp.json`:
    `sudo -u ec2-user python3.12 tools/provision-agentcore-creds.py --user terry.mcguinness --verify`
  - Confirm disposition `updated` and probe success. If verification fails
    or any disposition is `failed`, STOP and report.
  - DONE 2026-06-09. Single-user run on Anton verified `[agentcore-rag]` profile + MCP config + Anton seeing tools in Kiro panel. Terry's broken `AWS_PROFILE` line was rewritten to the correct profile.
  - _Validates: 8.1, 9.1, 11.4, 17.4_

- [x] 20. Phase C — bulk live run (gated)
  - STOP-AND-CONFIRM before bulk write.
  - `sudo -u ec2-user python3.12 tools/provision-agentcore-creds.py --all --verify`
  - Expect every other user with no pre-existing `[agentcore-rag]` section to
    be `created`; a re-run must classify all users as `skipped` per the
    Idempotency property.
  - Capture the JSON Run_Summary as the audit artifact.
  - DONE 2026-06-09. Bulk run results: 6 created, 1 updated (terry), 1 skipped (anton — already provisioned). Idempotency confirmed: re-run all 8 skipped.
  - _Validates: 7.3, 10.2, 10.7, 11.4, 17.1_

- [x] 21. Final checkpoint
  - All unit + property tests green.
  - Phase A, B, C live runs complete with documented Run_Summary captures.
  - Runbook posted; sudoers example reviewed by the host owner.
  - Mark spec COMPLETE in `.kiro/steering/12-multi-tenant-gap-tracker.md` and
    delete the stop-gap script `SETUP_AWS/provisioning/fix-user-mcp-aws-profile.sh`
    (which only treated the symptom).
  - DONE 2026-06-09. All 8 dev accounts provisioned. Runbook at `SETUP_AWS/provisioning/RUNBOOK_agentcore_creds.md`.

## Notes

- **Why a single Python file rather than bash**: stdlib gives us atomic temp+rename
  (`os.rename` + `os.fsync(dirfd)`), strict JSON serialization with key-order
  preservation, ConfigParser for source reads, and a clean `SecretRedactor` API
  routing every log path. The bash equivalent for byte-faithful INI edits and
  JSON manipulation is fragile and harder to test.
- **Why stdlib only**: rotation must be a single file copy + a re-run with no
  pip/uv steps. Pulling in third-party deps would force us to manage venvs per
  user, which is out of scope.
- **Critical path is the writers**: tasks 8 and 9 carry the hardest correctness
  bar — byte-faithful preservation of non-managed content under concurrent reads.
  The PBT properties 1, 2, 4 (task 15) are the durable test for these.
- **Stop-gap cleanup**: the earlier `fix-user-mcp-aws-profile.sh` removed the
  `AWS_PROFILE` env line from `mcp.json` as a symptom fix. The proper resolution
  is the opposite — *install* the `[agentcore-rag]` profile in
  `~/.aws/credentials` so the existing reference resolves. Task 21 deletes the
  stop-gap once the bulk run succeeds.
- **No deploy involved**: this is a host-side operations script. There is no
  AgentCore runtime change, no container rebuild, no `update-agent-runtime`.
  The only host change is the optional sudoers tightening documented in the
  runbook.
- **Ownership and sudo**: tasks 7, 8, 9, 11 issue `subprocess.run(["sudo", ...])`
  calls. The script never opens another user's home directory from its own UID.
  The unit tests mock `subprocess.run` and assert the argv shape; the live
  validation (tasks 18–20) exercises real sudo.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2", "2.1"] },
    { "id": 2, "tasks": ["3", "3.1", "4", "4.1", "5", "5.1", "6", "6.1"] },
    { "id": 3, "tasks": ["7"] },
    { "id": 4, "tasks": ["8", "8.1", "9", "9.1"] },
    { "id": 5, "tasks": ["10", "11", "11.1"] },
    { "id": 6, "tasks": ["12"] },
    { "id": 7, "tasks": ["13", "14", "14.1"] },
    { "id": 8, "tasks": ["15", "16", "17"] },
    { "id": 9, "tasks": ["18"] },
    { "id": 10, "tasks": ["19"] },
    { "id": 11, "tasks": ["20"] },
    { "id": 12, "tasks": ["21"] }
  ]
}
```

Wave 0 scaffolds the file. Wave 1 lands the redactor (every later task uses it
for logging). Wave 2 implements the four independent components in parallel
(identity gate, config, creds loader, user discovery). Wave 3 is the dir
provisioner that the file writers depend on. Wave 4 is the byte-faithful file
writers (the hardest correctness bar). Wave 5 layers idempotency check and the
verification probe. Wave 6 wires the per-user driver. Wave 7 finishes the
top-level (RunSummary, main). Wave 8 runs the test campaigns and lands the
runbook in parallel. Waves 9–11 are the gated live rollout (smoke → single-user
→ bulk). Wave 12 closes the spec.
