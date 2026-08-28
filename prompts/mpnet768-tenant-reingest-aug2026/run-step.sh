#!/usr/bin/env bash
# Sequential step runner for the mpnet768-tenant-reingest-aug2026 spec.
#
# One step, one agent, one process. Run them in order; review each log before
# starting the next.
#
# This is the SPEC-IMPLEMENTATION harness (Tasks 1-10 from tasks.md). The
# reingest RUN itself is driven by scripts/ralph_reingest_loop.sh, not by this
# script.
#
# Usage:
#   ./run-step.sh 1          # run step 1
#   ./run-step.sh 1 --dry    # print what would be sent, dispatch nothing
#   ./run-step.sh --list     # show the sequence

set -uo pipefail

REPO="/mcp_rag_eib/eib-mcp-rag-server"
BRANCH="mpnet768-tenant-reingest-aug2026"
STEPS="${REPO}/prompts/mpnet768-tenant-reingest-aug2026/steps"
LOGS="${REPO}/logs/mpnet768-tenant-reingest-aug2026"
AGENT="spec-impl"

# step | prompt file | model | effort
step_spec() {
  case "$1" in
    1) echo "step1-task01-state-scope-field.md|claude-sonnet-5|high" ;;
    2) echo "step2-task02-stage-catalog.md|claude-opus-4.8|xhigh" ;;
    3) echo "step3-task03-neo4j-index-rebuild.md|claude-opus-4.8|xhigh" ;;
    4) echo "step4-task04-validation-probe.md|claude-sonnet-5|high" ;;
    5) echo "step5-task05-iteration-prompt.md|claude-sonnet-5|high" ;;
    6) echo "step6-task06-manifest-writeback.md|claude-sonnet-5|high" ;;
    7) echo "step7-task07-cutover-script.md|claude-sonnet-5|high" ;;
    8) echo "step8-task08-dry-run-integration.md|claude-opus-4.8|xhigh" ;;
    9) echo "step9-task09-verification-record.md|claude-sonnet-5|high" ;;
   10) echo "step10-task10-changelog-and-phase81.md|claude-sonnet-5|high" ;;
    *) return 1 ;;
  esac
}

if [ "${1:-}" = "--list" ]; then
  echo "step 0  Preamble — read once, do not run                           [DOC]"
  for n in 1 2 3 4 5 6 7 8 9 10; do
    IFS='|' read -r f m e <<< "$(step_spec "$n")"
    printf 'step %s  %-50s %s / %s\n' "$n" "${f}" "$m" "$e"
  done
  echo
  echo "Steps 3 and 5 are hard prerequisites for step 8 — the dry-run walk"
  echo "cannot init a Work_Matrix that references a non-existent index-rebuild"
  echo "script, and the Iteration_Prompt's step 3 tenancy precheck reads the"
  echo "new scope/shared_once fields the catalog carries."
  echo
  echo "Steps 1, 3, 4, and 7 are independently shippable. Step 8 is where"
  echo "the whole extension gets exercised end-to-end (dry-run, no writes)."
  echo "The LIVE loop is scripts/ralph_reingest_loop.sh, not this harness."
  exit 0
fi

N="${1:-}"
DRY="${2:-}"

if [ -z "${N}" ] || ! IFS='|' read -r PROMPT_FILE MODEL EFFORT <<< "$(step_spec "${N}")"; then
  echo "Usage: ./run-step.sh <step-number> [--dry]" >&2
  echo "       ./run-step.sh --list" >&2
  exit 2
fi

PROMPT_PATH="${STEPS}/${PROMPT_FILE}"
LOG_PATH="${LOGS}/step${N}-$(date +%Y%m%dT%H%M%S).log"

if [ ! -f "${PROMPT_PATH}" ]; then
  echo "[ERROR] prompt file not found: ${PROMPT_PATH}" >&2
  echo "        author it before running this step." >&2
  exit 3
fi

mkdir -p "${LOGS}"

echo "[INFO] step ${N}: ${PROMPT_FILE}"
echo "[INFO] model:  ${MODEL}"
echo "[INFO] effort: ${EFFORT}"
echo "[INFO] log:    ${LOG_PATH}"
echo "[INFO] repo:   ${REPO}"
echo "[INFO] branch: ${BRANCH}"

if [ "${DRY}" = "--dry" ]; then
  echo "[DRY-RUN] would dispatch:"
  echo "  kiro-cli chat --agent ${AGENT} --model ${MODEL} --effort ${EFFORT} \\"
  echo "    --prompt-file ${PROMPT_PATH}"
  exit 0
fi

cd "${REPO}"
kiro-cli chat \
  --agent "${AGENT}" \
  --model "${MODEL}" \
  --effort "${EFFORT}" \
  --prompt-file "${PROMPT_PATH}" \
  2>&1 | tee "${LOG_PATH}"
