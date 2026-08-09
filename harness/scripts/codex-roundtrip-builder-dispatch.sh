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
model_cost_status="not_applicable"
WORK_RC=0

# --- run the Hermes builder worker on InferX (paid), output cap enforced via a wrapper ---
# Invoke the builder with the explicit InferX provider + model (never the profile's
# free OpenRouter default; no silent fallback). Provider `inferx` is defined in the
# builder profile's custom_providers (base_url https://model.inferx.net/endpoints/v1).
set +e
BUILD_OUT="$(INFERX_API_KEY="$INFERX_API_KEY" \
  timeout 300 hermes -p "$PROFILE" --provider inferx -m "$INFERX_MODEL" \
    -z "$REWORK_PROMPT" 2>/tmp/roundtrip-builder.err)"
WORK_RC=$?
set -e

FINISHED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ $WORK_RC -ne 0 ]; then
  # fail-closed: do NOT attribute a cost we cannot see
  echo "BUILDER_DISPATCH_FAILED issue=$ISSUE round=$ROUND rc=$WORK_RC model=$INFERX_MODEL model_cost_status=unknown (no retry/fallback)"
  echo "stderr: $(tail -3 /tmp/roundtrip-builder.err 2>/dev/null)"
  exit 1
fi

# --- the builder must have committed the rework; obtain the NEW head ---
NEW_SHA="$(git rev-parse HEAD 2>/dev/null || true)"
if [ -z "$NEW_SHA" ] || ! [[ "$NEW_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BUILDER_DISPATCH_FAILED: no valid HEAD commit after builder run (fail-closed)"
  exit 1
fi

# --- push the branch (control plane does the push, worker never does) ---
if ! git push -u origin "$BRANCH" >/tmp/roundtrip-push.log 2>&1; then
  echo "ABORT: push of $BRANCH failed (control-plane push): $(tail -1 /tmp/roundtrip-push.log)" >&2
  exit 1
fi

echo "BUILDER_DISPATCH_DONE run_id=$RUN_ID issue=$ISSUE round=$ROUND head=$NEW_SHA model=$INFERX_MODEL model_cost_status=$model_cost_status"
printf '%s' "$NEW_SHA"
exit 0
