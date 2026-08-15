#!/usr/bin/env bash
# codex-review-adapter.sh — Hermes->Codex->Hermes independent review adapter
#
# Contract-compliant, reproducible adapter that runs the PROVEN diff-inline
# read-only Codex review path for a specific commit and returns a structured
# result-envelope the Hermes coordinator consumes directly. Closes the
# Hermes->Codex->Hermes integration gap observed on 2026-08-09 (reviews used to
# be copy-pasted by the operator).
#
# Evidence for #69/#70: the bare `codex exec review --commit` path is broken on
# Windows (read-only sandbox cannot spawn pwsh for `git show`;
# CreateProcessAsUserW access denied). The inline-diff-via-stdin path works and
# produced substantive verdicts (KRÄVER ÄNDRINGAR with file/line findings).
#
# SINGLE spawn path (2026-08-09 fix): Codex is ALWAYS spawned by the trusted
# PID-bound runner `codex-review-runner.ps1` in this directory. There is NO
# inline-PowerShell fallback and NO other (e.g. Kimi/Hermes) route buried here.
# Root cause fixed: the previous version embedded the helper inline via
# `powershell -Command` with `$MAX=$MAX_RUNTIME`, whose heredoc escaping left
# `$MAX_RUNTIME` unset in PowerShell => `$MAX=$null` => the timeout loop fired
# ~1s after spawn, killing Codex with 0 tokens ("helper exits after a second").
#
# Contract: docs/architecture/dispatch-contract.md
# Envelope: contracts/result-envelope.schema.json (cost/usage honest -> unknown)
# Verification: harness/scripts/codex-review-verify.py (deterministic, no model)
#
# Usage:
#   CODEX_CLI_PATH=... ./codex-review-adapter.sh <full-commit-sha> [--base <rev>]
#     --base defaults to <sha>~1 (net change of the single commit).
#   Env: CODEX_CLI_PATH (required if 'codex' is not on PATH). No hardcoded
#     versioned default — resolve off PATH first, else require explicit
#     CODEX_CLI_PATH; fail closed when neither is present.
#
# Outputs run artifacts to .hermes/codex/reviews/<sha>/ (gitignored) and prints
# a JSON result-envelope to stdout for the caller to consume/route.
#
# Safety rules enforced:
#   1. run_id generated in the SHELL, never by a model.
#   2. Read-only sandbox + --ephemeral; no session persisted.
#   3. PID-bound process-tree timeout (runner: win PID + taskkill /T), never
#      matches by process name.
#   4. Honest cost/usage: 'unknown' unless measured (never 0).
#   5. Verdict is a capability result (KRÄVER ÄNDRINGAR = PASS), NOT commit
#      approval; merge/Done remains operator-only.
#   6. No secrets/prompts placed in git, GitHub, or the channel; artifacts are
#      gitignored and local.
set -euo pipefail

log(){ echo "[codex-review] $*" >&2; }
die(){ echo "ABORT: $*" >&2; exit 1; }

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$SELF_DIR/codex-review-runner.ps1"
RUNNER_WIN="$(cygpath -w "$RUNNER" 2>/dev/null || echo "$RUNNER")"
[ -f "$RUNNER" ] || die "runner not found: $RUNNER"

# Codex CLI MUST be explicit or resolvable; never a versioned absolute default.
# 2026-08-09 rework (#70): a hardcoded per-version path breaks on any install
# change. Resolve dynamically off PATH first; if not found, require the caller to
# export CODEX_CLI_PATH. Fail closed (die) when neither is present.
if [ -n "${CODEX_CLI_PATH:-}" ]; then
    CODEX="$CODEX_CLI_PATH"
elif command -v codex >/dev/null 2>&1; then
    CODEX="$(command -v codex)"
else
    die "codex CLI not found: set CODEX_CLI_PATH or add 'codex' to PATH (fail-closed)"
fi
[ -e "$CODEX" ] || die "CODEX_CLI_PATH points to missing file: $CODEX"
MAX_RUNTIME=540
SKIP_TRUSTED_DIR="--skip-git-repo-check"

SHA="${1:-}"; [ -n "$SHA" ] || die "usage: codex-review-adapter.sh <full-commit-sha> [--base <rev>]"
BASE="${2:-}"
if [ "$BASE" = "--base" ]; then BASE="${3:-}"; fi
BASE="${BASE:-${SHA}~1}"
# Exactly 40 lowercase hex characters (2026-08-09 rework, #70).
[ "${#SHA}" -eq 40 ] || die "bad sha: $SHA (expected exactly 40 lowercase hex chars)"
case "$SHA" in *[!0-9a-f]*) die "bad sha: $SHA (non-lowercase-hex character)";; esac
[ -n "${BASE:-}" ] || die "bad --base"

cd "$REPO_DIR"
git rev-parse "$SHA" >/dev/null 2>&1 || die "commit $SHA not found locally"
git rev-parse "$BASE" >/dev/null 2>&1 || die "base $BASE not found locally"

# --- run identity (shell, outside model) — must ALWAYS be a schema-valid UUID ---
# P1 fix: never fall back to a timestamp pseudo-id when Python/uuid is missing.
# If a real UUID cannot be produced we stop fail-closed with NO envelope (a
# non-UUID run_id would violate contracts/result-envelope.schema.json).
UUID_RE='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
RUN_ID="$(python -c "import uuid; print(uuid.uuid4())" 2>/dev/null || true)"
if [[ ! "$RUN_ID" =~ $UUID_RE ]]; then
    die "run_id generation failed (python uuid missing?) — cannot emit a schema-valid envelope"
fi
log "run_id=$RUN_ID commit=$SHA base=$BASE"

# --- before fingerprint (content-level) ---
BEFORE_FP="$( ( git status --porcelain; git diff; git diff --cached; git rev-parse HEAD ) | git hash-object --stdin )"

# --- brief + diff (verbatim) ---
git diff "$BASE" "$SHA" > /tmp/codex-review-diff.$$ 2>/dev/null || true
DIFF_BYTES=$(wc -c < /tmp/codex-review-diff.$$)
[ "$DIFF_BYTES" -gt 0 ] || die "empty diff between $BASE and $SHA"
[ "$DIFF_BYTES" -le 120000 ] || die "diff too large (${DIFF_BYTES} bytes); split into coherent units (see codex-review-gate skill)"
TITLE=$(git log -1 --format=%s "$SHA")

BRIEF="Du är en oberoende, read-only kodgranskare. Granska ENDAST nedan DIFF (inbäddad
i prompten). Använd INGA verktyg, öppna INGA filer, kör INGA kommandon, hämta
INGENTING externt.

Commit under granskning: $SHA ($TITLE)

Regler (obrytbara):
- ÄNDRA/committa/pusha INGENTING. Ingen skrivning. Inga verktyg.
- Du är enda reviewern; ditt outcome är INTE commitgodkännande — operatören sluter merge/Done.
- Granska raderna i DIFF nedan ärligt mot själva innehållet.

Lämna ditt svar i exakt struktur:
- VERDICT: GODKÄND | KRÄVER ÄNDRINGAR | INGESTION MISSLYCKADES
- NOTERING: 'KRÄVER ÄNDRINGAR' = capability-PASS, ej commitgodkännande.
- Diff injesterad: ja/nej — bekräfta specifik rad du verifierat.
- FINDINGS: FIL:RAD, allvar (P0/P1/P2), förklaring. Tom lista om inga.
- KOSTNAD: endast om du mäter; annars 'unknown' (aldrig 0).
- SUMMERING: en kort svensk mening.

## DIFF (verbatim — det enda du granskar)
$(cat /tmp/codex-review-diff.$$)
"
echo "$BRIEF" > /tmp/codex-review-prompt.$$
REQ_HASH=$( ( printf '%s\0%s\0%s' "$(sha256sum /tmp/codex-review-diff.$$ | cut -d' ' -f1)" "$SHA" "$(sha256sum /tmp/codex-review-prompt.$$ | cut -d' ' -f1)" ) | sha256sum | cut -d' ' -f1 )
log "review_request_hash(sha256)=$REQ_HASH diff_bytes=$DIFF_BYTES"

# --- run dir (local, gitignored) ---
OUT_DIR="$REPO_DIR/.hermes/codex/reviews/$SHA"
mkdir -p "$OUT_DIR"

# Fail-closed: purge any STALE per-SHA artifacts from a prior run so a failed or
# never-started review can NEVER be mistaken for a fresh verdict (confirmed
# 2026-08-09: a stale last_message from an earlier review leaked a verdict when
# the runner failed to spawn). The runner re-clears at start too — belt & braces.
rm -f "$OUT_DIR/last_message.md" "$OUT_DIR/stdout.jsonl" "$OUT_DIR/stderr.log"

# --- THE single spawn path: trusted PID-bound ps1 runner ---
# Same runner that produced all valid verdicts this session. No inline helper.
# Capture the runner's exit code (2026-08-09 rework, #70): success REQUIRES
# runner exit 0; a nonzero exit (incl. timeout 124) is never "succeeded".
RUNNER_RC=0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$RUNNER_WIN" \
    -CodexPath "$CODEX" \
    -PromptFile "$(cygpath -w /tmp/codex-review-prompt.$$)" \
    -LastMessageOut "$(cygpath -w "$OUT_DIR/last_message.md")" \
    -StdoutJson "$(cygpath -w "$OUT_DIR/stdout.jsonl")" \
    -StderrLog "$(cygpath -w "$OUT_DIR/stderr.log")" \
    -MaxSec "$MAX_RUNTIME" || RUNNER_RC=$?
log "runner rc=$RUNNER_RC (see $(basename "$OUT_DIR")/stderr.log for the [run] line)"

# Verdict only from a FRESH model result (the runner purges first). A value of
# INGESTION MISSLYCKADES is NOT success even if a file exists.
VERDICT="ERROR"
if [ -f "$OUT_DIR/last_message.md" ]; then
    VERDICT="$(grep -oE 'VERDICT: (GODKÄND|KRÄVER ÄNDRINGAR|INGESTION MISSLYCKADES)' "$OUT_DIR/last_message.md" | head -1 | sed 's/VERDICT: //' || echo ERROR)"
    VERDICT="${VERDICT:-ERROR}"
fi

# --- status determination (2026-08-09 rework, #70) ---
#   runner rc 124           -> timeout           -> timed_out
#   runner rc 0 AND fresh last_message AND valid verdict -> succeeded
#   everything else         -> failed
STATUS="failed"
if [ "$RUNNER_RC" -eq 124 ]; then
    STATUS="timed_out"
elif [ "$RUNNER_RC" -eq 0 ] && [ -f "$OUT_DIR/last_message.md" ] \
     && { [ "$VERDICT" = "GODKÄND" ] || [ "$VERDICT" = "KRÄVER ÄNDRINGAR" ]; }; then
    STATUS="succeeded"
else
    STATUS="failed"
fi
COST="unknown"; grep -iq "KOSTNAD: unknown" "$OUT_DIR/last_message.md" 2>/dev/null && COST="unknown"
log "verdict=$VERDICT status=$STATUS cost=$COST runner_rc=$RUNNER_RC"

# --- after fingerprint (content-level) ---
AFTER_FP="$( ( git status --porcelain; git diff; git diff --cached; git rev-parse HEAD ) | git hash-object --stdin )"
log "before_fp=$BEFORE_FP after_fp=$AFTER_FP"

# --- result-envelope (contracts/result-envelope.schema.json shape) ---
cat > /tmp/codex-review-envelope.$$ <<JSON
{
  "issue_id": "commit $SHA",
  "run_id": "$RUN_ID",
  "status": "$STATUS",
  "runtime": "codex-cli (diff-inline via codex-review-adapter.sh -> codex-review-runner.ps1)",
  "worker_role": "codex-reviewer",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "finished_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "model": "gpt-5.6-sol",
  "usage": {},
  "cost": {"confidence": "unknown"},
  "artifacts": [
    {"ref": "$SHA", "hash": "$(sha256sum /tmp/codex-review-diff.$$ | cut -d' ' -f1)", "size": $DIFF_BYTES}
  ],
  "evidence": ["$OUT_DIR/last_message.md", "review_request_hash=$REQ_HASH", "before_fp=$BEFORE_FP", "after_fp=$AFTER_FP"]
}
JSON
rm -f /tmp/codex-review-diff.$$ /tmp/codex-review-prompt.$$ 2>/dev/null || true
echo "REVIEW_ENVELOPE_JSON"
cat /tmp/codex-review-envelope.$$
echo
echo "CODEX_REVIEW_DONE run_id=$RUN_ID commit=$SHA verdict=$VERDICT cost=$COST"
rm -f /tmp/codex-review-envelope.$$