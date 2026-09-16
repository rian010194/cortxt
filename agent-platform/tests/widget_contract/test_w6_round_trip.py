"""W-6 round-trip contract: composed widget mandates through the dispatch gate.

Round-8 deliverable B for the W-6 development workstream (#501, refs #619).
The start-mission surface composes an ``issue-create`` mandate; ``ActionHost``
materialises it as an inbox Issue, the operator promotes it with the
registered mark-ready transition, and the dispatch projection turns the live
Issue into a claimable dispatch request.  These tests pin that round trip
closed through the host's real gates (compose writer, inbox->ready transition,
v2 projection, claim binding) -- never around them:

* composed-mandate round trip -- ``_bind_claim_run`` succeeds IFF the preview
  verdict is eligible AND the request id binds the payload digest
  (``approval_binds_digest``); any divergence is a failure;
* surface isolation -- the JavaScript renderer stays dependency-free with no
  launch-shaped vocabulary, and no surface action is ever routed to the cli
  launcher port;
* approval-parse parity -- the approval parser and the claim gate fail closed
  together on a pending-approval body, and the digest/stale/authorization
  categories stay distinct.

The composed mandate mirrors ``appRendererStartMission.composePayload``'s
output shape exactly (``action_id: "issue-create"`` + ``mandate`` +
``confirm: true``); the renderer's payload shape itself is exercised by the
node tests in ``test_s469_start_mission_flow.py``, so here it is mirrored as
data, not re-parsed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from widget.action_host import (
    ActionHost,
    AuthorizationFailure,
    DispatchDenied,
    StaleDispatchDenied,
)
from widget_contract.dispatch_request import approval_binds_digest

AGENT_PLATFORM_DIR = Path(__file__).resolve().parents[2]
RENDERER_PATH = AGENT_PLATFORM_DIR / "widget" / "app-renderer-start-mission.js"

REPO = "owner/repo"
TOKEN = "w6-round-trip-token"
APPROVAL_REF = "approval-w6-round-8"

POSITIVE_APPROVAL = (
    "Operator approved this exact scope, route, and limits for the W-6 round "
    "trip. Implementation start is approved for the worker in the isolated "
    "worktree."
)
PENDING_APPROVAL = "pending"


def _mandate_body(approval_line: str) -> str:
    """Eligible-issue body template (verified against test_action_host._claim_issue)."""
    return (
        "## Scope\n\n"
        "Round-trip a start-mission composed mandate through the live dispatch\n"
        "projection without touching neighbouring surfaces.\n\n"
        "## Deterministic acceptance criteria\n\n"
        "1. The claim gate admits exactly what the preview declares eligible.\n"
        "2. No surface action reaches the launcher port.\n\n"
        "## Approval status\n\n"
        f"{approval_line}\n\n"
        "## Worker role and limits\n\n"
        "- Workflow: work-launcher/v1.\n"
        "- Worker role: builder.\n"
        "- Max runtime: 1800 seconds.\n"
        "- Max cost: USD 8.00.\n"
        "- Max parallel workers: 1.\n"
        "- Delegation depth: 1.\n\n"
        "## Artifact policy\n\n"
        "Isolated worktree only.\n\n"
        "## Engine policy\n\n"
        "Reliability: unverified\n"
        "Engine: hermes-free\n"
    )


def _compose_payload(repo: str, title: str, body: str, labels: list[str]) -> dict:
    """Mirror of the renderer's composePayload shape (see module docstring)."""
    return {
        "action_id": "issue-create",
        "mandate": {"repo": repo, "title": title, "body": body, "labels": labels},
        "confirm": True,
    }


class _FakeIssueSurface:
    """issue_reader / issue_create_writer / label ports over an in-memory store."""

    def __init__(self) -> None:
        self.issues: dict[int, dict] = {}
        self.creates: list[dict] = []

    def create(self, repo, title, body, labels):
        """The compose effect: exactly one workflow:inbox label, caller labels kept."""
        number = 4600 + len(self.creates) + 1
        self.creates.append(
            {"repo": repo, "title": title, "body": body, "labels": list(labels)}
        )
        self.issues[number] = {
            "number": number,
            "title": title,
            "body": body,
            "labels": [{"name": str(x)} for x in labels] + [{"name": "workflow:inbox"}],
            "state": "open",
            "url": f"https://github.com/{repo}/issues/{number}",
            "milestone": None,
            "comments": [],
        }
        return {"issue_id": f"{repo}#{number}", "status": "ok"}

    def read(self, repo, number):
        issue = self.issues.get(number)
        return json.loads(json.dumps(issue)) if issue else None

    def labels(self, issue_id: str) -> list[str]:
        repo, number = issue_id.rsplit("#", 1)
        issue = self.issues.get(int(number))
        return [x["name"] for x in (issue or {}).get("labels", [])]

    def promote_to_ready(self, issue_id: str) -> dict:
        """The mark-ready effect: exactly the fixed inbox -> ready swap."""
        repo, number = issue_id.rsplit("#", 1)
        issue = self.issues[int(number)]
        workflow = [x["name"] for x in issue["labels"]
                    if str(x["name"]).lower().startswith("workflow:")]
        assert workflow == ["workflow:inbox"], f"not exactly workflow:inbox: {workflow}"
        kept = [x for x in issue["labels"]
                if not str(x["name"]).lower().startswith("workflow:")]
        issue["labels"] = kept + [{"name": "workflow:ready"}]
        return {"issue_id": issue_id, "status": "ok"}


def _make_host():
    surface = _FakeIssueSurface()
    host = ActionHost(
        issue_reader=surface.read,
        issue_create_writer=surface.create,
        labels_reader=surface.labels,
        transition_writer=surface.promote_to_ready,
        token=TOKEN,
    )
    return host, surface


def _compose_and_project(approval_text: str):
    """issue-create -> mark-ready -> authoritative v2 dispatch request."""
    host, surface = _make_host()
    payload = _compose_payload(
        repo=REPO,
        title="W-6 round trip: composed start-mission mandate",
        body=_mandate_body(approval_text),
        labels=["background-task"],
    )
    created = host.execute(
        action_id="issue-create",
        issue_id=f"{REPO}#0",
        approval_ref=APPROVAL_REF,
        confirm=True,
        token=TOKEN,
        mandate=payload["mandate"],
    )
    assert len(surface.creates) == 1, "issue-create must perform exactly one create"
    created_issue_id = created["result"]["issue_id"]
    assert created_issue_id == f"{REPO}#{next(iter(surface.issues))}"
    host.execute(
        action_id="mark-ready",
        issue_id=created_issue_id,
        approval_ref=APPROVAL_REF,
        confirm=True,
        token=TOKEN,
    )
    number = next(iter(surface.issues))
    request = host._build_dispatch_request(REPO, number)
    return host, surface, f"{REPO}#{number}", request


_GATE_DENIALS = (DispatchDenied, StaleDispatchDenied, AuthorizationFailure)


def _bind_admits(host, issue_id, approval_ref, request_id) -> bool:
    """True iff the live claim gate would admit this exact claim."""
    try:
        host._bind_claim_run(issue_id, approval_ref, request_id)
    except _GATE_DENIALS:
        return False
    return True


# ---------------------------------------------------------------------------
# A. Composed-mandate round trip: preview verdict == claim-gate verdict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("approval_text", [POSITIVE_APPROVAL, PENDING_APPROVAL],
                         ids=["positive-approval", "pending-approval"])
def test_composed_mandate_round_trip_gate_never_diverges_from_the_preview(
        approval_text):
    """_bind_claim_run succeeds IFF eligible AND the digest binding holds."""
    host, _surface, issue_id, request = _compose_and_project(approval_text)
    admitted = _bind_admits(
        host, issue_id, request["approval_reference"], request["request_id"])
    preview_admits = bool(request["eligible"]) and approval_binds_digest(
        request["request_id"], request)
    assert admitted is preview_admits, (
        "dispatch gate diverged from the preview verdict "
        f"(gate={admitted}, preview={preview_admits}, missing={request['missing']})"
    )


# ---------------------------------------------------------------------------
# B. Surface isolation: renderer stays dependency-free and off the launcher
# ---------------------------------------------------------------------------


def test_start_mission_renderer_is_dependency_free_and_launch_free():
    """The JS surface carries no require(), no claim-run vocabulary, and
    exactly the two action ids the flow declares (compose + mark-ready)."""
    source = RENDERER_PATH.read_text(encoding="utf-8")
    assert "require(" not in source, "renderer must not require() anything"
    assert "claim-run" not in source
    assert "data-launch-start" not in source
    ids = set(re.findall(r'action_id:\s*"([^"]+)"', source))
    assert ids == {"issue-create", "mark-ready"}
    # The three exported payload-shape functions s469 exercises by name.
    assert "composePayload: composePayload" in source
    assert "markReadyPayload: markReadyPayload" in source
    assert "renderPreview: renderPreview" in source


def test_registry_routes_only_claim_run_to_the_launcher_port():
    """issue-create and mark-ready stay on github-transition; only
    workflow.claim-run.v1 may reach the cli/launcher port."""
    host, _surface = _make_host()
    actions = host.capabilities()["actions"]
    ports = {a["operation"]: a["port"] for a in actions}
    assert ports["workflow.claim-run.v1"] == "cli"
    assert ports["github.issue-create.v1"] == "github-transition"
    assert ports["workflow.mark-ready.v1"] == "github-transition"
    launcher_routed = [op for op, port in ports.items() if port == "cli"]
    assert launcher_routed == ["workflow.claim-run.v1"], (
        f"a surface action reached the launcher port: {launcher_routed}"
    )


# ---------------------------------------------------------------------------
# C. Approval-parse parity: the parser and the gate fail closed together
# ---------------------------------------------------------------------------


def test_positive_approval_is_eligible_and_admitted_by_the_claim_gate():
    host, surface, issue_id, request = _compose_and_project(POSITIVE_APPROVAL)
    assert request["eligible"] is True, request["missing"]
    assert surface.issues[next(iter(surface.issues))]["labels"] == [
        {"name": "background-task"}, {"name": "workflow:ready"}]
    host._bind_claim_run(
        issue_id, request["approval_reference"], request["request_id"])


def test_pending_approval_is_ineligible_and_fails_closed_at_the_gate():
    host, _surface, issue_id, request = _compose_and_project(PENDING_APPROVAL)
    assert request["eligible"] is not True
    assert "approval_reference" in request["missing"]
    with pytest.raises(DispatchDenied) as exc:
        host._bind_claim_run(
            issue_id, request["approval_reference"], request["request_id"])
    assert exc.value.code == "dispatch_request_not_eligible"


def test_stale_request_id_is_refused_as_stale_not_denied():
    host, _surface, issue_id, request = _compose_and_project(POSITIVE_APPROVAL)
    with pytest.raises(StaleDispatchDenied):
        host._bind_claim_run(
            issue_id, request["approval_reference"], "stale-request-id")
    assert not approval_binds_digest("stale-request-id", request)
    assert approval_binds_digest(request["request_id"], request)


def test_forged_approval_reference_is_an_authorization_failure():
    host, _surface, issue_id, request = _compose_and_project(POSITIVE_APPROVAL)
    with pytest.raises(AuthorizationFailure):
        host._bind_claim_run(
            issue_id, APPROVAL_REF + "-forged", request["request_id"])
