# DRAFT — Kiro bug report: root cause of false Exit Code 1 (Linux/bash)

**Status:** POSTED 2026-08-13.
**Posted to:** [kirodotdev/Kiro#4833 (comment 5281038119)](https://github.com/kirodotdev/Kiro/issues/4833#issuecomment-5281038119) — chosen as closest prior art (same platform + integration stack), cross-referencing #9938 and #9483.

> **Pre-post checklist — completed**
> - [x] `~/.bashrc` not pasted verbatim; only individual lines quoted. (The token it contained has since been moved to `gh`'s 0600 credential store and is slated for rotation.)
> - [x] Body scanned clean for host/project identifiers: 0 hits across NOAA, NWS, NCEP, EMC, operator name, host IP, `mdc-mcp-rag`, MCP, GraphRAG, Neptune, OpenSearch, AgentCore, token prefix, AWS account number. Only the GitHub author handle identifies the reporter, which the operator cleared as acceptable for a public tracker.
> - [x] Target decided: comment on #4833 rather than a new issue, to consolidate with the two open issues already carrying this symptom.
>
> Retained in-repo as the provenance record for the upstream post. The body below is
> verbatim what was published (7,703 chars).

---

## Draft body

### Root cause for the false exit code (Linux/bash + Amazon Q / kiro-cli shell integration)

We hit this on Kiro 1.0.293 and traced it to a specific mechanism. Posting the analysis
since this thread identifies the trigger (OSC sequences from Fig/Q integration) but not
the underlying cause. Our symptom is `Exit Code: 1` rather than `-1`, but the emit path
is the same.

Diagnosed in-situ using Kiro's own agent (Claude Opus 5) via the IDE's `executeBash`
tool — the affected terminal was both the subject and the instrument, which is how the
first-command-vs-subsequent-command signature below surfaced. A human running one
command at a time would be unlikely to notice it. Every claim here is backed by a live
measurement on the host, reviewed and verified by operator.

**Environment**

| | |
|---|---|
| Kiro | 1.0.293 (remote / `kiro-server`) |
| OS | Amazon Linux (aarch64), kernel 6.x |
| Shell | GNU bash 5.2.15(1) |
| Integrations loaded | Kiro OSC 633 (`__vsc_*`), bash-preexec (`__bp_*`), Amazon Q / kiro-cli (`__fig_*`) |
| `Q_TERM_DISABLED` | `1` |

**Symptom signature (this part is diagnostic)**

In any given terminal session:
- the **first** command reports `Exit Code: 0`
- **every subsequent** command reports `Exit Code: 1`, regardless of real status

`echo test` reports 1. Adding an in-band probe shows the discrepancy plainly:

```
$ echo test; echo "BASH_SAYS=$?"
test
BASH_SAYS=0        <- bash's real status
Exit Code: 1       <- what Kiro displays
```

Command echo and prompt fragments in captured output accompany it, and some commands
return empty stdout entirely.

**Mechanism**

Kiro's integration reports status in `__vsc_command_complete`:

```bash
__vsc_command_complete () {
    if [[ -z "${__vsc_first_prompt-}" ]]; then
        __vsc_update_cwd
        builtin return                        # (1) first prompt: emits nothing
    fi
    if [ "$__vsc_current_command" = "" ]; then
        builtin printf '\e]633;D\a'           # (2) no status in the marker
    else
        builtin printf '\e]633;D;%s\a' "$__vsc_status"
    fi
    __vsc_update_cwd
}
```

Live state immediately after a successful command:

```
__vsc_status=[0]                <- correct
__vsc_current_command=[]        <- empty  => branch (2) taken
__vsc_first_prompt=[1]
```

So `$__vsc_status` holds the right value the whole time. The bug is purely that
branch (2) emits `633;D` **with no status field**, and Kiro appears to render a
status-less `D` as `1`.

Branch (1) explains the first-command-is-0 signature: on the very first prompt nothing
is emitted at all, and Kiro defaults that to 0.

**Why `__vsc_current_command` is empty**

It is assigned by `__vsc_preexec`, which is dispatched from `preexec_functions[]`:

```
preexec_functions=([0]="__fig_preexec_preserve_status" [1]="__vsc_preexec_only" [2]="preexec")
precmd_functions=([0]="__fig_pre_prompt"               [1]="__vsc_prompt_cmd"   [2]="precmd")
```

`preexec_functions` are driven **only** by bash-preexec's `DEBUG` trap. On this host
that trap is **absent**:

```
$ trap -p DEBUG
(empty)

$ echo "$__bp_trap_string"
trap -- '__bp_preexec_invoke_exec "$_"' DEBUG     <- bash-preexec recorded what it installed

$ echo "$__bp_preexec_interactive_mode"
on                                                 <- and believes it is armed
```

bash-preexec installs the trap via `__bp_install`, records it, and something later in
startup clears it. bash-preexec never re-arms, and has no self-check — it keeps
reporting `interactive_mode=on`. Result:

```
no DEBUG trap
  -> preexec_functions never fire
  -> __vsc_preexec never runs
  -> __vsc_current_command stays empty
  -> __vsc_command_complete takes the no-status branch
  -> Kiro receives '633;D' with no code and displays 1
```

`precmd_functions` are unaffected because they run from `PROMPT_COMMAND`, which is why
`__vsc_status` is still correct — only the *preexec* half of the integration is broken.

**Confirmation**

Re-arming the trap by hand fixes it immediately, in the same session:

```bash
trap -- '__bp_preexec_invoke_exec "$_"' DEBUG
```

After that, in the same terminal:

| command | reported |
|---|---|
| `echo test` (2nd+ in session) | 0 |
| `ls -la <file>` | 0 |
| `ls /nonexistent` | **2** (`ls`'s real code) |
| `bash -c 'exit 7'` | **7** |
| `exit 42` | **42** |

Command echo and prompt fragments also stop. Genuine failures still report correctly,
so this is not masking errors.

**Our persistent workaround**

Re-arm from `PROMPT_COMMAND` so it self-heals each prompt (we never identified *what*
clears the trap, so this is deliberately robust to that rather than dependent on it):

```bash
__ensure_bp_debug_trap() {
  if [[ -z "$(trap -p DEBUG)" ]] \
     && declare -F __bp_preexec_invoke_exec >/dev/null 2>&1; then
    trap -- '__bp_preexec_invoke_exec "$_"' DEBUG
  fi
  return 0
}
if [[ $- == *i* ]] && declare -F __bp_preexec_invoke_exec >/dev/null 2>&1; then
  case "${PROMPT_COMMAND-}" in
    *__ensure_bp_debug_trap*) ;;
    *) PROMPT_COMMAND="${PROMPT_COMMAND:+${PROMPT_COMMAND}$'\n'}__ensure_bp_debug_trap" ;;
  esac
fi
```

**Note on the workaround suggested in this thread**

Disabling the shell integration in non-TTY shells does stop the output corruption, but
if implemented as a guard on the sourcing line it introduces a *second* defect:

```bash
# returns 1 whenever the guard is false, and as the LAST line of .bashrc
# that makes .bashrc itself exit 1, poisoning $? for the whole session
[[ -t 1 && -f "$HOME/.local/share/kiro-cli/shell/bashrc.post.bash" ]] \
  && builtin source "$HOME/.local/share/kiro-cli/shell/bashrc.post.bash"
```

A fresh interactive shell then starts with `$?` already 1. Terminating such guarded
blocks with `:` avoids it. Worth flagging because the kiro-cli installer emits this
`[[ … ]] && source …` shape by default — benign while the file exists, but non-zero the
moment the test fails for any reason.

### Suggested hardening (Kiro side)

1. **Treat a status-less `633;D` as unknown, not as failure.** This alone would convert
   the bug from "every command looks like it failed" into "exit code unavailable," which
   is honest and far less disruptive. Currently a missing field renders as `1`, which is
   indistinguishable from a real failure.
2. **Make the reported code independent of `__vsc_current_command`.** `__vsc_status` was
   correct in every measurement we took; gating the emit on a *different* variable that
   depends on the preexec path is what couples exit-code reporting to DEBUG-trap health.
   Emitting `633;D;$__vsc_status` unconditionally would have avoided this entirely.
3. **Detect the hook conflict and surface it.** When `__vsc_preexec` is present in
   `preexec_functions` but no `DEBUG` trap exists, the integration is silently
   half-installed. A one-line warning at first prompt would save a lot of diagnosis —
   several open issues here (#9938, #9483, this one) share the symptom without a cause.
4. **Consider not delegating to bash-preexec when another consumer already owns it.**
   Kiro's integration currently rides in `preexec_functions`/`precmd_functions` behind
   Fig/Q. Installing its own `DEBUG` trap, or verifying the delegated one survives,
   would decouple it from third-party hook health.

### Possibly related open issues

- #9938 — same symptom triad (character echo, false exit 1, prompt fragments) on
  Windows/PowerShell. Different platform, but if the Windows integration has an
  equivalent status-less completion path, hardening item 1 may cover both.
- #9483 — `execute_bash` returns empty stdout mid-session. We also saw intermittent
  empty output on the same host; it stopped when the trap was re-armed, so it may share
  this cause.
