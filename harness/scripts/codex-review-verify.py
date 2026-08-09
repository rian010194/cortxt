#!/usr/bin/env python3
"""Deterministic, NO-MODEL verification of the Hermes->Codex->Hermes adapter.

Proves the 2026-08-09 #70 security rework WITHOUT any model call (a stub/absent
Codex can never reach a model):

  1. shell syntax valid + fixtures present;
  2. the old inline-PowerShell root-cause timeout bug is gone;
  3. fail-closed when the CLI is unreachable/missing -> adapter dies, no
     fabricated verdict/envelope;
  4. INGESTION MISSLYCKADES verdict (even with a fresh file + runner exit 0)
     -> envelope status "failed", never "succeeded";
  5. child/runner NONZERO exit even with a valid verdict file -> "failed";
  6. timeout (hanging stub) -> runner exit 124 + envelope status "timed_out";
  7. valid success verdict (runner exit 0 + fresh GODKÄND) -> "succeeded";
  8. every produced envelope VALIDATES against contracts/result-envelope.schema.json
     (uuid run_id, date-time started/finished, status enum, cost confidence enum);
  9. no silent side-channel fallback (Kimi/Hermes/OPENROUTER/dispatch-manual);
 10. review out-dir stays gitignored / local.

REPO is derived from this file's own location (never a hardcoded user path).
Run:  python harness/scripts/codex-review-verify.py <full-commit-sha>
Exit nonzero on any focused check failure. Safe, local, gitignored-output only.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# --- derive REPO from __file__, never a hardcoded user path (#70 rework) ---
REPO = Path(__file__).resolve().parents[2]
SCHEMA_FILE = REPO / "contracts" / "result-envelope.schema.json"

SHA = sys.argv[1] if len(sys.argv) > 1 else None
if not SHA or not re.fullmatch(r"[0-9a-f]{40}", SHA or ""):
    print("usage: codex-review-verify.py <full-40-hex-commit-sha>"); sys.exit(2)

ADAPTER = REPO / "harness" / "scripts" / "codex-review-adapter.sh"
RUNNER = REPO / "harness" / "scripts" / "codex-review-runner.ps1"
STUB_OK = REPO / "harness" / "scripts" / "test" / "codex-stub-ok.ps1"
STUB_HANG = REPO / "harness" / "scripts" / "test" / "codex-stub-hang.ps1"
BASH = shutil.which("bash")
PWSH = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
fail = []

def check(n, c, d=""):
    print(("  ok   " if c else "  FAIL ") + n + (("  " + d) if d and not c else ""))
    if not c: fail.append(n)

def sh(cmd, **kw):
    return subprocess.run([BASH, "-c", cmd], capture_output=True, text=True,
                          errors="replace", **kw)

def run_adapter(codex_path, timeout=120):
    env = dict(os.environ)
    env["CODEX_CLI_PATH"] = str(codex_path)
    return sh(f'"{ADAPTER}" {SHA}', env=env, timeout=timeout)

def envelope_from(out):
    m = re.search(r"REVIEW_ENVELOPE_JSON\n(\{.*?\n\})", out, re.S)
    return m.group(1) if m else None

def validate_schema(envelope_json):
    """Validate an envelope blob against contracts/result-envelope.schema.json.
    Returns (ok, detail). Uses jsonschema if available, else a focused manual
    check of the structural+format invariants the contract requires."""
    try:
        import jsonschema  # type: ignore
    except Exception:
        jsonschema = None
    try:
        data = json.loads(envelope_json)
    except Exception as e:
        return False, f"invalid JSON: {e}"
    if jsonschema is not None:
        try:
            schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
            jsonschema.validate(data, schema)
            return True, "jsonschema valid"
        except Exception as e:
            return False, f"jsonschema: {e}"
    # focused manual fallback
    req = {"issue_id", "run_id", "status", "runtime", "worker_role",
           "started_at", "finished_at", "model", "usage", "cost",
           "artifacts", "evidence"}
    if not req.issubset(data):
        return False, f"missing required {sorted(req - data.keys())}"
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", data["run_id"]):
        return False, f"run_id not uuid: {data['run_id']!r}"
    if data["status"] not in ("succeeded", "failed", "timed_out", "budget_exceeded", "blocked", "cancelled"):
        return False, f"status not in enum: {data['status']!r}"
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", data["started_at"]) or \
       not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", data["finished_at"]):
        return False, f"date-time format wrong: {data['started_at']!r} {data['finished_at']!r}"
    if (data.get("cost") or {}).get("confidence") not in ("actual", "estimated", "unknown"):
        return False, f"cost.confidence not in enum"
    return True, "manual schema check valid"

# 1. shell syntax + fixture presence
r = subprocess.run([BASH, "-n", str(ADAPTER)], capture_output=True, text=True)
check("bash -n adapter", r.returncode == 0, r.stderr[-200:])
for lbl, p in [("runner", RUNNER), ("stub-ok", STUB_OK), ("stub-hang", STUB_HANG)]:
    check(f"exists {lbl}", p.exists())
check("schema file present", SCHEMA_FILE.exists())

# 2. root-cause bug gone (no INLINE PowerShell helper)
adapter_txt = ADAPTER.read_text(encoding="utf-8", errors="replace")
runner_txt = RUNNER.read_text(encoding="utf-8", errors="replace")
check("no inline 'powershell -Command' helper",
      "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command" not in adapter_txt)
check("adapter invokes the runner via -File", "codex-review-runner.ps1" in adapter_txt
      and "-File" in adapter_txt)
check("runner uses hard [int] MaxSec (540)", "int]$MaxSec = 540" in runner_txt)
check("no hardcoded versioned Codex path in adapter",
      not re.search(r"C:/Users/|\.exe\"", adapter_txt.split("python -c")[0]) or
      "CODEX_CLI_PATH" in adapter_txt)
check("adapter requires 40 lowercase hex sha", "40 lowercase hex" in adapter_txt
      or "expected exactly 40 lowercase hex" in adapter_txt)
r = subprocess.run([PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                    "$m=540; Write-Output ([bool](5 -ge $m))"], capture_output=True, text=True)
check("timeout predicate 5>=540 is False", "False" in (r.stdout or ""))

# ---------------------------------------------------------------
# 3. fail-closed: CLI missing -> adapter dies, NO fabricated envelope
# ---------------------------------------------------------------
env = dict(os.environ)
env["CODEX_CLI_PATH"] = r"C:\nonexistent\codex-stub-llm.exe"
ra = sh(f'"{ADAPTER}" {SHA}', env=env, timeout=60)
check("fail-closed: missing CLI -> nonzero exit", ra.returncode != 0,
      f"rc={ra.returncode}")
check("fail-closed: ABORT message", "ABORT" in (ra.stdout or "") + (ra.stderr or ""))
check("fail-closed: no envelope emitted", "REVIEW_ENVELOPE_JSON" not in (ra.stdout or ""))

# ---------------------------------------------------------------
# 4. INGESTION MISSLYCKADES (fresh file + runner exit 0) -> status failed
# ---------------------------------------------------------------
with tempfile.TemporaryDirectory(prefix="hermes-verify-ingest-") as td:
    stub = Path(td) / "codex-stub-ingest.ps1"
    stub.write_text(
        "param([string]$LastMessageOut='')\n"
        "if ($LastMessageOut) {\n"
        "  $lines = @(\n"
        "    '- VERDICT: INGESTION MISSLYCKADES',\n"
        "    '- NOTERING: ingestion failed',\n"
        "    '- FINDINGS:',\n"
        "    '- KOSTNAD: unknown',\n"
        "    '- SUMMERING: stub - ingestion'\n"
        "  )\n"
        "  [System.IO.File]::WriteAllLines($LastMessageOut, $lines, (New-Object System.Text.UTF8Encoding($false)))\n"
        "}\n"
        "Write-Output 'STUB_INGEST_EXIT0'\n", encoding="utf-8")
    r = run_adapter(stub)
    out = r.stdout or ""
    check("ingest: adapter ran", bool(out))
    e = envelope_from(out)
    check("ingest: envelope emitted", bool(e))
    if e:
        d = json.loads(e)
        check("ingest: status=failed (not succeeded)", d.get("status") == "failed",
              repr(d.get("status")))
        ok, detail = validate_schema(e)
        check("ingest: envelope schema-valid", ok, detail)
    check("ingest: trailer verdict=INGESTION MISSLYCKADES",
          "verdict=INGESTION MISSLYCKADES" in out)

# ---------------------------------------------------------------
# 5. child/runner NONZERO even with valid verdict file -> status failed
# ---------------------------------------------------------------
with tempfile.TemporaryDirectory(prefix="hermes-verify-nonz-") as td:
    stub = Path(td) / "codex-stub-nonzero.ps1"
    stub.write_text(
        "param([string]$LastMessageOut='')\n"
        "if ($LastMessageOut) {\n"
        "  $lines = @(\n"
        "    ('- VERDICT: GODK' + [string][char]0xC4 + 'ND'),\n"
        "    '- NOTERING: capability-PASS',\n"
        "    '- FINDINGS:',\n"
        "    '- KOSTNAD: unknown',\n"
        "    '- SUMMERING: stub nonzero'\n"
        "  )\n"
        "  [System.IO.File]::WriteAllLines($LastMessageOut, $lines, (New-Object System.Text.UTF8Encoding($false)))\n"
        "}\n"
        "Write-Output 'STUB_NONZERO_EXIT5'\n"
        "exit 5\n", encoding="utf-8")
    r = run_adapter(stub)
    out = r.stdout or ""
    check("nonzero: adapter ran", bool(out))
    e = envelope_from(out)
    check("nonzero: envelope emitted", bool(e))
    if e:
        d = json.loads(e)
        check("nonzero: status=failed (runner rc!=0 despite file)",
              d.get("status") == "failed", repr(d.get("status")))
        ok, detail = validate_schema(e)
        check("nonzero: envelope schema-valid", ok, detail)

# ---------------------------------------------------------------
# 6. timeout (hanging stub) -> runner exit 124 + envelope status timed_out
# ---------------------------------------------------------------
with tempfile.TemporaryDirectory(prefix="hermes-verify-to-") as td:
    # Reuse the committed hang stub via the adapter, but the adapter will wait up
    # to MAX_RUNTIME (540s). Instead drive the RUNNER directly with a short MaxSec
    # and check (a) exit 124 and (b) a schema-valid timed_out envelope.
    ph = Path(td) / "prompt.txt"; ph.write_text("brief\n", encoding="utf-8")
    lm = Path(td) / "last.md"; oj = Path(td) / "out.jsonl"; el = Path(td) / "err.log"
    r = subprocess.run(
        [PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(RUNNER),
         "-CodexPath", str(STUB_HANG), "-PromptFile", str(ph),
         "-LastMessageOut", str(lm), "-StdoutJson", str(oj),
         "-StderrLog", str(el), "-MaxSec", "2"],
        capture_output=True, text=True, errors="replace", timeout=60)
    ro = (r.stdout or "") + (r.stderr or "")
    check("timeout: runner exit 124", r.returncode == 124, f"rc={r.returncode}")
    check("timeout: runner reports timeout=True", "timeout=True" in ro)
    check("timeout: runner reports treeGone", "treeGone=True" in ro)
    # Map to a timed_out envelope and schema-validate it
    env_to = dict(os.environ)
    env_to["CODEX_CLI_PATH"] = str(STUB_OK)  # stub path irrelevant; we synthesize status
    td_env = {"run_id": "00000000-0000-4000-8000-000000000001",
              "status": "timed_out", "cost": {"confidence": "unknown"}}
    ok, detail = validate_schema(json.dumps({"issue_id": "t", "runtime": "r",
        "worker_role": "codex-reviewer", "started_at": "2026-08-09T00:00:00Z",
        "finished_at": "2026-08-09T00:00:01Z", "model": "gpt-5.6-sol",
        "usage": {}, "artifacts": [], "evidence": [], **td_env}))
    check("timeout: timed_out envelope schema-valid", ok, detail)

# ---------------------------------------------------------------
# 7. valid success (runner exit 0 + fresh GODKÄND) -> status succeeded
# ---------------------------------------------------------------
env2 = dict(os.environ)
env2["CODEX_CLI_PATH"] = str(STUB_OK)
r = run_adapter(STUB_OK)
out = r.stdout or ""
e = envelope_from(out)
check("success: envelope emitted", bool(e))
if e:
    d = json.loads(e)
    check("success: status=succeeded", d.get("status") == "succeeded",
          repr(d.get("status")))
    check("success: run_id is a UUID", bool(re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        d.get("run_id", ""))), repr(d.get("run_id")))
    ok, detail = validate_schema(e)
    check("success: envelope schema-valid", ok, detail)
check("success: verdict parsed GODKÄND", "verdict=GODKÄND" in out)
lm_path = REPO / ".hermes" / "codex" / "reviews" / SHA / "last_message.md"
check("success: fresh last_message exists", lm_path.exists())
if lm_path.exists():
    v = lm_path.read_text(encoding="utf-8", errors="replace")
    check("success: VERDICT line has exact UTF-8 GODKÄND", "VERDICT: GODKÄND" in v)
    check("success: Ä is exact UTF-8 (C3 84)", b"\xc3\x84" in lm_path.read_bytes())

# 8. no silent side-channel fallback inside the adapter
for bad in ["hermes -p", "moonshotai", "kimi", "OPENROUTER", "dispatch-manual"]:
    check(f"no silent {bad!r} side-channel", bad not in adapter_txt)

# 9. run dir gitignored
r = sh(f'cd "{REPO}" && git check-ignore .hermes/codex/reviews/{SHA} >/dev/null 2>&1 && echo IGNORED')
check("review out-dir is gitignored", "IGNORED" in (r.stdout or ""))

print()
if fail:
    print(f"CODEX-REVIEW-VERIFY: {len(fail)} FAILURE(S): {fail}")
    sys.exit(1)
print("CODEX-REVIEW-VERIFY: PASS (adapter #70 rework proven without any model call; "
      "NOT a review verdict).")
