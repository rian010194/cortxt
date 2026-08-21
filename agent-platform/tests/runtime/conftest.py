"""Docker tier gating for the Phase 3 sandbox boundary tests.

Docker is a real capability that is not available in every environment — the
same shape of problem Phase 2 had with cortxt_resilient_inference credentials.
Tests that need a live daemon are marked ``docker_required`` AND request the
``sandbox_image`` fixture, which skips with a loud, specific reason when the
daemon is unreachable. It never errors and never hangs: the probe has its own
timeout.

A skipped boundary test is NOT a passed boundary test. The container network
isolation tests are the actual proof of decision A4 and must be confirmed green
in an environment with a running daemon (Docker Desktop started on the dev
machine, or GitHub Actions' hosted Ubuntu runner) before Phase 3 can be called
proven. Mechanically written is not the same as verified — the exact lesson
PRs #146/#147 taught about Phase 2's real_inference tests.
"""
from __future__ import annotations

import pytest

from runtime.execution.subprocess_sandbox import SANDBOX_IMAGE_TAG, build_image, docker_available

_DOCKER_STATE: dict[str, bool] = {}


@pytest.fixture(scope="session")
def sandbox_image() -> str:
    if "available" not in _DOCKER_STATE:
        _DOCKER_STATE["available"] = docker_available()
    if not _DOCKER_STATE["available"]:
        pytest.skip(
            "Docker daemon is not reachable (`docker info` failed) — container "
            "boundary proof NOT verified in this environment. Start Docker "
            "Desktop, or rely on the CI docker tier."
        )
    if "built" not in _DOCKER_STATE:
        build_image()
        _DOCKER_STATE["built"] = True
    return SANDBOX_IMAGE_TAG
