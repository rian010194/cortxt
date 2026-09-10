"""dispatch.request.v2 (S#520, design §2): approval bound to the execution config.

The v2 request digest binds the *semantic content* plus an immutable
`execution_profile_revision` (route engine, worker profile, provider, model,
isolation) and the report channel -- not identifiers alone. This module proves
the §2.4 contract deterministically:

- two requests with the same meaning produce the same digest;
- changing any bound field (model, provider, profile, route, limits, report
  channel, or semantic content) changes the digest;
- the operator's approval is recorded against the digest: a request whose
  digest differs from the approved digest is not treated as approved.
"""

from types import SimpleNamespace

import pytest

from routing.execution_profile import execution_profile, execution_profile_revision
from widget_contract.adapters.store_reads import read_dispatch_request_v2
from widget_contract.dispatch_request import (
    approval_binds_digest,
    build_dispatch_request_v2,
    request_digest_v2,
)
from widget_contract.registry import TYPES
from widget_contract.validation import validate

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
    "Isolated worktree; approved source/tests/docs only; no secrets.\n\n"
    "## Engine policy\n\n"
    "Reliability: unverified\n"
    "Engine: hermes-free\n"
)

PROVIDER = "nous"
MODEL = "upstage/solar-pro4:free"


def _issue(**overrides):
    issue = {
        "number": 520,
        "title": "Build: v2 — bind approval to the execution configuration",
        "body": _BODY,
        "state": "open",
        "labels": [{"name": "workflow:ready"}, {"name": "background-task"}],
        "url": f"https://github.com/{REPO}/issues/520",
        "milestone": None,
    }
    issue.update(overrides)
    return issue


def _choice(engine="hermes-free", reason="matched tag 'background-task'"):
    return SimpleNamespace(engine_id=engine, reason=reason)


def _v2(issue=None, choice=None, **kwargs):
    return build_dispatch_request_v2(
        issue or _issue(), choice or _choice(), repo=REPO,
        engine_registered=True, routable_tags=["background-task"],
        provider=kwargs.pop("provider", PROVIDER),
        model=kwargs.pop("model", MODEL),
        **kwargs)


def test_v2_is_schema_valid_and_carries_execution_profile():
    request = _v2()
    validate(request, TYPES["dispatch.request.v2"].schema)
    assert request["eligible"] is True
    assert request["schema_version"] == 2
    assert request["execution_profile_revision"].startswith("sha256:")
    assert request["report_channel"] == "issue-comment"
    assert request["request_id"].startswith("sha256:")


def test_v2_semantically_identical_requests_keep_the_same_digest():
    """§2.4: a semantically identical request keeps the same digest.

    Same issue, same resolved execution profile, same route/limits/channel --
    recomputed from separate reads -- must not drift.
    """
    first = _v2()
    second = _v2()
    assert first["request_id"] == second["request_id"]
    assert first["execution_profile_revision"] == second["execution_profile_revision"]
    # And the digest genuinely covers the bound field set: recomputing it from
    # the same payload yields the same id, not a new random one.
    assert request_digest_v2(first) == first["request_id"]


def test_v2_changing_bound_execution_field_changes_digest_and_revision():
    """§2.4: changing the resolved model -- a bound execution field -- changes
    both the execution_profile_revision and the request digest."""
    base = _v2()
    changed = _v2(model="deepseek-v4-flash-0731")
    assert changed["execution_profile_revision"] != base["execution_profile_revision"]
    assert changed["request_id"] != base["request_id"]


def test_v2_changing_provider_changes_digest():
    base = _v2()
    changed = _v2(provider="openai")
    assert changed["request_id"] != base["request_id"]


def test_v2_changing_worker_profile_changes_digest():
    """Changing the worker profile (role) is a bound profile change."""
    base = _v2()
    changed = _v2(issue=_issue(
        body=_BODY.replace("- Worker role: builder.", "- Worker role: researcher.")))
    assert changed["worker_role"] == "researcher"
    assert changed["request_id"] != base["request_id"]


def test_v2_changing_limit_changes_digest():
    """Changing a bound limit (max cost) changes the approval-relevant digest."""
    base = _v2()
    changed = _v2(issue=_issue(
        body=_BODY.replace("USD 8.00", "USD 12.00")))
    assert changed["max_cost_usd"] == 12.0
    assert changed["request_id"] != base["request_id"]


def test_v2_changing_report_channel_changes_digest():
    """Report channel is a bound field: changing it invalidates approval."""
    body = _BODY + "\n## Report channel\n\nwork-console\n"
    changed = _v2(issue=_issue(body=body))
    assert changed["report_channel"] == "work-console"
    assert changed["report_channel"] != _v2()["report_channel"]
    assert changed["request_id"] != _v2()["request_id"]


def test_v2_changing_semantic_content_changes_digest():
    """Semantic content is bound: a changed scope must not retain the old digest."""
    base = _v2()
    changed = _v2(issue=_issue(
        body=_BODY.replace(
            "Make a real `workflow:ready` Workstream launchable from Work.",
            "Make a different flow launchable.")))
    assert changed["request_id"] != base["request_id"]


def test_v2_approval_binds_digest_matching_and_differing():
    """§2.4 / §2: approval is recorded against the digest.

    A request whose digest equals the approved digest is approved; a request
    whose bound field changed (digest differs) is NOT approved, even though its
    approval_reference text still reads positive.
    """
    request = _v2()
    approved_id = request["request_id"]
    assert approval_binds_digest(approved_id, request) is True

    # Same approval text, but a different resolved model -> different digest.
    changed = _v2(model="deepseek-v4-flash-0731")
    assert changed["approval_reference"] == request["approval_reference"]
    assert approval_binds_digest(approved_id, changed) is False

    # No approved digest is never approved (fail closed).
    assert approval_binds_digest(None, request) is False


def test_execution_profile_revision_is_deterministic_and_sensitive():
    """The immutable execution profile revision is deterministic across the same
    configuration and changes when any bound execution field changes."""
    a = execution_profile_revision(execution_profile(
        engine_id="hermes-free", worker_role="builder",
        provider="nous", model="upstage/solar-pro4:free", isolation="worktree"))
    b = execution_profile_revision(execution_profile(
        engine_id="hermes-free", worker_role="builder",
        provider="nous", model="upstage/solar-pro4:free", isolation="worktree"))
    assert a == b
    c = execution_profile_revision(execution_profile(
        engine_id="hermes-free", worker_role="builder",
        provider="nous", model="deepseek-v4-flash-0731", isolation="worktree"))
    assert c != a


def test_v2_reader_validates_and_returns_projection():
    request = read_dispatch_request_v2(
        _issue(), _choice(), repo=REPO,
        routable_tags=["background-task"], provider=PROVIDER, model=MODEL)
    assert request["schema_version"] == 2
    assert request["execution_profile_revision"].startswith("sha256:")


def test_v2_stale_digest_rejected_at_launch_as_not_approved():
    """§2.4 end-to-end through the launch gate: an approval recorded against one
    execution configuration must not launch a request whose digest differs."""
    from widget_contract.adapters.cli_ports import StaleDispatchRequest, gh_claim_run_resume
    from routing.engine_manifest import EngineManifest
    from pathlib import Path

    class _FakeLauncher:
        def __init__(self):
            self.calls = []

        def resume(self, issue_id, **kwargs):
            self.calls.append((issue_id, kwargs))
            return {"issue_id": issue_id, "run_id": "run_v2"}

    manifests = (EngineManifest(engine_id="hermes-free", task_shapes=("background-task",),
                                cost_class="free", reliability_class="unverified"),)
    fake = _FakeLauncher()
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"

    # Approve against one execution configuration. Build the request from the
    # same routed choice the launch gate derives (route_for_issue), so the
    # routing_reason -- a bound field -- matches what the gate will recompute.
    from widget_contract.dispatch_request import build_dispatch_request_v2, route_for_issue
    routed_choice, _tags = route_for_issue(_issue(), manifests, fallback="claude-direct")
    approved = build_dispatch_request_v2(
        _issue(), routed_choice, repo=REPO, engine_registered=True,
        routable_tags=["background-task"], provider=PROVIDER, model=MODEL)
    approved_id = approved["request_id"]

    # At launch the resolved model differs -> the approved digest no longer
    # binds -> the launch is rejected as stale, no side effect.
    with pytest.raises(StaleDispatchRequest):
        gh_claim_run_resume(
            "owner/repo#520", registry=Path("unused-runs.json"), scripts_dir=scripts_dir,
            issue_reader=lambda repo, number: _issue(), manifests=manifests,
            engine_has_provider=lambda engine_id: engine_id == "hermes-free",
            launcher=fake, approval_ref=approved["approval_reference"],
            request_id=approved_id, request_version=2,
            provider=PROVIDER, model="deepseek-v4-flash-0731")
    assert fake.calls == []

    # A matching execution configuration launches.
    result = gh_claim_run_resume(
        "owner/repo#520", registry=Path("unused-runs.json"), scripts_dir=scripts_dir,
        issue_reader=lambda repo, number: _issue(), manifests=manifests,
        engine_has_provider=lambda engine_id: engine_id == "hermes-free",
        launcher=fake, approval_ref=approved["approval_reference"],
        request_id=approved_id, request_version=2,
        provider=PROVIDER, model=MODEL)
    assert result["run_id"] == "run_v2"
    assert fake.calls


# --- W11 (#542): charge policy revision + route bound into the request digest

def _charge_policy(**overrides):
    from routing.charge_policy import ChargePolicy
    base = dict(
        charge_policy_id="cp-nous-solar-pro4",
        charging="zero_charge",
        official_source="provider pricing, read 2026-09-10",
        read_date="2026-09-10",
        expiry="2026-12-10",
        route="zero_charge",
    )
    base.update(overrides)
    return ChargePolicy(**base)


def test_v2_without_charge_policy_carries_null_fields_and_stays_schema_valid():
    request = _v2()
    validate(request, TYPES["dispatch.request.v2"].schema)
    assert request["charge_policy_id"] is None
    assert request["charge_policy_revision"] is None
    assert request["charge_policy_route"] is None


def test_v2_with_charge_policy_is_schema_valid_and_binds_the_revision():
    request = _v2(charge_policy=_charge_policy())
    validate(request, TYPES["dispatch.request.v2"].schema)
    assert request["charge_policy_route"] == "zero_charge"
    assert request["charge_policy_revision"].startswith("sha256:")
    assert request_digest_v2(request) == request["request_id"]


def test_v2_adding_a_charge_policy_changes_the_request_digest():
    base = _v2()
    with_policy = _v2(charge_policy=_charge_policy())
    assert with_policy["request_id"] != base["request_id"]


def test_v2_rebinding_charge_policy_route_invalidates_prior_confirmation():
    """A route-binding change is a revision, not a silent mutation: the request
    digest changes, so an approval bound to the old digest is stale."""
    zero = _v2(charge_policy=_charge_policy(charging="zero_charge", route="zero_charge"))
    metered = _v2(charge_policy=_charge_policy(charging="metered", route="metered"))
    assert metered["charge_policy_revision"] != zero["charge_policy_revision"]
    assert metered["request_id"] != zero["request_id"]
    assert approval_binds_digest(zero["request_id"], metered) is False


def test_v2_charge_policy_content_change_changes_the_digest():
    base = _v2(charge_policy=_charge_policy())
    changed = _v2(charge_policy=_charge_policy(expiry="2027-06-01"))
    assert changed["request_id"] != base["request_id"]


def test_v2_identical_charge_policy_keeps_a_stable_digest():
    assert _v2(charge_policy=_charge_policy())["request_id"] == \
        _v2(charge_policy=_charge_policy())["request_id"]
