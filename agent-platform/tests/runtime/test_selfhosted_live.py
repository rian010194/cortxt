"""Opt-in read-only live proof for Vast.ai status and vLLM liveness."""
from __future__ import annotations

import json
import os
import time

import pytest

from runtime.selfhosted_lifecycle import _VastAiControlAdapter
from runtime.selfhosted_live_proof import API_KEY_ENV, content_free_evidence
from runtime.selfhosted_liveness import _LivenessHttpProbe


@pytest.fixture
def selfhosted_live_configuration() -> tuple[str, str | None]:
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    instance_id = os.environ.get("CORTXT_SELFHOSTED_INSTANCE_ID", "").strip()
    if not api_key or not instance_id:
        pytest.skip(
            "self-hosted live arm not configured: set "
            "CORTXT_SELFHOSTED_API_KEY and CORTXT_SELFHOSTED_INSTANCE_ID"
        )
    base_url = os.environ.get("CORTXT_SELFHOSTED_BASE_URL", "").strip() or None
    return instance_id, base_url


@pytest.mark.real_inference
def test_vastai_live_status(
    selfhosted_live_configuration: tuple[str, str | None],
) -> None:
    instance_id, _ = selfhosted_live_configuration
    started = time.monotonic()

    status = _VastAiControlAdapter(
        instance_id=instance_id, api_key_env=API_KEY_ENV
    ).status()

    assert status in {"running", "stopped"}
    print(json.dumps(
        content_free_evidence(status, None, time.monotonic() - started),
        sort_keys=True,
    ))


@pytest.mark.real_inference
def test_vllm_live_liveness(
    selfhosted_live_configuration: tuple[str, str | None],
) -> None:
    instance_id, base_url = selfhosted_live_configuration
    if base_url is None:
        pytest.skip(
            "self-hosted liveness live arm not configured: set "
            "CORTXT_SELFHOSTED_BASE_URL (Vast.ai status proof remains available)"
        )
    started = time.monotonic()
    status = _VastAiControlAdapter(
        instance_id=instance_id, api_key_env=API_KEY_ENV
    ).status()
    sample = _LivenessHttpProbe(
        base_url=base_url, api_key_env=API_KEY_ENV
    ).check()

    assert isinstance(sample.alive, bool)
    assert sample.vram_pct is None or isinstance(sample.vram_pct, float)
    assert sample.queue_depth is None or isinstance(sample.queue_depth, int)
    print(json.dumps(
        content_free_evidence(status, sample, time.monotonic() - started),
        sort_keys=True,
    ))
