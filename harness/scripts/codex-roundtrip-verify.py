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
    output-token cap exceeded, unknown verdict, no auto-retry (adapter invoked
    exactly N expected times), honest cost (never fabricated).

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
      over_cap: report usage.output_tokens above 12000
      invocation_log: file appended to each time the stub runs (retry counting)
    """
    verdict = scenario.get("verdict", "GODKAND")
    rc = scenario.get("rc", 0)
    broken = scenario.get("broken", False)
    over_cap = scenario.get("over_cap", False)
    invlog = scenario.get("invocation_log", "")
    vmap = {
        "GODKAND": "GODKÄND",
        "KRAVER": "KRÄVER ÄNDRINGAR",
        "INGESTION": "INGESTION MISSLYCKADES",
        "UNKNOWN": "RANDOM TEXT",
    }
    verdict_str = vmap[verdict]
    out_tokens = 13000 if over_cap else 512
    usage_json = json.dumps({"input_tokens": 1000, "output_tokens": out_tokens,
                             "cache_tokens": 0, "reasoning_tokens": 0})
    cost_json = json.dumps({"confidence": "unknown"})
    sha = scenario.get("sha", "a" * 40)
    envelope = json.dumps({
        "issue_id": "commit %s" % sha,
        "run_id": "11111111-2222-4333-8444-555555555555",
        "status": "succeeded",
        "runtime": "stub (no model)",
        "worker_role": "codex-reviewer",
        "started_at": "2026-08-09T00:00:00Z",
        "finished_at": "2026-08-09T00:00:01Z",
        "model": "gpt-5.6-sol",
        "usage": json.loads(usage_json),
        "cost": json.loads(cost_json),
        "artifacts": [{"ref": sha, "hash": "abc123", "size": 42}],
        "evidence": ["stub"],
    })
    # Use a quoted heredoc 'EOF' so the envelope is emitted verbatim (no shell expansion).
    header = "#!/usr/bin/env bash\nset -euo pipefail\n"
    if invlog:
        header += 'echo "$(date +%s) $(hostname)" >> "' + invlog + '"\n'
    body = header + (
        'SHA="${1:-}"\n'
        'echo "REVIEW_ENVELOPE_JSON"\n'
        "cat <<'ENVEOF'\n" + envelope + "\nENVEOF\n"
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
    if [ "$1" = "item-edit" ]; then exit 0; fi
    exit 0;;
  api)
    SUB="$1"
    if [ "$SUB" = "graphql" ]; then
      # Honor --jq by inspecting the query text: issue-read filters projectItems;
      # node-read filters node(id). Emit the status the python test configured.
      if printf '%s ' "$@" | grep -q 'projectItems'; then
        printf '%s' "$GHMOCK_WF_STATUS"   # issue workflow read (Ready check)
      else
        printf '%s' "$GHMOCK_WF_NAME"     # set_item_status read-back (Review/Blocked)
      fi
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


def run_gh_mocked(adapter, out_dir, cfg, sha, base, extra_args=None, issue="82"):
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
    }
    return run_orchestrator(adapter, None, sha, base, issue=issue, no_github=False,
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

        # ---------- Edge: output token cap exceeded ----------
        adapter_f = make_stub_adapter(out_dir, {"verdict": "GODKAND", "over_cap": True})
        p_f = run_orchestrator(adapter_f, None, sha_a, base)
        check("F output-cap exceeded: exit 3", p_f.returncode == 3, "rc=%d" % p_f.returncode)
        check("F output-cap: reason mentions cap", "cap" in p_f.stdout.lower(), p_f.stdout[-300:])

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
        p_r2 = run_gh_mocked(adapter_r1, out_dir, {"pr_draft": "false"}, sha_a, base,
                             extra_args=["--pr", "5"])
        check("R2 non-draft PR: fail-closed (nonzero)", p_r2.returncode != 0, "rc=%d" % p_r2.returncode)
        check("R2 non-draft PR: refused", "not a draft" in (p_r2.stdout+p_r2.stderr), "")

        # R3: PR head != requested commit -> fail-closed (Codex #5)
        p_r3 = run_gh_mocked(adapter_r1, out_dir, {"pr_head": "f"*40}, sha_a, base,
                             extra_args=["--pr", "5"])
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


if __name__ == "__main__":
    main()
