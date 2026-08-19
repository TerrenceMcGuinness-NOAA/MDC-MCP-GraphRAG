#!/usr/bin/env bash
# Sequential step runner for the default-tenant-freeze-retirement spec.
#
# One step, one agent, one process. Run them in order; review each log before
# starting the next. There is no parallelism and no grouping, for the reason the
# shared-scope-query-routing runner records: the wave-based approach kept
# discovering hidden couplings between supposedly independent tasks, and the
# coordination cost exceeded the benefit. tasks.md still carries a wave map --
# it is the dependency truth, not a dispatch plan.
#
# Usage:
#   ./run-step.sh 1          # run step 1
#   ./run-step.sh 1 --dry    # print what would be sent, dispatch nothing
#   ./run-step.sh --list     # show the sequence
#
# Branch: set DTFR_BRANCH to the branch this work belongs on. It defaults to
# the branch you are currently on, so the guard is opt-in rather than a
# hardcoded name that goes stale -- this spec's work has not been assigned a
# branch yet at the time the runner was written.

set -uo pipefail

REPO="/mdc-mcp-rag/eib-mcp-rag-server"
STEPS="${REPO}/prompts/default-tenant-freeze-retirement/steps"
LOGS="${REPO}/logs/default-tenant-freeze-retirement"
AGENT="spec-impl"

# step | prompt file | model | effort
step_spec() {
  case "$1" in
    1) echo "step1-task01-scoring-core.md|claude-opus-4.8|xhigh" ;;
    *) return 1 ;;
  esac
}

if [ "${1:-}" = "--list" ]; then
  echo "Authored and dispatchable:"
  for n in 1; do
    IFS='|' read -r f m e <<< "$(step_spec "$n")"
    printf '  step %s  %-44s %s / %s\n' "$n" "${f}" "$m" "$e"
  done
  echo
  echo "Planned, not yet authored (written one at a time, so each can carry"
  echo "findings from the step before it -- the same way the Phase 79 harness"
  echo "was built):"
  cat <<'PLAN'
  step 2   Task 2       corpus tenant_categories + P8 + anchoring guard
  step 3   Task 3.1-3.2 Registration_Shim, real catalog, orchestration, record
  step 4   Task 3.3-3.6 CLI, exits, P4/P9/P10/P14, P11/P12, failure tables
  step 5   Task 4       wrapper threshold comment + integration/log-history
  step 6   Task 6.1-6.2 structural.py + P1/P2/P3
  step 7   Task 6.3-6.4 ATOMIC R6.3 supersession + README status
  step 8   Task 8.1-8.2 addressing.py + P13
  step 9   Task 8.3     ATOMIC R6.2 supersession + both replacements
  step 10  Task 10      no-runtime-change gate, Retirement_Record, doc asserts
PLAN
  echo
  echo "Step 1 contains a ONE-SHOT sub-task. Task 1.2 records the corpus"
  echo "categories digest BEFORE step 2 adds tenant_categories. Recorded after,"
  echo "it certifies the post-change bytes and Property 8 becomes a tautology."
  echo
  echo "Steps 7 and 9 are ATOMIC. Each lands a freeze supersession together with"
  echo "its replacement check, because R8.2/R8.3 forbid any revision in which a"
  echo "criterion is relaxed and its replacement is absent. Ordering alone still"
  echo "permits a one-commit ungated window."
  exit 0
fi

N="${1:-}"
DRY="${2:-}"
spec="$(step_spec "${N}")" || {
  echo "usage: $0 {1|--list} [--dry]"
  echo "(steps 2-10 are planned but not yet authored; see --list)"; exit 2; }
IFS='|' read -r PROMPT MODEL EFFORT <<< "${spec}"

cd "${REPO}" || exit 1

actual="$(git branch --show-current)"
expected="${DTFR_BRANCH:-${actual}}"
[ "${actual}" = "${expected}" ] || {
  echo "[ERROR] on branch '${actual}', DTFR_BRANCH expects '${expected}'. Refusing."
  exit 1; }
echo "[OK] branch ${actual}"

command -v python3.12 >/dev/null 2>&1 || {
  echo "[ERROR] python3.12 not on PATH. That is the project toolchain."; exit 1; }
for m in pytest pytest_asyncio hypothesis chromadb; do
  python3.12 -c "import ${m}" 2>/dev/null || {
    echo "[ERROR] python3.12 missing module: ${m}"; exit 1; }
done
echo "[OK] toolchain python3.12"

# Step 1 is unrepeatable: refuse if the corpus has already grown.
if [ "${N}" = "1" ] && \
   grep -qs "tenant_categories" mcp_server_node/test/benchmark/ground_truth.json; then
  echo "[ERROR] the corpus already carries tenant_categories. A categories"
  echo "[ERROR] digest recorded now would not be pre-change. Resolve by hand."
  exit 1
fi

# src/ must be untouched by every step in this feature.
if ! git diff --quiet -- mcp_server_python/src/; then
  echo "[WARN] mcp_server_python/src/ has uncommitted changes. This feature"
  echo "[WARN] changes nothing under src/ -- review before dispatching."
fi

mkdir -p "${LOGS}"
BODY="$(cat "${STEPS}/00-preamble.md"; printf '\n\n'; cat "${STEPS}/${PROMPT}")"
LOG="${LOGS}/step${N}.log"

if [ "${DRY}" = "--dry" ]; then
  echo "[DRY] step ${N}: ${PROMPT}  model=${MODEL} effort=${EFFORT}"
  echo "[DRY] would send $(printf '%s' "${BODY}" | wc -c) bytes -> ${LOG}"
  exit 0
fi

echo "[RUN] step ${N}: ${PROMPT}  model=${MODEL} effort=${EFFORT}"
echo "[RUN] log: ${LOG}"
# Block live AWS. kiro-cli authenticates independently of AWS creds, so this
# costs nothing and removes the ability to reach OpenSearch, Neptune, Bedrock,
# or update-agent-runtime even through the shell tool. Every test in this
# feature is hermetic by requirement (R3.7).
env -u AWS_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY \
    -u AWS_SESSION_TOKEN -u AWS_CONTAINER_CREDENTIALS_FULL_URI \
    -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI \
    AWS_EC2_METADATA_DISABLED=true \
    AWS_SHARED_CREDENTIALS_FILE=/dev/null \
    AWS_CONFIG_FILE=/dev/null \
  kiro-cli chat --agent "${AGENT}" --model "${MODEL}" --effort "${EFFORT}" \
                --no-interactive "${BODY}" 2>&1 | tee "${LOG}"

echo
echo "Review ${LOG}, then: git status --porcelain=v1"
echo "Confirm: git diff --stat mcp_server_python/src/   (must be empty)"
echo "Next: author step $((N+1)) before running it"
