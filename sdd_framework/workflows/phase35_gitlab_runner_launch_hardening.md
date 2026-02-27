# SDD: Phase 35 — GitLab Runner Launch Script Hardening

**Version:** 1.0.0
**Created:** 2026-02-27
**Author:** Terry McGuinness + AI Assistants
**Status:** SPEC COMPLETE — Ready for Execution
**Execution Mode:** ISD (Interactive Supervised Development)
**Builds On:** Existing CI/CD infrastructure in `dev/ci/`
**Audience:** Global Workflow CI/CD Team, RDHPCS Platform Admins

---

## 1. Executive Summary

The GitLab runner launch script (`dev/ci/scripts/utils/gitlab/launch_gitlab_runner.sh`) currently provides basic register/run/unregister operations but lacks the operational maturity of its Jenkins counterpart (`dev/ci/scripts/utils/launch_java_agent.sh`). The Jenkins script has evolved to include proper argument parsing, idempotent health-check behavior, connection-loss recovery, and structured logging. This phase brings the GitLab script to parity.

### Gap Summary

| Capability | Jenkins (`launch_java_agent.sh`) | GitLab (`launch_gitlab_runner.sh`) |
|-----------|----------------------------------|-------------------------------------|
| Argument parsing | `getopts` with `-f`, `-n`, `-h` flags | Positional `$1` / `$2` only |
| Usage help | `-h` prints usage and exits | None |
| Idempotent run | Checks if agent is already connected before launching | Always launches (no status check) |
| Health-check mode | Detects offline → waits 5 min → re-checks → relaunches if still down | Not implemented |
| Force launch | `-f` flag bypasses status check | Not implemented |
| Skip wait | `-n` flag skips the 5-min retry delay | Not implemented |
| Module environment | Loads `gw_setup.${MACHINE_ID}` modulefiles | None — no module setup |
| Structured logging | Timestamped log with PID tracking | Basic log, no PID capture |
| Connection validation | Queries Jenkins API for node online status | No runner status query |
| Token validation | Validates GitHub CLI auth status | Token exists check only |
| Process management | Background launch with PID tracking | Background launch, no PID |
| Error on missing deps | Checks JAVA_HOME, agent.jar, gh CLI, jenkins_token | Only checks gitlab-runner binary |
| Platform cloud support | Handles `noaacloud` → `config.${PW_CSP}` | No cloud platform handling |

---

## 2. Current State

### 2.1 GitLab Script (`launch_gitlab_runner.sh`) — What It Does Today

**Location:** `dev/ci/scripts/utils/gitlab/launch_gitlab_runner.sh`

Three subcommands via positional `$1`:

1. **`register`** — Registers runner with GitLab server using `--url`, `--executor shell`, `--builds-dir`, `--custom_build_dir-enabled=true`, `--request-concurrency 24`. Sets `concurrent = 24` in config.toml.
2. **`run`** — Launches `gitlab-runner run --working-directory` via `nohup` in background.
3. **`unregister`** — Removes runner by name.

**Token handling:** Checks `$2`, then `$GITLAB_RUNNER_TOKEN` env var, then `gitlab_token` file.

**Binary management:** Auto-downloads `gitlab-runner` binary if missing.

**Platform configs sourced:** `dev/ci/platforms/config.${MACHINE_ID}` provides:
- `GITLAB_URL` — GitLab server URL (vlab.noaa.gov/gitlab-community)
- `GITLAB_RUNNER_NAME` — Human-readable runner name
- `GITLAB_BUILDS_DIR` — Build directory for `--builds-dir`
- `GITLAB_RUNNER_DIR` — Working directory for runner state

### 2.2 Jenkins Script (`launch_java_agent.sh`) — Reference Implementation

**Capabilities to port:**

1. **`getopts` argument parsing** with `-f` (force), `-n` (now/skip-wait), `-h` (help)
2. **Online status check** — queries controller API, parses JSON response to determine if node is offline
3. **Idempotent behavior** — if runner is already connected, does nothing ("Jenkins Agent is online (nothing done)")
4. **Retry with backoff** — if offline, waits 5 minutes then re-checks before relaunching
5. **Force override** — `-f` skips status check entirely
6. **PID tracking** — captures `$!` after `nohup` and logs it
7. **Remoting cache cleanup** — clears stale cache before relaunch
8. **Module environment setup** — loads platform modulefiles
9. **Dependency validation** — checks JAVA_HOME, agent.jar, gh CLI, auth tokens
10. **Structured error messages** — consistent `ERROR:` / `FATAL ERROR:` prefixes

---

## 3. Design Decisions

### 3.1 GitLab Runner Status Check Mechanism

The Jenkins script queries its controller's REST API:
```bash
curl -u "user:token" "${controller_url}/computer/${node}/api/json"
```

For GitLab, the equivalent is `gitlab-runner verify`:
```bash
./gitlab-runner verify --name "${GITLAB_RUNNER_NAME}" 2>&1
```

This returns exit code 0 if the runner is registered and can connect to the GitLab server. Additionally, we can check if a `gitlab-runner run` process is already active:
```bash
pgrep -f "gitlab-runner run" > /dev/null 2>&1
```

**Decision:** Use a three-tier check:
1. **Process check** — is `gitlab-runner run` already running? (PID-based)
2. **Metrics probe** — is the runner's embedded Prometheus HTTP server responding? (live liveness)
3. **Registration check** — can the runner reach the GitLab server? (`gitlab-runner verify`)

### 3.2 Subcommand Structure

Current: `$1` positional arg for `register`/`run`/`unregister`
Target: Keep subcommands as `$1` but add `getopts`-style flags that work with the `run` subcommand.

```
Usage: launch_gitlab_runner.sh <command> [options] [token]

Commands:
  register   Register a new GitLab runner
  run        Start or health-check the GitLab runner
  unregister Remove the GitLab runner

Options (for 'run' command):
  -f         Force launch regardless of current status
  -n         Skip wait period if runner is offline
  -h         Print this help message
```

### 3.3 Prometheus Metrics Endpoint for Liveness

The GitLab runner has a **built-in Prometheus metrics HTTP server** that can be enabled with `--listen-address`. This is the community best practice for runner health monitoring at scale. When enabled, a `curl` to the `/metrics` endpoint is a true liveness probe — it confirms the process is alive AND the internal HTTP server and job-processing goroutines are functional.

```bash
# Enable on launch
./gitlab-runner run --working-directory ${GITLAB_RUNNER_DIR} --listen-address "localhost:${GITLAB_RUNNER_METRICS_PORT}"

# Health check
curl -s --max-time 5 "http://localhost:${GITLAB_RUNNER_METRICS_PORT}/metrics" > /dev/null 2>&1
```

**Port selection:** The Prometheus project reserves port **9252** for GitLab Runner in their [default port allocations](https://github.com/prometheus/prometheus/wiki/Default-port-allocations). This is a convention, not a hard requirement — any available port works. On shared HPC nodes where multiple users may run runners, we:
- Bind to `localhost` only (not `0.0.0.0`) to avoid exposing metrics to the network
- Make the port configurable per-platform via `GITLAB_RUNNER_METRICS_PORT` in `config.${MACHINE_ID}`
- Default to `9252` if not set
- **Check port availability before launch** — if the configured port is occupied, fail with a clear error rather than launching with a dead metrics endpoint

**State file for cron jobs:** When a cron job runs the health check, it needs to know which port to probe without re-sourcing the full platform config and workflow environment. At launch time, write a `runner.state` file to `GITLAB_RUNNER_DIR`:

```bash
# Written by launch_runner() to ${GITLAB_RUNNER_DIR}/runner.state
RUNNER_PID=12345
RUNNER_METRICS_PORT=9252
RUNNER_STARTED="2026-02-27 14:30:00"
RUNNER_HOST=hera-login1
GITLAB_RUNNER_DIR=/scratch3/NCEPDEV/global/role.glopara/GFS_CI_CD/HERA/GitLab/Runner
```

The cron health-check entry then becomes self-contained:

```bash
# Example crontab entry (every 15 minutes)
*/15 * * * * /path/to/launch_gitlab_runner.sh run -n 2>&1 | logger -t gitlab-runner-healthcheck
```

Or for a lightweight probe-only check without the full launch logic:

```bash
# Minimal cron probe using only the state file
*/5 * * * * source /path/to/GITLAB_RUNNER_DIR/runner.state && curl -sf --max-time 5 http://localhost:${RUNNER_METRICS_PORT}/metrics > /dev/null || /path/to/launch_gitlab_runner.sh run -n
```

**Port availability check at launch:**

```bash
check_port_available() {
    local port="${1}"
    if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
        # Port is in use — check if it's OUR runner
        if curl -s --max-time 2 "http://localhost:${port}/metrics" 2>/dev/null | grep -q "gitlab_runner"; then
            log_msg "Port ${port} already in use by a GitLab Runner (may be our existing process)"
            return 1  # port used by a runner — caller should check if it's ours
        else
            log_msg "ERROR: Port ${port} is occupied by another service. Set GITLAB_RUNNER_METRICS_PORT to an available port in config.${MACHINE_ID}"
            return 2  # port used by something else — fatal
        fi
    fi
    return 0  # port available
}
```

**Key metrics available at `/metrics`:**

| Metric | What It Tells You |
|--------|-------------------|
| `gitlab_runner_jobs_running_total` | Jobs currently executing |
| `gitlab_runner_api_request_statuses_total` | API call success/failure rates to GitLab server |
| `gitlab_runner_request_concurrency` | Current concurrent request count |
| `gitlab_runner_concurrent` | Configured concurrency limit |
| `gitlab_runner_errors_total` | Caught errors |

This is strictly stronger than `pgrep` (which only checks if the PID exists) because a hung runner process would still show up in `pgrep` but would fail to respond to the HTTP probe.

### 3.4 What NOT to Port

- **Java/JDK management** — GitLab runner is a static Go binary, no JVM needed
- **GitHub CLI integration** — not relevant for GitLab runner operations
- **Controller API user auth** — GitLab runner auth is token-based at registration time, not per-API-call
- **Inline Python script for JSON parsing** — `gitlab-runner verify` avoids needing to parse JSON; if needed, use `jq` or simple `grep`

### 3.5 Stale Process Cleanup

Before relaunching, kill any orphaned `gitlab-runner run` processes:
```bash
pkill -f "gitlab-runner run" 2>/dev/null || true
sleep 2
```

The Jenkins script clears the `remoting/` cache directory. The GitLab equivalent is to optionally clear the runner's sentinels/state in `GITLAB_RUNNER_DIR` if the process was found dead.

### 3.6 Cloud Platform Handling

The Jenkins script handles `noaacloud` by sourcing `config.${PW_CSP}` instead of `config.${MACHINE_ID}`. The GitLab script should adopt the same pattern if GitLab runners are deployed on Parallel Works cloud nodes.

### 3.7 Local Development with `config.local`

**Problem:** The script cannot be tested or developed on a local VM because `detect_machine.sh` won't match any known HPC hostname, and the `case` statement will exit with "Unsupported platform."

**Solution:** `detect_machine.sh` already supports pre-setting `MACHINE_ID`:
```bash
# Line 11-12 of detect_machine.sh:
if [[ -n "${MACHINE_ID:-}" ]]; then
    return  # skip hostname detection entirely
fi
```

So the developer simply exports `MACHINE_ID=local` before invoking the script, and we:
1. Add `local` to the case statement in `launch_gitlab_runner.sh`
2. Create `dev/ci/platforms/config.local` with VM-appropriate paths and a mock GitLab URL
3. Use `$HOME`-relative paths so it works for any user without root or role accounts

**`config.local` design:**

```bash
#!/usr/bin/bash

#########################################################################
# config.local - Local VM / development workstation configuration
#
# For testing and developing CI/CD scripts outside HPC platforms.
# Usage: export MACHINE_ID=local before running launch_gitlab_runner.sh
#
# This config uses $HOME-relative paths so it works for any user.
# The GITLAB_URL can be pointed at a real GitLab instance or left
# as a placeholder for dry-run testing.
#########################################################################

# Main CI root directory - uses $HOME so no role account needed
export GFS_CI_ROOT="${HOME}/GFS_CI_CD/LOCAL"

# ICSDIR root directory (can be empty for runner testing)
export ICSDIR_ROOT="${GFS_CI_ROOT}/data/ICSDIR"

#########################################################################
# Jenkins configuration settings (not used for GitLab runner testing)
#########################################################################
export JENKINS_AGENT_LAUNCH_DIR=${GFS_CI_ROOT}/Jenkins/agent
export JENKINS_WORK_DIR=${GFS_CI_ROOT}/Jenkins/workspace

#########################################################################
# GitLab CI configuration
#########################################################################

# Point at your GitLab instance (can be a local GitLab, vlab, or placeholder)
# For dry-run testing without a real server, leave as-is — register will fail
# but run/status/health-check logic can still be exercised
export GITLAB_URL=${GITLAB_URL:-"https://vlab.noaa.gov/gitlab-community"}
export GITLAB_RUNNER_NAME="Local Dev $(hostname -s)"

# Build and runner directories (auto-created by launch script)
export GITLAB_BUILDS_DIR=${GFS_CI_ROOT}/BUILDS/GITLAB
export GITLAB_RUNNER_DIR="${GFS_CI_ROOT}/GitLab/Runner"

#########################################################################
# Port for GitLab Runner's embedded Prometheus metrics endpoint
#########################################################################
export GITLAB_RUNNER_METRICS_PORT=9252

#########################################################################
# CTest directories (not used for runner testing, but included for parity)
#########################################################################
export STAGED_CTESTS=${GITLAB_BUILDS_DIR}/stable/RUNTESTS

# No HPC account needed locally
export HPC_ACCOUNT=${HPC_ACCOUNT:-"none"}

#########################################################################
# System-specific settings
#########################################################################
export GFS_CI_UTIL_PATH="${HOME}/utils"
export GFS_CI_ROCOTO_PATH="${GFS_CI_UTIL_PATH}/src/rocoto/bin"
```

**Local development workflow:**

```bash
# 1. Set up (one-time)
export MACHINE_ID=local
export HOMEgfs_=$(git rev-parse --show-toplevel)  # or set manually
mkdir -p ~/GFS_CI_CD/LOCAL/GitLab/Runner

# 2. Source the config to verify paths
source ${HOMEgfs_}/dev/ci/platforms/config.local
echo "Runner dir: ${GITLAB_RUNNER_DIR}"
echo "Builds dir: ${GITLAB_BUILDS_DIR}"

# 3. Download the gitlab-runner binary (script does this automatically)
# Or manually: curl -L --output gitlab-runner https://...  && chmod +x gitlab-runner

# 4. Test status subcommand (no runner running yet)
./launch_gitlab_runner.sh status
# Expected: all 3 tiers fail, exit 1

# 5. Test run with -n (skip wait) — will launch a runner process
./launch_gitlab_runner.sh run -n
# Expected: launches runner, writes runner.state

# 6. Verify health check
./launch_gitlab_runner.sh status
# Expected: process alive, metrics responding (if port available), verify may fail without real GitLab server

# 7. Verify state file
cat ~/GFS_CI_CD/LOCAL/GitLab/Runner/runner.state

# 8. Test idempotency
./launch_gitlab_runner.sh run
# Expected: "GitLab Runner is online (nothing done)"

# 9. Test force relaunch
./launch_gitlab_runner.sh run -f
# Expected: kills existing, relaunches

# 10. Port conflict test
python3 -m http.server 9252 &
./launch_gitlab_runner.sh run -f
# Expected: detects port conflict, fails with clear message
kill %1
```

**What works without a real GitLab server:**
- `run` / `run -f` / `run -n` — process launches, metrics endpoint responds, state file written
- `status` — tier-1 (process) and tier-2 (metrics) work; tier-3 (verify) will fail without server
- Port conflict detection, state file persistence, idempotency, logging, argument parsing

**What requires a real GitLab server:**
- `register` — needs valid token and reachable GITLAB_URL
- `unregister` — needs existing registration
- Tier-3 `verify` check — needs server connectivity

---

## 4. Implementation Steps

### Step 1: Add `getopts` argument parsing and usage help
**Tag:** implement
**Target:** `dev/ci/scripts/utils/gitlab/launch_gitlab_runner.sh`

Replace the positional `$1`/`$2` argument handling with a structured approach:
- Extract subcommand from `$1`, then `shift`
- Parse remaining args with `getopts` for `-f`, `-n`, `-h`
- Add `print_usage()` function with full help text
- Validate that exactly one subcommand is provided

**Reference:** Lines 49-63 of `launch_java_agent.sh` (`getopts` block)

```bash
print_usage() {
    cat << 'EOF'
Usage: launch_gitlab_runner.sh <command> [options] [token]

Commands:
  register   Register a new GitLab runner with the GitLab server
  run        Start or health-check the GitLab runner
  unregister Remove the GitLab runner from the GitLab server

Options (apply to 'run' command):
  -f    Force launch regardless of current runner status
  -n    Skip the wait period if runner is found offline
  -h    Print this help message

Token:
  Runner authentication token. Can also be set via:
    GITLAB_RUNNER_TOKEN environment variable, or
    gitlab_token file in the runner directory
EOF
}
```

### Step 2: Add module environment setup
**Tag:** implement
**Target:** `dev/ci/scripts/utils/gitlab/launch_gitlab_runner.sh`

Add module loading after machine detection, matching the Jenkins pattern:

```bash
HOMEgfs="${HOMEgfs_}" source "${HOMEgfs_}/ush/module-setup.sh"
module use "${HOMEgfs_}/modulefiles"
module load "gw_setup.${MACHINE_ID}"
```

This ensures consistent environment (compilers, Python, utilities) for any downstream operations.

### Step 3: Add cloud platform (`noaacloud`) support
**Tag:** implement
**Target:** `dev/ci/scripts/utils/gitlab/launch_gitlab_runner.sh`

Mirror the Jenkins script's handling:

```bash
if [[ "${MACHINE_ID}" == "noaacloud" ]]; then
    source "${HOMEgfs_}/dev/ci/platforms/config.${PW_CSP}"
else
    source "${HOMEgfs_}/dev/ci/platforms/config.${MACHINE_ID}"
fi
```

### Step 4: Implement runner status check function
**Tag:** implement
**Target:** `dev/ci/scripts/utils/gitlab/launch_gitlab_runner.sh`

Create `check_runner_status()` function that performs a three-tier check. When called from a cron context, the function first attempts to read the port from `runner.state` (written at launch time), falling back to the platform config default:

```bash
check_runner_status() {
    # Load state file if it exists (written by launch_runner)
    RUNNER_STATE_FILE="${GITLAB_RUNNER_DIR}/runner.state"
    if [[ -f "${RUNNER_STATE_FILE}" ]]; then
        source "${RUNNER_STATE_FILE}"
        METRICS_PORT="${RUNNER_METRICS_PORT:-${GITLAB_RUNNER_METRICS_PORT:-9252}}"
    else
        METRICS_PORT="${GITLAB_RUNNER_METRICS_PORT:-9252}"
    fi

    # Tier 1: Is the process running?
    if pgrep -f "gitlab-runner run --working-directory ${GITLAB_RUNNER_DIR}" > /dev/null 2>&1; then
        RUNNER_PID=$(pgrep -f "gitlab-runner run --working-directory ${GITLAB_RUNNER_DIR}" | head -1)
        RUNNER_PROCESS_ALIVE="True"
    else
        RUNNER_PROCESS_ALIVE="False"
    fi

    # Tier 2: Is the metrics endpoint responding? (true liveness probe)
    if curl -s --max-time 5 "http://localhost:${METRICS_PORT}/metrics" > /dev/null 2>&1; then
        RUNNER_METRICS_ALIVE="True"
    else
        RUNNER_METRICS_ALIVE="False"
    fi

    # Tier 3: Can it reach the GitLab server? (registration validity)
    if ./gitlab-runner verify --name "${GITLAB_RUNNER_NAME}" > /dev/null 2>&1; then
        RUNNER_VERIFIED="True"
    else
        RUNNER_VERIFIED="False"
    fi
}
```

### Step 5: Implement idempotent `run` with health-check logic
**Tag:** implement
**Target:** `dev/ci/scripts/utils/gitlab/launch_gitlab_runner.sh`

Rewrite the `run` subcommand to match Jenkins' idempotent behavior:

1. If `-f` flag: skip checks, go straight to launch
2. Call `check_runner_status()`
3. If process alive AND metrics responding AND verified: print "GitLab Runner is online (nothing done)" and exit 0
4. If offline:
   - If `-n` flag NOT set: wait 5 minutes, re-check
   - If still offline after wait (or `-n` set): kill stale process, relaunch
5. Log PID of new process

```bash
launch_runner() {
    # Kill any orphaned process
    pkill -f "gitlab-runner run" 2>/dev/null || true
    sleep 2

    METRICS_PORT="${GITLAB_RUNNER_METRICS_PORT:-9252}"

    # Check port availability before launching
    check_port_available "${METRICS_PORT}"
    port_status=$?
    if [[ ${port_status} -eq 2 ]]; then
        log_msg "FATAL: Cannot launch — metrics port ${METRICS_PORT} occupied by non-runner service"
        exit 1
    fi

    COMMAND="nohup ./gitlab-runner run --working-directory ${GITLAB_RUNNER_DIR} --listen-address localhost:${METRICS_PORT}"
    log_msg "Launching GitLab Runner on ${host}"
    log_msg "Command: ${COMMAND}"
    ${COMMAND} >> "${GITLAB_LOG}" 2>&1 &
    RUNNER_PID=$!

    # Write state file for cron health checks
    cat > "${GITLAB_RUNNER_DIR}/runner.state" << EOF
RUNNER_PID=${RUNNER_PID}
RUNNER_METRICS_PORT=${METRICS_PORT}
RUNNER_STARTED="$(date '+%Y-%m-%d %H:%M:%S')"
RUNNER_HOST=$(hostname)
GITLAB_RUNNER_DIR=${GITLAB_RUNNER_DIR}
EOF

    log_msg "GitLab Runner launched with PID: ${RUNNER_PID} (metrics on localhost:${METRICS_PORT})"
    log_msg "State written to ${GITLAB_RUNNER_DIR}/runner.state"
}
```

### Step 6: Improve logging with PID and timestamps
**Tag:** implement
**Target:** `dev/ci/scripts/utils/gitlab/launch_gitlab_runner.sh`

Add a `log_msg()` helper and ensure all operations produce timestamped log entries:

```bash
log_msg() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${GITLAB_LOG}"
}
```

Replace all `echo` statements in operational paths with `log_msg`.

### Step 7: Add dependency validation for `register` subcommand
**Tag:** implement
**Target:** `dev/ci/scripts/utils/gitlab/launch_gitlab_runner.sh`

Before attempting registration, validate:
- `GITLAB_URL` is set and reachable (`curl --silent --head`)
- `GITLAB_BUILDS_DIR` exists or can be created
- `GITLAB_RUNNER_DIR` exists or can be created
- Token is non-empty

### Step 8: Add `status` subcommand
**Tag:** implement
**Target:** `dev/ci/scripts/utils/gitlab/launch_gitlab_runner.sh`

Add a new `status` subcommand (not present in Jenkins but natural for GitLab runner):

```bash
if [[ "${SUBCOMMAND}" == "status" ]]; then
    check_runner_status
    log_msg "Process alive: ${RUNNER_PROCESS_ALIVE} (PID: ${RUNNER_PID:-none})"
    log_msg "Metrics endpoint: ${RUNNER_METRICS_ALIVE} (port: ${GITLAB_RUNNER_METRICS_PORT:-9252})"
    log_msg "Server verified: ${RUNNER_VERIFIED}"
    if [[ "${RUNNER_PROCESS_ALIVE}" == "True" && "${RUNNER_METRICS_ALIVE}" == "True" && "${RUNNER_VERIFIED}" == "True" ]]; then
        log_msg "GitLab Runner is healthy (all 3 tiers passed)"
        exit 0
    elif [[ "${RUNNER_PROCESS_ALIVE}" == "True" && "${RUNNER_METRICS_ALIVE}" == "False" ]]; then
        log_msg "GitLab Runner process alive but metrics unresponsive — possible hung process"
        exit 1
    else
        log_msg "GitLab Runner needs attention"
        exit 1
    fi
fi
```

### Step 9: Write validation tests
**Tag:** validate
**Target:** `dev/ci/scripts/utils/gitlab/launch_gitlab_runner.sh`

Manual validation checklist (to be executed on a target platform):

1. `./launch_gitlab_runner.sh -h` — prints usage and exits 0
2. `./launch_gitlab_runner.sh run` — with runner already online → prints "nothing done"
3. `./launch_gitlab_runner.sh run` — with runner offline → waits 5 min → relaunches
4. `./launch_gitlab_runner.sh run -n` — with runner offline → skips wait → relaunches immediately
5. `./launch_gitlab_runner.sh run -f` — force launches regardless of status
6. `./launch_gitlab_runner.sh status` — reports process and connection status
7. `./launch_gitlab_runner.sh register` — registers with correct params, sets concurrent=24
8. `./launch_gitlab_runner.sh unregister` — removes runner cleanly
9. Kill `gitlab-runner run` process manually → re-run `./launch_gitlab_runner.sh run` → detects offline, relaunches
10. Verify log file contains timestamps and PIDs
11. `curl http://localhost:9252/metrics` returns Prometheus metrics while runner is running
12. `./launch_gitlab_runner.sh status` — with runner running → reports all 3 tiers passing
13. `./launch_gitlab_runner.sh status` — with runner killed → reports process and metrics tiers failing
14. Verify `runner.state` file exists in `GITLAB_RUNNER_DIR` after launch and contains correct PID/port
15. Simulate port conflict (e.g., `python3 -m http.server 9252 &`) → verify launch fails with clear error message
16. Cron-style invocation: `source runner.state && curl -sf http://localhost:${RUNNER_METRICS_PORT}/metrics` succeeds while runner is running
17. `export MACHINE_ID=local && ./launch_gitlab_runner.sh status` — runs without error using `config.local` paths
18. `export MACHINE_ID=local && ./launch_gitlab_runner.sh run -n` — launches runner in local dev mode, creates `~/GFS_CI_CD/LOCAL/GitLab/Runner/runner.state`
19. Full local dev workflow (Section 3.7 steps 1-10) — exercises all subcommands and edge cases on VM

### Step 10: Create `config.local` and update platform configs
**Tag:** implement, document
**Target:** `dev/ci/platforms/config.local` (new), `dev/ci/platforms/config.*` (existing)

Create `config.local` as described in Section 3.7. This file uses `$HOME`-relative paths and serves as the development/testing platform config.

Add `local` to the `case` statement in `launch_gitlab_runner.sh`:

```bash
case "${MACHINE_ID}" in
    hera | orion | hercules | wcoss2 | gaeac6)
        echo "Running GitLab Runner script on ${MACHINE_ID}"
        ;;
    local)
        echo "Running GitLab Runner script in local development mode"
        ;;
    noaacloud)
        echo "Running GitLab Runner script on ${PW_CSP}"
        ;;
    *)
        echo "Unsupported platform. Exiting with error."
        exit 1
        ;;
esac
```

Add the new `GITLAB_RUNNER_METRICS_PORT` variable to all existing platform config files:

```bash
# Port for GitLab Runner's embedded Prometheus metrics endpoint
# Used by launch_gitlab_runner.sh for liveness health checks
# Default: 9252 (IANA-allocated for GitLab Runner in Prometheus port registry)
# Bound to localhost only — not exposed to the network
export GITLAB_RUNNER_METRICS_PORT=9252
```

Verify that the new variable is added to all platform configs: `config.hera`, `config.hercules`, `config.orion`, `config.wcoss2`, `config.gaeac6`, `config.local`.

---

## 5. Target Script Structure

After implementation, the script should follow this flow:

```
launch_gitlab_runner.sh <command> [options] [token]
        │
        ├── print_usage() if -h
        │
        ├── Detect machine (detect_machine.sh) — or skip if MACHINE_ID pre-set (e.g., local)
        ├── Load modules (module-setup.sh + gw_setup.${MACHINE_ID}) — skip if local
        ├── Source platform config (config.${MACHINE_ID} or config.${PW_CSP} or config.local)
        ├── cd to GITLAB_RUNNER_DIR
        ├── Download gitlab-runner binary if missing
        ├── Resolve token ($2 → env var → file)
        │
        ├── register ──→ validate deps → ./gitlab-runner register → set concurrent
        │
        ├── run ──→ check_runner_status() [3 tiers: pgrep + metrics curl + verify]
        │          ├── -f flag? → launch_runner()
        │          ├── all 3 tiers pass? → "nothing done", exit 0
        │          ├── any tier fails + no -n → wait 5m → re-check
        │          │                      ├── still offline → launch_runner()
        │          │                      └── back online → "nothing done"
        │          └── offline + -n → launch_runner()
        │
        ├── status ──→ check_runner_status() → report + exit code
        │
        └── unregister ──→ ./gitlab-runner unregister --name
```

---

## 6. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| `pgrep` matching unrelated processes | Use specific pattern: `pgrep -f "gitlab-runner run --working-directory ${GITLAB_RUNNER_DIR}"` |
| `gitlab-runner verify` not available in older binary versions | Fall back to process-only check if verify fails |
| Killing runner during active job | `pkill` sends SIGTERM; gitlab-runner handles graceful shutdown. Add a `--grace-period` consideration. |
| Module environment changes break runner | Module loading is for environment consistency, not runner dependency — runner is a static binary |
| Token in process list visible via `ps` | Token is only used at registration time, not in `run` command — no change from current behavior |
| Metrics port conflict on shared HPC nodes | Bind to `localhost` only; make port configurable via `GITLAB_RUNNER_METRICS_PORT`; `check_port_available()` detects conflicts before launch; distinguishes "port used by another runner" vs "port used by unrelated service" |
| Metrics endpoint not available (old binary) | If `curl` to metrics port fails AND `pgrep` shows process alive, fall back to tier-1 + tier-3 only; log a warning that metrics are unavailable |
| Stale `runner.state` after crash | `check_runner_status()` validates PID is actually alive and metrics respond — a stale state file with a dead PID is handled by the tier-1 check |
| Cron job can't source platform config | `runner.state` file is self-contained — cron only needs to `source` it, no module setup or platform config required |
| `config.local` accidentally committed with user-specific paths | All paths are `$HOME`-relative — config works for any user. No hardcoded paths. |
| Module loading fails in local mode | Skip module loading when `MACHINE_ID=local` — modules are only available on supported HPC platforms |
| Hung runner process (PID alive, metrics dead) | Detect this specific case in `status` subcommand — report as "possible hung process" for operator attention |

---

## 7. Acceptance Criteria

- [ ] `launch_gitlab_runner.sh -h` prints usage with all commands and options documented
- [ ] `launch_gitlab_runner.sh run` is idempotent — does nothing if all 3 health tiers pass
- [ ] `launch_gitlab_runner.sh run` relaunches if any health tier fails (with 5-min wait unless `-n`)
- [ ] `launch_gitlab_runner.sh run -f` launches unconditionally
- [ ] `launch_gitlab_runner.sh status` reports runner health with appropriate exit code
- [ ] All log entries include timestamps and PIDs
- [ ] Stale processes are cleaned up before relaunch
- [ ] Script works on all supported platforms: Hera, Hercules, Orion, WCOSS2, Gaea C6, **local**
- [ ] `config.local` exists in `dev/ci/platforms/` with `$HOME`-relative paths
- [ ] `export MACHINE_ID=local` enables full local development workflow on any VM
- [ ] Module loading is skipped when `MACHINE_ID=local` (no Spack/Lmod available)
- [ ] No functional regression in `register` or `unregister` subcommands
- [ ] Cloud platform (`noaacloud`) config sourcing matches Jenkins pattern
- [ ] Prometheus metrics endpoint enabled on `localhost:${GITLAB_RUNNER_METRICS_PORT}` (default 9252)
- [ ] `runner.state` file written to `GITLAB_RUNNER_DIR` at launch with PID, port, timestamp, hostname
- [ ] `check_runner_status()` reads port from `runner.state` when available (cron-safe)
- [ ] `check_port_available()` detects port conflicts before launch and distinguishes runner vs non-runner occupants
- [ ] `status` subcommand reports all three health tiers (process, metrics, verify)
- [ ] `status` detects and reports hung-process condition (PID alive, metrics dead)
- [ ] `GITLAB_RUNNER_METRICS_PORT` added to all platform config files
