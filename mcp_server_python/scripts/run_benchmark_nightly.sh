#!/usr/bin/env bash
#
# run_benchmark_nightly.sh — Phase 71 nightly RAG benchmark wrapper.
#
# Runs the RAG benchmark harness, normalises its per-run result into the
# single-line-per-run JSONL schema that the `get_quality_metrics` MCP tool
# reads, appends it to `quality_metrics.jsonl` (host + container-visible
# paths), rotates old snapshots, and emits a fail-loud structured ERROR log
# when any category's score drops more than a threshold below its trailing
# N-day median.
#
# Spec: .kiro/specs/nightly-rag-benchmark-harness/  (SDD Phase 71)
#
# SCHEMA NOTE (deviation from the draft spec, intentional): the
# `get_quality_metrics` reader (src/tools/utility.py::_render_quality_metrics)
# treats each JSONL line as ONE benchmark RUN with a nested `categories` dict
# and an `overall` block, and `--compare` diffs the last two LINES (runs).
# The draft spec's "one JSONL line per category" + "keep 90 x 6" rotation
# would break `--compare` (it would diff two categories, not two time-points).
# This wrapper therefore writes one line per RUN and rotates to the last
# `KEEP_RUNS` runs — the schema the reader actually contracts for. The
# category detail lives inside each line's `categories` object.
#
# Harness: mcp_server_node/scripts/run_benchmark.js is the harness that emits
# that exact schema (overall + per-category P@K/R@K/MRR/coverage/latency)
# across the 6 categories in test/benchmark/ground_truth.json. It writes a
# timestamped file to test/benchmark/results/; this wrapper bridges that file
# into quality_metrics.jsonl. (The AWS-only config/benchmark_runner.py, which
# the draft design also referenced, targets OpenSearch/S3 and does NOT emit
# this schema — it is not used here.)
#
# All paths + the benchmark command are overridable via environment variables
# so the append/rotate/regression logic is unit-testable without the live
# databases or systemd (see MCP_BENCHMARK_CMD).
#
set -euo pipefail

# ── SPOT paths / config (all overridable) ──────────────────────────────────
REPO_ROOT="${MCP_REPO_ROOT:-/mcp_rag_eib/eib-mcp-rag-server}"
NODE_DIR="${MCP_NODE_DIR:-${REPO_ROOT}/mcp_server_node}"
SECRETS_SRC="${MCP_SECRETS_FILE:-${HOME}/.config/eib-mcp/secrets.env}"
HOST_STATE_DIR="${MCP_HOST_STATE_DIR:-/mcp_rag_eib/data/mcp-server/state}"
# Host path bind-mounted to the container's /app/sdd_framework/execution_state.
# Defaults to the host state dir so at least one copy is always written; the
# operator sets this to the RW-mount source so the in-container tool sees it.
CONTAINER_STATE_DIR="${MCP_CONTAINER_STATE_DIR:-${HOST_STATE_DIR}}"
RESULTS_DIR="${MCP_BENCHMARK_RESULTS_DIR:-${NODE_DIR}/test/benchmark/results}"
ARCHIVE_DIR="${MCP_BENCHMARK_ARCHIVE_DIR:-${HOST_STATE_DIR}/benchmark-archive}"
KEEP_RUNS="${MCP_BENCHMARK_KEEP_RUNS:-90}"
REGRESSION_PCT="${MCP_BENCHMARK_REGRESSION_PCT:-10}"
MEDIAN_WINDOW="${MCP_BENCHMARK_MEDIAN_WINDOW:-7}"
QUALITY_FILE="quality_metrics.jsonl"
# Benchmark command — overridable for testing. Default: the Node harness.
BENCHMARK_CMD="${MCP_BENCHMARK_CMD:-node ${NODE_DIR}/scripts/run_benchmark.js}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# ── 1. Source the shell secrets SPOT (best-effort) ─────────────────────────
if [[ -f "${SECRETS_SRC}" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "${SECRETS_SRC}"
  set +a
  log "[OK] sourced secrets from ${SECRETS_SRC}"
else
  log "[WARN] secrets file ${SECRETS_SRC} not found; continuing without it"
fi

mkdir -p "${HOST_STATE_DIR}" "${ARCHIVE_DIR}"

# ── 2. Run the benchmark harness ───────────────────────────────────────────
# run_benchmark.js exits 1 on a CRITICAL regression — that is a quality signal,
# not a harness failure, so we do not abort on it here. A missing result file
# (step 3) is the real failure condition.
log "[OK] running benchmark: ${BENCHMARK_CMD}"
if ( cd "${NODE_DIR}" && eval "${BENCHMARK_CMD}" ); then
  log "[OK] benchmark command completed cleanly"
else
  log "[WARN] benchmark command exited non-zero (critical regression or error)"
fi

# ── 3. Locate the freshest result JSON ─────────────────────────────────────
latest_result="$(ls -1t "${RESULTS_DIR}"/*.json 2>/dev/null | head -n1 || true)"
if [[ -z "${latest_result}" ]]; then
  log "[ERROR] no benchmark result JSON found in ${RESULTS_DIR}"
  exit 1
fi
log "[OK] latest result: ${latest_result}"

# ── 4. Compact to one line + append to both quality_metrics.jsonl paths ────
line="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])), separators=(",",":")))' "${latest_result}")"
appended=0
for d in "${HOST_STATE_DIR}" "${CONTAINER_STATE_DIR}"; do
  # Skip a duplicate write when both vars resolve to the same directory.
  if (( appended == 1 )) && [[ "${d}" == "${HOST_STATE_DIR}" ]]; then continue; fi
  mkdir -p "${d}"
  printf '%s\n' "${line}" >> "${d}/${QUALITY_FILE}"
  log "[OK] appended snapshot to ${d}/${QUALITY_FILE}"
  appended=1
  [[ "${CONTAINER_STATE_DIR}" == "${HOST_STATE_DIR}" ]] && break
done

# ── 5. Rotation: keep the last KEEP_RUNS runs; archive older lines ─────────
rotate() {
  local f="$1"
  [[ -f "${f}" ]] || return 0
  local n
  n="$(wc -l < "${f}")"
  if (( n > KEEP_RUNS )); then
    local overflow=$(( n - KEEP_RUNS ))
    local stamp
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    head -n "${overflow}" "${f}" | gzip -c > "${ARCHIVE_DIR}/quality_metrics_${stamp}.jsonl.gz"
    tail -n "${KEEP_RUNS}" "${f}" > "${f}.tmp" && mv "${f}.tmp" "${f}"
    log "[OK] rotated ${f}: archived ${overflow} old run(s), kept ${KEEP_RUNS}"
  fi
}
rotate "${HOST_STATE_DIR}/${QUALITY_FILE}"
if [[ "${CONTAINER_STATE_DIR}" != "${HOST_STATE_DIR}" ]]; then
  rotate "${CONTAINER_STATE_DIR}/${QUALITY_FILE}"
fi

# ── 6. Regression check: latest vs trailing N-run median, per category ─────
# Emits a structured JSON ERROR log line (journal-visible, greppable) for each
# category/metric whose latest score is > REGRESSION_PCT below its median over
# the trailing MEDIAN_WINDOW runs. Assumes ~1 run/day, so N runs ~= N days.
# Always exits 0 — a regression is logged loudly but is not a service failure.
python3 - "${HOST_STATE_DIR}/${QUALITY_FILE}" "${MEDIAN_WINDOW}" "${REGRESSION_PCT}" <<'PY'
import json, sys, statistics

path, window, pct = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
rows = []
try:
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
except OSError:
    sys.exit(0)

if len(rows) < 2:
    print(json.dumps({"event": "rag_quality_regression_check",
                      "status": "insufficient_history", "snapshots": len(rows)}))
    sys.exit(0)

def cats(row):
    c = dict(row.get("categories") or {})
    c["overall"] = row.get("overall") or {}
    return c

latest = cats(rows[-1])
history = [cats(r) for r in rows[-(window + 1):-1]]  # up to `window` prior runs
metrics = ("mrr", "precision_at_k", "coverage")

regressions = []
for cat, cur in latest.items():
    for m in metrics:
        cur_v = cur.get(m)
        if cur_v is None:
            continue
        vals = [h[cat][m] for h in history
                if cat in h and h[cat].get(m) is not None]
        if len(vals) < 2:
            continue
        med = statistics.median(vals)
        if med > 0 and cur_v < med * (1 - pct / 100.0):
            rec = {"event": "rag_quality_regression", "category": cat, "metric": m,
                   "score": round(cur_v, 4), f"median_{window}run": round(med, 4),
                   "drop_pct": round((med - cur_v) / med * 100, 1)}
            regressions.append(rec)
            print("[ERROR] " + json.dumps(rec), file=sys.stderr)

if not regressions:
    print(json.dumps({"event": "rag_quality_regression_check", "status": "ok",
                      "categories": len(latest)}))
sys.exit(0)
PY

log "[OK] nightly benchmark wrapper complete"
