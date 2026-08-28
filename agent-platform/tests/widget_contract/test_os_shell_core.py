"""Deterministic checks for the Cortxt OS shell core (issue #418).

The shell is plain HTML/CSS/JS with no JS test runner in this repo, so these
tests inspect the shell source the same way the sibling widget-host tests do
(string / JSON assertions). They cover the acceptance criteria: one
authoritative app registry, separated shell state, Workstream-context
propagation and persistence, desktop window lifecycle, mobile single-app
routing, responsive transition, and synthetic/authority parity with the site
mirror.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WIDGET = Path(__file__).resolve().parents[2] / "widget"
MIRROR = Path(__file__).resolve().parents[3] / "site" / "public" / "widgets"

APPS = json.loads((WIDGET / "apps.json").read_text(encoding="utf-8"))
HTML = (WIDGET / "index.html").read_text(encoding="utf-8")
CSS = (WIDGET / "os.css").read_text(encoding="utf-8")
JS = (WIDGET / "work-console.js").read_text(encoding="utf-8")
RENDERER = (WIDGET / "os-renderer.js").read_text(encoding="utf-8")
D_RENDERER = (WIDGET / "app-renderer-decisions-evidence.js").read_text(encoding="utf-8")

PORTED = {"work-console", "decisions", "evidence"}
DEFERRED = {"execution", "policies", "atlas", "connections"}


# --- one authoritative app registry ----------------------------------------

def test_registry_ids_are_unique():
    ids = [app["id"] for app in APPS["apps"]]
    assert len(ids) == len(set(ids)), f"duplicate app id in apps.json: {ids}"


def test_registry_is_the_single_source_for_ported_and_deferred_apps():
    by_id = {app["id"]: app for app in APPS["apps"]}
    for app_id in PORTED:
        assert by_id[app_id]["kind"] in {"pinned", "window"}
        assert "window" in by_id[app_id]
    assert by_id["work-console"]["kind"] == "pinned"
    for app_id in DEFERRED:
        assert by_id[app_id]["kind"] == "deferred", app_id
    # every non-"all" entry keeps icon + route (guards apps-manifest test too)
    for app in APPS["apps"]:
        if app["id"] == "all":
            continue
        assert "icon" in app and "route" in app


def test_shell_markup_has_no_hardcoded_per_app_button_list():
    # The drawer and mobile nav are rendered from the registry, not hard-coded.
    assert 'data-app-list' in HTML and 'data-mobile-nav' in HTML
    assert HTML.count('data-app="') == 0
    assert 'apps.json' in JS
    assert 'renderChrome' in JS and '[data-app-list]' in JS and '[data-mobile-nav]' in JS


def test_maker_studio_host_excludes_deferred_apps_from_its_rail():
    maker = (WIDGET / "maker.html").read_text(encoding="utf-8")
    assert 'filter(function(a){ return a.kind !== "deferred"; })' in maker


# --- shell state separation ----------------------------------------------

def test_state_separates_ui_context_and_app_local_view():
    assert 'ui:{open:' in JS and 'zTop:' in JS and 'mobileApp:' in JS
    # S2: context carries both the legacy workstreamId and the activeWorkstreamId
    # ("all" is a distinct global context).
    assert 'context:{workstreamId:null,activeWorkstreamId:null}' in JS
    assert 'apps:{"work-console":{panel:' in JS


# --- context propagation + persistence ---------------------------------

def test_single_persistence_key_carries_ui_context_app_and_windows():
    # Schema v2 (S2) persists ui/context/apps plus the WindowInstance model,
    # dock favorites, and desktop layout under one key; v1 blobs migrate.
    assert 'SHELL_KEY="cortxt-os-shell"' in JS
    assert 'localStorage.setItem(SHELL_KEY,JSON.stringify({v:2,ui:state.ui,context:state.context,apps:state.apps,windows:state.windows,dockFavorites:state.dockFavorites,desktopLayout:state.desktopLayout}))' in JS
    assert 'function restore()' in JS and 'localStorage.getItem(SHELL_KEY)' in JS
    assert 'saved.v===2' in JS  # schema-version gate
    assert 'syncWindowsFromUi()' in JS  # migration path for v1 blobs


def test_selecting_a_workstream_propagates_to_every_mounted_app():
    assert 'function propagateContext()' in JS
    for selector in ('[data-active-context]', '[data-decisions-body]',
                     '[data-evidence-body]', '[data-studio-frame]'):
        assert selector in JS
    assert 'function selectWorkstream(id){state.context.workstreamId=id;persist();propagateContext()}' in JS
    assert 'selectWorkstream(item.id)' in JS


def test_reload_restores_selected_workstream_by_id_not_by_position():
    # currentItem() only falls back to the first item when nothing was stored.
    assert 'list.find(function(x){return x.id===wanted})' in JS
    assert 'if(!wanted&&list.length)return list[0]' in JS
    # render() no longer force-selects the first item.
    assert 'select(items[0])' not in JS


# --- desktop window lifecycle ------------------------------------------

def test_desktop_lifecycle_controls_exist_for_decisions_and_evidence():
    for app_id in ("decisions", "evidence"):
        assert f'data-window-focus="{app_id}"' in HTML
        assert f'data-window-min="{app_id}"' in HTML
        assert f'data-close-window="{app_id}"' in HTML
    # Work Console is pinned: focus + minimise but never close.
    assert 'data-window="console"' in HTML
    assert 'data-close-window="console"' not in HTML
    for fn in ('function openApp', 'function focusApp', 'function closeApp',
               'function setMin', 'function toggleArrange'):
        assert fn in JS
    assert 'isPinned(id)' in JS  # pinned app cannot be closed
    assert 'state.ui.z[id]=++state.ui.zTop' in JS  # focus raises z-order


def test_desktop_layout_survives_reload():
    # open / minimised / z-order all live in the persisted ui blob.
    assert 'state.ui.open' in JS and 'state.ui.min' in JS and 'state.ui.z' in JS
    assert 'x.classList.toggle("minimized"' in JS
    assert '.app-window.minimized' in CSS


# --- mobile single-app routing --------------------------------------

def test_mobile_renders_exactly_one_app_without_window_chrome():
    assert 'function isNarrow(){return window.innerWidth<=NARROW}' in JS
    # narrow branch hides every window except the active one.
    assert 'x.hidden=x.dataset.window!==w' in JS
    assert 'state.ui.mobileApp' in JS
    assert '@media(max-width:720px)' in CSS
    assert '.window-actions{display:none}' in CSS  # no desktop title-bar controls
    assert '.mobile-nav{position:fixed' in CSS and 'display:flex' in CSS


def test_mobile_nav_switches_among_the_three_implemented_apps():
    # mobile nav buttons come from the registry, deferred apps excluded.
    assert 'if(mnav&&!deferred)' in JS
    assert 'm.addEventListener("click",function(){openApp(a.id)})' in JS


# --- live responsive transition -----------------------------------

def test_resize_reapplies_view_from_persisted_state_without_reload():
    assert 'window.addEventListener("resize"' in JS
    assert 'setTimeout(applyView,120)' in JS
    # applyView derives from state.ui / state.ui.mobileApp, it does not re-init.
    assert 'function applyView()' in JS
    assert 'location.reload' not in JS


# --- synthetic determinism / authority boundary preserved -----------

def test_authority_boundary_and_synthetic_mode_are_unchanged():
    assert 'fetch("api/workstreams"' in JS
    assert 'fetch("fixtures/workstreams.json"' in JS
    assert 'The app failed closed. No evidence or decision action is exposed.' in JS
    assert '"X-Cortxt-Token":state.token' in JS
    assert 'state.model.synthetic' in JS


# --- canonical design system, no private palette -------------------

ROLE_VARS = ("--bg", "--surface", "--layer", "--hover", "--stroke", "--strong",
             "--text", "--muted", "--dim", "--accent", "--warn", "--bad")


def test_shell_css_has_no_private_palette_and_consumes_canonical_tokens():
    # ADR-043: the OS consumer loads canonical tokens rather than defining a
    # private palette. Every colour role in :root now resolves from a
    # --token-* custom property (offline hex only as the var() fallback), and
    # os.css never *defines* a --token-* property of its own.
    root = CSS[CSS.index(":root{") + len(":root{"):CSS.index("}", CSS.index(":root{"))]
    for role in ROLE_VARS:
        decl = root.split(role + ":", 1)[1].split(";", 1)[0]
        assert decl.startswith("var(--token-") or decl.startswith("color-mix("), (role, decl)
    assert "var(--token-" in CSS
    assert not re.search(r"--token-[\w-]+\s*:(?!,)", CSS), "os.css must not define --token-* properties"


def test_os_shell_loads_canonical_tokens_via_widget_host_adapter():
    # Reuse the existing Widget Host adapter (maker.js -> WidgetMaker.applyTokens),
    # loaded before the shell script, then fetch the canonical tokens.json.
    assert '<script src="maker.js"></script>' in HTML
    assert HTML.index('src="maker.js"') < HTML.index('src="work-console.js"')
    assert "function loadTokens()" in JS
    assert 'fetch("tokens.json"' in JS
    assert "window.WidgetMaker" in JS and "applyTokens" in JS
    assert "wm.defaultTokens" in JS  # offline fallback to the adapter's own tokens


@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
def test_window_tiling_yields_distinct_non_overlapping_rectangles():
    # Behavioural check: execute the shell's own deterministic layout function
    # and prove real geometry -- distinct, in-bounds, pairwise non-overlapping
    # rectangles -- for 1, 2 and 3 open secondary windows.
    script = (
        "const m=require(%s);"
        "const eps=1e-9;"
        "function ov(a,b){return a.x<b.x+b.w-eps&&b.x<a.x+a.w-eps&&a.y<b.y+b.h-eps&&b.y<a.y+a.h-eps;}"
        "for(const ids of [['decisions'],['decisions','evidence'],['decisions','evidence','studio']]){"
        "  const r=m.tileRects(ids);const keys=['work-console',...ids];"
        "  for(const k of keys){const g=r[k];"
        "    if(!g){console.error('missing',k);process.exit(2);}"
        "    if(g.x<-eps||g.y<-eps||g.x+g.w>1+eps||g.y+g.h>1+eps){console.error('oob',k,JSON.stringify(g));process.exit(3);}}"
        "  for(let i=0;i<keys.length;i++)for(let j=i+1;j<keys.length;j++){"
        "    const A=r[keys[i]],B=r[keys[j]];"
        "    if(JSON.stringify(A)===JSON.stringify(B)){console.error('identical',keys[i],keys[j]);process.exit(4);}"
        "    if(ov(A,B)){console.error('overlap',keys[i],keys[j],JSON.stringify(A),JSON.stringify(B));process.exit(5);}}"
        "}"
        "console.log('ok');"
    ) % json.dumps(str(WIDGET / "work-console.js"))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


def test_shell_markup_and_css_carry_real_movable_resizable_geometry():
    # No more shared centred rectangle: the placebo "arrange" CSS is gone and
    # each window has a drag surface (window-bar) plus a resize handle.
    assert "left:50%;top:50%" not in CSS
    assert ".canvas.arranging" not in CSS
    assert "data-window-resize" in HTML and HTML.count("data-window-resize") >= 3
    assert ".canvas.compose .window-resize{display:block}" in CSS
    assert "function applyGeom()" in JS and "function beginWindowDrag(" in JS
    assert "state.ui.geom" in JS  # persisted per-window rects


def test_mobile_shows_one_fullscreen_app_with_no_window_chrome():
    mq = CSS[CSS.index("@media(max-width:720px){"):]
    mq = mq[:mq.index("@media", 1)]
    assert ".window-bar{display:none}" in mq         # no desktop window bar on mobile
    assert ".window-resize{display:none!important}" in mq
    assert ".mobile-nav{position:fixed" in mq and "bottom:0" in mq  # switcher stays in viewport
    assert "overflow-x:hidden" in CSS               # shell never wider than the viewport
    assert "100dvh" in CSS                          # dynamic viewport height, nav not clipped
    assert "position:static!important" in mq        # absolute geometry is dropped on mobile


# --- slice A: focus, z-order, direct window interaction (#421) ---------

def test_pointer_down_on_window_surface_gives_focus():
    # The shell listens for pointerdown on any [data-window] surface (except
    # interactive controls, which keep their own behavior) and focuses it.
    assert 'document.addEventListener("pointerdown"' in JS
    assert 'ev.target.closest("[data-window]")' in JS
    assert 'focusApp(appIdForWindow(win.dataset.window))' in JS
    assert 'if(ev.target.closest("button,a,input"))return' in JS


def test_move_resize_do_not_require_arrange_mode():
    # Basic window functions must not be gated behind Arrange: the drag gate
    # only rejects narrow (mobile) viewports and interactive controls.
    assert 'if(!state.ui.arranging||isNarrow())return;' not in JS
    assert 'function beginWindowDrag(' in JS
    assert 'initCompose();' in JS  # bar + resize handles always wired


def test_focus_and_z_order_are_consistent():
    # One source of truth: the active window is the open, non-minimized app
    # with the highest z-order; the focused class is derived from it.
    assert 'function activeWindowId()' in JS
    assert 'state.ui.z[id]=++state.ui.zTop' in JS
    assert 'id===activeWindowId()' in JS
    assert '.app-window.focused' in CSS


def test_arrange_is_explicit_layout_only():
    # Arrange stays an explicit layout action (compose class + aria-pressed),
    # and is no longer a prerequisite for move/resize or focus.
    assert 'function toggleArrange()' in JS
    assert '.canvas.compose' in CSS
    assert 'classList.toggle("compose",!!state.ui.arranging)' in JS


def test_direct_resize_handle_visible_without_arrange():
    # The resize handle renders on desktop without Arrange enabled; mobile
    # still hides it (covered by the mobile media query test above).
    rule = CSS[CSS.index(".window-resize{"):]
    rule = rule[:rule.index("}")]
    assert "display:block" in rule


def test_mobile_back_navigation_preserves_context():
    # Mobile nav gains an explicit back control that returns to the default
    # app; openApp only changes the active mobile app, never the context.
    assert 'data-mobile-back' in JS or "mobileBack" in JS
    assert 'openApp("work-console")' in JS


# --- dock/taskbar + maximize/restore (#432) ----------------------------

def _widget_read(name):
    """Read a widget file directly from THIS checkout's widget dir.

    The editable cortxt_agent_platform install (an earlier pip install -e from
    the main checkout) installs a MetaPathFinder that can make the module-level
    WIDGET/HTML/JS/CSS globals resolve against the MAIN checkout instead of the
    worktree under test. Deriving the path from __file__ (not the module global)
    pins these assertions to the checkout that actually contains this file
    (#432).
    """
    base = Path(__file__).resolve().parents[2]
    return (base / "widget" / name).read_text(encoding="utf-8")


def test_dock_renders_from_registry():
    # The shell chrome renders a dock from the authoritative app registry.
    html = _widget_read("index.html")
    assert 'data-os-dock' in html
    js = _widget_read("work-console.js")
    assert 'dock=q("[data-os-dock]")' in js
    assert 'data-dock-app' in js


def test_dock_entries_launch_or_are_disabled():
    # Non-deferred dock entries open/focus apps; deferred entries stay disabled.
    js = _widget_read("work-console.js")
    assert 'dk.addEventListener("click",function(){openApp(a.id)})' in js
    assert 'dk.disabled=true' in js


def test_dock_active_app_consistent_with_focus():
    # The dock highlights the active window, consistent with the focused
    # window (one source of truth via activeWindowId).
    js = _widget_read("work-console.js")
    css = _widget_read("os.css")
    assert 'data-dock-app' in js and "activeWindowId()" in js
    assert '.os-dock button.active' in css


def test_maximize_restore_state_and_persistence():
    # Maximize/restore toggles a persisted max flag; maximized class applied
    # in applyView; pinned console cannot be maximized.
    js = _widget_read("work-console.js")
    css = _widget_read("os.css")
    html = _widget_read("index.html")
    assert 'function setMax(id,on)' in js and 'function toggleMax(id)' in js
    assert 'state.ui.max' in js
    assert 'x.classList.toggle("maximized"' in js
    assert '.app-window.maximized' in css
    assert 'if(isDeferred(id)||isPinned(id))return' in js  # pinned excluded
    assert 'data-window-max' in html


def test_maximize_buttons_wired_and_console_excluded():
    # Maximize buttons exist for decisions/evidence/studio but not console.
    html = _widget_read("index.html")
    js = _widget_read("work-console.js")
    assert html.count('data-window-max="') >= 3
    assert 'data-window-max="work-console"' not in html
    assert 'toggleMax(x.dataset.windowMax)' in js


# --- Work Console as a registered operator app (#426) ------------------

def test_work_console_registered_in_shared_renderer():
    # Work Console is a first-class registered app, like Decisions/Evidence.
    assert 'OSRenderer.register("work-console",renderWorkConsole)' in JS
    assert "function renderWorkConsole(" in JS


def test_render_delegates_to_work_console_renderer_with_fallback():
    # render() delegates panel rendering to the registry and falls back to the
    # same function directly when the registry is unavailable.
    assert 'var handled=OSRenderer.render("work-console"' in JS
    assert 'if(!handled)renderWorkConsole(' in JS


def test_work_console_row_projects_decision_and_evidence_state():
    # The operator row shows pending-decision and evidence-count projections
    # from the Workstream data (no app-local fork).
    assert "pending-decision" in JS
    assert "evidence-count" in JS
    assert ".workstream-row .pending-decision" in CSS
    assert ".workstream-row .evidence-count" in CSS


def test_work_console_panels_render_from_shared_context():
    # renderWorkConsole reads its data from the passed context/state, the same
    # shell-owned projection the whole OS uses.
    assert "var s=(ctx&&ctx.state)||state" in JS
    assert "s.model&&s.model.workstreams" in JS
    assert "attention.map(function(x)" in JS
    assert 'empty("No Workstream currently requires operator attention.")' in JS


# --- shared app renderer module (#425) ---------------------------------

def test_renderer_module_loaded_before_shell_and_exposed():
    # The module must be present, load before the shell, and expose the API.
    assert "function register(appId, renderFn, opts)" in RENDERER
    assert "function render(appId, winEl, ctx)" in RENDERER
    assert "function has(appId)" in RENDERER
    assert 'global.OSRenderer = api' in RENDERER
    assert HTML.index('src="os-renderer.js"') < HTML.index('src="work-console.js"')


def test_shell_delegates_to_renderer_with_fallback():
    # propagateContext calls OSRenderer.render for decisions/evidence first and
    # falls back to inline projections when nothing is registered.
    assert "OSRenderer.render" in JS
    assert 'OSRenderer.render("decisions"' in JS
    assert 'OSRenderer.render("evidence"' in JS
    assert "OSRenderer" in JS  # referenced by the shell


def test_renderer_registry_dispatch_and_fallback_behavior():
    # Behavioral check: execute the module in a DOM-less runtime and prove
    # registration, dispatch, and fallback.
    import subprocess
    script = (
        "const m=require(%s);"
        "let calls=[];"
        "m.register('a',function(el,ctx){calls.push(['a',el,ctx])});"
        "if(m.has('a')!==true)process.exit(2);"
        "if(m.render('a','EL',{x:1})!==true)process.exit(3);"
        "if(m.render('nope','EL',{})!==false)process.exit(4);"
        "if(m.has('nope')!==false)process.exit(5);"
        "if(calls.length!==1||calls[0][1]!=='EL'||calls[0][2].x!==1)process.exit(6);"
        "console.log('ok');"
    ) % json.dumps(str(WIDGET / "os-renderer.js"))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- app runtime stabilization (#431) ---------------------------------

def test_renderer_exposes_lifecycle_events_and_capabilities():
    # OSRenderer now carries mount/unmount lifecycle, an event channel, and
    # capability lookup.
    assert "function mount(appId, winEl, ctx)" in RENDERER
    assert "function unmount(appId)" in RENDERER
    assert "function on(event, fn)" in RENDERER
    assert "function emit(event, payload)" in RENDERER
    assert "capabilities: appCapabilities" in RENDERER


def test_renderer_lifecycle_events_capabilities_behavior():
    # Behavioral check: mount/unmount, emit/on, and capability lookup work in a
    # DOM-less runtime.
    import subprocess
    script = (
        "const m=require(%s);"
        "let mounted=0, unmounted=0, got=null;"
        "m.register('a',function(el,ctx){mounted++},{capabilities:['read:x']});"
        "if(m.mount('a','EL',{})!==true)process.exit(2);"
        "if(m.unmount('a')!==true)process.exit(3);"
        "if(m.capabilities('a').join(',')!=='read:x')process.exit(4);"
        "if(m.capabilities('nope').length!==0)process.exit(5);"
        "m.on('ev',function(p){got=p});"
        "if(m.emit('ev',{n:7})!==true)process.exit(6);"
        "if(!got||got.n!==7)process.exit(7);"
        "console.log('ok');"
    ) % json.dumps(str(WIDGET / "os-renderer.js"))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


def test_app_manifest_declares_capabilities_mode_and_mobile():
    # apps.json declares capabilities, public/operator-only mode, and
    # mobile-activation for every app entry (except the synthetic "all").
    by_id = {a["id"]: a for a in APPS["apps"] if a["id"] != "all"}
    assert len(by_id) == 8
    for app in by_id.values():
        assert isinstance(app.get("capabilities"), list), app["id"]
        assert app.get("mode") in {"operator", "public"}, app["id"]
        assert isinstance(app.get("mobile"), bool), app["id"]
    assert by_id["atlas"]["mode"] == "public"
    assert by_id["atlas"]["mobile"] is True
    assert by_id["execution"]["mode"] == "operator"
    assert by_id["execution"]["mobile"] is False


def test_shell_emits_context_event_through_renderer():
    # propagateContext emits a named "context" event with the shared context.
    assert 'OSRenderer.emit("context",ctx)' in JS


# --- Decisions and Evidence authority journey (#427) -------------------

def test_decisions_evidence_renderer_loaded_and_registered():
    # The app renderer file loads after os-renderer.js and before the shell,
    # and registers both apps with the shared registry.
    assert HTML.index('src="os-renderer.js"') < HTML.index('src="app-renderer-decisions-evidence.js"')
    assert HTML.index('src="app-renderer-decisions-evidence.js"') < HTML.index('src="work-console.js"')
    assert 'OSRenderer.register("decisions", renderDecisions)' in D_RENDERER
    assert 'OSRenderer.register("evidence", renderEvidence)' in D_RENDERER


def test_decisions_is_an_authority_aware_app():
    # Decisions shows the pending decision plus evidence context and exposes a
    # fail-closed accept path (approval reference + explicit confirmation).
    assert "function renderDecisions(winEl, ctx)" in D_RENDERER
    assert "No authoritative decision is pending" in D_RENDERER
    assert 'data-d-accept' in D_RENDERER
    assert "Preview acceptance" in D_RENDERER  # synthetic never mutates
    assert "Approval reference is required." in D_RENDERER  # fail closed
    assert '"X-Cortxt-Token": s.token' in D_RENDERER


def test_evidence_is_attributable_and_read_only():
    # Evidence projects attributable evidence for the selected Workstream and
    # never exposes an action.
    assert "function renderEvidence(winEl, ctx)" in D_RENDERER
    assert "No authoritative evidence is attached." in D_RENDERER
    assert "ev.status" in D_RENDERER
    assert "review-actions" not in D_RENDERER.split("function renderEvidence")[1]


def test_shell_delegates_decisions_evidence_to_shared_renderer():
    # The shell's propagateContext delegates to OSRenderer for decisions and
    # evidence with inline fallback (issue #425 behavior preserved).
    assert 'OSRenderer.render("decisions"' in JS
    assert 'OSRenderer.render("evidence"' in JS
    assert "OSRenderer" in JS


def test_decisions_evidence_renderer_registration_behavior():
    # Behavioral check: load os-renderer.js then the app renderer in a DOM-less
    # runtime and prove both apps are registered and dispatch.
    import subprocess
    script = (
        "const m=require(%s);"
        "const d=require(%s);"
        "if(!m.has('decisions')||!m.has('evidence'))process.exit(2);"
        "const el={innerHTML:''};"
        "if(m.render('decisions',el,{workstream:null,state:{}})!==true)process.exit(3);"
        "if(el.innerHTML.indexOf('Select a Workstream')===-1)process.exit(4);"
        "if(m.render('evidence',el,{workstream:null,state:{}})!==true)process.exit(5);"
        "console.log('ok');"
    ) % (json.dumps(str(WIDGET / "os-renderer.js")), json.dumps(str(WIDGET / "app-renderer-decisions-evidence.js")))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- site mirror parity ------------------------------------------

# Files that MUST be byte-identical between the authoritative widget source
# and the web-served site mirror. Deliberately excludes maker.js/maker.html:
# those ship different product versions per surface (issue #435, S1a), so a
# byte-equality assertion on them would be false/red. Their single
# source-of-truth reconciliation is left to the TypeScript/source-of-truth
# track, not S1a.
@pytest.mark.parametrize("name", [
    "index.html", "os.css", "work-console.js", "apps.json",
    "os-renderer.js", "app-renderer-decisions-evidence.js",
])
def test_site_mirror_is_identical(name):
    assert (WIDGET / name).read_text(encoding="utf-8") == (MIRROR / name).read_text(encoding="utf-8")


# --- S1a: Studio navigation boundary (issue #435) -----------------
# These assertions target the ACTUALLY DEPLOYED web-served files under
# site/public/widgets (the surface a browser hits at /widgets/), plus the
# authoritative shell files that the site mirror must stay identical to for
# the affected artifacts.

SITE_MAKER = (MIRROR / "maker.js").read_text(encoding="utf-8")
SHELL_BRIDGE = (WIDGET / "shell-iframe-bridge.js").read_text(encoding="utf-8")
SITE_HTML = (MIRROR / "index.html").read_text(encoding="utf-8")


def test_studio_back_no_longer_navigates_to_workspace_or_widgets():
    # The recursion vector must be gone from the deployed Studio pane:
    # no plain anchor to /workspace/ or /widgets/ for the back-to-Work-Console
    # affordance. The affordance is now a button wired to the bridge.
    assert 'studio-back" href="/workspace/"' not in SITE_MAKER
    assert 'href="/workspace/"' not in SITE_MAKER
    assert '<a class="studio-back"' not in SITE_MAKER
    assert 'data-studio-back' in SITE_MAKER
    assert 'parent.postMessage' in SITE_MAKER


def test_studio_sends_only_the_allowed_shell_command():
    # The Studio pane posts exactly the allow-listed command with version 1.
    assert '"activate-app"' in SITE_MAKER
    assert '"cortxt-os-iframe"' in SITE_MAKER
    assert 'v: 1' in SITE_MAKER
    assert 'appId: "work-console"' in SITE_MAKER


def test_parent_validates_origin_command_and_payload():
    # The shell must validate origin, command, and payload before acting.
    shell = (WIDGET / "work-console.js").read_text(encoding="utf-8")
    assert 'ShellIframeBridge.listenFromIframe' in shell
    bridge = SHELL_BRIDGE
    assert 'validateMessage' in bridge
    assert 'normalizeOrigin' in bridge
    assert 'ALLOWED_COMMANDS' in bridge
    assert '"activate-app"' in bridge
    assert 'ALLOWED_APP_IDS' in bridge


def test_work_console_activated_in_outer_shell():
    # On a valid activation command, the shell focuses/opens the requested app.
    shell = (WIDGET / "work-console.js").read_text(encoding="utf-8")
    assert 'focusApp(id)' in shell
    assert 'payload.appId' in shell


def test_no_nested_os_mount_and_recursion_guard_present():
    # The shell refuses to render the desktop when embedded, and shows the
    # "Open in Cortxt OS" affordance (no window.top navigation).
    shell = (WIDGET / "work-console.js").read_text(encoding="utf-8")
    assert 'isRecursionMount' in shell
    assert 'window.top' in shell  # origin-validated check, not navigation
    assert '<strong>Open in Cortxt OS</strong>' in shell


def test_docs_link_points_to_real_docs():
    # The Studio docs link must point at the real docs, not /widgets/ (OS).
    assert '"/docs/widgets/"' in SITE_MAKER
    # And the mislabeled "Docs"-style link to /widgets/ must not be the
    # primary docs affordance in the studio pane header.
    assert 'studio-links"><a href="/docs/widgets/"' in SITE_MAKER


# --- S2: workstreams, windows, and hybrid binding (issue #437) ---------
# The WindowInstance model, workstream switcher, hybrid binding, and schema
# v2 persistence live in the authoritative work-console.js (agent) and its
# mirrored site copy (parity asserts byte-identity for the affected files).

S2_HTML = (WIDGET / "index.html").read_text(encoding="utf-8")
S2_CSS = (WIDGET / "os.css").read_text(encoding="utf-8")


def test_window_instance_model_present():
    # state.windows is the durable WindowInstance model; state.ui remains the
    # rendering projection. A WindowInstance carries id/appId/contextBinding/
    # bounds/displayState/zIndex (multi-window per app is representable).
    assert 'windows:[]' in JS
    assert 'function windowForApp(id)' in JS
    assert 'function syncWindowsFromUi()' in JS
    assert 'contextBinding:{mode:"follow-active",workstreamId:null}' in JS
    assert 'displayState:state.ui.min[a.id]?"minimized":' in JS
    assert 'zIndex:state.ui.z[a.id]||0' in JS


def test_hybrid_binding_modes_and_effective_workstream():
    # Windows bind follow-active | locked | global; effectiveWorkstreamId
    # resolves the projected workstream; bindingLabel is the quiet indicator.
    assert 'function setWindowBinding(id,mode,workstreamId)' in JS
    assert 'mode==="locked"' in JS and '"global"' in JS and '"follow-active"' in JS
    assert 'function effectiveWorkstreamId(id)' in JS
    assert 'return "all"' in JS
    assert 'function bindingLabel(id)' in JS
    assert '"follows active"' in JS and '"locked: "' in JS and '"All Work"' in JS


def test_workstream_switcher_surfaces():
    # The switcher exposes recent, attention, All Work, create, and archived;
    # selection is a shell action; switchWorkstream supports "all".
    assert 'function renderSwitcher()' in JS
    assert 'function switchWorkstream(id)' in JS
    assert 'function activeContextId()' in JS
    assert '"all"' in JS and 'data-ws-id="all"' in JS
    assert 'data-ws-list' in JS and 'data-ws-toggle' in JS
    assert 'function recentWorkstreams()' in JS
    assert 'data-ws-create' in JS
    assert 'data-ws-list' in S2_HTML and 'data-ws-toggle' in S2_HTML and 'data-ws-create' in S2_HTML
    assert '.ws-item' in S2_CSS and '.ws-switcher' in S2_CSS


def test_active_context_supports_all():
    # activeWorkstreamId is the S2 context carrier; "all" is a distinct global
    # context; switching to "all" clears the single-workstream selection.
    assert 'activeWorkstreamId' in JS
    assert 'state.context.activeWorkstreamId=(id==="all")?"all":id' in JS
    assert 'state.context.workstreamId=null' in JS


def test_before_switch_guard_blocks_pending_mutation():
    # hasPendingMutation detects an open confirm dialog or an entered approval
    # reference; switchWorkstream routes through the guard.
    assert 'function hasPendingMutation()' in JS
    assert 'dialog.open' in JS
    assert 'data-approval-ref' in JS
    assert 'window.confirm("Switch Workstream?' in JS


def test_binding_indicator_rendered_in_chrome():
    # Each window bar carries a quiet binding indicator populated by applyView.
    assert S2_HTML.count('data-binding-indicator') >= 4
    assert 'function bindingLabel(id)' in JS
    assert 'el.textContent=id?bindingLabel(id):""' in JS
    assert '.binding-indicator' in S2_CSS
