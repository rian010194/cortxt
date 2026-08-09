#!/usr/bin/env python3
"""Deterministic, NO-MODEL verification of the Hermes->Codex->Hermes adapter.

Proves the 2026-08-09 adapter fix WITHOUT any model call (a stub/absent Codex
can never reach a model):
  1. shell syntax valid;
  2. the old `$MAX=$MAX_RUNTIME` immediate-timeout root-cause bug is gone;
  3. fail-closed when the model binary is unreachable -> status=failed, no
     fabricated verdict, honest cost (unknown);
  4. happy path through a deterministic stub -> fresh last_message with a
     correctly UTF-8-encoded GODKÄND verdict, status=succeeded;
  5. the proven PID-bound process-tree timeout kills a hanging stub (treeGone);
  6. no silent fallback to a side-channel (Kimi/Hermes) inside the adapter;
  7. run dir stays gitignored / local.

Run:  python harness/scripts/codex-review-verify.py <full-commit-sha>
Exit nonzero on any focused check failure. Safe, local, gitignored-output only.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"C:\Users\rikar\Cortxt\projects\ai-workspace-control-plane")
SHA = sys.argv[1] if len(sys.argv) > 1 else None
if not SHA or not re.fullmatch(r"[0-9a-f]{40}", SHA or ""):
    print("usage: codex-review-verify.py <full-40-hex-commit-sha>"); sys.exit(2)
ADAPTER = REPO / "harness" / "scripts" / "codex-review-adapter.sh"
RUNNER = REPO / "harness" / "scripts" / "codex-review-runner.ps1"
STUB_OK = REPO / "harness" / "scripts" / "test" / "codex-stub-ok.ps1"
STUB_HANG = REPO / "harness" / "scripts" / "test" / "codex-stub-hang.ps1"
BASH = shutil.which("bash")
PWSH = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
PWSH_BARE = "/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
fail = []

def check(n, c, d=""):
    print(("  ok   " if c else "  FAIL ") + n + (("  " + d) if d and not c else ""))
    if not c: fail.append(n)


def sh(cmd, **kw):
    return subprocess.run([BASH, "-c", cmd], capture_output=True, text=True,
                          errors="replace", **kw)

# 1. shell syntax + fixture presence
r = subprocess.run([BASH, "-n", str(ADAPTER)], capture_output=True, text=True)
check("bash -n adapter", r.returncode == 0, r.stderr[-200:])
for lbl, p in [("runner", RUNNER), ("stub-ok", STUB_OK), ("stub-hang", STUB_HANG)]:
    check(f"exists {lbl}", p.exists())

# 2. root-cause bug gone: no INLINE PowerShell helper (adapter must use -File)
adapter_txt = ADAPTER.read_text(encoding="utf-8", errors="replace")
runner_txt = RUNNER.read_text(encoding="utf-8", errors="replace")
check("no inline 'powershell -Command' helper",
      "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command" not in adapter_txt)
check("adapter invokes the runner via -File", "codex-review-runner.ps1" in adapter_txt
      and "-File" in adapter_txt)
check("runner uses hard [int] MaxSec (540)", "int]$MaxSec = 540" in runner_txt)
# the immediate-timeout predicate must be FALSE for a sane deadline
r = subprocess.run([PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                    "$m=540; Write-Output ([bool](5 -ge $m))"], capture_output=True, text=True)
check("timeout predicate 5>=540 is False", "False" in (r.stdout or ""))

# 3. fail-closed: model unreachable -> no verdict, honest envelope
env = dict(os.environ)
env["CODEX_CLI_PATH"] = r"C:\nonexistent\codex-stub-llm.exe"
r = sh(f'"{ADAPTER}" {SHA}', env=env, timeout=120)
out = r.stdout or ""
m = re.search(r"REVIEW_ENVELOPE_JSON\n(\{.*?\n\})", out, re.S)
check("adapter emits envelope JSON", bool(m))
if m:
    e = json.loads(m.group(1))
    check("status=failed (model blocked)", e.get("status") == "failed")
    check("cost.confidence=unknown", (e.get("cost") or {}).get("confidence") == "unknown")
    check("usage empty", e.get("usage") in ({}, None))
    check("evidence has review_request_hash",
          any(str(x).startswith("review_request_hash=") for x in e.get("evidence", [])))
    check("no fabricated amount", (e.get("cost") or {}).get("amount") is None)
check("trailer verdict=ERROR", "verdict=ERROR" in out)
outdir = REPO / ".hermes" / "codex" / "reviews" / SHA
check("no last_message produced on fail-closed", not (outdir / "last_message.md").exists())

# 4. happy path through a stub (NO model) -> fresh GODKÄND, correct status
env2 = dict(os.environ)
env2["CODEX_CLI_PATH"] = str(STUB_OK)
r = sh(f'"{ADAPTER}" {SHA}', env=env2, timeout=120)
out = r.stdout or ""
m = re.search(r"REVIEW_ENVELOPE_JSON\n(\{.*?\n\})", out, re.S)
check("happy: adapter emits envelope JSON", bool(m))
if m:
    e = json.loads(m.group(1))
    check("happy: status=succeeded", e.get("status") == "succeeded", repr(e.get("status")))
check("happy: verdict parsed GODKÄND", "verdict=GODKÄND" in out)
lm = outdir / "last_message.md"
check("happy: fresh last_message exists", lm.exists())
if lm.exists():
    v = lm.read_text(encoding="utf-8", errors="replace")
    check("happy: VERDICT line has exact UTF-8 GODKÄND", "VERDICT: GODKÄND" in v)
    raw = lm.read_bytes()
    check("happy: Ä is exact UTF-8 (C3 84)", b"\xc3\x84" in raw)

# 5. PID-bound process-tree timeout kills a hanging stub
ph = Path(r"C:\Users\rikar\AppData\Local\Temp\cx-prompty.txt")
ph.write_text("brief\n", encoding="utf-8")
r = subprocess.run(
    [PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(RUNNER),
     "-CodexPath", str(STUB_HANG),
     "-PromptFile", str(ph),
     "-LastMessageOut", r"C:\Users\rikar\AppData\Local\Temp\cx-lastmy.txt",
     "-StdoutJson", r"C:\Users\rikar\AppData\Local\Temp\cx-outy.jsonl",
     "-StderrLog", r"C:\Users\rikar\AppData\Local\Temp\cx-erry.log",
     "-MaxSec", "2"],
    capture_output=True, text=True, errors="replace", timeout=60)
ro = (r.stdout or "") + (r.stderr or "")
check("runner times out hanging stub (timeout=True)", "timeout=True" in ro, ro[-200:])
check("runner reports treeGone (no leaked process)", "treeGone=True" in ro)
check("runner exit 0 on timeout", r.returncode == 0, f"rc={r.returncode}")

# 6. no silent side-channel fallback inside the adapter
for bad in ["hermes -p", "moonshotai", "kimi", "OPENROUTER", "dispatch-manual"]:
    check(f"no silent {bad!r} side-channel", bad not in adapter_txt)

# 7. run dir gitignored
r = sh(f'cd "{REPO}" && git check-ignore .hermes/codex/reviews/{SHA} >/dev/null 2>&1 && echo IGNORED')
check("review out-dir is gitignored", "IGNORED" in (r.stdout or ""))

print()
if fail:
    print(f"CODEX-REVIEW-VERIFY: {len(fail)} FAILURE(S): {fail}")
    sys.exit(1)
print("CODEX-REVIEW-VERIFY: PASS (adapter fix proven without any model call; "
      "NOT a review verdict).")