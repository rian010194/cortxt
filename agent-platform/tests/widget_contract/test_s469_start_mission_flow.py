"""#469: "Start a mission" is the first step of the Work flow.

Before this app existed, every "New Workstream" control on Home and Work
emitted `OSRenderer.emit("command", {command:"create-workstream"})` and
nothing subscribed to the `command` event -- three buttons on two surfaces
did nothing at all when clicked. This suite covers two separable things:

  1. the dead-button regression itself -- a handler now exists for
     `create-workstream` and something now listens on the `command` bus;
  2. the new app's own contract -- `app-renderer-start-mission.js` groups
     missions by demand on the operator, never invents a "ready" state for
     a mission it cannot read, and is honest about what preview/stale data
     means for what can be started.

These are source-level and behavioral contract tests over the renderer, in
the same style as the rest of the widget suite: the JS is served as a
static asset, so where a real behavioral assertion is possible the renderer
is driven through `node` in a DOM-less stub; everything else is asserted
against source text the same way test_s469_terminal_outcome_language.py
does.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WIDGET = ROOT / "widget"
MIRROR = ROOT.parent / "site" / "public" / "widgets"

RENDERER = WIDGET / "app-renderer-start-mission.js"
SHELL = WIDGET / "work-console.js"
APPS = WIDGET / "apps.json"
INDEX = WIDGET / "index.html"
SITE_INDEX = MIRROR / "index.html"
SITE_RENDERER = MIRROR / "app-renderer-start-mission.js"
SITE_SHELL = MIRROR / "work-console.js"

NODE = shutil.which("node")


@pytest.fixture(scope="module")
def source() -> str:
    return RENDERER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def shell_source() -> str:
    return SHELL.read_text(encoding="utf-8")


def _run_node(script: str):
    return subprocess.run(["node", "-e", script], capture_output=True, text=True)


# --- behavioral: driving the real renderer through node --------------------
#
# app-renderer-start-mission.js is a CommonJS module (`module.exports`) that
# also assigns `window.MissionState` and calls `winEl.innerHTML =`. It cannot
# be `require`d directly from Python, so these tests drive it through `node`
# with a stub element -- the renderer only ever assigns `innerHTML` and calls
# `querySelectorAll` (which may safely return `[]`) on the element it is
# given, so a minimal stub is a faithful enough DOM for these assertions.

MISSIONS_SCRIPT = """
const m = require(%(path)s);
const missions = [
  {id: "WS-1", title: "Blocked one", workflow: "blocked"},
  {id: "WS-2", title: "Decision one", workflow: "ready", decision: {summary: "pick a path"}},
  {id: "WS-3", title: "Review one", workflow: "review"},
  {id: "WS-4", title: "Running one", workflow: "in-progress"},
  {id: "WS-5", title: "Ready one", workflow: "ready"},
  {id: "WS-6", title: "Inbox one", workflow: "inbox"},
  {id: "WS-7", title: "Unknown one", workflow: "some-made-up-value"},
  {id: "WS-8", title: "Done one", workflow: "done"},
];
const el = {innerHTML: "", querySelectorAll: function () { return []; }};
m.render(el, {state: {model: {repo: "org/repo", model: {}, workstreams: missions}}});
console.log(el.innerHTML);
"""


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_every_mission_in_the_input_is_rendered_as_a_row():
    """Missions the operator can act on must not silently vanish from the list."""
    script = MISSIONS_SCRIPT % {"path": json.dumps(str(RENDERER))}
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    html = out.stdout
    for wid in ("WS-1", "WS-2", "WS-3", "WS-4", "WS-5", "WS-6", "WS-7", "WS-8"):
        assert 'data-mission-open="%s"' % wid in html, "missing row for %s" % wid


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_groups_appear_in_demand_first_order():
    """What is stopped or awaiting a decision must reach the operator's eye
    before what is merely running, and running before what has not started --
    reading top to bottom should already be triage order."""
    script = MISSIONS_SCRIPT % {"path": json.dumps(str(RENDERER))}
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    html = out.stdout
    order = ["blocked", "decision", "review", "running", "ready", "inbox", "unknown", "done"]
    positions = []
    for key in order:
        marker = 'data-mission-group="%s"' % key
        assert marker in html, "missing group %s" % key
        positions.append(html.index(marker))
    assert positions == sorted(positions), (
        "groups are not in demand-first order (blocked, decision, review, "
        "running, ready, inbox, unknown, done): %r" % list(zip(order, positions))
    )


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_an_unrecognised_workflow_value_renders_as_state_not_recorded():
    """A mission whose state the OS cannot read must never look like one that
    is safe to start -- it must say plainly that nothing was recorded, not
    guess "ready" and not silently drop into some other group."""
    script = """
const m = require(%(path)s);
const missions = [{id: "WS-9", title: "Mystery", workflow: "totally-unrecognised-value"}];
const el = {innerHTML: "", querySelectorAll: function () { return []; }};
m.render(el, {state: {model: {repo: "org/repo", model: {}, workstreams: missions}}});
console.log(el.innerHTML);
""" % {"path": json.dumps(str(RENDERER))}
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    html = out.stdout
    assert 'data-mission-group="unknown"' in html
    assert 'data-mission-state="unknown"' in html
    assert "State not recorded" in html
    # It must not be mis-sorted into the ready/startable group.
    assert 'data-mission-group="ready"' not in html
    assert "Ready to start" not in html


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_a_mission_carrying_a_decision_is_grouped_as_needs_your_decision_regardless_of_workflow():
    """A pending decision is a claim on the operator's authority that no
    workflow label overrides -- even a mission whose Issue says `ready` must
    surface as needing a decision first, never as merely startable."""
    script = """
const m = require(%(path)s);
const missions = [{id: "WS-10", title: "Contested", workflow: "ready", decision: {summary: "approve or reject"}}];
const el = {innerHTML: "", querySelectorAll: function () { return []; }};
m.render(el, {state: {model: {repo: "org/repo", model: {}, workstreams: missions}}});
console.log(el.innerHTML);
""" % {"path": json.dumps(str(RENDERER))}
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    html = out.stdout
    assert 'data-mission-group="decision"' in html
    assert 'data-mission-state="decision"' in html
    assert "Needs your decision" in html
    assert 'data-mission-group="ready"' not in html


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_the_synthetic_preview_model_renders_no_tracker_link_and_says_nothing_can_be_started():
    """Preview/demo data is not a live record. An operator must never be
    offered a working-looking "open the tracker" control, or any other
    action, against sample data that starts nothing."""
    script = """
const m = require(%(path)s);
const el = {innerHTML: "", querySelectorAll: function () { return []; }};
m.render(el, {state: {model: {synthetic: true, repo: "org/repo", workstreams: []}}});
console.log(el.innerHTML);
""" % {"path": json.dumps(str(RENDERER))}
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    html = out.stdout
    assert "nothing can be started" in html
    assert "data-mission-new=" not in html


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_a_model_with_unavailable_status_says_the_list_may_be_incomplete():
    """Freshness must be stated, not assumed: an operator deciding what to
    work on deserves to know when the OS could not actually read the record,
    rather than being shown a quietly-short list with no explanation."""
    script = """
const m = require(%(path)s);
const el = {innerHTML: "", querySelectorAll: function () { return []; }};
m.render(el, {state: {model: {repo: "org/repo", status: "unavailable", workstreams: []}}});
console.log(el.innerHTML);
""" % {"path": json.dumps(str(RENDERER))}
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    html = out.stdout
    assert "could not be read" in html
    assert "may be incomplete or empty" in html


# --- the dead-button regression: a handler and a subscriber must exist -----

def test_create_workstream_command_has_a_handler(shell_source):
    """The actual #469 defect: three "New Workstream" controls emitted
    `create-workstream` and nothing in the shell had a case for it, so the
    command silently went nowhere. A handler must exist in the shell's typed
    command map."""
    assert '"create-workstream":function(){openDeep("start")}' in shell_source


def test_command_bus_has_a_subscriber(shell_source):
    """The other half of the same defect: `OSRenderer.emit("command", ...)`
    is the app-side bus every "New Workstream" control actually calls, and it
    had no listener at all. Something must now subscribe to it and route
    into the same typed handler map, or the fix only half-exists."""
    assert 'OSRenderer.on("command",function(p){' in shell_source
    assert "commandHandlers[name](p)" in shell_source


# --- registration: apps.json and both index.html carriers ------------------

def test_apps_json_registers_the_start_app():
    """openDeep("start") (the create-workstream handler) can only resolve to
    a real app if the registry actually carries a `start` entry -- otherwise
    the fixed handler would itself be a dead end."""
    registry = json.loads(APPS.read_text(encoding="utf-8"))
    by_id = {a["id"]: a for a in registry["apps"]}
    assert "start" in by_id, "apps.json has no 'start' app entry"
    start = by_id["start"]
    assert start["title"] == "Start a mission"
    assert "read:workstream-summary" in start["capabilities"]


@pytest.mark.parametrize("index_path", [INDEX, SITE_INDEX], ids=["widget", "site-mirror"])
def test_index_html_loads_the_start_mission_renderer(index_path):
    """The app registers itself into OSRenderer at load time (`OSRenderer.register("start", ...)`
    in app-renderer-start-mission.js) -- if either host page never loads the
    script, "start" resolves in the registry but renders nothing."""
    html = index_path.read_text(encoding="utf-8")
    assert "app-renderer-start-mission.js" in html


@pytest.mark.parametrize("index_path", [INDEX, SITE_INDEX], ids=["widget", "site-mirror"])
def test_index_html_carries_the_start_window_element(index_path):
    """The third registration place. `apps.json` gives `start` kind `window`,
    so `openWindow("start")` is reachable from the launcher and from the deep
    window control. `applyView` only ever iterates the `[data-window]`
    elements that exist, so without this section the shell would enter
    multi-window mode showing nothing -- a control that does nothing, which is
    the defect this delivery removes rather than relocates."""
    html = index_path.read_text(encoding="utf-8")
    assert 'data-window="start"' in html, "no start window section"
    assert "data-start-body" in html, "start window has no body for the renderer"


@pytest.mark.parametrize("shell_path", [SHELL, SITE_SHELL], ids=["widget", "site-mirror"])
def test_the_start_window_body_is_actually_rendered(shell_path):
    """A window element with no render call opens empty. `propagateContext`
    wires every other window body the same way."""
    source = shell_path.read_text(encoding="utf-8")
    assert 'q("[data-start-body]")' in source
    assert 'OSRenderer.render("start"' in source


def test_apps_json_start_window_name_matches_the_element():
    """`windowOf` falls back to the app id, so a mismatch here would be
    invisible until the window failed to open."""
    registry = json.loads(APPS.read_text(encoding="utf-8"))
    start = {a["id"]: a for a in registry["apps"]}["start"]
    assert start["window"] == "start"


# --- the run-result control must not dead-end -------------------------------

LAUNCH = WIDGET / "app-renderer-work-launch.js"
SITE_LAUNCH = MIRROR / "app-renderer-work-launch.js"


@pytest.mark.parametrize("path", [LAUNCH, SITE_LAUNCH], ids=["widget", "site-mirror"])
def test_a_failed_run_projection_is_not_reported_as_an_authority_statement(path):
    """#469 widens this path from claimed-only to every terminal Workstream,
    so the control now reaches it for many more missions. A caught fetch
    failure used to render "This Workstream has no authorized launch" --
    telling the operator a fact about their mandate on the strength of a
    failed GET. Verified live: when the host died mid-request the surface
    said exactly that about a Workstream whose Run record was intact."""
    source = path.read_text(encoding="utf-8")
    assert "runProjectionUnavailableNotice" in source
    assert ".catch(function () { winEl.innerHTML = runProjectionUnavailableNotice(); });" in source
    assert "nothing about its authority has been" in source


@pytest.mark.parametrize("path", [LAUNCH, SITE_LAUNCH], ids=["widget", "site-mirror"])
def test_no_recorded_run_is_named_as_such_not_as_a_missing_launch(path):
    """The Work control appears for any workflow in RUN_RESULT_WORKFLOWS, which
    does not prove a Run exists. When none does, the surface must say the Run
    record is missing rather than making a claim about launch authority."""
    source = path.read_text(encoding="utf-8")
    assert "noRunRecordNotice" in source
    assert "if (!runs.length) { winEl.innerHTML = noRunRecordNotice(); return; }" in source


@pytest.mark.parametrize("path", [LAUNCH, SITE_LAUNCH], ids=["widget", "site-mirror"])
def test_the_launch_gate_itself_is_unchanged(path):
    """Neither new message grants anything. The dispatch-request fetch stays
    gated solely on a typed `launch` next action, and the widened read path
    still refuses every Workstream that is neither claimed nor terminal."""
    source = path.read_text(encoding="utf-8")
    assert 'if (typed !== "launch" ||' in source
    assert "if (!followable(x)) { winEl.innerHTML = noLaunchNotice(typed); return; }" in source
    assert 'var TERMINAL_WORKFLOWS = ["blocked", "review", "done"];' in source


# --- site mirror parity -----------------------------------------------------
#
# The suite already asserts byte-identical parity between agent-platform/widget
# and site/public/widgets for the other shell/renderer files
# (test_os_shell_core.py::test_site_mirror_is_identical); this app is new
# enough that it was not yet in that parametrized list, so it gets its own
# identical check here rather than silently going unmirrored.

def test_site_mirror_copy_exists():
    assert SITE_RENDERER.is_file(), "site/public/widgets is missing app-renderer-start-mission.js"


def test_site_mirror_is_byte_identical_to_the_agent_platform_copy():
    """The widget host and the public site each load their own copy of this
    script; if the two ever diverge, which behaviour an operator gets depends
    on which surface served the page -- exactly the kind of silent drift the
    rest of the suite already guards other shell files against."""
    assert RENDERER.read_bytes() == SITE_RENDERER.read_bytes()
