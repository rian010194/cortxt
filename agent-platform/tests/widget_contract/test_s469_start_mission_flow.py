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
