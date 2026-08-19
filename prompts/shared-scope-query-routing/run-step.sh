#!/usr/bin/env bash
# Sequential step runner for the shared-scope-query-routing spec.
#
# One step, one agent, one process. Run them in order; review each log before
# starting the next. There is no parallelism and no grouping: the earlier
# wave-based approach kept discovering hidden couplings between supposedly
# independent tasks, and the coordination cost exceeded the benefit.
#
# Usage:
#   ./run-step.sh 1          # run step 1
#   ./run-step.sh 1 --dry    # print what would be sent, dispatch nothing
#   ./run-step.sh --list     # show the sequence

set -uo pipefail

REPO="/mdc-mcp-rag/eib-mcp-rag-server"
BRANCH="update_shared_scoping"
STEPS="${REPO}/prompts/shared-scope-query-routing/steps"
LOGS="${REPO}/logs/shared-scope-query-routing"
AGENT="spec-impl"

# step | prompt file | model | effort
step_spec() {
  case "$1" in
    1) echo "step1-task06-baselines.md|claude-opus-4.8|xhigh" ;;
    2) echo "step2-task01-scope-authority.md|claude-sonnet-5|high" ;;
    3) echo "step3-task03-catalog-transport.md|claude-sonnet-5|high" ;;
    4) echo "step4-task04-error-normalization.md|claude-sonnet-5|high" ;;
    5) echo "step5-task12_1-write-path-frozen.md|claude-sonnet-5|high" ;;
    6) echo "step6-task02-read-router.md|claude-opus-4.8|xhigh" ;;
    7) echo "step7-task07_1_7_2-condition-probe.md|claude-sonnet-5|high" ;;
    8) echo "step8-task07_3-07_8-atomic-routing.md|claude-opus-4.8|xhigh" ;;
    9) echo "step9-task08-readpath-corrections.md|claude-sonnet-5|high" ;;
    *) return 1 ;;
  esac
}

if [ "${1:-}" = "--list" ]; then
  echo "step 0  Task 2.4  property generators + adapters fixture   [DONE]"
  for n in 1 2 3 4 5 6 7 8 9; do
    IFS='|' read -r f m e <<< "$(step_spec "$n")"
    printf 'step %s  %-46s %s / %s\n' "$n" "${f}" "$m" "$e"
  done
  echo
  echo "Step 1 is one-shot: it records the pre-change baseline. Later steps"
  echo "modify rendering paths, so it cannot be redone after step 4."
  echo
  echo "Step 6 builds the Read_Router, the resolver every later step routes"
  echo "through. Opus/xhigh for the same reason step 1 got it: a wrong"
  echo "cardinality or prefix-order decision here is expensive downstream."
  echo
  echo "Step 7 is Task 7.1+7.2 only. Task 7.3/7.5/7.6 are one atomic unit"
  echo "(7.3 without 7.6 flips branch_isolation to failing for the correct"
  echo "reason) and become step 8, which also consumes the one-shot Task 6"
  echo "baselines. Landing 7.1+7.2 first shrinks that step 8 to 6 subtasks."
  echo
  echo "Step 8 is the step where the bug stops existing, and the only one"
  echo "that cannot be partially landed or retried against a fresh"
  echo "baseline. Opus/xhigh. Review its diff before anything else runs."
  echo
  echo "Step 9 (Task 8) closes what the substitution left behind: GGSR"
  echo "forwarding tenant= (without it, enriched reads bypass tenancy"
  echo "entirely) and three mis-cited preservation invariants."
  exit 0
fi

N="${1:-}"
DRY="${2:-}"
spec="$(step_spec "${N}")" || { echo "usage: $0 {1..9|--list} [--dry]"; exit 2; }
IFS='|' read -r PROMPT MODEL EFFORT <<< "${spec}"

cd "${REPO}" || exit 1

actual="$(git branch --show-current)"
[ "${actual}" = "${BRANCH}" ] || {
  echo "[ERROR] on branch '${actual}', expected '${BRANCH}'. Refusing."; exit 1; }

command -v python3.12 >/dev/null 2>&1 || {
  echo "[ERROR] python3.12 not on PATH. That is the project toolchain."; exit 1; }
for m in pytest pytest_asyncio hypothesis chromadb; do
  python3.12 -c "import ${m}" 2>/dev/null || {
    echo "[ERROR] python3.12 missing module: ${m}"; exit 1; }
done
echo "[OK] branch ${actual}, toolchain python3.12"

# Step 1 is unrepeatable: refuse if a rendering path has already moved.
if [ "${N}" = "1" ] && \
   grep -qs "read_router" mcp_server_python/src/data/chromadb_adapter.py \
                          mcp_server_python/src/data/opensearch_adapter.py; then
  echo "[ERROR] adapters already reference read_router. A baseline captured now"
  echo "[ERROR] would not be pre-change. Resolve by hand."; exit 1
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
# Block live AWS. Verified: kiro-cli authenticates independently of AWS creds, so
# this costs nothing and removes the ability to reach OpenSearch, Neptune,
# Bedrock, or update-agent-runtime even through the shell tool.
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
echo "Next: $0 $((N+1))"
