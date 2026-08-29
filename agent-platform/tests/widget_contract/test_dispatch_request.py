"""S7b (#471): dispatch-request projection and no-hardcoded-launcher wiring."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from widget_contract.adapters.cli_ports import ClaimRunDenied, gh_claim_run_resume
from widget_contract.adapters.store_reads import read_dispatch_request_v1
from widget_contract.dispatch_request import build_dispatch_request_v1
from widget_contract.registry import TYPES
from widget_contract.validation import validate

REPO = "owner/repo"


def _issue(**overrides):
    issue = {
        "number": 471,
        "title": "Build: S7b — Operator launch from Work through the gated launcher",
        "body": (
            "## Scope\n\nMake a workflow:ready Workstream launchable.\n\n"
            "## Deterministic acceptance criteria\n\n- AC one\n- AC two\n\n"
            "## Approval status\n\nOperator approved on 2026-08-29.\n\n"
            "## Worker role and limits\n\n"
            "Worker role: builder\nMax runtime: 5400 seconds\nMax cost: USD 8.00\n"
            "Max parallel workers: 2\nDelegation depth: 1\n\n"
            "## Artifact policy\n\nIsolated worktree only.\n\n"
        ),
        "state": "open",
        "labels": [{"name": "workflow:ready"}, {"name": "background-task"}],
        "url": f"https://github.com/{REPO}/issues/471",
        "milestone": None,
    }
    issue.update(overrides)
    return issue


def _choice(engine="hermes-free", reason="matched tag 'background-task'"):
    return SimpleNamespace(engine_id=engine, reason=reason)


def test_eligible_dispatch_request_is_schema_valid_with_projected_values():
    request = read_dispatch_request_v1(_issue(), _choice(), repo=REPO,
                                       engine_registered=True, routable_tags=["background-task"])
    validate(request, TYPES["dispatch.request.v1"].schema)
    assert request["eligible"] is True
    assert request["engine"] == "hermes-free"
    assert request["worker_role"] == "builder"
    assert request["max_runtime_seconds"] == 5400
    assert request["max_cost_usd"] == 8.0
    assert request["missing"] == []


def test_missing_limits_render_not_eligible_with_missing_list():
    issue = _issue(body="## Scope\n\nOnly scope.\n", labels=[{"name": "workflow:ready"}])
    request = build_dispatch_request_v1(issue, _choice(), repo=REPO,
                                        engine_registered=True, routable_tags=["background-task"])
    assert request["eligible"] is False
    assert "acceptance_criteria" in request["missing"]
    assert "approval_reference" in request["missing"]
    assert "worker_role" in request["missing"]


def test_workflow_mismatch_is_not_eligible():
    issue = _issue(labels=[{"name": "workflow:inbox"}, {"name": "background-task"}])
    request = build_dispatch_request_v1(issue, _choice(), repo=REPO,
                                        engine_registered=True, routable_tags=["background-task"])
    assert request["eligible"] is False
    assert "workflow_ready" in request["missing"]


def test_unroutable_issue_is_not_eligible():
    request = build_dispatch_request_v1(_issue(labels=[{"name": "workflow:ready"}]), None,
                                        repo=REPO, engine_registered=True, routable_tags=[])
    assert request["eligible"] is False
    assert "routable_task_tag" in request["missing"]
    assert "engine_routed" in request["missing"]


def test_unregistered_engine_is_not_eligible():
    request = build_dispatch_request_v1(_issue(), _choice(engine="claude-direct"), repo=REPO,
                                        engine_registered=False, routable_tags=["general"])
    assert request["eligible"] is False
    assert "engine_registered" in request["missing"]


class _FakeLauncher:
    def __init__(self):
        self.calls = []

    def resume(self, issue_id, *, runtime, worker_role, workflow, max_runtime_seconds, prompt):
        self.calls.append({
            "issue_id": issue_id, "runtime": runtime, "worker_role": worker_role,
            "workflow": workflow, "max_runtime_seconds": max_runtime_seconds, "prompt": prompt,
        })
        return {"issue_id": issue_id, "run_id": "run_1"}


def test_claim_run_resume_uses_projection_not_hardcoded_values():
    from routing.engine_manifest import EngineManifest

    manifests = (EngineManifest(engine_id="hermes-free", task_shapes=("background-task",),
                                cost_class="free", reliability_class="unverified"),)
    fake = _FakeLauncher()
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    result = gh_claim_run_resume(
        "owner/repo#471",
        registry=Path("unused-runs.json"),
        scripts_dir=scripts_dir,
        issue_reader=lambda repo, number: _issue(),
        manifests=manifests,
        engine_has_provider=lambda engine_id: engine_id == "hermes-free",
        launcher=fake,
    )
    assert result["run_id"] == "run_1"
    assert fake.calls[0]["runtime"] == "hermes-free"
    assert fake.calls[0]["worker_role"] == "builder"
    assert fake.calls[0]["max_runtime_seconds"] == 5400
    assert fake.calls[0]["runtime"] != "hermes-coordinator"


def test_claim_run_resume_rejects_not_eligible_without_launching():
    from routing.engine_manifest import EngineManifest

    manifests = (EngineManifest(engine_id="hermes-free", task_shapes=("background-task",),
                                cost_class="free", reliability_class="unverified"),)
    fake = _FakeLauncher()
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    with pytest.raises(ClaimRunDenied):
        gh_claim_run_resume(
            "owner/repo#471",
            registry=Path("unused-runs.json"),
            scripts_dir=scripts_dir,
            issue_reader=lambda repo, number: _issue(labels=[{"name": "workflow:inbox"}]),
            manifests=manifests,
            engine_has_provider=lambda engine_id: engine_id == "hermes-free",
            launcher=fake,
        )
    assert fake.calls == []
