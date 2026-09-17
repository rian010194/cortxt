"""Contract tests for the Cortxt OS dialogue app renderer (B1.5d).

The shell is plain HTML/CSS/JS with no JS test runner in this repo, so these
tests inspect the renderer source and drive the pure exported helpers in a
DOM-less Node runtime, the same way the sibling shell tests do
(``test_os_shell_core.py`` precedent). The site mirror is covered by byte
parity (``test_os_shell_core.py``), so the Node tests ``require()`` the
``agent-platform/widget`` copy only.

Every assertion below is pinned to the frozen route table of
``b15c-order.md`` section D2 and the behaviour rows of ``b15d-order.md``
(T-D1 .. T-D15). A missing ``node`` binary is a FAILURE, never a skip.
"""
import json
import re
import subprocess
from pathlib import Path

WIDGET = Path(__file__).resolve().parents[2] / "widget"
RENDERER = WIDGET / "app-renderer-dialogue.js"
SOURCE = RENDERER.read_text(encoding="utf-8")

FROZEN_ROUTES = {
    "sessions": "api/dialogue/sessions",
    "session": "api/dialogue/session",
    "connect": "api/dialogue/connect",
    "turn": "api/dialogue/turn",
    "cancel": "api/dialogue/cancel",
}


def _run_node(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["node", "-e", script], capture_output=True, text=True,
                          encoding="utf-8", timeout=60)


def _require_expr(expr: str) -> subprocess.CompletedProcess:
    """``require()`` the widget copy and evaluate an expression that may use
    ``d`` (the module) and ``M`` (a pretty-printed JSON of it, unused)."""
    return _run_node(
        "const d=require(%s);\n%s\n" % (json.dumps(str(RENDERER)), expr)
    )


# --- T-D1: source hygiene ----------------------------------------------------

def test_td1_source_has_no_invented_data_words_or_extra_routes():
    forbidden = re.compile(r"fixture|synthetic|demo|sample|mock", re.IGNORECASE)
    assert not forbidden.search(SOURCE), "renderer mentions an invented-data word"
    api_paths = re.findall(r"api/[a-z/-]+", SOURCE)
    allowed = set(FROZEN_ROUTES.values())
    assert set(api_paths) <= allowed, api_paths
    assert api_paths, "renderer lost its route constants"
    routes = re.search(r"var ROUTES = \{.*?\};", SOURCE, re.DOTALL)
    assert routes, "ROUTES constant missing"
    for key, path in FROZEN_ROUTES.items():
        assert re.search(r"\b%s:\s*\"%s\"" % (key, re.escape(path)), routes.group(0)), key


# --- T-D2: request failure classification ------------------------------------

def test_td2_network_failure_maps_to_error_state_and_no_extra_urls():
    script = """
const d=require(%s);
(async () => {
  const urls = [];
  const stub = async (u, i) => { urls.push(u); throw new Error("network down"); };
  const r = await d.request({ fetch: stub, token: "t" }, "GET", "api/dialogue/sessions");
  if (r.httpStatus !== 0 || r.body !== null) process.exit(2);
  const v0 = d.listView(0, null);
  if (v0.state !== "error") process.exit(3);
  const v5 = d.listView(500, {schema_version: 1, status: "error",
                              error: {kind: "dialogue_error", message: "boom"}});
  if (v5.state !== "error") process.exit(4);
  const html = d.renderList({state: "error", kind: "dialogue_error",
                             sentence: "The dialogue host answered with an error: dialogue_error",
                             storeKind: null, sessions: [], unreadable: []});
  if (!html.includes('data-dialogue-state="error"')) process.exit(5);
  if (!html.includes("dialogue_error")) process.exit(6);
  if (urls.some(u => !u.startsWith("api/"))) process.exit(7);
  console.log("ok");
})();
""" % json.dumps(str(RENDERER))
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- T-D3: list states ---------------------------------------------------------

def test_td3_empty_unavailable_and_partial_are_distinct():
    script = """
const d=require(%s);
const ok200 = d.listView(200, {status: "ok", sessions: [], unreadable: [], root_exists: false});
if (ok200.state !== "empty") process.exit(2);
const un503 = d.listView(503, {schema_version: 1, status: "unavailable",
                               error: {kind: "dialogue_unavailable", message: "m"}});
if (un503.state !== "unavailable") process.exit(3);
const partial = d.listView(200, {status: "partial",
  sessions: [{cortxt_session_id: "s", created_at: "t", turn_count: 1, open_turn_id: null, connected: false}],
  unreadable: [{entry: "session_x", kind: "integrity_error"}]});
if (partial.state !== "partial") process.exit(4);
const html = d.renderList(partial);
if (!html.includes("session_x") || !html.includes("integrity_error")) process.exit(5);
console.log("ok");
""" % json.dumps(str(RENDERER))
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- T-D4: request headers ------------------------------------------------------

def test_td4_every_request_carries_token_and_no_store():
    script = """
const d=require(%s);
(async () => {
  const inits = [];
  const stub = async (u, i) => { inits.push(i); return {status: 200, json: async () => ({})}; };
  const deps = { fetch: stub, token: "tok-1" };
  await d.request(deps, "GET", "api/dialogue/sessions");
  await d.request(deps, "POST", "api/dialogue/turn", {body: {}});
  if (inits.length !== 2) process.exit(2);
  for (const i of inits) {
    if (i.headers["X-Cortxt-Token"] !== "tok-1") process.exit(3);
    if (i.cache !== "no-store") process.exit(4);
  }
  if (inits[1].headers["Content-Type"] !== "application/json") process.exit(5);
  console.log("ok");
})();
""" % json.dumps(str(RENDERER))
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- T-D5: fail closed without a token -------------------------------------------

def test_td5_no_token_means_unavailable_and_no_fetch():
    script = """
const d=require(%s);
let calls = 0;
globalThis.fetch = async () => { calls += 1; return {status: 200, json: async () => ({})}; };
function fakeEl() {
  return {innerHTML: "", querySelector() { return null; }, querySelectorAll() { return []; }};
}
const el1 = fakeEl();
d.renderDialogue(el1, {state: {token: null, model: {synthetic: true}}});
if (!el1.innerHTML.includes('data-dialogue-state="unavailable"')) process.exit(2);
if (calls !== 0) process.exit(3);
const el2 = fakeEl();
d.renderDialogue(el2, {state: {token: null}});
if (!el2.innerHTML.includes('data-dialogue-state="unavailable"')) process.exit(4);
if (calls !== 0) process.exit(5);
console.log("ok");
""" % json.dumps(str(RENDERER))
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- T-D6: turn status table -------------------------------------------------------

def test_td6_turn_status_transitions():
    script = """
const d=require(%s);
const T1 = "turn_a", T2 = "turn_b";
const fin = (outcome) => ({sequence: 9, event_type: "dialogue.turn.finished",
                           payload: {turn_id: T1, outcome: outcome, stop_reason: null, detail: null}});
const upd = (t) => ({sequence: 5, event_type: "dialogue.updates",
                     payload: {turn_id: t, events: []}});
const table = [
  [[], T1, "posting", "sending"],
  [[], T1, "accepted", "sending"],
  [[upd(T1)], T1, "accepted", "streaming"],
  [[fin("completed")], T1, "accepted", "completed"],
  [[fin("failed")], T1, "accepted", "failed"],
  [[fin("interrupted")], T1, "accepted", "failed"],
  [[fin("cancelled")], T1, "accepted", "cancelled"],
  [[upd(T2)], T1, "accepted", "sending"],
];
for (const [events, turnId, phase, want] of table) {
  const got = d.turnStatus(events, turnId, phase);
  if (got !== want) { console.error(turnId + " " + phase + " -> " + got + " want " + want); process.exit(10); }
}
console.log("ok");
""" % json.dumps(str(RENDERER))
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


def _transcript_events():
    return [
        {"sequence": 0, "event_type": "session.created", "payload": {}},
        {"sequence": 1, "event_type": "dialogue.acp.bound", "payload": {"acp_session_id": "a"}},
        {"sequence": 2, "event_type": "dialogue.turn.started",
         "payload": {"turn_id": "turn_a", "prompt_text": "Hi there"}},
        {"sequence": 3, "event_type": "dialogue.updates", "payload": {"turn_id": "turn_a", "events": [
            {"wire_seq": 40, "origin": "live", "kind": "session_update",
             "update_type": "agent_message_chunk",
             "payload": {"update": {"content": {"type": "text", "text": "Hel"}}}, "decision": None},
            {"wire_seq": 41, "origin": "live", "kind": "session_update",
             "update_type": "agent_message_chunk",
             "payload": {"update": {"content": {"type": "text", "text": "lo"}}}, "decision": None},
        ]}},
        {"sequence": 4, "event_type": "dialogue.turn.finished",
         "payload": {"turn_id": "turn_a", "outcome": "completed", "stop_reason": "end_turn",
                     "detail": None}},
    ]


def _node_literal(obj) -> str:
    return json.dumps(obj)


# --- T-D7: foldTranscript ordering and history marking ------------------------------

def test_td7_fold_marks_history_and_inserts_one_divider():
    script = """
const d=require(%s);
const events = %s;
const items = d.foldTranscript(events, 4);
const types = items.map(i => i.type);
if (JSON.stringify(types) !== JSON.stringify(["prompt", "reply", "outcome", "history_divider"])) process.exit(2);
const reply = items.find(i => i.type === "reply");
if (!reply || reply.text !== "Hello") process.exit(3);
if (!items.every(i => i.history === true)) process.exit(4);
if (items.filter(i => i.type === "history_divider").length !== 1) process.exit(5);
console.log("ok");
""" % (json.dumps(str(RENDERER)), _node_literal(_transcript_events()))
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- T-D8: load markers --------------------------------------------------------------

def test_td8_load_markers_render_replay_and_fresh_at_position():
    script = """
const d=require(%s);
const events = %s;
events.push({sequence: 5, event_type: "dialogue.session.loaded",
             payload: {replay_boundary: 4, replayed_update_count: 3, out_of_turn_count: 0}});
events.push({sequence: 6, event_type: "dialogue.session.loaded",
             payload: {replay_boundary: 5, replayed_update_count: 0, out_of_turn_count: 0}});
const items = d.foldTranscript(events, 4);
const replay = items.filter(i => i.type === "load_marker" && i.divider === "replay");
const fresh = items.filter(i => i.type === "load_marker" && i.divider === "fresh");
if (replay.length !== 1 || !replay[0].text.includes("3")) process.exit(2);
if (fresh.length !== 1 || !fresh[0].text.includes("started fresh")) process.exit(3);
const order = items.map(i => i.type).join("|");
if (order !== "prompt|reply|outcome|history_divider|load_marker|load_marker") process.exit(4);
console.log("ok");
""" % (json.dumps(str(RENDERER)), _node_literal(_transcript_events()))
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- T-D9: denied permissions are visible ---------------------------------------------

def test_td9_denied_permission_renders_with_marker():
    script = """
const d=require(%s);
const events = %s;
events.push({sequence: 6, event_type: "dialogue.updates", payload: {turn_id: "turn_a", events: [
  {"wire_seq": 50, "origin": "live", "kind": "permission_request", "update_type": null,
   "payload": {"toolCall": {"title": "write a file"}}, "decision": "denied"}]}});
const items = d.foldTranscript(events, 4);
const perm = items.find(i => i.type === "permission");
if (!perm) process.exit(2);
if (!perm.text.includes("denied")) process.exit(3);
const html = d.renderTranscript(items);
if (!html.includes('data-dialogue-permission="denied"')) process.exit(4);
if (!html.includes("denied")) process.exit(5);
console.log("ok");
""" % (json.dumps(str(RENDERER)), _node_literal(_transcript_events()))
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- T-D10: wire-sequence numbers never drive order -----------------------------------

def test_td10_order_follows_event_sequence_not_wire_seq():
    script = """
const d=require(%s);
const events = [
  {sequence: 0, event_type: "session.created", payload: {}},
  {sequence: 1, event_type: "dialogue.turn.started",
   payload: {turn_id: "turn_a", prompt_text: "q"}},
  {sequence: 3, event_type: "dialogue.updates", payload: {turn_id: "turn_a", events: [
    {"wire_seq": 40, "origin": "live", "kind": "session_update",
     "update_type": "agent_message_chunk",
     "payload": {"update": {"content": {"type": "text", "text": "one "}}}, "decision": null}]}},
  {sequence: 4, event_type: "dialogue.updates", payload: {turn_id: "turn_a", events: [
    {"wire_seq": 3, "origin": "live", "kind": "session_update",
     "update_type": "agent_message_chunk",
     "payload": {"update": {"content": {"type": "text", "text": "two"}}}, "decision": null}]}},
];
const items = d.foldTranscript(events, -1);
const reply = items.find(i => i.type === "reply");
if (!reply || reply.text !== "one two") process.exit(2);
console.log("ok");
""" % json.dumps(str(RENDERER))
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- T-D11: every server string is escaped ---------------------------------------------

def test_td11_server_strings_are_escaped():
    script = """
const d=require(%s);
const evil = '<img src=x onerror=1>';
const events = [
  {sequence: 1, event_type: "dialogue.turn.started",
   payload: {turn_id: "turn_a", prompt_text: evil}},
  {sequence: 2, event_type: "dialogue.updates", payload: {turn_id: "turn_a", events: [
    {"wire_seq": 1, "origin": "live", "kind": "session_update",
     "update_type": "agent_message_chunk",
     "payload": {"update": {"content": {"type": "text", "text": evil}}}, "decision": null}]}},
  {sequence: 3, event_type: "dialogue.turn.finished",
   payload: {turn_id: "turn_a", outcome: "completed", stop_reason: "end_turn", detail: null}},
];
const t = d.renderTranscript(d.foldTranscript(events, -1));
if (!t.includes("&lt;img")) process.exit(2);
if (t.includes("<img")) process.exit(3);
const lv = d.listView(200, {status: "partial",
  sessions: [{cortxt_session_id: evil, created_at: "", turn_count: 0, open_turn_id: null, connected: false}],
  unreadable: [{entry: evil, kind: evil}]});
const l = d.renderList(lv);
if (!l.includes("&lt;img") || l.includes("<img src=x")) process.exit(4);
const ef = d.classifyFailure(500, {error: {kind: "dialogue_error", message: evil}});
const fe = d.renderList({state: "error", kind: ef.kind, sentence: ef.sentence,
                         storeKind: null, sessions: [], unreadable: []});
if (!fe.includes("&lt;img") || fe.includes("<img src=x")) process.exit(5);
console.log("ok");
""" % json.dumps(str(RENDERER))
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- T-D12: failure classification for every contract kind ------------------------------

def test_td12_classify_failure_covers_every_kind():
    script = """
const d=require(%s);
const kinds = %s;
const unavailable = new Set(["dialogue_unavailable", "acp_unavailable",
                             "agent_unavailable", "agent_capacity"]);
for (const k of kinds) {
  const status = unavailable.has(k) ? 503 : 500;
  const f = d.classifyFailure(status, {schema_version: 1, status: "unavailable",
                                       error: {kind: k, message: "m"}});
  if (f.state !== (unavailable.has(k) ? "unavailable" : "error")) process.exit(10);
  if (!f.sentence.includes(k)) process.exit(11);
  const html = d.renderList({state: f.state, kind: f.kind, sentence: f.sentence,
                             storeKind: null, sessions: [], unreadable: []});
  if (!html.includes(k)) process.exit(12);
}
console.log("ok");
""" % (json.dumps(str(RENDERER)),
       _node_literal([
           "not_found", "method_not_allowed", "authorization_denied",
           "dialogue_unavailable", "validation_error", "invalid_cursor",
           "rate_limited", "dialogue_writer_busy", "session_not_found",
           "session_unreadable", "cursor_ahead", "acp_unavailable",
           "agent_unavailable", "agent_capacity", "already_connected",
           "not_connected", "turn_in_progress", "turn_not_open",
           "agent_connection_lost", "agent_protocol_error", "sequence_conflict",
           "store_refused", "dialogue_error"]))
    out = _run_node(script)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- T-D14: site mirror parity ------------------------------------------------------------

def test_td14_site_mirror_is_byte_identical():
    mirror = Path(__file__).resolve().parents[3] / "site" / "public" / "widgets" / "app-renderer-dialogue.js"
    assert RENDERER.read_bytes() == mirror.read_bytes()


# --- T-D15: POST only from the four click handlers -------------------------------------------

_ALLOWED_POST_FNS = {"onCreate", "onConnect", "onSend", "onCancel"}


def _all_function_spans(source: str):
    """Yield (name, start, brace_end) for every `function name(...)` or
    `async function name(...)` occurrence, nested or not (brace-matched)."""
    for m in re.finditer(r"(?:^|\n|\{)\s*(?:async )?function (\w+)\s*\(", source):
        name = m.group(1)
        i = source.index("(", m.end() - 1)
        depth = 0
        body_start = None
        while i < len(source):
            c = source[i]
            if body_start is None:
                if c == "{":
                    depth = 1
                    body_start = i + 1
            else:
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        yield name, m.start(), i
                        break
            i += 1


def test_td15_post_only_inside_click_handlers():
    """The only POST call sites sit inside the four click handlers
    (create, connect, send, cancel); every other function body — including
    renderDialogue, the poll chain and the open/read layer — contains none."""
    fns = list(_all_function_spans(SOURCE))
    names = {name for name, _s, _e in fns}
    assert set(_ALLOWED_POST_FNS) <= names, "click handlers missing: %s" % (_ALLOWED_POST_FNS - names)
    for match in re.finditer(r'"POST"', SOURCE):
        enclosing = [name for name, start, end in fns if start <= match.start() <= end]
        assert enclosing, "POST at offset %d outside any function" % match.start()
        innermost = enclosing[-1]
        assert innermost in _ALLOWED_POST_FNS, \
            "POST inside %s (line %d), not a click handler" % (innermost, SOURCE[:match.start()].count("\n") + 1)
    # and each handler really POSTs
    for handler in sorted(_ALLOWED_POST_FNS):
        assert any(name == handler and '"POST"' in SOURCE[start:end]
                   for name, start, end in fns), "%s lost its POST call site" % handler


# --- T-D13: window registration across both carriers -----------------------------

APPS = json.loads((WIDGET / "apps.json").read_text(encoding="utf-8"))
HTML = (WIDGET / "index.html").read_text(encoding="utf-8")
SOURCE_CONSOLE = (WIDGET / "work-console.js").read_text(encoding="utf-8")
MIRROR = Path(__file__).resolve().parents[3] / "site" / "public" / "widgets"
MIRROR_HTML = (MIRROR / "index.html").read_text(encoding="utf-8")
MIRROR_CONSOLE = (MIRROR / "work-console.js").read_text(encoding="utf-8")


def test_td13_dialogue_app_is_registered_as_a_window_app():
    entry = {"id": "dialogue", "title": "Dialogue", "short": "Dialogue",
             "icon": "dialogue", "route": "/dialogue", "kind": "window",
             "window": "dialogue", "widgets": None,
             "capabilities": ["read:dialogue-session", "act:dialogue-turn"],
             "mode": "operator", "mobile": True}
    by_id = {a["id"]: a for a in APPS["apps"]}
    assert by_id["dialogue"] == entry
    assert APPS["apps"][-1]["id"] == "dialogue"
    # both index.html carriers: window section + body + script before work-console.js
    for html in (HTML, MIRROR_HTML):
        assert 'data-window="dialogue"' in html
        assert "data-dialogue-body" in html
        assert 'src="app-renderer-dialogue.js"' in html
        assert html.index('src="app-renderer-dialogue.js"') < html.index('src="work-console.js"')
    # both work-console copies: open-gated render + poller stop hook
    for console in (SOURCE_CONSOLE, MIRROR_CONSOLE):
        assert "state.ui.open.dialogue" in console
        assert "_cortxtStopDialogue" in console
    # the renderer registers itself into the shared registry
    assert 'OSRenderer.register("dialogue", renderDialogue' in SOURCE
