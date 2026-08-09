#!/usr/bin/env bash
# dispatch-manual.sh — minimal contract-compliant MANUAL dispatch adapter
#
# Proves the smallest adapter that can take an approved *Ready* GitHub issue,
# create a run_id OUTSIDE any model, dispatch one worker profile, capture a
# result envelope, transition the issue Ready -> In progress -> Review, and
# push status back to Buzz. No n8n, no second control plane.
#
# Contract: docs/architecture/dispatch-contract.md
# Routine:  docs/operations/manual-dispatch-routine.md
# Boundary: Buzz pushes STATUS only — it never creates backlog.
#
# Usage:
#   OPENROUTER_API_KEY=... ./dispatch-manual.sh <owner/repo#num|URL> [profile] [--dry-run]
#
# Safety rules enforced here:
#   1. Do NOT dispatch a ticket blocked by an OPEN issue.
#   2. Do NOT dispatch unless the issue has acceptance criteria.
#   3. run_id is generated in the SHELL, never by a model.
#   4. No agent approves its own work -> final Done is left to the operator.
#   5. Secrets/prompts are never placed in GitHub, the channel, or git.
#
# State transitions:
#   Ready -> (claim comment + run_id) -> In progress -> (run) -> Review
#   Done is reached ONLY by independent review + operator approval.

set -euo pipefail

REPO="rian010194/ai-workspace-control-plane"
PROJECT_NUM="4"                       # "AI Workspace Delivery" v2 project
WF_STATUS_FIELDID="PVTSSF_lAHOBcHJy84BfFfWzhZa88A"   # Workflow Status
OPT_INPROGRESS="89a2da8a"; OPT_REVIEW="4bfdd926"; OPT_READY="6b6c745a"

WORKFLOW_RE="(Blocked by|Depends on) *:? *#?[0-9]+"

usage(){ echo "usage: dispatch-manual.sh <owner/repo#num|URL> [profile] [--dry-run]"; exit 2; }
log(){  echo "[dispatch] $*"; }
die(){  log "ABORT: $*" >&2; exit 1; }

# --- resolve issue spec ---
ISSUE="${1:-}"; [ -n "$ISSUE" ] || usage
PROFILE="${2:-researcher}"
DRYRUN=""; case " $* " in *" --dry-run "*) DRYRUN=1;; esac

# normalise e.g. https://github.com/OWNER/REPO/issues/N -> OWNER/REPO#N
case "$ISSUE" in
  *github.com/*/issues/*) ISSUE="$(echo "$ISSUE" | sed -E 's#https?://github.com/([^/]+/[^/]+)/issues/([0-9]+)#\1#\2#')";;
esac
[[ "$ISSUE" =~ ^[^/]+/[^/]+#[0-9]+$ ]] || die "bad issue spec: $ISSUE"
ISSUE_NUM="${ISSUE##*#}"

# --- Step 0: pre-dispatch guard (fail closed) ---
REPO="${ISSUE%%#*}"
NUM="${ISSUE##*#}"
log "guard: reading issue $ISSUE"
JSON="$(gh issue view "$NUM" -R "$REPO" --json state,title,body -q . 2>/dev/null)" \
  || die "cannot read issue $ISSUE (gh auth?)"
STATE="$(echo "$JSON" | python -c "import sys,json;print(json.load(sys.stdin)['state'])")"
BODY="$(  echo "$JSON" | python -c "import sys,json;print(json.load(sys.stdin)['body'] or '')")"
TITLE="$(echo "$JSON" | python -c "import sys,json;print(json.load(sys.stdin)['title'] or '')")"
[ "$STATE" = "OPEN" ] || die "issue is $STATE, not OPEN -> do not dispatch"

# blocker check: refuse if 'Blocked by/depends on #N' where N is still open
if grep -Eiq "$WORKFLOW_RE" <<<"$BODY"; then
  for b in $(grep -Eio "#[0-9]+" <<<"$BODY" | grep -oE "[0-9]+" | sort -u); do
    if [ "$(gh issue view "$b" -R "$REPO" --json state -q .state 2>/dev/null)" = "OPEN" ]; then
      die "blocked by open issue #$b -> do NOT dispatch (learned from #16 error)"
    fi
  done
fi
grep -Eq '\-\s*\[[ x]\]|Acceptance crit|accepter' <<<"$BODY" || {
  die "no acceptance criteria found -> issue not dispatchable"
}

# Ready check (project workflow status must be Ready) — advisory unless --dry-run
WF="$(gh project item-list "$PROJECT_NUM" --owner "${REPO%%/*}" --format json --limit 100 2>/dev/null \
        | python -c "import sys,json
d=json.load(sys.stdin)
for i in d['items']:
    if str(i.get('content',{}).get('number'))=='$ISSUE_NUM':
        print(i.get('workflow Status',''));break" || true)"
log "project workflow status = '${WF:-<not-in-project>}'"
if [ -n "$WF" ] && [ "$WF" != "Ready" ]; then
  die "workflow status is '$WF', not 'Ready' -> create/ready a test issue first"
fi

# --- Step 1: run identity generated OUTSIDE the model ---
RUN_ID="$(date -u +%Y%m%d_%H%M%S)_$(openssl rand -hex 4)"
log "run_id = $RUN_ID (generated in shell, outside any model)"
[ -n "$DRYRUN" ] && { log "dry-run: would dispatch run $RUN_ID -> profile $PROFILE"; exit 0; }

# --- Step 2: claim (Ready -> In progress) on the GitHub source of truth ---
CLAIM="Claimed by manual dispatch adapter (dispatch-manual.sh).
run_id: \`$RUN_ID\`
runtime: ${PROFILE}
status: In progress (Ready -> In progress per dispatch-contract).
No agent approves its own work; final Done is operator-only."
gh issue comment "$NUM" -R "$REPO" --body "$CLAIM" >/dev/null
log "claim comment posted on $ISSUE"

ITEM_ID="$(gh project item-list "$PROJECT_NUM" --owner "${REPO%%/*}" --format json --limit 100 2>/dev/null \
             | python -c "import sys,json
d=json.load(sys.stdin)
for i in d['items']:
    if str(i.get('content',{}).get('number'))=='$ISSUE_NUM':
        print(i['id']);break" || true)"
[ -n "$ITEM_ID" ] && { gh project item-edit --id "$ITEM_ID" --project-id "PVT_kwHOBcHJy84BfFfW" \
  --field-id "$WF_STATUS_FIELDID" --single-select-option-id "$OPT_INPROGRESS" >/dev/null 2>&1 \
  && log "workflow -> In progress"; } || log "issue not linked to project; skip transition"

# --- Step 3: dispatch one worker profile (non-interactive one-shot) ---
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
log "dispatching profile '$PROFILE' (run $RUN_ID)"
MODEL_HINT="$(hermes -p "$PROFILE" status 2>/dev/null | grep -iE "Model:" | head -1 | sed 's/^ *Model: *//' || echo unknown)"

PROMPT="You are the ${PROFILE} worker for a manual-dispatch adapter proof (synthetic test).
Dispatch context (already approved; do NOT browse or fetch anything):
- Issue: ${REPO}#${ISSUE_NUM}
- Title: ${TITLE}
- run_id: ${RUN_ID}
Task: confirm you can see this context and output ONLY a SHORT markdown list of:
(1) the issue you worked, (2) the run_id you were given, (3) the first
acceptance criterion you can see, (4) the provider/model identifier you ran on.
Do not use tools, do not browse, do not elaborate. Three to four bullets only.
No secrets, no private docs, no full prompts."

set +e  # worker failure must be captured, not fatal (fail-closed)
WORK_OUT="$(OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}" timeout 90 \
            hermes -p "$PROFILE" -z "$PROMPT" 2>/tmp/dispatch.err)"
RC=$?
set -e
if [ $RC -ne 0 ]; then
  FIN_STATUS="failed"
  ERR_TAIL="$(tail -3 /tmp/dispatch.err 2>/dev/null)"
  WORK_OUT="${WORK_OUT:-}<worker rc=$RC stderr: ${ERR_TAIL:-n/a}>"
fi
FIN_STATUS="${FIN_STATUS:-succeeded}"
FINISHED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# --- Step 4: result envelope posted to the issue (source of truth) ---
# Honest cost/usage: the manual dispatch adapter does NOT measure model usage or
# cost, so it MUST report 'unknown', never 0 and never a guessed provider label.
# #58/#71: 'Cost | USD 0.00 (free :free openrouter model)' was a false default —
# it claimed a specific provider+cost regardless of the actual model used.
COST_STATUS="unknown (not measured by dispatch-manual.sh)"
COST_CONFIDENCE="unknown"
USAGE_STATUS="unknown (usage not captured by dispatch-manual.sh)"
ENVELOPE="## Run result: \`$RUN_ID\`

| Field | Value |
|---|---|
| Status | \`$FIN_STATUS\` |
| Runtime | Hermes ($(hermes --version 2>/dev/null | head -1)) |
| Worker role | $PROFILE |
| Model | $MODEL_HINT |
| Started at | $STARTED |
| Finished at | $FINISHED |
| Cost | $COST_STATUS (confidence: $COST_CONFIDENCE) |
| Usage | $USAGE_STATUS |
| Error | none |

**Work output (evidence):**
\`\`\`
$WORK_OUT
\`\`\`

Result left at **Review — final Done requires independent review + operator approval.**"
gh issue comment "$NUM" -R "$REPO" --body "$ENVELOPE" >/dev/null
log "result envelope posted on $ISSUE (status=$FIN_STATUS)"

# --- Step 5: In progress -> Review ---
[ -n "$ITEM_ID" ] && gh project item-edit --id "$ITEM_ID" --project-id "PVT_kwHOBcHJy84BfFfW" \
  --field-id "$WF_STATUS_FIELDID" --single-select-option-id "$OPT_REVIEW" >/dev/null 2>&1 \
  && log "workflow -> Review"

# --- Step 6: push status to Buzz (status only; never creates backlog) ---
if command -v python >/dev/null && [ -f harness/scripts/buzz-return.py ]; then
  STAT_MSG="dispatch $ISSUE run $RUN_ID ${PROFILE} -> $FIN_STATUS (Review) — ready for operator"
  PY="$(command -v python)"
  BUZZ_RET="$(cygpath -w "$(cd "$(dirname "$0")" && pwd)/buzz-return.py" 2>/dev/null || echo "$(cd "$(dirname "$0")" && pwd)/buzz-return.py")"
  "$PY" "$BUZZ_RET" send --content "$STAT_MSG" >/tmp/buzz.out 2>/tmp/buzz.err \
    && log "buzz-return OK: $(cat /tmp/buzz.out)" \
    || log "buzz-return skip: $(tail -2 /tmp/buzz.err) (dry-run/no key)"
fi

echo "DISPATCH_DONE run_id=$RUN_ID issue=$ISSUE profile=$PROFILE status=$FIN_STATUS"
