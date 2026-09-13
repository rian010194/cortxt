#!/usr/bin/env python
"""Producer CI gate for the contract package (VLT-D-007 step 2, issue #604).

One PR-CI entry point that composes the two fail-closed checks:

1. ``export_contracts.py --check`` -- the packaged exports are congruent with
   the embedded production schemas (step 1 congruence, plus the worker pair's
   verbatim copy);
2. ``contract_version_gate.py`` -- the N/N-1 version policy against the
   latest ``contracts/vX.Y.Z`` tag (a contract change without a version bump
   is red; a MAJOR bump without a ``SUPPORTED_CONTRACT_VERSIONS`` extension is
   red).

Both scripts are read-only. This wrapper exists so CI names one command and
the failure output names the failing half.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"


def main(argv: list[str] | None = None) -> int:
    checks = (
        [sys.executable, str(SCRIPTS / "export_contracts.py"), "--check"],
        [sys.executable, str(SCRIPTS / "contract_version_gate.py")],
    )
    failed = False
    for command in checks:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            command,
            check=False,
            cwd=str(REPO_ROOT),
        )
        if completed.returncode != 0:
            failed = True
    if failed:
        print(
            "CONTRACT-GATE-RED: see DRIFT/GATE-RED lines above "
            "(a contract change requires a version bump per VLT-D-007 §3)"
        )
        return 1
    print("CONTRACT-GATE-GREEN: exports congruent and version policy satisfied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
