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
import re
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
    # Routed through the sanctioned router, not around it: dispatch checks the
    # APP_COMMANDS allow-list and normalizes the payload. Indexing the handler
    # map directly would leave two routers free to disagree about what exists.
    assert "ShellCommands.dispatch(p&&p.command,p,commandHandlers)" in shell_source


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


# These drive the module through node, so they load the `agent-platform/widget`
# copy only: `site/package.json` declares `"type": "module"`, which makes node
# treat the byte-identical mirror as ESM, where `module.exports` never runs and
# `require` yields `{}`. The mirror carries these properties through the byte
# parity assertion below, not through a second node run.

NOTICE_SCRIPT = """
const l = require(%(path)s);
console.log(JSON.stringify({
  noLaunch: l.noLaunchNotice("none"),
  noRunRecord: l.noRunRecordNotice(),
  unavailable: l.runProjectionUnavailableNotice(),
  followable: {
    claimed:   l.followable({workflow: "in-progress"}),
    prefixed:  l.followable({workflow: "workflow:blocked"}),
    blocked:   l.followable({workflow: "blocked"}),
    review:    l.followable({workflow: "review"}),
    done:      l.followable({workflow: "done"}),
    ready:     l.followable({workflow: "ready"}),
    inbox:     l.followable({workflow: "inbox"}),
    unknown:   l.followable({workflow: "unknown"}),
    missing:   l.followable({}),
    nullish:   l.followable(null),
  },
}));
"""


@pytest.mark.skipif(NODE is None, reason="node unavailable")
@pytest.mark.parametrize("path", [LAUNCH], ids=["widget"])
def test_a_failed_run_projection_is_not_reported_as_an_authority_statement(path):
    """#469 widens this path from claimed-only to every terminal Workstream,
    so the control now reaches it for many more missions. A caught fetch
    failure used to render "This Workstream has no authorized launch" --
    telling the operator a fact about their mandate on the strength of a
    failed GET. Verified live: when the host died mid-request the surface
    said exactly that about a Workstream whose Run record was intact."""
    out = _run_node(NOTICE_SCRIPT % {"path": json.dumps(str(path))})
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert "could not be read" in got["unavailable"]
    assert "nothing about its authority has been determined" in got["unavailable"]
    assert "no authorized launch" not in got["unavailable"]


@pytest.mark.skipif(NODE is None, reason="node unavailable")
@pytest.mark.parametrize("path", [LAUNCH], ids=["widget"])
def test_no_recorded_run_is_named_as_such_not_as_a_missing_launch(path):
    """The Work control appears for any workflow in RUN_RESULT_WORKFLOWS, which
    does not prove a Run exists. When none does, the surface must say the Run
    record is missing rather than making a claim about launch authority."""
    out = _run_node(NOTICE_SCRIPT % {"path": json.dumps(str(path))})
    got = json.loads(out.stdout)
    assert "No Run is recorded" in got["noRunRecord"]
    assert "no authorized launch" not in got["noRunRecord"]
    # The three refusals must remain distinguishable from one another.
    assert len({got["noLaunch"], got["noRunRecord"], got["unavailable"]}) == 3


@pytest.mark.skipif(NODE is None, reason="node unavailable")
@pytest.mark.parametrize("path", [LAUNCH], ids=["widget"])
def test_the_widened_read_path_is_bounded(path):
    """`followable` is the entire boundary of the widening. A Workstream that
    never ran anything must not become readable, and neither notice may grant
    anything: the dispatch-request fetch stays gated on a typed `launch` next
    action, which `followable` is never consulted for."""
    out = _run_node(NOTICE_SCRIPT % {"path": json.dumps(str(path))})
    f = json.loads(out.stdout)["followable"]
    for k in ("claimed", "prefixed", "blocked", "review", "done"):
        assert f[k] is True, f"{k} should be readable"
    for k in ("ready", "inbox", "unknown", "missing", "nullish"):
        assert f[k] is False, f"{k} must not become readable"
    source = path.read_text(encoding="utf-8")
    assert 'if (typed !== "launch" ||' in source
    assert "if (!followable(x)) { winEl.innerHTML = noLaunchNotice(typed); return; }" in source


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


# --- behavioral: the controls the source-grep tests could not see -----------
#
# The review that found the preview-mode dead control noted that every click
# handler and the run-result gate were asserted only by grepping the source
# for literals. These drive the real functions instead.

RUN_RESULT_SCRIPT = """
const w = require(%(path)s);
const cases = [
  ["blocked live",   {id:"WS-1", issue_id:"o/r#1", workflow:"blocked"},     false],
  ["review live",    {id:"WS-2", issue_id:"o/r#2", workflow:"review"},      false],
  ["done live",      {id:"WS-3", issue_id:"o/r#3", workflow:"done"},        false],
  ["running live",   {id:"WS-4", issue_id:"o/r#4", workflow:"in-progress"}, false],
  ["prefixed live",  {id:"WS-5", issue_id:"o/r#5", workflow:"workflow:blocked"}, false],
  ["ready live",     {id:"WS-6", issue_id:"o/r#6", workflow:"ready"},       false],
  ["inbox live",     {id:"WS-7", issue_id:"o/r#7", workflow:"inbox"},       false],
  ["unknown live",   {id:"WS-8", issue_id:"o/r#8", workflow:"unknown"},     false],
  ["no issue live",  {id:"WS-9", workflow:"blocked"},                       false],
  ["blocked synth",  {id:"WS-1", issue_id:"o/r#1", workflow:"blocked"},     true],
  ["review synth",   {id:"WS-2", issue_id:"o/r#2", workflow:"review"},      true],
  ["running synth",  {id:"WS-4", issue_id:"o/r#4", workflow:"in-progress"}, true],
];
const out = {};
for (const [name, x, synthetic] of cases) out[name] = w.runResultAvailable(x, synthetic);
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_the_run_result_control_is_never_offered_in_preview_mode():
    """The defect this covers: `renderLaunch` refuses every non-launch
    Workstream in synthetic mode *before* it consults `followable`, so the
    read-only follow path is unreachable there. Offering the control anyway
    puts a button in front of the operator that can only answer "this
    Workstream has no authorized launch" -- a dead control that also makes an
    authority claim on a path that never asked about authority. The site
    mirror serves exactly this mode from `fixtures/workstreams.json`."""
    out = _run_node(RUN_RESULT_SCRIPT % {"path": json.dumps(str(SHELL))})
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    for name in ("blocked synth", "review synth", "running synth"):
        assert got[name] is False, f"{name} offers a control preview mode cannot honour"


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_the_run_result_control_is_offered_for_exactly_the_workflows_with_a_run():
    """A live Workstream that has been worked on gets the control; one that
    never ran anything, or carries no Issue, does not -- otherwise the control
    dead-ends on a Workstream with no Run to show."""
    out = _run_node(RUN_RESULT_SCRIPT % {"path": json.dumps(str(SHELL))})
    got = json.loads(out.stdout)
    for name in ("blocked live", "review live", "done live", "running live", "prefixed live"):
        assert got[name] is True, f"{name} should reach its run result"
    for name in ("ready live", "inbox live", "unknown live", "no issue live"):
        assert got[name] is False, f"{name} has no Run and must offer no control"


CLICK_SCRIPT = """
const m = require(%(path)s);
const missions = [{id: "WS-1", title: "One", workflow: "ready"}];
const state = {model: {repo: "org/repo", model: {}, workstreams: missions}};
const rows = [];
function stubButton(dataset) {
  const handlers = [];
  return {dataset, addEventListener: (_e, fn) => handlers.push(fn), click: () => handlers.forEach(f => f())};
}
const el = {
  innerHTML: "",
  querySelectorAll: function (sel) {
    if (sel === "[data-mission-open]") return rows;
    return [];
  },
};
const calls = [];
global.window = global;
global.ShellCommandHandlers = {
  "switch-workstream": p => calls.push(["switch", p.workstreamId]),
  "open-app": p => calls.push(["open", p.appId]),
};
rows.push(stubButton({missionOpen: %(clicked)s}));
m.render(el, {state});
rows[0].click();
console.log(JSON.stringify(calls));
"""


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_clicking_a_mission_selects_it_and_opens_work():
    """The whole point of the app. Nothing asserted this: the earlier stub
    returned [] for every selector, so a misspelled payload key would have
    shipped four more dead controls with the suite green."""
    out = _run_node(CLICK_SCRIPT % {"path": json.dumps(str(RENDERER)), "clicked": '"WS-1"'})
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [["switch", "WS-1"], ["open", "work"]]


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_a_row_whose_mission_is_gone_navigates_nowhere():
    """`switch-workstream` fails closed on an unknown id, but it does so
    silently -- so an unconditional `open-app` would land the operator in Work
    looking at the previously selected Workstream, believing this row opened
    it. The stale row must navigate nowhere at all."""
    out = _run_node(CLICK_SCRIPT % {"path": json.dumps(str(RENDERER)), "clicked": '"WS-GONE"'})
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == []


DISPATCH_SCRIPT = """
const c = require(%(path)s);
const seen = [];
const handlers = {
  "create-workstream": p => seen.push(["create", p]),
  "open-external": p => seen.push(["external", p]),
};
const r = {
  listed:      c.dispatch("create-workstream", {command: "create-workstream"}, handlers),
  unknown:     c.dispatch("definitely-not-a-command", {}, handlers),
  proto:       c.dispatch("constructor", {}, handlers),
  nonString:   c.dispatch(null, {}, handlers),
  badPayload:  c.dispatch("create-workstream", "not-an-object", handlers),
};
console.log(JSON.stringify({r, seen}));
"""


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_the_command_bus_is_allow_listed_by_the_same_router_as_everything_else():
    """The bridge routes through `ShellCommands.dispatch` rather than indexing
    the handler map, so `create-workstream` has to be in APP_COMMANDS to work
    at all -- one allow-list, not two that can disagree. Unknown names,
    prototype keys and non-string commands still fail closed, and a
    non-object payload is normalized rather than passed through."""
    shell_commands = WIDGET / "shell-commands.js"
    out = _run_node(DISPATCH_SCRIPT % {"path": json.dumps(str(shell_commands))})
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["r"]["listed"] is True, "create-workstream is not in APP_COMMANDS"
    assert got["r"]["unknown"] is False
    assert got["r"]["proto"] is False
    assert got["r"]["nonString"] is False
    assert got["r"]["badPayload"] is True
    assert got["seen"][-1] == ["create", {}], "a non-object payload must be normalized"


@pytest.mark.parametrize("shell_path", [SHELL, SITE_SHELL], ids=["widget", "site-mirror"])
def test_the_launch_window_body_is_only_rendered_while_its_window_is_open(shell_path):
    """Rendering the launch body costs a network read: `api/runs` plus, for a
    live Run, a 5s poller. #469 widened that path from claimed-only to every
    terminal Workstream and most Workstreams are `done`, so rendering it while
    the window is closed would fetch on nearly every selection and refresh.
    Closing the window must also stop the poller rather than leave it writing
    into a hidden node.

    This is a source assertion: `propagateContext` needs a real document and
    is not exported, so the browser is the only place the rendered result can
    be observed. `openWindow` sets `state.ui.open[id]` before it calls
    `renderAll`, which is what makes the gate open in time."""
    source = shell_path.read_text(encoding="utf-8")
    assert "if(l&&state.ui.open.launch){" in source
    assert 'if(typeof l._cortxtStopLiveRun==="function")l._cortxtStopLiveRun();' in source
    ordering = source.index("state.ui.open[a.id]=true")
    assert ordering < source.index("renderAll();", ordering), \
        "openWindow must mark the window open before it renders"


# --- #619: compose is a real mutation, preview reads the real terms ---------
#
# The start flow previously ended honestly but dead-ended: "the record is an
# Issue, open the tracker" was the only shape a new mission could take. #619
# adds the two shapes a live host can actually authorize -- compose (the
# issue-create action POST, operator-gated by the host's own capability
# registration) and preview (the authoritative dispatch.request.v2, rendered
# read-only). Both fail closed everywhere else.

COMPOSE_SCRIPT = """
const m = require(%(path)s);
const missions = [{id: "WS-1", title: "Ready one", workflow: "ready"}];
const out = {};
out.compose_available_live_with_cap = m.composeAvailable({
  model: {repo: "org/repo", workstreams: missions},
  capabilities: [{id: "issue-create"}],
});
out.compose_available_live_without_cap = m.composeAvailable({
  model: {repo: "org/repo", workstreams: missions},
  capabilities: [],
});
out.compose_available_synthetic_with_cap = m.composeAvailable({
  model: {synthetic: true, repo: "org/repo", workstreams: missions},
  capabilities: [{id: "issue-create"}],
});
out.compose_available_no_model = m.composeAvailable({});
out.compose_available_null = m.composeAvailable(null);
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_compose_is_offered_only_for_a_live_model_with_the_registered_action():
    """The same fail-closed split as launch/recovery/unblock in the Work
    shell: synthetic and preview data authorize nothing, and a host without
    the registered `issue-create` capability gets the tracker link instead of
    a control that can only be refused."""
    out = _run_node(COMPOSE_SCRIPT % {"path": json.dumps(str(RENDERER))})
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["compose_available_live_with_cap"] is True
    for k in ("compose_available_live_without_cap",
              "compose_available_synthetic_with_cap",
              "compose_available_no_model",
              "compose_available_null"):
        assert got[k] is False, f"{k}: compose must fail closed"


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_compose_payload_is_exactly_the_confirmed_form_contents():
    """The POSTed mandate is the trimmed form contents with labels split on
    commas and empties dropped -- nothing else, and `confirm: true` always
    explicit. Exported so the payload shape is exercised rather than grepped;
    the confirmation checkbox the launch dialog uses is not needed here
    because every field IS the operator's own typed input."""
    script = """
const m = require(%(path)s);
console.log(JSON.stringify(m.composePayload({
  repo: '  org/repo  ', title: ' Wire the gate ',
  body: 'Do the thing.', labels: 'a, b,,c ,',
})));
""" % {"path": json.dumps(str(RENDERER))}
    out = _run_node(script)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["action_id"] == "issue-create"
    assert got["confirm"] is True
    assert got["mandate"] == {
        "repo": "org/repo", "title": "Wire the gate",
        "body": "Do the thing.", "labels": ["a", "b", "c"],
    }


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_compose_form_renders_only_when_authorized_and_binds_the_token():
    """The form appears only in the authorized shape, and its submit posts to
    api/action with the shell's action token -- the same header pattern the
    launch confirmation dialog uses."""
    script = """
const m = require(%(path)s);
function renderWith(state) {
  const el = {innerHTML: "", querySelectorAll: function () { return []; }};
  m.render(el, {state});
  return el.innerHTML;
}
const authorized = renderWith({model: {repo: "org/repo", workstreams: []}, capabilities: [{id: "issue-create"}], token: "t1"});
const unauthorized = renderWith({model: {repo: "org/repo", workstreams: []}, capabilities: []});
const synthetic = renderWith({model: {synthetic: true, repo: "org/repo", workstreams: []}, capabilities: [{id: "issue-create"}]});
console.log(JSON.stringify({
  authorized: authorized.includes("data-mission-compose-form"),
  tracker_link_when_unauthorized: unauthorized.includes("data-mission-new="),
  no_form_in_synthetic: !synthetic.includes("data-mission-compose-form"),
  no_link_in_synthetic: !synthetic.includes("data-mission-new="),
}));
""" % {"path": json.dumps(str(RENDERER))}
    out = _run_node(script)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["authorized"] is True
    assert got["no_form_in_synthetic"] is True
    assert got["no_link_in_synthetic"] is True
    assert got["tracker_link_when_unauthorized"] is True
    source = RENDERER.read_text(encoding="utf-8")
    assert 'fetch("api/action"' in source
    assert '"X-Cortxt-Token": s.token' in source
    # The surface posts exactly the compose action here; the one other POST
    # in this file is the operator-gated mark-ready transition, asserted
    # exactly in its own section below.
    assert 'action_id: "issue-create"' in source
    assert source.count("fetch(\"api/action\"") == 2


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_the_start_surface_never_offers_or_posts_a_claim_run():
    """Start composes and previews; it never launches. The launch-shaped
    vocabulary must not appear on this surface at all, and the only action
    the surface knows how to POST is issue-create -- so the first step of the
    flow can never become a second, ungated launch path."""
    script = """
const m = require(%(path)s);
const el = {innerHTML: "", querySelectorAll: function () { return []; }};
m.render(el, {state: {model: {repo: "org/repo", workstreams: []}, capabilities: [{id: "issue-create"}, {id: "claim-run"}], token: "t1"}});
console.log(el.innerHTML);
""" % {"path": json.dumps(str(RENDERER))}
    out = _run_node(script)
    assert out.returncode == 0, out.stderr
    html = out.stdout
    assert "claim-run" not in html
    assert "data-launch-run" not in html
    source = RENDERER.read_text(encoding="utf-8")
    assert "claim-run" not in source
    assert "data-launch-start" not in source


PREVIEW_SCRIPT = """
const m = require(%(path)s);
const panel = {innerHTML: ""};
m.renderPreview(panel, %(payload)s, %(authority)s);
console.log(JSON.stringify({html: panel.innerHTML}));
"""


def _preview_html(payload: dict, authority: dict | None = None) -> str:
    out = _run_node(PREVIEW_SCRIPT % {
        "path": json.dumps(str(RENDERER)),
        "payload": json.dumps(payload),
        "authority": json.dumps(authority),
    })
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)["html"]


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_preview_renders_eligibility_from_the_authoritative_request():
    """The preview renders the server's own verdict, its engine and routing
    facts -- field-for-field, the same document the launch step will confirm
    against. The two approval facts come from the workstream projection's
    authority block (the third argument), never from the v2 document: that
    document carries neither field, so reading them from it is exactly the
    gate-P2 defect that rendered "not recorded" for an approved mission."""
    html = _preview_html({
        "issue_id": "org/repo#12", "eligible": True, "engine": "codex",
        "routing_reason": "default", "routable_task_tags": ["code", "review"],
        "execution_profile_revision": "r7",
    }, authority={"approval_recorded": True, "approval_source": "issue-body-approval-status"})
    assert 'data-preview-eligible' in html
    assert "Eligible" in html
    assert "org/repo#12" in html
    assert "codex" in html
    assert "default" in html
    assert "code, review" in html
    assert "r7" in html
    assert "yes" in html
    assert "issue-body-approval-status" in html


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_preview_renders_the_honest_absence_shape_without_an_authority_block():
    """With no workstream authority available -- projection unreadable, or a
    freshly composed Issue not yet on it -- the rows must say plainly that
    nothing was recorded: "not recorded" and no source. Never a guessed
    "yes", and never a value read off the v2 document it is not carried on."""
    html = _preview_html({
        "issue_id": "org/repo#15", "eligible": False,
        "missing": ["approval_reference"],
    }, authority=None)
    assert "Approval recorded" in html
    assert "not recorded" in html
    assert 'data-preview-ineligible' in html
    # The source row renders the empty-value dash; neither a positive nor a
    # negative approval verdict may be invented.
    assert 'Approval source</span><span class="launch-value">—<' in html
    assert ">yes<" not in html
    assert ">no<" not in html


# --- gate P2 (#619): the preview's two reads, and what each one is for ------
#
# The preview performs exactly two GETs: the authoritative dispatch.request.v2
# (whose digest the launch gate binds -- it must stay exactly one) and the
# /api/workstreams projection, read only for the authority block's approval
# provenance. These drive the real loadPreview through node with a stubbed
# fetch, so the count, the order and each document's role are asserted
# behaviorally instead of grepped.

FETCH_SCRIPT = """
const m = require(%(path)s);
const requests = [];
const panel = {innerHTML: ""};
const winEl = {querySelector: function (sel) { return sel === "[data-mission-preview-panel]" ? panel : null; }};
global.window = global;
function mkPage(body, ok) { return {ok: ok, json: function () { return Promise.resolve(body); }}; }
const dispatchPage = mkPage(%(req)s, %(dispatch_ok)s);
/* Lazily constructed so a rejecting page is only created when the
   workstreams fetch actually happens -- an unconsumed rejection at script
   scope would kill node before the assertions run. */
const workstreamPage = function () { return %(workstream_page)s; };
global.fetch = function (url, opts) {
  requests.push({url: String(url), cache: !!(opts && opts.cache)});
  if (String(url).indexOf("api/dispatch-request") === 0) return Promise.resolve(dispatchPage);
  return Promise.resolve(workstreamPage());
};
m.loadPreview(winEl, %(issue)s);
setTimeout(function () {
  console.log(JSON.stringify({requests: requests, html: panel.innerHTML}));
}, 20);
"""

_DISPATCH_REQ = {
    "issue_id": "o/r#1", "eligible": True, "engine": "codex",
    "routing_reason": "default", "routable_task_tags": ["code"],
    "execution_profile_revision": "r7",
}

_PROJECTION_WITH_AUTHORITY = {
    "schema_version": 1, "synthetic": False,
    "workstreams": [{"id": "WS-1", "issue_id": "o/r#1", "workflow": "ready",
                     "authority": {"source": "GitHub Issue",
                                   "workflow_label": "workflow:ready",
                                   "approval_recorded": True,
                                   "approval_source": "issue-body-approval-status"}}],
}


def _fetch_preview(*, dispatch_ok: bool, workstream_page: str):
    out = _run_node(FETCH_SCRIPT % {
        "path": json.dumps(str(RENDERER)),
        "req": json.dumps(_DISPATCH_REQ),
        "dispatch_ok": "true" if dispatch_ok else "false",
        "workstream_page": workstream_page,
        "issue": json.dumps("o/r#1"),
    })
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_the_preview_performs_exactly_one_dispatch_request_and_one_projection_read():
    """Still exactly ONE dispatch-request GET -- the launch step's digest
    binding reads this same path, so the preview must not multiply it -- plus
    exactly ONE workstream-projection GET, from which alone the two approval
    rows take their values."""
    got = _fetch_preview(
        dispatch_ok=True,
        workstream_page="mkPage(%s, true)" % json.dumps(_PROJECTION_WITH_AUTHORITY))
    assert got["requests"] == [
        {"url": "api/dispatch-request?issue=o%2Fr%231", "cache": True},
        {"url": "api/workstreams", "cache": True},
    ], got["requests"]
    # Dispatch facts still come from the v2 document...
    assert "codex" in got["html"] and "r7" in got["html"]
    # ...and the approval facts come from the projection's authority block.
    assert "yes" in got["html"]
    assert "issue-body-approval-status" in got["html"]


@pytest.mark.skipif(NODE is None, reason="node unavailable")
@pytest.mark.parametrize("workstream_page", [
    'mkPage({"schema_version": 1, "status": "unavailable", "error": {"kind": "github_read", "message": "gh issue list failed"}}, false)',
    'Promise.reject(new Error("connection refused"))',
], ids=["unavailable-503", "network-error"])
def test_an_unreadable_projection_renders_the_honest_absence_shape(workstream_page):
    """When the projection cannot be read (a 503 from the host, or the fetch
    itself failing), the preview must not dead-end and must not invent
    approval facts: the rows render "not recorded" with no source -- the same
    honest shape as before, but now it is genuinely the absence of the fact,
    not a field the document never carried."""
    got = _fetch_preview(dispatch_ok=True, workstream_page=workstream_page)
    assert [r["url"] for r in got["requests"]] == [
        "api/dispatch-request?issue=o%2Fr%231", "api/workstreams"]
    assert "Approval recorded" in got["html"]
    assert "not recorded" in got["html"]
    assert 'Approval source</span><span class="launch-value">—<' in got["html"]
    assert ">yes<" not in got["html"]
    assert ">no<" not in got["html"]
    # The v2 document's own facts are still rendered.
    assert "codex" in got["html"]


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_a_failed_dispatch_request_read_never_adds_a_projection_fetch():
    """The dispatch-request read is the preview's gate: when IT fails, the
    panel shows the error and no second request may be issued at all."""
    got = _fetch_preview(
        dispatch_ok=False,
        workstream_page='Promise.reject(new Error("should never be reached"))')
    assert got["requests"] == [{"url": "api/dispatch-request?issue=o%2Fr%231", "cache": True}]
    assert "could not be read" in got["html"]


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_preview_renders_missing_and_errors_and_never_a_launch_control():
    """An ineligible request shows what is missing, in the same structure the
    launch app renders it -- and still offers no launch affordance: the
    preview starts nothing, starting stays in the launch step."""
    html = _preview_html({
        "issue_id": "org/repo#13", "eligible": False,
        "missing": ["approval_reference"],
        "errors": [{"code": "mandate_incomplete", "category": "mandate",
                    "recovery": "Record the approved mandate on the Issue."}],
    })
    assert 'data-preview-ineligible' in html
    assert "Not startable yet" in html
    assert "mandate_incomplete" in html
    assert "Record the approved mandate" in html
    assert "data-launch-start" not in html
    assert "claim-run" not in html


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_preview_never_renders_provider_or_model_fields_that_v2_does_not_carry():
    """The v2 dispatch request has no provider or model fields, so the panel
    must not invent them: the execution profile revision is the
    replaceable-execution fact it does carry, and nothing beyond it."""
    html = _preview_html({"issue_id": "org/repo#14", "eligible": True})
    assert "Provider" not in html
    assert "Model" not in html


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_the_preview_fetch_is_gated_on_a_real_issue_and_a_live_model():
    """The preview control exists only where it can work: a mission carrying
    an Issue on a live host. Synthetic mode renders none -- the static host
    has no api/ route, and a control that can only answer 'unavailable' is a
    dead control."""
    script = """
const m = require(%(path)s);
const missions = [
  {id: "WS-1", title: "With issue", workflow: "ready", issue_id: "org/repo#1"},
  {id: "WS-2", title: "No issue", workflow: "ready"},
];
function renderWith(state) {
  const el = {innerHTML: "", querySelectorAll: function () { return []; }};
  m.render(el, {state});
  return el.innerHTML;
}
console.log(JSON.stringify({
  live_with_issue: renderWith({model: {repo: "org/repo", workstreams: missions}}).includes("data-mission-preview="),
  live_no_issue: renderWith({model: {repo: "org/repo", workstreams: missions}}).includes("data-mission-preview=\\"org/repo#1\\""),
  synthetic: renderWith({model: {synthetic: true, repo: "org/repo", workstreams: missions}}).includes("data-mission-preview="),
}));
""".replace("\n", "\n") % {"path": json.dumps(str(RENDERER))}
    out = _run_node(script)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["live_with_issue"] is True
    assert got["live_no_issue"] is True
    assert got["synthetic"] is False
    source = RENDERER.read_text(encoding="utf-8")
    assert 'fetch("api/dispatch-request?issue="' in source
    assert '{cache:"no-store"}' in source or '{ cache: "no-store" }' in source


def test_the_preview_panel_element_exists_for_the_renderer_to_fill():
    """`loadPreview` writes into `[data-mission-preview-panel]`; without the
    element the fetch would run against nothing (the querySelector guard
    silently returns). The section is part of the render contract."""
    source = RENDERER.read_text(encoding="utf-8")
    assert 'data-mission-preview-panel' in source


# --- #619: the Work surface's prepare affordance ----------------------------

PREPARE_SCRIPT = """
const w = require(%(path)s);
const cases = {
  live_with_cap:      {s: {model: {repo: "o/r"}, capabilities: [{id: "issue-create"}]}, x: {id: "WS-1", issue_id: "o/r#1", workflow: "ready", next_action: {kind: "prepare"}}},
  live_without_cap:   {s: {model: {repo: "o/r"}, capabilities: []}, x: {id: "WS-1", issue_id: "o/r#1", workflow: "ready", next_action: {kind: "prepare"}}},
  synthetic_granted:  {s: {model: {synthetic: true, repo: "o/r"}}, x: {id: "WS-1", issue_id: "o/r#1", workflow: "ready", next_action: {kind: "prepare"}, view_capabilities: ["view:prepare"]}},
  synthetic_unganted: {s: {model: {synthetic: true, repo: "o/r"}}, x: {id: "WS-1", issue_id: "o/r#1", workflow: "ready", next_action: {kind: "prepare"}}},
  wrong_kind:         {s: {model: {repo: "o/r"}, capabilities: [{id: "issue-create"}]}, x: {id: "WS-1", issue_id: "o/r#1", workflow: "ready", next_action: {kind: "launch"}}},
  uncorrelated:       {s: {model: {repo: "o/r"}, capabilities: [{id: "issue-create"}]}, x: {id: "WS-1", workflow: "ready", next_action: {kind: "prepare"}}},
};
const out = {};
for (const [name, c] of Object.entries(cases)) out[name] = w.prepareAvailable(c.s, c.x);
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_the_prepare_affordance_is_gated_per_authorities():
    """Live: only with the registered `issue-create` action. Synthetic: only
    with the fixture's own `view:prepare` grant. Anything else -- wrong typed
    kind, uncorrelated projection, no capabilities -- is refused, exactly the
    launch/recovery/unblock discipline."""
    out = _run_node(PREPARE_SCRIPT % {"path": json.dumps(str(SHELL))})
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["live_with_cap"] is True
    for k in ("live_without_cap", "synthetic_unganted", "wrong_kind", "uncorrelated"):
        assert got[k] is False, f"{k}: prepare must fail closed"
    # synthetic grant is granted (typo'd key name is the fixture's, not the
    # contract's): the one True branch in preview mode.
    assert got["synthetic_granted"] is True


@pytest.mark.parametrize("shell_path", [SHELL, SITE_SHELL], ids=["widget", "site-mirror"])
def test_the_prepare_control_hands_off_to_the_start_app(shell_path):
    """The shell never performs the mutation: the prepare branch renders a
    primary control that opens the Start app (which owns the compose form and
    the terms preview) via the same data-deep-open wiring as every other
    handoff."""
    source = shell_path.read_text(encoding="utf-8")
    assert 'data-deep-open="start"' in source


@pytest.mark.parametrize("shell_path", [SHELL, SITE_SHELL], ids=["widget", "site-mirror"])
def test_the_shell_still_never_calls_an_action_port(shell_path):
    """Adding the prepare affordance must not change the shell's own mutation
    boundary: work-console.js still contains no action POST of any kind --
    compose stays in the Start app, gated by the host's capability
    registration."""
    source = shell_path.read_text(encoding="utf-8")
    assert 'fetch("api/action"' not in source
    # The shell's prose comments may name the launch action; what must never
    # exist here is the executable boundary itself -- an action POST. The
    # only POST-shaped call in the shell targets the read projections.
    assert "issue-create" in source  # the gate references the action id; the POST does not live here
    assert 'method: "POST"' not in source  # the shell performs no POST at all; compose lives in the Start app


# --- #619 round 6: the operator-gated mark-ready confirmation ---------------
#
# An inbox mission has exactly one real mutation reachable from this surface:
# the promotion of its Issue to workflow:ready -- the only label write in the
# product. It is offered under the same fail-closed split as compose, and the
# confirmation dialog mirrors `beginRecovery` in
# app-renderer-decisions-evidence.js: an explained modal, a REQUIRED approval
# reference refused client-side when empty, explicit `confirm: true` on the
# POST, and denials (TransitionDenied, 409) rendered honestly in the dialog.

READY_AVAILABLE_SCRIPT = """
const m = require(%(path)s);
const cases = {
  live_with_cap:     {s: {model: {repo: "o/r"}, capabilities: [{id: "mark-ready"}]},                  x: {id: "WS-1", issue_id: "o/r#1", workflow: "inbox"}},
  live_prefixed:     {s: {model: {repo: "o/r"}, capabilities: [{id: "mark-ready"}]},                  x: {id: "WS-1", issue_id: "o/r#1", workflow: "workflow:inbox"}},
  live_without_cap:  {s: {model: {repo: "o/r"}, capabilities: []},                                    x: {id: "WS-1", issue_id: "o/r#1", workflow: "inbox"}},
  live_wrong_cap:    {s: {model: {repo: "o/r"}, capabilities: [{id: "issue-create"}]},                x: {id: "WS-1", issue_id: "o/r#1", workflow: "inbox"}},
  synthetic_granted: {s: {model: {synthetic: true, repo: "o/r"}, capabilities: [{id: "mark-ready"}]}, x: {id: "WS-1", issue_id: "o/r#1", workflow: "inbox"}},
  ready_not_inbox:   {s: {model: {repo: "o/r"}, capabilities: [{id: "mark-ready"}]},                  x: {id: "WS-1", issue_id: "o/r#1", workflow: "ready"}},
  no_issue:          {s: {model: {repo: "o/r"}, capabilities: [{id: "mark-ready"}]},                  x: {id: "WS-1", workflow: "inbox"}},
  null_x:            {s: {model: {repo: "o/r"}, capabilities: [{id: "mark-ready"}]},                  x: null},
};
const out = {};
for (const [name, c] of Object.entries(cases)) out[name] = m.readyAvailable(c.s, c.x);
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_mark_ready_is_offered_only_for_a_live_inbox_issue_with_the_registered_action():
    """The same fail-closed split as compose: a live host that registered
    `mark-ready`, a mission the OS reads as inbox (prefixed or not), carrying
    an Issue. Preview data authorizes no mutation even where a fixture grants
    `view:prepare` -- navigation -- and a mission that is already ready is
    never offered the transition again."""
    out = _run_node(READY_AVAILABLE_SCRIPT % {"path": json.dumps(str(RENDERER))})
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    for k in ("live_with_cap", "live_prefixed"):
        assert got[k] is True, f"{k}: the inbox promotion must be offered"
    for k in ("live_without_cap", "live_wrong_cap", "synthetic_granted",
              "ready_not_inbox", "no_issue", "null_x"):
        assert got[k] is False, f"{k}: mark-ready must fail closed"


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_mark_ready_payload_is_exactly_the_confirmed_transition():
    """The POST is the selected Issue, the typed approval reference (trimmed,
    under the field name the action host's request schema requires) and an
    explicit confirmation -- nothing else is invented browser-side."""
    script = """
const m = require(%(path)s);
console.log(JSON.stringify(m.markReadyPayload({issue_id: "o/r#7"}, "  op-approval-7  ")));
console.log(JSON.stringify(m.markReadyPayload({issue_id: "o/r#8"}, null)));
""" % {"path": json.dumps(str(RENDERER))}
    out = _run_node(script)
    assert out.returncode == 0, out.stderr
    lines = [line for line in out.stdout.splitlines() if line.strip()]
    assert json.loads(lines[0]) == {
        "action_id": "mark-ready", "issue_id": "o/r#7",
        "approval_ref": "op-approval-7", "confirm": True,
    }
    assert json.loads(lines[1]) == {
        "action_id": "mark-ready", "issue_id": "o/r#8",
        "approval_ref": "", "confirm": True,
    }


@pytest.mark.skipif(NODE is None, reason="node unavailable")
def test_the_mark_ready_control_renders_only_in_the_authorized_shape():
    """The transition button appears beside the row only where
    `readyAvailable` holds; everywhere else the row renders with no
    transition control at all -- never a control that can only be refused."""
    script = """
const m = require(%(path)s);
const missions = [{id: "WS-1", title: "Inbox one", workflow: "inbox", issue_id: "o/r#1"}];
function renderWith(state) {
  const el = {innerHTML: "", querySelectorAll: function () { return []; }};
  m.render(el, {state});
  return el.innerHTML;
}
console.log(JSON.stringify({
  authorized: renderWith({model: {repo: "o/r", workstreams: missions}, capabilities: [{id: "mark-ready"}], token: "t1"}).includes("data-mission-ready=\\"o/r#1\\""),
  without_cap: renderWith({model: {repo: "o/r", workstreams: missions}, capabilities: []}).includes("data-mission-ready="),
  synthetic: renderWith({model: {synthetic: true, repo: "o/r", workstreams: missions}, capabilities: [{id: "mark-ready"}]}).includes("data-mission-ready="),
}));
""" % {"path": json.dumps(str(RENDERER))}
    out = _run_node(script)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["authorized"] is True
    assert got["without_cap"] is False
    assert got["synthetic"] is False


def test_the_mark_ready_dialog_mirrors_the_recovery_gate(source):
    """The same operator gate as `beginRecovery` in
    app-renderer-decisions-evidence.js, field for field: a modal `<dialog>`
    form carrying the reviewed-action-boundary explanation of the
    inbox -> ready transition, a REQUIRED approval-reference input, an alert
    region for refusals, and a distinct confirm button."""
    assert 'document.createElement("dialog")' in source
    assert '<p class="eyebrow">Reviewed action boundary</p>' in source
    assert "workflow:inbox" in source and "workflow:ready" in source
    assert 'data-m-ready-approval required autocomplete="off"' in source
    assert '<div data-m-ready-error role="alert"></div>' in source
    assert '<button value="confirm" class="primary-action">Confirm ready</button>' in source
    # The client-side refusal must exist: an empty reference never reaches
    # the host.
    assert '"Approval reference is required."' in source


def test_the_mark_ready_wiring_is_bound_and_fails_closed_on_a_stale_row(source):
    """The click handler resolves the button's Issue against the CURRENT
    projection (not the one this render saw) and opens the dialog only for a
    mission that is still there; a stale row re-renders the list instead of
    transitioning a mission the operator is no longer looking at."""
    assert 'qa("[data-mission-ready]").forEach(function (b) {' in source
    assert "if (!x) { renderStart(winEl, ctx); return; }" in source
    assert "beginMarkReady(x, s);" in source


def test_mark_ready_denials_are_rendered_not_softened(source):
    """TransitionDenied and 409 must land in the dialog's alert region with
    the host's own recovery text -- never silently swallowed into a success
    rendering."""
    post = source[source.index("function beginMarkReady"):]
    post = post[:post.index("function readyButton")]
    assert "if (!res.ok) {" in post
    assert "(err.recovery || err.message)" in post
    assert 'dlg.querySelector("[data-m-ready-error]").textContent' in post
    assert "dlg.showModal();" in post
    # Success says what happened and what it did NOT do.
    assert "data-m-ready-done" in post
    assert "workflow:ready" in post


def test_the_start_surface_posts_exactly_issue_create_and_mark_ready(source):
    """The surface's full mutation vocabulary: the compose write and the
    operator-gated inbox promotion. No third action id may appear, and no
    launch-shaped control either -- so the first step of the flow can never
    become a second, ungated launch path."""
    ids = set(re.findall(r'action_id:\s*"([^"]+)"', source))
    assert ids == {"issue-create", "mark-ready"}
    assert source.count('fetch("api/action"') == 2
    assert source.count('"X-Cortxt-Token": s.token') == 2
    assert "claim-run" not in source
    assert "data-launch-start" not in source


# --- #619: both edited files stay byte-identical across the mirror ----------

@pytest.mark.parametrize("name", ["app-renderer-start-mission.js", "work-console.js"])
def test_the_619_files_are_byte_identical_across_the_mirror(name):
    assert (WIDGET / name).read_bytes() == (MIRROR / name).read_bytes(), \
        f"{name} diverged between agent-platform/widget and site/public/widgets"
