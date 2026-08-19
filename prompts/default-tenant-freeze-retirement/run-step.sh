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
    2) echo "step2-task02-tenant-cases.md|claude-sonnet-5|high" ;;
    3) echo "step3-task03_1_3_2-shim-and-run.md|claude-opus-4.8|xhigh" ;;
    4) echo "step4-task03_3-03_6-cli-and-tests.md|claude-sonnet-5|high" ;;
    5) echo "step5-task04-wrapper-integration.md|claude-sonnet-5|high" ;;
    6) echo "step6-task06_1_6_2-structural.md|claude-opus-4.8|xhigh" ;;
    7) echo "step7-task06_3_6_4-atomic-reporting.md|claude-opus-4.8|xhigh" ;;
    8) echo "step8-task08_1_8_2-addressing.md|claude-sonnet-5|high" ;;
    *) return 1 ;;
  esac
}

if [ "${1:-}" = "--list" ]; then
  echo "Authored and dispatchable:"
  for n in 1 2 3 4 5 6 7 8; do
    IFS='|' read -r f m e <<< "$(step_spec "$n")"
    printf '  step %s  %-44s %s / %s\n' "$n" "${f}" "$m" "$e"
  done
  echo
  echo "Planned, not yet authored (written one at a time, so each can carry"
  echo "findings from the step before it -- the same way the Phase 79 harness"
  echo "was built):"
  cat <<'PLAN'
  step 9   Task 8.3     ATOMIC R6.2 supersession + both replacements
  step 10  Task 10      no-runtime-change gate, Retirement_Record, doc asserts
PLAN
  echo
  echo "Step 1 contains a ONE-SHOT sub-task. Task 1.2 records the corpus"
  echo "categories digest BEFORE step 2 adds tenant_categories. Recorded after,"
  echo "it certifies the post-change bytes and Property 8 becomes a tautology."
  echo
  echo "Step 8 builds the query-tool half of the replacement. Unlike step 6"
  echo "it cannot parse the render: the visible Collection field carries the"
  echo "LOGICAL name, and the capture stub sees the logical name too, so"
  echo "physical addressing is not in the text at all. It works against the"
  echo "router plus both adapters instead. Nothing calls it until step 9."
  echo
  echo "STEP 7 IS THE FIRST ATOMIC STEP. Task 6.3 lands the R6.3 supersession"
  echo "and the structural swap in ONE change. A commit that relaxes the"
  echo "criterion without the replacement present leaves the default-tenant"
  echo "reporting path with no gate at all -- worse than either end state."
  echo "It expects NO new failures: the comparison method changes, the"
  echo "rendered output does not."
  echo
  echo "Step 6 builds the comparison that replaces byte-equality for the"
  echo "three reporting tools. Nothing calls it yet -- byte-equality stays"
  echo "fully in force through step 6, which is why it is separated from"
  echo "the atomic swap in step 7. Opus/xhigh: the extraction rules turn"
  echo "on details the recorded baselines do not even contain."
  echo
  echo "Step 5 is small: the wrapper default is ALREADY 10, so the threshold"
  echo "change is comment text only. Its value is the log-history tests --"
  echo "in particular that a two-line log reports ok while evaluating no"
  echo "metric at all, which reads as a passing gate and is not one."
  echo
  echo "Step 4 closes out the harness: the command line plus the tests for"
  echo "everything steps 1-3 built. Its token check needs the boundary-"
  echo "anchored form -- a raw _tool_ substring search cannot pass, because"
  echo "the mandated build_tool_map contains it. Design Property 12 amended."
  echo
  echo "Step 3 writes the part that actually calls the tools. Two traps in it"
  echo "fail silently rather than loudly: a null catalog makes all eight"
  echo "tenant cases look like a router bug, and sharing the Node results"
  echo "folder lets the wrapper record a stale Node result as a Python run."
  echo
  echo "Step 2 edits the shared corpus the older Node benchmark also reads."
  echo "Its new cases go in a separate top-level section for that reason:"
  echo "inside the existing one they would shift Node per-category counts"
  echo "from 10 to 11 and move the shared history the gate compares to."
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
  echo "usage: $0 {1..8|--list} [--dry]"
  echo "(steps 9-10 are planned but not yet authored; see --list)"; exit 2; }
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
