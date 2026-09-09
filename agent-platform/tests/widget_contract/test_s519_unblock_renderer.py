"""W7 (#519): the unblock control's gates, driven rather than grepped.

The #469 review made the point these exist to answer: a test that scans a
renderer's source for a string literal passes while the behaviour is broken,
and it was exactly such a test that let a dead control ship. These gates decide
whether a *mutation* control is offered, so they are driven through node
against the real module.

They load the `agent-platform/widget` copy only. `site/package.json` declares
`"type": "module"`, so node treats the byte-identical mirror as ESM, where
`module.exports` never runs and `require` yields `{}`. The mirror carries these
properties through the byte-parity assertion at the end.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WIDGET = ROOT / "widget"
MIRROR = ROOT.parent / "site" / "public" / "widgets"
RENDERER = WIDGET / "app-renderer-decisions-evidence.js"
SITE_RENDERER = MIRROR / "app-renderer-decisions-evidence.js"

NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node unavailable")


def _run_node(script: str):
    return subprocess.run(["node", "-e", script], capture_output=True, text=True)


def _js(**cases) -> dict:
    script = "const d = require(%s);\nconst out = {};\n" % json.dumps(str(RENDERER))
    for name, expr in cases.items():
        script += "out[%s] = %s;\n" % (json.dumps(name), expr)
    script += "console.log(JSON.stringify(out));"
    out = _run_node(script)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# A Workstream whose Issue, Run and evidence references correlate -- the
# renderer refuses to offer anything at all on an uncorrelated one.
#
# It carries the server's typed `next_action`, because that is the only thing
# saying the run authority currently permits the action. The declared
# capability does not: `capabilities()` serves the widget spec's actions
# statically, so on a live host it is constant.
BLOCKED = ('{id:"WS-519", issue_id:"o/r#519", workflow:"blocked", '
           'next_action:{kind:"unblock", label:"Lift the block and return to ready"}, '
           'runs:[{run_id:"r1", issue_ref:"o/r#519"}], evidence:[]}')
IN_PROGRESS = (BLOCKED.replace('workflow:"blocked"', 'workflow:"in-progress"')
                      .replace('kind:"unblock"', 'kind:"recover"'))
READY = (BLOCKED.replace('workflow:"blocked"', 'workflow:"ready"')
                .replace('kind:"unblock"', 'kind:"launch"'))
# Blocked, but the server established no run authority: a corrupt session
# record, or an Issue blocked by triage that correlates no Run at all.
BLOCKED_NO_AUTHORITY = BLOCKED.replace(
    'next_action:{kind:"unblock", label:"Lift the block and return to ready"}, ',
    'next_action:null, ')

LIVE = ('{token:"t", model:{synthetic:false}, '
        'capabilities:[{id:"unblock-to-ready"},{id:"recover-to-ready"}]}')
LIVE_NO_UNBLOCK = '{token:"t", model:{synthetic:false}, capabilities:[{id:"recover-to-ready"}]}'

def test_the_control_is_offered_only_on_a_blocked_workstream():
    """`blocked` is the port's own precondition and it re-reads the label
    before writing, so offering the control anywhere else is an invitation to
    a refusal."""
    got = _js(blocked="d.unblockVisible(%s, %s)" % (LIVE, BLOCKED),
              in_progress="d.unblockVisible(%s, %s)" % (LIVE, IN_PROGRESS),
              ready="d.unblockVisible(%s, %s)" % (LIVE, READY))
    assert got["blocked"] is True
    assert got["in_progress"] is False
    assert got["ready"] is False


def test_holding_recovery_does_not_grant_unblock():
    """The two capabilities are separate by design. A host that registered
    only `recover-to-ready` must offer no unblock control at all."""
    got = _js(unblock="d.unblockVisible(%s, %s)" % (LIVE_NO_UNBLOCK, BLOCKED),
              recovery="d.recoveryVisible(%s, %s)" % (LIVE_NO_UNBLOCK, IN_PROGRESS))
    assert got["unblock"] is False
    assert got["recovery"] is True


def test_holding_unblock_does_not_grant_recovery():
    live_no_recover = '{token:"t", model:{synthetic:false}, capabilities:[{id:"unblock-to-ready"}]}'
    got = _js(unblock="d.unblockVisible(%s, %s)" % (live_no_recover, BLOCKED),
              recovery="d.recoveryVisible(%s, %s)" % (live_no_recover, IN_PROGRESS))
    assert got["unblock"] is True
    assert got["recovery"] is False


def test_preview_mode_explains_but_never_executes():
    """The #469 lesson applied here before it can bite: a control that preview
    mode cannot honour must not look executable. The section stays reachable so
    the operator can read what it would do, with an inert, disabled button."""
    preview = ('{model:{synthetic:true}, capabilities:[]}')
    blocked_granted = BLOCKED[:-1] + ', view_capabilities:["view:unblock"]}'
    got = _js(visible="d.unblockVisible(%s, %s)" % (preview, blocked_granted),
              executable="d.unblockExecutable(%s, %s)" % (preview, blocked_granted),
              html="d.unblockSection(%s, %s)" % (preview, blocked_granted))
    assert got["visible"] is True
    assert got["executable"] is False
    assert "disabled" in got["html"] and "data-u-unblock-disabled" in got["html"]
    assert "data-u-unblock class=" not in got["html"]


def test_a_preview_without_the_view_grant_offers_nothing():
    preview = '{model:{synthetic:true}, capabilities:[]}'
    got = _js(visible="d.unblockVisible(%s, %s)" % (preview, BLOCKED),
              html="d.unblockSection(%s, %s)" % (preview, BLOCKED))
    assert got["visible"] is False
    assert got["html"] == ""


def test_the_live_section_binds_a_real_control():
    got = _js(html="d.unblockSection(%s, %s)" % (LIVE, BLOCKED))
    assert "data-u-unblock class=" in got["html"]
    assert "disabled" not in got["html"]


def test_the_justification_minimum_matches_the_server():
    """The browser re-checks it so the operator is told before the request
    rather than by a refusal; the server's check stays the authority. If the
    two drift, the browser starts sending requests it knows will be denied."""
    from widget_contract.adapters.github_ports import MIN_UNBLOCK_JUSTIFICATION
    got = _js(minimum="d.MIN_UNBLOCK_JUSTIFICATION")
    assert got["minimum"] == MIN_UNBLOCK_JUSTIFICATION


# --- the degraded-store notice ---------------------------------------------

# Both carry the FULL live capability list, because that is what a live host
# always sends. A degraded fixture with `capabilities:[]` would prove the
# notice under a premise that never occurs in production -- and would pass
# just as happily while an executable control rendered beside it.
DEGRADED = ('{token:"t", model:{synthetic:false, store_health:{status:"degraded", '
            'withheld:["recover","unblock"], '
            'unreadable_records:[{record:"session_abc", message:"event hash is invalid"}]}}, '
            'capabilities:[{id:"unblock-to-ready"},{id:"recover-to-ready"}]}')
HEALTHY = ('{token:"t", model:{synthetic:false, store_health:{status:"ok", withheld:[], '
           'unreadable_records:[]}}, '
           'capabilities:[{id:"unblock-to-ready"},{id:"recover-to-ready"}]}')


def test_a_degraded_store_explains_the_missing_control_instead_of_showing_nothing():
    """The acceptance criterion's visible half. Without this the operator sees
    a blocked Workstream with no control and no reason, which reads as "there
    is nothing to do here" -- the opposite of what is true."""
    got = _js(html="d.unblockSection(%s, %s)" % (DEGRADED, BLOCKED_NO_AUTHORITY))
    assert "data-store-degraded" in got["html"]
    assert "session_abc" in got["html"], "the operator must be told which record to repair"
    assert "event hash is invalid" in got["html"]
    # It must not be mistaken for a statement about this Workstream's mandate.
    assert "not because this Workstream is ineligible" in got["html"]
    # And it must not smuggle in an executable control.
    assert "data-u-unblock class=" not in got["html"]


def test_the_notice_is_silent_on_a_healthy_store():
    got = _js(unblock='d.storeHealthNotice(%s, "unblock", %s)' % (HEALTHY, BLOCKED),
              recover='d.storeHealthNotice(%s, "recover", %s)' % (HEALTHY, IN_PROGRESS))
    assert got["unblock"] == ""
    assert got["recover"] == ""


def test_the_notice_only_speaks_for_the_affordances_actually_withheld():
    """`withheld` is the server's list. A notice that fired for an affordance
    the server did not withhold would be noise, and noise gets ignored."""
    partial = DEGRADED.replace('withheld:["recover","unblock"]', 'withheld:["recover"]')
    got = _js(unblock='d.storeHealthNotice(%s, "unblock", %s)' % (partial, BLOCKED),
              recover='d.storeHealthNotice(%s, "recover", %s)' % (partial, IN_PROGRESS))
    assert got["unblock"] == ""
    assert "data-store-degraded" in got["recover"]


def test_an_absent_store_health_field_renders_no_notice():
    """An older host that does not send the field must not produce a scary
    banner; it produces nothing, exactly as before."""
    got = _js(html='d.storeHealthNotice({model:{synthetic:false}}, "unblock", %s)' % BLOCKED)
    assert got["html"] == ""


def test_a_degraded_store_withholds_the_control_on_a_live_host():
    """The first of the two defects the independent review found.

    The gates read `hasAction`, and `capabilities()` serves the widget spec's
    actions statically -- so on any live host that check is always true. The
    control therefore rendered as executable next to the notice saying it was
    withheld: the operator was told the affordance was unavailable and handed
    it in the same breath. The server's authority, the typed `next_action`, is
    what has to decide, exactly as `work-console.js` has done since #498."""
    got = _js(visible="d.unblockVisible(%s, %s)" % (DEGRADED, BLOCKED_NO_AUTHORITY),
              recovery="d.recoveryVisible(%s, %s)" % (
                  DEGRADED, IN_PROGRESS.replace('kind:"recover"', 'kind:"__none__"')),
              html="d.unblockSection(%s, %s)" % (DEGRADED, BLOCKED_NO_AUTHORITY))
    assert got["visible"] is False, "a declared capability is not a live permission"
    assert got["recovery"] is False
    assert "data-store-degraded" in got["html"]
    assert "data-u-unblock class=" not in got["html"], \
        "the notice and an executable control must never render together"


def test_exactly_one_notice_renders_and_only_where_it_applies():
    """The second: the recover notice was emitted unconditionally in
    `renderDecisions`, so a blocked Workstream showed the same paragraph twice
    -- once for recover, once for unblock -- and a `ready` or `done` one showed
    it about a control that was never on offer there."""
    got = _js(
        blocked_recover='d.storeHealthNotice(%s, "recover", %s)' % (DEGRADED, BLOCKED_NO_AUTHORITY),
        blocked_unblock='d.storeHealthNotice(%s, "unblock", %s)' % (DEGRADED, BLOCKED_NO_AUTHORITY),
        ready_recover='d.storeHealthNotice(%s, "recover", %s)' % (DEGRADED, READY),
        ready_unblock='d.storeHealthNotice(%s, "unblock", %s)' % (DEGRADED, READY))
    # On a blocked Workstream only the unblock notice speaks.
    assert got["blocked_recover"] == ""
    assert "data-store-degraded" in got["blocked_unblock"]
    # On a Workstream where neither control was ever offered, neither speaks.
    assert got["ready_recover"] == ""
    assert got["ready_unblock"] == ""


def test_a_denial_that_is_not_json_still_reports_the_status():
    """The port's refusals reach the operator only through this channel.
    Parsing the body before checking `ok` replaced them with a JSON syntax
    error whenever the response was not JSON."""
    source = RENDERER.read_text(encoding="utf-8")
    # Scoped to this dialog's own body: `beginRecovery` and `beginDecision`
    # keep the older ordering, and asserting across the whole file would
    # silently measure theirs instead of this one.
    start = source.index("function beginUnblock(")
    body = source[start:source.index("function storeHealthNotice(", start)]
    # The response is read as text before `ok` is consulted, and a body that
    # is not JSON leaves `result` null rather than throwing.
    assert body.index("await response.text()") < body.index("if (!response.ok)")
    assert "JSON.parse(body)" in body
    assert "HTTP " in body, "a non-JSON denial must still name the status"


def test_site_mirror_is_byte_identical():
    assert RENDERER.read_bytes() == SITE_RENDERER.read_bytes()


# --- Work: the surface the operator actually starts from --------------------
#
# The independent review's first finding. `work-console.js` had no `unblock`
# branch at all: the typed next action rendered its LABEL ("Lift the block and
# return to ready") with no control underneath, and, because `primaryKind`
# stayed truthy, it also demoted the run-result button from the primary
# control to a secondary one. A blocked Workstream was told what to do and
# given nothing to do it with -- the dead-affordance shape of #469, reproduced
# in the surface that consumes the very field W7 added.

SHELL = WIDGET / "work-console.js"


def _shell(**cases) -> dict:
    script = "const m = require(%s);\nconst out = {};\n" % json.dumps(str(SHELL))
    for name, expr in cases.items():
        script += "out[%s] = %s;\n" % (json.dumps(name), expr)
    script += "console.log(JSON.stringify(out));"
    out = _run_node(script)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


WS_BLOCKED = ('{id:"WS-519", issue_id:"o/r#519", number:519, workflow:"blocked", '
              'next_action:{kind:"unblock", label:"Lift the block and return to ready"}, '
              'runs:[{run_id:"r1", issue_ref:"o/r#519"}], evidence:[]}')
WS_BLOCKED_NO_AUTHORITY = WS_BLOCKED.replace(
    'next_action:{kind:"unblock", label:"Lift the block and return to ready"}', 'next_action:null')
SHELL_LIVE = ('{model:{synthetic:false}, '
              'capabilities:[{id:"unblock-to-ready"},{id:"recover-to-ready"}]}')


def test_work_authorizes_the_unblock_affordance_it_advertises():
    """Work must have a gate for `unblock` at all. Without one the kind is
    unrecognised, no control is derived, and the label above it is a promise
    the surface cannot keep."""
    got = _shell(kind="m.nextActionKind(%s)" % WS_BLOCKED,
                 available="m.unblockAvailable(%s, %s)" % (SHELL_LIVE, WS_BLOCKED))
    assert got["kind"] == "unblock"
    assert got["available"] is True


def test_work_withholds_it_when_the_server_established_no_authority():
    """Same rule as every other affordance here: the typed kind is the
    server's answer, and its absence is a refusal, not an invitation."""
    got = _shell(available="m.unblockAvailable(%s, %s)" % (SHELL_LIVE, WS_BLOCKED_NO_AUTHORITY))
    assert got["available"] is False


def test_work_keeps_the_run_result_reachable_on_a_blocked_workstream():
    """#469's control must survive W7. A blocked Workstream's Run has already
    stopped, and reading what it did is how the operator decides whether to
    lift the block at all."""
    got = _shell(available="m.runResultAvailable(%s, false)" % WS_BLOCKED,
                 workflows="m.RUN_RESULT_WORKFLOWS")
    assert got["available"] is True
    assert "blocked" in got["workflows"]


def test_unblock_does_not_borrow_another_workstreams_authority():
    """The kinds are separate authorities, not a family. A `blocked`
    Workstream carrying a `recover` next action gets nothing, and vice
    versa."""
    crossed = WS_BLOCKED.replace('kind:"unblock"', 'kind:"recover"')
    in_progress = WS_BLOCKED.replace('workflow:"blocked"', 'workflow:"in-progress"')
    got = _shell(blocked_with_recover="m.unblockAvailable(%s, %s)" % (SHELL_LIVE, crossed),
                 in_progress_with_unblock="m.unblockAvailable(%s, %s)" % (SHELL_LIVE, in_progress))
    assert got["blocked_with_recover"] is False
    assert got["in_progress_with_unblock"] is False


def test_work_site_mirror_is_byte_identical():
    assert SHELL.read_bytes() == (MIRROR / "work-console.js").read_bytes()


# --- Work's rendered output, not just its gate ------------------------------
#
# The re-review's point: finding 1 was literally "a label with no control
# under it". That is the RENDERING, and a gate test cannot see it. These drive
# `renderWork` against a stub element -- it only assigns `innerHTML` and calls
# `querySelectorAll`, so a minimal stub is a faithful enough DOM.

STUB_EL = ("function stub(){return {innerHTML:\"\", querySelectorAll:function(){return []}, "
           "querySelector:function(){return null}};}")


def _render_work(state_js, ws_js) -> str:
    script = (
        "const m = require(%s);\n%s\n"
        "const el = stub();\n"
        "m.renderWork(el, {state: %s, workstream: %s});\n"
        "console.log(JSON.stringify({html: el.innerHTML}));"
        % (json.dumps(str(SHELL)), STUB_EL, state_js, ws_js))
    out = _run_node(script)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)["html"]


WS_FULL = WS_BLOCKED[:-1] + ', title:"T", outcome:"O", mandate:"M"}'
WS_FULL_NO_AUTHORITY = WS_BLOCKED_NO_AUTHORITY[:-1] + ', title:"T", outcome:"O", mandate:"M"}'


def test_work_renders_a_control_under_the_label_it_shows():
    """The regression itself. Before the fix this HTML contained the label and
    no control at all."""
    html = _render_work(SHELL_LIVE, WS_FULL)
    assert "Lift the block and return to ready" in html
    assert "data-unblock-open" in html, "the label must not be a promise with no control"
    # #469's control survives, and is not duplicated by a second route to it.
    assert "data-open-run-result" in html
    assert html.count('data-deep-open="decisions"') == 0, \
        "the primary already opens Decisions; a second button is noise"


def test_work_never_says_nothing_to_do_when_the_store_is_degraded():
    """Re-review finding: with the authority withheld there is no typed next
    action, so Work fell through to "No next action pending." -- asserting
    there is nothing to do on a Workstream whose only problem is that the
    evidence is unreadable. That is the silence the field exists to end, told
    by the first screen the operator reads."""
    degraded_shell = ('{model:{synthetic:false, status:"fresh", store_health:{status:"degraded", '
                      'withheld:["recover","unblock"], unreadable_records:[]}}, '
                      'capabilities:[{id:"unblock-to-ready"}]}')
    html = _render_work(degraded_shell, WS_FULL_NO_AUTHORITY)

    assert "No next action pending." not in html
    assert "data-work-store-degraded" in html
    assert "withheld until the store is repaired" in html
    # Still no control: explaining the refusal must not soften it.
    assert "data-unblock-open" not in html
    # And the run result stays reachable, which is how the operator decides.
    assert "data-open-run-result" in html


def test_a_healthy_store_with_nothing_to_do_still_says_so():
    """The notice must not fire where nothing is withheld, or it becomes
    wallpaper."""
    healthy = ('{model:{synthetic:false, status:"fresh", store_health:{status:"ok", '
               'withheld:[], unreadable_records:[]}}, capabilities:[]}')
    html = _render_work(healthy, WS_FULL_NO_AUTHORITY)
    assert "data-work-store-degraded" not in html
    assert "No next action pending." in html
