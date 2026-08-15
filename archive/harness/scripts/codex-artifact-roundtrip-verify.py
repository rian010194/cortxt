#!/usr/bin/env python3
"""Deterministic, no-model checks for codex-artifact-roundtrip.sh."""
from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "harness" / "scripts" / "codex-artifact-roundtrip.sh"
_git_bash = pathlib.Path(r"C:\Program Files\Git\usr\bin\bash.exe")
BASH = str(_git_bash) if os.name == "nt" and _git_bash.exists() else (shutil.which("bash") or "bash")


def run(args: list[str], *, result: str = "VERDICT: GODKÄND\nFINDINGS: none\nKOSTNAD: unknown", extra=None):
    env = os.environ.copy()
    if os.name == "nt" and _git_bash.exists():
        env["PATH"] = str(_git_bash.parent) + os.pathsep + env.get("PATH", "")
    env.update({"CODEX_ARTIFACT_NO_GITHUB": "1", "CODEX_ARTIFACT_TEST_RESULT": result})
    if extra:
        env.update(extra)
    return subprocess.run([BASH, str(SCRIPT), *args], cwd=ROOT, env=env, text=True,
                          encoding="utf-8", errors="replace", capture_output=True)


def main() -> int:
    passes = 0
    with tempfile.TemporaryDirectory(dir=ROOT) as td:
        rel = pathlib.Path(td).relative_to(ROOT) / "artifact.md"
        path = ROOT / rel
        path.write_text("# planning artifact\n", encoding="utf-8")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        base = ["-i", "92", "-a", rel.as_posix(), "--sha256", sha]

        ok = run(base)
        assert ok.returncode == 0 and "ARTIFACT_REVIEW_DONE" in ok.stdout and sha in ok.stdout, ok.stderr
        passes += 1

        not_ready = run(base, extra={"CODEX_ARTIFACT_TEST_STATE": "Inbox"})
        assert not_ready.returncode != 0 and "not Ready" in not_ready.stderr
        passes += 1

        bad_hash = run(base[:-1] + ["0" * 64])
        assert bad_hash.returncode != 0 and "hash mismatch" in bad_hash.stderr
        passes += 1

        traversal = run(["-i", "92", "-a", "../outside.md", "--sha256", sha])
        assert traversal.returncode != 0 and "traversal-free" in traversal.stderr
        passes += 1

        cap = run(base, extra={"CODEX_ARTIFACT_MAX_BYTES": "1"})
        assert cap.returncode != 0 and "byte cap" in cap.stderr
        passes += 1

        invalid = run(base, result="VERDICT: INGESTION MISSLYCKADES")
        assert invalid.returncode != 0 and "invalid or failed review verdict" in invalid.stderr and "moving issue to Blocked" in invalid.stderr
        passes += 1

    print(f"codex-artifact-roundtrip-verify: {passes}/6 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
