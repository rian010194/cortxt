"""Deterministic checks for the Cortxt OS shell core (issue #418; S6a).

The shell is plain HTML/CSS/JS with no JS test runner in this repo, so these
tests inspect the shell source the same way the sibling widget-host tests do
(string / JSON assertions), plus behavioral checks executed in a DOM-less Node
runtime for the pure helpers.

S6a (issue #459) establishes the approved single-primary-surface interaction
model: Home and Work are shell/primary SURFACES (not windows), deep
capabilities open in context with a back path, multi-window is an explicit
opt-in, Activity Center is a shell-owned attention overlay, and the global
chrome is restrained (identity, Home, Work, Workstream context, search,
Activity, profile). The accepted ADR-044 vocabulary and authority boundary are
unchanged.
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

SURFACES = {"home", "work"}
REGISTERED_WINDOWS = {"decisions", "evidence", "policies", "execution", "atlas", "connections", "studio"}


def _widget_read(name):
    """Read a widget file directly from THIS checkout's widget dir (pins
    assertions to the checkout that actually contains this file, #432)."""
    base = Path(__file__).resolve().parents[2]
    return (base / "widget" / name).read_text(encoding="utf-8")


# --- one authoritative app registry ----------------------------------------

def test_registry_ids_are_unique():
    ids = [app["id"] for app in APPS["apps"]]
    assert len(ids) == len(set(ids)), f"duplicate app id in apps.json: {ids}"


def test_registry_surface_and_window_kinds():
    # S6a: Home is a shell-owned system surface and Work is the primary
    # surface; neither is an ordinary window. Registered apps stay windows for
    # the explicit opt-in multi-window mode.
    by_id = {app["id"]: app for app in APPS["apps"]}
    assert by_id["home"]["kind"] == "surface"
    assert by_id["home"]["window"] is None
    assert by_id["work"]["kind"] == "primary"
    assert by_id["work"]["window"] is None
    assert by_id["work"]["route"] == "/work"
    assert by_id["work"]["mode"] == "operator"
    for app_id in REGISTERED_WINDOWS:
        assert by_id[app_id]["kind"] == "window", app_id
        assert "window" in by_id[app_id] and by_id[app_id]["window"], app_id
    # ADR-044: Work Console is retired; no `workspace` app identity exists.
    assert "work-console" not in by_id
    assert "workspace" not in by_id
    # every non-"all" entry keeps icon + route.
    for app in APPS["apps"]:
        if app["id"] == "all":
            continue
        assert "icon" in app and "route" in app
        assert app["mode"] in {"operator", "public"}
        assert isinstance(app.get("mobile"), bool)


def test_shell_markup_has_no_hardcoded_per_app_button_list():
    # The chrome is rendered from the registry, not hard-coded. The permanent
    # primary navigation is restrained: Home and Work only.
    assert 'data-mobile-nav' in HTML and 'data-nav-home' in HTML and 'data-nav-work' in HTML
    assert HTML.count('data-app="') == 0
    assert 'apps.json' in JS
    assert 'function renderMobileNav()' in JS
    assert 'data-app-list' not in HTML
    assert 'data-app-drawer' not in HTML


def test_maker_studio_host_excludes_deferred_apps_from_its_rail():
    maker = (WIDGET / "maker.html").read_text(encoding="utf-8")
    assert 'filter(function(a){ return a.kind !== "deferred"; })' in maker


# --- S6a: system-surface vs app presentation ------------------------------

def test_home_is_a_system_surface_not_an_ordinary_window():
    # ADR-044 item 5 + S6a AC2: Home is a shell-owned system surface with no
    # window chrome. No `data-window="home"` window section exists and no
    # close/min/max control targets it.
    assert 'data-window="home"' not in HTML
    assert 'data-close-window="home"' not in HTML
    assert 'data-window-min="home"' not in HTML
    assert 'data-window-max="home"' not in HTML
    assert 'data-surface="home"' in HTML
    assert 'data-home-body' in HTML
    # The shell never renders Home through the window lifecycle.
    assert 'openApp("home")' not in JS
    assert 'function openHome()' in JS


def test_work_is_a_primary_surface_not_a_window():
    assert 'data-window="work"' not in HTML
    assert 'data-close-window="work"' not in HTML
    assert 'data-surface="work"' in HTML
    assert 'data-work-body' in HTML
    assert 'function openWork()' in JS


def test_deep_capability_surface_in_context():
    # Deep capabilities open in context on the primary surface with a back
    # path (S6a AC4), plus an explicit "Open in new window" opt-in.
    assert 'data-surface="deep"' in HTML
    assert 'data-deep-body' in HTML
    assert 'data-deep-back' in HTML
    assert 'data-deep-window' in HTML
    assert 'function openDeep(appId,recordRef)' in JS


def test_no_empty_desktop_in_default_journey():
    # The empty-desktop state is gone from the shell: a normal entry/resume
    # journey always has a primary surface (Home or Work).
    assert 'data-empty-desktop' not in HTML
    assert "empty-desktop" not in CSS
    assert "No windows open" not in HTML


def test_restrained_global_chrome():
    # The os-bar holds only: identity (-> landing), Home, Work, workstream
    # context, search/command, Activity, profile. No launcher drawer, no dock,
    # no Exit affordance.
    osbar = HTML[HTML.index("<header class=\"os-bar\""):HTML.index("</header>")]
    for marker in ("data-nav-home", "data-nav-work", "data-ws-toggle",
                   "data-search-toggle", "data-activity-toggle"):
        assert marker in osbar, marker
    assert "data-launcher-toggle" not in osbar
    assert "data-os-dock" not in HTML
    assert "data-launcher-list" not in HTML
    assert "data-exit-workspace" not in HTML
    assert "Exit Workspace" not in HTML


# --- shell state separation ----------------------------------------------

def test_state_separates_surfaces_ui_context_and_app_local_view():
    assert 'primary:"home"' in JS
    assert 'deepApp:null' in JS and 'deepRec:null' in JS and 'multiMode:false' in JS
    assert 'ui:{open:{}' in JS and 'zTop:' in JS and 'mobileApp:' in JS
    assert 'context:{workstreamId:null,activeWorkstreamId:null}' in JS
    assert 'apps:{}' in JS
    assert 'windows:[]' in JS


# --- context propagation + persistence ---------------------------------

def test_single_persistence_key_carries_v4_state():
    assert 'SHELL_KEY="cortxt-os-shell"' in JS
    assert 'JSON.stringify({v:4,primary:state.primary,deepApp:state.deepApp,deepRec:state.deepRec,multiMode:state.multiMode' in JS
    assert 'function restore()' in JS and 'localStorage.getItem(SHELL_KEY)' in JS
    assert 'function migrateSavedState(saved)' in JS
    assert 'saved.schemaVersion=4' in JS


def test_selecting_a_workstream_propagates_to_every_mounted_app():
    assert 'function selectWorkstream(id){' in JS
    for selector in ('[data-active-context]', '[data-decisions-body]',
                     '[data-evidence-body]', '[data-studio-frame]'):
        assert selector in JS
    assert 'persist();renderSwitcher();renderAll();' in JS
    assert 'var workEl=q("[data-work-body]")' in JS


def test_reload_restores_selected_workstream_by_id_not_by_position():
    # currentItem() finds the selected Workstream by id and returns null when
    # nothing is selected (S6a first-time context consistency: no implicit
    # fallback to the first Workstream).
    assert 'list.find(function(x){return x.id===wanted})' in JS
    assert 'if(!wanted)return null' in JS
    assert 'if(!wanted&&list.length)return list[0]' not in JS


def test_first_time_entry_stays_unbound():
    # S6a correction 1: a genuine first-time/no-Workstream entry must not
    # display an active Workstream; the chrome chip defaults to a truthful
    # unbound state.
    assert "No Workstream selected" in HTML
    assert 'chip.textContent=x?(x.id+" · "+x.title):"No Workstream selected"' in JS
    # The first-time Home surface explains the smallest next step and the
    # demo selection binds explicitly.
    assert 'if(!s.hadSavedSession)' in JS
    assert "Start a Workstream" in JS
    assert "Explore the demo Workstream" in JS
    assert 'selectWorkstream(items()[0].id)' in JS


# --- S6b: Home resume experience (issue #461) ----------------------------

def test_home_resume_default_behavior():
    # S6b AC1: a returning session renders a resume card for the selected
    # Workstream with one obvious action that enters Work; Home has no window
    # chrome.
    assert "Resume your work" in JS
    assert 'data-resume-work' in JS
    assert 'Resume Work →' in JS
    assert 'resumeBtn.addEventListener("click",function(){openWork()})' in JS
    assert 'data-window="home"' not in HTML
    # The resume meta surfaces workflow, phase, and the next meaningful
    # action so the operator knows exactly what to resume.
    assert 'resume.nextAction?(" · Next: "+esc(resume.nextAction))' in JS


def test_home_first_time_and_no_selection_states():
    # S6b AC2: distinct first-time and no-selection states with the smallest
    # useful next step; no authoritative state implied before selection.
    assert "Start a Workstream" in JS
    assert "Select or start a Workstream" in JS
    assert "No Workstream is selected. Choose one to resume, or start a new one." in JS
    assert 'data-recent-ws' in JS


def test_home_attention_preview_is_read_only_navigation():
    # S6b AC3: the Home attention preview is a read-only projection; rows
    # navigate via validated focus-record (navigateAttention); no mutation
    # port exists in Home; Activity remains the authoritative surface.
    assert 'attentionItems().filter(function(it){return it.requiresAttention})' in JS
    assert "attention.slice(0,3)" in JS
    assert 'navigateAttention(it)' in JS
    assert 'data-attention-open' in JS
    assert 'data-home-activity' in JS
    assert 'toggleActivity()' in JS
    assert "record-decision" not in JS
    assert 'fetch("api/action"' not in JS


def test_home_has_no_marketing_prose():
    # S6b: Home is operational, not a landing page. No landing-page
    # narrative or "Soon" wall lives in the Home renderer.
    assert "Durable work, in one place." not in JS
    assert "Agents get swapped." not in JS
    assert "Sooner" not in JS
    assert 'disabled aria-disabled="true"' not in JS


def test_home_recent_list_is_recency_ordered():
    # Reviewer finding (S6b): the Home "Recent Workstreams" section must be
    # truthful — it uses the recency+attention sort (recentWorkstreams),
    # excluding the resume Workstream, not raw model order.
    assert "var recent=recentWorkstreams().filter(function(w){return w.id!==x.id}).slice(0,3)" in JS
    assert "function recentWorkstreams()" in JS


# --- surface navigation + multi-window opt-in ----------------------------

def test_one_primary_surface_at_a_time():
    # Exactly one surface is visible; the shell never shows two surfaces.
    assert 'el.hidden=el.dataset.surface!==state.primary' in JS
    assert 'function showPrimary(name)' in JS


def test_multi_window_is_an_explicit_opt_in():
    # S6a AC5: opening a window requires an explicit action; surface apps
    # never become windows; Return to primary collapses windows and restores
    # the focused primary layout.
    assert 'function openWindow(id){' in JS
    assert 'if(!a||isSurfaceKind(a.id))return' in JS
    assert 'state.ui.open[a.id]=true' in JS
    assert 'function returnToPrimary()' in JS
    assert 'state.ui.open={}' in JS
    assert 'data-return-primary' in HTML
    assert 'data-multi-mode' in HTML
    assert 'function openDeep(appId,recordRef)' in JS


def test_open_window_from_deep_returns_to_work_primary():
    # Reviewer finding 1: opening a window from a deep capability collapses
    # the deep surface back to Work so the window and Work are both visible
    # (window mode never duplicates the in-context surface).
    assert 'if(state.primary==="deep"){state.primary="work";state.deepApp=null;state.deepRec=null}' in JS


def test_v4_migration_drops_surface_windows():
    # Reviewer finding 2: v4 surfaces (home/work) are never windows; the
    # migration removes them from the window model so an upgrading S5.5
    # session cannot show the multi-window bar with zero windows.
    assert '["home","work"].forEach(function(surf){if(saved.ui[k][surf]!==undefined)delete saved.ui[k][surf]})' in JS


def test_focus_record_accepts_prefixed_and_bare_refs():
    # Reviewer finding 3: the documented deep-link form record=#<number> and
    # the bare form both resolve known records; unknown records still fail
    # closed.
    assert 'var ref=String(p.recordRef).replace(/^#/,"")' in JS
    assert 'String(x.number||x.id)===ref' in JS


def test_narrow_never_shows_window_chrome():
    # Mobile is one surface at a time; desktop window behavior is never
    # emulated on narrow layouts.
    assert '@media(max-width:720px)' in CSS
    assert '.window-bar{display:none}' in CSS
    assert '.window-actions{display:none}' in CSS
    assert '.window-resize{display:none!important}' in CSS
    assert '.mobile-nav{position:fixed' in CSS
    assert 'isNarrow()' in JS
    assert 'min-height:44px' in CSS  # coarse-pointer targets


def test_activity_center_is_a_shell_overlay_not_a_window():
    by_id = {a["id"]: a for a in APPS["apps"]}
    assert "activity" not in by_id and "activity-center" not in by_id
    assert 'data-activity-panel' in HTML
    assert 'data-activity-toggle' in HTML
    assert 'data-activity-count' in HTML
    assert 'data-window="activity"' not in HTML
    assert 'activity:{open:false' in JS


# --- desktop window lifecycle (opt-in mode) ------------------------------

def test_desktop_lifecycle_controls_exist_for_registered_apps():
    for app_id in ("decisions", "evidence"):
        assert f'data-window-focus="{app_id}"' in HTML
        assert f'data-window-min="{app_id}"' in HTML
        assert f'data-close-window="{app_id}"' in HTML
    for fn in ('function closeWindow', 'function setMin', 'function setMax',
               'function toggleMax', 'function focusWindow'):
        assert fn in JS
    assert 'function activeWindowId()' in JS
    assert 'state.ui.z[id]=++state.ui.zTop' in JS  # focus raises z-order


def test_pointer_down_on_window_surface_gives_focus():
    assert 'document.addEventListener("pointerdown"' in JS
    assert 'ev.target.closest("[data-window]")' in JS
    assert 'focusWindow(appIdForWindow(win.dataset.window))' in JS


def test_move_resize_do_not_require_arrange_mode():
    assert 'function beginWindowDrag(' in JS
    assert 'initCompose();' in JS


# --- mobile single-app routing --------------------------------------

def test_mobile_renders_exactly_one_app_without_window_chrome():
    assert 'function isNarrow(){return window.innerWidth<=NARROW}' in JS
    assert '.window-actions{display:none}' in CSS
    assert '.mobile-nav{position:fixed' in CSS and 'display:flex' in CSS
    assert 'function renderMobileNav()' in JS


def test_mobile_nav_is_minimal_and_deterministic():
    # Mobile navigation is Home · Work · Activity (no app list, no Studio).
    assert '["home","Home"],["work","Work"],["activity","Activity"]' in JS
    assert 'dataset.mobileNav' in JS
    assert '.mobile-nav button{flex:1' in CSS


# --- live responsive transition -----------------------------------

def test_resize_reapplies_view_from_persisted_state_without_reload():
    assert 'window.addEventListener("resize"' in JS
    assert 'function applyView()' in JS
    assert 'location.reload' not in JS


# --- synthetic determinism / authority boundary preserved -----------

def test_authority_boundary_and_synthetic_mode_are_unchanged():
    assert 'fetch("api/workstreams"' in JS
    assert 'fetch("fixtures/workstreams.json"' in JS
    assert 'The shell failed closed: no evidence or decision action is exposed.' in JS
    assert '"X-Cortxt-Token": s.token' in D_RENDERER
    assert 'state.model.synthetic' in JS


# --- canonical design system, no private palette -------------------

ROLE_VARS = ("--bg", "--surface", "--layer", "--hover", "--stroke", "--strong",
             "--text", "--muted", "--dim", "--accent", "--warn", "--bad")


def test_shell_css_has_no_private_palette_and_consumes_canonical_tokens():
    root = CSS[CSS.index(":root{") + len(":root{"):CSS.index("}", CSS.index(":root{"))]
    for role in ROLE_VARS:
        decl = root.split(role + ":", 1)[1].split(";", 1)[0]
        assert decl.startswith("var(--token-") or decl.startswith("color-mix("), (role, decl)
    assert "var(--token-" in CSS
    assert not re.search(r"--token-[\w-]+\s*:(?!,)", CSS), "os.css must not define --token-* properties"


def test_os_shell_loads_canonical_tokens_via_widget_host_adapter():
    assert '<script src="maker.js"></script>' in HTML
    assert HTML.index('src="maker.js"') < HTML.index('src="work-console.js"')
    assert "function loadTokens()" in JS
    assert 'fetch("tokens.json"' in JS
    assert "window.WidgetMaker" in JS and "applyTokens" in JS


def test_motion_focus_and_reduced_preferences():
    assert "@media(prefers-reduced-motion:reduce)" in CSS
    assert "@media(prefers-reduced-transparency:reduce)" in CSS
    assert "outline:2px solid var(--accent);outline-offset:2px" in CSS
    assert "min-height:44px" in CSS


def test_shell_css_has_no_dead_chrome_selectors():
    # S6a removed the dock, launcher drawer, and empty-desktop states.
    for dead in (".os-dock", ".app-launcher", ".empty-desktop", "home-window",
                 "app-window.primary"):
        assert dead not in CSS, dead
    for live in (".os-bar", ".ws-switcher", ".search-panel", ".activity-panel",
                 ".system-surface", ".primary-surface", ".deep-surface",
                 ".multi-mode-bar", ".mobile-nav", ".app-window", ".work-card"):
        assert live in CSS, live


@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
def test_window_tiling_yields_distinct_non_overlapping_rectangles():
    # Behavioral check: the opt-in window tiling produces distinct, in-bounds,
    # pairwise non-overlapping rectangles for 1..3 open windows.
    script = (
        "const m=require(%s);"
        "const eps=1e-9;"
        "function ov(a,b){return a.x<b.x+b.w-eps&&b.x<a.x+a.w-eps&&a.y<b.y+b.h-eps&&b.y<a.y+a.h-eps;}"
        "for(const ids of [['decisions'],['decisions','evidence'],['decisions','evidence','policies']]){"
        "  const r=m.tileRects(ids);"
        "  for(const k of ids){const g=r[k];"
        "    if(!g){console.error('missing',k);process.exit(2);}"
        "    if(g.x<-eps||g.y<-eps||g.x+g.w>1+eps||g.y+g.h>1+eps){console.error('oob',k,JSON.stringify(g));process.exit(3);}}"
        "  for(let i=0;i<ids.length;i++)for(let j=i+1;j<ids.length;j++){"
        "    const A=r[ids[i]],B=r[ids[j]];"
        "    if(JSON.stringify(A)===JSON.stringify(B)){console.error('identical',ids[i],ids[j]);process.exit(4);}"
        "    if(ov(A,B)){console.error('overlap',ids[i],ids[j],JSON.stringify(A),JSON.stringify(B));process.exit(5);}}"
        "}"
        "console.log('ok');"
    ) % json.dumps(str(WIDGET / "work-console.js"))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- Work as the first principal app (ADR-044) ---------------------------

def test_work_app_registered_in_shared_renderer():
    assert 'OSRenderer.register("work",renderWork)' in JS
    assert "function renderWork(" in JS
    assert 'OSRenderer.register("work-console"' not in JS
    assert "function renderWorkConsole(" not in JS


def test_work_surface_never_duplicates_full_app_workflows():
    assert "openReview(" not in JS
    assert "showConsole(" not in JS
    assert "confirmDecision(" not in JS
    assert "data-console-panel" not in HTML
    assert "data-console-view" not in HTML
    assert "data-review" not in HTML
    assert 'action_id: "record-decision"' in D_RENDERER
    assert "data-d-approval" in D_RENDERER


def test_work_summaries_deep_link_with_exact_context():
    # Work's deep-open buttons open the responsible app with the exact
    # Workstream and record context in-context (S6a), with an explicit
    # opt-in window path.
    assert "data-deep-open" in JS
    assert "data-win-open" in JS
    assert 'openDeep(appId,"#"+String(x.number||x.id))' in JS
    assert "function openDeep(appId,recordRef)" in JS


def test_shell_core_has_no_work_specific_branch():
    core = RENDERER + (WIDGET / "shell-commands.js").read_text(encoding="utf-8")
    assert 'if(id==="work")' not in core
    assert 'appId==="work"' not in core
    assert 'workstreamId==="work"' not in core
    # Work registers through the generic registry path like any other app.
    assert 'OSRenderer.register("work",renderWork)' in JS


def test_app_without_workstream_context_can_register_and_open():
    by_id = {a["id"]: a for a in APPS["apps"]}
    assert "work" in by_id and "home" in by_id
    for a in APPS["apps"]:
        assert "requiresWorkstream" not in a, a["id"]
    # The shell never blocks opening on a missing Workstream selection.
    assert 'function openDeep(appId,recordRef)' in JS
    assert 'if(!state.context.workstreamId)return' not in JS


# --- Decisions and Evidence authority journey ---------------------------

def test_decisions_evidence_renderer_loaded_and_registered():
    assert HTML.index('src="os-renderer.js"') < HTML.index('src="app-renderer-decisions-evidence.js"')
    assert HTML.index('src="app-renderer-decisions-evidence.js"') < HTML.index('src="work-console.js"')
    assert 'OSRenderer.register("decisions", renderDecisions)' in D_RENDERER
    assert 'OSRenderer.register("evidence", renderEvidence)' in D_RENDERER


def test_decisions_is_an_authority_aware_app():
    assert "function renderDecisions(winEl, ctx)" in D_RENDERER
    assert "No authoritative decision is pending" in D_RENDERER
    assert 'data-d-accept' in D_RENDERER
    assert "Approval reference is required." in D_RENDERER
    assert '"X-Cortxt-Token": s.token' in D_RENDERER


def test_evidence_is_attributable_and_read_only():
    assert "function renderEvidence(winEl, ctx)" in D_RENDERER
    assert "No authoritative evidence is attached." in D_RENDERER
    assert "ev.status" in D_RENDERER
    assert "review-actions" not in D_RENDERER.split("function renderEvidence")[1]


# --- Activity Center authority boundary (ADR-044) ------------------------

def test_activity_center_has_no_mutation_port():
    assert 'action_id: "record-decision"' in D_RENDERER
    assert 'record-decision' not in JS  # shell core exposes no decision mutation
    assert 'AttentionItemProjection' in JS
    assert 'function isValidAttentionItem(item)' in JS
    contract = JS[JS.index('AttentionItemProjection={'):JS.index('};', JS.index('AttentionItemProjection={'))]
    for banned in ('mutat', 'approve', 'workflow'):
        assert banned not in contract, banned


def test_activity_cannot_invoke_workflow_or_decision_mutations():
    assert "record-decision" not in JS
    assert "data-activity-accept" not in JS
    assert "data-activity-approve" not in JS
    assert 'fetch("api/action"' not in JS
    assert 'data-activity-open' in JS
    assert 'dispatchCommand("focus-record"' in JS or 'navigateAttention(it)' in JS
    assert "Presentation state is local. Workflow status is authoritative." in JS


@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
def test_attention_item_validation_behavioral():
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


# --- migration (v1 -> v4) ------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
def test_v2_to_v4_migration_renames_work_console_and_derives_primary():
    # Behavioral: work-console references migrate to `work` across every
    # carrier; the v4 primary surface derives from the previous session
    # shape; the selected Workstream and other apps are preserved.
    script = (
        "const m=require(%s);"
        "const saved={v:3,ui:{open:{'work-console':true,'decisions':true},mobileApp:'work-console',z:{'work-console':5},min:{},max:{},geom:{}},context:{workstreamId:'WS-042'},apps:{'work-console':{panel:'attention'},'decisions':{}},windows:[{id:'win-work-console',appId:'work-console',contextBinding:{mode:'locked',workstreamId:'WS-042'}},{id:'win-decisions',appId:'decisions'}],dockFavorites:['work-console','decisions','evidence'],desktopLayout:{}};"
        "m.migrateSavedState(saved);"
        "if(saved.ui.open['work']!==undefined||saved.ui.open['work-console']!==undefined)process.exit(2);"
        "if(saved.ui.open['decisions']!==true)process.exit(3);"
        "if(saved.ui.mobileApp!=='work')process.exit(4);"
        "if(saved.ui.z['work']!==undefined)process.exit(5);"
        "if(saved.context.workstreamId!=='WS-042')process.exit(6);"
        "if(saved.apps['work']===undefined||saved.apps['work-console']!==undefined)process.exit(7);"
        "if(saved.windows[0].appId!=='work'||saved.windows[1].appId!=='decisions')process.exit(8);"
        "if(saved.dockFavorites[0]!=='work')process.exit(9);"
        "if(saved.primary!=='work')process.exit(10);"
        "if(saved.schemaVersion!==4)process.exit(11);"
        "if(saved.ui.open['work']!==undefined)process.exit(13);"
        "const unbound={v:3,ui:{open:{},mobileApp:'work'},context:{workstreamId:null},apps:{},windows:[],dockFavorites:[]};"
        "m.migrateSavedState(unbound);"
        "if(unbound.primary!=='home')process.exit(12);"
        "console.log('ok');"
    ) % json.dumps(str(WIDGET / "work-console.js"))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- terminology regression (S6a) ----------------------------------------

def test_no_user_facing_workspace_misuse():
    # "Workspace" is reserved for the optional Git execution resource. It must
    # not appear as a label for Cortxt OS, Home, Work, or navigation.
    assert "Exit Workspace" not in HTML
    assert "data-exit-workspace" not in HTML
    assert "exit-workspace" not in JS
    assert "Soon" not in HTML and "Soon" not in JS
    assert "First principal app" not in HTML and "First principal app" not in JS
    assert "Related app" not in HTML and "Related app" not in JS
    assert "data-window=\"console\"" not in HTML


# --- site mirror parity ------------------------------------------

@pytest.mark.parametrize("name", [
    "index.html", "os.css", "work-console.js", "apps.json",
    "shell-commands.js", "os-renderer.js", "app-renderer-decisions-evidence.js",
])
def test_site_mirror_is_identical(name):
    assert (WIDGET / name).read_text(encoding="utf-8") == (MIRROR / name).read_text(encoding="utf-8")


# --- S1a: Studio navigation boundary (issue #435) -----------------

SITE_MAKER = (MIRROR / "maker.js").read_text(encoding="utf-8")
SHELL_BRIDGE = (WIDGET / "shell-iframe-bridge.js").read_text(encoding="utf-8")
SITE_HTML = (MIRROR / "index.html").read_text(encoding="utf-8")


def test_studio_back_no_longer_navigates_to_workspace_or_widgets():
    assert 'studio-back" href="/workspace/"' not in SITE_MAKER
    assert 'href="/workspace/"' not in SITE_MAKER
    assert '<a class="studio-back"' not in SITE_MAKER
    assert 'data-studio-back' in SITE_MAKER
    assert 'parent.postMessage' in SITE_MAKER


def test_studio_sends_only_the_allowed_shell_command():
    assert '"activate-app"' in SITE_MAKER
    assert '"cortxt-os-iframe"' in SITE_MAKER
    assert 'v: 1' in SITE_MAKER


def test_parent_validates_origin_command_and_payload():
    shell = (WIDGET / "work-console.js").read_text(encoding="utf-8")
    assert 'ShellIframeBridge.listenFromIframe' in shell
    assert 'validateMessage' in SHELL_BRIDGE
    assert 'normalizeOrigin' in SHELL_BRIDGE
    assert 'ALLOWED_COMMANDS' in SHELL_BRIDGE
    assert '"activate-app"' in SHELL_BRIDGE
    assert 'ALLOWED_APP_IDS' in SHELL_BRIDGE


def test_no_nested_os_mount_and_recursion_guard_present():
    assert 'isRecursionMount' in JS
    assert 'window.top' in JS
    assert '<strong>Open in Cortxt OS</strong>' in JS


def test_docs_link_points_to_real_docs():
    assert '"/docs/widgets/"' in SITE_MAKER
    assert 'studio-links"><a href="/docs/widgets/"' in SITE_MAKER


# --- S1b: shell command router, deep links, history ----------------------

SHELL_COMMANDS = (WIDGET / "shell-commands.js").read_text(encoding="utf-8")


def test_command_router_defines_typed_commands():
    for cmd in ('"open-app"', '"close-app"', '"focus-app"', '"switch-workstream"',
                '"open-home"', '"open-external"', '"focus-record"',
                '"open-window"', '"return-primary"'):
        assert cmd in SHELL_COMMANDS
    assert '"exit-workspace"' not in SHELL_COMMANDS
    assert 'dispatch: function (command, payload, handlers)' in SHELL_COMMANDS
    assert 'if (!APP_COMMANDS[command]) return false;' in SHELL_COMMANDS


def test_deep_link_parser_supports_app_ws_and_record():
    assert 'function parseDeepLink(hash)' in SHELL_COMMANDS
    assert 'out.appId = normalizeAppId(v)' in SHELL_COMMANDS
    assert 'out.workstreamId = v' in SHELL_COMMANDS
    assert 'applyDeepLink' in SHELL_COMMANDS


def test_shell_wires_command_handlers():
    assert 'window.ShellCommandHandlers=commandHandlers' in JS
    assert '"open-app":function(p){' in JS
    assert '"open-home":function(){openHome()}' in JS
    assert '"open-window":function(p){if(p&&p.appId)openWindow(migrateWorkConsole(p.appId))}' in JS
    assert '"return-primary":function(){returnToPrimary()}' in JS
    # No exit-workspace navigation to "/" remains.
    assert 'window.location.href="/"' not in JS
    assert 'global.location.href' not in JS


def test_boot_and_hashchange_apply_deep_links():
    assert 'var bootHash=(typeof location!=="undefined")?location.hash:""' in JS
    assert 'ShellCommands.applyDeepLink(bootHash,window.ShellCommandHandlers)' in JS
    assert 'window.addEventListener("hashchange"' in JS
    assert 'ShellCommands.applyDeepLink(location.hash,commandHandlers)' in JS
    assert 'location.reload' not in JS


def test_history_push_integration():
    assert 'function pushShellState()' in JS
    assert 'ShellCommands.pushState(surfaceAppId()||null,activeContextId())' in JS


def test_router_behavior_in_domless_runtime():
    script = (
        "const m=require(%s);"
        "let got=[];"
        "const h={"
        "  'open-app':function(p){got.push(['open',p.appId])},"
        "  'switch-workstream':function(p){got.push(['ws',p.workstreamId])},"
        "  'open-window':function(p){got.push(['win',p.appId])},"
        "  'return-primary':function(){got.push(['return'])},"
        "};"
        "if(m.dispatch('open-app',{appId:'studio'},h)!==true)process.exit(2);"
        "if(m.dispatch('nope',{},h)!==false)process.exit(3);"
        "if(m.dispatch('open-app',{},null)!==false)process.exit(4);"
        "if(m.dispatch('exit-workspace',{},h)!==false)process.exit(5);"
        "if(m.dispatch('open-window',{appId:'decisions'},h)!==true)process.exit(6);"
        "if(m.dispatch('return-primary',{},h)!==true)process.exit(7);"
        "const d1=m.parseDeepLink('#app=studio&ws=WS-042');"
        "if(d1.appId!=='studio'||d1.workstreamId!=='WS-042')process.exit(8);"
        "const d2=m.parseDeepLink('');"
        "if(d2.appId!==null||d2.workstreamId!==null)process.exit(9);"
        "const d3=m.parseDeepLink('#ws=all');"
        "if(d3.workstreamId!=='all')process.exit(10);"
        "const d4=m.parseDeepLink('#app=work-console&ws=WS-042');"
        "if(d4.appId!=='work'||d4.workstreamId!=='WS-042')process.exit(11);"
        "if(m.normalizeAppId('work-console')!=='work')process.exit(12);"
        "const d5=m.parseDeepLink('#app=decisions&ws=WS-042&record=42');"
        "if(d5.recordRef!=='42')process.exit(13);"
        "if(got.length!==3||got[0][0]!=='open'||got[1][0]!=='win'||got[2][0]!=='return')process.exit(14);"
        "console.log('ok');"
    ) % json.dumps(str(WIDGET / "shell-commands.js"))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr or out.stdout
    assert "ok" in out.stdout


# --- S6a: landing/docs terminology reconciliation ------------------------

def test_workspace_page_is_a_real_entry_deep_linking_home():
    ws = Path(__file__).resolve().parents[3] / "site" / "src" / "pages" / "workspace.astro"
    text = ws.read_text(encoding="utf-8")
    assert '/widgets/#app=home' in text
    assert "location.replace('/widgets/#app=home')" in text
    assert "Work Console" not in text


def test_landing_nav_does_not_label_the_os_workspace():
    # The OS entry keeps its URL but is no longer labelled "Workspace";
    # "Cortxt OS" is the OS entry label.
    idx = Path(__file__).resolve().parents[3] / "site" / "src" / "pages" / "index.astro"
    text = idx.read_text(encoding="utf-8")
    assert 'href="/widgets/">Cortxt OS</a>' in text
    assert 'href="/workspace/">Home</a>' in text
    assert "Work Console" not in text
