"""Run one opt-in Hermes free-route call and print content-free evidence."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

_AGENT_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(_AGENT_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_PLATFORM_ROOT))

from runtime.adapters.hermes_free_adapter import HermesFreeAdapter  # noqa: E402


def live_configuration() -> tuple[str, str]:
    """Return the configured route or raise with a credential-free message."""
    model = os.environ.get("CORTXT_FREE_MODEL", "").strip()
    provider = os.environ.get("CORTXT_FREE_PROVIDER", "").strip()
    if not model or not provider:
        raise RuntimeError("set CORTXT_FREE_MODEL and CORTXT_FREE_PROVIDER")
    if shutil.which("hermes") is None:
        raise RuntimeError("hermes CLI is not available on PATH")
    return model, provider


def content_free_evidence(result: dict[str, Any], model: str, provider: str) -> dict[str, Any]:
    """Summarize a result without prompt, credentials, or model output."""
    session_id = result.get("session_id")
    stdout = result.get("stdout")
    return {
        "status": result.get("status"),
        "model": model,
        "provider": provider,
        "elapsed_seconds": result.get("elapsed_seconds"),
        "session_id": "present" if isinstance(session_id, str) and session_id else "absent",
        "stdout_length": len(stdout) if isinstance(stdout, str) else 0,
    }


def main() -> int:
    try:
        model, provider = live_configuration()
    except RuntimeError as error:
        print(json.dumps({"status": "not_configured", "reason": str(error)}, sort_keys=True))
        return 1

    try:
        result = HermesFreeAdapter().invoke(
            profile="researcher",
            prompt="Reply with exactly: OK",
            timeout_seconds=120,
        )
    except Exception as error:  # The proof reports type only; exception text may contain output.
        print(json.dumps({"status": "error", "error_type": type(error).__name__}, sort_keys=True))
        return 1

    print(json.dumps(content_free_evidence(result, model, provider), sort_keys=True))
    return 0 if result.get("status") == "succeeded" and bool(result.get("stdout")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
