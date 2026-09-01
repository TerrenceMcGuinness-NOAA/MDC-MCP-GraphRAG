#!/usr/bin/env bash
# run-prompt.sh — Run a prompt file through kiro-cli chat
#
# Generic prompt runner for SDD phases and ad-hoc prompts.
# Takes a markdown prompt file as input and sends it to kiro-cli
# with configurable model, effort, and agent.
#
# Usage:
#   ./run-prompt.sh <prompt-file>                           # defaults: sonnet-5 / high / spec-impl
#   ./run-prompt.sh <prompt-file> --model claude-opus-4.8   # override model
#   ./run-prompt.sh <prompt-file> --effort xhigh            # override effort
#   ./run-prompt.sh <prompt-file> --agent task-impl         # override agent
#   ./run-prompt.sh <prompt-file> --dry                     # print what would be sent
#   ./run-prompt.sh <prompt-file> --model claude-opus-4.8 --effort xhigh --dry
#
# Logs are written to logs/<prompt-basename>.log
#
set -uo pipefail

REPO="/mcp_rag_eib/eib-mcp-rag-server"
LOGS="${REPO}/logs/prompt-runs"

# ── defaults ───────────────────────────────────────────────────────────
MODEL="claude-sonnet-5"
EFFORT="high"
AGENT="spec-impl"
DRY=false
PROMPT_FILE=""

# ── parse args ─────────────────────────────────────────────────────────
usage() {
  cat <<'EOF'
Usage: run-prompt.sh <prompt-file> [OPTIONS]

Arguments:
  <prompt-file>       Path to a markdown prompt file (.md)

Options:
  --model MODEL       Model to use (default: claude-sonnet-5)
                      Examples: claude-sonnet-5, claude-opus-4.8
  --effort EFFORT     Effort level (default: high)
                      Options: low, medium, high, xhigh
  --agent AGENT       Agent name (default: spec-impl)
  --dry               Print what would be sent, don't execute
  --help              Show this help

Examples:
  ./run-prompt.sh prompts/phase82_cots_cypher_dialect_parity_prompt.md
  ./run-prompt.sh prompts/phase82_cots_cypher_dialect_parity_prompt.md --model claude-opus-4.8 --effort xhigh
  ./run-prompt.sh prompts/phase82_cots_cypher_dialect_parity_prompt.md --dry
EOF
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)   MODEL="$2"; shift 2 ;;
    --effort)  EFFORT="$2"; shift 2 ;;
    --agent)   AGENT="$2"; shift 2 ;;
    --dry)     DRY=true; shift ;;
    --help|-h) usage 0 ;;
    -*)        echo "[ERROR] Unknown option: $1" >&2; usage 1 ;;
    *)
      if [[ -z "${PROMPT_FILE}" ]]; then
        PROMPT_FILE="$1"; shift
      else
        echo "[ERROR] Unexpected argument: $1" >&2; usage 1
      fi
      ;;
  esac
done

if [[ -z "${PROMPT_FILE}" ]]; then
  echo "[ERROR] No prompt file specified." >&2
  usage 1
fi

# ── resolve prompt file ───────────────────────────────────────────────
# Accept absolute paths, relative to CWD, or relative to repo root
if [[ -f "${PROMPT_FILE}" ]]; then
  PROMPT_PATH="$(cd "$(dirname "${PROMPT_FILE}")" && pwd)/$(basename "${PROMPT_FILE}")"
elif [[ -f "${REPO}/${PROMPT_FILE}" ]]; then
  PROMPT_PATH="${REPO}/${PROMPT_FILE}"
else
  echo "[ERROR] Prompt file not found: ${PROMPT_FILE}" >&2
  echo "        Tried: ${PROMPT_FILE}" >&2
  echo "        Tried: ${REPO}/${PROMPT_FILE}" >&2
  exit 1
fi

PROMPT_NAME="$(basename "${PROMPT_PATH}" .md)"

# ── pre-flight checks ─────────────────────────────────────────────────
KIRO_CLI="${HOME}/.local/bin/kiro-cli"
if ! command -v kiro-cli >/dev/null 2>&1 && [[ ! -x "${KIRO_CLI}" ]]; then
  echo "[ERROR] kiro-cli not found. Run: SETUP/update-kiro-cli-musl.sh" >&2
  exit 1
fi
# Prefer the one on PATH, fall back to ~/.local/bin
KIRO="$(command -v kiro-cli 2>/dev/null || echo "${KIRO_CLI}")"

cd "${REPO}" || exit 1

BRANCH="$(git branch --show-current)"
echo "[OK] repo: ${REPO}"
echo "[OK] branch: ${BRANCH}"
echo "[OK] kiro-cli: $(${KIRO} --version 2>/dev/null || echo 'unknown')"
echo "[OK] prompt: ${PROMPT_PATH} ($(wc -c < "${PROMPT_PATH}") bytes)"
echo "[OK] model: ${MODEL}  effort: ${EFFORT}  agent: ${AGENT}"

# ── prepare log ────────────────────────────────────────────────────────
mkdir -p "${LOGS}"
TIMESTAMP="$(date +%F_%H%M%S)"
LOG="${LOGS}/${PROMPT_NAME}_${TIMESTAMP}.log"

# ── read prompt body ───────────────────────────────────────────────────
BODY="$(cat "${PROMPT_PATH}")"

if ${DRY}; then
  echo ""
  echo "[DRY] Would send $(printf '%s' "${BODY}" | wc -c) bytes to:"
  echo "[DRY]   kiro-cli chat --agent ${AGENT} --model ${MODEL} --effort ${EFFORT} --no-interactive"
  echo "[DRY] Log: ${LOG}"
  echo ""
  echo "--- Prompt preview (first 40 lines) ---"
  head -40 "${PROMPT_PATH}"
  echo "..."
  exit 0
fi

echo ""
echo "[RUN] ${PROMPT_NAME}  model=${MODEL}  effort=${EFFORT}"
echo "[RUN] log: ${LOG}"
echo ""

# Block live AWS — kiro-cli authenticates independently, but this prevents
# the agent from reaching OpenSearch, Neptune, Bedrock, or any AWS service
# through shell tool invocations.
env -u AWS_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY \
    -u AWS_SESSION_TOKEN -u AWS_CONTAINER_CREDENTIALS_FULL_URI \
    -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI \
    AWS_EC2_METADATA_DISABLED=true \
    AWS_SHARED_CREDENTIALS_FILE=/dev/null \
    AWS_CONFIG_FILE=/dev/null \
  "${KIRO}" chat --agent "${AGENT}" --model "${MODEL}" --effort "${EFFORT}" \
                 --no-interactive "${BODY}" 2>&1 | tee "${LOG}"

echo ""
echo "[DONE] Log saved: ${LOG}"
echo "Review: less ${LOG}"
echo "Status: git status --porcelain=v1"
