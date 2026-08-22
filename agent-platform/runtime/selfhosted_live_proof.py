"""Run the read-only Vast.ai status and optional vLLM liveness live proof."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_AGENT_PLATFORM_ROOT = Path(__file__).resolve().parent.parent
if str(_AGENT_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_PLATFORM_ROOT))

from runtime.selfhosted_lifecycle import _VastAiControlAdapter  # noqa: E402
from runtime.selfhosted_liveness import LivenessSample, _LivenessHttpProbe  # noqa: E402

API_KEY_ENV = "CORTXT_SELFHOSTED_API_KEY"


def live_configuration() -> tuple[str, str | None]:
    """Return instance id and optional base URL, or raise without secret values."""
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    instance_id = os.environ.get("CORTXT_SELFHOSTED_INSTANCE_ID", "").strip()
    if not api_key or not instance_id:
        raise RuntimeError(
            "set CORTXT_SELFHOSTED_API_KEY and CORTXT_SELFHOSTED_INSTANCE_ID"
        )
    base_url = os.environ.get("CORTXT_SELFHOSTED_BASE_URL", "").strip() or None
    return instance_id, base_url


def content_free_evidence(
    status: str,
    sample: LivenessSample | None,
    elapsed_seconds: float,
) -> dict[str, Any]:
    """Summarize observations without credentials, endpoint data, or raw bodies."""
    return {
        "status": status,
        "alive": sample.alive if sample is not None else None,
        "vram_present": sample is not None and sample.vram_pct is not None,
        "queue_present": sample is not None and sample.queue_depth is not None,
        "elapsed_seconds": round(elapsed_seconds, 3),
    }


def run_live_proof(instance_id: str, base_url: str | None) -> dict[str, Any]:
    """Make only the read-only status and optional liveness requests."""
    started = time.monotonic()
    status = _VastAiControlAdapter(
        instance_id=instance_id, api_key_env=API_KEY_ENV
    ).status()
    sample = None
    if base_url is not None:
        sample = _LivenessHttpProbe(
            base_url=base_url, api_key_env=API_KEY_ENV
        ).check()
    return content_free_evidence(status, sample, time.monotonic() - started)


def main() -> int:
    try:
        instance_id, base_url = live_configuration()
        evidence = run_live_proof(instance_id, base_url)
    except Exception as error:
        # Report the type only: exception messages can contain endpoint details.
        print(json.dumps({"status": "error", "error_type": type(error).__name__}, sort_keys=True))
        return 1

    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] in {"running", "stopped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
