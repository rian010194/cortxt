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
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
# Adapter path overrideable for deterministic NO-MODEL verification (a stub that
# emits the same envelope contract without calling a model). Default: merged adapter.
ADAPTER="${CODEX_ROUNDTRIP_ADAPTER:-$SELF_DIR/codex-review-adapter.sh}"
OUTPUT_CAP_TOKENS="${CODEX_ROUNDTRIP_OUTPUT_CAP:-12000}"   # #82/#12: cap configured BEFORE any model run
MAX_ADAPTER_CALLS=3                                            # #82/#9: initial + max 2 reworks => 3 Codex calls hard ceiling
WF_FIELD="PVTSSF_lAHOBcHJy84BfFfWzhZa88A"
PROJECT_ID="PVT_kwHOBcHJy84BfFfW"
OPT_REVIEW="4bfdd926"; OPT_BLOCKED="20948c2f"
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
  # If attached to Project 4, must be Ready to dispatch; if not attached, this is a warning only.
  if [ -n "$ISSUE_WF" ] && [ "$ISSUE_WF" != "Ready" ]; then
    die "issue #$ISSUE workflow is '$ISSUE_WF', not 'Ready' -> fail-closed before dispatch"
  fi
else
  die "gh not authenticated (and CODEX_ROUNDTRIP_NO_GITHUB not set)"
fi

# #82/#5: when a PR is supplied, it must be OPEN + draft, with exact head SHA + correct base.
if [ -n "$PR_NUM" ] && [ -z "$NO_GITHUB" ]; then
  PR_JSON="$(gh pr view "$PR_NUM" -R "$REPO" --json state,isDraft,headRefOid,baseRefName,headRefName 2>/dev/null)" \
    || die "cannot read PR $PR_NUM"
  PR_STATE="$(echo "$PR_JSON" | python -c "import sys,json;print(json.load(sys.stdin)['state'])")"
  PR_HEAD="$(echo "$PR_JSON" | python -c "import sys,json;print(json.load(sys.stdin)['headRefOid'])")"
  PR_BASE="$(echo "$PR_JSON" | python -c "import sys,json;print(json.load(sys.stdin)['baseRefName'])")"
  PR_DRAFT_RAW="$(echo "$PR_JSON" | python -c "import sys,json;print(json.load(sys.stdin)['isDraft'])")"
  # json 'true'/'false' -> python True/False -> normalize to lowercase for bash compare
  PR_DRAFT="$(printf '%s' "$PR_DRAFT_RAW" | tr '[:upper:]' '[:lower:]')"
  # fail-closed: OPEN + draft + exact head SHA + base == integration base.
  [ "$PR_STATE" = "OPEN" ] || die "PR $PR_NUM state is $PR_STATE, not OPEN -> fail-closed"
  [ "$PR_DRAFT" = "true" ] || die "PR $PR_NUM is not a draft -> fail-closed (review targets drafts only)"
  [ "$PR_HEAD" = "$SHA" ] || die "PR $PR_NUM head ($PR_HEAD) != requested commit ($SHA) -> fail-closed"
  [ "$PR_BASE" = "$BASE" ] || die "PR $PR_NUM base ($PR_BASE) != requested base ($BASE) -> fail-closed"
  log "PR #$PR_NUM verified: OPEN, draft, head=$PR_HEAD base=$PR_BASE"
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
    echo "{\"round\":$round,\"status\":\"failed\",\"verdict\":\"unknown\",\"reason\":\"invalid envelope: $schema_error\",\"cost_conf\":\"unknown\",\"output_tokens\":null,\"cap_verified\":false,\"artifacts\":[]}"
    return 0
  fi

  # Preserve artifacts ref/hash/size from the envelope through the result (#82/#8).
  local artifacts_json
  artifacts_json="$(printf '%s' "$preview" | python -c "
import sys,json
d=json.load(sys.stdin)
print(json.dumps([{'ref':a.get('ref'),'hash':a.get('hash'),'size':a.get('size')} for a in d.get('artifacts',[]) if isinstance(a,dict)]))
")"

  # Output-token cap (pre-configured BEFORE the model run, #82/#12): if the envelope
  # does NOT report usage.output_tokens, the cap CANNOT be verified -> fail-closed
  # (missing verifiable cap/usage must NOT be presented as evidence of compliance).
  local out_tokens cap_verified
  out_tokens="$(printf '%s' "$preview" | python -c "
import sys,json
d=json.load(sys.stdin)
u=d.get('usage',{}) or {}
v=u.get('output_tokens')
print(v if isinstance(v,int) else '')
")"
  out_tokens="${out_tokens:-}"
  cap_verified=false
  if [ -z "$out_tokens" ]; then
    echo "{\"round\":$round,\"status\":\"blocked\",\"verdict\":\"$verdict\",\"reason\":\"output-token usage not reported; cap ($OUTPUT_CAP_TOKENS) unverifiable -> fail-closed\",\"cost_conf\":unknown,\"output_tokens\":null,\"cap_verified\":false,\"artifacts\":$artifacts_json}"
    return 0
  fi
  if [ "$out_tokens" -gt "$OUTPUT_CAP_TOKENS" ]; then
    echo "{\"round\":$round,\"status\":\"failed\",\"verdict\":\"unknown\",\"reason\":\"output token cap exceeded ($out_tokens > $OUTPUT_CAP_TOKENS)\",\"cost_conf\":\"unknown\",\"output_tokens\":$out_tokens,\"cap_verified\":false,\"artifacts\":$artifacts_json}"
    return 0
  fi
  cap_verified=true

  # Envelope status must itself be succeeded for a valid review result.
  local env_status cost_conf
  env_status="$(printf '%s' "$preview" | python -c "import sys,json;print(json.load(sys.stdin).get('status',''))")"
  cost_conf="$(printf '%s' "$preview" | python -c "import sys,json;print(json.dumps(json.load(sys.stdin).get('cost',{}).get('confidence','unknown')))")"
  if [ "$env_status" != "succeeded" ]; then
    echo "{\"round\":$round,\"status\":\"$env_status\",\"verdict\":\"$verdict\",\"reason\":\"envelope status $env_status (not succeeded)\",\"cost_conf\":$cost_conf,\"output_tokens\":$out_tokens,\"cap_verified\":$cap_verified,\"artifacts\":$artifacts_json}"
    return 0
  fi

  echo "{\"round\":$round,\"status\":\"succeeded\",\"verdict\":\"$verdict\",\"reason\":\"\",\"cost_conf\":$cost_conf,\"output_tokens\":$out_tokens,\"cap_verified\":$cap_verified,\"artifacts\":$artifacts_json}"
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
    blocked) want_opt="$OPT_BLOCKED";;
    review)  want_opt="$OPT_REVIEW";;
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
  want_label="Blocked"; [ "$want" = "review" ] && want_label="Review"
  if [ "$got" != "$want_label" ]; then
    log "set_item_status read-back mismatch: want=$want_label got=$got"
    return 1
  fi
  log "project #$ISSUE workflow -> $want_label (verified)"
  return 0
}

block_item(){
  [ -n "$NO_GITHUB" ] && { log "NO_GITHUB: skip block transition"; return 0; }
  set_item_status "blocked"
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
  local cost_conf artifacts_line cap_verified
  cost_conf="$(echo "$result" | python -c "import sys,json;print(json.load(sys.stdin).get('cost_conf','unknown'))")"
  cap_verified="$(echo "$result" | python -c "import sys,json;print(json.load(sys.stdin).get('cap_verified',False))")"
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
| Output-cap verified (<=12000) | $cap_verified |
| PR | ${PR_NUM:-n/a} |

**Reproducible evidence (ref + hash + size only — no raw prompt, no secrets, no confidential artifacts):**
\`\`\`
$artifacts_line
\`\`\`

> Capability result, NOT approval. A worker never approves its own work; Hermes
> does not substitute its own judgment for the Codex verdict. Merge / Done /
> deploy remain operator-only.
EOF
  local body_win
  body_win="$(cygpath -w "$body_file")"
  # Post via gh api to capture the NUMERIC comment id reliably (#82/#6).
  local post_json cid readback
  post_json="$(gh api "repos/$REPO/issues/$ISSUE/comments" -f body=@"$body_win" 2>/tmp/roundtrip-post.err)" \
    || { log "evidence POST failed: $(tail -2 /tmp/roundtrip-post.err)"; rm -f "$body_file"; return 1; }
  cid="$(printf '%s' "$post_json" | python -c "import sys,json;print(json.load(sys.stdin).get('id',''))")"
  [ -n "$cid" ] || { log "evidence POST returned no numeric id"; rm -f "$body_file"; return 1; }
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
FINAL_RESULT=""
CALLS=0
while :; do
  CALLS=$((CALLS+1))
  if [ "$CALLS" -gt "$MAX_ADAPTER_CALLS" ]; then
    log "TERMINAL: adapter-call ceiling $MAX_ADAPTER_CALLS hit -> blocked + operator escalation (no self-approval)."
    if [ -z "$DRYRUN" ] && ! block_item; then log "block transition failed"; fi
    echo "ROUNDTRIP_END {\"round\":$CALLS,\"status\":\"blocked\",\"verdict\":\"CEILING\"}"
    exit 4
  fi
  RES="$(run_one_review "$SHA" "$BASE" "$CALLS")"
  STATUS="$(echo "$RES" | python -c "import sys,json;print(json.load(sys.stdin).get('status','failed'))")"
  VERDICT="$(echo "$RES" | python -c "import sys,json;print(json.load(sys.stdin).get('verdict','unknown'))")"

  # Fail-closed terminal statuses (no retry, no fallback)
  case "$STATUS" in
    timed_out|failed)
      log "TERMINAL fail-closed: status=$STATUS (call $CALLS). no retry, no model fallback."
      if [ -z "$DRYRUN" ] && ! block_item; then log "block transition failed"; fi
      echo "ROUNDTRIP_END $RES"
      exit 3
      ;;
    succeeded) ;;
    blocked) # cap unverifiable -> fail-closed block
      log "TERMINAL fail-closed: status=blocked (call $CALLS). no retry, no model fallback."
      if [ -z "$DRYRUN" ] && ! block_item; then log "block transition failed"; fi
      echo "ROUNDTRIP_END $RES"
      exit 3
      ;;
    *) # unknown status -> fail-closed
      log "TERMINAL fail-closed: unknown status=$STATUS (call $CALLS)"
      echo "ROUNDTRIP_END $RES"
      exit 3
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
    # #82/#10: use the REAL bounded Hermes Builder dispatch adapter (not an arbitrary hook).
    if [ -z "$REWORK_DISPATCH" ] || [ ! -x "$REWORK_DISPATCH" ]; then
      die "--rework-dispatch (Hermes Builder dispatch adapter) required but missing/not executable: $REWORK_DISPATCH"
    fi
    # The Builder dispatch adapter must: run the builder on InferX (12k cap), commit, PUSH a NEW
    # PR-head, and print the NEW pushed 40-hex commit SHA on stdout. fail-closed on any miss.
    NEW_SHA="$(set +e; "$REWORK_DISPATCH" "$REPO" "$ISSUE" "$CALLS"; echo "RC=$?")"
    NEW_RC="${NEW_SHA##*RC=}"; NEW_SHA="${NEW_SHA%RC=*}"
    NEW_SHA="$(printf '%s' "$NEW_SHA" | tr -d ' \r\n' | tail -c 40)"
    if [ "$NEW_RC" != "0" ] || ! [[ "$NEW_SHA" =~ ^[0-9a-f]{40}$ ]]; then
      die "Builder dispatch did not deliver a pushed 40-hex PR-head (rc=$NEW_RC) -> fail-closed"
    fi
    # Require the new head to actually exist on origin (local==remote for the reworked PR head).
    # In NO_GITHUB deterministic mode the dispatch is a stub; the fetch/push guarantee is a
    # real-run concern (the verifier exercises the SHA-format + rc fail-closed instead).
    if [ -z "$NO_GITHUB" ]; then
      git fetch origin "$NEW_SHA" 2>/dev/null || die "new PR-head $NEW_SHA not on origin -> fail-closed"
    fi
    SHA="$NEW_SHA"
    continue
  fi

  # Ingestion failure / model error / unknown verdict -> fail-closed (no retry)
  log "TERMINAL fail-closed: verdict='$VERDICT' status=$STATUS — ingestion/model failure, no retry."
  [ -z "$DRYRUN" ] && { block_item || log "block transition failed"; }
  echo "ROUNDTRIP_END $RES"
  exit 3
done
