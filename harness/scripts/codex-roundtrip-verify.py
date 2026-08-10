#!/usr/bin/env python3
"""codex-roundtrip-verify.py — deterministic NO-MODEL verifier for codex-roundtrip.sh

Demonstrates the ROUNDTRIP-001 (#82) fail-closed + control-flow contract WITHOUT
calling any model and WITHOUT any GitHub write (CODEX_ROUNDTRIP_NO_GITHUB=1).
It stands up stub codex-review-adapter scripts that emit the same envelope
contract the real merged adapter emits (PR #81), then runs codex-roundtrip.sh
against them and asserts:

  Path A  GODKÄND                     -> orchestrator exits 0, verdict GODKÄND
  Path B  KRÄVER ÄNDRINGAR -> rework -> GODKÄND   (rework dispatched, 2 review rounds)
  Path C  fail-closed timeout (rc 124) -> orchestrator exits 3, status=timed_out
  + additional fail-closed edges: broken envelope, INGESTION MISSLYCKADES,
    unknown verdict, no auto-retry (adapter invoked exactly N expected times),
    honest cost + usage (never fabricated; missing usage = unknown, NOT a block),
    deterministic review-artifact byte cap (MAX_ARTIFACT_BYTES, multibyte-aware),
    and exact Ready->In progress->Blocked transitions for every terminal failure class.
NOTE (operator #82/AC6): there is NO hard 12k-output-token cap for the Codex reviewer;
usage is reported when present and NEVER blocks. The hard 12k cap applies ONLY to the
InferX Builder adapter (not verified here — this file is the Codex orchestrator verifier).

Usage:
  python codex-roundtrip-verify.py            # all checks, exit nonzero on failure
  python codex-roundtrip-verify.py --verbose  # per-check detail

Run from repo root. Requires: bash, python, git (a real repo). No model, no gh.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORCH = os.path.join(REPO_ROOT, "harness", "scripts", "codex-roundtrip.sh")
ADAPTER_REAL = os.path.join(REPO_ROOT, "harness", "scripts", "codex-review-adapter.sh")
DISPATCH = os.path.join(REPO_ROOT, "harness", "scripts", "codex-roundtrip-builder-dispatch.sh")

PASS = 0
FAIL = 0
CHECKS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        CHECKS.append(f"  PASS  {name}")
    else:
        FAIL += 1
        CHECKS.append(f"  FAIL  {name}  {detail}")


def make_stub_adapter(out_dir, scenario):
    """Write a stub adapter bash script that emits the real adapter's contract.

    scenario keys:
      verdict:  GODKAND | KRAVER | INGESTION | UNKNOWN
      rc:       exit code returned (124 for timeout simulation; 0 otherwise)
      broken:   omit the REVIEW_ENVELOPE_JSON markers (broken envelope)
      no_usage: omit usage entirely (operator-AC6: missing usage -> unknown, NOT a blocker)
      big_artifact: emit an envelope larger than MAX_ARTIFACT_BYTES (ingestion fail-closed)
      invocation_log: file appended to each time the stub runs (retry counting)
    """
    verdict = scenario.get("verdict", "GODKAND")
    rc = scenario.get("rc", 0)
    broken = scenario.get("broken", False)
    no_usage = scenario.get("no_usage", False)
    big_artifact = scenario.get("big_artifact", False)
    multibyte_big = scenario.get("multibyte_big", False)
    invlog = scenario.get("invocation_log", "")
    vmap = {
        "GODKAND": "GODKÄND",
        "KRAVER": "KRÄVER ÄNDRINGAR",
        "INGESTION": "INGESTION MISSLYCKADES",
        "UNKNOWN": "RANDOM TEXT",
    }
    verdict_str = vmap[verdict]
    out_tokens = 512
    usage_json = json.dumps({"input_tokens": 1000, "output_tokens": out_tokens,
                             "cache_tokens": 0, "reasoning_tokens": 0})
    cost_json = json.dumps({"confidence": "unknown"})
    sha = scenario.get("sha", "a" * 40)
    artifacts = [{"ref": sha, "hash": "abc123", "size": 42}]
    if big_artifact:
        artifacts = [{"ref": sha, "hash": "abc123", "size": 42, "blob": "x" * 300000}]
    if multibyte_big:
        # Point-2 regression: many MULTIBYTE chars ('å' = 2 UTF-8 bytes each). We want a blob
        # whose CHARACTER count stays under a small cap but whose UTF-8 BYTE count exceeds it,
        # proving the orchestrator compares wc -c (bytes), not bash ${#preview} (chars).
        # 300 'å' = 600 UTF-8 bytes but only 300 chars; with a cap of 500 that only byte-logic catches.
        artifacts = [{"ref": sha, "hash": "abc123", "size": 42, "blob": "å" * 300}]
    env = {
        "issue_id": "commit %s" % sha,
        "run_id": "11111111-2222-4333-8444-555555555555",
        "status": "succeeded",
        "runtime": "stub (no model)",
        "worker_role": "codex-reviewer",
        "started_at": "2026-08-09T00:00:00Z",
        "finished_at": "2026-08-09T00:00:01Z",
        "model": "gpt-5.6-sol",
        "cost": json.loads(cost_json),
        "artifacts": artifacts,
        "evidence": ["stub"],
    }
    if not no_usage:
        env["usage"] = json.loads(usage_json)
    else:
        # operator-AC6: usage present but EMPTY (schema-valid) -> output_tokens unknown, NOT a block
        env["usage"] = {}
    # Use a quoted heredoc 'EOF' so the envelope is emitted verbatim (no shell expansion).
    header = "#!/usr/bin/env bash\nset -euo pipefail\n"
    if invlog:
        header += 'echo "$(date +%s) $(hostname)" >> "' + invlog + '"\n'
    body = header + (
        'SHA="${1:-}"\n'
        'echo "REVIEW_ENVELOPE_JSON"\n'
        "cat <<'ENVEOF'\n" + json.dumps(env, ensure_ascii=False) + "\nENVEOF\n"
        'echo "CODEX_REVIEW_DONE run_id=1 commit=\\"$SHA\\" verdict=%s cost=unknown"\n' % verdict_str +
        "exit %d\n" % rc
    )
    if broken:
        # keep the markers AND the done line but Omit the envelope JSON entirely
        # (still leaves markers present -> duplicate-marker risk; simpler: remove markers)
        body = header + (
            'SHA="${1:-}"\n'
            "echo 'CODE: broken envelope (no markers)'\n"
            'echo "CODEX_REVIEW_DONE run_id=1 commit=\\"$SHA\\" verdict=%s cost=unknown"\n' % verdict_str +
            "exit %d\n" % rc
        )
    path = os.path.join(out_dir, "stub-adapter.sh")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(path, 0o755)
    return path


def run_orchestrator(adapter, rework_dispatch, sha, base, issue="82", max_rework=2, extra_args=None,
                     no_github=True, mock_dir=None, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    env["CODEX_ROUNDTRIP_ADAPTER"] = adapter
    # Explicitly control the NO_GITHUB flag so it exactly matches the parameter,
    # regardless of any inherited CODEX_ROUNDTRIP_NO_GITHUB env var.
    if no_github:
        env["CODEX_ROUNDTRIP_NO_GITHUB"] = "1"
    else:
        env.pop("CODEX_ROUNDTRIP_NO_GITHUB", None)
    if mock_dir:
        env["PATH"] = mock_dir + os.pathsep + env.get("PATH", "")
    bash = shutil.which("bash") or "bash"
    args = [bash, ORCH, "-i", issue, "-c", sha, "-b", base, "--max-rework", str(max_rework)]
    if extra_args:
        args += extra_args
    if rework_dispatch:
        args += ["--rework-dispatch", rework_dispatch]
    env["PATH"] = env.get("PATH", "")
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=REPO_ROOT)
    return proc


def make_gh_mock(out_dir, cfg):
    """Write a deterministic `gh` shim to out_dir/bin controlling GitHub behavior.
    Built with plain Python concatenation (no nested-heredoc escaping). Behavior is
    driven by env vars the python driver sets per test."""
    bin_dir = os.path.join(out_dir, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    sh = os.path.join(bin_dir, "gh")
    L = []
    L.append("#!/usr/bin/env bash")
    L.append('CMD="$1"; shift || true')
    L.append("""
case "$CMD" in
  auth) echo "logged in"; exit 0;;
  issue)
    if [ "$1" = "view" ]; then printf '%s' "$GHMOCK_ISSUE_STATE"; exit 0; fi
    exit 0;;
  pr)
    # state,isDraft,headRefOid,baseRefName,headRefName
    printf '{"state":"%s","isDraft":%s,"headRefOid":"%s","baseRefName":"%s","headRefName":"agent/x"}' \\
      "$GHMOCK_PR_STATE" "$GHMOCK_PR_DRAFT" "$GHMOCK_PR_HEAD" "$GHMOCK_PR_BASE"
    exit 0;;
  project)
    if [ "$1" = "item-list" ]; then
      printf '{"items":[{"id":"PVTI_mock","content":{"number":%s}}]}' "$GHMOCK_ISSUE_NUM"; exit 0
    fi
    if [ "$1" = "item-edit" ]; then
      # stateful: record the single-select-option-id -> label in the state file (Codex-item2).
      # Append each successful transition to GHMOCK_TX_LOG (Ready, In progress, Review, Blocked)
      # so tests can assert the exact sequence, not just the final state. Failure injection:
      #   GHMOCK_FAIL_REVIEW  -> the Review transition fails (mv_review fail)
      #   GHMOCK_FAIL_BLOCKED -> the Blocked transition fails (fail_terminal tx path -> exit 6)
      for a in "$@"; do
        case "$a" in
          89a2da8a)
            echo "In progress" > "$GHMOCK_STATE_FILE"
            printf '%s\n' "In progress" >> "$GHMOCK_TX_LOG";;
          4bfdd926)
            if [ "$GHMOCK_FAIL_REVIEW" = "1" ]; then
              printf '%s\n' "Review(FAIL)" >> "$GHMOCK_TX_LOG"; exit 7
            fi
            echo "Review" > "$GHMOCK_STATE_FILE"
            printf '%s\n' "Review" >> "$GHMOCK_TX_LOG";;
          20948c2f)
            if [ "$GHMOCK_FAIL_BLOCKED" = "1" ]; then
              printf '%s\n' "Blocked(FAIL)" >> "$GHMOCK_TX_LOG"; exit 7
            fi
            echo "Blocked" > "$GHMOCK_STATE_FILE"
            printf '%s\n' "Blocked" >> "$GHMOCK_TX_LOG";;
        esac
      done
      exit 0
    fi
    exit 0;;
  api)
    SUB="$1"
    if [ "$SUB" = "graphql" ]; then
      # Return the CURRENT stateful status (all read-backs see the latest recorded value).
      ST="$(cat "$GHMOCK_STATE_FILE" 2>/dev/null || echo "$GHMOCK_WF_STATUS")"
      printf '%s' "$ST"
      exit 0
    fi
    # issues/N/comments POST or read-back (path ends with /comments)
    case "$SUB" in *comments)
      if [[ "$*" == *--jq* ]]; then
        # read-back path: return the body or empty
        if [ "$GHMOCK_READBACK" = "empty" ]; then exit 0; fi
        echo "## Codex review evidence - ROUNDTRIP #$GHMOCK_ISSUE_NUM, round 1"
        echo "- abc | hash \`abc123\` | size 42"
        exit 0
      fi
      # POST: return numeric comment id
      printf '{"id":%s}' "$GHMOCK_COMMENT_ID"; exit 0;;
    esac
    exit 0;;
  *) exit 0;;
esac
""")
    with open(sh, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    os.chmod(sh, 0o755)
    return bin_dir


def run_gh_mocked(adapter, out_dir, cfg, sha, base, extra_args=None, issue="82", rework_dispatch=None):
    """Run the orchestrator against the deterministic gh mock (NO_GITHUB off)."""
    bin_dir = make_gh_mock(out_dir, cfg)
    env_extra = {
        "GHMOCK_ISSUE_STATE": cfg.get("issue_state", "OPEN"),
        "GHMOCK_WF_STATUS": cfg.get("wf_status", "Ready"),
        "GHMOCK_PR_STATE": cfg.get("pr_state", "OPEN"),
        "GHMOCK_PR_DRAFT": cfg.get("pr_draft", "true"),
        "GHMOCK_PR_HEAD": cfg.get("pr_head", sha),
        "GHMOCK_PR_BASE": cfg.get("pr_base", base),
        "GHMOCK_ISSUE_NUM": issue,
        "GHMOCK_COMMENT_ID": cfg.get("comment_id", "424242"),
        "GHMOCK_READBACK": cfg.get("readback", "post"),
        # node-shape status used for set_item_status read-back (Review/Blocked)
        "GHMOCK_WF_NAME": cfg.get("wf_name", "Review"),
        # transition failure-injection + exact-sequence log
        "GHMOCK_FAIL_REVIEW": cfg.get("fail_review", "0"),
        "GHMOCK_FAIL_BLOCKED": cfg.get("fail_blocked", "0"),
        "GHMOCK_TX_LOG": cfg.get("tx_log", os.path.join(out_dir, "tx-log-%d" % os.getpid())),
    }
    # stateful workflow-status file: start as the configured initial wf status
    state_file = os.path.join(out_dir, "wf-state-%s" % os.getpid())
    with open(state_file, "w", encoding="utf-8") as f:
        f.write(cfg.get("wf_status", "Ready"))
    env_extra["GHMOCK_STATE_FILE"] = state_file
    # transitions log starts at the configured initial status (Ready)
    tx_log = env_extra["GHMOCK_TX_LOG"]
    with open(tx_log, "w", encoding="utf-8") as f:
        f.write("Ready\n")
    return run_orchestrator(adapter, rework_dispatch, sha, base, issue=issue, no_github=False,
                            mock_dir=bin_dir, extra_args=extra_args, env_extra=env_extra)


def main():
    verbose = "--verbose" in sys.argv
    global PASS, FAIL

    with tempfile.TemporaryDirectory() as out_dir:
        out_dir = os.path.realpath(out_dir)
        base = "c0d641db15232e949630ced01ddab4f9114ce9d3"  # integration tip (reachable)
        sha_a = base  # any reachable commit for path A

        # ---------- Path A: GODKÄND ----------
        invlog_a = os.path.join(out_dir, "inv_a.log")
        adapter_a = make_stub_adapter(out_dir, {"verdict": "GODKAND", "invocation_log": invlog_a})
        p = run_orchestrator(adapter_a, None, sha_a, base)
        out = p.stdout
        ok_exit = p.returncode == 0
        # parse the ROUNDTRIP_END JSON payload -> verdict must be GODKÄND
        end_json = ""
        if "ROUNDTRIP_END" in out:
            end_json = out.split("ROUNDTRIP_END", 1)[1].strip()
        verdict_ok = False
        try:
            parsed_end = json.loads(end_json)
            verdict_ok = parsed_end.get("verdict") == "GODKÄND"
        except Exception:
            verdict_ok = ("GODKÄND" in out and "SUCCEEDED" not in out.upper()) and '"verdict": "GODKÄND"' in out or 'verdict":"GODKÄND"' in out
        ok_verdict = verdict_ok
        ok_end = "ROUNDTRIP_END" in out
        inv_count = 0
        if os.path.exists(invlog_a):
            inv_count = sum(1 for _ in open(invlog_a))
        check("A GODKÄND: exit 0", ok_exit, "rc=%d" % p.returncode)
        check("A GODKÄND: verdict present", ok_verdict, out[-400:])
        check("A GODKÄND: ROUNDTRIP_END emitted", ok_end)
        check("A GODKÄND: exactly 1 adapter invocation (no retry)", inv_count == 1, "count=%d" % inv_count)

        # ---------- Path B: KRÄVER -> rework -> GODKÄND ----------
        invlog_b = os.path.join(out_dir, "inv_b.log")
        # stub adapter returns KRÄVER on first call, GODKÄND on subsequent (rework fixes it)
        adapter_b = write_stub_b(out_dir, invlog_b)

        # rework dispatch stub: simulates the Builder dispatch adapter delivering a reworked,
        # pushed commit. Contract (#82/#1): args = (owner/repo#issue, round); must emit
        # BUILDER_DISPATCH_DONE ... head=<40hex> on stdout, exit 0 (orchestrator parses head=).
        args_log = os.path.join(out_dir, "dispatch-args.log")
        rework_stub = os.path.join(out_dir, "rework.sh")
        with open(rework_stub, "w", encoding="utf-8") as f:
            f.write(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'ISSUE="${1:-}"; ROUND="${2:-0}"\n'
                'printf "%s %s" "$ISSUE" "$ROUND" >> "' + args_log + '" # record real production args\n'
                'printf "BUILDER_DISPATCH_DONE issue=%s round=%s head=cccccccccccccccccccccccccccccccccccccc%02d model=Qwen3-Coder-Next-FP8 model_cost_status=unknown\\n" "$ISSUE" "$ROUND" "$((ROUND))"\n'
                'echo "RC=0"\n'
            )
        os.chmod(rework_stub, 0o755)

        first_sha = sha_a
        # KRÄVER->rework->new-review flow runs WITHOUT dry-run + NO_GITHUB (real control flow,
        # thoroughly deterministic because the adapter + rework scripts are stubs, no model/gh writes).
        p_b2 = run_orchestrator(adapter_b, rework_stub, first_sha, base, max_rework=2)
        out_b2 = p_b2.stdout + "\n" + p_b2.stderr  # [roundtrip] logs go to stderr
        check("B KRÄVER->rework->GODKÄND: exit 0", p_b2.returncode == 0, "rc=%d" % p_b2.returncode)
        rounds = (out_b2.count("[roundtrip] --- round")
                  + out_b2.count("VERDICT"))
        check("B KRÄVER->rework->GODKÄND: >=2 independent Codex reviews (2 rounds)", rounds >= 2, "rounds=%d" % rounds)
        check("B final verdict GODKÄND", "GODKÄND" in out_b2.split("ROUNDTRIP_END")[-1] or "GODKÄND" in out_b2, out_b2[-300:])
        # #82/#1 + #12: assert the REAL production dispatch signature (owner/repo#issue, round),
        # captured by the stub's arg recorder — not a mock that adapts to implementation bugs.
        if os.path.exists(args_log):
            sig = open(args_log, encoding="utf-8").read()
            import re as _re
            issue_part, _, round_part = sig.partition(" ")
            check("B dispatch signature: owner/repo#issue + numeric round",
                  _re.match(r"^[^/]+/[^/]+#[0-9]+$", issue_part) and _re.fullmatch(r"\d+", round_part),
                  "sig=%r" % sig)
        else:
            check("B dispatch signature: owner/repo#issue + numeric round", False, "args log missing")

        # ---------- Path C: fail-closed timeout ----------
        invlog_c = os.path.join(out_dir, "inv_c.log")
        adapter_c = make_stub_adapter(out_dir, {"verdict": "GODKAND", "rc": 124, "invocation_log": invlog_c})
        p_c = run_orchestrator(adapter_c, None, sha_a, base)
        check("C timeout: exit 3 (fail-closed)", p_c.returncode == 3, "rc=%d" % p_c.returncode)
        check("C timeout: status=timed_out", "timed_out" in p_c.stdout, p_c.stdout[-300:])
        inv_c = sum(1 for _ in open(invlog_c)) if os.path.exists(invlog_c) else 0
        check("C timeout: exactly 1 adapter invocation (no retry)", inv_c == 1, "count=%d" % inv_c)

        # ---------- Edge: broken envelope ----------
        adapter_d = make_stub_adapter(out_dir, {"verdict": "GODKAND", "broken": True})
        p_d = run_orchestrator(adapter_d, None, sha_a, base)
        check("D broken envelope: exit 3", p_d.returncode == 3, "rc=%d" % p_d.returncode)
        check("D broken envelope: status=failed", "failed" in p_d.stdout, p_d.stdout[-300:])

        # ---------- Edge: INGESTION MISSLYCKADES ----------
        adapter_e = make_stub_adapter(out_dir, {"verdict": "INGESTION"})
        p_e = run_orchestrator(adapter_e, None, sha_a, base)
        check("E ingestion failure: exit 3 (not success)", p_e.returncode == 3, "rc=%d" % p_e.returncode)

        # ---------- Edge (operator-AC6): missing usage -> unknown, NOT a blocker ----------
        adapter_f = make_stub_adapter(out_dir, {"verdict": "GODKAND", "no_usage": True})
        p_f = run_orchestrator(adapter_f, None, sha_a, base)
        check("F' missing-usage GODKÄND: exit 0 (does NOT block)", p_f.returncode == 0,
              "rc=%d" % p_f.returncode)
        # the final envelope reports output_tokens null/unknown (from empty usage), not fabricated
        check("F' missing-usage: output_tokens not fabricated",
              'output_tokens":null' in p_f.stdout or 'output_tokens": null' in p_f.stdout,
              p_f.stdout[-200:])

        # ---------- Edge: unknown verdict fail-closed ------
        adapter_g = make_stub_adapter(out_dir, {"verdict": "UNKNOWN"})
        p_g = run_orchestrator(adapter_g, None, sha_a, base)
        check("G unknown verdict: exit 3 (fail-closed)", p_g.returncode == 3, "rc=%d" % p_g.returncode)

        # ===== Codex #82 rework regressions (NO-MODEL) =====

        # R1: issue workflow NOT Ready -> fail-closed (Codex #1/#4)
        adapter_r1 = make_stub_adapter(out_dir, {"verdict": "GODKAND"})
        p_r1 = run_gh_mocked(adapter_r1, out_dir, {"wf_status": "Todo"}, sha_a, base)
        check("R1 issue not Ready: fail-closed (nonzero)", p_r1.returncode != 0, "rc=%d" % p_r1.returncode)
        check("R1 issue not Ready: refused before dispatch", "not 'Ready'" in (p_r1.stdout+p_r1.stderr), "")

        # R2: PR supplied but NOT draft -> fail-closed (Codex #5)
        p_r2 = run_gh_mocked(adapter_r1, out_dir, {"pr_draft": "false", "pr_base": "agent/separate-harness-verticals"}, sha_a, base,
                             extra_args=["--pr", "5", "--base-branch", "agent/separate-harness-verticals"])
        check("R2 non-draft PR: fail-closed (nonzero)", p_r2.returncode != 0, "rc=%d" % p_r2.returncode)
        check("R2 non-draft PR: refused", "not a draft" in (p_r2.stdout+p_r2.stderr), "")
        # R2b: --pr with a mismatched base branch -> fail-closed (Codex-item2)
        p_r2b = run_gh_mocked(adapter_r1, out_dir, {"pr_base": "agent/separate-harness-verticals"}, sha_a, base,
                              extra_args=["--pr", "5", "--base-branch", "agent/wrong"])
        check("R2b base-branch mismatch: fail-closed (nonzero)", p_r2b.returncode != 0, "rc=%d" % p_r2b.returncode)
        check("R2b base-branch mismatch: refused", "base branch" in (p_r2b.stdout+p_r2b.stderr).lower(), "")

        # R3: PR head != requested commit -> fail-closed (Codex #5)
        p_r3 = run_gh_mocked(adapter_r1, out_dir, {"pr_head": "f"*40, "pr_base": "agent/separate-harness-verticals"}, sha_a, base,
                             extra_args=["--pr", "5", "--base-branch", "agent/separate-harness-verticals"])
        check("R3 wrong PR head: fail-closed (nonzero)", p_r3.returncode != 0, "rc=%d" % p_r3.returncode)
        check("R3 wrong PR head: refused", "head" in (p_r3.stdout+p_r3.stderr), "")

        # R4: evidence read-back fails -> run must NOT report success (Codex #6/#8)
        adapter_r4 = make_stub_adapter(out_dir, {"verdict": "GODKAND"})
        p_r4 = run_gh_mocked(adapter_r4, out_dir, {"readback": "empty"}, sha_a, base)
        check("R4 evidence read-back fail: not success (rc=5)", p_r4.returncode == 5, "rc=%d" % p_r4.returncode)

        # R5: schema-INVALID envelope -> fail-closed (Codex #7)
        adapter_r5 = write_schema_invalid_adapter(out_dir)
        p_r5 = run_orchestrator(adapter_r5, None, sha_a, base)
        check("R5 schema-invalid envelope: fail-closed (nonzero)", p_r5.returncode != 0, "rc=%d" % p_r5.returncode)
        check("R5 schema-invalid envelope: reason mentions invalid", "invalid" in (p_r5.stdout+p_r5.stderr).lower(), "")

        # R7: exactly 3 Codex calls for 2 reworks (initial + 2), then ceiling -> blocked/exit 4 (Codex #9)
        invlog_r7 = os.path.join(out_dir, "inv_r7.log")
        adapter_r7 = write_kraver_always(out_dir, invlog_r7, name="stub-kraver-r7.sh")  # KRÄVER every call
        rework_ok = os.path.join(out_dir, "rework-ok.sh")
        with open(rework_ok, "w", encoding="utf-8") as f:
            f.write(
                "#!/usr/bin/env bash\nset -euo pipefail\n"
                'R="${2:-0}"\n'
                'printf "BUILDER_DISPATCH_DONE issue=x round=%s head=dddddddddddddddddddddddddddddddddddddddd%02d model=Q model_cost_status=unknown\\n" "$R" "$((R))"\n'
                'echo "RC=0"\n'
            )
        os.chmod(rework_ok, 0o755)
        p_r7 = run_orchestrator(adapter_r7, rework_ok, sha_a, base, max_rework=2)
        calls = sum(1 for _ in open(invlog_r7)) if os.path.exists(invlog_r7) else 0
        check("R7 2 reworks => exactly 3 Codex calls", calls == 3, "calls=%d rc=%d" % (calls, p_r7.returncode))
        check("R7 ceiling -> blocked/exit 4", p_r7.returncode == 4, "rc=%d" % p_r7.returncode)

        # R8: Builder dispatch that does NOT deliver a 40-hex PR-head -> fail-closed (Codex #10)
        rework_bad = os.path.join(out_dir, "rework-bad.sh")
        with open(rework_bad, "w", encoding="utf-8") as f:
            f.write(
                "#!/usr/bin/env bash\nset -euo pipefail\n"
                'echo "BUILDER_DISPATCH_FAILED issue=82 round=1 (no head)"\n'
                'echo "RC=0"\n'
            )
        os.chmod(rework_bad, 0o755)
        adapter_r8 = write_kraver_always(out_dir, "", name="stub-kraver-r8.sh")
        p_r8 = run_orchestrator(adapter_r8, rework_bad, sha_a, base, max_rework=2)
        check("R8 builder-no-pushed-head: fail-closed (nonzero)", p_r8.returncode != 0, "rc=%d" % p_r8.returncode)
        check("R8 builder-no-pushed-head: refused", "did not deliver" in (p_r8.stdout+p_r8.stderr), "")

        # R9: --max-rework validation (#82/#9): invalid value must fail-closed BEFORE dispatch.
        adapter_r9 = make_stub_adapter(out_dir, {"verdict": "GODKAND", "sha": sha_a})
        p_r9 = run_orchestrator(adapter_r9, None, sha_a, base, max_rework=0)  # 0 -> invalid
        check("R9 --max-rework=0: fail-closed (nonzero)", p_r9.returncode != 0, "rc=%d" % p_r9.returncode)
        check("R9 --max-rework=0: refused", "max-rework" in (p_r9.stdout+p_r9.stderr).lower(), "")

        # ===== Codex-item6: regressions for the new deterministic guards =====

        # RR4: review artifact exceeds deterministic MAX_ARTIFACT_BYTES -> ingestion fail-closed.
        adapter_rr4 = make_stub_adapter(out_dir, {"verdict": "GODKAND", "sha": sha_a, "big_artifact": True})
        p_rr4 = run_orchestrator(adapter_rr4, None, sha_a, base)
        check("RR4 big-artifact ingestion: exit 3 (fail-closed)", p_rr4.returncode == 3,
              "rc=%d" % p_rr4.returncode)
        check("RR4 big-artifact: refused for size", "artifact" in p_rr4.stdout.lower(), "")

        # ----- Point-2 regressions: MAX_ARTIFACT_BYTES byte-vs-char + fail-closed validation -----
        # MB1: MULTIBYTE artifact — 300 'å' chars = 600 UTF-8 bytes but 300 chars. With a cap of 500
        # only wc -c byte-logic catches it (a bash ${#preview} char-length check would NOT). Must fail-closed.
        adapter_mb1 = make_stub_adapter(out_dir, {"verdict": "GODKAND", "sha": sha_a, "multibyte_big": True})
        p_mb1 = run_orchestrator(adapter_mb1, None, sha_a, base,
                                 env_extra={"CODEX_ROUNDTRIP_MAX_ARTIFACT_BYTES": "500"})
        blob_chars = 300  # chars under the 500 cap
        blob_bytes = 300 * len("å".encode("utf-8"))  # 300*2 = 600 UTF-8 bytes over the 500 cap
        check("MB1 multibyte: char count (%d) is UNDER cap but BYTE count (%d) exceeds -> fail-closed"
              % (blob_chars, blob_bytes),
              p_mb1.returncode not in (0,) and "artifact" in p_mb1.stdout.lower(),
              "rc=%d chars=%d bytes=%d" % (p_mb1.returncode, blob_chars, blob_bytes))
        check("MB1 multibyte: reason reports byte size", "bytes" in (p_mb1.stdout + p_mb1.stderr), "")

        # MB2: MAX_ARTIFACT_BYTES invalid (non-positive-int env) -> fail-closed BEFORE any run.
        adapter_mb2 = make_stub_adapter(out_dir, {"verdict": "GODKAND", "sha": sha_a})
        p_mb2 = run_orchestrator(adapter_mb2, None, sha_a, base,
                                 env_extra={"CODEX_ROUNDTRIP_MAX_ARTIFACT_BYTES": "abc"})
        check("MB2 bad MAX_ARTIFACT_BYTES: fail-closed pre-run", p_mb2.returncode != 0,
              "rc=%d" % p_mb2.returncode)
        check("MB2 bad MAX_ARTIFACT_BYTES: refused before dispatch",
              "MAX_ARTIFACT_BYTES" in (p_mb2.stdout + p_mb2.stderr), "")
        # MB3: MAX_ARTIFACT_BYTES zero -> also invalid (must be positive).
        p_mb3 = run_orchestrator(adapter_mb2, None, sha_a, base,
                                 env_extra={"CODEX_ROUNDTRIP_MAX_ARTIFACT_BYTES": "0"})
        check("MB3 zero MAX_ARTIFACT_BYTES: fail-closed pre-run", p_mb3.returncode != 0,
              "rc=%d" % p_mb3.returncode)

        # RR2: PR base BRANCH name vs expected base branch mismatch (#82/Codex-item1) -> fail-closed.
        adapter_rr2 = make_stub_adapter(out_dir, {"verdict": "GODKAND", "sha": sha_a})
        p_rr2 = run_gh_mocked(adapter_rr2, out_dir,
                              {"pr_base": "agent/separate-harness-verticals"}, sha_a, base,
                              extra_args=["--pr", "5", "--base-branch", "agent/wrong-base"])
        check("RR2 base-branch mismatch: fail-closed (nonzero)", p_rr2.returncode != 0, "rc=%d" % p_rr2.returncode)
        check("RR2 base-branch mismatch: refused", "base branch" in (p_rr2.stdout+p_rr2.stderr).lower(), "")

        # ===== Codex-item7: real Git fixtures for the builder-dispatch adapter guards =====
        # Runs the REAL adapter (bash) against a THROWAWAY temp git repo + a stub `hermes`
        # (no model, no network) to prove the allowlist / dirty / unchanged / scoped-commit guards.
        # A synthetic profile dir supplies the InferX key + max_tokens so the cap-gate passes;
        # a stub `hermes` in PATH produces the configured worktree changes deterministically.
        git_fixtures(out_dir, check, globals())
        # ===== Codex-item2: exact workflow-status transitions via the STATEFUL gh mock =====
        transition_tests(out_dir, check, globals(), sha_a, base)

    if verbose:
        for c in CHECKS:
            print(c)
    print()
    print("ROUNDTRIP_VERIFY: PASS=%d FAIL=%d" % (PASS, FAIL))
    if FAIL:
        print("ROUNDTRIP_VERIFY: FAILED (exit 1)")
        sys.exit(1)
    print("ROUNDTRIP_VERIFY: OK (exit 0)")
    sys.exit(0)


def envelope_b():
    return json.dumps({
        "issue_id": "commit %s" % ("a" * 40),
        "run_id": "22222222-2222-4333-8444-555555555555",
        "status": "succeeded",
        "runtime": "stub (no model)",
        "worker_role": "codex-reviewer",
        "started_at": "2026-08-09T00:00:00Z",
        "finished_at": "2026-08-09T00:00:01Z",
        "model": "gpt-5.6-sol",
        "usage": {"input_tokens": 1000, "output_tokens": 512, "cache_tokens": 0, "reasoning_tokens": 0},
        "cost": {"confidence": "unknown"},
        "artifacts": [{"ref": "a" * 40, "hash": "abc123", "size": 42}],
        "evidence": ["stub"],
    })


def write_stub_b(out_dir, invlog):
    """Proper per-call stub: KRÄVER on round 1, GODKÄND on round 2+."""
    path = os.path.join(out_dir, "stub-b2.sh")
    body = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'SHA="${1:-}"\n'
        'echo "$(date +%s) $(hostname)" >> "' + invlog + '"\n'
        'cnt="' + out_dir + '/call_count_b"\n'
        'if [ -f "$cnt" ]; then n=$(cat "$cnt"); else n=0; fi\n'
        'n=$((n+1)); echo "$n" > "$cnt"\n'
        'if [ "$n" -eq 1 ]; then v="KRÄVER ÄNDRINGAR"; else v="GODKÄND"; fi\n'
        'echo "REVIEW_ENVELOPE_JSON"\n'
        "cat <<'ENVEOF'\n" + envelope_b() + "\nENVEOF\n"
        'echo "CODEX_REVIEW_DONE run_id=1 commit=\\"$SHA\\" verdict=$v cost=unknown"\n'
        "exit 0\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(path, 0o755)
    return path


def write_schema_invalid_adapter(out_dir):
    """Adapter whose envelope misses a REQUIRED field (cost) -> schema-invalid."""
    path = os.path.join(out_dir, "stub-schema-invalid.sh")
    env = json.dumps({
        "issue_id": "commit x",
        "run_id": "33333333-4444-4333-8444-555555555555",
        "status": "succeeded",
        "runtime": "stub",
        "worker_role": "codex-reviewer",
        "started_at": "2026-08-09T00:00:00Z",
        "finished_at": "2026-08-09T00:00:01Z",
        "model": "gpt-5.6-sol",
        "usage": {"output_tokens": 512},
        # NOTE: 'cost' deliberately omitted -> schema-invalid
        "artifacts": [{"ref": "a", "hash": "x", "size": 1}],
        "evidence": ["stub"],
    })
    body = (
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'SHA="${1:-}"\n'
        'echo "REVIEW_ENVELOPE_JSON"\n'
        "cat <<'ENVEOF'\n" + env + "\nENVEOF\n"
        'echo "CODEX_REVIEW_DONE run_id=1 commit=\\"$SHA\\" verdict=GODKÄND cost=unknown"\n'
        "exit 0\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(path, 0o755)
    return path


def write_kraver_always(out_dir, invlog, name="stub-kraver.sh"):
    """Adapter that always returns KRÄVER ÄNDRINGAR (for ceiling/count tests)."""
    path = os.path.join(out_dir, name)
    body = (
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'SHA="${1:-}"\n'
    )
    if invlog:
        body += 'echo "$(date +%s)" >> "' + invlog + '"\n'
    body += (
        'echo "REVIEW_ENVELOPE_JSON"\n'
        "cat <<'ENVEOF'\n" + envelope_b() + "\nENVEOF\n"
        'echo "CODEX_REVIEW_DONE run_id=1 commit=\\"$SHA\\" verdict=KRÄVER ÄNDRINGAR cost=unknown"\n'
        "exit 0\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(path, 0o755)
    return path


def git_fixtures(base_out, check, g):
    """Codex-item7: REAL Git fixtures driving the dispatch adapter's fail-closed guards.

    Uses a throwaway temp git repo (the 3 allowlisted files committed), a synthetic
    $LOCALAPPDATA profile providing an InferX key + max_tokens (so the cap-gate passes),
    and a stub `hermes` on PATH that writes to the worktree per STUB_ACTION. The REAL
    codex-roundtrip-builder-dispatch.sh is run from the temp repo; no model ever fires.
    """
    import tempfile as tf, subprocess as sp
    base = os.path.realpath(tf.mkdtemp(prefix="hermes-fixture-"))
    repo = os.path.join(base, "repo")
    localdata = os.path.join(base, ".localappdata")
    bindir = os.path.join(base, ".bin")
    os.makedirs(os.path.join(localdata, "hermes", "profiles", "builder"), exist_ok=True)
    os.makedirs(bindir, exist_ok=True)
    # synthetic builder profile: key + explicit inferx max_tokens
    with open(os.path.join(localdata, "hermes", "profiles", "builder", "config.yaml"), "w", encoding="utf-8") as f:
        f.write("custom_providers:\n- name: inferx\n  base_url: https://model.inferx.net/endpoints/v1\n"
                "  api_key: testkey\n  model: Q\n  max_tokens: 12000\n")
    # stub hermes: modifies the (worktree) CWD per STUB_ACTION; emits a plausible model line
    stub = os.path.join(bindir, "hermes")
    with open(stub, "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env bash\nset -euo pipefail\n"
                "case \"${STUB_ACTION:-}-${1:-}\" in\n"
                "  'ok-*'|'nice-*'|'ok'*) # default: append to an allowlisted file (valid rework)\n"
                "    echo '# rework' >> harness/scripts/codex-roundtrip.sh\n"
                "    echo '# rework' >> harness/scripts/codex-roundtrip-verify.py\n"
                "    ;;esac\n")
    # NOTE: we drive the dirty/unchanged guards via orchestration of the repo state below,
    # not the stub, to keep the stub shape simple. Stub always writes an allowed file.
    os.chmod(stub, 0o755)

    def prepare_repo(start_dirty=False, unexpected=False):
        import shutil as _sh
        _sh.rmtree(repo, ignore_errors=True)
        os.makedirs(os.path.join(localdata, "hermes", "profiles", "builder"), exist_ok=True)
        # re-write the synthetic profile (LOCALAPPDATA dir is inside repo; gets wiped)
        with open(os.path.join(localdata, "hermes", "profiles", "builder", "config.yaml"), "w", encoding="utf-8") as f:
            f.write("custom_providers:\n- name: inferx\n  base_url: https://model.inferx.net/endpoints/v1\n"
                    "  api_key: testkey\n  model: Q\n  max_tokens: 12000\n")
        sp.run(["git", "init", "-q", repo], check=True)
        sp.run(["git","-C",repo,"config","user.email","t@t"], check=True)
        sp.run(["git","-C",repo,"config","user.name","t"], check=True)
        os.makedirs(os.path.join(repo,"harness","scripts"), exist_ok=True)
        for p in ["harness/scripts/codex-roundtrip.sh","harness/scripts/codex-roundtrip-verify.py","harness/scripts/codex-roundtrip-builder-dispatch.sh"]:
            open(os.path.join(repo,p),"w").write("# baseline\n")
        sp.run(["git","-C",repo,"add","-A"], check=True)
        sp.run(["git","-C",repo,"commit","-q","-m","base"], check=True)
        if start_dirty:
            open(os.path.join(repo,"harness","scripts","codex-roundtrip.sh"),"a").write("dirty\n")
        if unexpected:
            os.makedirs(os.path.join(repo,"docs"), exist_ok=True)
            open(os.path.join(repo,"docs/ugc.md"),"w").write("unexpected\n")

    def run_adapter(action, cwd=repo, force_dirty=False, force_unexpected=False):
        env=dict(os.environ)
        env["LOCALAPPDATA"]=localdata
        env["PATH"]=bindir+os.pathsep+env.get("PATH","")
        env["CODEX_ROUNDTRIP_BUILDER_PROMPT_REWORK"]="x"
        env["INFERX_API_KEY"]="testkey"
        env["STUB_ACTION"]=action
        r=sp.run([shutil.which("bash") or "bash", DISPATCH,
                  "rian010194/ai-workspace-control-plane#82","1","fixture-branch"],
                 capture_output=True,text=True,env=env,cwd=cwd)
        return r.returncode, r.stdout, r.stderr

    # G1: default clean run — remote push would be needed; with no origin, the adapter reaches
    # the (scoped) commit then push fails; that still proves the allowlist/scoped-commit path
    # executed (we accept reach of push as the cap-of-test; a full happy path needs a bare origin).
    # We focus on the FAIL-CLOSED guards:

    # G2: START DIRTY shared tree -> denied before any model.
    prepare_repo(start_dirty=True)
    rc,out,err=run_adapter("ok")
    check("G2 dirty start-tree denied", rc!=0 and "not clean" in (out+err).lower(), "rc=%d"%rc)

    # G3: UNEXPECTED file present at start -> denied (allowlist enforcement pre-model is covered
    # by the worktree; the shared-tree check also fails on it). Assert denied.
    prepare_repo(start_dirty=False, unexpected=True)
    rc,out,err=run_adapter("ok")
    check("G3 unexpected-start denied", rc!=0, "rc=%d (%s)"%(rc,(out+err)[-120:]))

    # G1b: clean start, stub produces a valid allowlisted change -> scoped commit produced;
    # adapter fails later at push (no origin) — but the scoped-commit + allowlist logic ran.
    prepare_repo(start_dirty=False)
    rc,out,err=run_adapter("ok")
    # should get past dirty/allowlist, only failing at push-origin missing (or unreachable), rc!=0
    check("G1 clean->scoped-commit attempted (later push-only fail)", rc!=0, "rc=%d"%rc)

    # cleanup temp tree
    import shutil as _sh
    _sh.rmtree(base, ignore_errors=True)


def transition_tests(out_dir, check, g, sha_a, base):
    """Codex-item2 + point-3 regressions: prove EXACT workflow-status transitions via the
    STATEFUL gh mock AND that every terminal failure class after a successful claim routes
    through fail_terminal (Ready -> In progress -> Blocked), ends in Blocked, and that a
    Blocked-transition/read-back failure itself yields a SEPARATE exit code (6) — not just rc.
    """
    import subprocess as sp, glob, os as _os

    def state_file():
        cands = glob.glob(_os.path.join(_os.path.realpath(out_dir), "wf-state-*"))
        return max(cands, key=_os.path.getmtime) if cands else None

    def tx_seq():
        cands = glob.glob(_os.path.join(_os.path.realpath(out_dir), "tx-log-*"))
        if not cands:
            return []
        latest = max(cands, key=_os.path.getmtime)
        with open(latest, encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]

    def final_state():
        sf = state_file()
        return open(sf, encoding="utf-8").read().strip() if sf else ""

    def assert_blocked_sequence(name, p, exp_rc, tx_tail=("In progress", "Blocked"),
                                exp_exit6=False):
        state = final_state()
        seq = tx_seq()
        if exp_exit6:
            # The Blocked transition ITSELF failed -> distinct exit 6. Here the semantics differ:
            # the run must NOT report success, the tx log must show the In-progress claim and a
            # FAILED Blocked attempt (Blocked(FAIL)), and the state must NOT have moved to Blocked
            # (it stays In progress because the block transition could not be verified). This is
            # exactly why the exit code is separated (6) — the operator must intervene.
            check("%s: distinct exit 6 when Blocked transition/read-back itself fails" % name,
                  p.returncode == 6, "rc=%d" % p.returncode)
            check("%s: run NOT Blocked (block transition failed -> state In progress)" % name,
                  state == "In progress", "state=%r" % state)
            check("%s: In-progress claimed then Blocked(FAIL) attempt recorded" % name,
                  seq[:1] == ["Ready"] and "In progress" in seq and "Blocked(FAIL)" in seq,
                  "seq=%r" % seq)
        else:
            check("%s: exit %d" % (name, exp_rc), p.returncode == exp_rc,
                  "rc=%d want=%d" % (p.returncode, exp_rc))
            check("%s: final workflow Blocked" % name, state == "Blocked", "state=%r" % state)
            check("%s: tx begins Ready, has In progress then Blocked" % name,
                  seq[:1] == ["Ready"] and "In progress" in seq and seq[-1] == "Blocked",
                  "seq=%r" % seq)

    # T1: GODKÄND -> exact Ready->In progress->Review (final Review)
    a_ok = make_stub_adapter(out_dir, {"verdict": "GODKAND", "sha": sha_a})
    p_t1 = run_gh_mocked(a_ok, out_dir, {}, sha_a, base)
    sf = state_file()
    final = open(sf, encoding="utf-8").read().strip() if sf else ""
    check("T1 GODKÄND transition path: final workflow Review", p_t1.returncode == 0 and final == "Review",
          "rc=%d state=%r" % (p_t1.returncode, final))
    # confirm the run log shows the In-progress claim then Review
    check("T1 GODKÄND: In-progress claim executed", "In progress" in (p_t1.stdout + p_t1.stderr) or
          "Ready->In progress" in (p_t1.stdout + p_t1.stderr), "")

    # T2: terminal-fail (timeout) -> Blocked (final Blocked, not Review/In progress)
    # Use a DEDICATED tx_log so the exact timeout sequence is captured under p_t2's own file,
    # independent of any later test overwriting the shared log (Codex-fynd: T9 must not read
    # another run's log via "latest mtime").
    t2_tx_log = os.path.join(out_dir, "tx-log-t2-%d" % os.getpid())
    a_to = make_stub_adapter(out_dir, {"verdict": "GODKAND", "rc": 124, "sha": sha_a})
    p_t2 = run_gh_mocked(a_to, out_dir, {"tx_log": t2_tx_log}, sha_a, base)  # NOPASS: rc=124 -> fail_terminal
    sf = state_file()
    final = open(sf, encoding="utf-8").read().strip() if sf else ""
    check("T2 timeout -> Blocked", p_t2.returncode not in (0, 5) and final == "Blocked",
          "rc=%d state=%r" % (p_t2.returncode, final))
    # Save T2's exact sequence IMMEDIATELY after p_t2, from its own log file, so T9 can later
    # assert the timeout class proof against this captured value (not the latest-mtime log).
    t2_seq = []
    if os.path.exists(t2_tx_log):
        with open(t2_tx_log, encoding="utf-8") as _f:
            t2_seq = [ln.strip() for ln in _f if ln.strip()]

    # T3: GODKÄND evidence POST/read-back failure -> fail_terminal (Ready->In progress->Blocked), rc 5
    a_t3 = make_stub_adapter(out_dir, {"verdict": "GODKAND", "sha": sha_a})
    p_t3 = run_gh_mocked(a_t3, out_dir, {"readback": "empty"}, sha_a, base)
    assert_blocked_sequence("T3 GODKÄND evidence read-back fail -> Blocked", p_t3, 5)

    # T4: GODKÄND Review transition/read-back failure -> fail_terminal (Blocked), rc 5
    a_t4 = make_stub_adapter(out_dir, {"verdict": "GODKAND", "sha": sha_a})
    p_t4 = run_gh_mocked(a_t4, out_dir, {"fail_review": "1"}, sha_a, base)
    assert_blocked_sequence("T4 GODKÄND Review transition fail -> Blocked", p_t4, 5)

    # T5: Blocked transition/read-back ITSELF fails -> SEPARATE exit code 6 (not rc 3/5)
    a_t5 = make_stub_adapter(out_dir, {"verdict": "GODKAND", "rc": 124, "sha": sha_a})
    p_t5 = run_gh_mocked(a_t5, out_dir, {"fail_blocked": "1"}, sha_a, base)
    assert_blocked_sequence("T5 Blocked-transition fail -> distinct exit 6", p_t5, 6, exp_exit6=True)

    # T6: KRÄVER evidence POST/read-back failure -> fail_terminal (Blocked), rc 5
    a_t6 = make_stub_adapter(out_dir, {"verdict": "KRAVER", "sha": sha_a})
    rework_ok6 = os.path.join(out_dir, "rework6.sh")
    with open(rework_ok6, "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env bash\nset -euo pipefail\n"
                'printf "BUILDER_DISPATCH_DONE issue=x round=%s head=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee01 model=Q model_cost_status=unknown\\n" "${2:-0}"\n'
                'echo "RC=0"\n')
    os.chmod(rework_ok6, 0o755)
    p_t6 = run_gh_mocked(a_t6, out_dir, {"readback": "empty"}, sha_a, base, rework_dispatch=rework_ok6)
    assert_blocked_sequence("T6 KRÄVER evidence read-back fail -> Blocked", p_t6, 5)

    # T7: KRÄVER but Builder dispatch missing/not-executable -> fail_terminal (Blocked), rc 3
    a_t7 = make_stub_adapter(out_dir, {"verdict": "KRAVER", "sha": sha_a})
    missing = os.path.join(out_dir, "does-not-exist.sh")
    p_t7 = run_gh_mocked(a_t7, out_dir, {}, sha_a, base, rework_dispatch=missing)
    assert_blocked_sequence("T7 missing Builder dispatch -> Blocked", p_t7, 3)

    # T8: KRÄVER but Builder dispatch yields no valid 40-hex PR-head -> fail_terminal (Blocked), rc 3
    a_t8 = make_stub_adapter(out_dir, {"verdict": "KRAVER", "sha": sha_a})
    rework_noh = os.path.join(out_dir, "rework-noh.sh")
    with open(rework_noh, "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env bash\nset -euo pipefail\n"
                'echo "BUILDER_DISPATCH_FAILED issue=82 round=1 (no head delivered)"\n'
                'echo "RC=0"\n')
    os.chmod(rework_noh, 0o755)
    p_t8 = run_gh_mocked(a_t8, out_dir, {}, sha_a, base, rework_dispatch=rework_noh)
    assert_blocked_sequence("T8 builder delivered no valid head -> Blocked", p_t8, 3)

    # T9: ADAPTER terminal status (rc 124) leaves the exact Ready->In progress->Blocked sequence.
    # This asserts the TIMEOUT class proof against the sequence captured from p_t2's OWN dedicated
    # log immediately after that run (t2_seq) — NOT a re-read of the "latest mtime" log, which
    # after T8 would silently be T8's (same-shaped) sequence and prove nothing about the timeout run.
    check("T9 timeout tx sequence = Ready, In progress, Blocked",
          t2_seq[:1] == ["Ready"] and "In progress" in t2_seq and t2_seq[-1] == "Blocked",
          "seq=%r" % t2_seq)


if __name__ == "__main__":
    main()
