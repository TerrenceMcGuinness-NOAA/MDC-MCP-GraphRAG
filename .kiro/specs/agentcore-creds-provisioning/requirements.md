# Requirements Document

## Introduction

This feature codifies a provisioning automation that grants every current and
future per-user OS account on the shared EC2 instance `ip-10-40-136-39` (AWS
account `903050880929`) the ability to use the `agentcore-mcp-rag` MCP server
from Kiro. The shared EC2 host runs Kiro under multiple human OS accounts (e.g.
`terry.mcguinness`, `emc-user`, plus future users). The MCP server is a stdio
proxy (`tools/agentcore-kiro-proxy.py`) that calls AWS Bedrock AgentCore via
boto3; without per-user AWS credentials boto3 falls back to the EC2 instance
role, which lacks `bedrock-agentcore:InvokeAgentRuntime`, causing Kiro to show
"No tools available" for the server.

The fix that has been validated by hand for `terry.mcguinness` is: copy the
master IAM keys from `/home/ec2-user/.aws/credentials [default]` into each
target user's `~/.aws/credentials` under a named profile `[agentcore-rag]`,
ensure each user's `~/.kiro/settings/mcp.json` `agentcore-mcp-rag` server entry
sets `AWS_PROFILE=agentcore-rag` and `AWS_REGION=us-east-1`, then verify with
`aws sts get-caller-identity` and an MCP probe.

This spec defines a provisioning script (the "Provisioning_Script") plus a
runbook that performs that fix once, idempotently, for every eligible user, and
provides a single-user onboarding mode for accounts created later. Key rotation
in AWS, IAM identity management, and any change requiring AWS console / admin
access are explicitly out of scope.

## Glossary

- **Provisioning_Script**: The bash or Python program defined by this spec that
  installs AWS credentials and MCP configuration for one or more target users.
- **Operator**: The OS account that executes the Provisioning_Script. The
  Operator is fixed by this spec to be the OS user `ec2-user`.
- **Source_Credentials_File**: The fixed file path
  `/home/ec2-user/.aws/credentials` from which the master IAM access key id and
  secret access key are read.
- **Source_Profile_Name**: The profile section name `default` inside the
  Source_Credentials_File from which keys are read.
- **Target_User**: A single per-user OS account on the EC2 instance that the
  Provisioning_Script provisions.
- **Eligible_User_Set**: The computed set of OS accounts that the
  Provisioning_Script will provision in bulk mode (see Requirement 2).
- **Exclusion_List**: A configurable list of OS account names that are excluded
  from the Eligible_User_Set even if they would otherwise qualify.
- **AWS_Profile_Name**: The fixed profile-section name `agentcore-rag` used in
  the Target_User AWS credentials file and referenced by `AWS_PROFILE` in the
  Target_User MCP config file.
- **AWS_Credentials_File**: The file `~/.aws/credentials` of a Target_User.
- **AWS_Config_Directory**: The directory `~/.aws/` of a Target_User.
- **MCP_Config_File**: The file `~/.kiro/settings/mcp.json` of a Target_User.
- **MCP_Settings_Directory**: The directory `~/.kiro/settings/` of a Target_User.
- **Server_Entry**: The JSON object stored at
  `mcpServers["agentcore-mcp-rag"]` inside a MCP_Config_File.
- **Managed_Keys**: The exact set of JSON keys in a Server_Entry that the
  Provisioning_Script is permitted to create or modify, namely `command`,
  `args`, and the two environment variables `env.AWS_REGION` and
  `env.AWS_PROFILE`.
- **AgentCore_Runtime_ARN**: The configurable AWS Bedrock AgentCore runtime ARN
  passed to the proxy via `--runtime-id`. Default value is
  `arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/mdc_mcp_rag_server_python-v5K2F8BGrN`.
- **AWS_Region**: The configurable AWS region. Default value is `us-east-1`.
- **Proxy_Path**: The configurable absolute filesystem path of the MCP stdio
  proxy. Default value is
  `/mdc-mcp-rag/eib-mcp-rag-server/tools/agentcore-kiro-proxy.py`.
- **Verification_Probe**: The pair of AWS calls `aws sts get-caller-identity`
  and `aws bedrock-agentcore-control list-agent-runtimes` invoked under a
  Target_User identity with `AWS_PROFILE=agentcore-rag` and `AWS_REGION` set
  to the configured AWS_Region.
- **Run_Summary**: The structured human-readable report emitted by the
  Provisioning_Script at the end of every run, classifying each Target_User as
  one of `created`, `updated`, `skipped`, or `failed`.
- **Bulk_Mode**: The Provisioning_Script execution mode that iterates over the
  full Eligible_User_Set.
- **Single_User_Mode**: The Provisioning_Script execution mode that provisions
  exactly one named Target_User.

## Requirements

### Requirement 1: Operator Identity Constraint

**User Story:** As a system administrator of the shared EC2 instance, I want the
Provisioning_Script to refuse to run as anyone other than `ec2-user`, so that
the script never operates without sudo and source-credentials access and so that
its behavior under any other identity is undefined.

#### Acceptance Criteria

1. WHEN the Provisioning_Script starts, THE Provisioning_Script SHALL determine
   the effective OS username and effective UID of the invoking process before
   reading the Source_Credentials_File and before writing to any Target_User
   home directory.
2. IF the effective OS username of the invoking process is not `ec2-user` and
   the effective UID is not `0`, THEN THE Provisioning_Script SHALL emit an
   error message to standard error naming the required Operator identity
   `ec2-user`, SHALL NOT modify any Target_User home directory, and SHALL exit
   with a non-zero status.
3. IF the effective UID of the invoking process is `0` (root) and the
   `SUDO_USER` environment variable is unset, empty, or not byte-equal to
   `ec2-user`, THEN THE Provisioning_Script SHALL emit an error message to
   standard error naming the required Operator identity `ec2-user`, SHALL NOT
   modify any Target_User home directory, and SHALL exit with a non-zero
   status.
4. WHILE the Provisioning_Script is running as `ec2-user` (effective username
   `ec2-user`, or effective UID `0` with `SUDO_USER` byte-equal to
   `ec2-user`), THE Provisioning_Script SHALL acquire elevated privileges via
   `sudo` only for the specific filesystem operations that target a
   Target_User home directory.

### Requirement 2: Eligible User Discovery

**User Story:** As a system administrator, I want the Provisioning_Script to
compute the set of human OS accounts to provision deterministically, so that
the same input host produces the same Eligible_User_Set on every run.

#### Acceptance Criteria

1. WHEN the Provisioning_Script runs in Bulk_Mode, THE Provisioning_Script
   SHALL enumerate candidate OS accounts via the host's NSS passwd database
   (the same view returned by `getent passwd`), so that NSS sources beyond
   `/etc/passwd` are honored.
2. THE Provisioning_Script SHALL include in the Eligible_User_Set every OS
   account whose home directory in the NSS passwd entry is byte-equal to
   `/home/<account-name>` where `<account-name>` is the login name of that
   entry, whose login shell is not `/sbin/nologin`, not `/usr/sbin/nologin`,
   and not `/bin/false`, and whose UID is greater than or equal to `1000`.
3. THE Provisioning_Script SHALL exclude from the Eligible_User_Set the OS
   accounts `ec2-user`, `root`, and any account name whose byte-wise value
   appears in the Exclusion_List.
4. WHERE an Exclusion_List file path is supplied via the `--exclude-file`
   command-line option, THE Provisioning_Script SHALL read that file and
   union into the Exclusion_List the trimmed value of every line for which:
   the line is not empty after stripping leading and trailing ASCII
   whitespace, and the first non-whitespace character is not `#`.
5. IF the path supplied via `--exclude-file` does not exist or is not
   readable by `ec2-user`, THEN THE Provisioning_Script SHALL emit an error
   message to standard error identifying the supplied path, SHALL NOT compute
   an Eligible_User_Set, SHALL NOT modify any filesystem state, and SHALL
   exit with a non-zero status.
6. WHEN the Eligible_User_Set is computed, THE Provisioning_Script SHALL log
   the resulting account names in ascending byte-wise (C-locale) order
   before performing any filesystem modification.

### Requirement 3: Source Credentials Loading

**User Story:** As an operator, I want the Provisioning_Script to read master
IAM keys from a single fixed source file, so that key rotation has a single
documented input.

#### Acceptance Criteria

1. THE Provisioning_Script SHALL read the AWS access key id and AWS secret
   access key from the `[default]` section of the Source_Credentials_File,
   stripping leading and trailing ASCII whitespace from each value, removing
   a single matching pair of surrounding `'` or `"` characters if present,
   and ignoring lines whose first non-whitespace character is `#` or `;`.
2. IF the Source_Credentials_File does not exist or is not readable by
   `ec2-user`, THEN THE Provisioning_Script SHALL emit an error message
   identifying the Source_Credentials_File path, SHALL NOT include any
   credential value in that error message, and SHALL exit with a non-zero
   status.
3. IF the `[default]` section of the Source_Credentials_File is missing, OR
   does not contain `aws_access_key_id`, OR does not contain
   `aws_secret_access_key`, OR either field is empty after stripping, THEN
   THE Provisioning_Script SHALL emit an error message naming the missing or
   empty field and the Source_Credentials_File path, SHALL NOT include any
   credential value in that error message, and SHALL exit with a non-zero
   status.
4. THE Provisioning_Script SHALL NOT write the loaded `aws_access_key_id`,
   `aws_secret_access_key`, or `aws_session_token` value to standard output,
   standard error, any log file, or any shell trace output (e.g. `set -x`),
   under any verbosity setting.
5. WHERE the `[default]` section of the Source_Credentials_File contains an
   `aws_session_token` field, THE Provisioning_Script SHALL parse that field
   using the same whitespace, quote, and comment rules defined in
   acceptance criterion 1.
6. IF the `[default]` section of the Source_Credentials_File does not contain
   an `aws_session_token` field, THEN THE Provisioning_Script SHALL treat
   the absence as non-fatal and SHALL NOT emit an error.

### Requirement 4: AWS Config Directory Provisioning

**User Story:** As a Target_User, I want my `~/.aws/` directory to exist with
correct ownership and permissions before any credential file is installed, so
that AWS credentials are not exposed to other OS accounts.

#### Acceptance Criteria

1. WHEN the Provisioning_Script provisions a Target_User and that Target_User's
   AWS_Config_Directory does not exist, THE Provisioning_Script SHALL create
   the AWS_Config_Directory.
2. WHEN the Provisioning_Script provisions a Target_User, THE
   Provisioning_Script SHALL set the AWS_Config_Directory mode to `0700`,
   overriding any pre-existing mode bits.
3. WHEN the Provisioning_Script provisions a Target_User, THE
   Provisioning_Script SHALL set the AWS_Config_Directory ownership to that
   Target_User's UID and primary GID, overriding any pre-existing ownership.
4. IF the AWS_Config_Directory path exists and is a symbolic link or any
   filesystem object other than a regular directory, THEN THE
   Provisioning_Script SHALL emit an error message identifying the path and
   the actual filesystem object type, SHALL NOT modify the path, SHALL
   classify that Target_User as `failed` in the Run_Summary, and SHALL
   continue to the next Target_User in Bulk_Mode.
5. WHEN the Provisioning_Script provisions a Target_User, THE
   Provisioning_Script SHALL complete all AWS_Config_Directory operations
   for that Target_User before writing the AWS_Credentials_File for that
   Target_User.
6. IF the Target_User's home directory does not exist, is not a regular
   directory, or is not owned by that Target_User's UID, THEN THE
   Provisioning_Script SHALL emit an error message identifying the home
   directory path, SHALL NOT create or modify any filesystem path under it,
   SHALL classify that Target_User as `failed` in the Run_Summary, and SHALL
   continue to the next Target_User in Bulk_Mode.

### Requirement 5: AWS Credentials File Provisioning

**User Story:** As a Target_User, I want the `[agentcore-rag]` profile in my
`~/.aws/credentials` file to contain the master IAM keys with strict ownership
and permissions, so that the Kiro MCP proxy can authenticate as my IAM
identity without exposing keys to other accounts.

#### Acceptance Criteria

1. WHEN the Provisioning_Script provisions a Target_User, THE
   Provisioning_Script SHALL ensure that the Target_User's
   AWS_Credentials_File exists and contains exactly one profile section whose
   header is `[agentcore-rag]`, creating the file and any missing parent
   directories if they do not already exist.
2. WHEN the Provisioning_Script writes the `[agentcore-rag]` profile section,
   THE Provisioning_Script SHALL set the `aws_access_key_id` field to the
   value of the `aws_access_key_id` loaded from the Source_Credentials_File
   `[default]` section, with surrounding ASCII whitespace stripped.
3. WHEN the Provisioning_Script writes the `[agentcore-rag]` profile section,
   THE Provisioning_Script SHALL set the `aws_secret_access_key` field to the
   value of the `aws_secret_access_key` loaded from the
   Source_Credentials_File `[default]` section, with surrounding ASCII
   whitespace stripped.
4. WHEN the Provisioning_Script writes the AWS_Credentials_File, THE
   Provisioning_Script SHALL set the file mode to `0600` (owner read/write
   only; no group or world permissions) before the new content becomes
   observable to other processes.
5. WHEN the Provisioning_Script writes the AWS_Credentials_File, THE
   Provisioning_Script SHALL set the file ownership to the Target_User's UID
   and primary GID before the new content becomes observable to other
   processes.
6. IF the Target_User's AWS_Credentials_File already contains content outside
   the `[agentcore-rag]` section, THEN THE Provisioning_Script SHALL preserve
   that content byte-for-byte, including all other profile sections, all
   comment lines, all blank lines, and the original relative ordering of
   all sections that are not `[agentcore-rag]`.
7. THE Provisioning_Script SHALL NOT create any new profile section in the
   Target_User's AWS_Credentials_File whose header is not exactly
   `[agentcore-rag]`.
8. IF the Target_User's AWS_Credentials_File already contains a profile
   section named `[agentcore-rag]` when provisioning begins, THEN THE
   Provisioning_Script SHALL replace that entire section with one containing
   only the `aws_access_key_id` and `aws_secret_access_key` fields specified
   in criteria 2 and 3, discarding any other fields previously present
   within that section.
9. WHEN the Provisioning_Script writes the AWS_Credentials_File, THE
   Provisioning_Script SHALL perform the update atomically such that any
   concurrent reader observes either the previous complete file content or
   the new complete file content with mode `0600` and the Target_User's UID
   and primary GID, and never a truncated, zero-length, or partially-written
   file.

### Requirement 6: MCP Config File Provisioning

**User Story:** As a Target_User, I want my `~/.kiro/settings/mcp.json` to
declare the `agentcore-mcp-rag` server entry pointing at the proxy, the runtime
ARN, the AWS region, and the `agentcore-rag` profile, so that Kiro can launch
the MCP server with the correct credentials.

#### Acceptance Criteria

1. WHEN the Provisioning_Script provisions a Target_User and the
   MCP_Settings_Directory does not exist, THE Provisioning_Script SHALL create
   the MCP_Settings_Directory with ownership set to that Target_User's UID
   and primary GID and mode set to `0700`.
2. WHEN the Provisioning_Script provisions a Target_User and the
   MCP_Config_File does not exist, THE Provisioning_Script SHALL create the
   MCP_Config_File containing a JSON object with a top-level `mcpServers`
   object that contains exactly one Server_Entry keyed `agentcore-mcp-rag`.
3. WHEN the Provisioning_Script writes the MCP_Config_File, THE
   Provisioning_Script SHALL set the file ownership to the Target_User's UID
   and primary GID and the file mode to `0600`.
4. THE Provisioning_Script SHALL set the Server_Entry `command` field to the
   JSON string `"python3.12"`.
5. THE Provisioning_Script SHALL set the Server_Entry `args` field to the JSON
   array `[Proxy_Path, "--runtime-id", AgentCore_Runtime_ARN]`, replacing any
   pre-existing value of `args` in its entirety because `args` is a
   Managed_Key.
6. THE Provisioning_Script SHALL set the Server_Entry `env.AWS_REGION` field
   to the configured AWS_Region as a JSON string.
7. THE Provisioning_Script SHALL set the Server_Entry `env.AWS_PROFILE` field
   to the JSON string `"agentcore-rag"`, which is equal to AWS_Profile_Name.
8. WHERE the MCP_Config_File already contains a top-level `mcpServers` object
   with server entries other than `agentcore-mcp-rag`, THE Provisioning_Script
   SHALL leave the byte-equivalent JSON content of those server entries,
   their key order, and their value types unchanged.
9. WHERE the MCP_Config_File already contains a Server_Entry keyed
   `agentcore-mcp-rag`, THE Provisioning_Script SHALL leave every member of
   that Server_Entry whose key is not in Managed_Keys byte-equivalent in
   value, key order, and type to its pre-invocation state, including but not
   limited to `disabled`, `autoApprove`, `disabledTools`, and any environment
   variables in `env` other than `AWS_REGION` and `AWS_PROFILE`.
10. WHERE the MCP_Config_File already contains JSON members at the top level
    other than `mcpServers`, THE Provisioning_Script SHALL leave those members
    byte-equivalent in value, key order, and type to their pre-invocation
    state.
11. IF the MCP_Config_File exists and its content is not valid JSON, THEN THE
    Provisioning_Script SHALL emit an error message identifying the
    MCP_Config_File path, SHALL NOT modify the MCP_Config_File, SHALL classify
    that Target_User as `failed` in the Run_Summary, and SHALL continue to
    the next Target_User in Bulk_Mode.
12. WHEN the Provisioning_Script writes the MCP_Config_File, THE
    Provisioning_Script SHALL perform the update atomically such that any
    concurrent reader observes either the previous complete JSON content or
    the new complete JSON content, and never a truncated, zero-length, or
    partially-written file.
13. WHEN the Provisioning_Script writes the MCP_Config_File, THE
    Provisioning_Script SHALL serialize the JSON with two-space indentation
    and a trailing newline, SHALL preserve the relative key order of every
    pre-existing key it does not modify, and SHALL append any newly-added
    Managed_Keys after pre-existing keys at the same JSON object level.

### Requirement 7: Idempotency

**User Story:** As an operator, I want the Provisioning_Script to be safe to
re-run, so that I can run it on every host change, on a schedule, or after
master-key rotation without causing drift or duplicate state.

#### Acceptance Criteria

1. WHEN the Provisioning_Script provisions a Target_User and the Target_User's
   AWS_Credentials_File already contains an `[agentcore-rag]` profile whose
   `aws_access_key_id` and `aws_secret_access_key` fields are byte-equal to
   the values loaded from the Source_Credentials_File, THE Provisioning_Script
   SHALL NOT alter the byte content of the AWS_Credentials_File, SHALL NOT
   alter any other profile section in that file, and SHALL NOT alter any
   field in the `[agentcore-rag]` profile section beyond the two managed
   fields.
2. WHEN the Provisioning_Script provisions a Target_User and the Target_User's
   MCP_Config_File parses to a JSON value whose `agentcore-mcp-rag`
   Server_Entry has Managed_Keys whose parsed values are equal (in JSON
   structural sense, ignoring whitespace and key ordering) to the values
   that would otherwise be written, THE Provisioning_Script SHALL NOT alter
   the byte content of the MCP_Config_File, SHALL NOT alter any non-managed
   field in the `agentcore-mcp-rag` Server_Entry, and SHALL NOT alter any
   other Server_Entry.
3. WHEN the Provisioning_Script is invoked twice in succession on the same
   host with the same arguments and the same Source_Credentials_File contents,
   THE Provisioning_Script SHALL classify, in the second invocation, every
   Target_User in the Eligible_User_Set as `skipped` in its Run_Summary,
   where `skipped` denotes that neither the AWS_Credentials_File nor the
   MCP_Config_File of that Target_User had its byte content modified during
   the second invocation.
4. WHEN the Provisioning_Script provisions a Target_User and that
   Target_User's AWS_Credentials_File and MCP_Config_File did not exist
   before the run and were created during the run, THE Provisioning_Script
   SHALL classify that Target_User as `created` in the Run_Summary; WHEN
   either file existed before the run and had its byte content modified
   during the run, THE Provisioning_Script SHALL classify that Target_User
   as `updated`.
5. THE Provisioning_Script SHALL re-assert the AWS_Credentials_File mode at
   `0600` and ownership at the Target_User's UID and primary GID on every
   run, including runs that make no content change to that file, where mode
   or ownership re-assertion that does not alter the file's byte content
   SHALL NOT cause the Target_User to be classified as anything other than
   `skipped` for purposes of acceptance criterion 3.
6. THE Provisioning_Script SHALL re-assert the MCP_Config_File mode at
   `0600` and ownership at the Target_User's UID and primary GID on every
   run, including runs that make no content change to that file, where mode
   or ownership re-assertion that does not alter the file's byte content
   SHALL NOT cause the Target_User to be classified as anything other than
   `skipped` for purposes of acceptance criterion 3.

### Requirement 8: Verification Probe

**User Story:** As an operator, I want the Provisioning_Script to optionally
verify that each provisioned Target_User can actually call AWS Bedrock
AgentCore, so that I have evidence the provisioning worked end-to-end before I
walk away.

#### Acceptance Criteria

1. WHERE the `--verify` command-line option is supplied, THE Provisioning_Script
   SHALL execute the Verification_Probe for every Target_User that the current
   run classifies as `created`, `updated`, or `skipped`.
2. WHEN the Verification_Probe runs for a Target_User, THE Provisioning_Script
   SHALL execute the AWS calls under the Target_User's UID with environment
   variables `AWS_PROFILE=agentcore-rag`, `AWS_REGION` set to the configured
   AWS_Region, and `HOME` set to the Target_User's home directory.
3. IF the `aws sts get-caller-identity` call exits with a non-zero status, OR
   does not complete within 30 seconds of being invoked, for a Target_User,
   THEN THE Provisioning_Script SHALL classify that Target_User as `failed`
   in the Run_Summary, and SHALL record in the per-user reason whether the
   failure was a timeout or a non-zero exit.
4. IF the `aws bedrock-agentcore-control list-agent-runtimes` call exits with
   a non-zero status, OR does not complete within 30 seconds of being
   invoked, for a Target_User, THEN THE Provisioning_Script SHALL classify
   that Target_User as `failed` in the Run_Summary, and SHALL record in the
   per-user reason whether the failure was a timeout or a non-zero exit.
5. THE Provisioning_Script SHALL NOT include the response body of
   `aws sts get-caller-identity` or
   `aws bedrock-agentcore-control list-agent-runtimes` verbatim in the
   Run_Summary unless the `--verbose` command-line option is supplied.

### Requirement 9: Single-User Onboarding Mode

**User Story:** As an operator onboarding a new developer, I want to provision
exactly one named Target_User without touching anyone else's home directory,
so that I can add a single account safely without re-running the bulk job.

#### Acceptance Criteria

1. WHERE the `--user <name>` command-line option is supplied, THE
   Provisioning_Script SHALL operate in Single_User_Mode and SHALL set the
   Target_User to the OS account named `<name>`.
2. WHILE the Provisioning_Script is in Single_User_Mode, THE Provisioning_Script
   SHALL NOT create, modify, or delete any filesystem path under any home
   directory recorded in the NSS passwd database other than the home
   directory of the named Target_User.
3. IF the named Target_User does not exist in the NSS passwd database, THEN
   THE Provisioning_Script SHALL emit an error message identifying the
   missing user, SHALL NOT modify any filesystem path, and SHALL exit with
   a non-zero status.
4. IF the named Target_User is `ec2-user`, `root`, or appears in the
   Exclusion_List, THEN THE Provisioning_Script SHALL emit an error message
   identifying the conflict, SHALL NOT modify any filesystem path, and SHALL
   exit with a non-zero status.
5. IF the named Target_User has a UID less than `1000` in the NSS passwd
   database, THEN THE Provisioning_Script SHALL emit an error message
   identifying the UID and the eligibility threshold, SHALL NOT modify any
   filesystem path, and SHALL exit with a non-zero status.
6. IF the named Target_User has a login shell of `/sbin/nologin`,
   `/usr/sbin/nologin`, or `/bin/false` in the NSS passwd database, THEN THE
   Provisioning_Script SHALL emit an error message identifying the
   non-interactive shell, SHALL NOT modify any filesystem path, and SHALL
   exit with a non-zero status.
7. IF the named Target_User has a home directory in the NSS passwd database
   that is not byte-equal to `/home/<name>`, THEN THE Provisioning_Script
   SHALL emit an error message identifying the actual home directory path,
   SHALL NOT modify any filesystem path, and SHALL exit with a non-zero
   status.

### Requirement 10: Bulk Provisioning Mode

**User Story:** As an operator running the script on a host where every
existing user needs the fix, I want a single command that walks the entire
Eligible_User_Set, so that I do not have to script the iteration myself.

#### Acceptance Criteria

1. WHERE the `--all` command-line option is supplied and the `--user` option is
   not supplied, THE Provisioning_Script SHALL operate in Bulk_Mode.
2. WHILE the Provisioning_Script is in Bulk_Mode, THE Provisioning_Script
   SHALL process the Eligible_User_Set in ascending POSIX C-locale order of
   OS account name, processing each Target_User exactly once per invocation.
3. IF provisioning a single Target_User fails in Bulk_Mode, THEN THE
   Provisioning_Script SHALL classify that Target_User as `failed` in the
   Run_Summary with a per-user reason recording the failure cause, and SHALL
   continue to process every remaining Target_User in the Eligible_User_Set.
4. IF both `--all` and `--user` are supplied on the same invocation, THEN THE
   Provisioning_Script SHALL emit an error message identifying the conflict,
   SHALL NOT modify any Target_User home directory, and SHALL exit with a
   non-zero status.
5. IF neither `--all` nor `--user` is supplied on the same invocation, THEN
   THE Provisioning_Script SHALL emit an error message stating that exactly
   one of `--all` or `--user` is required, SHALL NOT modify any filesystem
   path, and SHALL exit with a non-zero status.
6. WHERE the `--dry-run` command-line option is supplied, WHILE the
   Provisioning_Script is in Bulk_Mode, THE Provisioning_Script SHALL emit a
   Run_Summary listing the Target_Users that would have been processed and
   the disposition each would have received, and SHALL NOT create, modify,
   or delete any filesystem path under any Target_User home directory.
7. WHEN the Provisioning_Script completes a Bulk_Mode run, THE
   Provisioning_Script SHALL exit with status `0` if and only if every
   Target_User in the Run_Summary has a disposition other than `failed`, and
   SHALL exit with a non-zero status code distinct from the
   argument-conflict status code from criteria 4 and 5 if any Target_User
   has disposition `failed`.

### Requirement 11: Run Summary Output

**User Story:** As an operator, I want a single summary table at the end of
every run that tells me what changed, so that I can audit the run quickly.

#### Acceptance Criteria

1. WHEN the Provisioning_Script finishes processing all Target_Users, THE
   Provisioning_Script SHALL write the Run_Summary to standard output.
2. THE Run_Summary SHALL include one row per processed Target_User containing
   the Target_User name, a per-user disposition value drawn from the set
   {`created`, `updated`, `skipped`, `failed`}, and a reason string of at
   most 200 ASCII characters; reason strings longer than 200 characters
   SHALL be truncated to the first 200 characters with the final three
   characters replaced by `...`.
3. THE Run_Summary SHALL include an aggregate count for each disposition
   value in the set {`created`, `updated`, `skipped`, `failed`}, where any
   disposition not represented by any row SHALL be reported with count `0`.
4. IF every Target_User in the Run_Summary has a disposition other than
   `failed`, THEN THE Provisioning_Script SHALL exit with status code `0`.
5. IF any Target_User has disposition `failed`, THEN THE Provisioning_Script
   SHALL exit with a non-zero status code in the inclusive range `1` to
   `255`.
6. WHEN the Eligible_User_Set in Bulk_Mode is empty (no candidate matched the
   eligibility predicate after exclusions), THE Provisioning_Script SHALL
   write a Run_Summary with zero per-user rows, aggregate count `0` for
   every disposition, and SHALL exit with status code `0`.
7. WHERE the `--format json` command-line option is supplied, THE
   Provisioning_Script SHALL write the Run_Summary as a single JSON object
   to standard output containing the per-user rows and aggregate counts
   defined in criteria 2 and 3, and SHALL NOT write any human-readable
   table form to standard output.

### Requirement 12: Secret Redaction

**User Story:** As a security-conscious operator, I want the Provisioning_Script
to never disclose the master IAM keys in any output it produces, so that
re-running the script in a shared terminal or CI log does not leak credentials.

#### Acceptance Criteria

1. THE Provisioning_Script SHALL NOT write the value of `aws_access_key_id`
   or `aws_secret_access_key` loaded from the Source_Credentials_File to
   standard output, standard error, or any log file under any verbosity
   setting, including a debug-level setting.
2. WHERE log output references the loaded `aws_access_key_id`, THE
   Provisioning_Script SHALL refer to it by the literal string
   `<aws_access_key_id redacted>`.
3. WHERE log output references the loaded `aws_secret_access_key`, THE
   Provisioning_Script SHALL refer to it by the literal string
   `<aws_secret_access_key redacted>`.
4. WHEN the Provisioning_Script terminates abnormally because of an unhandled
   exception, THE Provisioning_Script SHALL ensure that any traceback
   written to standard output, standard error, or a log file does not
   contain the loaded `aws_access_key_id` or `aws_secret_access_key`
   values.
5. WHERE the Provisioning_Script logs a subprocess invocation (its command,
   arguments, or environment variables), THE Provisioning_Script SHALL
   substitute the loaded `aws_access_key_id` value with the literal string
   `<aws_access_key_id redacted>` and the loaded `aws_secret_access_key`
   value with the literal string `<aws_secret_access_key redacted>` in
   every such log line.
6. THE Provisioning_Script SHALL NOT include the contents of, or the path
   to, any temporary file used to hold the loaded `aws_access_key_id` or
   `aws_secret_access_key` value in any error message, diagnostic message,
   or log line.
7. WHEN the Provisioning_Script receives `SIGINT` or `SIGTERM`, THE
   Provisioning_Script SHALL flush any partial Run_Summary or log output
   with the redaction substitutions defined in criteria 2, 3, and 5
   applied, and SHALL exit with a non-zero status.

### Requirement 13: Configurable Runtime Parameters

**User Story:** As an operator who must redeploy the AgentCore runtime
periodically, I want the runtime ARN, region, and proxy path to be parameters
of the Provisioning_Script rather than hard-coded constants, so that I can
re-provision after a redeploy without editing the script.

#### Acceptance Criteria

1. WHERE the `--runtime-arn <arn>` command-line option is supplied, THE
   Provisioning_Script SHALL use that value as the AgentCore_Runtime_ARN,
   taking precedence over any environment variable or default value.
2. WHERE the `--region <name>` command-line option is supplied, THE
   Provisioning_Script SHALL use that value as the AWS_Region, taking
   precedence over any environment variable or default value.
3. WHERE the `--proxy-path <path>` command-line option is supplied, THE
   Provisioning_Script SHALL use that value as the Proxy_Path, taking
   precedence over any environment variable or default value.
4. WHERE no command-line option for a given parameter is supplied, AND the
   corresponding environment variable is set and non-empty, THE
   Provisioning_Script SHALL use the environment variable value:
   `AGENTCORE_RUNTIME_ARN` for AgentCore_Runtime_ARN, `AWS_REGION` for
   AWS_Region, and `AGENTCORE_PROXY_PATH` for Proxy_Path.
5. WHERE neither a command-line option nor a corresponding environment
   variable is set for a given parameter, THE Provisioning_Script SHALL use
   the default value defined in the Glossary entry for that parameter.
6. IF the resolved AgentCore_Runtime_ARN does not match the regular
   expression
   `^arn:aws:bedrock-agentcore:[a-z0-9-]+:[0-9]{12}:runtime/[A-Za-z0-9_.-]+$`,
   THEN THE Provisioning_Script SHALL emit an error message identifying the
   malformed ARN and the source from which it was resolved (CLI option,
   environment variable, or default), and SHALL exit with a non-zero status.
7. IF the resolved AWS_Region does not match the regular expression
   `^[a-z]{2}-[a-z]+-[0-9]+$`, THEN THE Provisioning_Script SHALL emit an
   error message identifying the malformed region and the source from which
   it was resolved (CLI option, environment variable, or default), and
   SHALL exit with a non-zero status.
8. IF the resolved Proxy_Path, after resolving any symbolic links to its
   target, does not refer to an existing regular file readable by
   `ec2-user`, THEN THE Provisioning_Script SHALL emit an error message
   identifying the missing or unreadable path and the source from which it
   was resolved (CLI option, environment variable, or default), and SHALL
   exit with a non-zero status.

### Requirement 14: Cross-File Profile-Name Invariant

**User Story:** As a Target_User, I want the AWS profile name written into my
`~/.aws/credentials` file to always match the `AWS_PROFILE` value written into
my `~/.kiro/settings/mcp.json` for the `agentcore-mcp-rag` Server_Entry, so
that the proxy never silently picks up the wrong profile.

#### Acceptance Criteria

1. WHEN the Provisioning_Script completes a successful provisioning run for
   a Target_User, THE AWS_Credentials_File of that Target_User SHALL contain
   exactly one profile section whose header name, after stripping leading
   and trailing ASCII whitespace, is byte-for-byte identical (case-sensitive)
   to the value of the `AWS_PROFILE` field in the `agentcore-mcp-rag`
   Server_Entry of that Target_User's MCP_Config_File, with no other profile
   section in the file matching that name under a case-insensitive
   comparison.
2. WHEN the Provisioning_Script completes a successful provisioning run for
   a Target_User, THE Provisioning_Script SHALL have written the literal
   string `agentcore-rag` (lowercase ASCII, no surrounding whitespace, no
   quoting characters) as both the AWS_Credentials_File profile section
   header name and the `AWS_PROFILE` field value in the `agentcore-mcp-rag`
   Server_Entry, and SHALL NOT leave any other profile section header or
   `AWS_PROFILE` value in either file that differs from `agentcore-rag` only
   by case or whitespace.
3. IF the AWS_Credentials_File or the MCP_Config_File of a Target_User is
   modified by any process other than the Provisioning_Script between the
   Provisioning_Script reading and writing that file within a single
   provisioning run, THEN THE Provisioning_Script SHALL abort that
   Target_User's provisioning without committing a partial cross-file
   update, SHALL leave each file either byte-equal to its pre-run content or
   fully updated to the new `agentcore-rag` value (never an intermediate
   mixed state), SHALL classify that Target_User as `failed` in the
   Run_Summary with a per-user reason indicating concurrent modification,
   and SHALL continue to the next Target_User in Bulk_Mode.

### Requirement 15: Documentation Deliverables

**User Story:** As an operator who inherits this host, I want a README-style
runbook checked into the repository that explains when to run the
Provisioning_Script, how to add or exclude users, how to rotate the master
keys, and how to verify the result, so that I do not have to reverse-engineer
the script from its source.

#### Acceptance Criteria

1. THE feature SHALL produce a runbook file at the absolute repository path
   `.kiro/specs/agentcore-creds-provisioning/RUNBOOK.md` formatted as a
   Markdown document.
2. THE runbook file SHALL contain top-level section headings titled
   "Operator Identity", "Bulk Mode", "Single User Mode", "Exclude File
   Format", "Run Summary Dispositions", "Master Key Rotation",
   "Verification", "Troubleshooting", "References", and "Out of Scope".
3. THE runbook file SHALL document the intended Operator identity, the
   Bulk_Mode invocation command rendered as a fenced code block, the
   Single_User_Mode invocation command rendered as a fenced code block, the
   format of the `--exclude-file` argument with at least one worked example
   rendered as a fenced code block, and every Run_Summary disposition value
   defined in Requirement 11 together with the condition under which it is
   emitted.
4. THE runbook file SHALL document the master-key rotation procedure as the
   ordered steps: (a) replace the values inside the `[default]` section of
   the Source_Credentials_File, (b) re-run the Provisioning_Script in
   Bulk_Mode with the `--verify` option, with the re-run command rendered
   as a fenced code block.
5. THE runbook file SHALL contain explicit cross-references, formatted as
   Markdown links, to the steering documents
   `~/.kiro/steering/01-agentcore-mcp-for-global-workflow.md` and
   `~/.kiro/steering/02-agentcore-mcp-tool-guide.md` by their file paths,
   and to the verification probe semantics defined by the `--verify`
   option in Requirement 8.
6. THE runbook file SHALL contain a "Troubleshooting" section that, for
   each Run_Summary disposition value indicating failure, lists the
   recommended diagnostic action and the corresponding remediation step.
7. THE runbook file SHALL list every item declared out of scope by
   Requirement 16 under the "Out of Scope" heading.
8. IF the runbook file at
   `.kiro/specs/agentcore-creds-provisioning/RUNBOOK.md` does not exist, OR
   does not contain every section heading required by acceptance criterion
   2, OR does not contain every component named in acceptance criteria 3
   through 7, THEN the feature SHALL be considered non-compliant with this
   requirement.

### Requirement 16: Out-of-Scope Boundary

**User Story:** As a reviewer, I want the spec to declare explicitly which
adjacent activities are not part of this feature, so that the script's
responsibilities are bounded.

#### Acceptance Criteria

1. THE Provisioning_Script SHALL NOT call any AWS API in the namespaces
   `iam:*`, `sso-admin:*`, `identitystore:*`, or the action
   `sts:AssumeRole`, including but not limited to `iam:CreateUser`,
   `iam:DeleteUser`, `iam:CreateAccessKey`, `iam:UpdateAccessKey`,
   `iam:DeleteAccessKey`, `iam:CreateLoginProfile`, `iam:AttachUserPolicy`,
   `iam:PutUserPolicy`, `iam:DetachUserPolicy`, `iam:CreatePolicy`, and
   `iam:DeletePolicy`.
2. THE Provisioning_Script SHALL NOT create, modify, delete, rename, or
   change the permissions or ownership of any filesystem path under
   `tools/agentcore-kiro-proxy.py` or under the `mdc-mcp-rag` server source
   tree; the only filesystem paths the Provisioning_Script may write to are
   under `/home/<Target_User>` for some Target_User in the Eligible_User_Set
   of the current run.
3. THE Provisioning_Script SHALL NOT modify the EC2 instance profile, the
   EC2 instance role, any role trust policy, any inline role policy, any
   managed role policy, or any AWS resource other than read-only invocations
   of `sts:GetCallerIdentity` and the AgentCore APIs invoked by the
   Verification_Probe.
4. THE Provisioning_Script SHALL NOT rotate, regenerate, replace, or
   deactivate any IAM access key, including via AWS APIs, local commands, or
   subprocess invocations.
5. WHEN the Source_Credentials_File contents change between two
   Provisioning_Script runs, THE Provisioning_Script SHALL propagate the new
   credential values into every Target_User's AWS_Credentials_File on the
   next run, where this propagation is the only mechanism by which the
   Provisioning_Script reflects key rotation performed by an external
   operator.

### Requirement 17: Property-Test Correctness Properties

**User Story:** As a developer maintaining the Provisioning_Script, I want a
small set of generative correctness properties that the implementation must
satisfy, so that property-based tests can give me high confidence that
refactors do not regress idempotency, isolation, or secret handling.

#### Acceptance Criteria

1. FOR ALL pairs of consecutive Provisioning_Script invocations on the same
   host with the same arguments and unchanged Source_Credentials_File
   contents, where the Eligible_User_Set has cardinality between 1 and 32
   inclusive, the byte content of every Target_User's AWS_Credentials_File
   and MCP_Config_File after the second invocation SHALL be byte-equal to
   the content after the first invocation (idempotency property).
2. FOR ALL valid pre-existing MCP_Config_File contents that contain a
   `mcpServers` object, with at most 32 server entries and JSON nesting
   depth at most 4, every top-level JSON member of the MCP_Config_File
   other than `mcpServers`, every `mcpServers` entry whose key is not
   `agentcore-mcp-rag`, and every member of the `agentcore-mcp-rag`
   Server_Entry whose key is not in Managed_Keys SHALL parse to a
   canonical-form JSON value byte-equal to the canonical-form JSON value
   parsed from the pre-invocation file (preservation property).
3. FOR ALL combinations of command-line arguments (drawn from the valid
   inputs defined by Requirements 9, 10, and 13) and pre-existing filesystem
   states, where loaded `aws_access_key_id` is between 16 and 128 ASCII
   characters and `aws_secret_access_key` is between 1 and 256 ASCII
   characters, the captured standard output, standard error, and any file
   written by the Provisioning_Script SHALL NOT contain the contiguous byte
   sequence of the loaded `aws_access_key_id` or `aws_secret_access_key`
   (no-leak property).
4. FOR ALL Target_Users provisioned by a single Provisioning_Script
   invocation, the value of `AWS_PROFILE` in that Target_User's
   `agentcore-mcp-rag` Server_Entry SHALL be byte-equal, after stripping
   leading and trailing ASCII whitespace, to a profile-section header name
   that exists in that Target_User's AWS_Credentials_File (cross-file
   profile-name match property).
5. FOR ALL Single_User_Mode invocations of the Provisioning_Script with
   target `<name>` drawn from valid POSIX portable filename character set
   names of length 1 to 32 inclusive, no filesystem path under any
   `/home/<other>` directory where `<other>` is not byte-equal to `<name>`
   SHALL be created, modified, or deleted by that invocation, and no
   pre-existing path under any such `/home/<other>` SHALL have its mode,
   ownership, or content modification time changed by that invocation
   (single-user isolation property).
6. THE property-based test corpus SHALL include the following fixed
   corner-case inputs in addition to randomly generated inputs: an empty
   AWS_Credentials_File, a malformed JSON MCP_Config_File, a Target_User
   name of maximum POSIX portable length, an `aws_secret_access_key` value
   that contains JSON-significant characters (`"`, `\`, `\n`, `\t`), an
   absent AWS_Credentials_File, an absent MCP_Config_File, and an
   MCP_Config_File whose Server_Entry already contains the target
   Managed_Keys values byte-equal to the values that would be written.
