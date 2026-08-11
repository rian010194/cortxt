#!/usr/bin/env bash
# Hash-bound artifact review ingress for the merged Hermes -> Codex round-trip.
# It is intentionally thin: the existing PID-bound Codex runner remains the
# only model spawn path, while GitHub remains the workflow/evidence authority.
set -euo pipefail

REPO="rian010194/ai-workspace-control-plane"
ISSUE=""
ARTIFACT=""
EXPECTED_SHA=""
MAX_BYTES="${CODEX_ARTIFACT_MAX_BYTES:-200000}"
NO_GITHUB="${CODEX_ARTIFACT_NO_GITHUB:-}"
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SELF_DIR/../.." && pwd)"
RUNNER="${CODEX_ARTIFACT_RUNNER:-$SELF_DIR/codex-review-runner.ps1}"
PROJECT_ID="PVT_kwHOBcHJy84BfFfW"
WF_FIELD="PVTSSF_lAHOBcHJy84BfFfWzhZa88A"
OPT_INPROGRESS="89a2da8a"
OPT_REVIEW="4bfdd926"
OPT_BLOCKED="20948c2f"
CLAIMED=0
TERMINAL=0

log(){ printf '[artifact-review] %s\n' "$*" >&2; }
die(){ log "ABORT: $*"; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    -R|--repo) REPO="${2:-}"; shift 2;;
    -i|--issue) ISSUE="${2:-}"; shift 2;;
    -a|--artifact) ARTIFACT="${2:-}"; shift 2;;
    --sha256) EXPECTED_SHA="${2:-}"; shift 2;;
    *) die "unknown argument: $1";;
  esac
done

[[ "$ISSUE" =~ ^[1-9][0-9]*$ ]] || die "--issue must be a positive integer"
[[ "$EXPECTED_SHA" =~ ^[0-9A-Fa-f]{64}$ ]] || die "--sha256 must be exactly 64 hex characters"
[[ "$MAX_BYTES" =~ ^[1-9][0-9]*$ ]] || die "CODEX_ARTIFACT_MAX_BYTES must be a positive integer"
[ -n "$ARTIFACT" ] || die "--artifact is required"
case "$ARTIFACT" in
  /*|[A-Za-z]:*|*..*) die "artifact must be a traversal-free repository-relative path";;
esac

cd "$REPO_DIR"
[ -f "$ARTIFACT" ] || die "artifact is not a regular file: $ARTIFACT"
[ ! -L "$ARTIFACT" ] || die "artifact symlinks are not allowed"
RESOLVED="$(python -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$ARTIFACT")"
ROOT_RESOLVED="$(python -c 'import os; print(os.path.realpath("."))')"
python -c 'import os,sys; root,path=sys.argv[1:]; sys.exit(0 if os.path.commonpath([root,path]) == root else 1)' "$ROOT_RESOLVED" "$RESOLVED" \
  || die "artifact resolves outside repository"
SIZE=0
ACTUAL_SHA=""
# Size and hash are computed from a private snapshot (see below), so the bytes
# Codex reviews are exactly the bytes whose hash was verified (atomic, no
# TOCTOU between hash check and prompt ingestion).

RUN_ID="$(python -c 'import uuid; print(uuid.uuid4())')"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
TMP_DIR="$(mktemp -d)"
# Register cleanup and the EXIT trap IMMEDIATELY after mktemp -d, on the ORIGINAL
# (MSYS) path, BEFORE any path conversion or snapshot copy. This guarantees that
# a failure on ANY later line (cygpath, byte-cap, hash, claim, post) can never
# leave the temp directory behind (Codex round-3 P1).
cleanup(){ rm -rf "$TMP_DIR"; }
on_exit(){
  local rc=$?
  if [ $rc -ne 0 ] && [ "${CLAIMED:-0}" -eq 1 ] && [ "${TERMINAL:-0}" -eq 0 ]; then
    log "terminal failure after claim; moving issue to Blocked"
    set_state "$OPT_BLOCKED" "Blocked" || log "ERROR: Blocked transition/read-back failed"
  fi
  cleanup
}
trap on_exit EXIT
# Native Windows python cannot open MSYS /tmp or /c/... paths -> derive a
# separate Windows path (kept distinct from the original $TMP_DIR used for bash
# commands and cleanup). Only paths handed to native python use TMP_DIR_WIN.
TMP_DIR_WIN="$TMP_DIR"
if command -v cygpath >/dev/null 2>&1 && [[ "$TMP_DIR_WIN" != [A-Za-z]:* ]]; then
  TMP_DIR_WIN="$(cygpath -w "$TMP_DIR_WIN" 2>/dev/null || printf '%s' "$TMP_DIR_WIN")"
fi
# Private snapshot: copy the artifact once, then derive size, hash and the
# prompt body from this same snapshot so verification and ingestion are atomic.
# This closes the TOCTOU the reviewer flagged: the bytes Codex sees are exactly
# the bytes whose SHA-256 was checked.
SNAPSHOT="$TMP_DIR/artifact.snapshot"
cp "$ARTIFACT" "$SNAPSHOT"
SIZE="$(wc -c < "$SNAPSHOT" | tr -d ' ')"
[ "$SIZE" -le "$MAX_BYTES" ] || die "artifact exceeds byte cap ($SIZE > $MAX_BYTES)"
ACTUAL_SHA="$(sha256sum < "$SNAPSHOT" | cut -d' ' -f1)"
ACTUAL_SHA="${ACTUAL_SHA,,}"
[ "$ACTUAL_SHA" = "${EXPECTED_SHA,,}" ] || die "artifact hash mismatch: expected $EXPECTED_SHA actual $ACTUAL_SHA"
OUT_DIR="$REPO_DIR/.hermes/codex/artifact-reviews/$RUN_ID"
mkdir -p "$OUT_DIR"

project_state(){
  [ -n "$NO_GITHUB" ] && { printf 'OPEN\tTESTITEM\t%s\n' "${CODEX_ARTIFACT_TEST_STATE:-Ready}"; return; }
  gh api graphql -f query="
query {
  repository(owner: \"${REPO%%/*}\", name: \"${REPO##*/}\") {
    issue(number: $ISSUE) { state projectItems(first: 20) { nodes {
      id project { number }
      fieldValueByName(name: \"Workflow Status\") {
        ... on ProjectV2ItemFieldSingleSelectValue { name }
      }
    } } }
  }
}" --jq '.data.repository.issue as $i | $i.projectItems.nodes[] | select(.project.number==4) | [$i.state,id,.fieldValueByName.name] | @tsv'
}

set_state(){
  local option="$1" expected="$2" row item got
  [ -n "$NO_GITHUB" ] && { CODEX_ARTIFACT_TEST_STATE="$expected"; export CODEX_ARTIFACT_TEST_STATE; return 0; }
  row="$(project_state)" || return 1
  item="$(printf '%s' "$row" | cut -f2)"
  [ -n "$item" ] || return 1
  gh project item-edit --id "$item" --project-id "$PROJECT_ID" --field-id "$WF_FIELD" --single-select-option-id "$option" >/dev/null || return 1
  got="$(project_state | cut -f3)"
  [ "$got" = "$expected" ]
}

ROW="$(project_state)" || die "cannot read issue/Project 4 state"
[ "$(printf '%s' "$ROW" | cut -f1)" = "OPEN" ] || die "issue is not OPEN"
[ "$(printf '%s' "$ROW" | cut -f3)" = "Ready" ] || die "issue workflow is not Ready"
set_state "$OPT_INPROGRESS" "In progress" || die "claim transition/read-back failed"
CLAIMED=1

PROMPT="$TMP_DIR/prompt.md"
cat > "$PROMPT" <<EOF
You are an independent, read-only reviewer. Review only the artifact embedded below.
Use no tools, open no files, run no commands and fetch nothing externally.

Issue: $REPO#$ISSUE
Artifact: $ARTIFACT
Verified SHA-256: $ACTUAL_SHA

Return exactly:
VERDICT: GODKÄND | KRÄVER ÄNDRINGAR | INGESTION MISSLYCKADES
FINDINGS: only actionable P0/P1/P2 findings with evidence, impact and smallest correction.
KOSTNAD: measured amount or unknown; never fabricate zero.

--- ARTIFACT START ---
$(cat "$SNAPSHOT")
--- ARTIFACT END ---
EOF

LAST="$OUT_DIR/last_message.md"
STDOUT="$OUT_DIR/stdout.jsonl"
STDERR="$OUT_DIR/stderr.log"
if [ -n "${CODEX_ARTIFACT_TEST_RESULT:-}" ] && [ -n "$NO_GITHUB" ]; then
  printf '%s\n' "$CODEX_ARTIFACT_TEST_RESULT" > "$LAST"
else
  [ -f "$RUNNER" ] || die "Codex runner not found: $RUNNER"
  if [ -n "${CODEX_CLI_PATH:-}" ]; then CODEX="$CODEX_CLI_PATH";
  elif command -v codex >/dev/null 2>&1; then CODEX="$(command -v codex)";
  else die "Codex CLI not found"; fi
  RUNNER_WIN="$(cygpath -w "$RUNNER" 2>/dev/null || printf '%s' "$RUNNER")"
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$RUNNER_WIN" \
    -CodexPath "$CODEX" -PromptFile "$(cygpath -w "$PROMPT")" \
    -LastMessageOut "$(cygpath -w "$LAST")" -StdoutJson "$(cygpath -w "$STDOUT")" \
    -StderrLog "$(cygpath -w "$STDERR")" -MaxSec 540
fi

[ -f "$LAST" ] || die "review result missing"
VERDICT="$(grep -oE 'VERDICT: (GODKÄND|KRÄVER ÄNDRINGAR|INGESTION MISSLYCKADES)' "$LAST" | head -1 | sed 's/VERDICT: //' || true)"
case "$VERDICT" in GODKÄND|"KRÄVER ÄNDRINGAR") :;; *) die "invalid or failed review verdict";; esac

FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
ENVELOPE="$TMP_DIR_WIN/envelope.json"
python - "$ENVELOPE" "$REPO#$ISSUE" "$RUN_ID" "$STARTED_AT" "$FINISHED_AT" "$ARTIFACT" "$ACTUAL_SHA" "$SIZE" "$VERDICT" <<'PY'
import json,sys
out,issue,run_id,started,finished,ref,sha,size,verdict=sys.argv[1:]
data={"schema_version":"codex-artifact-review/v1","issue_id":issue,"run_id":run_id,
"status":"succeeded","runtime":"codex-review-runner.ps1","worker_role":"codex-reviewer",
"started_at":started,"finished_at":finished,"model":"OpenAI/Codex","usage":{},
"cost":{"confidence":"unknown"},"artifacts":[{"ref":ref,"hash":sha,"size":int(size)}],
"evidence":["artifact_sha256="+sha],"review":{"verdict":verdict}}
with open(out,"w",encoding="utf-8",newline="\n") as f: json.dump(data,f,ensure_ascii=False,sort_keys=True,separators=(",",":"))
PY
ENVELOPE_SHA="$(sha256sum < "$ENVELOPE" | cut -d' ' -f1)"

if [ -z "$NO_GITHUB" ]; then
  BODY="$TMP_DIR_WIN/comment.md"
  { printf '<!-- codex-artifact-review-envelope -->\nArtifact review `%s`\n\nEnvelope SHA-256: `%s`\n\n```json\n' "$RUN_ID" "$ENVELOPE_SHA"; cat "$ENVELOPE"; printf '\n```\n'; } > "$BODY"
  PAYLOAD="$TMP_DIR_WIN/payload.json"
  python -c 'import json,sys; print(json.dumps({"body":open(sys.argv[1],encoding="utf-8").read()},ensure_ascii=False))' "$BODY" > "$PAYLOAD"
  RESPONSE="$(gh api --method POST "repos/$REPO/issues/$ISSUE/comments" --input "$PAYLOAD")" || die "GitHub evidence post failed"
  COMMENT_ID="$(printf '%s' "$RESPONSE" | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
  [[ "$COMMENT_ID" =~ ^[0-9]+$ ]] || die "GitHub comment id invalid"
  gh api "repos/$REPO/issues/comments/$COMMENT_ID" --jq .body > "$TMP_DIR_WIN/readback.md" || die "GitHub evidence read-back failed"
  python - "$TMP_DIR_WIN/readback.md" "$ENVELOPE_SHA" <<'PY'
import hashlib,re,sys
text=open(sys.argv[1],encoding="utf-8").read()
m=re.search(r"```json\n(.*?)\n```",text,re.S)
if not m or hashlib.sha256(m.group(1).encode()).hexdigest()!=sys.argv[2]: raise SystemExit(1)
PY
fi

set_state "$OPT_REVIEW" "Review" || die "Review transition/read-back failed"
TERMINAL=1
printf 'ARTIFACT_REVIEW_DONE issue=%s#%s run_id=%s verdict=%s artifact_sha256=%s envelope_sha256=%s\n' \
  "$REPO" "$ISSUE" "$RUN_ID" "$VERDICT" "$ACTUAL_SHA" "$ENVELOPE_SHA"
