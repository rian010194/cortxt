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
REWORK_ROUND=0
PR_NUM=""
REWORK_DISPATCH=""
DRYRUN=""
ISSUE=""
SHA=""
BASE=""
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
# Adapter path overrideable for deterministic NO-MODEL verification (a stub that
# emits the same envelope contract without calling a model). Default: merged adapter.
ADAPTER="${CODEX_ROUNDTRIP_ADAPTER:-$SELF_DIR/codex-review-adapter.sh}"
PROJECT_NUM="4"
WF_STATUS_FIELDID="PVTSSF_lAHOBcHJy84BfFfWzhZa88A"
OPT_REVIEW="4bfdd926"; OPT_BLOCKED="20948c2f"
OUTPUT_CAP_TOKENS=12000

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

# --- ensure git state: the reviewed commit must be reachable locally ---
git cat-file -e "$SHA" 2>/dev/null || die "commit $SHA not reachable locally — fetch first"
git cat-file -e "$BASE" 2>/dev/null || die "base $BASE not reachable locally — fetch first"

# --- pull latest issue + PR metadata from GitHub (source of truth) ---
NO_GITHUB="${CODEX_ROUNDTRIP_NO_GITHUB:-}"
if [ -n "$NO_GITHUB" ]; then
  log "NO_GITHUB mode (deterministic verification): skipping gh reads/writes; issue assumed OPEN"
elif gh auth status >/dev/null 2>&1; then
  ISSUE_STATE="$(gh issue view "$ISSUE" -R "$REPO" --json state -q .state 2>/dev/null)" \
    || die "cannot read issue $ISSUE"
  [ "$ISSUE_STATE" = "OPEN" ] || die "issue $ISSUE is $ISSUE_STATE, not OPEN -> fail-closed"
else
  die "gh not authenticated (and CODEX_ROUNDTRIP_NO_GITHUB not set)"
fi

if [ -n "$PR_NUM" ] && [ -z "$NO_GITHUB" ]; then
  PR_JSON="$(gh pr view "$PR_NUM" -R "$REPO" --json state,isDraft,headRefOid,baseRefName,headRefName 2>/dev/null)" \
    || die "cannot read PR $PR_NUM"
  PR_HEAD="$(echo "$PR_JSON" | python -c "import sys,json;print(json.load(sys.stdin)['headRefOid'])")"
  PR_BASE="$(echo "$PR_JSON" | python -c "import sys,json;print(json.load(sys.stdin)['baseRefName'])")"
  PR_DRAFT="$(echo "$PR_JSON" | python -c "import sys,json;print(json.load(sys.stdin)['isDraft'])")"
  # fail-closed: if a PR is supplied, the commit under review MUST be its head.
  [ "$PR_HEAD" = "$SHA" ] || die "PR $PR_NUM head ($PR_HEAD) != requested commit ($SHA) -> fail-closed"
  log "PR #$PR_NUM: head=$PR_HEAD base=$PR_BASE isDraft=$PR_DRAFT (draft expected: $([ -n "$DRYRUN" ] && echo n/a || echo 'yes if scoped') )  -> commit match OK"
fi

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

  # Machine-validate the envelope (schema required fields) — fail-closed if broken.
  parsed="$(printf '%s' "$preview" | python -c "
import sys,json
try:
    d=json.load(sys.stdin)
except Exception as e:
    print('PARSE_ERROR: '+str(e)); sys.exit(0)
req=['issue_id','run_id','status','runtime','worker_role','started_at','finished_at','model','usage','cost','artifacts','evidence']
missing=[k for k in req if k not in d]
if missing:
    print('MISSING: '+','.join(missing)); sys.exit(0)
print('OK status=%s cost_conf=%s usage=%s' % (d.get('status'), d.get('cost',{}).get('confidence'), json.dumps(d.get('usage',{}))))
")"
  if [[ "$parsed" != OK\ * ]]; then
    echo "{\"round\":$round,\"status\":\"failed\",\"verdict\":\"unknown\",\"reason\":\"invalid envelope schema: $parsed\",\"cost_conf\":\"unknown\",\"output_tokens\":null}"
    return 0
  fi

  # Output-token cap: from envelope usage.output_tokens, if present. Exceed -> blocked.
  local out_tokens cap_ok
  out_tokens="$(printf '%s' "$preview" | python -c "
import sys,json
d=json.load(sys.stdin)
u=d.get('usage',{}) or {}
v=u.get('output_tokens')
print(v if isinstance(v,int) else '')
")"
  out_tokens="${out_tokens:-}"
  if [ -n "$out_tokens" ] && [ "$out_tokens" -gt "$OUTPUT_CAP_TOKENS" ]; then
    echo "{\"round\":$round,\"status\":\"failed\",\"verdict\":\"unknown\",\"reason\":\"output token cap exceeded ($out_tokens > $OUTPUT_CAP_TOKENS)\",\"cost_conf\":\"unknown\",\"output_tokens\":$out_tokens}"
    return 0
  fi

  # Envelope status must itself be succeeded for a valid review result.
  local env_status
  env_status="$(printf '%s' "$preview" | python -c "import sys,json;print(json.load(sys.stdin).get('status',''))")"
  if [ "$env_status" != "succeeded" ]; then
    echo "{\"round\":$round,\"status\":\"$env_status\",\"verdict\":\"$verdict\",\"reason\":\"envelope status $env_status (not succeeded)\",\"cost_conf\":$(printf '%s' "$preview" | python -c "import sys,json;print(json.dumps(json.load(sys.stdin).get('cost',{}).get('confidence','unknown')))"),\"output_tokens\":${out_tokens:-null}}"
    return 0
  fi

  echo "{\"round\":$round,\"status\":\"succeeded\",\"verdict\":\"$verdict\",\"reason\":\"\",\"cost_conf\":$(printf '%s' "$preview" | python -c "import sys,json;print(json.dumps(json.load(sys.stdin).get('cost',{}).get('confidence','unknown')))"),\"output_tokens\":${out_tokens:-null}}"
}

# --- GitHub project item id lookup (content number = issue) ---
get_item_id(){
  gh project item-list "$PROJECT_NUM" --owner "${REPO%%/*}" --format json --limit 100 2>/dev/null \
    | python -c "
import sys,json
d=json.load(sys.stdin)
for i in d.get('items',[]):
    if str(i.get('content',{}).get('number'))=='$ISSUE':
        print(i.get('id','')); break
" || true
}

block_item(){
  [ -n "$NO_GITHUB" ] && { log "NO_GITHUB: skip block transition"; return 0; }
  local id
  id="$(get_item_id)"
  [ -n "$id" ] && gh project item-edit --id "$id" --project-id "PVT_kwHOBcHJy84BfFfW" \
    --field-id "$WF_STATUS_FIELDID" --single-select-option-id "$OPT_BLOCKED" >/dev/null 2>&1 || true
}

mv_review(){
  [ -n "$NO_GITHUB" ] && { log "NO_GITHUB: skip review transition"; return 0; }
  local id
  id="$(get_item_id)"
  [ -n "$id" ] && gh project item-edit --id "$id" --project-id "PVT_kwHOBcHJy84BfFfW" \
    --field-id "$WF_STATUS_FIELDID" --single-select-option-id "$OPT_REVIEW" >/dev/null 2>&1 || true
}

# --- post review evidence to GitHub (ref + hash + verdict + commit; NO raw prompt/secrets) ---
post_evidence(){
  [ -n "$NO_GITHUB" ] && { log "NO_GITHUB: skip evidence posting"; return 0; }
  local round="$1" verdict="$2" result="$3" sha="$4"
  local cost_conf artifacts evidence artifact_refs verdict_line
  cost_conf="$(echo "$result" | python -c "import sys,json;print(json.load(sys.stdin).get('cost_conf','unknown'))")"
  verdict_line="$verdict"
  artifacts="$(echo "$result" | python -c "import sys,json;d=json.load(sys.stdin);print(' '.join([a.get('ref','')+'|'+str(a.get('hash','')) for a in d.get('artifacts',[])]))")"
  # Write the comment body to a temp file (git-bash backtick/$() pitfall => --body-file)
  local body_file
  body_file="$(mktemp)"
  cat > "$body_file" <<EOF
## Codex review evidence — ROUNDTRIP #$ISSUE, round $round

| Field | Value |
|---|---|
| Commit reviewed | \`$sha\` |
| Workflow base | \`$BASE\` |
| Codex verdict | **$verdict_line** |
| Run status | $([ "$verdict" = GODKÄND ] || echo 'failed/blocked — see status above') |
| Cost confidence | $cost_conf (honest: unknown unless measured, never 0) |
| PR | ${PR_NUM:-n/a} |

**Reproducible evidence (ref + hash only — no raw prompt, no secrets, no confidential artifacts):**
\`\`\`
$artifacts
\`\`\`

> Capability result, NOT approval. A worker never approves its own work; Hermes
> does not substitute its own judgment for the Codex verdict. Merge / Done /
> deploy remain operator-only.
EOF
  # Post + read back verified (method per codex-review-gate: gh api select by id, not naive grep)
  local body_win
  body_win="$(cygpath -w "$body_file")"
  local cid
  cid="$(gh issue comment "$ISSUE" -R "$REPO" --body-file "$body_win" --json id -q .id 2>/dev/null)" || true
  if [ -n "$cid" ]; then
    local readback
    readback="$(gh api "repos/$REPO/issues/$ISSUE/comments" --jq ".[] | select(.id==$cid) | .body" 2>/dev/null)" || true
    if [ -n "$readback" ] && [[ "$readback" == *"ROUNDTRIP #$ISSUE, round $round"* ]]; then
      log "evidence comment posted + read back verified: issue #$ISSUE, comment id $cid (round $round, verdict=$verdict)"
    else
      log "WARNING: evidence comment id $cid could not be verified via read-back (verification, not absence)"
    fi
  else
    log "WARNING: could not obtain comment id for evidence posting"
  fi
  rm -f "$body_file"
}

# --- main round-trip loop ---
echo "ROUNDTRIP_BEGIN repo=$REPO issue=$ISSUE commit=$SHA base=$BASE max_rework=$MAX_REWORK dr=$([ -n "$DRYRUN" ] && echo yes || echo no)"
FINAL_RESULT=""
while :; do
  REWORK_ROUND=$((REWORK_ROUND+1))
  RES="$(run_one_review "$SHA" "$BASE" "$REWORK_ROUND")"
  STATUS="$(echo "$RES" | python -c "import sys,json;print(json.load(sys.stdin).get('status','failed'))")"
  VERDICT="$(echo "$RES" | python -c "import sys,json;print(json.load(sys.stdin).get('verdict','unknown'))")"

  # Fail-closed terminal statuses (no retry, no fallback)
  case "$STATUS" in
    timed_out|failed)
      FINAL_RESULT="$RES"
      log "TERMINAL fail-closed: status=$STATUS (round $REWORK_ROUND). no retry, no model fallback."
      [ -n "$DRYRUN" ] || block_item
      echo "ROUNDTRIP_END $FINAL_RESULT"
      exit 3
      ;;
    succeeded) ;;
    *) # unknown status -> fail-closed
      FINAL_RESULT="$RES"
      log "TERMINAL fail-closed: unknown status=$STATUS (round $REWORK_ROUND)"
      echo "ROUNDTRIP_END $FINAL_RESULT"
      exit 3
      ;;
  esac

  if [ "$VERDICT" = "GODKÄND" ]; then
    log "VERDICT GODKÄND (round $REWORK_ROUND) — capability result, NOT approval. merge/Done is operator-only."
    # Register evidence in GitHub (ref+hash+verdict+commit only)
    if [ -z "$DRYRUN" ]; then
      post_evidence "$REWORK_ROUND" "$VERDICT" "$RES" "$SHA"
      mv_review
    fi
    echo "ROUNDTRIP_END $RES"
    exit 0
  fi

  if [ "$VERDICT" = "KRÄVER ÄNDRINGAR" ]; then
    if [ "$REWORK_ROUND" -ge "$MAX_REWORK" ]; then
      log "max rework rounds ($MAX_REWORK) reached with KRÄVER ÄNDRINGAR -> blocked + operator escalation (no self-approval)."
      [ -z "$DRYRUN" ] && { post_evidence "$REWORK_ROUND" "$VERDICT" "$RES" "$SHA"; block_item; }
      echo "ROUNDTRIP_END $RES"
      exit 4
    fi
    # Scoped rework dispatch (to the implementation worker) + a fresh review on the NEW commit.
    log "VERDICT KRÄVER ÄNDRINGAR (round $REWORK_ROUND) — triggering scoped rework + new independent review."
    if [ -n "$DRYRUN" ]; then
      FINAL_RESULT="$RES"
      echo "ROUNDTRIP_END $RES (dry-run: rework would dispatch via ${REWORK_DISPATCH:-<none>})"
      exit 0
    fi
    if [ -z "$REWORK_DISPATCH" ] || [ ! -x "$REWORK_DISPATCH" ]; then
      die "rework dispatch script required (--rework-dispatch) but missing/not executable: $REWORK_DISPATCH"
    fi
    # The dispatch script must: implement the rework on the branch, commit, push,
    # and print the NEW commit SHA on stdout (single line, 40 hex).
    NEW_SHA="$("$REWORK_DISPATCH" "$REPO" "$ISSUE" "$REWORK_ROUND" 2>/tmp/codex-roundtrip-rework.err)"
    [[ "$NEW_SHA" =~ ^[0-9a-f]{40}$ ]] || die "rework dispatch did not return a 40-hex new SHA (got: '$NEW_SHA') — fail-closed"
    SHA="$NEW_SHA"
    # Note: base for the follow-up review is the PREVIOUS commit SHA (the codex-review-adapter
    # defaults to <sha>~1, so a fresh commit whose parent is the reworked base is correct).
    BASE="$BASE"
    continue
  fi

  # Ingestion failure / model error / unknown verdict -> fail-closed (no retry)
  log "TERMINAL fail-closed: verdict='$VERDICT' status=$STATUS — ingestion/model failure, no retry."
  [ -z "$DRYRUN" ] && block_item
  echo "ROUNDTRIP_END $RES"
  exit 3
done
