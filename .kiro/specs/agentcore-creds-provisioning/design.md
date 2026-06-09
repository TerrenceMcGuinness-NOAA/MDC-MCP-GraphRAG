# Design Document

## Overview

`provision-agentcore-creds.py` is a Python 3.12 stdlib-only provisioning tool
that runs once (or on demand) as `ec2-user` on the shared EC2 host and brings
every eligible per-user OS account up to spec for the `agentcore-mcp-rag` MCP
server: a `[agentcore-rag]` profile in each user's `~/.aws/credentials` and an
`agentcore-mcp-rag` server entry in each user's `~/.kiro/settings/mcp.json`.
It is idempotent, refuses to run under any identity other than `ec2-user`,
escalates only via `sudo` for per-target filesystem writes, never logs the
master keys, and emits a Run_Summary classifying each user as `created` /
`updated` / `skipped` / `failed`.

## Architecture

```
                         ec2-user shell
                              │
                              ▼
                    ┌──────────────────┐
                    │  argparse + main │
                    └─────────┬────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   IdentityGate   │  R1
                    └─────────┬────────┘  (refuse non-ec2-user; no side effects yet)
                              │
                              ▼
                    ┌──────────────────┐
                    │  ConfigResolver  │  R13
                    └─────────┬────────┘  (CLI > env > default; ARN/region regex; proxy path check)
                              │
                              ▼
                    ┌──────────────────┐
                    │ CredentialsLoader│  R3
                    └─────────┬────────┘  (parse [default]; never log values)
                              │
                              ▼
                    ┌──────────────────┐
                    │  UserDiscovery   │  R2, R9
                    └─────────┬────────┘  (NSS passwd; predicate; exclusion-file)
                              │
              Bulk_Mode       │      Single_User_Mode
              ┌───────────────┴───────────────┐
              ▼                               ▼
     ┌────────────────┐              ┌────────────────┐
     │  for each tgt  │              │   single tgt   │
     └───────┬────────┘              └───────┬────────┘
             │                               │
             └──────────────┬────────────────┘
                            ▼
                  ┌────────────────────┐
                  │  UserProvisioner   │  R4–R7, R14
                  ├────────────────────┤
                  │  AwsConfigDir      │  R4
                  │  AwsCredsWriter    │  R5
                  │  McpConfigWriter   │  R6
                  └─────────┬──────────┘  (atomic temp+rename, sudo for ownership)
                            │
                            ▼
                  ┌────────────────────┐
                  │  VerificationProbe │  R8 (only if --verify)
                  └─────────┬──────────┘  (sudo -u target aws ..., 30s timeout)
                            │
                            ▼
                  ┌────────────────────┐
                  │   RunSummary       │  R11
                  └─────────┬──────────┘  (table or JSON; aggregate counts; exit code)
                            │
                            ▼
                          stdout

       cross-cutting:
         SecretRedactor (R12) wraps every Logger sink and excepthook
         Logger (stderr) — never receives raw key/secret bytes
```

Trust boundaries:

- The script process runs as **ec2-user**. No `setuid` is used.
- Per-target writes happen by spawning `sudo` subprocesses (`install`, `chown`,
  `chmod`, plus a single-shot `python -c` fragment for atomic rename + fsync).
  The script never opens another user's home directory directly from its own
  UID.
- The Verification_Probe runs `aws ...` under each target user via
  `sudo -u <target> -H env AWS_PROFILE=... AWS_REGION=... aws ...`.

## Components and Interfaces

### Implementation language and packaging

| Decision | Choice | Reason |
|---|---|---|
| Language | Python 3.12 | Already on host, used by the proxy; better atomic-write and JSON handling than bash |
| Dependencies | stdlib only (`argparse`, `configparser`, `json`, `os`, `pwd`, `signal`, `subprocess`, `re`, `sys`, `tempfile`, `dataclasses`) | No pip step in provisioning; rotation is one file copy + one re-run |
| File path | `tools/provision-agentcore-creds.py` | Co-located with the proxy it provisions for |
| Permissions | mode `0750`, owned by `ec2-user:ec2-user` | Only ec2-user (and root via sudo) needs to execute it; group bit allows `developers` to read for review |
| Invocation | `sudo -u ec2-user /usr/bin/python3.12 tools/provision-agentcore-creds.py --all --verify` | `ec2-user` runs directly; admins invoke via `sudo -u ec2-user` |

The configparser stdlib has a known limitation: it drops comments and blank
lines on round-trip. Because R5.6 demands byte-for-byte preservation of all
non-`agentcore-rag` content (including comments and blank lines), the
`AwsCredsWriter` does **not** use configparser for round-trip; it uses a
purpose-built section-aware line tokenizer. configparser is still used for
*reading* the source `[default]` section in `CredentialsLoader`.

### Module decomposition

| Module / class | Responsibility | Maps to |
|---|---|---|
| `IdentityGate` | Verify effective uid/username and SUDO_USER; abort before any side effect. | R1 |
| `ConfigResolver` | Resolve runtime ARN / region / proxy path with CLI > env > default precedence; validate via regex; check proxy path is a regular readable file (after symlink resolution). | R13 |
| `CredentialsLoader` | Read and parse `[default]` from `Source_Credentials_File`; expose `(access_key_id, secret_access_key, session_token | None)` to internal callers only. Never serialize. | R3 |
| `UserDiscovery` | Enumerate eligible users from `pwd.getpwall()`; apply predicate (UID, shell, home); union exclusion file; emit sorted list. | R2 |
| `Eligibility` | Pure predicate `is_eligible(pwd_entry, exclusion_set) -> (bool, reason)`. Reused by `--user` validation. | R2, R9 |
| `UserProvisioner` | Per-user driver: orchestrates `AwsConfigDir`, `AwsCredsWriter`, `McpConfigWriter` and produces a `RunRecord`. | R4–R7, R14 |
| `AwsConfigDir` | Ensure `~/.aws/` exists, mode 0700, owned by target user; reject symlinks/non-dirs. | R4 |
| `AwsCredsWriter` | Section-aware INI editor: read existing file (if any), replace exactly the `[agentcore-rag]` section, preserve everything else byte-for-byte, atomic write. | R5, R14 |
| `McpConfigWriter` | JSON editor: load (or fabricate) mcp.json, mutate the four `Managed_Keys` on the `agentcore-mcp-rag` server entry, preserve all other keys with their original ordering, atomic write. | R6, R14 |
| `Idempotency` | After-write comparator: byte-equality on creds file content; structural equivalence on MCP file (parse both sides, deep-equal Managed_Keys + verify non-managed unchanged). | R7 |
| `VerificationProbe` | Execute `sts get-caller-identity` and `bedrock-agentcore-control list-agent-runtimes` as the target user with 30s timeouts; classify timeout vs non-zero. | R8 |
| `RunSummary` | Collect `RunRecord` instances; render table or JSON; compute exit code. | R11 |
| `SecretRedactor` | Substitute the loaded access key id and secret values with the literal redaction strings in any text passed through `Logger.write`, in subprocess argv echoes, and in `sys.excepthook`. | R12 |
| `Logger` | Single sink for diagnostics on stderr. All writes flow through `SecretRedactor`. | R12 |
| `SignalHandler` | Install handlers for SIGINT/SIGTERM that flush the in-progress Run_Summary through the redactor before exit. | R12.7 |

### Algorithms

#### Identity gate (R1)

```python
def gate() -> None:
    euid = os.geteuid()
    euser = pwd.getpwuid(euid).pw_name
    sudo_user = os.environ.get("SUDO_USER", "")

    if euid == 0:
        if sudo_user != "ec2-user":
            die("Operator must be ec2-user (refusing root with SUDO_USER=%r)" % sudo_user)
    elif euser != "ec2-user":
        die("Operator must be ec2-user (running as %r)" % euser)
    # No filesystem read/write occurs before this point.
```

#### Source credential loading (R3)

`configparser.ConfigParser(interpolation=None, comment_prefixes=("#", ";"))`
is used to read `Source_Credentials_File`. After read, each value is stripped
of surrounding whitespace and a single matching pair of `'` or `"`. The loader
returns an `IamCreds` and immediately registers
`creds.access_key_id` and `creds.secret_access_key` (and the session token if
present) with `SecretRedactor` so downstream logs see redaction.

#### User discovery (R2)

```python
def eligible_users(exclusions: frozenset[str]) -> list[TargetUser]:
    out: list[TargetUser] = []
    for e in pwd.getpwall():                       # NSS-backed
        if e.pw_uid < 1000:               continue
        if e.pw_shell in NOLOGIN_SHELLS:   continue
        if e.pw_dir != f"/home/{e.pw_name}": continue
        if e.pw_name in {"ec2-user", "root"} | exclusions: continue
        out.append(TargetUser(e.pw_name, e.pw_uid, e.pw_gid, e.pw_dir, e.pw_shell))
    out.sort(key=lambda u: u.name.encode("ascii"))   # C-locale order
    return out
```

`--user <name>` reuses the predicate via `Eligibility.check_or_die(name, exclusions)`
to enforce R9.5–R9.7.

#### Credentials file write (R5, R7, R14)

```
def write_creds(target: TargetUser, creds: IamCreds, dry_run: bool) -> FileChange:
    1. Read existing /home/<u>/.aws/credentials via sudo cat (sudo only;
       no other access to the file's UID).
       - If missing, treat as zero sections.
       - On read error, return FileChange(failed, reason).
    2. Tokenize into [Section] preserving every line.
    3. Locate the [agentcore-rag] section, if any. Replace it with a fresh
       Section whose raw_lines are exactly:
          ["[agentcore-rag]\n",
           f"aws_access_key_id = {creds.access_key_id}\n",
           f"aws_secret_access_key = {creds.secret_access_key}\n"]
       If absent, append a new Section.
       (Other sections, comments, blank lines, ordering — untouched.)
    4. Serialize all sections back to bytes.
    5. Compare with pre-existing bytes:
          - byte-equal      -> disposition = skipped
          - new bytes       -> disposition = created (if file did not exist) or updated
    6. If dry_run: skip write, return planned disposition.
    7. Atomic write via sudo helper:
          - write to /home/<u>/.aws/credentials.tmp.<pid>
          - chown <u>:<gid>, chmod 0600 on the temp
          - fsync, rename over real path, fsync directory
       Re-assert mode/ownership on the final path even on skipped (R7.5).
    8. Return FileChange.
```

The "sudo helper" is a small fragment invoked as
`sudo -n /usr/bin/install -m 0600 -o <u> -g <g> /tmp/<...> /home/<u>/.aws/credentials`
combined with a separate `sudo -n /usr/bin/python3.12 -c <atomic_rename_snippet>`
to perform fsync + rename atomically.

Tempfile placement is the **same directory** as the target file so `os.rename`
is guaranteed atomic on the same filesystem.

#### MCP config file write (R6, R7, R14)

```
def write_mcp(target: TargetUser, cfg: Config, dry_run: bool) -> FileChange:
    1. Read existing mcp.json via sudo cat. If missing, start from {}.
    2. json.loads strict. If parse fails -> failed, abort this user (R6.11).
    3. Ensure obj["mcpServers"] is a dict; if absent, create as {} at the
       end of obj.
    4. entry = obj["mcpServers"].setdefault("agentcore-mcp-rag", {})
       For each Managed_Key, if absent insert at end:
          entry["command"] = "python3.12"
          entry["args"]    = [cfg.proxy_path, "--runtime-id", cfg.runtime_arn]
          entry.setdefault("env", {})
          entry["env"]["AWS_REGION"]  = cfg.region
          entry["env"]["AWS_PROFILE"] = "agentcore-rag"
       (Existing keys keep their positions; new Managed_Keys append. Other
        env vars, autoApprove, disabled, disabledTools, etc., are untouched.)
    5. Re-serialize: json.dumps(obj, indent=2, ensure_ascii=False) + "\n".
    6. Idempotency comparison:
       - Re-parse new bytes; deep-equal Managed_Keys vs the parsed old.
       - Compare canonical-form JSON of every key NOT in Managed_Keys; if
         any of those changed (which would be a bug), abort with failed.
       - If old bytes existed and new bytes are byte-equal: skipped.
       - Else: updated (existing file) or created (no file).
    7. Atomic write via the same temp-rename protocol used for credentials.
```

#### Verification probe (R8)

```
def verify(target: TargetUser, cfg: Config) -> Optional[FileChange]:
    base_env = {"AWS_PROFILE": "agentcore-rag",
                "AWS_REGION":  cfg.region,
                "HOME":        target.home,
                "PATH":        "/usr/local/bin:/usr/bin:/bin"}
    for cmd, label in [
        (["aws", "sts", "get-caller-identity"], "sts"),
        (["aws", "bedrock-agentcore-control", "list-agent-runtimes",
          "--region", cfg.region], "agentcore"),
    ]:
        rc = run_as(target, cmd, env=base_env, timeout=30)
        if rc.timed_out:
            return failed(label + " timeout after 30s")
        if rc.returncode != 0:
            return failed(label + " exit %d" % rc.returncode)
    return None
```

`run_as` wraps `subprocess.run(["sudo", "-n", "-u", target.name, "-H", "env", *flatten(env), *cmd], ...)`.
stdout is captured but **not echoed** unless `--verbose` (R8.5).

#### Secret redaction (R12)

```python
class SecretRedactor:
    def __init__(self) -> None:
        self._tokens: list[tuple[str, str]] = []

    def register(self, value: str, label: str) -> None:
        if value:
            self._tokens.append((value, f"<{label} redacted>"))

    def scrub(self, text: str) -> str:
        for raw, rep in self._tokens:
            if raw and raw in text:
                text = text.replace(raw, rep)
        return text
```

`Logger.write(text)` → `sys.stderr.write(redactor.scrub(text))`. Subprocess
argv echoes are run through `redactor.scrub` before logging. `sys.excepthook`
is replaced with one that captures `traceback.format_exception()` into a
string and writes the redacted version (R12.4). SIGINT/SIGTERM handler calls
`RunSummary.flush_partial()` which goes through the same logger (R12.7).

#### Single-user vs bulk dispatch (R9, R10)

```python
def main(argv) -> int:
    args = parse_args(argv)
    if args.all and args.user:
        die("--all and --user are mutually exclusive", code=2)
    if not args.all and not args.user:
        die("exactly one of --all or --user is required", code=2)
    gate()
    cfg = ConfigResolver().resolve(args)
    creds = CredentialsLoader().load()
    if args.user:
        target = Eligibility.check_or_die(args.user, cfg.exclusions)
        records = [provision_one(target, cfg, creds)]
        targets = [target]
    else:
        targets = UserDiscovery().eligible(cfg.exclusions)
        records = [provision_one(t, cfg, creds) for t in targets]
    if cfg.verify:
        for r, t in zip(records, targets):
            if r.disposition != "failed":
                fail = verify(t, cfg)
                if fail:
                    r.disposition, r.reason = "failed", fail.reason
    return RunSummary(records, format=cfg.output_format).render_and_exit_code()
```

### CLI surface

| Option | Type | Default | Notes / requirement |
|---|---|---|---|
| `--all` | flag | — | Bulk_Mode (R10.1) |
| `--user <name>` | str | — | Single_User_Mode (R9.1) |
| `--exclude-file <path>` | path | — | Optional exclusion list (R2.4) |
| `--verify` | flag | off | Run Verification_Probe (R8.1) |
| `--verbose` | flag | off | Echo redacted subprocess output (R8.5, R12) |
| `--dry-run` | flag | off | Plan only; no writes (R10.6) |
| `--format {table,json}` | enum | `table` | Run_Summary form (R11.7) |
| `--runtime-arn <arn>` | str | env `AGENTCORE_RUNTIME_ARN` or built-in default | Validated by regex (R13.1, R13.6) |
| `--region <name>` | str | env `AWS_REGION` or `us-east-1` | Validated by regex (R13.2, R13.7) |
| `--proxy-path <path>` | path | env `AGENTCORE_PROXY_PATH` or built-in default | Symlink-resolved + readable check (R13.3, R13.8) |

### Sudo strategy

**Required (must run as root via sudo):**

- `install -d -m 0700 -o <u> -g <u> /home/<u>/.aws/`
- `install -d -m 0700 -o <u> -g <u> /home/<u>/.kiro/settings/`
- `install -m 0600 -o <u> -g <u> /tmp/<staged> /home/<u>/.aws/credentials.tmp.<pid>`
- `install -m 0600 -o <u> -g <u> /tmp/<staged> /home/<u>/.kiro/settings/mcp.json.tmp.<pid>`
- A 1-line python `-c` that performs `os.rename` + `os.fsync(dirfd)` on the
  target dir (ensures durability and atomic visibility).
- `chmod` / `chown` re-assertion on existing files (R7.5, R7.6).
- Verification probe: `sudo -n -u <u> -H env ... aws ...`.

**Not allowed via sudo (must run as ec2-user):**

- Reading `Source_Credentials_File` (`/home/ec2-user/.aws/credentials`).
- Parsing exclusion file.
- Computing eligibility.
- Producing the staged tempfile bytes (in `/tmp`, owned by ec2-user, mode 0600).

A minimal sudoers fragment for this is documented in the runbook.

## Data Models

```python
from dataclasses import dataclass, field
from typing import Literal, Optional

Disposition = Literal["created", "updated", "skipped", "failed"]

@dataclass(frozen=True)
class Config:
    runtime_arn: str
    region: str
    proxy_path: str          # already symlink-resolved and existence-checked
    runtime_arn_source: Literal["cli", "env", "default"]
    region_source:      Literal["cli", "env", "default"]
    proxy_path_source:  Literal["cli", "env", "default"]
    mode: Literal["bulk", "single"]
    target_user: Optional[str]   # only set in single mode
    exclusions: frozenset[str]
    verify: bool
    verbose: bool
    dry_run: bool
    output_format: Literal["table", "json"]

@dataclass(frozen=True)
class IamCreds:
    access_key_id: str
    secret_access_key: str
    session_token: Optional[str]

@dataclass(frozen=True)
class TargetUser:
    name: str
    uid: int
    gid: int
    home: str
    shell: str

@dataclass
class RunRecord:
    user: str
    disposition: Disposition
    reason: str = ""           # truncated to 200 chars by RunSummary

@dataclass
class FileChange:
    """Result of a single file write attempt."""
    path: str
    disposition: Disposition
    reason: str = ""

@dataclass
class Section:
    """One section of an INI-style credentials file with raw lines preserved."""
    header: Optional[str]    # None for the leading anonymous block
    raw_lines: list[str]     # original lines including comments and blanks
```

The MCP config file is held in memory as a `dict` parsed via `json.loads`,
which preserves insertion order in CPython 3.7+. New Managed_Keys are inserted
by mutating the existing dict so pre-existing keys keep their positions and
any new ones appear at the end of their object level (R6.13).

The credentials file is held as an ordered list of `Section` objects so that
byte-for-byte round-trip on every section the script does not own is
guaranteed (R5.6).

### Run_Summary table form (default)

```
agentcore-creds-provisioning summary
====================================
USER                  DISPOSITION  REASON
alice                 created
bob                   updated
carol                 skipped
dave                  failed       sts timeout after 30s

aggregate: created=1 updated=1 skipped=1 failed=1
exit: 6
```

### Run_Summary JSON form (`--format json`)

```json
{
  "version": 1,
  "users": [
    {"name": "alice", "disposition": "created", "reason": ""},
    {"name": "bob",   "disposition": "updated", "reason": ""},
    {"name": "carol", "disposition": "skipped", "reason": ""},
    {"name": "dave",  "disposition": "failed",  "reason": "sts timeout after 30s"}
  ],
  "aggregate": {"created": 1, "updated": 1, "skipped": 1, "failed": 1},
  "exit_code": 6
}
```

Reason strings are truncated to 200 ASCII characters with `...` as the final
three characters when truncated (R11.2).

## Error Handling

### Filesystem write protocol

| Path | Owner | Mode | Strategy | Failure handling |
|---|---|---|---|---|
| `/home/<u>/.aws/` | `<u>:<u>` | `0700` | `sudo install -d -m 0700 -o <u> -g <u>` if absent; `sudo chmod 0700` + `sudo chown <u>:<u>` to re-assert | If path is symlink or non-dir → `failed`, continue (R4.4) |
| `/home/<u>/.aws/credentials` | `<u>:<u>` | `0600` | Stage bytes in `/tmp` (ec2-user-owned, 0600); `sudo install -m 0600 -o <u> -g <u> tmp /home/<u>/.aws/credentials.tmp.<pid>`; `sudo python -c "<fsync+rename>"` (atomic rename on same FS) | On any subprocess error, return `failed`, leave original untouched |
| `/home/<u>/.kiro/settings/` | `<u>:<u>` | `0700` | Same as `~/.aws/` | Same as `~/.aws/` |
| `/home/<u>/.kiro/settings/mcp.json` | `<u>:<u>` | `0600` | Same temp-rename protocol as credentials; serializer uses `json.dumps(obj, indent=2)` + trailing `\n` | Invalid pre-existing JSON → `failed`, continue (R6.11) |

### Disposition table

| Failure mode | Layer | Disposition | Continue in Bulk_Mode? |
|---|---|---|---|
| Identity gate fails | global | — | exit 3 |
| Source creds missing/malformed | global | — | exit 4 |
| Argument conflict | global | — | exit 2 |
| Bad runtime ARN / region / proxy path | global | — | exit 5 |
| `~/.aws/` is a symlink | per-user | `failed` | yes (R4.4) |
| Home dir missing or not owned by user | per-user | `failed` | yes (R4.6) |
| Existing creds file unreadable via sudo | per-user | `failed` | yes |
| Credentials file write fails | per-user | `failed` | yes |
| Existing mcp.json is invalid JSON | per-user | `failed` | yes (R6.11) |
| mcp.json write fails | per-user | `failed` | yes |
| Concurrent modification detected | per-user | `failed` | yes (R14.3) |
| Verification probe non-zero exit | per-user | `failed` | yes (R8.3, R8.4) |
| Verification probe timeout (30s) | per-user | `failed` | yes (R8.3, R8.4) |
| All managed values byte-equal | per-user | `skipped` | n/a |
| Files did not exist; created | per-user | `created` | n/a |
| Files existed; managed values changed | per-user | `updated` | n/a |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All processed users dispositioned non-failed (R10.7, R11.4) |
| `2` | Argument-conflict / usage error (R10.4, R10.5) |
| `3` | Identity gate refused (R1.2, R1.3) |
| `4` | Source credential load failed (R3.2, R3.3) |
| `5` | Configuration validation failed (R13.6, R13.7, R13.8) |
| `6` | At least one Target_User dispositioned failed (R11.5) |

These are distinct (R10.7) so the caller can tell argument errors from
provisioning errors.

### Concurrency assumptions

- **Reader/writer race**: Kiro reads `mcp.json` to launch the MCP server; the
  proxy reads `~/.aws/credentials` on every invocation. The temp-then-rename
  protocol means any concurrent reader observes either the old complete bytes
  or the new complete bytes, never a torn read (R5.9, R6.12).
- **Writer/writer race**: another process editing the same file between our
  read and our rename is detected by capturing the file's `(st_dev, st_ino,
  st_size, st_mtime_ns)` snapshot before write and re-checking after. If the
  snapshot changed and our staged bytes were derived from the old snapshot,
  abort that user as `failed` with reason "concurrent modification detected"
  (R14.3).
- **Partial-write durability**: an `os.fsync(dirfd)` of the parent directory
  follows every rename so the new entry is durable on power loss.

## Correctness Properties

The five universally-quantified properties from R17 anchor the design
guarantees. Each is testable against the implementation through a Hypothesis
generator (see Testing Strategy).

### Property 1: Idempotency (R17.1)

**Validates: Requirements 7.1, 7.2, 7.3, 17.1**

Two consecutive runs of the Provisioning_Script with the same arguments and
unchanged Source_Credentials_File produce byte-equal `~/.aws/credentials` and
`~/.kiro/settings/mcp.json` for every Target_User across the two runs.

Design satisfies this through the `Idempotency` module's byte-equality check
on the credentials file and structural equivalence check on the MCP file
before deciding `skipped`. Mode and ownership re-assertion does not alter
file byte content.

### Property 2: Preservation (R17.2)

**Validates: Requirements 5.6, 5.7, 6.8, 6.9, 6.10, 17.2**

Every JSON member of `mcp.json` not in `Managed_Keys`, every `mcpServers`
entry whose key is not `agentcore-mcp-rag`, and every top-level key other
than `mcpServers` parses to the same canonical-form JSON value before and
after the run.

Design satisfies this through `McpConfigWriter` mutating only the four
`Managed_Keys` of the `agentcore-mcp-rag` entry. Dict insertion order is
preserved by CPython 3.7+ `dict`. The serializer uses fixed indent and emits
an explicit trailing newline.

### Property 3: No-leak (R17.3)

**Validates: Requirements 3.4, 12.1, 12.4, 12.5, 12.6, 12.7, 17.3**

The loaded `aws_access_key_id` and `aws_secret_access_key` byte sequences
never appear in any output the script produces (stdout, stderr, log files,
files written to target home directories).

Design satisfies this through `SecretRedactor` registering values at load
time and scrubbing every text routed through `Logger`, subprocess argv
echoes, and `sys.excepthook`. The signal handler flushes through the same
redactor.

### Property 4: Cross-file profile-name match (R17.4)

**Validates: Requirements 14.1, 14.2, 17.4**

Every provisioned user's credentials section header (after stripping
whitespace) equals the `AWS_PROFILE` value in their mcp.json
`agentcore-mcp-rag` entry.

Design satisfies this through both `AwsCredsWriter` and `McpConfigWriter`
writing the literal constant `agentcore-rag`. `UserProvisioner` post-write
asserts the invariant before classifying disposition.

### Property 5: Single-user isolation (R17.5)

**Validates: Requirements 9.2, 17.5**

When invoked with `--user <name>`, no filesystem path under any home
directory other than the named target's is created, modified, or deleted.

Design satisfies this through `UserProvisioner` being constructed once per
target. `Eligibility.check_or_die` short-circuits before any sudo subprocess
runs. Sudo argv embeds the literal target name and home path so the surface
for accidental cross-target writes is zero.

## Testing Strategy

### Unit tests (pytest)

- `IdentityGate`: parametrize over (euid, euser, SUDO_USER) tuples; assert
  exit codes per R1.
- `ConfigResolver`: every CLI/env/default precedence path; ARN regex pass and
  fail; region regex pass and fail; proxy path symlink resolution.
- `CredentialsLoader`: source files with quoted values, comments, missing
  fields, missing section; redaction is registered before any logging.
- `Eligibility`: passwd entries that pass and fail every clause of R2 / R9.
- `AwsCredsWriter`: pre-existing files with multiple sections, comments, and
  blank lines; verify byte-for-byte preservation of non-managed sections.
  Verify atomic temp-rename via mocked `subprocess.run`.
- `McpConfigWriter`: pre-existing files with `powers`, multiple servers,
  custom `autoApprove`, `disabledTools`, and other env vars; verify
  preservation; verify Managed_Keys are written with correct types and order;
  verify invalid-JSON case raises and produces `failed`.
- `VerificationProbe`: mock `subprocess.run`; assert timeout=30 honored;
  assert disposition reasons distinguish timeout vs non-zero.
- `RunSummary`: every disposition combination; reason truncation at 200
  chars; JSON output schema; exit code mapping.
- `SecretRedactor`: scrubs literal values from arbitrary text; tracebacks
  scrubbed via excepthook; subprocess argv echoes scrubbed.

### Property-based tests (Hypothesis, R17)

Each property maps to one Hypothesis test. Inputs use `pyfakefs` for the
filesystem so no sudo is required:

- **Idempotency** (R17.1): generate 1–32 target users, populate fake homes,
  run the script twice with identical inputs, assert byte-equality of every
  produced file across the two runs.
- **Preservation** (R17.2): generate arbitrary valid mcp.json shapes (≤32
  servers, depth ≤4) including non-`agentcore-mcp-rag` entries and extra
  top-level keys; run the writer; assert every non-managed key parses to the
  same canonical-form JSON value as before.
- **No-leak** (R17.3): generate access keys (16–128 chars) and secrets
  (1–256 chars including `"`, `\`, `\n`); capture stdout/stderr/log for an
  entire run; assert neither the access key nor secret appears as a contiguous
  byte sequence.
- **Cross-file profile-name match** (R17.4): for any successful per-user
  outcome, parse both files and assert the credentials section header equals
  the mcp.json `AWS_PROFILE` field.
- **Single-user isolation** (R17.5): generate `--user <name>` invocations
  over many fake homes; assert no path under any other home was created,
  modified, or deleted.

Fixed corner-case corpus (R17.6) is also exercised: empty creds file,
malformed JSON mcp.json, max-length name, secret containing JSON-significant
chars, absent credentials file, absent mcp.json, mcp.json already in target
state.

### Integration smoke test (CI)

In addition to PBT/unit, a single integration test on a disposable container
runs the script in `--dry-run` against a fixture of three fake users, asserts
the planned dispositions, then runs without `--dry-run` and asserts the actual
files match.

## Open Questions

These items are not blockers; the implementation should resolve them and the
runbook should answer:

1. **Sudoers tightening**: should `ec2-user` get a NOPASSWD allowance for
   exactly `install -m 0600`, `install -d`, `chmod`, `chown`, `rename` on
   `/home/*/.aws/` and `/home/*/.kiro/settings/`, or is the existing broad
   `ec2-user ALL=(ALL) NOPASSWD: ALL` acceptable? Recommend the narrower form
   for defense-in-depth, but defer to the host owner. Document both options
   in the runbook.
2. **Region mismatch detection**: if `AWS_Region` resolves to a value
   different from what the runtime ARN region segment says
   (`arn:aws:bedrock-agentcore:us-east-1:...`), should the script warn or
   error? Current design only validates each independently. Suggest a
   non-fatal warning emitted by `ConfigResolver`.
3. **Existing per-user `[default]` profile**: if a target user already has a
   `[default]` profile in their `~/.aws/credentials` that conflicts with
   ambient AWS tooling, the spec preserves it byte-for-byte (R5.6) and only
   touches `[agentcore-rag]`. The runbook should note this so operators do
   not expect the script to clean up old profiles.
4. **Multi-runtime support**: a future expansion may need to provision more
   than one MCP server entry. The current design hard-codes the
   `agentcore-mcp-rag` entry name. Defer until requirements emerge; the
   `McpConfigWriter` can be parameterized by entry name without algorithmic
   change.
5. **Logging persistence**: should run summaries be archived (e.g.
   `/var/log/provision-agentcore-creds.log`)? The requirements do not ask
   for this, so the script writes only to stdout/stderr. The runbook can
   suggest `script(1)` or systemd-journal capture if an audit trail is
   wanted.
