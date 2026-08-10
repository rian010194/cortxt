#!/usr/bin/env bash
# codex-roundtrip.sh — Hermes -> Codex -> Hermes round-trip orchestrator (ROUNDTRIP-001, #82)
#
# Closes the ingestion gap (operator no longer copy-pastes between Hermes and
# Codex). Reads an approved-ready GitHub issue + a draft-PR (commit SHA + base),
# automatically invokes the merged codex-review-adapter.sh (PR #81) with the
# exact commit SHA and correct base, reads the machine envelope + Codex verdict
# back, registers review evidence in GitHub (ref + hash + verdict, never raw
# prompt/secrets/confidential content), and on KRÄVER ÄNDRINGAR triggers a
# scoped rework dispatch to the implementation worker followed by a NEW
# independent Codex review — bounded to a hard rework-round ceiling, then
# blocked + operator escalation.
#
# Contract:   docs/architecture/dispatch-contract.md
# Envelope:   contracts/result-envelope.schema.json
# Adapter:    harness/scripts/codex-review-adapter.sh (merged via PR #81)
# Verifier:   harness/scripts/codex-roundtrip-verify.py (deterministic, no model)
# Runtime decision (#82): Hermes builder profile = TEMPORARY implementation
#   runtime for this pilot. Pi track (#65/#66/#72) is NOT claimed finished.
#
# Hard rules (fail-closed, from #82 spec):
#   1. Commit SHA must be exactly 40 lowercase hex; base must be non-empty.
#   2. Issue must be OPEN and workflow Ready (dispatch contract) before review.
#   3. Review adapter invoked EXACTLY once per round; no silent model/provider
#      fallback; NO automatic retry on HTTP 402/404/429.
#   4. Output cap: max 12,000 output tokens per model run (validated against
#      the envelope usage when present); exceed -> blocked/failed.
#   5. Envelope status derived ONLY from runner exit code + whitelisted verdict
#      (same contract as codex-review-verify.py). Never fabricate verdict/usage.
#   6. A worker NEVER approves its own work; Hermes NEVER substitutes its own
#      judgment for the Codex verdict. Verdict is a capability result, not
#      approval -> merge/Done/deploy stays operator-only.
#   7. Fail-closed on: timeout, broken envelope, ingestion failure, model error,
#      402/404/429, unknown status -> exit != 0, blocked/failed, no retry.
#   8. Evidence posted to GitHub as ref+hash+verdict+commit only — NO raw
#      prompt, NO secrets, NO confidential artifacts.
#
# Usage:
#   ./codex-roundtrip.sh -R rian010194/ai-workspace-control-plane \
#       -i 82 -c <40hex-sha> -b <base-rev> [--pr <draft-pr-num>] \
#       [--max-rework 2] [--rework-dispatch <script>] [--dry-run]
#
# Output: prints the final round-trip JSON result + posts GitHub evidence when a
# real run (not --dry-run). Exit 0 only on a clean GODKÄND stop (or dry-run
# simulation); exit non-zero on fail-closed / blocked / max-rework.
set -euo pipefail

REPO="rian010194/ai-workspace-control-plane"
MAX_REWORK=2
PR_NUM=""
REWORK_DISPATCH=""
DRYRUN=""
ISSUE=""
SHA=""
BASE=""
REWORK_BRANCH=""   # the draft-PR head branch; set from -b/PR head, NOT the diff base
REWORK_BASE_BRANCH=""  # expected PR base BRANCH name (Codex-item1); compared vs PR baseRefName
BUILDER_PUSH_BRANCH="" # PR's verified headRefName; the ONLY branch the builder may push to (Codex-item3)
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
# Adapter path overrideable for deterministic NO-MODEL verification (a stub that
# emits the same envelope contract without calling a model). Default: merged adapter.
ADAPTER="${CODEX_ROUNDTRIP_ADAPTER:-$SELF_DIR/codex-review-adapter.sh}"
# Operator #82/AC6 (2026-08-10): Codex reviewer runs on the operator's Codex subscription, so
# there is NO hard 12k-output-token cap for the adapter. Runtime terms instead:
#   - PID-bound max 540 s per call (enforced by the merged adapter's MAX_RUNTIME);
#   - max 3 Codex calls per round-trip (MAX_ADAPTER_CALLS below);
#   - no auto-retry, no reviewer/provider fallback;
#   - fail-closed on timeout / transport / invalid envelope / ingestion failure;
#   - usage reported when present; missing usage = model_cost_status unknown (never fabricated,
#     and does NOT block a valid subscription run).
MAX_RUNTIME=540   # operator-AC6: PID-bound max runtime per Codex call
# Deterministic max size of the review artifact the orchestrator ingests (memory/ingestion safety).
MAX_ARTIFACT_BYTES="${CODEX_ROUNDTRIP_MAX_ARTIFACT_BYTES:-200000}"
WF_FIELD="PVTSSF_lAHOBcHJy84BfFfWzhZa88A"
PROJECT_ID="PVT_kwHOBcHJy84BfFfW"
OPT_INPROGRESS="89a2da8a"; OPT_REVIEW="4bfdd926"; OPT_BLOCKED="20948c2f"
ENV_SCHEMA="$SELF_DIR/../../contracts/result-envelope.schema.json"

log(){ echo "[roundtrip] $*" >&2; }
die(){ log "ABORT: $*" >&2; exit 1; }

# --- arg parsing ---
while [ $# -gt 0 ]; do
  case "$1" in
    -R|--repo)        REPO="${2:-}"; shift 2;;
    -i|--issue)       ISSUE="${2:-}"; shift 2;;
    -c|--commit)      SHA="${2:-}"; shift 2;;
    -b|--base)        BASE="${2:-}"; shift 2;;
    --pr)             PR_NUM="${2:-}"; shift 2;;
    --branch)         REWORK_BRANCH="${2:-}"; shift 2;;
    --base-branch)    REWORK_BASE_BRANCH="${2:-}"; shift 2;;
    --max-rework)     MAX_REWORK="${2:-}"; shift 2;;
    --rework-dispatch) REWORK_DISPATCH="${2:-}"; shift 2;;
    --dry-run)        DRYRUN=1; shift;;
    *) die "unknown arg: $1";;
  esac
done

[ -n "$ISSUE" ] || die "missing -i <issue>"
[ -n "$SHA" ]   || die "missing -c <commit-sha>"
[ -n "$BASE" ]  || die "missing -b <base-rev>"
[ -f "$ADAPTER" ] || die "adapter not found: $ADAPTER (must run on integration-branch tree with merged PR #81)"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "bad commit sha: $SHA (exactly 40 lowercase hex required)"
# #82/Codex-item1: the diff BASE SHA fed to the Codex adapter is distinct from the PR base
# BRANCH name; captured AFTER arg parsing so -b is authoritative.
DIFF_BASE_SHA="$BASE"

# #82/#9: compute the Codex-call ceiling AFTER arg parsing so --max-rework is honored;
# validate it (>=1, integer). ceiling = 1 initial + MAX_REWORK reworks.
MAX_REWORK="${MAX_REWORK:-2}"
[[ "$MAX_REWORK" =~ ^[0-9]+$ ]] && [ "$MAX_REWORK" -ge 1 ] || die "bad --max-rework '$MAX_REWORK' (must be integer >= 1)"
MAX_ADAPTER_CALLS=$((1 + MAX_REWORK))
log "rework ceiling: MAX_REWORK=$MAX_REWORK MAX_ADAPTER_CALLS=$MAX_ADAPTER_CALLS"

# --- ensure git state: the reviewed commit must be reachable locally ---
git cat-file -e "$SHA" 2>/dev/null || die "commit $SHA not reachable locally — fetch first"
git cat-file -e "$BASE" 2>/dev/null || die "base $BASE not reachable locally — fetch first"

# --- pull latest issue + PR metadata from GitHub (source of truth) ---
NO_GITHUB="${CODEX_ROUNDTRIP_NO_GITHUB:-}"
if [ -n "$NO_GITHUB" ]; then
  log "NO_GITHUB mode (deterministic verification): gh reads/writes stubbed; issue assumed OPEN+Ready"
elif gh auth status >/dev/null 2>&1; then
  ISSUE_STATE="$(gh issue view "$ISSUE" -R "$REPO" --json state -q .state 2>/dev/null)" \
    || die "cannot read issue $ISSUE"
  [ "$ISSUE_STATE" = "OPEN" ] || die "issue $ISSUE is $ISSUE_STATE, not OPEN -> fail-closed"
  # #82/#4 + #1: issue must be workflow Ready (GraphQL read-back), not merely OPEN.
  ISSUE_WF="$(gh api graphql -f query="
query {
  repository(owner: \"${REPO%%/*}\", name: \"${REPO##*/}\") {
    issue(number: $ISSUE) { projectItems(first: 20) { nodes {
      project { number }
      fieldValueByName(name: \"Workflow Status\") {
        ... on ProjectV2ItemFieldSingleSelectValue { name }
      }
    } } }
  }
}" --jq '.data.repository.issue.projectItems.nodes[] | select(.project.number==4) | .fieldValueByName.name' 2>/dev/null | head -1)" \
    || true
  log "issue #$ISSUE workflow status = '${ISSUE_WF:-<not-on-project-4>}'"
  # #82/#7: missing Project-4 item OR missing Workflow Status must fail-closed; Ready explicit.
  if [ -z "$ISSUE_WF" ]; then
    die "issue #$ISSUE has no Workflow Status on Project 4 (missing item/status) -> fail-closed"
  fi
  [ "$ISSUE_WF" = "Ready" ] || die "issue #$ISSUE workflow is '$ISSUE_WF', not 'Ready' -> fail-closed before dispatch"
else
  die "gh not authenticated (and CODEX_ROUNDTRIP_NO_GITHUB not set)"
fi

# #82/#5: when a PR is supplied, it must be OPEN + draft, with exact head SHA + correct base.
if [ -n "$PR_NUM" ] && [ -z "$NO_GITHUB" ]; then
  PR_JSON="$(gh pr view "$PR_NUM" -R "$REPO" --json state,isDraft,headRefOid,baseRefName,headRefName 2>/dev/null)" \
    || die "cannot read PR $PR_NUM"
  PR_STATE="$(echo "$PR_JSON" | python -c "import sys,json;print(json.load(sys.stdin)['state'])")"
  PR_HEAD="$(echo "$PR_JSON" | python -c "import sys,json;print(json.load(sys.stdin)['headRefOid'])")"
  PR_BASE_BRANCH="$(echo "$PR_JSON" | python -c "import sys,json;print(json.load(sys.stdin)['baseRefName'])")"   # branch NAME
  PR_HEAD_BRANCH="$(echo "$PR_JSON" | python -c "import sys,json;print(json.load(sys.stdin)['headRefName'])")"
  # #82/Codex-item1: the PR base BRANCH NAME is compared against the expected branch, and MUST
  # NOT be conflated with the diff base SHA (`DIFF_BASE_SHA` is what the adapter is fed).
  REWORK_BRANCH="${REWORK_BRANCH:-$PR_HEAD_BRANCH}"
  # Codex-item2: when --pr is used, the expected base branch MUST be supplied (flag or trusted
  # config) — the baseRefName check may never be silently skipped.
  REWORK_BASE_BRANCH="${REWORK_BASE_BRANCH:-${CODEX_ROUNDTRIP_BASE_BRANCH:-}}"
  [ -n "$REWORK_BASE_BRANCH" ] || die "--pr requires --base-branch (or trusted CODEX_ROUNDTRIP_BASE_BRANCH); baseRefName check cannot be skipped -> fail-closed"
  [ "$PR_BASE_BRANCH" = "$REWORK_BASE_BRANCH" ] || die "PR $PR_NUM base branch ($PR_BASE_BRANCH) != expected ($REWORK_BASE_BRANCH) -> fail-closed"
  # Codex-item3: the PR's VERIFIED headRefName is the ONLY builder push target; the builder must
  # never infer the push branch from an arbitrary current checkout.
  BUILDER_PUSH_BRANCH="$PR_HEAD_BRANCH"
  PR_DRAFT_RAW="$(echo "$PR_JSON" | python -c "import sys,json;print(json.load(sys.stdin)['isDraft'])")"
  # json 'true'/'false' -> python True/False -> normalize to lowercase for bash compare
  PR_DRAFT="$(printf '%s' "$PR_DRAFT_RAW" | tr '[:upper:]' '[:lower:]')"
  # fail-closed: OPEN + draft + exact head SHA + base == integration base.
  [ "$PR_STATE" = "OPEN" ] || die "PR $PR_NUM state is $PR_STATE, not OPEN -> fail-closed"
  [ "$PR_DRAFT" = "true" ] || die "PR $PR_NUM is not a draft -> fail-closed (review targets drafts only)"
  [ "$PR_HEAD" = "$SHA" ] || die "PR $PR_NUM head ($PR_HEAD) != requested commit ($SHA) -> fail-closed"
  log "PR #$PR_NUM verified: OPEN, draft, head=$PR_HEAD base_branch=${PR_BASE_BRANCH:-n/a}"
fi
# Codex-item3: when no PR is used, the builder push branch falls back to the work branch
# (REWORK_BRANCH or current branch). When a PR IS used, BUILDER_PUSH_BRANCH is the verified
# headRefName set above — never inferred from an arbitrary checkout.
REWORK_BRANCH="${REWORK_BRANCH:-$(git branch --show-current 2>/dev/null || true)}"
BUILDER_PUSH_BRANCH="${BUILDER_PUSH_BRANCH:-$REWORK_BRANCH}"

# --- ROUND function: run exactly ONE Codex review via the merged adapter ---
# Always emits a uniform JSON: {status, verdict, reason?, cost_conf, output_tokens?}
run_one_review(){
  local sha="$1" base="$2" round="$3"
  log "--- round $round review: adapter $ADAPTER <$sha> --base $base ---"
  local out env_start env_end preview parsed rc
  set +e
  out="$( "$ADAPTER" "$sha" --base "$base" 2>/tmp/codex-roundtrip-adapter.err )"
  rc=$?
  set -e

  if [ $rc -eq 124 ]; then
    echo "{\"round\":$round,\"status\":\"timed_out\",\"verdict\":\"none\",\"reason\":\"adapter timeout\",\"cost_conf\":\"unknown\",\"output_tokens\":null}"
    return 0
  fi
  if [ $rc -ne 0 ]; then
    echo "{\"round\":$round,\"status\":\"failed\",\"verdict\":\"unknown\",\"reason\":\"adapter nonzero rc=$rc\",\"cost_conf\":\"unknown\",\"output_tokens\":null}"
    return 0
  fi

  # extract envelope JSON between REVIEW_ENVELOPE_JSON / CODEX_REVIEW_DONE markers
  # (guard: grep returns 1 on no-match which must NOT abort under set -euo pipefail)
  env_start="$(printf '%s\n' "$out" | grep -n '^REVIEW_ENVELOPE_JSON$' | head -1 | cut -d: -f1 || true)"
  env_end="$(printf '%s\n' "$out" | grep -n '^CODEX_REVIEW_DONE' | head -1 | cut -d: -f1 || true)"
  if [ -z "$env_start" ] || [ -z "$env_end" ] || [ "$env_end" -le "$env_start" ]; then
    echo "{\"round\":$round,\"status\":\"failed\",\"verdict\":\"unknown\",\"reason\":\"broken envelope (no JSON markers)\",\"cost_conf\":\"unknown\",\"output_tokens\":null}"
    return 0
  fi
  preview="$(printf '%s\n' "$out" | sed -n "$((env_start+1)),$((env_end-1))p")"

  # Operator-AC6: deterministic max review-artifact size at ingestion (memory/ingestion safety).
  # If the artifact exceeds the cap, fail-closed (ingestion failure) — do not ingest it.
  if [ -n "${preview:-}" ] && [ "${#preview}" -gt "$MAX_ARTIFACT_BYTES" ]; then
    echo "{\"round\":$round,\"status\":\"failed\",\"verdict\":\"unknown\",\"reason\":\"review artifact exceeds deterministic max ${MAX_ARTIFACT_BYTES} bytes\",\"cost_conf\":\"unknown\",\"output_tokens\":null}"
    return 0
  fi

  # Authoritative verdict: from the adapter's own CODEX_REVIEW_DONE line (which comes
  # from last_message.md, freshly produced by the runner). GODKÄND / KRÄVER ÄNDRINGAR
  # are success capability verdicts; INGESTION MISSLYCKADES is NOT success.
  # NOTE: multi-word verdicts ("KRÄVER ÄNDRINGAR") must be captured whole — take
  # everything between 'verdict=' and the trailing ' cost=' token, not just [^ ]*.
  local verdict rawv reason
  rawv="$(printf '%s\n' "$out" | grep -oE 'CODEX_REVIEW_DONE .*verdict=.*' | head -1 | sed 's/.*verdict=//' | sed 's/ cost=.*//' | tr -d '\r')"
  # WHITELIST parse: only the exact known verdicts are accepted; anything else -> unknown.
  case "$rawv" in
    GODKÄND)                      verdict="GODKÄND"; reason="";;
    "KRÄVER ÄNDRINGAR")           verdict="KRÄVER ÄNDRINGAR"; reason="";;
    INGESTION\ MISSLYCKADES)      verdict="INGESTION MISSLYCKADES"; reason="ingestion failed";;
    *)                            verdict="unknown"; reason="unrecognized/absent verdict ($rawv)";;
  esac

  # Machine-validate the envelope: REAL schema validation against
  # contracts/result-envelope.schema.json (jsonschema), not just required keys (#82/#7).
  # Native Windows python cannot open MSYS /c/... paths -> convert via cygpath -w.
  local schema_error schema_win
  schema_win="$(cygpath -w "$ENV_SCHEMA" 2>/dev/null || echo "$ENV_SCHEMA")"
  schema_error="$(printf '%s' "$preview" | SCHEMA_FILE="$schema_win" python -c "
import os,sys,json
d=json.load(sys.stdin)
schema_file=os.environ.get('SCHEMA_FILE','')
try:
    import jsonschema
except ImportError:
    jsonschema=None
try:
    schema=json.load(open(schema_file,encoding='utf-8'))
except Exception as e:
    print('SCHEMA_LOAD_ERR: '+str(e)); sys.exit(0)
if jsonschema:
    try:
        jsonschema.validate(d, schema)
        print('')
    except Exception as e:
        print('SCHEMA_INVALID: '+str(e))
else:
    # fallback structural check (jsonschema unavailable): required keys present
    req=schema.get('required',[])
    missing=[k for k in req if k not in d]
    print('NO_JSONSCHEMA missing=%s' % (','.join(missing) if missing else ''))
")"
  if [ -n "$schema_error" ]; then
    echo "{\"round\":$round,\"status\":\"failed\",\"verdict\":\"unknown\",\"reason\":\"invalid envelope: $schema_error\",\"cost_conf\":\"unknown\",\"output_tokens\":null,\"artifacts\":[]}"
    return 0
  fi

  # Preserve artifacts ref/hash/size from the envelope through the result (#82/#8).
  local artifacts_json
  artifacts_json="$(printf '%s' "$preview" | python -c "
import sys,json
d=json.load(sys.stdin)
print(json.dumps([{'ref':a.get('ref'),'hash':a.get('hash'),'size':a.get('size')} for a in d.get('artifacts',[]) if isinstance(a,dict)]))
")"

  # Usage (operator #82/AC6): report output_tokens WHEN the envelope provides it; missing usage
  # is model_cost_status: unknown (never fabricated) and does NOT block a valid subscription run.
  local out_tokens
  out_tokens="$(printf '%s' "$preview" | python -c "
import sys,json
d=json.load(sys.stdin)
u=d.get('usage',{}) or {}
v=u.get('output_tokens')
print(v if isinstance(v,int) else '')
")"
  out_tokens="${out_tokens:-}"

  # Envelope status must itself be succeeded for a valid review result.
  local env_status cost_conf
  env_status="$(printf '%s' "$preview" | python -c "import sys,json;print(json.load(sys.stdin).get('status',''))")"
  cost_conf="$(printf '%s' "$preview" | python -c "import sys,json;print(json.dumps(json.load(sys.stdin).get('cost',{}).get('confidence','unknown')))")"
  if [ "$env_status" != "succeeded" ]; then
    echo "{\"round\":$round,\"status\":\"$env_status\",\"verdict\":\"$verdict\",\"reason\":\"envelope status $env_status (not succeeded)\",\"cost_conf\":$cost_conf,\"output_tokens\":${out_tokens:-null},\"artifacts\":$artifacts_json}"
    return 0
  fi

  echo "{\"round\":$round,\"status\":\"succeeded\",\"verdict\":\"$verdict\",\"reason\":\"\",\"cost_conf\":$cost_conf,\"output_tokens\":${out_tokens:-null},\"artifacts\":$artifacts_json}"
}

# --- GitHub project item id lookup (content number = issue) ---
# Returns the item id, or empty. Fail-closed: get_item_id itself must succeed
# when NOT in NO_GITHUB mode (a gh failure here aborts, not swallowed).
get_item_id(){
  gh project item-list 4 --owner "${REPO%%/*}" --format json --limit 100 2>/dev/null \
    | python -c "
import sys,json
d=json.load(sys.stdin)
for i in d.get('items',[]):
    if str(i.get('content',{}).get('number'))=='$ISSUE':
        print(i.get('id','')); break
" || { log "get_item_id failed (gh)"; return 1; }
}

# Fail-closed project transitions: each sets the workflow status and VERIFIES it
# via GraphQL read-back. On mismatch/non-zero -> return 1 (caller must abort).
set_item_status(){
  local want="$1"
  local id want_opt
  id="$(get_item_id)" || return 1
  [ -n "$id" ] || { log "set_item_status: item id not found for #$ISSUE"; return 1; }
  case "$want" in
    blocked)     want_opt="$OPT_BLOCKED";;
    review)      want_opt="$OPT_REVIEW";;
    in_progress) want_opt="$OPT_INPROGRESS";;
    *) log "set_item_status: unknown status $want"; return 1;;
  esac
  gh project item-edit --id "$id" --project-id "$PROJECT_ID" \
    --field-id "$WF_FIELD" --single-select-option-id "$want_opt" >/dev/null 2>&1 || return 1
  # verify via GraphQL
  local got
  got="$(gh api graphql -f query="
query { node(id: \"$id\") {
  ... on ProjectV2Item {
    fieldValueByName(name: \"Workflow Status\") {
      ... on ProjectV2ItemFieldSingleSelectValue { name }
    }
  }
}}" --jq '.data.node.fieldValueByName.name' 2>/dev/null || true)"
  # map option back to desired label
  local want_label
  case "$want" in
    blocked) want_label="Blocked";;
    review)  want_label="Review";;
    in_progress) want_label="In progress";;
  esac
  if [ "$got" != "$want_label" ]; then
    log "set_item_status read-back mismatch: want=$want_label got=$got"
    return 1
  fi
  log "project #$ISSUE workflow -> $want_label (verified)"
  return 0
}
start_item(){
  [ -n "$NO_GITHUB" ] && { log "NO_GITHUB: skip In-progress claim"; return 0; }
  set_item_status "in_progress"
}

block_item(){
  [ -n "$NO_GITHUB" ] && { log "NO_GITHUB: skip block transition"; return 0; }
  set_item_status "blocked"
}

# Codex-item3: common terminal-failure path AFTER a claim. Attempts Blocked + read-back;
# reports the transition outcome separately so no path leaves a failed run as In progress.
# Returns the run's exit code to use (blocked-transition failure is NOT silently swallowed).
fail_terminal(){
  local exitwant="$1" reason="$2"
  local tx=0
  if [ -z "$DRYRUN" ]; then
    if block_item; then
      log "terminal failure -> Blocked (read-back verified)"
    else
      log "TERMINAL TRANSITION ERROR: could not set/verify Blocked after failure (run leaves non-In-progress handling to operator)"
      tx=1
    fi
  fi
  echo "ROUNDTRIP_END $reason"
  [ $tx -eq 0 ] && exit "$exitwant" || exit 6
}

mv_review(){
  [ -n "$NO_GITHUB" ] && { log "NO_GITHUB: skip review transition"; return 0; }
  set_item_status "review"
}

# --- post review evidence to GitHub (ref + hash + size + verdict + commit; NO raw prompt/secrets) ---
# FAIL-CLOSED (#82/#6,/#8): must post AND read back the numeric comment id AND confirm the
# body contains the artifacts; any failure returns 1 so the run does not report success.
post_evidence(){
  [ -n "$NO_GITHUB" ] && { log "NO_GITHUB: skip evidence posting"; return 0; }
  local round="$1" verdict="$2" result="$3" sha="$4"
  local cost_conf out_tokens artifacts_line
  cost_conf="$(echo "$result" | python -c "import sys,json;print(json.load(sys.stdin).get('cost_conf','unknown'))")"
  # Usage reported when the envelope provides it; missing -> model_cost_status unknown (not fabricated).
  out_tokens="$(echo "$result" | python -c "
import sys,json
d=json.load(sys.stdin)
v=d.get('output_tokens')
print(v if isinstance(v,int) else 'unknown')
")"
  # Preserve artifacts ref/hash/size from the envelope through the posted evidence (#82/#8).
  artifacts_line="$(echo "$result" | python -c "
import sys,json
d=json.load(sys.stdin)
arts=d.get('artifacts',[])
print('\n'.join([('- `%s` | hash `%s` | size %s' % (a.get('ref',''), a.get('hash',''), a.get('size',''))) for a in arts]) if arts else '(none)')
")"
  local body_file
  body_file="$(mktemp)"
  cat > "$body_file" <<EOF
## Codex review evidence — ROUNDTRIP #$ISSUE, round $round

| Field | Value |
|---|---|
| Commit reviewed | \`$sha\` |
| Workflow base | \`$BASE\` |
| Codex verdict | **$verdict** |
| Run status | $([ "$verdict" = GODKÄND ] && echo 'succeeded (Review)' || echo 'failed/blocked') |
| Cost confidence | $cost_conf (honest: unknown unless measured, never 0) |
| Output usage (tokens) | $out_tokens (unknown = not reported, not fabricated) |
| PR | ${PR_NUM:-n/a} |

**Reproducible evidence (ref + hash + size only — no raw prompt, no secrets, no confidential artifacts):**
\`\`\`
$artifacts_line
\`\`\`

> Capability result, NOT approval. A worker never approves its own work; Hermes
> does not substitute its own judgment for the Codex verdict. Merge / Done /
> deploy remain operator-only.
EOF
  local body_win post_json cid readback json_file
  body_win="$(cygpath -w "$body_file")"
  # #82/#3: post via gh api using the VERIFIED JSON/--input path so the BODY CONTENT
  # (not the path) is posted. Build {"body": <content>} to a temp JSON file, then --input it.
  json_file="$(mktemp)"
  set +e
  python - "$body_win" "$(cygpath -w "$json_file")" <<'PY' >/tmp/roundtrip-post.err 2>&1
import sys, json
body = open(sys.argv[1], encoding="utf-8").read()
open(sys.argv[2], "w", encoding="utf-8").write(json.dumps({"body": body}))
PY
  PY_RC=$?
  set -e
  if [ "$PY_RC" -ne 0 ]; then
    log "evidence JSON build failed: $(tail -2 /tmp/roundtrip-post.err)"; rm -f "$body_file" "$json_file"; return 1
  fi
  # perform the GH POST using the JSON payload file (verified --input path)
  json_file_win="$(cygpath -w "$json_file")"
  post_json="$(gh api "repos/$REPO/issues/$ISSUE/comments" --input "$json_file_win" 2>/tmp/roundtrip-post-id.err)"
  cid="$(printf '%s' "$post_json" | python -c "import sys,json;print(json.load(sys.stdin).get('id','') or '')")"
  rm -f "$json_file"
  if [ -z "$cid" ] || [ -z "$post_json" ]; then
    log "evidence POST failed: $(tail -2 /tmp/roundtrip-post-id.err 2>/dev/null)"
    rm -f "$body_file"; return 1
  fi
  # Read back the EXACT id and confirm body contains artifacts + marker (#82/#6,/#8).
  readback="$(gh api "repos/$REPO/issues/$ISSUE/comments" \
    --jq ".[] | select(.id==$cid) | .body" 2>/dev/null)" || true
  if [ -z "$readback" ]; then
    log "evidence read-back FAILED for comment id $cid"; rm -f "$body_file"; return 1
  fi
  # confirm the body contains the artifact hashes (not just the header marker)
  local artifact_ok=0
  if [ "$(echo "$result" | python -c "import sys,json;print(len(json.load(sys.stdin).get('artifacts',[])))")" -eq 0 ]; then
    artifact_ok=1
    log "note: no artifacts in envelope (capability still recorded)"
  elif printf '%s' "$readback" | grep -q "hash \`" ; then
    artifact_ok=1
  fi
  if printf '%s' "$readback" | grep -q "ROUNDTRIP #$ISSUE, round $round" && [ "$artifact_ok" -eq 1 ]; then
    log "evidence posted + read back verified: issue #$ISSUE comment id $cid (round $round, verdict=$verdict)"
  else
    log "evidence read-back content mismatch for comment id $cid (artifact_ok=$artifact_ok)"
    rm -f "$body_file"; return 1
  fi
  rm -f "$body_file"
  return 0
}

# --- main round-trip loop ---
# #82/#9: rework ceiling = max 3 Codex adapter CALLS total (initial review + 2 reworks).
echo "ROUNDTRIP_BEGIN repo=$REPO issue=$ISSUE commit=$SHA base=$BASE max_calls=$MAX_ADAPTER_CALLS dr=$([ -n "$DRYRUN" ] && echo yes || echo no)"
# Codex-item6: valid claim -> Ready -> In progress (fail-closed + read-back verified).
if [ -z "$DRYRUN" ]; then
  if ! start_item; then
    log "TERMINAL fail-closed: Ready->In progress claim failed"
    echo "ROUNDTRIP_END {\"status\":\"failed\",\"reason\":\"claim transition failed\"}"
    exit 5
  fi
fi
FINAL_RESULT=""
CALLS=0
while :; do
  CALLS=$((CALLS+1))
  if [ "$CALLS" -gt "$MAX_ADAPTER_CALLS" ]; then
    log "TERMINAL: adapter-call ceiling $MAX_ADAPTER_CALLS hit -> blocked + operator escalation (no self-approval)."
    fail_terminal 4 "{\"round\":$CALLS,\"status\":\"blocked\",\"verdict\":\"CEILING\"}"
  fi
  RES="$(run_one_review "$SHA" "$DIFF_BASE_SHA" "$CALLS")"
  STATUS="$(echo "$RES" | python -c "import sys,json;print(json.load(sys.stdin).get('status','failed'))")"
  VERDICT="$(echo "$RES" | python -c "import sys,json;print(json.load(sys.stdin).get('verdict','unknown'))")"

  # Fail-closed terminal statuses (no retry, no fallback) — routed via the common Blocked path.
  case "$STATUS" in
    timed_out|failed)
      log "TERMINAL fail-closed: status=$STATUS (call $CALLS). no retry, no model fallback."
      fail_terminal 3 "$RES"
      ;;
    succeeded) ;;
    blocked) # cap unverifiable -> fail-closed block
      log "TERMINAL fail-closed: status=blocked (call $CALLS). no retry, no model fallback."
      fail_terminal 3 "$RES"
      ;;
    *) # unknown status -> fail-closed
      log "TERMINAL fail-closed: unknown status=$STATUS (call $CALLS)"
      fail_terminal 3 "$RES"
      ;;
  esac

  if [ "$VERDICT" = "GODKÄND" ]; then
    log "VERDICT GODKÄND (call $CALLS) — capability result, NOT approval. merge/Done is operator-only."
    if [ -z "$DRYRUN" ]; then
      # FAIL-CLOSED (#82/#6): evidence + Review transition MUST succeed or the run is NOT success.
      if ! post_evidence "$CALLS" "$VERDICT" "$RES" "$SHA"; then
        log "TERMINAL fail-closed: evidence posting/read-back failed -> not success"
        echo "ROUNDTRIP_END $RES"
        exit 5
      fi
      if ! mv_review; then
        log "TERMINAL fail-closed: Review transition/read-back failed -> not success"
        echo "ROUNDTRIP_END $RES"
        exit 5
      fi
    fi
    echo "ROUNDTRIP_END $RES"
    exit 0
  fi

  if [ "$VERDICT" = "KRÄVER ÄNDRINGAR" ]; then
    log "VERDICT KRÄVER ÄNDRINGAR (call $CALLS) — triggering scoped rework + new independent review."
    if [ -n "$DRYRUN" ]; then
      FINAL_RESULT="$RES"
      echo "ROUNDTRIP_END $RES (dry-run: rework would dispatch via ${REWORK_DISPATCH:-<none>})"
      exit 0
    fi
    # #82/#10: post + read back the KRÄVER review evidence BEFORE dispatch (fail-closed).
    if ! post_evidence "$CALLS" "$VERDICT" "$RES" "$SHA"; then
      log "TERMINAL fail-closed: KRÄVER evidence posting/read-back failed -> not proceeding"
      echo "ROUNDTRIP_END $RES"; exit 5
    fi
    # #82/#10: use the REAL bounded Hermes Builder dispatch adapter (not an arbitrary hook).
    if [ -z "$REWORK_DISPATCH" ] || [ ! -x "$REWORK_DISPATCH" ]; then
      die "--rework-dispatch (Hermes Builder dispatch adapter) required but missing/not executable: $REWORK_DISPATCH"
    fi
    # #82/#5: capture pre-builder HEAD; post-builder must be a NEW pushed commit == PR's new remote head.
    PRE_HEAD="$(git rev-parse HEAD)"
    # #82/#1+#3: argument contract = (owner/repo#issue, round, PR-head-branch) — identical to the
    # Builder adapter; the push target is the PR's verified headRefName, never inferred.
    DISPATCH_ISSUE="${REPO}#${ISSUE}"
    [ -n "$BUILDER_PUSH_BRANCH" ] || fail_terminal 3 "{\"status\":\"blocked\",\"reason\":\"BUILDER_PUSH_BRANCH empty (PR headRefName not verified)\"}"
    BUILD_OUT="$(set +e; "$REWORK_DISPATCH" "$DISPATCH_ISSUE" "$CALLS" "$BUILDER_PUSH_BRANCH"; echo "RC=$?")"
    BUILD_RC="$(printf '%s' "$BUILD_OUT" | grep -oE 'RC=[0-9]+$' | head -1 | cut -d= -f2 || true)"
    # extract the 40-hex SHA from the BUILDER_DISPATCH_DONE ... head=<sha> line (#82/#5)
    NEW_SHA="$(printf '%s' "$BUILD_OUT" | grep -oE 'head=[0-9a-f]{40}' | head -1 | cut -d= -f2 || true)"
    if [ -z "$BUILD_RC" ] || [ "$BUILD_RC" != "0" ] || ! [[ "$NEW_SHA" =~ ^[0-9a-f]{40}$ ]]; then
      fail_terminal 3 "{\"status\":\"blocked\",\"reason\":\"builder dispatch did not deliver a pushed 40-hex PR-head\"}"
    fi
    [ "$NEW_SHA" != "$PRE_HEAD" ] || fail_terminal 3 "{\"status\":\"blocked\",\"reason\":\"builder produced no NEW commit\"}"
    # Codex-item3/4: the builder pushed to the PR's VERIFIED headRefName (BUILDER_PUSH_BRANCH).
    # After the (isolated) worktree push, verify NEW_SHA == remote branch == GitHub PR head
    # WITHOUT requiring the shared local branch to move (it stays untouched).
    if [ -z "$NO_GITHUB" ]; then
      [ -n "$BUILDER_PUSH_BRANCH" ] || fail_terminal 3 "{\"status\":\"blocked\",\"reason\":\"BUILDER_PUSH_BRANCH empty\"}"
      git fetch origin "$BUILDER_PUSH_BRANCH" 2>/dev/null || true
      remote_br="$(git rev-parse --verify "origin/$BUILDER_PUSH_BRANCH" 2>/dev/null || true)"
      pr_head_now="$(gh pr view "$PR_NUM" -R "$REPO" --json headRefOid -q .headRefOid 2>/dev/null || true)"
      if [ "$NEW_SHA" != "$remote_br" ] || [ "$remote_br" != "$pr_head_now" ]; then
        fail_terminal 3 "{\"status\":\"blocked\",\"reason\":\"new head != remote branch != PR head\"}"
      fi
      # the shared local branch must remain at PRE_HEAD (untouched by the isolated push)
      shared_local="$(git rev-parse --verify HEAD)"
      [ "$shared_local" = "$PRE_HEAD" ] || fail_terminal 3 "{\"status\":\"blocked\",\"reason\":\"shared local branch moved unexpectedly\"}"
    fi
    SHA="$NEW_SHA"
    continue
  fi

  # Ingestion failure / model error / unknown verdict -> fail-closed (no retry) via common Blocked path.
  log "TERMINAL fail-closed: verdict='$VERDICT' status=$STATUS — ingestion/model failure, no retry."
  fail_terminal 3 "$RES"
done
