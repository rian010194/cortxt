"""work resume --request-file must verify the v2 dispatch digest (#571).

The verifier in cli/unified_cli.py historically re-derived the LEGACY v1
digest (`_request_id`) and therefore rejected every valid v2 dispatch
snapshot produced by the host/OS path and `widget_contract/adapters/
cli_ports.py`. These tests pin the v2 acceptance case (a real
`build_dispatch_request_v2` snapshot resumes) and the fail-closed case
(a tampered bound field is rejected).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

AGENT_PLATFORM_PATH = Path(__file__).parent.parent.parent
if str(AGENT_PLATFORM_PATH) not in sys.path:
    sys.path.insert(0, str(AGENT_PLATFORM_PATH))
# work_launcher lives in the clone-root scripts/ dir (the same path _run_work
# itself adds at runtime); mirror the proven pattern from
# widget_contract/test_s497_negative_arm_launch_contract.py so the module is
# importable/patchable before the CLI lazily imports it.
SCRIPTS = str(Path(__file__).resolve().parents[3] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from cli.unified_cli import _run_work
from widget_contract.dispatch_request import build_dispatch_request_v2

REPO = "owner/repo"

_BODY = (
    "## Scope\n\n"
    "Make a real `workflow:ready` Workstream launchable from Work.\n\n"
    "## Deterministic acceptance criteria\n\n"
    "1. Work exposes launch only for an eligible real Workstream.\n"
    "2. The confirmation view matches the server-validated dispatch request.\n\n"
    "## Approval status\n\n"
    "Operator approved this exact scope, route, and limits on 2026-09-10.\n\n"
    "## Worker role and limits\n\n"
    "- Workflow: work-launcher/v1\n"
    "- Worker role: builder.\n"
    "- Max runtime: 5400 seconds.\n"
    "- Max cost: USD 8.00 hard ceiling.\n"
    "- Max parallel workers: 2.\n"
    "- Delegation depth: 1.\n\n"
    "## Artifact policy\n\n"
    "Isolated worktree; approved `docs/agents` and `agent-platform/tests` only; no secrets.\n\n"
    "## Engine policy\n\n"
    "Reliability: unverified\n"
    "Engine: hermes-free\n"
)

PROVIDER = "nous"
MODEL = "upstage/solar-pro4:free"


def _v2_snapshot(**overrides):
    issue = {
        "number": 520,
        "title": "Build: v2 — bind approval to the execution configuration",
        "body": _BODY,
        "state": "open",
        "labels": [{"name": "workflow:ready"}, {"name": "background-task"}],
        "url": f"https://github.com/{REPO}/issues/520",
        "milestone": None,
    }
    choice = SimpleNamespace(engine_id="hermes-free", reason="matched tag 'background-task'")
    request = build_dispatch_request_v2(
        issue, choice, repo=REPO,
        engine_registered=True, routable_tags=["background-task"],
        provider=PROVIDER, model=MODEL)
    request.update(overrides)
    return request


class _FakeLauncher:
    def __init__(self):
        self.resume_calls = []

    def resume(self, issue_id, **kwargs):
        self.resume_calls.append({"issue_id": issue_id, **kwargs})
        return {"run_id": "run-test-1", "issue_id": issue_id}


def _make_args(request_file, registry):
    # v2 snapshots carry `issue_id` as "owner/repo#N" (the format the host
    # path and launcher.resume use end-to-end, cf. cli_ports.py:103).
    return argparse.Namespace(
        work_command="resume",
        issue_id="owner/repo#520",
        prompt="fallback prompt",
        runtime="hermes-coordinator",
        worker_role="builder",
        workflow="work-launcher/v1",
        max_runtime_seconds=600,
        request_file=request_file,
        isolate=False,
        registry=registry,
        repo=REPO,
        approve=True,
    )


def test_work_resume_accepts_a_valid_v2_dispatch_snapshot(tmp_path):
    import work_launcher

    request = _v2_snapshot()
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")

    fake = _FakeLauncher()
    args = _make_args(request_file, tmp_path / "runs.json")
    with patch("work_launcher.default_launcher", return_value=fake):
        envelope = _run_work(args)

    assert envelope.status == "succeeded", envelope.error
    assert envelope.run_id == "run-test-1"
    assert fake.resume_calls, "launcher.resume was not called"
    call = fake.resume_calls[0]
    # The approved v2 snapshot's own request_id is carried through to the run.
    assert call["request_id"] == request["request_id"]
    assert call["isolate"] is True
    # The worker is taught the versioned result-contract instruction, not the
    # raw fallback prompt (W6, #520).
    assert "builder" in call["prompt"] or "attest" in call["prompt"].lower()


def test_work_resume_rejects_a_snapshot_with_tampered_bound_field(tmp_path):
    """Fail-closed: a modified bound field must not pass the digest check."""
    import work_launcher

    request = _v2_snapshot()
    request["max_cost_usd"] = 999.0  # tamper a v2-bound field, keep request_id
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")

    fake = _FakeLauncher()
    args = _make_args(request_file, tmp_path / "runs.json")
    with patch("work_launcher.default_launcher", return_value=fake):
        envelope = _run_work(args)

    assert envelope.status == "failed"
    assert envelope.error["category"] == "work_error"
    assert "dispatch request digest does not match its snapshot" in envelope.error["message"]
    assert fake.resume_calls == []  # nothing launched on a rejected snapshot
