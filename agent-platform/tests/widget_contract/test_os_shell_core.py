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

PORTED = {"work", "decisions", "evidence"}
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
    # S5.5a/ADR-044: Work is the first principal app (id `work`, route `/work`);
    # Work Console is retired and no `workspace` app identity exists.
    assert by_id["work"]["kind"] == "pinned"
    assert by_id["work"]["route"] == "/work"
    assert by_id["work"]["window"] == "work"
    assert by_id["work"]["mode"] == "operator"
    assert "work-console" not in by_id
    assert "workspace" not in by_id
    for app_id in DEFERRED:
        assert by_id[app_id]["kind"] == "deferred", app_id
    # every non-"all" entry keeps icon + route (guards apps-manifest test too)
    for app in APPS["apps"]:
        if app["id"] == "all":
            continue
        assert "icon" in app and "route" in app


def test_shell_markup_has_no_hardcoded_per_app_button_list():
    # The launcher and mobile nav are rendered from the registry, not
    # hard-coded (S4: the "Apps & canvas" drawer is removed).
    assert 'data-launcher-list' in HTML and 'data-mobile-nav' in HTML
    assert HTML.count('data-app="') == 0
    assert 'apps.json' in JS
    assert 'renderChrome' in JS and '[data-launcher-list]' in JS and '[data-mobile-nav]' in JS
    assert 'data-app-list' not in HTML  # drawer hybrid removed
    assert 'data-app-drawer' not in HTML


def test_maker_studio_host_excludes_deferred_apps_from_its_rail():
    maker = (WIDGET / "maker.html").read_text(encoding="utf-8")
    assert 'filter(function(a){ return a.kind !== "deferred"; })' in maker


# --- shell state separation ----------------------------------------------

def test_state_separates_ui_context_and_app_local_view():
    assert 'ui:{open:' in JS and 'zTop:' in JS and 'mobileApp:' in JS
    # S2: context carries both the legacy workstreamId and the activeWorkstreamId
    # ("all" is a distinct global context).
    assert 'context:{workstreamId:null,activeWorkstreamId:null}' in JS
    # ADR-044: app-local state is separate and empty by default (the Work
    # Console sub-view state is retired with the app).
    assert 'apps:{}' in JS


# --- context propagation + persistence ---------------------------------

def test_single_persistence_key_carries_ui_context_app_and_windows():
    # Schema v3 (S5.5a) persists ui/context/apps plus the WindowInstance model,
    # dock favorites, and desktop layout under one key; v1/v2 blobs migrate.
    assert 'SHELL_KEY="cortxt-os-shell"' in JS
    assert 'localStorage.setItem(SHELL_KEY,JSON.stringify({v:3,ui:state.ui,context:state.context,apps:state.apps,windows:state.windows,dockFavorites:state.dockFavorites,desktopLayout:state.desktopLayout,activity:state.activity,schemaVersion:3}))' in JS
    assert 'function restore()' in JS and 'localStorage.getItem(SHELL_KEY)' in JS
    assert 'saved.v===2||saved.v===3' in JS  # schema-version gate
    assert 'syncWindowsFromUi()' in JS  # migration path for v1 blobs
    assert 'function migrateSavedState(saved)' in JS  # v2 -> v3 work-console -> work


def test_selecting_a_workstream_propagates_to_every_mounted_app():
    assert 'function propagateContext()' in JS
    for selector in ('[data-active-context]', '[data-decisions-body]',
                     '[data-evidence-body]', '[data-studio-frame]'):
        assert selector in JS
    assert 'function selectWorkstream(id){state.context.workstreamId=id;persist();propagateContext()}' in JS
    # The switcher routes selection through propagateContext (S2), and the
    # Work renderer reads the same shell-owned context projection.
    assert 'persist();propagateContext();renderSwitcher();' in JS
    assert 'var workEl=q("[data-work-body]")' in JS


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
    # Work is the first principal app: focus + minimise but never close
    # (ADR-044; kind pinned = favorite semantics, not an unclosable window).
    assert 'data-window="work"' in HTML
    assert 'data-close-window="work"' not in HTML
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
    assert 'a.kind==="deferred")return' in JS
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
    assert 'The shell failed closed: no evidence or decision action is exposed.' in JS
    # The mandate-protected action port (X-Cortxt-Token) now lives in the
    # Decisions renderer, which owns the record-decision mutation (ADR-044).
    assert '"X-Cortxt-Token": s.token' in D_RENDERER
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
        "  const r=m.tileRects(ids);const keys=['work',...ids];"
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
    # Mobile nav gains an explicit back control; S5.5b: back is deterministic
    # (Workstream -> Home); openApp only changes the active mobile app, never
    # the context.
    assert 'data-mobile-back' in JS or "mobileBack" in JS
    assert 'openApp("home")' in JS


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
    # S4: the dock shows favorites + running apps; deferred apps do NOT appear
    # in the dock (they live only in the launcher catalog). Dock entries
    # launch/focus on click.
    js = _widget_read("work-console.js")
    assert 'dk.addEventListener("click",function(){openApp(a.id)})' in js
    # Deferred apps are excluded from the dock.
    assert 'if(!a||a.kind==="deferred")return' in js
    # The launcher catalog marks deferred apps as disabled.
    launcher_js = js
    assert 'b.disabled=true;b.setAttribute("aria-disabled","true")' in launcher_js
    assert 'dataset.launchApp' in launcher_js


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
    # Maximize buttons exist for decisions/evidence/studio but not Work.
    html = _widget_read("index.html")
    js = _widget_read("work-console.js")
    assert html.count('data-window-max="') >= 3
    assert 'data-window-max="work"' not in html
    assert 'toggleMax(x.dataset.windowMax)' in js


# --- Work as the first principal app (ADR-044/S5.5a) -------------------

def test_work_app_registered_in_shared_renderer():
    # Work is a first-class registered app, like Decisions/Evidence; the
    # retired work-console renderer is gone (ADR-044).
    assert 'OSRenderer.register("work",renderWork)' in JS
    assert "function renderWork(" in JS
    assert 'OSRenderer.register("work-console"' not in JS
    assert "function renderWorkConsole(" not in JS


def test_render_delegates_to_work_renderer_with_fallback():
    # render() delegates the Work body to the registry and falls back to the
    # same function directly when the registry is unavailable.
    assert 'var workEl=q("[data-work-body]")' in JS
    assert 'OSRenderer.render("work",workEl' in JS
    assert 'if(workEl&&!OSRenderer.render("work"' in JS


def test_work_summary_projects_workstream_state_without_forking():
    # The Work surface is a read-only summary of the shell-owned Workstream:
    # title/outcome/workflow/decision/evidence, with validated deep links into
    # Decisions and Evidence. No app-local fork, no review flow, no mutation.
    assert "work-objective" in JS
    assert "work-hero" in JS
    assert 'data-work-open="decisions"' in JS
    assert 'data-work-open="evidence"' in JS
    assert 'dispatchCommand("open-app",{appId:b.dataset.workOpen})' in JS
    assert "openReview(" not in JS
    assert "showConsole(" not in JS
    assert "confirmDecision(" not in JS


def test_work_surface_never_duplicates_full_app_workflows():
    # ADR-044: Work never duplicates a full app workflow; the console review
    # panels (attention/workstreams/records) are retired with Work Console.
    assert "data-console-panel" not in HTML
    assert "data-console-view" not in HTML
    assert "data-attention-count" not in HTML
    assert "data-review" not in HTML
    assert "console-nav" not in HTML
    # The record-decision authority flow lives in Decisions (its own dialog),
    # not in the shell console (verified ownership).
    assert 'action_id: "record-decision"' in D_RENDERER
    assert "data-d-approval" in D_RENDERER


def test_confirm_dialog_ownership_moved_to_decisions():
    # The shell's console confirm dialog is removed; the before-switch guard
    # now watches Decisions' own dialog + approval reference.
    assert "data-confirm-dialog" not in HTML
    assert "data-approval-ref" not in HTML
    assert 'document.querySelector("dialog[open]")' in JS
    assert "[data-d-approval]" in JS


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
    assert len(by_id) == 9
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
    "shell-commands.js", "os-renderer.js", "app-renderer-decisions-evidence.js",
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
    # hasPendingMutation detects an open authority dialog (Decisions owns the
    # record-decision dialog since ADR-044/S5.5a) or an entered approval
    # reference; switchWorkstream routes through the guard.
    assert 'function hasPendingMutation()' in JS
    assert 'dialog[open]' in JS
    assert '[data-d-approval]' in JS
    assert 'window.confirm("Switch Workstream?' in JS


def test_binding_indicator_rendered_in_chrome():
    # Each window bar carries a quiet binding indicator populated by applyView.
    assert S2_HTML.count('data-binding-indicator') >= 4
    assert 'function bindingLabel(id)' in JS
    assert 'el.textContent=id?bindingLabel(id):""' in JS
    assert '.binding-indicator' in S2_CSS


# --- S1b: shell command router, deep links, history (issue #439) --------
# The typed command router (shell-commands.js) plus the shell integration
# (commandHandlers, deep-link boot/hashchange, history push) live in the
# authoritative work-console.js/shell-commands.js and the mirrored site copy.

SHELL_COMMANDS = (WIDGET / "shell-commands.js").read_text(encoding="utf-8")
S1B_HTML = (WIDGET / "index.html").read_text(encoding="utf-8")


def test_command_router_defines_typed_commands():
    # The router declares exactly the typed command set; dispatch fails closed
    # on unknown commands or missing handlers (no navigation side effects).
    for cmd in ('"open-app"', '"close-app"', '"focus-app"', '"switch-workstream"',
                '"open-home"', '"exit-workspace"', '"open-external"'):
        assert cmd in SHELL_COMMANDS
    assert 'dispatch: function (command, payload, handlers)' in SHELL_COMMANDS
    assert 'if (!APP_COMMANDS[command]) return false;' in SHELL_COMMANDS


def test_deep_link_parser_supports_app_and_ws():
    # #app=<id>[&ws=<id>] parses into {appId, workstreamId}; empty hash yields
    # nulls; "all" is a valid workstream value; the legacy work-console app id
    # normalizes to work (ADR-044).
    assert 'function parseDeepLink(hash)' in SHELL_COMMANDS
    assert 'out.appId = normalizeAppId(v)' in SHELL_COMMANDS
    assert 'out.workstreamId = v' in SHELL_COMMANDS
    assert 'applyDeepLink' in SHELL_COMMANDS


def test_shell_wires_command_handlers():
    # The shell exposes commandHandlers and dispatches to lifecycle functions;
    # open-home no-ops gracefully; exit-workspace returns to landing;
    # open-external opens a new tab. S5.5a: open-app and switch-workstream
    # validate their references (unknown ids fail closed) and open-app
    # resolves the legacy work-console id through the ADR-044 alias.
    assert 'window.ShellCommandHandlers = commandHandlers' in JS
    assert '"open-app": function(p){ if(p&&p.appId){var a=appById(migrateWorkConsole(p.appId));if(a&&!isDeferred(a.id))openApp(a.id);} }' in JS
    assert '"close-app": function(p){ if(p&&p.appId)closeApp(p.appId); }' in JS
    assert '"focus-app": function(p){ if(p&&p.appId)focusApp(p.appId); }' in JS
    assert '"switch-workstream": function(p){ if(p&&p.workstreamId){var known=p.workstreamId==="all"||items().some(function(x){return x.id===p.workstreamId});if(known)switchWorkstream(p.workstreamId);} }' in JS
    assert '"open-home": function(){ openHome(); }' in JS
    assert 'window.location.href="/"' in JS  # exit-workspace
    assert 'window.open(p.url,"_blank","noopener")' in JS  # open-external
    # work-console.js's IIFE binds no `global` parameter; navigation must use
    # the browser `window` (unbound `global` would silently no-op in browsers).
    assert 'global.location.href' not in JS and 'global.open(' not in JS


def test_boot_and_hashchange_apply_deep_links():
    # The shell reads the initial deep link after the model loads (captured
    # before any first-run Home open mutates the hash) and reacts to
    # hashchange; no location.reload-based navigation.
    assert 'var bootHash=(typeof location!=="undefined")?location.hash:""' in JS
    assert 'ShellCommands.applyDeepLink(bootHash, window.ShellCommandHandlers)' in JS
    assert 'window.addEventListener("hashchange"' in JS
    assert 'ShellCommands.applyDeepLink(location.hash, commandHandlers)' in JS
    assert 'location.reload' not in JS


def test_history_push_integration():
    # App opening/focusing and workstream switching push the shell state onto
    # the hash for defined back/refresh/deep-link semantics.
    assert 'function pushShellState(appId)' in JS
    assert 'ShellCommands.pushState(appId||null,activeContextId())' in JS
    assert 'persist();applyView();pushShellState(id)' in JS
    assert 'ShellCommands.pushState(state.ui.mobileApp||null,activeContextId())' in JS


def test_router_behavior_in_domless_runtime():
    # Behavioral check: execute shell-commands.js in a DOM-less runtime and
    # prove command dispatch, deep-link parsing, the ADR-044 work-console ->
    # work alias, and fail-closed unknown commands.
    import subprocess
    script = (
        "const m=require(%s);"
        "let got=[];"
        "const h={"
        "  'open-app':function(p){got.push(['open',p.appId])},"
        "  'switch-workstream':function(p){got.push(['ws',p.workstreamId])}"
        "};"
        "if(m.dispatch('open-app',{appId:'studio'},h)!==true)process.exit(2);"
        "if(m.dispatch('nope',{},h)!==false)process.exit(3);"
        "if(m.dispatch('open-app',{},null)!==false)process.exit(4);"
        "const d1=m.parseDeepLink('#app=studio&ws=WS-042');"
        "if(d1.appId!=='studio'||d1.workstreamId!=='WS-042')process.exit(5);"
        "const d2=m.parseDeepLink('');"
        "if(d2.appId!==null||d2.workstreamId!==null)process.exit(6);"
        "const d3=m.parseDeepLink('#ws=all');"
        "if(d3.workstreamId!=='all')process.exit(7);"
        "if(m.applyDeepLink('#app=evidence&ws=all',h)!==true)process.exit(8);"
        "if(got.length!==3||got[0][0]!=='open'||got[1][1]!=='all'||got[2][0]!=='open')process.exit(9);"
        "const d4=m.parseDeepLink('#app=work-console&ws=WS-042');"
        "if(d4.appId!=='work'||d4.workstreamId!=='WS-042')process.exit(10);"
        "if(m.normalizeAppId('work-console')!=='work')process.exit(11);"
        "if(m.normalizeAppId('decisions')!=='decisions')process.exit(12);"
        "if(m.applyDeepLink('#app=work-console&ws=WS-042',h)!==true)process.exit(13);"
        "if(got.length!==5||got[3][0]!=='ws'||got[3][1]!=='WS-042'||got[4][0]!=='open'||got[4][1]!=='work')process.exit(14);"
        "console.log('ok');"
    ) % json.dumps(str(WIDGET / "shell-commands.js"))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- S3: unpinned session model (issue #441) ---------------------------
# No mandatory pinned Work Console: no window is forced open, sessions
# restore as saved, empty desktop shows a launcher, first-run shows the
# Cortxt Home placeholder, and Work Console is closable.

S3_HTML = (WIDGET / "index.html").read_text(encoding="utf-8")


def test_no_mandatory_pinned_window_in_initial_state():
    # Initial state opens NO window; restore() and applyView() never force
    # Work open (ADR-044: no app is a shell invariant).
    assert 'ui:{open:{}' in JS
    assert 'state.ui.open=Object.assign({},saved.ui.open);' in JS  # no forced open
    assert 'state.ui.open["work"]=true' not in JS
    assert 'state.ui.open["work"]=true;' not in JS


def test_close_work_app_works():
    # Work is closable like any other window: closeApp only guards deferred
    # apps (ADR-044 item 9: no app is permanently pinned open).
    assert 'if(isDeferred(id))return;\n  delete state.ui.open[id]' in JS or 'if(isDeferred(id))return;' in JS
    assert 'if(isPinned(id)||isDeferred(id))return' not in JS  # pinned guard removed from closeApp


def test_active_window_can_be_null():
    # activeWindowId returns null when no window is open (no work-console
    # default).
    assert 'var best=null,bz=-1' in JS
    assert 'return best;' in JS


def test_empty_desktop_and_first_run_home_surfaces():
    # The shell chrome carries an empty-desktop affordance; S5 replaced the
    # first-run Home placeholder with the real Cortxt Home app, which opens
    # as a window when no saved session exists.
    assert 'data-empty-desktop' in S3_HTML
    assert 'data-home-surface' not in S3_HTML
    assert 'emptyDesktop.hidden=!!anyOpen' in JS
    assert 'openHome()' in JS and 'hadSavedSession' in JS


def test_session_restore_tracks_had_saved_session():
    # restore() records whether a saved session existed so first-run (no
    # saved session) can show Home.
    assert 'state.hadSavedSession=!!(saved&&typeof saved==="object"&&(saved.ui||saved.windows))' in JS
    assert 'hadSavedSession:false' in JS


def test_pinned_semantics_favorite_only():
    # "Pinned" no longer implies an unclosable window: the manifest may keep
    # kind:pinned for the dock favorite, but the shell never force-opens it.
    by_id = {a["id"]: a for a in APPS["apps"]}
    assert by_id["work"]["kind"] == "pinned"  # favorite icon retained
    assert 'isPinned(id)' in JS  # helper retained for favorite semantics


# --- S4: dock/launcher separation (issue #443) --------------------------
# The dock shows favorites + running apps with a quiet running indicator; the
# launcher lists ALL apps (deferred as catalog); the "Apps & canvas" drawer is
# removed.

S4_HTML = (WIDGET / "index.html").read_text(encoding="utf-8")
S4_CSS = (WIDGET / "os.css").read_text(encoding="utf-8")


def test_dock_is_favorites_plus_running():
    # The dock renders favorites (default set) plus currently running apps,
    # with a quiet running indicator; deferred apps never appear in the dock.
    assert 'var favorites=state.dockFavorites' in JS
    assert 'var running=Object.keys(state.ui.open)' in JS
    assert 'if(!a||a.kind==="deferred")return' in JS  # deferred excluded from dock
    assert 'x.classList.toggle("running",open)' in JS  # quiet running indicator
    assert '.os-dock button.running::after' in S4_CSS


def test_launcher_lists_all_apps_including_deferred_catalog():
    # The launcher lists every registry app; deferred entries are disabled
    # catalog items ("Soon · planned").
    assert 'data-launcher-list' in S4_HTML and 'data-launcher-toggle' in S4_HTML
    assert 'data-launcher-close' in S4_HTML
    assert 'state.registry.forEach(function(a)' in JS
    assert '"Soon · planned"' in JS
    assert 'b.disabled=true;b.setAttribute("aria-disabled","true")' in JS


def test_drawer_hybrid_removed():
    # The combined "Apps & canvas" drawer is gone; the launcher replaces it.
    assert 'data-app-list' not in S4_HTML
    assert 'data-app-drawer' not in S4_HTML
    assert 'data-reveal-apps' not in S4_HTML
    assert '.app-launcher{' in S4_CSS


def test_launcher_wiring_present():
    # The launcher opens/closes from chrome; launching a non-deferred app
    # opens it and closes the launcher.
    assert 'function openLauncher()' in JS
    assert 'launcherPanel.hidden=false' in JS
    assert 'data-launcher-close' in JS
    assert 'var panel=q("[data-launcher]");if(panel)panel.hidden=true' in JS


# --- S5: Cortxt Home + landing-to-workspace transition (#445) ----------
# Cortxt Home is a registered app with identity + lifecycle; /workspace/ is a
# real entry (deep link into Home) instead of a bare redirect; Exit Workspace
# returns to the public landing; refresh/back/deep-link semantics are defined
# (session restore + #app=home deep link); mobile Home is full-screen.

S5_HTML = (WIDGET / "index.html").read_text(encoding="utf-8")
S5_JS = (WIDGET / "work-console.js").read_text(encoding="utf-8")


def test_home_is_a_registered_app_with_identity_and_lifecycle():
    by_id = {a["id"]: a for a in APPS["apps"]}
    home = by_id["home"]
    assert home["kind"] == "window"
    assert home["window"] == "home"
    assert home["mode"] == "public"
    assert home["mobile"] is True
    assert home["route"] == "/"
    assert 'data-window="home"' in S5_HTML
    assert 'data-home-body' in S5_HTML
    assert 'OSRenderer.register("home",renderHome)' in S5_JS
    assert 'function renderHome(winEl,ctx)' in S5_JS


def test_home_opens_apps_via_typed_commands():
    # Home launch tiles dispatch typed shell commands (open-app / open-external
    # / exit-workspace), never ordinary page navigation.
    assert 'data-home-open' in S5_JS
    assert 'dispatchCommand("open-app",{appId:' in S5_JS
    assert 'dispatchCommand("open-external",{url:"/docs/"})' in S5_JS
    assert 'dispatchCommand("exit-workspace",{})' in S5_JS
    assert 'ShellCommands.dispatch(command,payload,handlers)' in S5_JS


def test_open_home_command_and_first_run_open_home():
    # The typed open-home command opens Cortxt Home; first run (no saved
    # session) opens Home instead of showing a placeholder.
    assert '"open-home": function(){ openHome(); }' in S5_JS
    assert 'function openHome()' in S5_JS and 'openApp("home")' in S5_JS
    assert 'if(!state.hadSavedSession&&!bootApplied)openHome()' in S5_JS
    assert 'var bootHash=(typeof location!=="undefined")?location.hash:""' in S5_JS


def test_exit_workspace_wired_in_chrome_and_home():
    # Exit Workspace is an explicit chrome affordance plus a Home action; both
    # route through the typed command that returns to the public landing.
    assert 'data-exit-workspace' in S5_HTML
    assert 'dispatchCommand("exit-workspace",{})' in S5_JS
    assert 'window.location.href="/"' in S5_JS


def test_workspace_page_is_a_real_entry_deep_linking_home():
    # /workspace/ is a real entry: it deep-links into the OS shell at
    # #app=home (single shell surface; no second shell) instead of a bare
    # redirect to /widgets/.
    ws = Path(__file__).resolve().parents[3] / "site" / "src" / "pages" / "workspace.astro"
    text = ws.read_text(encoding="utf-8")
    assert '/widgets/#app=home' in text
    assert "location.replace('/widgets/#app=home')" in text


def test_landing_nav_corrects_the_studio_mislabel():
    # The nav item pointing at the OS shell (/widgets/) is no longer labelled
    # "Studio"; "Workspace" remains the landing-to-Home entry.
    idx = Path(__file__).resolve().parents[3] / "site" / "src" / "pages" / "index.astro"
    text = idx.read_text(encoding="utf-8")
    assert 'href="/workspace/">Workspace</a>' in text
    assert 'href="/widgets/">Cortxt OS</a>' in text
    assert '>Studio</a>' not in text


# --- S5.5a: ADR-044 app boundary + migration seam (issue #449) ----------
# Work is the first principal app (id `work`, route `/work`); Work Console is
# retired with a one-release compatibility alias; schema v3 migrates saved
# sessions; global context is optional; Activity Center has no mutation port.

S55A_HTML = (WIDGET / "index.html").read_text(encoding="utf-8")
S55A_JS = (WIDGET / "work-console.js").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
def test_v2_to_v3_migration_renames_work_console_to_work():
    # Behavioral check: the pure migration helper renames every work-console
    # reference (ui open/z/mobileApp, windows, apps, dockFavorites) to `work`
    # while preserving the selected Workstream and every other open app.
    script = (
        "const m=require(%s);"
        "const saved={v:2,ui:{open:{'work-console':true,'decisions':true},mobileApp:'work-console',z:{'work-console':5},min:{},max:{},geom:{}},context:{workstreamId:'WS-042'},apps:{'work-console':{panel:'attention'},'decisions':{}},windows:[{id:'win-work-console',appId:'work-console',contextBinding:{mode:'locked',workstreamId:'WS-042'}},{id:'win-decisions',appId:'decisions'}],dockFavorites:['work-console','decisions','evidence'],desktopLayout:{}};"
        "m.migrateSavedState(saved);"
        "if(saved.ui.open['work']!==true||saved.ui.open['work-console']!==undefined)process.exit(2);"
        "if(saved.ui.open['decisions']!==true)process.exit(3);"
        "if(saved.ui.mobileApp!=='work')process.exit(4);"
        "if(saved.ui.z['work']!==5)process.exit(5);"
        "if(saved.context.workstreamId!=='WS-042')process.exit(6);"
        "if(saved.apps['work']===undefined||saved.apps['work-console']!==undefined)process.exit(7);"
        "if(saved.windows[0].appId!=='work'||saved.windows[1].appId!=='decisions')process.exit(8);"
        "if(saved.dockFavorites[0]!=='work')process.exit(9);"
        "if(saved.dockFavorites.indexOf('decisions')===-1)process.exit(10);"
        "if(saved.schemaVersion!==3)process.exit(11);"
        "console.log('ok');"
    ) % json.dumps(str(WIDGET / "work-console.js"))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


def test_v3_writer_keeps_v2_fields_and_rollback_safe():
    # The v3 writer keeps the v2 field set intact (additive schema), persists
    # schemaVersion 3, and migrates saved blobs on read; an older v2 reader
    # ignores the unknown v3 fields.
    assert 'JSON.stringify({v:3,ui:state.ui,context:state.context,apps:state.apps,windows:state.windows,dockFavorites:state.dockFavorites,desktopLayout:state.desktopLayout,activity:state.activity,schemaVersion:3})' in JS
    assert 'saved.schemaVersion=3' in JS
    assert 'function migrateSavedState(saved)' in JS
    assert 'saved.v===2||saved.v===3' in JS
    assert 'function migrateWorkConsole(ref)' in JS


def test_deep_link_legacy_alias_work_console_to_work():
    # The router resolves #app=work-console to the work app through the
    # one-release alias and normalizes app ids (behavioral coverage in the
    # DOM-less router test).
    assert 'LEGACY_APP_ALIASES' in SHELL_COMMANDS
    assert 'work-console' in SHELL_COMMANDS and '"work"' in SHELL_COMMANDS
    assert 'normalizeAppId' in SHELL_COMMANDS
    assert 'out.appId = normalizeAppId(v)' in SHELL_COMMANDS
    assert 'migrateWorkConsole' in S55A_JS  # shell-side alias on activation


def test_shell_core_has_no_work_specific_branch():
    # ADR-044 conformance: registering Work adds no Work-specific branch to
    # shell core. The renderer/router/window logic operates on generic app ids
    # from the registry; `work` appears only as a registry entry, a migration
    # target, and the primary-column layout key.
    core = RENDERER + SHELL_COMMANDS
    assert 'if(id==="work")' not in core
    assert 'appId==="work"' not in core
    assert 'workstreamId==="work"' not in core
    # The shell opens apps generically (registry-driven), never by app id.
    assert 'openApp(a.id)' in JS
    assert 'focusApp(appIdForWindow(win.dataset.window))' in JS
    # Work registers through the generic registry path like any other app.
    assert 'OSRenderer.register("work",renderWork)' in JS


def test_app_without_workstream_context_can_register_and_open():
    # ADR-044 item 8: global context is optional. The registry declares no
    # mandatory workstream requirement for any app, and the shell opens apps
    # with no selected Workstream (empty desktop -> launcher -> app).
    by_id = {a["id"]: a for a in APPS["apps"]}
    assert "work" in by_id and "home" in by_id
    for a in APPS["apps"]:
        assert "requiresWorkstream" not in a, a["id"]
    # The shell never blocks opening on a missing Workstream selection.
    assert 'function openApp(id){' in JS
    assert 'if(!state.context.workstreamId)return' not in JS
    # Empty desktop affordance exists: the shell is usable with no app open.
    assert 'data-empty-desktop' in S55A_HTML
    assert 'emptyDesktop.hidden=!!anyOpen' in JS
    # Home (S5) is the first-run entry and opens with no Workstream bound.
    assert 'function openHome()' in JS and 'openApp("home")' in JS


def test_activity_center_has_no_mutation_port():
    # ADR-044 items 5-6: Activity Center consumes typed attention projections
    # and may not approve, mutate workflow state, own decision requests, or
    # become a backlog. In S5.5a the projection contract is typed and
    # read-only; the record-decision mutation port lives only in Decisions.
    assert 'action_id: "record-decision"' in D_RENDERER
    assert 'record-decision' not in JS  # shell core exposes no decision mutation
    assert 'AttentionItemProjection' in JS
    assert 'function isValidAttentionItem(item)' in JS
    # The projection contract carries presentation + validated navigation
    # only: no decision/workflow/mutation fields.
    contract = JS[JS.index('AttentionItemProjection={'):JS.index('};', JS.index('AttentionItemProjection={'))]
    for banned in ('mutat', 'approve', 'workflow'):
        assert banned not in contract, banned
    # No console attention panel markup remains (retired with Work Console).
    assert 'data-attention-count' not in S55A_HTML
    assert 'data-console-panel' not in S55A_HTML


@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
def test_attention_item_validation_behavioral():
    # isValidAttentionItem accepts a well-formed projection and rejects
    # malformed items (wrong types, missing fields, missing targetCommand).
    script = (
        "const m=require(%s);"
        "const ok={id:'a1',sourceCapability:'read:decision-pending',sourceRecordRef:'#445',sourceVersion:'v1',workstreamId:'WS-042',occurredAt:'2026-08-28T00:00:00Z',severity:'high',requiresAttention:true,title:'Decision',summary:'pending',targetCommand:'open-app',dedupeKey:'d1',expiresAt:null};"
        "if(!m.isValidAttentionItem(ok))process.exit(2);"
        "if(m.isValidAttentionItem(null))process.exit(3);"
        "if(m.isValidAttentionItem({id:'x'}))process.exit(4);"
        "if(m.isValidAttentionItem(Object.assign({},ok,{severity:7})))process.exit(5);"
        "if(m.isValidAttentionItem(Object.assign({},ok,{targetCommand:''})))process.exit(6);"
        "console.log('ok');"
    ) % json.dumps(str(WIDGET / "work-console.js"))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- S5.5b: Work primary surface (issue #452) ---------------------------
# The Work app is the coherent primary surface for the selected Workstream:
# objective/mandate summary, phase/status, next action, blockers, decisions
# summary, evidence summary, milestones/plan, related resources. Every
# summary deep-links to its responsible app with exact context through
# validated references; Work never duplicates a full app workflow and adds
# no Work-specific branch to shell core.

S55B_JS = (WIDGET / "work-console.js").read_text(encoding="utf-8")


def test_work_surface_presents_full_workstream_summary():
    # The Work renderer projects objective/mandate, phase/status, next action,
    # blockers, decisions, evidence, milestones/plan, and related resources
    # from the shell-owned context (no app-local fork).
    assert "work-hero" in S55B_JS
    assert "work-objective" in S55B_JS
    assert "work-mandate" in S55B_JS
    for card in ("status", "next", "decisions", "evidence", "milestones", "related"):
        assert f'data-work-card="{card}"' in S55B_JS
    assert "x.phase||x.workflow" in S55B_JS
    assert "nextAction" in S55B_JS
    assert "x.blockers" in S55B_JS
    assert "x.milestones" in S55B_JS
    assert "x.related" in S55B_JS


def test_work_summaries_deep_link_with_exact_context():
    # Each summary deep-links to its responsible app with the exact Workstream
    # context; the router validates app/workstream before dispatch. Record
    # context is introduced with the validated per-app record router in S5.5c.
    assert "function deepLink(appId,workstreamId)" in S55B_JS
    assert '"app="+encodeURIComponent(appId)' in S55B_JS
    assert '"ws="+encodeURIComponent(workstreamId)' in S55B_JS
    assert "data-work-deep" in S55B_JS
    assert 'deep("decisions")' in S55B_JS and 'deep("evidence")' in S55B_JS
    assert 'deep("execution")' in S55B_JS and 'deep("policies")' in S55B_JS
    assert "ShellCommands.applyDeepLink(b.dataset.workDeep" in S55B_JS
    # No record= emission in S5.5b (the validated record router is S5.5c).
    assert '"record="+encodeURIComponent' not in S55B_JS


def test_work_does_not_duplicate_full_app_workflows():
    # ADR-044: Work summarizes and deep-links; it never embeds another app's
    # renderer, mutation, or full workflow.
    assert "app-renderer-decisions-evidence" not in S55B_JS  # no renderer import
    assert "renderDecisions(" not in S55B_JS and "renderEvidence(" not in S55B_JS
    assert "record-decision" not in S55B_JS  # no mutation port
    assert "data-work-open" in S55B_JS  # typed commands only
    assert 'dispatchCommand("open-app"' in S55B_JS


def test_work_surface_still_read_only_and_synthetic_safe():
    # The Work surface is read-only: it renders projections and dispatches
    # validated navigation; it never mutates authority, and synthetic mode
    # changes nothing about it.
    assert "state.model.synthetic" in S55B_JS
    assert 'fetch("api/action"' not in S55B_JS
    assert "work-note" in S55B_JS


def test_home_to_work_transition_preserved():
    # Home tile/action opens Work with the selected Workstream; first-run
    # still opens Home; the open-home command is unchanged.
    assert '"open-home": function(){ openHome(); }' in S55B_JS
    assert "function openHome()" in S55B_JS and 'openApp("home")' in S55B_JS
    assert 'if(!state.hadSavedSession&&!bootApplied)openHome()' in S55B_JS
    assert 'data-home-open="work"' in S55B_JS


def test_landing_and_workspace_pages_use_work_language():
    # ADR-044 wording: the landing and /workspace/ entry label the app Work;
    # Workspace remains only the execution-resource term / landing entry URL.
    idx = Path(__file__).resolve().parents[3] / "site" / "src" / "pages" / "index.astro"
    text = idx.read_text(encoding="utf-8")
    assert "Work Console" not in text
    assert "Cortxt OS / Work, Evidence, Decisions" in text
    assert 'href="/workspace/">Workspace</a>' in text  # landing entry unchanged
    ws = Path(__file__).resolve().parents[3] / "site" / "src" / "pages" / "workspace.astro"
    wtext = ws.read_text(encoding="utf-8")
    assert "Work Console" not in wtext
    assert "Cortxt OS and Work" in wtext


def test_mobile_back_is_deterministic_workstream_to_home():
    # S5.5b AC5: mobile back is deterministic (Workstream -> Home), not back
    # to Work.
    assert 'back.setAttribute("aria-label","Back to Home")' in S55B_JS
    assert 'back.addEventListener("click",function(){openApp("home")})' in S55B_JS


def test_work_primary_surface_no_shell_core_branch():
    # ADR-044 conformance (extended): the Work primary surface still adds no
    # Work-specific branch to shell core; deep links route through the generic
    # validated router.
    core = RENDERER + SHELL_COMMANDS
    assert 'if(id==="work")' not in core
    assert 'appId==="work"' not in core
    assert 'workstreamId==="work"' not in core


# --- S5.5c: Activity Center (issue #455) --------------------------------
# Shell-owned system surface (ADR-044 items 5-6): right-side panel consuming
# typed AttentionItemProjection items with local presentation state only;
# validated record navigation (focus-record); no mutation port.

S55C_HTML = (WIDGET / "index.html").read_text(encoding="utf-8")
S55C_JS = (WIDGET / "work-console.js").read_text(encoding="utf-8")
S55C_COMMANDS = (WIDGET / "shell-commands.js").read_text(encoding="utf-8")


def test_activity_center_is_shell_surface_not_app_or_window():
    # ADR-044 item 5: Activity Center is a shell-owned system surface, NOT a
    # registered app and NOT a window.
    by_id = {a["id"]: a for a in APPS["apps"]}
    assert "activity" not in by_id and "activity-center" not in by_id
    assert 'data-activity-panel' in S55C_HTML
    assert 'data-activity-toggle' in S55C_HTML
    assert 'data-activity-count' in S55C_HTML
    assert 'data-window="activity"' not in S55C_HTML
    assert 'activity:{open:false' in S55C_JS


def test_activity_items_conform_to_attention_projection():
    # Items derive from the shell-owned model and each conforms to the
    # AttentionItemProjection contract (validated by isValidAttentionItem).
    assert "function attentionItems()" in S55C_JS
    assert "function isValidAttentionItem(item)" in S55C_JS
    assert "sourceCapability" in S55C_JS and "targetCommand" in S55C_JS
    assert "requiresAttention" in S55C_JS and "dedupeKey" in S55C_JS
    assert "items.filter(isValidAttentionItem)" in S55C_JS


def test_activity_group_dedupe_filter_read_dismiss_local():
    # Group (time/type/workstream), dedupe, filter, mark read, dismiss are
    # local presentation operations persisted under the shell key only.
    assert "activityVisibleItems" in S55C_JS
    assert "state.activity.filters.groupBy" in S55C_JS
    assert "state.activity.read" in S55C_JS and "state.activity.dismissed" in S55C_JS
    assert "data-activity-group" in S55C_JS
    assert "data-activity-read" in S55C_JS and "data-activity-dismiss" in S55C_JS
    assert "Presentation state is local. Workflow status is authoritative." in S55C_JS
    assert "dedupeKey" in S55C_JS
    # S5.5c review: explicit dedupe by dedupeKey and time-based grouping.
    assert "function activityGroupKey(it,groupBy)" in S55C_JS
    assert "seen[it.dedupeKey]" in S55C_JS
    assert "occurredAt?String(it.occurredAt).slice(0,10)" in S55C_JS


def test_activity_cannot_invoke_workflow_or_decision_mutations():
    # ADR-044 item 6: Activity may NOT approve, mutate workflow state, own
    # decision requests, or reproduce a full app workflow. The panel has no
    # mutation action port; the only action is validated navigation.
    assert "record-decision" not in S55C_JS
    assert "data-activity-accept" not in S55C_JS
    assert "data-activity-approve" not in S55C_JS
    assert 'fetch("api/action"' not in S55C_JS
    assert 'data-activity-open' in S55C_JS
    assert 'dispatchCommand("focus-record"' in S55C_JS
    assert "Never" in S55C_JS or "never" in S55C_JS  # boundary comment


@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
def test_activity_record_navigation_validates_fail_closed():
    # The validated record router: parseDeepLink parses record=; applyDeepLink
    # dispatches focus-record when a record is present; unknown app/ws/record
    # fail closed (no navigation).
    script = (
        "const m=require(%s);"
        "const h={"
        "  'open-app':function(p){got.push(['open',p.appId])},"
        "  'focus-record':function(p){got.push(['record',p.appId,p.workstreamId,p.recordRef])},"
        "  'switch-workstream':function(p){got.push(['ws',p.workstreamId])}"
        "};let got=[];"
        "const d=m.parseDeepLink('#app=decisions&ws=WS-042&record=42');"
        "if(d.appId!=='decisions'||d.workstreamId!=='WS-042'||d.recordRef!=='42')process.exit(2);"
        "const d2=m.parseDeepLink('#app=evidence&ws=WS-042');"
        "if(d2.recordRef!==null)process.exit(3);"
        "if(m.applyDeepLink('#app=decisions&ws=WS-042&record=42',h)!==true)process.exit(4);"
        "if(got.length!==2||got[0][0]!=='ws'||got[1][0]!=='record'||got[1][2]!=='WS-042'||got[1][3]!=='42')process.exit(5);"
        "console.log('ok');"
    ) % json.dumps(str(WIDGET / "shell-commands.js"))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


def test_activity_panel_close_semantics_and_mobile_sheet():
    # Panel closes with Escape, close control, or outside interaction; on
    # mobile it becomes a full-screen sheet (media query in scoped styles).
    assert 'ev.key==="Escape"' in S55C_JS
    assert "data-activity-close" in S55C_JS
    assert "ev.target.closest(\"[data-activity-panel]\")" in S55C_JS
    assert "@media(max-width:720px)" in S55C_JS
    assert "width:100vw" in S55C_JS


def test_activity_synthetic_mode_non_mutating():
    # The panel renders from the shell-owned synthetic model and exposes no
    # authoritative mutations; item actions are navigation only.
    assert "state.model.synthetic" in S55C_JS
    assert "state.model&&state.model.workstreams" in S55C_JS
    assert "focus-record" in S55C_COMMANDS
    # S5.5c review: the focus-record handler validates the record reference
    # against the model (unknown records fail closed).
    assert 'String(x.number||x.id)===String(p.recordRef)' in S55C_JS


# --- S5.5d: desktop chrome + hierarchy (issue #457) ---------------------
# os.css ownership transfers to S5.5d (operator decision D7): dead console
# styling removed; compact dock states; no top app-tab row; primary/secondary
# composition (Work full-canvas when alone); window active/inactive chrome;
# empty desktop; motion/a11y/responsive hardening.

S55D_CSS = (WIDGET / "os.css").read_text(encoding="utf-8")
S55D_HTML = (WIDGET / "index.html").read_text(encoding="utf-8")
S55D_JS = (WIDGET / "work-console.js").read_text(encoding="utf-8")


def test_os_css_has_no_dead_console_styling():
    # AC1: the retired Work Console markup's selectors are gone from os.css;
    # the selectors that remain are live (home/launcher/dock/windows/empty
    # desktop are all still rendered).
    for dead in ("console-layout", "console-nav", "console-content",
                 "attention-card", "workstream-row", "review-grid",
                 "authority-card", "app-drawer", "home-surface"):
        assert dead not in S55D_CSS, dead
    # Live shared selectors must survive (used by the current renderers).
    for live in (".empty-state", ".review-actions", ".projection-list",
                 ".primary-action", ".eyebrow", ".binding-indicator",
                 ".ws-item", ".app-launcher", ".empty-desktop"):
        assert live in S55D_CSS, live


def test_dock_states_compact_and_distinct():
    # AC2: favorite (outlined icon + tooltip label via aria-label), running
    # (quiet dot), active (accent underline/raised + dot) are visually
    # distinct; deferred apps never appear in the dock (existing S4 test).
    assert ".os-dock button.running::after" in S55D_CSS
    assert ".os-dock button.active::before" in S55D_CSS
    assert ".os-dock button.active{" in S55D_CSS
    assert ".os-dock button:focus-visible" in S55D_CSS
    assert ".os-dock button{min-height:40px}" in S55D_CSS
    assert 'dk.setAttribute("aria-label",a.title)' in S55D_JS  # tooltip label


def test_no_top_app_tab_row_in_chrome():
    # AC3: the os-bar holds system chrome only; no permanent per-app text-tab
    # row (apps live in the dock/launcher/mobile nav, rendered from the
    # registry).
    assert 'data-app-tab' not in S55D_HTML
    assert 'class="app-tabs"' not in S55D_HTML
    assert 'data-app="' not in S55D_HTML  # no hardcoded per-app buttons
    osbar = S55D_HTML[S55D_HTML.index("<header class=\"os-bar\""):S55D_HTML.index("</header>")]
    assert "data-ws-toggle" in osbar and "data-launcher-toggle" in osbar
    assert "data-activity-toggle" in osbar and "data-exit-workspace" in osbar


def test_primary_full_canvas_when_alone_and_tiled_with_secondaries():
    # AC4: Work is full-canvas when it is the only open window (no empty
    # right column); a requested secondary tiles the right column via the
    # existing geometry.
    assert 'if(secondaryOpenIds().length===0)tiles["work"]={x:0,y:0,w:1,h:1};' in S55D_JS
    assert ".app-window.primary{left:0;top:0;width:100%;height:100%;z-index:1}" in S55D_CSS
    assert "function tileRects(openIds)" in S55D_JS  # secondary tiling intact


def test_window_active_inactive_chrome_and_focus_ring():
    # AC5: focused vs unfocused windows are visually distinct; a visible
    # focus ring exists on interactive chrome controls.
    assert ".app-window:not(.focused):not(.minimized){opacity:.92}" in S55D_CSS
    assert ".app-window.focused{outline:1px solid var(--accent)}" in S55D_CSS
    assert "outline:2px solid var(--accent);outline-offset:2px" in S55D_CSS


def test_empty_desktop_styled_and_usable():
    # AC6: the empty desktop is styled and raised above the canvas; the
    # launcher affordance is present.
    assert ".empty-desktop{z-index:5}" in S55D_CSS
    assert ".empty-desktop{" in S55D_CSS
    assert "data-empty-desktop" in S55D_HTML
    assert 'data-launcher-toggle' in S55D_HTML


def test_motion_a11y_responsive_hardening():
    # AC7: reduced motion respected; keyboard focus visible; coarse-pointer
    # targets adequate (44px mobile nav); narrow-width chrome correct.
    assert "@media(prefers-reduced-motion:reduce)" in S55D_CSS
    assert ".mobile-nav button{min-height:44px}" in S55D_CSS
    assert "@media(max-width:720px)" in S55D_CSS
    assert ".os-dock{display:none}" in S55D_CSS  # dock hidden on mobile
    assert ".window-actions{display:none}" in S55D_CSS  # no desktop chrome on mobile
