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
BLOCKED = ('{id:"WS-519", issue_id:"o/r#519", workflow:"blocked", '
           'runs:[{run_id:"r1", issue_ref:"o/r#519"}], evidence:[]}')
IN_PROGRESS = BLOCKED.replace('workflow:"blocked"', 'workflow:"in-progress"')
READY = BLOCKED.replace('workflow:"blocked"', 'workflow:"ready"')

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

DEGRADED = ('{model:{synthetic:false, store_health:{status:"degraded", '
            'withheld:["recover","unblock"], '
            'unreadable_records:[{record:"session_abc", message:"event hash is invalid"}]}}, '
            'capabilities:[]}')
HEALTHY = ('{model:{synthetic:false, store_health:{status:"ok", withheld:[], '
           'unreadable_records:[]}}, capabilities:[{id:"unblock-to-ready"}]}')


def test_a_degraded_store_explains_the_missing_control_instead_of_showing_nothing():
    """The acceptance criterion's visible half. Without this the operator sees
    a blocked Workstream with no control and no reason, which reads as "there
    is nothing to do here" -- the opposite of what is true."""
    got = _js(html="d.unblockSection(%s, %s)" % (DEGRADED, BLOCKED))
    assert "data-store-degraded" in got["html"]
    assert "session_abc" in got["html"], "the operator must be told which record to repair"
    assert "event hash is invalid" in got["html"]
    # It must not be mistaken for a statement about this Workstream's mandate.
    assert "not because this Workstream is ineligible" in got["html"]
    # And it must not smuggle in an executable control.
    assert "data-u-unblock class=" not in got["html"]


def test_the_notice_is_silent_on_a_healthy_store():
    got = _js(unblock='d.storeHealthNotice(%s, "unblock")' % HEALTHY,
              recover='d.storeHealthNotice(%s, "recover")' % HEALTHY)
    assert got["unblock"] == ""
    assert got["recover"] == ""


def test_the_notice_only_speaks_for_the_affordances_actually_withheld():
    """`withheld` is the server's list. A notice that fired for an affordance
    the server did not withhold would be noise, and noise gets ignored."""
    partial = DEGRADED.replace('withheld:["recover","unblock"]', 'withheld:["recover"]')
    got = _js(unblock='d.storeHealthNotice(%s, "unblock")' % partial,
              recover='d.storeHealthNotice(%s, "recover")' % partial)
    assert got["unblock"] == ""
    assert "data-store-degraded" in got["recover"]


def test_an_absent_store_health_field_renders_no_notice():
    """An older host that does not send the field must not produce a scary
    banner; it produces nothing, exactly as before."""
    got = _js(html='d.storeHealthNotice({model:{synthetic:false}}, "unblock")')
    assert got["html"] == ""


def test_site_mirror_is_byte_identical():
    assert RENDERER.read_bytes() == SITE_RENDERER.read_bytes()
