(function(){"use strict";
/* Cortxt OS shell core (ADR-044: general shell and first-party app runtime).
   S6a: single-primary-surface interaction model (operator-approved prototype
   lab/s6-prototype). One authoritative app registry (apps.json) drives the
   shell chrome, the deep-capability routing, and window resolution.

   Presentation model (S6a):
     - Home and Work are shell/primary SURFACES, not windows: one primary
       surface at a time, no window chrome, no empty desktop in the default
       journey.
     - Deep capabilities (Decisions, Evidence, Policies, Execution Inspector,
       Atlas, Connections, Studio) open IN CONTEXT on the primary surface with
       a clear back path to Work, preserving the active Workstream and record.
     - Multi-window remains an explicit opt-in ("Open in new window") with
       focus/move/resize/minimize/restore and a "Return to primary" action;
       it is never the default and never appears on narrow layouts.
     - Activity Center is a shell-owned attention overlay; search/command is a
       shell affordance; the workstream switcher is the global context.

   State (schema v4, additive over v3):
     state.primary   "home" | "work" | "deep"   the active primary surface
     state.deepApp   appId of the in-context deep capability (when deep)
     state.deepRec   optional record ref
     state.ui.open   open WINDOWS only (explicit multi-window opt-in)
     state.context   the selected Workstream, propagated to every mounted app
     state.apps      app-local view state (never authoritative)
     state.windows   WindowInstance model (S2) for the opt-in window mode
   The authority boundary (load/loadBoundary) is unchanged and still fails
   closed. Work is the first principal app, not the identity of the OS;
   Home and Activity Center are system surfaces. */
var SHELL_KEY="cortxt-os-shell",NARROW=720;
var state={
  model:null,token:null,capabilities:[],registry:[],
  primary:"home",deepApp:null,deepRec:null,multiMode:false,
  ui:{open:{},min:{},max:{},z:{},zTop:10,geom:{},mobileApp:"home"},
  context:{workstreamId:null,activeWorkstreamId:null},
  apps:{},
  windows:[],
  dockFavorites:[],
  desktopLayout:{},
  activity:{open:false,filters:{groupBy:"time",types:{},workstreamId:null},read:{},dismissed:{}},
  schemaVersion:4,
  hadSavedSession:false
};
var q=function(s,r){return(r||document).querySelector(s)},qa=function(s,r){return Array.from((r||document).querySelectorAll(s))};
var esc=function(v){return String(v==null?"":v).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})};
function empty(message){return '<div class="empty-state">'+esc(message)+'</div>'}

/* ---- canonical design tokens (ADR-043) -------------------------------- */
function applyTokens(t){
  var wm=(typeof window!=="undefined")&&window.WidgetMaker;
  if(wm&&wm.applyTokens){wm.applyTokens(t);return}
  var root=document.documentElement,c=(t&&t.colors)||{};
  Object.keys(c).forEach(function(k){root.style.setProperty("--token-"+k,c[k]);root.style.setProperty("--"+k,c[k])});
}
async function loadTokens(){
  var wm=(typeof window!=="undefined")&&window.WidgetMaker;
  try{var r=await fetch("tokens.json",{cache:"no-store"});if(!r.ok)throw Error(r.status);applyTokens(await r.json())}
  catch(_e){if(wm&&wm.defaultTokens)applyTokens(wm.defaultTokens())}
}

/* ---- persistence (schema v4, additive over v3) ------------------------ */
var LEGACY_APP_ALIASES={"work-console":"work"};
function migrateWorkConsole(ref){return LEGACY_APP_ALIASES[ref]||ref}
function migrateSavedState(saved){
  /* v1 -> v2 -> v3 -> v4 migration on read. v3 (S5.5a/ADR-044) retires Work
     Console across every carrier; v4 (S6a) adds the primary-surface model.
     Never touches the selected Workstream or other apps. */
  if(!saved||typeof saved!=="object")return;
  if(saved.ui&&typeof saved.ui==="object"){
    var ui=saved.ui;
    ["open","min","max","z","geom"].forEach(function(k){
      if(ui[k]&&typeof ui[k]==="object"){
        if(ui[k]["work-console"]!==undefined){ui[k]["work"]=ui[k]["work-console"];delete ui[k]["work-console"]}
      }
    });
    if(ui.mobileApp==="work-console")ui.mobileApp="work";
  }
  if(saved.apps&&typeof saved.apps==="object"){
    if(saved.apps["work-console"]!==undefined){saved.apps["work"]=saved.apps["work-console"];delete saved.apps["work-console"]}
  }
  if(Array.isArray(saved.windows)){
    saved.windows.forEach(function(w){if(w&&w.appId==="work-console")w.appId="work"});
  }
  if(Array.isArray(saved.dockFavorites)){
    for(var i=0;i<saved.dockFavorites.length;i++){
      if(saved.dockFavorites[i]==="work-console")saved.dockFavorites[i]="work";
    }
  }
  if(!saved.activity||typeof saved.activity!=="object")saved.activity={open:false,filters:{groupBy:"time",types:{},workstreamId:null},read:{},dismissed:{}};
  /* v4: derive the primary surface from the previous session shape. A saved
     session that had Work open resumes Work; anything else resumes Home.
     Surfaces are never windows in v4: drop home/work from the window model. */
  if(saved.primary==null){
    var hadWork=!!(saved.ui&&saved.ui.open&&saved.ui.open["work"]);
    saved.primary=hadWork?"work":"home";
  }
  if(saved.deepApp==null)saved.deepApp=null;
  if(saved.deepRec==null)saved.deepRec=null;
  if(saved.multiMode==null)saved.multiMode=false;
  if(saved.ui&&typeof saved.ui==="object"){
    ["open","min","max","z","geom"].forEach(function(k){
      if(saved.ui[k]&&typeof saved.ui[k]==="object"){
        ["home","work"].forEach(function(surf){if(saved.ui[k][surf]!==undefined)delete saved.ui[k][surf]});
      }
    });
    if(saved.ui.mobileApp==="home"||saved.ui.mobileApp==="work")saved.ui.mobileApp=saved.primary;
  }
  saved.schemaVersion=4;
}
function persist(){
  try{localStorage.setItem(SHELL_KEY,JSON.stringify({v:4,primary:state.primary,deepApp:state.deepApp,deepRec:state.deepRec,multiMode:state.multiMode,ui:state.ui,context:state.context,apps:state.apps,windows:state.windows,dockFavorites:state.dockFavorites,desktopLayout:state.desktopLayout,activity:state.activity,schemaVersion:4}))}catch(_e){}
}
function restore(){
  var saved;try{saved=JSON.parse(localStorage.getItem(SHELL_KEY)||"null")}catch(_e){saved=null}
  state.hadSavedSession=!!(saved&&typeof saved==="object"&&(saved.ui||saved.windows||saved.primary));
  if(!saved||typeof saved!=="object")return;
  migrateSavedState(saved);
  if(typeof saved.primary==="string")state.primary=saved.primary;
  if(saved.deepApp)state.deepApp=saved.deepApp;
  if(saved.deepRec)state.deepRec=saved.deepRec;
  if(saved.multiMode)state.multiMode=saved.multiMode;
  if(saved.ui&&typeof saved.ui==="object"){
    state.ui=Object.assign(state.ui,saved.ui);
    state.ui.open=Object.assign({},saved.ui.open);
    state.ui.min=Object.assign({},saved.ui.min);state.ui.z=Object.assign({},saved.ui.z);
    state.ui.max=(saved.ui.max&&typeof saved.ui.max==="object")?Object.assign({},saved.ui.max):{};
    state.ui.geom=(saved.ui.geom&&typeof saved.ui.geom==="object")?Object.assign({},saved.ui.geom):{};
  }
  if(saved.context&&typeof saved.context.workstreamId==="string")state.context.workstreamId=saved.context.workstreamId;
  if(saved.context&&typeof saved.context.activeWorkstreamId==="string")state.context.activeWorkstreamId=saved.context.activeWorkstreamId;
  if(saved.apps&&typeof saved.apps==="object")state.apps=Object.assign(state.apps,saved.apps);
  if(saved.activity&&typeof saved.activity==="object")state.activity=Object.assign(state.activity,saved.activity);
  if(saved.v===2||saved.v===3||saved.v===4){
    if(Array.isArray(saved.windows))state.windows=saved.windows.slice();
    state.dockFavorites=Array.isArray(saved.dockFavorites)?saved.dockFavorites.slice():[];
    state.desktopLayout=(saved.desktopLayout&&typeof saved.desktopLayout==="object")?saved.desktopLayout:{};
  }
}

/* ---- WindowInstance model (S2) ---------------------------------------- */
function windowForApp(id){
  return state.windows.find(function(w){return w.appId===id})||null;
}
function bindingLabel(id){
  var w=windowForApp(id);
  if(!w||!w.contextBinding)return "follows active";
  if(w.contextBinding.mode==="locked")return "locked: "+(w.contextBinding.workstreamId||"?");
  if(w.contextBinding.mode==="global")return "All Work";
  return "follows active";
}

/* ---- authoritative app registry -------------------------------------- */
async function loadRegistry(){
  try{var r=await fetch("apps.json",{cache:"no-store"});if(r.ok){var data=await r.json();state.registry=(data.apps||[]).filter(function(a){return a.id})}}catch(_e){state.registry=[]}
  if(!state.registry.length)state.registry=[{id:"work",title:"Work",short:"Work",kind:"primary"}];
}
function appById(id){return state.registry.find(function(a){return a.id===id})||null}
function windowOf(id){var a=appById(id);return a&&a.window?a.window:id}
function appIdForWindow(win){var a=state.registry.find(function(x){return(x.window||x.id)===win});return a?a.id:win}
function isSurfaceKind(id){var a=appById(id);return a&&(a.kind==="surface"||a.kind==="primary")}
function activeWindowId(){
  /* Highest z-order among open, non-minimized WINDOWS (opt-in window mode). */
  var best=null,bz=-1;
  Object.keys(state.ui.open).forEach(function(id){
    if(!state.ui.open[id]||state.ui.min[id])return;
    var z=state.ui.z[id]||0;
    if(z>=bz){bz=z;best=id}
  });
  return best;
}
function anyOpenWindows(){
  return Object.keys(state.ui.open).some(function(id){return !!state.ui.open[id]&&!state.ui.min[id]});
}

/* ---- selected Workstream context ------------------------------- */
function items(){return(state.model&&state.model.workstreams)||[]}
function currentItem(){
  /* S6a correction: no implicit fallback to the first Workstream. A genuine
     first-time / no-selection state stays unbound ("No Workstream selected");
     an explicit selection is the only thing that binds context. */
  var list=items(),wanted=state.context.workstreamId;
  if(!wanted)return null;
  return list.find(function(x){return x.id===wanted})||null;
}
function selectWorkstream(id){
  /* id: a workstream id, "all", or null (no selection). */
  if(id!==activeContextId()&&hasPendingMutation()&&!window.confirm("Switch Workstream? Any unsaved approval reference will be discarded."))return;
  state.context.activeWorkstreamId=(id==="all")?"all":id;
  state.context.workstreamId=(id==="all")?null:id;
  persist();renderSwitcher();renderAll();
  pushShellState();
}
function activeContextId(){return state.context.activeWorkstreamId||state.context.workstreamId||null}
function hasPendingMutation(){
  var openDialog=document.querySelector("dialog[open]");
  if(openDialog)return true;
  var ref=q("[data-d-approval]");
  if(ref&&ref.value&&ref.value.trim())return true;
  return false;
}
function recentWorkstreams(){
  var list=items().slice();
  list.sort(function(a,b){
    var aw=a.attention?1:0,bw=b.attention?1:0;
    if(aw!==bw)return bw-aw;
    return (b.number||0)-(a.number||0);
  });
  return list;
}
function renderSwitcher(){
  var root=q("[data-ws-list]");
  if(!root)return;
  var list=items(),active=activeContextId(),recent=recentWorkstreams();
  var html='';
  html+='<button type="button" class="ws-item'+(active==="all"?" active":"")+'" data-ws-id="all"><span class="ws-icon">\u229e</span><span><strong>All Work</strong><small>every workstream</small></span></button>';
  recent.forEach(function(x){
    var on=active===x.id;
    html+='<button type="button" class="ws-item'+(on?" active":"")+'" data-ws-id="'+esc(x.id)+'"><span class="ws-icon">'+(x.attention?'<em class="ws-attention">'+esc(x.attention==="decision"?"D":"B")+'</em>':esc(x.id.slice(0,2)))+'</span><span><strong>'+esc(x.title)+'</strong><small>'+esc(x.id)+(x.attention?' · '+esc(x.attention):'')+'</small></span></button>';
  });
  var done=list.filter(function(x){return x.workflow==="done"});
  if(done.length){
    html+='<div class="ws-group">Archived</div>';
    done.forEach(function(x){
      var on=active===x.id;
      html+='<button type="button" class="ws-item'+(on?" active":"")+'" data-ws-id="'+esc(x.id)+'"><span class="ws-icon">\u2713</span><span><strong>'+esc(x.title)+'</strong><small>'+esc(x.id)+' · accepted</small></span></button>';
    });
  }
  root.innerHTML=html;
  qa("[data-ws-id]",root).forEach(function(b){
    b.addEventListener("click",function(){
      selectWorkstream(b.dataset.wsId);
      var p=q("[data-workstream-switcher]");if(p)p.hidden=true;
      var t=q("[data-ws-toggle]");if(t)t.setAttribute("aria-expanded","false");
    });
  });
  var count=q("[data-ws-create]");
  if(count)count.addEventListener("click",function(){
    OSRenderer.emit("command",{command:"create-workstream"});
  });
}

/* ---- surface navigation (S6a) ---------------------------------------- */
function surfaceAppId(){return state.primary==="deep"?state.deepApp:state.primary}
function pushShellState(){
  if(typeof ShellCommands!=="undefined"&&ShellCommands.pushState&&typeof location!=="undefined"){
    ShellCommands.pushState(surfaceAppId()||null,activeContextId());
  }
}
function showPrimary(name){
  /* name: "home" | "work" | "deep" */
  state.primary=name;
  if(name!=="deep"){state.deepApp=null;state.deepRec=null}
  persist();applyView();renderAll();
  pushShellState();
}
function openHome(){state.ui.mobileApp="home";showPrimary("home")}
function openWork(){state.ui.mobileApp="work";showPrimary("work")}
function openDeep(appId,recordRef){
  var a=appById(migrateWorkConsole(appId));
  if(!a)return;
  state.deepApp=a.id;state.deepRec=recordRef||null;
  state.ui.mobileApp=a.id;
  showPrimary("deep");
}
function openWindow(id){
  /* Explicit opt-in multi-window: surface apps never become windows. When
     opened from a deep capability, the deep surface collapses back to Work
     so the window and Work are both visible (window mode never duplicates
     the in-context surface). */
  var a=appById(id);
  if(!a||isSurfaceKind(a.id))return;
  state.ui.open[a.id]=true;delete state.ui.min[a.id];state.ui.z[a.id]=++state.ui.zTop;
  state.multiMode=true;
  if(state.primary==="deep"){state.primary="work";state.deepApp=null;state.deepRec=null}
  persist();applyView();renderAll();
  pushShellState();
}
function closeWindow(id){delete state.ui.open[id];delete state.ui.min[id];delete state.ui.z[id];persist();applyView();renderAll()}
function setMin(id,on){if(on)state.ui.min[id]=true;else delete state.ui.min[id];persist();applyView();renderAll()}
function setMax(id,on){if(on)state.ui.max[id]=true;else delete state.ui.max[id];persist();applyView();renderAll()}
function toggleMax(id){setMax(id,!state.ui.max[id])}
function focusWindow(id){state.ui.open[id]=true;delete state.ui.min[id];state.ui.z[id]=++state.ui.zTop;persist();applyView();renderAll()}
function returnToPrimary(){
  /* Collapse multi-window mode back to the focused primary layout. */
  state.ui.open={};state.ui.min={};state.ui.z={};
  state.multiMode=false;
  persist();applyView();renderAll();
}

/* ---- responsive rendering ----------------------------------------- */
function isNarrow(){return window.innerWidth<=NARROW}
function ensureStudio(id){if(id==="studio"){var f=q("[data-studio-frame]");if(f&&!f.getAttribute("src")&&f.dataset.src)f.src=f.dataset.src}}
function applyView(){
  var narrow=isNarrow();
  document.body.classList.toggle("is-mobile",narrow);
  /* Primary surfaces: exactly one visible. */
  qa("[data-surface]").forEach(function(el){
    el.hidden=el.dataset.surface!==state.primary;
  });
  var deepTitle=q("[data-deep-title]");
  if(deepTitle){var a=appById(state.deepApp);deepTitle.textContent=a?a.title:""}
  var deepBind=q("[data-deep-binding]");
  if(deepBind){var x=currentItem();deepBind.textContent=x?(x.id+" · "+(state.deepRec?"record "+state.deepRec:"in context")):""}
  /* Windows: opt-in only (desktop). Narrow never shows window chrome. */
  if(narrow){
    qa("[data-window]").forEach(function(el){
      el.hidden=true;el.style.left=el.style.top=el.style.width=el.style.height="";
      el.classList.remove("focused","minimized","maximized");
    });
  }else{
    applyWindowGeometry();
    qa("[data-window]").forEach(function(el){
      var id=appIdForWindow(el.dataset.window),open=!!state.ui.open[id];
      el.hidden=!open;
      el.classList.toggle("minimized",open&&!!state.ui.min[id]);
      el.classList.toggle("maximized",open&&!state.ui.min[id]&&!!state.ui.max[id]);
      el.classList.toggle("focused",open&&!state.ui.min[id]&&id===activeWindowId());
      if(open&&state.ui.z[id])el.style.zIndex=String(state.ui.z[id]);
      if(open)ensureStudio(id);
    });
  }
  /* Multi-window mode bar. */
  var mm=q("[data-multi-mode]");
  if(mm)mm.hidden=!anyOpenWindows()||narrow;
  /* Chrome nav active state. */
  qa(".nav-item[data-nav-home]").forEach(function(b){b.classList.toggle("active",state.primary==="home")});
  qa(".nav-item[data-nav-work]").forEach(function(b){b.classList.toggle("active",state.primary==="work"||state.primary==="deep")});
  /* Mobile nav. */
  renderMobileNav();
  /* Quiet workstream-binding indicator per window (S2). */
  qa("[data-binding-indicator]").forEach(function(el){
    var id=appIdForWindow((el.closest("[data-window]")||{}).dataset?((el.closest("[data-window]")||{}).dataset.window||""):"");
    el.textContent=id?bindingLabel(id):"";
  });
}
/* Deterministic non-overlapping window geometry for the opt-in window mode:
   a simple 2-column grid over the canvas. */
function tileRects(ids){
  var rects={},n=(ids||[]).length;
  if(!n)return rects;
  var cols=Math.min(2,n),rows=Math.ceil(n/cols),g=0.012;
  var cw=(1-g*(cols+1))/cols,ch=(1-g*(rows+1))/rows;
  ids.forEach(function(id,i){
    var r=Math.floor(i/cols),c=i%cols;
    rects[id]={x:g+c*(cw+g),y:g+r*(ch+g),w:cw,h:ch};
  });
  return rects;
}
function applyWindowGeometry(){
  var ids=Object.keys(state.ui.open).filter(function(id){return !!state.ui.open[id]&&!state.ui.min[id]});
  if(!ids.length){
    qa("[data-window]").forEach(function(el){el.style.left=el.style.top=el.style.width=el.style.height=""});
    return;
  }
  var tiles=tileRects(ids);
  ids.forEach(function(id){
    var el=q('[data-window="'+windowOf(id)+'"]');if(!el)return;
    var g=state.ui.geom[id]||tiles[id];
    if(!g)return;
    el.style.left=(g.x*100).toFixed(3)+"%";el.style.top=(g.y*100).toFixed(3)+"%";
    el.style.width=(g.w*100).toFixed(3)+"%";el.style.height=(g.h*100).toFixed(3)+"%";
  });
}
function clampFrac(v,max){return v<0?0:(v>max?max:v)}
function geomFor(id){
  var g=state.ui.geom[id];
  if(g&&typeof g.x==="number")return g;
  return {x:0.05,y:0.05,w:0.9,h:0.8};
}
function beginWindowDrag(el,ev,mode){
  /* Direct window interaction: move/resize always works on desktop, without
     requiring an arrange mode. */
  if(isNarrow())return;
  if(ev.target.closest("button,a,input"))return;
  var canvas=q("[data-canvas]"),cr=canvas.getBoundingClientRect();
  var id=appIdForWindow(el.dataset.window),start=geomFor(id),sx=ev.clientX,sy=ev.clientY;
  ev.preventDefault();
  function move(e){
    var dx=cr.width?(e.clientX-sx)/cr.width:0,dy=cr.height?(e.clientY-sy)/cr.height:0,g;
    if(mode==="move")g={x:clampFrac(start.x+dx,1-start.w),y:clampFrac(start.y+dy,1-start.h),w:start.w,h:start.h};
    else g={x:start.x,y:start.y,w:clampFrac(start.w+dx,1-start.x)||0.16,h:clampFrac(start.h+dy,1-start.y)||0.16};
    if(g.w<0.16)g.w=0.16;if(g.h<0.16)g.h=0.16;
    state.ui.geom[id]=g;applyWindowGeometry();
  }
  function up(){document.removeEventListener("mousemove",move);document.removeEventListener("mouseup",up);persist()}
  document.addEventListener("mousemove",move);document.addEventListener("mouseup",up);
}
function initCompose(){
  qa("[data-window]").forEach(function(el){
    var bar=q(".window-bar",el);
    if(bar)bar.addEventListener("mousedown",function(ev){beginWindowDrag(el,ev,"move")});
    var handle=el.querySelector("[data-window-resize]");
    if(handle)handle.addEventListener("mousedown",function(ev){beginWindowDrag(el,ev,"resize")});
  });
}

/* ---- mobile chrome ------------------------------------------------ */
function renderMobileNav(){
  var mnav=q("[data-mobile-nav]");
  if(!mnav)return;
  mnav.innerHTML="";
  [["home","Home"],["work","Work"],["activity","Activity"]].forEach(function(pair){
    var b=document.createElement("button");
    b.type="button";b.dataset.mobileNav=pair[0];b.textContent=pair[1];
    b.setAttribute("aria-label",pair[1]);
    var on=pair[0]==="home"?state.primary==="home":(pair[0]==="work"?(state.primary==="work"||state.primary==="deep"):state.activity.open);
    b.classList.toggle("active",on);
    b.addEventListener("click",function(){
      if(pair[0]==="home")openHome();
      else if(pair[0]==="work")openWork();
      else toggleActivity();
    });
    mnav.appendChild(b);
  });
}

/* ---- Search / command ------------------------------------------------ */
function openSearch(prefill){
  var panel=q("[data-search-panel]");
  if(panel)panel.hidden=false;
  var input=q("[data-search-input]");
  if(input){input.value=prefill||"";input.focus()}
  renderSearch(prefill||"");
}
function closeSearch(){var p=q("[data-search-panel]");if(p)p.hidden=true}
function renderSearch(term){
  var results=q("[data-search-results]");
  if(!results)return;
  var t=(term||"").trim().toLowerCase();
  var html='';
  var apps=state.registry.filter(function(a){return a.kind!=="surface"&&a.kind!=="primary"});
  var appHits=apps.filter(function(a){return !t||a.title.toLowerCase().indexOf(t)>=0||a.id.indexOf(t)>=0});
  appHits.forEach(function(a){
    html+='<button type="button" data-search-app="'+esc(a.id)+'"><span class="sr-label">'+esc(a.title)+'</span><span class="sr-meta">open</span></button>';
  });
  var wsHits=items().filter(function(w){return !t||w.id.toLowerCase().indexOf(t)>=0||w.title.toLowerCase().indexOf(t)>=0});
  wsHits.forEach(function(w){
    html+='<button type="button" data-search-ws="'+esc(w.id)+'"><span class="sr-label">'+esc(w.id)+' — '+esc(w.title)+'</span><span class="sr-meta">switch Workstream</span></button>';
  });
  [["go-home","Home"],["go-work","Work"],["go-activity","Activity Center"]].forEach(function(a){
    if(t&&a[1].toLowerCase().indexOf(t)<0)return;
    html+='<button type="button" data-search-action="'+esc(a[0])+'"><span class="sr-label">'+esc(a[1])+'</span><span class="sr-meta">go</span></button>';
  });
  if(!html)html='<div class="empty-state">No matches.</div>';
  results.innerHTML=html;
  qa("[data-search-app]",results).forEach(function(b){b.onclick=function(){openDeep(b.dataset.searchApp);closeSearch()}});
  qa("[data-search-ws]",results).forEach(function(b){b.onclick=function(){selectWorkstream(b.dataset.searchWs);openWork();closeSearch()}});
  qa("[data-search-action]",results).forEach(function(b){b.onclick=function(){
    var a=b.dataset.searchAction;
    if(a==="go-home")openHome();
    else if(a==="go-work")openWork();
    else if(a==="go-activity")toggleActivity();
    closeSearch();
  }});
}

/* ---- data + authority boundary (unchanged) -------------------- */
async function load(){
  var response=await fetch("api/workstreams",{cache:"no-store"});
  if(response.ok)return response.json();
  if(response.status!==404){var failed=await response.json().catch(function(){return{}});throw new Error(failed.error&&failed.error.message||"Authoritative Workstream data is unavailable")}
  var fixture=await fetch("fixtures/workstreams.json",{cache:"no-store"});if(!fixture.ok)throw new Error("Demo Workstream data is unavailable");return fixture.json();
}
async function loadBoundary(){try{var cap=await fetch("api/capabilities",{cache:"no-store"});if(cap.ok)state.capabilities=(await cap.json()).actions||[];var tok=await fetch("api/token",{cache:"no-store"});if(tok.ok)state.token=(await tok.json()).token}catch(_e){state.capabilities=[];state.token=null}}
function setMode(){var banner=q("[data-mode-banner]"),demo=state.model.synthetic;banner.innerHTML=demo?"<strong>Interactive preview</strong><span>Synthetic data · no external mutation</span>":"<strong>Local mode</strong><span>Live projection of "+esc(state.model.repo)+(state.model.status!=="fresh"?" · stale data":"")+"</span>"}

/* ---- Activity Center projection contract (ADR-044; S5.5c) ------------ */
var AttentionItemProjection={
  id:"string",sourceCapability:"string",sourceRecordRef:"string",
  sourceVersion:"string",workstreamId:"string|null",occurredAt:"string",
  severity:"string",requiresAttention:"boolean",title:"string",
  summary:"string",targetCommand:"string",dedupeKey:"string|null",
  expiresAt:"string|null"
};
function isValidAttentionItem(item){
  if(!item||typeof item!=="object")return false;
  var fields=Object.keys(AttentionItemProjection);
  for(var i=0;i<fields.length;i++){
    var k=fields[i],t=AttentionItemProjection[k],v=item[k];
    if(t==="string|null"){if(v!=null&&typeof v!=="string")return false}
    else if(typeof v!==t)return false;
  }
  return typeof item.targetCommand==="string"&&item.targetCommand.length>0;
}
function attentionItems(){
  var list=(state.model&&state.model.workstreams)||[];
  var items=[];
  list.forEach(function(x){
    if(x.attention){
      items.push({
        id:"att-"+x.id+"-decision",
        sourceCapability:"read:decision-pending",
        sourceRecordRef:String(x.number||x.id),
        sourceVersion:"v1",workstreamId:x.id,
        occurredAt:new Date().toISOString(),
        severity:x.attention==="decision"?"high":"medium",
        requiresAttention:true,title:x.title,
        summary:(x.decision&&x.decision.summary)||("Workstream "+x.id+" requires attention ("+x.attention+")."),
        targetCommand:"focus-record",dedupeKey:"ws:"+x.id+":"+x.attention,expiresAt:null
      });
    }
    if(x.workflow==="done"){
      items.push({
        id:"att-"+x.id+"-done",
        sourceCapability:"read:workstream-summary",
        sourceRecordRef:String(x.number||x.id),
        sourceVersion:"v1",workstreamId:x.id,
        occurredAt:new Date().toISOString(),
        severity:"low",requiresAttention:false,title:x.title,
        summary:"Important completed work: "+(x.outcome||"accepted"),
        targetCommand:"focus-record",dedupeKey:"ws:"+x.id+":done",expiresAt:null
      });
    }
  });
  return items.filter(isValidAttentionItem);
}
function activityVisibleItems(){
  var items=attentionItems();
  var f=state.activity.filters||{types:{},workstreamId:null};
  var seen={};
  return items.filter(function(it){
    if(it.dedupeKey){if(seen[it.dedupeKey])return false;seen[it.dedupeKey]=true}
    if(it.requiresAttention===false&&f.types&&f.types["done"]===false)return false;
    if(f.workstreamId&&it.workstreamId!==f.workstreamId)return false;
    if(state.activity.dismissed&&state.activity.dismissed[it.id])return false;
    return true;
  });
}
function activityGroupKey(it,groupBy){
  if(groupBy==="type")return it.severity;
  if(groupBy==="workstream")return it.workstreamId||"all";
  var d=it.occurredAt?String(it.occurredAt).slice(0,10):"unknown";
  return d;
}
function activityCount(){
  return attentionItems().filter(function(it){return it.requiresAttention&&!state.activity.read[it.id]}).length;
}
function navigateAttention(it){
  /* Validated navigation to the owning record in context (never a mutation). */
  var appId=it.sourceCapability==="read:decision-pending"?"decisions":"evidence";
  if(it.workstreamId)selectWorkstream(it.workstreamId);
  openDeep(appId,it.sourceRecordRef);
  var p=q("[data-activity-panel]");if(p)p.hidden=true;
  state.activity.open=false;persist();applyView();
}
function renderActivity(){
  var panel=q("[data-activity-panel]"),badge=q("[data-activity-count]");
  if(badge)badge.textContent=String(activityCount());
  if(!panel)return;
  var items=activityVisibleItems(),read=state.activity.read||{},f=state.activity.filters||{};
  var html='<div class="activity-head"><h3>Activity</h3><button type="button" data-activity-close aria-label="Close Activity Center">×</button></div>';
  html+='<div class="activity-filters">'+
    '<button type="button" data-activity-group="time"'+(f.groupBy==="time"?' class="active"':'')+'>Time</button>'+
    '<button type="button" data-activity-group="type"'+(f.groupBy==="type"?' class="active"':'')+'>Type</button>'+
    '<button type="button" data-activity-group="workstream"'+(f.groupBy==="workstream"?' class="active"':'')+'>Workstream</button>'+
  '</div>';
  if(!items.length)html+='<div class="empty-state">Nothing needs your attention.</div>';
  else{
    var groups={};
    items.forEach(function(it){
      var key=activityGroupKey(it,f.groupBy);
      (groups[key]=groups[key]||[]).push(it);
    });
    Object.keys(groups).forEach(function(g){
      html+='<div class="activity-group"><h4>'+esc(g)+'</h4>';
      groups[g].forEach(function(it){
        html+='<article class="activity-item'+(read[it.id]?' read':'')+'" data-activity-id="'+esc(it.id)+'">'+
          '<span class="state">'+esc(it.severity)+'</span>'+
          '<strong>'+esc(it.title)+'</strong>'+
          '<p>'+esc(it.summary)+'</p>'+
          '<div class="activity-actions">'+
            '<button type="button" data-activity-open="'+esc(it.id)+'">Open →</button>'+
            '<button type="button" data-activity-read="'+esc(it.id)+'">'+(read[it.id]?'Mark unread':'Mark read')+'</button>'+
            '<button type="button" data-activity-dismiss="'+esc(it.id)+'">Dismiss</button>'+
          '</div></article>';
      });
      html+='</div>';
    });
  }
  html+='<small class="activity-note">Presentation state is local. Workflow status is authoritative.</small>';
  panel.innerHTML=html;
  qa("[data-activity-close]",panel).forEach(function(b){b.onclick=toggleActivity});
  qa("[data-activity-group]",panel).forEach(function(b){b.onclick=function(){state.activity.filters.groupBy=b.dataset.activityGroup;persist();renderActivity()}});
  qa("[data-activity-read]",panel).forEach(function(b){b.onclick=function(){
    var id=b.dataset.activityRead;if(state.activity.read[id])delete state.activity.read[id];else state.activity.read[id]=Date.now();
    persist();renderActivity();
  }});
  qa("[data-activity-dismiss]",panel).forEach(function(b){b.onclick=function(){state.activity.dismissed[b.dataset.activityDismiss]=Date.now();persist();renderActivity()}});
  qa("[data-activity-open]",panel).forEach(function(b){b.onclick=function(){
    var it=attentionItems().find(function(x){return x.id===b.dataset.activityOpen});
    if(!it)return;
    navigateAttention(it);
  }});
}
function toggleActivity(){
  state.activity.open=!state.activity.open;
  var panel=q("[data-activity-panel]");
  if(panel)panel.hidden=!state.activity.open;
  if(state.activity.open)renderActivity();
  persist();
}

/* ---- Home app (system surface, S5 + S6a) ----------------------------- */
function dispatchCommand(command,payload){
  var handlers=(typeof window!=="undefined")?window.ShellCommandHandlers:null;
  if(typeof ShellCommands!=="undefined"&&ShellCommands.dispatch&&handlers){
    ShellCommands.dispatch(command,payload,handlers);return;
  }
  if(handlers&&typeof handlers[command]==="function")handlers[command](payload||{});
}
function renderHome(winEl,ctx){
  var s=(ctx&&ctx.state)||state;
  var x=currentItem();
  var list=items().filter(function(w){return w.id!=="all"});
  if(!s.hadSavedSession){
    /* First-time state: truthful unbound context, smallest next step. */
    winEl.innerHTML='<div class="firsttime-inner"><div class="firsttime-card">'+
      '<span class="eyebrow">Home</span>'+
      '<h2>Start a Workstream</h2>'+
      '<p>A Workstream is the durable unit of work: the outcome, mandate, decisions, evidence, and continuity you own — regardless of which engine, provider, or model executes a run.</p>'+
      '<button type="button" class="primary-action" data-ft-demo>Explore the demo Workstream</button>'+
      '<button type="button" class="chrome-button" data-ft-create>Create a Workstream</button>'+
      '</div></div>';
    var demo=q("[data-ft-demo]",winEl);
    if(demo)demo.addEventListener("click",function(){
      if(items().length)selectWorkstream(items()[0].id);
      openWork();
    });
    var create=q("[data-ft-create]",winEl);
    if(create)create.addEventListener("click",function(){OSRenderer.emit("command",{command:"create-workstream"})});
    return;
  }
  if(!x){
    /* Returning entry with no selection: explicit unbound state. */
    var html='<div class="home-inner">'+
      '<span class="eyebrow">Home</span>'+
      '<h1 class="home-heading">Select or start a Workstream</h1>'+
      '<p class="home-sub">No Workstream is selected. Choose one to resume, or start a new one.</p>'+
      '<div class="home-section"><h3>Recent Workstreams</h3><div class="recent-list">';
    list.slice(0,5).forEach(function(w){
      html+='<button type="button" class="recent-row" data-recent-ws="'+esc(w.id)+'"><strong>'+esc(w.id)+'</strong><span>'+esc(w.title)+'</span><small>'+(w.workflow||"")+'</small></button>';
    });
    html+='</div></div>';
    html+='<div class="home-section"><h3>Start</h3><div class="home-actions">'+
      '<button type="button" class="chrome-button" data-home-create>New Workstream</button>'+
      '<button type="button" class="chrome-button" data-home-allapps>All apps</button>'+
      '</div></div></div>';
    winEl.innerHTML=html;
    qa("[data-recent-ws]",winEl).forEach(function(b){
      b.addEventListener("click",function(){selectWorkstream(b.dataset.recentWs);openWork()});
    });
    var create2=q("[data-home-create]",winEl);
    if(create2)create2.addEventListener("click",function(){OSRenderer.emit("command",{command:"create-workstream"})});
    var allapps2=q("[data-home-allapps]",winEl);
    if(allapps2)allapps2.addEventListener("click",function(){openSearch("")});
    return;
  }
  /* Returning entry with a selection: resume-first (S6b). */
  var resume=x;
  var attention=attentionItems().filter(function(it){return it.requiresAttention});
  var recent=recentWorkstreams().filter(function(w){return w.id!==x.id}).slice(0,3);
  var html2='<div class="home-inner">'+
    '<span class="eyebrow">Home</span>'+
    '<h1 class="home-heading">Resume your work</h1>'+
    '<p class="home-sub">Your Workstreams keep their outcome, mandate, decisions, and evidence. Pick up where you left off.</p>';
  if(resume){
    html2+='<div class="home-section"><h3>Resume</h3>'+
      '<div class="resume-card">'+
        '<div class="rc-body">'+
          '<p class="rc-title">'+esc(resume.id)+' — '+esc(resume.title)+'</p>'+
          '<p class="rc-outcome">'+esc(resume.outcome)+'</p>'+
          '<p class="rc-meta">'+esc(resume.workflow||"no workflow label")+(resume.phase?(" · "+esc(resume.phase)):"")+(resume.nextAction?(" · Next: "+esc(resume.nextAction)):"")+'</p>'+
        '</div>'+
        '<button type="button" class="primary-action" data-resume-work>Resume Work →</button>'+
      '</div></div>';
  }
  if(attention.length){
    html2+='<div class="home-section"><h3>Needs attention</h3><div class="attention-preview">';
    attention.slice(0,3).forEach(function(it){
      var sev=it.severity==="high"?"warn":(it.severity==="low"?"good":"bad");
      html2+='<button type="button" class="attention-row" data-attention-open="'+esc(it.id)+'">'+
        '<span class="a-state '+sev+'" aria-hidden="true"></span>'+
        '<span class="a-main"><span class="a-title">'+esc(it.title)+'</span><span class="a-sum">'+esc(it.summary)+'</span></span>'+
        '<span class="link-button">Open →</span></button>';
    });
    html2+='<div class="attention-more"><button type="button" class="link-button" data-home-activity>All attention in Activity →</button></div>';
    html2+='</div></div>';
  }
  html2+='<div class="home-section"><h3>Recent Workstreams</h3><div class="recent-list">';
  recent.forEach(function(w){
    html2+='<button type="button" class="recent-row" data-recent-ws="'+esc(w.id)+'"><strong>'+esc(w.id)+'</strong><span>'+esc(w.title)+'</span><small>'+(w.workflow||"")+'</small></button>';
  });
  html2+='</div></div>';
  html2+='<div class="home-section"><h3>Start</h3><div class="home-actions">'+
    '<button type="button" class="chrome-button" data-home-create>New Workstream</button>'+
    '<button type="button" class="chrome-button" data-home-allapps>All apps</button>'+
    '</div></div></div>';
  winEl.innerHTML=html2;
  var resumeBtn=q("[data-resume-work]",winEl);
  if(resumeBtn)resumeBtn.addEventListener("click",function(){openWork()});
  qa("[data-attention-open]",winEl).forEach(function(b){
    b.addEventListener("click",function(){
      var it=attentionItems().find(function(y){return y.id===b.dataset.attentionOpen});
      if(it)navigateAttention(it);
    });
  });
  var homeActivity=q("[data-home-activity]",winEl);
  if(homeActivity)homeActivity.addEventListener("click",function(){toggleActivity()});
  qa("[data-recent-ws]",winEl).forEach(function(b){
    b.addEventListener("click",function(){selectWorkstream(b.dataset.recentWs);openWork()});
  });
  var create3=q("[data-home-create]",winEl);
  if(create3)create3.addEventListener("click",function(){OSRenderer.emit("command",{command:"create-workstream"})});
  var allapps3=q("[data-home-allapps]",winEl);
  if(allapps3)allapps3.addEventListener("click",function(){openSearch("")});
}
if(typeof OSRenderer!=="undefined"){OSRenderer.register("home",renderHome)}

/* ---- Work app (S5.5b/ADR-044 + S6a surface routing) ------------------ */
function renderWork(winEl,ctx){
  var s=(ctx&&ctx.state)||state,x=(ctx&&ctx.workstream)||null;
  if(!x){
    winEl.innerHTML='<div class="home-inner">'+
      '<span class="eyebrow">Work</span>'+
      '<h1 class="home-heading">No Workstream selected</h1>'+
      '<p class="home-sub">Select a Workstream from the switcher above, or start one, to project its work here.</p>'+
      '<div class="home-section"><h3>Recent Workstreams</h3><div class="recent-list">';
    items().slice(0,5).forEach(function(w){
      winEl.innerHTML+='<button type="button" class="recent-row" data-recent-ws="'+esc(w.id)+'"><strong>'+esc(w.id)+'</strong><span>'+esc(w.title)+'</span><small>'+(w.workflow||"")+'</small></button>';
    });
    winEl.innerHTML+='</div></div></div>';
    qa("[data-recent-ws]",winEl).forEach(function(b){
      b.addEventListener("click",function(){selectWorkstream(b.dataset.recentWs);openWork()});
    });
    return;
  }
  var decision=x.decision||null,evidence=x.evidence||[];
  var phase=x.phase||x.workflow||"in-progress";
  var milestones=(x.milestones&&x.milestones.length)?x.milestones:[];
  var blockers=(x.blockers&&x.blockers.length)?x.blockers:[];
  var runs=(x.runs&&x.runs.length)?x.runs:[];
  var doneCount=milestones.filter(function(m){return m.done}).length;
  var pct=milestones.length?Math.round(doneCount/milestones.length*100):0;
  var phaseClass=phase.toLowerCase().indexOf("block")>=0?"blocked":(phase.toLowerCase().indexOf("accept")>=0||phase.toLowerCase().indexOf("done")>=0?"done":"");
  var html='<div class="work-inner">'+
    '<div class="work-head">'+
      '<div>'+
        '<span class="eyebrow">Work · '+esc(x.id)+'</span>'+
        '<h1 class="wh-title">'+esc(x.title)+'</h1>'+
        '<p class="wh-outcome">'+esc(x.outcome)+'</p>'+
      '</div>'+
      '<div class="wh-status"><span class="work-phase '+phaseClass+'">'+esc(phase)+'</span><small style="color:var(--dim);font-size:11px">'+esc(x.workflow||"")+'</small></div>'+
    '</div>'+
    '<p class="work-mandate"><b>Mandate:</b> '+esc(x.mandate||x.acceptance_criteria||"No mandate recorded.")+'</p>'+
    '<div class="work-layout">'+
      '<div class="work-col">'+
        '<section class="work-card next-card"><h3>Next</h3>'+
          '<p class="wc-main">'+(x.nextAction?esc(x.nextAction):(decision?esc(decision.summary):"No next action pending."))+'</p>'+
          (decision?'<p class="wc-sub">'+esc(decision.summary)+'</p>':'')+
          '<div class="work-actions">'+
            '<button type="button" class="primary-action" data-deep-open="decisions">Open Decisions →</button>'+
            '<button type="button" class="chrome-button" data-deep-open="evidence">Open Evidence</button>'+
            '<button type="button" class="chrome-button" data-deep-open="execution">Execution Inspector</button>'+
          '</div>'+
          '<div class="work-actions">'+
            '<button type="button" class="chrome-button" data-win-open="decisions">Open in new window</button>'+
          '</div>'+
        '</section>'+
        (blockers.length?'<section class="work-card"><h3>Blocked</h3>'+blockers.map(function(b){
          return '<p class="wc-main" style="color:var(--bad)">'+esc(b.reason)+'</p><p class="wc-sub"><b>Recovery:</b> '+esc(b.recovery)+'</p>';
        }).join("")+'</section>':"")+
        '<section class="work-card"><h3>Evidence</h3>'+
          (evidence.length?evidence.map(function(ev){return '<p class="wc-row" style="cursor:default"><strong>'+esc(ev.title)+'</strong><small>'+esc(ev.status)+'</small></p><p class="wc-sub">'+esc(ev.detail)+'</p>'}).join("")+'<button type="button" class="link-button" data-deep-open="evidence">Open Evidence with context →</button>':'<p class="wc-sub">No attributable evidence yet.</p>')+
        '</section>'+
        (milestones.length?'<section class="work-card"><h3>Milestones</h3>'+
          '<p class="wc-meta">'+esc(String(doneCount))+' of '+esc(String(milestones.length))+' complete ('+esc(String(pct))+'%)</p>'+
          '<div class="progress-track" aria-hidden="true"><div class="progress-fill" style="width:'+esc(String(pct))+'%"></div></div>'+
          milestones.map(function(m){return '<p class="wc-row" style="cursor:default"><strong>'+esc(m.title)+'</strong>'+(m.done?'<small class="done-mark">✓ done</small>':'<small>pending</small>')+'</p>'}).join("")+
        '</section>':"")+
      '</div>'+
      '<div class="work-col">'+
        '<section class="work-card"><h3>Decisions</h3>'+
          (decision?'<p class="wc-main">'+esc(decision.summary)+'</p><button type="button" class="link-button" data-deep-open="decisions">Open Decisions with context →</button>':'<p class="wc-sub">No authoritative decision is pending.</p>')+
        '</section>'+
        '<section class="work-card"><h3>Capabilities</h3>'+
          '<button type="button" class="wc-row" data-deep-open="policies"><strong>Policies</strong><small>Open →</small></button>'+
          '<button type="button" class="wc-row" data-deep-open="atlas"><strong>Atlas</strong><small>Open →</small></button>'+
          '<button type="button" class="wc-row" data-deep-open="connections"><strong>Connections</strong><small>Open →</small></button>'+
        '</section>'+
        (runs.length?'<section class="work-card"><h3>Execution detail</h3>'+
          '<p class="exec-sub">Recent runs — replaceable execution, subordinate to this Workstream</p>'+
          runs.map(function(r){return '<div class="exec-row"><span class="exec-id">'+esc(r.id)+'</span><span class="exec-status '+esc(r.status)+'" aria-hidden="true"></span><span>'+esc(r.engine)+' · '+esc(r.model)+'</span><small style="margin-left:auto;color:var(--dim)">'+esc(r.status)+' · $'+esc(String(r.cost_usd))+'</small></div>'}).join("")+
          '<button type="button" class="link-button" data-deep-open="execution">Open Execution Inspector →</button>'+
        '</section>':"")+
      '</div>'+
    '</div>'+
    '<small class="work-note">Summaries are read-only projections. Each opens its responsible app with the exact Workstream context; Work never duplicates a full app workflow.</small>'+
  '</div>';
  winEl.innerHTML=html;
  qa("[data-deep-open]",winEl).forEach(function(b){
    b.addEventListener("click",function(){
      var appId=b.dataset.deepOpen;
      if(appId==="decisions"&&decision)openDeep(appId,"#"+String(x.number||x.id));
      else openDeep(appId);
    });
  });
  qa("[data-win-open]",winEl).forEach(function(b){
    b.addEventListener("click",function(){openWindow(b.dataset.winOpen)});
  });
}
if(typeof OSRenderer!=="undefined"){OSRenderer.register("work",renderWork)}

/* ---- Deep capabilities (in-context, subordinate) --------------------- */
function renderPolicies(body,ctx){
  var x=(ctx&&ctx.workstream)||null;
  body.innerHTML='<span class="eyebrow">Policies · '+esc(x?x.id:"")+'</span><h3>Applicable policies</h3>'+
    '<div class="projection-list">'+
    '<article><span class="eyebrow">mandate</span><strong>Scope and budget boundary</strong><p>Scope and budget fixed by operator approval; no scope expansion without a decision.</p></article>'+
    '<article><span class="eyebrow">provider</span><strong>Provider policy fails closed</strong><p>Evidence without an attributable source is rejected by the policy gate.</p></article>'+
    '<article><span class="eyebrow">evidence</span><strong>Attribution gate</strong><p>Every accepted control must cite a source record that survives across runs.</p></article>'+
    '</div>';
}
if(typeof OSRenderer!=="undefined"){OSRenderer.register("policies",renderPolicies)}
function renderExecution(body,ctx){
  var x=(ctx&&ctx.workstream)||null;
  var runs=(x&&x.runs&&x.runs.length)?x.runs:[];
  body.innerHTML='<span class="eyebrow">Execution Inspector · '+esc(x?x.id:"")+'</span><h3>Runs and execution detail</h3>'+
    '<p style="color:var(--muted);font-size:12px;max-width:640px">Execution is replaceable: a new run may use a different engine, provider, or model without redefining the Workstream or losing accepted evidence.</p>'+
    '<div class="projection-list">'+
    (runs.length?runs.map(function(r){
      return '<article><span class="eyebrow">'+esc(r.status)+' · '+esc(r.engine)+'</span><strong>'+esc(r.id)+'</strong><p>Provider: '+esc(r.provider)+' · Model: '+esc(r.model)+' · Evidence: '+esc(String(r.evidence))+' · Cost: $'+esc(String(r.cost_usd))+'</p></article>';
    }).join(""):'<article><p>No runs recorded for this Workstream.</p></article>')+
    '</div>'+
    '<p class="exec-sub">Sessions, terminals, and logs remain available under each run on demand.</p>';
}
if(typeof OSRenderer!=="undefined"){OSRenderer.register("execution",renderExecution)}
function renderAtlas(body){
  body.innerHTML='<span class="eyebrow">Atlas</span><h3>Derived roadmap map</h3><div class="projection-list"><article><p>Atlas renders roadmap relationships from GitHub Issues. The map projection is read-only and derived; it is never a second backlog.</p></article></div>';
}
if(typeof OSRenderer!=="undefined"){OSRenderer.register("atlas",renderAtlas)}
function renderConnections(body){
  body.innerHTML='<span class="eyebrow">Connections</span><h3>External integrations</h3><div class="projection-list"><article><p>Connections manages webhooks, adapters, providers, runtimes, and MCP consumers through authorized ports. This surface projects the registered capabilities.</p></article></div>';
}
if(typeof OSRenderer!=="undefined"){OSRenderer.register("connections",renderConnections)}
function renderDeep(){
  var body=q("[data-deep-body]");
  if(!body)return;
  var appId=state.deepApp;
  var x=currentItem();
  var ctx={workstream:x,state:state,deep:true};
  var handled=OSRenderer.render(appId,body,ctx);
  if(!handled){
    if(appId==="studio"){
      var frame=q("[data-studio-frame]");
      body.innerHTML='<span class="eyebrow">Studio</span><h3>Composition authoring</h3><p class="wc-sub">Studio is available as a window from search. In this surface it opens its embedded composition host.</p>';
      if(frame)frame.src=frame.dataset.src||"maker.html"+(x?"?workstream="+encodeURIComponent(x.id):"");
    }else{
      body.innerHTML=empty("This capability is registered but has no projection in this slice.");
    }
  }
}

/* ---- context propagation + full render ------------------------------- */
function propagateContext(){
  var x=currentItem();
  var chip=q("[data-active-context]");
  if(chip)chip.textContent=x?(x.id+" · "+x.title):"No Workstream selected";
  var ctx={workstream:x,state:state};
  renderDeep();
  var d=q("[data-decisions-body]");
  if(d&&!OSRenderer.render("decisions",d,ctx))d.innerHTML=x?'<span class="eyebrow">'+esc(x.id)+'</span><h3>'+esc(x.title)+'</h3><p>'+(x.decision?esc(x.decision.summary):"No authoritative decision is pending for this Workstream.")+'</p>':empty("Select a Workstream to project its decision.");
  var e=q("[data-evidence-body]");
  if(e&&!OSRenderer.render("evidence",e,ctx))e.innerHTML=x?'<span class="eyebrow">'+esc(x.id)+'</span><h3>Evidence</h3><div class="projection-list">'+(x.evidence.length?x.evidence.map(function(ev){return'<article><strong>'+esc(ev.title)+'</strong><p>'+esc(ev.detail)+'</p></article>'}).join(""):empty("No authoritative evidence is attached."))+'</div>':empty("Select a Workstream to project its evidence.");
  var p=q("[data-policies-body]");
  if(p)p.innerHTML=x?'':'';
  qa("[data-studio-frame]").forEach(function(frame){
    var src="maker.html"+(x?"?workstream="+encodeURIComponent(x.id):"");
    frame.dataset.src=src;if(frame.getAttribute("src"))frame.src=src;
  });
  OSRenderer.emit("context",ctx);
}
function renderAll(){
  var ctx={workstream:currentItem(),state:state};
  var workEl=q("[data-work-body]");
  if(workEl&&!OSRenderer.render("work",workEl,ctx))renderWork(workEl,ctx);
  var homeEl=q("[data-home-body]");
  if(homeEl&&!OSRenderer.render("home",homeEl,ctx))renderHome(homeEl,ctx);
  renderSwitcher();
  propagateContext();
}

/* ---- boot / wiring ------------------------------------------------ */
if(typeof document!=="undefined"&&typeof window!=="undefined"){
  /* S1a recursion guard: a Cortxt OS shell must never mount inside another
     Cortxt OS window. */
  var isRecursionMount=false;
  try{isRecursionMount=(typeof window.top!=="undefined")&&(window.self!==window.top)}catch(_e){isRecursionMount=true}
  if(isRecursionMount){
    var _banner=q("[data-mode-banner]");
    if(_banner)_banner.innerHTML="<strong>Open in Cortxt OS</strong><span>This surface cannot be embedded inside the OS.</span>";
    var _canvas=q("[data-canvas]");
    if(_canvas)_canvas.innerHTML=''+
      '<div style="max-width:520px;margin:4rem auto;text-align:center;">'+
        '<h2 style="margin:0 0 .5rem;">Open in Cortxt OS</h2>'+
        '<p style="color:var(--muted);line-height:1.5;margin:0 0 1rem;">A Cortxt OS window cannot be embedded inside itself. Use the launcher to open this app in the OS.</p>'+
      '</div>';
  } else if (typeof ShellIframeBridge !== "undefined" && ShellIframeBridge.listenFromIframe) {
    ShellIframeBridge.listenFromIframe(function(payload){
      var id=(payload&&payload.appId)||null;
      if(id)id=migrateWorkConsole(id);
      if(id&&state&&state.registry){
        if(id==="home")openHome();
        else if(id==="work")openWork();
        else openDeep(id);
      }
    });
  }
  /* S1b: typed shell command router. S6a: surfaces + validated deep links;
     open-app routes Home/Work to surfaces and other apps in context; the
     legacy `work-console` id resolves to `work` (ADR-044 alias). */
  if(typeof ShellCommands!=="undefined"){
    var commandHandlers={
      "open-app":function(p){
        if(!p||!p.appId)return;
        var id=migrateWorkConsole(p.appId);
        var a=appById(id);
        if(!a)return;
        if(id==="home"){openHome();return}
        if(id==="work"){openWork();return}
        openDeep(id);
      },
      "close-app":function(p){if(p&&p.appId)closeWindow(p.appId)},
      "focus-app":function(p){if(p&&p.appId)focusWindow(p.appId)},
      "switch-workstream":function(p){
        if(p&&p.workstreamId){
          var known=p.workstreamId==="all"||items().some(function(x){return x.id===p.workstreamId});
          if(known)selectWorkstream(p.workstreamId);
        }
      },
      "open-home":function(){openHome()},
      "open-external":function(p){if(p&&p.url)try{window.open(p.url,"_blank","noopener")}catch(_e){}},
      "focus-record":function(p){
        if(!p||!p.appId||!p.recordRef)return;
        var a=appById(migrateWorkConsole(p.appId));
        if(!a)return;
        if(p.workstreamId&&p.workstreamId!=="all"&&!items().some(function(x){return x.id===p.workstreamId}))return;
        /* The documented deep-link form is record=#<number>; accept both the
           prefixed and bare forms so known records never fail closed. */
        var ref=String(p.recordRef).replace(/^#/,"");
        if(!items().some(function(x){return String(x.number||x.id)===ref}))return;
        if(p.workstreamId)selectWorkstream(p.workstreamId);
        openDeep(a.id,p.recordRef);
      },
      "open-window":function(p){if(p&&p.appId)openWindow(migrateWorkConsole(p.appId))},
      "return-primary":function(){returnToPrimary()},
    };
    window.ShellCommandHandlers=commandHandlers;
    window.addEventListener("hashchange",function(){
      if(typeof ShellCommands!=="undefined"&&ShellCommands.applyDeepLink){
        ShellCommands.applyDeepLink(location.hash,commandHandlers);
      }
    });
  }
  /* Chrome wiring. */
  var navHome=q("[data-nav-home]");if(navHome)navHome.onclick=openHome;
  var navWork=q("[data-nav-work]");if(navWork)navWork.onclick=openWork;
  var wsToggle=q("[data-ws-toggle]"),wsPanel=q("[data-workstream-switcher]");
  if(wsToggle&&wsPanel){wsToggle.onclick=function(){var open=wsPanel.hidden;wsPanel.hidden=!open;this.setAttribute("aria-expanded",String(open));if(open)renderSwitcher()}}
  var searchToggle=q("[data-search-toggle]"),searchPanel=q("[data-search-panel]");
  if(searchToggle){searchToggle.onclick=function(){var open=searchPanel&&!searchPanel.hidden;if(searchPanel)searchPanel.hidden=open;this.setAttribute("aria-expanded",String(!open));if(!open)openSearch("")}}
  var searchClose=q("[data-search-close]");if(searchClose)searchClose.onclick=closeSearch;
  var searchInput=q("[data-search-input]");
  if(searchInput)searchInput.addEventListener("input",function(){renderSearch(searchInput.value)});
  document.addEventListener("keydown",function(ev){
    if(ev.key==="/"||((ev.ctrlKey||ev.metaKey)&&ev.key.toLowerCase()==="k")){
      ev.preventDefault();openSearch("");return;
    }
    if(ev.key==="Escape"){
      [q("[data-search-panel]"),q("[data-activity-panel]"),q("[data-workstream-switcher]")].forEach(function(p){if(p)p.hidden=true});
      if(q("[data-search-toggle]"))q("[data-search-toggle]").setAttribute("aria-expanded","false");
      if(q("[data-ws-toggle]"))q("[data-ws-toggle]").setAttribute("aria-expanded","false");
    }
  });
  var activityToggle=q("[data-activity-toggle]"),activityPanel=q("[data-activity-panel]");
  if(activityToggle)activityToggle.onclick=toggleActivity;
  if(activityPanel){
    document.addEventListener("pointerdown",function(ev){
      if(activityPanel.hidden)return;
      if(ev.target.closest("[data-activity-panel]")||ev.target.closest("[data-activity-toggle]"))return;
      state.activity.open=false;activityPanel.hidden=true;persist();
    });
  }
  var deepBack=q("[data-deep-back]");
  if(deepBack)deepBack.onclick=function(){openWork()};
  var deepWin=q("[data-deep-window]");
  if(deepWin)deepWin.onclick=function(){if(state.deepApp)openWindow(state.deepApp)};
  var returnPrimary=q("[data-return-primary]");
  if(returnPrimary)returnPrimary.onclick=returnToPrimary;
  qa("[data-window-focus]").forEach(function(x){x.onclick=function(){focusWindow(x.dataset.windowFocus)}});
  qa("[data-window-min]").forEach(function(x){x.onclick=function(){var id=x.dataset.windowMin;setMin(id,!state.ui.min[id])}});
  qa("[data-window-max]").forEach(function(x){x.onclick=function(){toggleMax(x.dataset.windowMax)}});
  qa("[data-close-window]").forEach(function(x){x.onclick=function(){closeWindow(x.dataset.closeWindow)}});
  qa("[data-window] .window-bar").forEach(function(bar){bar.addEventListener("dblclick",function(ev){if(ev.target.closest("button,a,input"))return;var win=bar.closest("[data-window]"),id=appIdForWindow(win.dataset.window);if(state.ui.min[id])setMin(id,false)})});
  initCompose();
  document.addEventListener("pointerdown",function(ev){
    if(isNarrow())return;
    var win=ev.target.closest("[data-window]");
    if(!win)return;
    if(ev.target.closest("button,a,input"))return;
    focusWindow(appIdForWindow(win.dataset.window));
  });
  var resizeTimer;window.addEventListener("resize",function(){clearTimeout(resizeTimer);resizeTimer=setTimeout(function(){applyView();renderAll()},120)});

  restore();
  loadTokens();
  loadRegistry().then(function(){
    renderAll();applyView();
    return Promise.all([load(),loadBoundary()]);
  }).then(function(values){
    state.model=values[0];setMode();
    renderAll();applyView();renderSwitcher();
    var _panel=q("[data-activity-panel]");
    if(_panel)_panel.hidden=!state.activity.open;
    renderActivity();
    var bootHash=(typeof location!=="undefined")?location.hash:"";
    var bootApplied=false;
    if(typeof ShellCommands!=="undefined"&&ShellCommands.applyDeepLink&&window.ShellCommandHandlers){
      bootApplied=ShellCommands.applyDeepLink(bootHash,window.ShellCommandHandlers);
    }
    if(!state.hadSavedSession&&!bootApplied)openHome();
  }).catch(function(error){
    q("[data-mode-banner]").innerHTML="<strong>Data unavailable</strong><span>"+esc(error.message)+"</span>";
    var workEl=q("[data-work-body]");
    if(workEl)workEl.innerHTML=empty("Cortxt OS could not establish authoritative state. The shell failed closed: no evidence or decision action is exposed.");
  });
}
if(typeof module==="object"&&module.exports)module.exports={tileRects:tileRects,migrateSavedState:migrateSavedState,migrateWorkConsole:migrateWorkConsole,LEGACY_APP_ALIASES:LEGACY_APP_ALIASES,isValidAttentionItem:isValidAttentionItem,AttentionItemProjection:AttentionItemProjection};
})();
