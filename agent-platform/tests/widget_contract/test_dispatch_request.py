"""S7b (#471): dispatch-request projection and no-hardcoded-launcher wiring.

The primary fixture uses the real issue #471 Markdown format: ordered
``1.`` acceptance criteria, bulleted ``- Worker role:``-style limits, a
positive ``## Approval status``, and an explicit ``## Engine policy``.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from widget_contract.adapters.cli_ports import ClaimRunDenied, DispatchNotEligible, gh_claim_run_resume
from widget_contract.adapters.store_reads import read_dispatch_request_v1
from widget_contract.dispatch_request import build_dispatch_request_v1, parse_engine_policy
from widget_contract.registry import TYPES
from widget_contract.validation import validate

REPO = "owner/repo"

# The real #471 deterministic acceptance criteria, verbatim.
_REAL_ACS = [
    "Work exposes launch only for an eligible real Workstream whose complete mandate is authoritatively `workflow:ready`.",
    "The confirmation view matches the server-validated dispatch request byte-for-field; browser-supplied values cannot widen scope or limits.",
    "A confirmed action enters only through `workflow.claim-run.v1` and the execution-map-gated Work Launcher; tests prove no direct Dispatcher/UI bypass.",
    "Exactly one durable `run_id` and claim are created and GitHub moves `ready -> in-progress` through the existing path.",
    "Duplicate clicks, replay, another active Run, stale receipt, and label drift fail closed without a second launch.",
    "Routing choice and reason are visible. A cheap engine may be selected only when its declared task shape/reliability and the approved request permit it.",
    "Synthetic mode has no action capability and cannot reach `/api/action` successfully.",
    "Authorization, confirmation, same-origin, rate-limit, and approval-reference protections remain intact.",
    "Relevant launcher, dispatcher, action-host, widget-contract, and shell-core tests pass, plus conformance/build/syntax/parity/diff checks and desktop/narrow browser evidence.",
]

APPROVAL_TEXT = (
    "Operator approved this exact scope, route, and limits on 2026-08-30. "
    "Implementation start is approved for the worker in the isolated worktree."
)


def _issue(**overrides):
    issue = {
        "number": 471,
        "title": "Build: S7b — Operator launch from Work through the gated launcher",
        "body": (
            "Part of: #469\nBlocked by: #470\nWork kind: delivery\n\n"
            "## Scope\n\nMake a real `workflow:ready` Workstream launchable from the Work app "
            "without widening UI authority or creating a new dispatch path.\n\n"
            "## Deterministic acceptance criteria\n\n"
            + "\n".join(f"{i}. {ac}" for i, ac in enumerate(_REAL_ACS, start=1)) + "\n\n"
            "## Approval status\n\n" + APPROVAL_TEXT + "\n\n"
            "## Worker role and limits\n\n"
            "- Workflow: work-launcher/v1\n"
            "- Worker role: builder.\n"
            "- Max runtime: 5400 seconds.\n"
            "- Max cost: USD 8.00 hard ceiling; target <= USD 5.00.\n"
            "- Max parallel workers: 2, one writer only.\n"
            "- Delegation depth: 1.\n\n"
            "## Artifact policy\n\nIsolated worktree; approved source/tests/docs only; no secrets.\n\n"
            "## Engine policy\n\nReliability: unverified\nEngine: hermes-free\n"
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
    assert request["workflow_id"] == "work-launcher/v1"
    assert request["max_runtime_seconds"] == 5400
    assert request["max_cost_usd"] == 8.0
    assert request["max_parallel_workers"] == 2
    assert request["delegation_depth"] == 1
    assert request["missing"] == []
    assert request["errors"] == []


def test_real_issue_format_parses_ordered_acceptance_and_bulleted_limits():
    """Regression for the exact #471 Markdown format (review blocker 3)."""
    request = build_dispatch_request_v1(_issue(), _choice(), repo=REPO,
                                        engine_registered=True, routable_tags=["background-task"])
    assert request["acceptance_criteria"] == _REAL_ACS
    assert request["scope"].startswith("Make a real `workflow:ready` Workstream launchable")
    assert request["approval_reference"] == APPROVAL_TEXT
    assert request["max_runtime_seconds"] == 5400
    assert request["max_cost_usd"] == 8.0
    assert request["max_parallel_workers"] == 2
    assert request["delegation_depth"] == 1


def test_request_id_is_stable_for_identical_issue_and_changes_with_mandate():
    first = build_dispatch_request_v1(_issue(), _choice(), repo=REPO,
                                      engine_registered=True, routable_tags=["background-task"])
    second = build_dispatch_request_v1(_issue(), _choice(), repo=REPO,
                                       engine_registered=True, routable_tags=["background-task"])
    assert first["request_id"] == second["request_id"]
    assert first["request_id"].startswith("sha256:")

    changed = build_dispatch_request_v1(
        _issue(body=_issue()["body"].replace(APPROVAL_TEXT, "Operator approved a different scope on 2026-08-30.")),
        _choice(), repo=REPO, engine_registered=True, routable_tags=["background-task"])
    assert changed["request_id"] != first["request_id"]


def test_engine_policy_is_required_for_eligibility():
    issue = _issue(body=_issue()["body"].replace("## Engine policy\n\nReliability: unverified\nEngine: hermes-free\n", ""))
    request = build_dispatch_request_v1(issue, _choice(), repo=REPO,
                                        engine_registered=True, routable_tags=["background-task"])
    assert request["eligible"] is False
    assert "engine_policy" in request["missing"]
    assert any(e["code"] == "engine_policy" and e["recovery"] for e in request["errors"])


def test_engine_policy_rejects_unapproved_engine():
    issue = _issue(body=_issue()["body"].replace("Engine: hermes-free", "Engine: dsh"))
    request = build_dispatch_request_v1(issue, _choice(engine="hermes-free"), repo=REPO,
                                        engine_registered=True, routable_tags=["background-task"])
    assert request["eligible"] is False
    assert "engine_policy_unapproved" in request["missing"]


def test_engine_policy_reliability_verified_routes_away_from_unverified():
    """A mandate approving `verified` must not select an unverified engine,
    even when it is cheapest (review blocker 4)."""
    issue = _issue(body=_issue()["body"].replace("Reliability: unverified\nEngine: hermes-free\n",
                                                 "Reliability: verified\nEngine: claude-direct\n"))
    request = build_dispatch_request_v1(issue, _choice(engine="claude-direct"), repo=REPO,
                                        engine_registered=False, routable_tags=["background-task"])
    assert "engine_registered" in request["missing"]
    # The mandate-approved engine is what the confirmation view displays; its
    # provider is not yet registered (prerequisite PR #474), so it stays
    # fail-closed rather than falling back to an unapproved cheap engine.
    assert request["engine"] == "claude-direct"


def test_negated_approval_is_not_an_approval_reference():
    """The real #471 records 'Implementation start is not approved'; that must
    not count as an approval reference (review reproduction evidence)."""
    issue = _issue(body=_issue()["body"].replace(
        APPROVAL_TEXT, "Operator approved issue creation and planning on 2026-08-29. "
                       "**Implementation start is not approved.**"))
    request = build_dispatch_request_v1(issue, _choice(), repo=REPO,
                                        engine_registered=True, routable_tags=["background-task"])
    assert request["eligible"] is False
    assert "approval_reference" in request["missing"]


def test_missing_limits_render_not_eligible_with_missing_list():
    issue = _issue(body="## Scope\n\nOnly scope.\n", labels=[{"name": "workflow:ready"}])
    request = build_dispatch_request_v1(issue, _choice(), repo=REPO,
                                        engine_registered=True, routable_tags=["background-task"])
    assert request["eligible"] is False
    for code in ("acceptance_criteria", "approval_reference", "workflow", "worker_role",
                 "max_parallel_workers", "delegation_depth", "engine_policy"):
        assert code in request["missing"]
    # Every missing code has a stable category + recovery entry (AC5).
    assert {e["code"] for e in request["errors"]} == set(request["missing"])


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
                                        engine_registered=False, routable_tags=["background-task"])
    assert request["eligible"] is False
    assert "engine_registered" in request["missing"]


def test_parse_engine_policy_accepts_bulleted_and_plain_sections():
    assert parse_engine_policy("## Engine policy\n\nReliability: verified\nEngine: dsh\n") == {
        "approved_reliability": "verified", "approved_engine": "dsh"}
    assert parse_engine_policy("## Routing policy\n\n- Reliability: unverified\n- Engine: hermes-free\n") == {
        "approved_reliability": "unverified", "approved_engine": "hermes-free"}
    assert parse_engine_policy("## Scope\n\nNo policy here.\n") is None


class _FakeLauncher:
    def __init__(self):
        self.calls = []

    def resume(self, issue_id, *, runtime, worker_role, workflow, max_runtime_seconds,
               max_cost_usd, max_parallel_workers, delegation_depth, artifact_policy,
               request_id, prompt):
        self.calls.append({
            "issue_id": issue_id, "runtime": runtime, "worker_role": worker_role,
            "workflow": workflow, "max_runtime_seconds": max_runtime_seconds,
            "max_cost_usd": max_cost_usd, "max_parallel_workers": max_parallel_workers,
            "delegation_depth": delegation_depth, "artifact_policy": artifact_policy,
            "request_id": request_id, "prompt": prompt,
        })
        return {"issue_id": issue_id, "run_id": "run_1"}


def test_claim_run_resume_uses_projection_not_hardcoded_values():
    from routing.engine_manifest import EngineManifest
    from widget_contract.dispatch_request import build_dispatch_request_v1, route_for_issue

    manifests = (EngineManifest(engine_id="hermes-free", task_shapes=("background-task",),
                                cost_class="free", reliability_class="unverified"),)
    fake = _FakeLauncher()
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    # The confirmed request snapshot id is validated against the rebuilt
    # request, so derive it from the same server projection first.
    request = build_dispatch_request_v1(
        _issue(), route_for_issue(_issue(), manifests, "claude-direct")[0], repo=REPO,
        engine_registered=True, routable_tags=["background-task"])
    result = gh_claim_run_resume(
        "owner/repo#471",
        registry=Path("unused-runs.json"),
        scripts_dir=scripts_dir,
        issue_reader=lambda repo, number: _issue(),
        manifests=manifests,
        engine_has_provider=lambda engine_id: engine_id == "hermes-free",
        launcher=fake,
        approval_ref=APPROVAL_TEXT,
        request_id=request["request_id"],
    )
    assert result["run_id"] == "run_1"
    call = fake.calls[-1]
    assert call["runtime"] == "hermes-free"
    assert call["worker_role"] == "builder"
    assert call["workflow"] == "work-launcher/v1"
    assert call["max_runtime_seconds"] == 5400
    assert call["max_cost_usd"] == 8.0
    assert call["max_parallel_workers"] == 2
    assert call["delegation_depth"] == 1
    assert call["artifact_policy"]
    assert call["request_id"] == request["request_id"]
    assert call["runtime"] != "hermes-coordinator"


def test_claim_run_resume_rejects_not_eligible_without_launching():
    from routing.engine_manifest import EngineManifest

    manifests = (EngineManifest(engine_id="hermes-free", task_shapes=("background-task",),
                                cost_class="free", reliability_class="unverified"),)
    fake = _FakeLauncher()
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    with pytest.raises(DispatchNotEligible) as exc:
        gh_claim_run_resume(
            "owner/repo#471",
            registry=Path("unused-runs.json"),
            scripts_dir=scripts_dir,
            issue_reader=lambda repo, number: _issue(labels=[{"name": "workflow:inbox"}]),
            manifests=manifests,
            engine_has_provider=lambda engine_id: engine_id == "hermes-free",
            launcher=fake,
        )
    assert "workflow_ready" in exc.value.missing
    assert fake.calls == []


def test_claim_run_resume_rejects_mismatched_approval_and_stale_request():
    from routing.engine_manifest import EngineManifest
    from widget_contract.adapters.cli_ports import ApprovalMismatch, StaleDispatchRequest

    manifests = (EngineManifest(engine_id="hermes-free", task_shapes=("background-task",),
                                cost_class="free", reliability_class="unverified"),)
    fake = _FakeLauncher()
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    with pytest.raises(ApprovalMismatch):
        gh_claim_run_resume(
            "owner/repo#471", registry=Path("unused-runs.json"), scripts_dir=scripts_dir,
            issue_reader=lambda repo, number: _issue(), manifests=manifests,
            engine_has_provider=lambda engine_id: engine_id == "hermes-free",
            launcher=fake, approval_ref="someone-else-approves")
    with pytest.raises(StaleDispatchRequest):
        gh_claim_run_resume(
            "owner/repo#471", registry=Path("unused-runs.json"), scripts_dir=scripts_dir,
            issue_reader=lambda repo, number: _issue(), manifests=manifests,
            engine_has_provider=lambda engine_id: engine_id == "hermes-free",
            launcher=fake, approval_ref=APPROVAL_TEXT, request_id="sha256:stale")
    assert fake.calls == []
