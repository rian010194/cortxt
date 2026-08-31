"""S7d browser acceptance: preview navigation authority vs mutation authority.

Three blocking defects were found by browser acceptance at PR #488 head
54521db, and these tests pin the contract that closes them:

1. Cross-Workstream leakage. ``loadSynthetic`` fetched the single global
   ``fixtures/dispatch-request.json`` and ignored its ``issue`` argument, while
   ``renderRequest`` built the heading from ``x.id || req.issue_id``. Selecting
   WS-042 therefore rendered #471's dispatch request under a "WS-042" eyebrow:
   global fixture data relabelled with the selected Workstream's id.
2. The recovery journey was unreachable in preview mode, so an acceptance plan
   that claimed a locked ``recover-to-ready`` affordance was unsupported.
3. The launch view was orphaned: ``launchAvailable`` required a live action
   capability, so Work's primary control stayed "Open Decisions" even for an
   eligible ``workflow:ready`` Workstream, and ``#app=launch`` was reachable
   only by hand-editing the deep link.

The fix is a strict split. A synthetic fixture may carry a typed
per-Workstream ``next_action`` and read-only ``view_capabilities``
(``view:launch`` / ``view:recovery``) that authorize *navigating* to a
non-mutating preview. It must never carry an ``act:`` capability, an action
token, or an action endpoint. Every surface correlates its Issue, Run and
evidence references before rendering and fails closed on any mismatch.
"""
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
WIDGET = REPO_ROOT / "agent-platform" / "widget"
MIRROR = REPO_ROOT / "site" / "public" / "widgets"

JS = (WIDGET / "work-console.js").read_text(encoding="utf-8")
LAUNCH = (WIDGET / "app-renderer-work-launch.js").read_text(encoding="utf-8")
DECISIONS = (WIDGET / "app-renderer-decisions-evidence.js").read_text(encoding="utf-8")
WORKSTREAMS = json.loads((WIDGET / "fixtures" / "workstreams.json").read_text(encoding="utf-8"))
REQUEST = json.loads((WIDGET / "fixtures" / "dispatch-request.json").read_text(encoding="utf-8"))

BY_ID = {w["id"]: w for w in WORKSTREAMS["workstreams"]}


# --- fixture shape --------------------------------------------------------

def test_every_workstream_fixture_carries_a_correlatable_issue():
    """Correlation is impossible without an Issue: every fixture must carry
    one, and every Run/evidence reference must agree with it."""
    for ws in WORKSTREAMS["workstreams"]:
        assert ws["issue_id"], f"{ws['id']} has no issue_id"
        for run in ws.get("runs") or []:
            assert run.get("issue_id") == ws["issue_id"], f"{ws['id']} run {run.get('id')} is foreign"
        for item in ws.get("evidence") or []:
            assert item.get("issue_id") == ws["issue_id"], f"{ws['id']} evidence is foreign"


def test_synthetic_fixtures_never_grant_a_mutation_capability():
    """A fixture may authorize a view, never an act. No fixture may carry an
    action token or an ``act:`` capability of any kind."""
    blob = json.dumps(WORKSTREAMS)
    assert "act:" not in blob
    assert "token" not in blob.lower()
    for ws in WORKSTREAMS["workstreams"]:
        for capability in ws.get("view_capabilities") or []:
            assert capability.startswith("view:"), f"{ws['id']} grants {capability}"


def test_lifecycle_states_are_not_conflated_in_one_fixture():
    """Each lifecycle state gets its own Workstream: a ready launch example, a
    distinct stranded in-progress recovery example, and a review/decision
    example that carries no launch request."""
    ready, recover, decision = BY_ID["WS-048"], BY_ID["WS-051"], BY_ID["WS-042"]

    assert ready["workflow"] == "ready"
    assert ready["next_action"]["kind"] == "launch"
    assert ready["view_capabilities"] == ["view:launch"]

    assert recover["workflow"] == "in-progress"
    assert recover["next_action"]["kind"] == "recover"
    assert recover["view_capabilities"] == ["view:recovery"]
    assert [r["status"] for r in recover["runs"]] == ["conflict"]
    assert recover["id"] != ready["id"]

    assert decision["workflow"] == "review"
    assert decision["next_action"]["kind"] == "decision"
    assert decision["view_capabilities"] == ["view:decision"]
    assert "view:launch" not in decision["view_capabilities"]


# --- 1. Home -> Resume -> Work -> launch preview is navigable -------------

def test_eligible_ready_workstream_routes_from_work_to_launch_preview():
    """The eligible ready fixture reaches the launch preview through normal
    navigation: Work derives its primary control from the typed next action
    and opens the registered launch app with the Workstream context."""
    assert "function nextActionKind(x)" in JS
    assert 'primaryKind==="launch"' in JS
    assert "data-launch-run" in JS
    assert 'openDeep("launch")' in JS
    # Preview mode is authorized by the fixture's own view grant, not by a
    # live action capability.
    assert 'viewAuthorized(x, "view:launch")' in JS
    assert 'actAuthorized(s, "claim-run")' in JS


def test_launch_affordance_is_a_real_keyboard_control():
    """Navigation must be keyboard-reachable: the affordances are <button>
    elements with an explicit type, never click-only div handlers."""
    for marker in ("data-launch-run", "data-recover-ready"):
        assert f'<button type="button"' in JS and marker in JS
    # The disabled preview controls are still buttons, so focus order and
    # screen-reader semantics stay intact.
    assert 'data-launch-start-disabled disabled aria-disabled="true"' in LAUNCH
    assert 'data-r-recover-disabled class="chrome-button" disabled aria-disabled="true"' in DECISIONS


def test_primary_action_is_derived_from_the_typed_next_action():
    """launch -> launch label, recover -> recovery label, decision -> Decisions,
    and no authorized next action -> no mutation-oriented primary control."""
    assert 'primaryKind==="launch"' in JS
    assert 'primaryKind==="recover"' in JS
    assert 'primaryKind==="decision"' in JS
    assert "Review and start Run" in JS
    assert "Return to ready (recover)" in JS
    # An unauthorized kind degrades to no primary control, never to another
    # mutation.
    assert "if(primaryKind===\"launch\"&&!launchAvailable(s,x))primaryKind=null;" in JS
    assert "if(primaryKind===\"recover\"&&!recoveryAvailable(s,x))primaryKind=null;" in JS


# --- 2. the preview has no executable mutation boundary -------------------

def test_launch_preview_has_no_executable_mutation_in_synthetic_mode():
    """The preview shows where the boundary is and refuses to be it: the
    control is disabled, no handler is bound to it, and the only action POST
    stays on the live confirmed path."""
    assert "Requires live action host" in LAUNCH
    assert "data-launch-start-disabled" in LAUNCH
    # The click handler binds to the live control only.
    assert 'winEl.querySelector("[data-launch-start]")' in LAUNCH
    assert 'querySelector("[data-launch-start-disabled]")' not in LAUNCH
    # The static host has no mutation route at all.
    assert "do_POST" not in (WIDGET / "serve.py").read_text(encoding="utf-8")


def test_recovery_preview_is_reachable_but_not_executable():
    """Navigation to the recovery explanation is available in preview mode;
    the workflow mutation is not."""
    assert "function recoveryVisible(s, x)" in DECISIONS
    assert "function recoveryExecutable(s, x)" in DECISIONS
    assert 'viewAuthorized(x, "view:recovery")' in DECISIONS
    assert "Requires live action host" in DECISIONS
    # Executable recovery requires a live host AND the registered action.
    assert "!isSynthetic(s) && hasAction(s, \"recover-to-ready\")" in DECISIONS
    # The confirm dialog is bound only to the enabled control.
    assert 'querySelector("[data-r-recover]")' in DECISIONS
    assert 'querySelector("[data-r-recover-disabled]")' not in DECISIONS


# --- 3. an ineligible Workstream cannot reach launch ----------------------

def test_ineligible_workstream_cannot_open_launch_through_navigation():
    """Work offers no launch control unless the typed next action is `launch`
    and the Workstream is authoritatively ready."""
    assert 'x.workflow !== "ready" || nextActionKind(x) !== "launch"' in JS


def test_ineligible_workstream_cannot_open_launch_by_deep_link():
    """Even a hand-edited deep link fails closed: the renderer refuses before
    any dispatch request is fetched."""
    assert 'typed !== "launch"' in LAUNCH
    assert '(x.view_capabilities || []).indexOf("view:launch") === -1' in LAUNCH
    assert "no authorized launch" in LAUNCH
    # Within renderLaunch itself, the refusal returns before either loader is
    # called -- an ineligible Workstream causes no fetch at all.
    body = LAUNCH[LAUNCH.index("function renderLaunch(winEl, ctx)"):]
    body = body[:body.index("OSRenderer.register")]
    guard = body.index("This Workstream has no authorized launch")
    assert guard < body.index("loadSynthetic(")
    assert guard < body.index("loadLive(")
    assert "return;" in body[guard:body.index("loadSynthetic(")]


@pytest.mark.parametrize("ws_id", ["WS-042", "WS-039", "WS-031"])
def test_no_ineligible_fixture_grants_launch(ws_id):
    ws = BY_ID[ws_id]
    assert (ws.get("next_action") or {}).get("kind") != "launch"
    assert "view:launch" not in (ws.get("view_capabilities") or [])


# --- 5/6. cross-Workstream leakage fails closed ---------------------------

def test_request_must_correlate_to_the_selected_workstream():
    """The heading is no longer `x.id || req.issue_id`: a request whose Issue
    differs from the selected Workstream's renders nothing at all."""
    assert "x.issue_id !== req.issue_id" in LAUNCH
    assert "does not belong to the selected Workstream" in LAUNCH
    # The old relabelling expression is gone.
    assert "esc(x.id || req.issue_id)" not in LAUNCH


def test_ws042_can_never_render_the_launch_request():
    """WS-042 is the decision example and owns no launch request; the only
    dispatch-request fixture belongs to WS-048's Issue."""
    assert REQUEST["issue_id"] == BY_ID["WS-048"]["issue_id"]
    assert REQUEST["issue_id"] != BY_ID["WS-042"]["issue_id"]
    assert REQUEST["issue_id"] != "owner/repo#471"


def test_decisions_and_evidence_fail_closed_on_correlation_mismatch():
    assert "function correlated(x)" in DECISIONS
    assert "do not correlate" in DECISIONS
    assert "function correlated(x)" in JS
    assert "Correlation failed" in JS


def test_request_digest_matches_its_own_snapshot():
    """Re-pointing the fixture at WS-048's Issue must re-derive the digest,
    never leave a stale one that a confirmation could bind to."""
    import sys
    agent_platform = str(REPO_ROOT / "agent-platform")
    if agent_platform not in sys.path:
        sys.path.insert(0, agent_platform)
    from widget_contract.dispatch_request import _request_id

    assert REQUEST["request_id"] == _request_id(REQUEST)


# --- mirror parity --------------------------------------------------------

@pytest.mark.parametrize("name", [
    "work-console.js",
    "app-renderer-work-launch.js",
    "app-renderer-decisions-evidence.js",
    "fixtures/workstreams.json",
    "fixtures/dispatch-request.json",
])
def test_site_mirror_matches_canonical_source(name):
    assert (WIDGET / name).read_text(encoding="utf-8") == (MIRROR / name).read_text(encoding="utf-8")
