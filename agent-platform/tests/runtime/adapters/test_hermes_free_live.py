"""Opt-in live proof for the Hermes free-tier adapter."""
from __future__ import annotations

import json
import os

import pytest

from runtime.adapters.hermes_free_adapter import HermesFreeAdapter
from runtime.adapters.hermes_free_live_proof import content_free_evidence, live_configuration


@pytest.fixture
def hermes_free_live_route() -> tuple[str, str]:
    try:
        return live_configuration()
    except RuntimeError as error:
        pytest.skip(f"Hermes free live arm not configured: {error}")


@pytest.mark.real_inference
def test_hermes_free_live_response(hermes_free_live_route: tuple[str, str]) -> None:
    model, provider = hermes_free_live_route

    result = HermesFreeAdapter().invoke(
        profile="researcher",
        prompt="Reply with exactly: OK",
        timeout_seconds=120,
    )

    assert result["status"] == "succeeded"
    assert isinstance(result["stdout"], str) and result["stdout"].strip()
    assert result["elapsed_seconds"] > 0
    assert result["session_id"] is None or (
        isinstance(result["session_id"], str) and result["session_id"].strip()
    )
    configured_values = [
        value for name, value in os.environ.items() if name.startswith("CORTXT_FREE_") and value
    ]
    assert all(value not in result["stdout"] for value in configured_values)

    print(json.dumps(content_free_evidence(result, model, provider), sort_keys=True))
