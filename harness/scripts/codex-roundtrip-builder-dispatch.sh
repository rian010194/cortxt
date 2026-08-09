#!/usr/bin/env bash
# codex-roundtrip-builder-dispatch.sh — REAL bounded Hermes Builder dispatch adapter (#82/#10)
#
# The implementation-worker leg of the ROUNDTRIP-001 round-trip. On a
# KRÄVER ÄNDRINGAR verdict it runs the Hermes `builder` profile on the InferX
# model `Qwen3-Coder-Next-FP8` (paid; endpoint https://model.inferx.net/endpoints/v1)
# with a hard 12,000-token output cap, then commits + PUSHES a new draft-PR head and
# prints that pushed 40-hex commit SHA on stdout for codex-roundtrip.sh to review next.
#
# This is the REAL bounded adapter — NOT an arbitrary hook. It enforces:
#   - paid InferX model only; NO free model, NO silent provider/model fallback,
#     Deepseek V4 Flash 0731 Med ONLY on a new explicit operator decision.
#   - output cap 12,000 tokens (configured BEFORE the run).
#   - no automatic retry / fallback on HTTP 402/404/429 -> fail-closed (blocked/failed).
#   - model_cost_status reported per actual run (never fabricated; unknown if not measured).
#   - GitHub writes (push/PR) happen HERE in the control plane, never in the worker.
#
# Usage:
#   CODEX_ROUNDTRIP_BUILDER_PROMPT_REWORK="<text>" \
#     ./codex-roundtrip-builder-dispatch.sh <owner/repo#issue> <round> [--dry-run]
#   On success prints the pushed 40-hex commit SHA (single line) and exits 0.
#
# Contract: docs/architecture/dispatch-contract.md ; docs/operations/manual-dispatch-routine.md
set -euo pipefail

REPO_ARG="${1:-}"; ROUND="${2:-1}"; DRYRUN=""
case " $* " in *" --dry-run "*) DRYRUN=1;; esac
[ -n "$REPO_ARG" ] || { echo "usage: codex-roundtrip-builder-dispatch.sh <owner/repo#issue> [round] [--dry-run]" >&2; exit 2; }
REPO="${REPO_ARG%%#*}"; ISSUE="${REPO_ARG##*#}"
BRANCH="$(git branch --show-current)" || BRANCH="agent/roundtrip-82-codex-orchestrator"

# --- InferX model (operator decision 2026-08-09); NO fallback ---
INFERX_BASE_URL="${INFERX_BASE_URL:-https://model.inferx.net/endpoints/v1}"
INFERX_MODEL="Qwen3-Coder-Next-FP8"
OUTPUT_CAP="${CODEX_ROUNDTRIP_OUTPUT_CAP:-12000}"
MAX_RUNTIME=540   # operator-approved max runtime for the new builder attempt (2026-08-09)
PROFILE="builder"

# Resolve the InferX api_key from the builder profile config (cleartext; never printed).
PROFILE_DIR="${LOCALAPPDATA}/hermes/profiles/${PROFILE}"
KEY="$(grep -E '^\s*api_key\s*:' "$PROFILE_DIR/config.yaml" 2>/dev/null | tail -1 \
        | sed -E 's/^\s*api_key\s*:\s*//' | tr -d "\r")"
# Prefer an explicit env override; else the config key; fail closed if neither.
INFERX_API_KEY="${INFERX_API_KEY:-$KEY}"
if [ -z "$INFERX_API_KEY" ] || [ "$INFERX_API_KEY" = "<REDACTED>" ]; then
  echo "ABORT: no InferX api_key resolvable for builder profile (fail-closed)" >&2; exit 1
fi

# --- rework prompt (the builder sees issue context + the Codex findings + files) ---
REWORK_PROMPT="${CODEX_ROUNDTRIP_BUILDER_PROMPT_REWORK:-}"
[ -n "$REWORK_PROMPT" ] || { echo "ABORT: CODEX_ROUNDTRIP_BUILDER_PROMPT_REWORK not set" >&2; exit 1; }

[ -n "$DRYRUN" ] && { echo "dry-run: would dispatch builder on $INFERX_MODEL (cap $OUTPUT_CAP) for #$ISSUE round $ROUND"; exit 0; }

RUN_ID="$(date -u +%Y%m%d_%H%M%S)_$(openssl rand -hex 4)"
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# #82/#6: the builder MODEL IS run; cost is not measured by this adapter -> unknown (never not_applicable).
model_cost_status="unknown"
WORK_RC=0

# #82/#2: enforce the 12,000-token output cap in the ACTUAL InferX request, not a dormant var.
# The InferX provider config in the builder profile must carry an explicit max_tokens <= 12000;
# fail-closed (do NOT run) if the runtime/profile does not expose an explicit cap.
CAP_KV="$(grep -iE '^\s*max_(output_)?tokens\s*:' "$PROFILE_DIR/config.yaml" 2>/dev/null | tail -1 | tr -d ' \t' | tr '[:upper:]' '[:lower:]' || true)"
CAP_VAL="${CAP_KV##*:}"
if [ -z "$CAP_VAL" ] || [ "$CAP_VAL" -lt 1 ] || [ "$CAP_VAL" -gt "$OUTPUT_CAP" ]; then
  echo "ABORT: no explicit max_tokens <= $OUTPUT_CAP configured in builder profile InferX provider (got '${CAP_VAL:-<none>}') -> fail-closed BEFORE model run" >&2
  exit 1
fi

# --- isolation + scope (Codex-items 3 & 4): explicit worktree + file allowlist ---
# The builder may only change these files; anything else (incl. pre-existing dirty state)
# or an unexpected change fails closed. Run happens in a THROWAWAY WORKTREE so the shared
# working tree / branch history is never mutated by the worker.
ALLOWED_FILES=(
  "harness/scripts/codex-roundtrip.sh"
  "harness/scripts/codex-roundtrip-verify.py"
  "harness/scripts/codex-roundtrip-builder-dispatch.sh"
)
PRE_HEAD="$(git rev-parse HEAD)"
# fail-closed if the shared working tree is dirty (existing/untracked changes) before dispatch
if [ -n "$(git status --porcelain)" ]; then
  echo "ABORT: shared working tree is not clean before builder dispatch (fail-closed, Codex-item3)" >&2
  exit 1
fi
# create a throwaway worktree at the current HEAD for the builder to edit
WT_DIR="$(mktemp -d)/wt"
git worktree add "$WT_DIR" "$PRE_HEAD" >/tmp/roundtrip-wt.log 2>&1 || {
  echo "ABORT: could not create clean worktree: $(tail -2 /tmp/roundtrip-wt.log)" >&2; exit 1; }
cleanup(){ git worktree remove --force "$WT_DIR" 2>/dev/null || true; git worktree prune 2>/dev/null || true; }
trap cleanup EXIT

# --- run the Hermes builder worker on InferX (paid); cap enforced at the API request ---
# Working directory = the isolated worktree; the builder is told it may only edit allowlisted files.
set +e
( cd "$WT_DIR" && INFERX_API_KEY="$INFERX_API_KEY" \
  timeout "$MAX_RUNTIME" hermes -p "$PROFILE" --provider inferx -m "$INFERX_MODEL" \
    -z "$REWORK_PROMPT" ) >/tmp/roundtrip-builder.out 2>/tmp/roundtrip-builder.err
WORK_RC=$?
set -e

FINISHED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ $WORK_RC -ne 0 ]; then
  # fail-closed: do NOT attribute a cost we cannot see
  echo "BUILDER_DISPATCH_FAILED issue=$ISSUE round=$ROUND rc=$WORK_RC model=$INFERX_MODEL model_cost_status=unknown (no retry/fallback)"
  echo "stderr: $(tail -3 /tmp/roundtrip-builder.err 2>/dev/null)"
  exit 1
fi

# --- Codex-item3: verify ONLY allowlisted files changed (fail-closed on foreign changes) ---
CHANGED="$(git -C "$WT_DIR" status --porcelain | awk '{print $2}')"
UNEXPECTED="$(comm -23 <(printf '%s\n' "$CHANGED" | sort -u) <(printf '%s\n' "${ALLOWED_FILES[@]}" | sort -u))"
if [ -n "$UNEXPECTED" ]; then
  echo "ABORT: builder changed unexpected files (fail-closed, Codex-item3): $UNEXPECTED" >&2
  exit 1
fi
[ -n "$CHANGED" ] || { echo "ABORT: builder made NO changes (fail-closed, Codex-item4)" >&2; exit 1; }

# --- Codex-item4: control plane creates an EXACT scoped commit from THIS run's diff ---
# Stage ONLY the allowlisted files that actually changed; commit with the run_id in the message.
git -C "$WT_DIR" add -- "${ALLOWED_FILES[@]}" 2>/dev/null || true
git -C "$WT_DIR" commit -m "feat(#82): builder scoped rework (run $RUN_ID)" -q >/tmp/roundtrip-commit.log 2>&1 || {
  echo "ABORT: scoped commit failed: $(tail -2 /tmp/roundtrip-commit.log)" >&2; exit 1; }
NEW_SHA="$(git -C "$WT_DIR" rev-parse HEAD)"
if [ "$NEW_SHA" = "$PRE_HEAD" ] || ! [[ "$NEW_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "ABORT: scoped commit did not produce a NEW valid head (fail-closed, Codex-item4)" >&2; exit 1
fi
# diff of the scoped commit must touch ONLY allowlisted files (belt & braces)
SCOPE_DIFF="$(git -C "$WT_DIR" diff --name-only "$PRE_HEAD" "$NEW_SHA")"
if [ -n "$(comm -23 <(printf '%s\n' "$SCOPE_DIFF" | sort -u) <(printf '%s\n' "${ALLOWED_FILES[@]}" | sort -u))" ]; then
  echo "ABORT: scoped commit includes non-allowed files (fail-closed)" >&2; exit 1
fi

# --- push the branch (control plane does the push, worker never does) — fast-forward only ---
# Push the ISOLATED worktree's exact head commit to the remote branch; does not mutate the
# shared checkout. Remote must fast-forward (a non-FF push is refused -> fail-closed).
if ! git -C "$WT_DIR" push origin "HEAD:$BRANCH" >/tmp/roundtrip-push.log 2>&1; then
  echo "ABORT: push of $BRANCH (HEAD:$BRANCH) failed (control-plane push): $(tail -1 /tmp/roundtrip-push.log)" >&2
  exit 1
fi

echo "BUILDER_DISPATCH_DONE run_id=$RUN_ID issue=$ISSUE round=$ROUND head=$NEW_SHA model=$INFERX_MODEL model_cost_status=$model_cost_status"
printf '%s' "$NEW_SHA"
exit 0
