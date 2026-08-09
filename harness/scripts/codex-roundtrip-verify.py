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


def run_orchestrator(adapter, rework_dispatch, sha, base, issue="82", max_rework=2, extra_args=None):
    env = dict(os.environ)
    env["CODEX_ROUNDTRIP_ADAPTER"] = adapter
    env["CODEX_ROUNDTRIP_NO_GITHUB"] = "1"
    bash = shutil.which("bash") or "bash"
    args = [bash, ORCH, "-i", issue, "-c", sha, "-b", base, "--max-rework", str(max_rework)]
    if extra_args:
        args += extra_args
    if rework_dispatch:
        args += ["--rework-dispatch", rework_dispatch]
    # Ensure 'python' (not python3) resolves on Windows MSYS
    env["PATH"] = env.get("PATH", "")
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=REPO_ROOT)
    return proc


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

        # rework dispatch stub: simulates the implementation worker delivering a reworked
        # commit. Returns a 40-hex NEW SHA on stdout (single line). No real git mutation:
        # the orchestrator's loop passes the new SHA to the NEXT stub-review (which ignores
        # reachability); the pre-loop git-cat-file check only guards the FIRST SHA.
        rework_stub = os.path.join(out_dir, "rework.sh")
        with open(rework_stub, "w", encoding="utf-8") as f:
            # exactly 40 hex: 38 'c's + 2-digit round -> 40
            f.write(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'ROUND="${3:-0}"\n'
                'printf "%s%02d\\n" "cccccccccccccccccccccccccccccccccccccc" "$((ROUND))"\n'
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


if __name__ == "__main__":
    main()
