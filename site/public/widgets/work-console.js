(function(){"use strict";
/* Cortxt OS shell core.
   One authoritative app registry (apps.json) drives the app drawer, the mobile
   navigation bar and window resolution. Shell state is split into:
     state.ui        global UI state (open/minimised windows, z-order, arrange
                     mode, drawer, the single active mobile app)
     state.context   the selected Workstream, propagated to every mounted app
     state.apps      app-local view state (e.g. the Work Console sub-view)
     state.windows   WindowInstance model (S2): one running instance of an app,
                     optionally bound to a workstream (follow-active | locked |
                     global). The desktop (layout/restoration) is separate from
                     any app. state.ui is the rendering projection of this
                     model; windows are the durable domain model.
     state.dockFavorites / state.desktopLayout
                     foundations for the later dock/launcher separation (S4).
   state.ui + state.context + state.apps + state.windows persist to one
   localStorage key (schema v2) so a reload restores the layout, the selected
   Workstream, and window workstream bindings. The authority boundary
   (load/loadBoundary/confirmDecision) is unchanged and still fails closed. */
var SHELL_KEY="cortxt-os-shell",NARROW=720;
var state={
  model:null,token:null,capabilities:[],registry:[],
  ui:{open:{},min:{},max:{},z:{},geom:{},zTop:10,arranging:false,mobileApp:"work-console",drawer:false},
  context:{workstreamId:null,activeWorkstreamId:null},
  apps:{"work-console":{panel:"attention"}},
  windows:[],
  dockFavorites:[],
  desktopLayout:{},
  schemaVersion:2,
  hadSavedSession:false
};
var q=function(s,r){return(r||document).querySelector(s)},qa=function(s,r){return Array.from((r||document).querySelectorAll(s))};
var esc=function(v){return String(v==null?"":v).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})};
function empty(message){return '<div class="empty-state">'+esc(message)+'</div>'}

/* ---- canonical design tokens (ADR-043) -------------------------------- */
/* The OS shell owns no palette. It reuses the Widget Host token adapter
   (maker.js -> window.WidgetMaker.applyTokens, the same mirror of
   widget_contract/tokens.py that maker.html loads) to project the canonical
   tokens.json onto :root. os.css only ever references var(--token-*) with
   offline hex fallbacks; if both the fetch and the adapter are unavailable
   those fallbacks are all that render. */
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

/* ---- deterministic, non-overlapping window geometry ------------------
   The pinned console holds a fixed left column; every other open window
   tiles the right column top-to-bottom in a stable registry order. Values
   are fractions of the canvas box so the layout survives viewport changes.
   A window the operator drags or resizes in compose mode carries an
   explicit rect in state.ui.geom and is then exempt from tiling. */
var CONSOLE_W=0.58,GUTTER=0.014,MIN_W=0.18,MIN_H=0.16;
function tileRects(openIds){
  var rects={"work-console":{x:0,y:0,w:CONSOLE_W,h:1}},n=(openIds||[]).length;
  for(var i=0;i<n;i++){
    var h=(1-GUTTER*(n-1))/n;
    rects[openIds[i]]={x:CONSOLE_W+GUTTER,y:i*(h+GUTTER),w:1-CONSOLE_W-GUTTER,h:h};
  }
  return rects;
}
function secondaryOpenIds(){
  return state.registry
    .filter(function(a){return a.kind!=="pinned"&&a.kind!=="deferred"&&!!state.ui.open[a.id]})
    .map(function(a){return a.id});
}
function customGeom(id){var g=state.ui.geom[id];return(g&&typeof g.x==="number")?g:null}
function geomFor(id,openIds){
  return customGeom(id)||tileRects(openIds||secondaryOpenIds())[id]||
    {x:CONSOLE_W+GUTTER,y:0,w:1-CONSOLE_W-GUTTER,h:1};
}
function applyGeom(){
  if(isNarrow())return;
  var tiles=tileRects(secondaryOpenIds());
  qa("[data-window]").forEach(function(el){
    var id=appIdForWindow(el.dataset.window);
    if(el.hidden){el.style.left=el.style.top=el.style.width=el.style.height="";return}
    var g=customGeom(id)||tiles[id];if(!g)return;
    el.style.left=(g.x*100).toFixed(3)+"%";el.style.top=(g.y*100).toFixed(3)+"%";
    el.style.width=(g.w*100).toFixed(3)+"%";el.style.height=(g.h*100).toFixed(3)+"%";
  });
}
function clampFrac(v,max){return v<0?0:(v>max?max:v)}
function beginWindowDrag(el,ev,mode){
  /* Direct window interaction: move/resize always works on desktop, without
     requiring Arrange mode. Arrange is only an explicit layout action. */
  if(isNarrow())return;
  if(ev.target.closest("button,a,input"))return;
  var canvas=q("[data-canvas]"),cr=canvas.getBoundingClientRect();
  var id=appIdForWindow(el.dataset.window),start=geomFor(id),sx=ev.clientX,sy=ev.clientY;
  ev.preventDefault();
  function move(e){
    var dx=cr.width?(e.clientX-sx)/cr.width:0,dy=cr.height?(e.clientY-sy)/cr.height:0,g;
    if(mode==="move")g={x:clampFrac(start.x+dx,1-start.w),y:clampFrac(start.y+dy,1-start.h),w:start.w,h:start.h};
    else g={x:start.x,y:start.y,w:clampFrac(start.w+dx,1-start.x)||MIN_W,h:clampFrac(start.h+dy,1-start.y)||MIN_H};
    if(g.w<MIN_W)g.w=MIN_W;if(g.h<MIN_H)g.h=MIN_H;
    state.ui.geom[id]=g;applyGeom();
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

/* ---- persistence (schema v2) ------------------------------------------ */
/* One localStorage key. Schema v2 adds the WindowInstance model, dock
   favorites, and desktop layout; v1 blobs (ui/context/apps only) migrate on
   read so old sessions restore their windows with follow-active bindings. */
function persist(){
  syncWindowsFromUi();
  try{localStorage.setItem(SHELL_KEY,JSON.stringify({v:2,ui:state.ui,context:state.context,apps:state.apps,windows:state.windows,dockFavorites:state.dockFavorites,desktopLayout:state.desktopLayout}))}catch(_e){}
}
function restore(){
  var saved;try{saved=JSON.parse(localStorage.getItem(SHELL_KEY)||"null")}catch(_e){saved=null}
  state.hadSavedSession=!!(saved&&typeof saved==="object"&&(saved.ui||saved.windows));
  if(!saved||typeof saved!=="object")return;
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
  if(!state.apps["work-console"])state.apps["work-console"]={panel:"attention"};
  if(saved.v===2&&Array.isArray(saved.windows)){
    state.windows=saved.windows.slice();
    state.dockFavorites=Array.isArray(saved.dockFavorites)?saved.dockFavorites.slice():[];
    state.desktopLayout=(saved.desktopLayout&&typeof saved.desktopLayout==="object")?saved.desktopLayout:{};
  }else{
    /* v1 migration: derive WindowInstance entries from the ui blob. */
    syncWindowsFromUi();
    state.dockFavorites=[];
    state.desktopLayout={};
  }
}

/* ---- WindowInstance model (S2) ---------------------------------------- */
/* A window is one running instance of an app, optionally bound to a
   workstream. state.ui remains the rendering projection; windows are the
   durable domain model. */
function windowForApp(id){
  return state.windows.find(function(w){return w.appId===id})||null;
}
function syncWindowsFromUi(){
  var byApp={};
  state.windows.forEach(function(w){byApp[w.appId]=w});
  var next=[];
  state.registry.forEach(function(a){
    if(a.kind==="deferred")return;
    var existing=byApp[a.id];
    next.push(existing?Object.assign({},existing,{displayState:state.ui.min[a.id]?"minimized":(state.ui.max[a.id]?"maximized":"normal"),zIndex:state.ui.z[a.id]||0}):{
      id:"win-"+a.id,appId:a.id,
      contextBinding:{mode:"follow-active",workstreamId:null},
      bounds:(state.ui.geom[a.id]&&typeof state.ui.geom[a.id].x==="number")?state.ui.geom[a.id]:null,
      displayState:state.ui.min[a.id]?"minimized":(state.ui.max[a.id]?"maximized":"normal"),
      zIndex:state.ui.z[a.id]||0,
      appStateRef:null
    });
  });
  state.windows=next;
}
function setWindowBinding(id,mode,workstreamId){
  var w=windowForApp(id);
  if(!w)return;
  w.contextBinding={mode:mode==="locked"?"locked":(mode==="global"?"global":"follow-active"),workstreamId:(mode==="locked"&&workstreamId)?workstreamId:null};
  persist();applyView();
}
function effectiveWorkstreamId(id){
  /* The workstream a window projects: locked -> its own; global -> "all"
     (no single workstream); follow-active -> the active context. */
  var w=windowForApp(id);
  if(!w)return state.context.activeWorkstreamId||state.context.workstreamId||null;
  if(w.contextBinding.mode==="locked")return w.contextBinding.workstreamId||null;
  if(w.contextBinding.mode==="global")return "all";
  return state.context.activeWorkstreamId||state.context.workstreamId||null;
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
  try{var r=await fetch("apps.json",{cache:"no-store"});if(r.ok){var data=await r.json();state.registry=(data.apps||[]).filter(function(a){return a.id&&a.id!=="all"})}}catch(_e){state.registry=[]}
  if(!state.registry.length)state.registry=[{id:"work-console",title:"Work Console",short:"Work",kind:"pinned",window:"console"}];
}
function appById(id){return state.registry.find(function(a){return a.id===id})||null}
function windowOf(id){var a=appById(id);return a&&a.window?a.window:id}
function appIdForWindow(win){var a=state.registry.find(function(x){return(x.window||x.id)===win});return a?a.id:win}
function isDeferred(id){var a=appById(id);return!a||a.kind==="deferred"}
function isPinned(id){var a=appById(id);return!!a&&a.kind==="pinned"}
function activeWindowId(){
  /* One source of truth for the active window: the open, non-minimized app
     with the highest z-order. Focus, active app, and visual stacking all
     derive from state.ui.z. Null when no window is open (S3: no mandatory
     pinned window). */
  var best=null,bz=-1;
  Object.keys(state.ui.open).forEach(function(id){
    if(!state.ui.open[id]||state.ui.min[id]||isDeferred(id))return;
    var z=state.ui.z[id]||0;
    if(z>=bz){bz=z;best=id}
  });
  return best;
}

/* ---- chrome built from the one registry ----------------------------- */
/* S4: the dock shows favorites + running apps with compact icons and a quiet
   running indicator; the launcher lists ALL apps (deferred as catalog
   entries). The combined "Apps & canvas" drawer is removed. */
function renderChrome(){
  var mnav=q("[data-mobile-nav]"),dock=q("[data-os-dock]"),launcher=q("[data-launcher-list]");
  if(mnav)mnav.innerHTML="";if(dock)dock.innerHTML="";if(launcher)launcher.innerHTML="";
  var favorites=state.dockFavorites&&state.dockFavorites.length?state.dockFavorites.slice():
    ["work-console","decisions","evidence","studio"];
  var running=Object.keys(state.ui.open).filter(function(id){return !!state.ui.open[id]});
  var dockIds=[];
  favorites.forEach(function(id){if(dockIds.indexOf(id)===-1)dockIds.push(id)});
  running.forEach(function(id){if(dockIds.indexOf(id)===-1)dockIds.push(id)});
  dockIds.forEach(function(id){
    var a=appById(id);if(!a||a.kind==="deferred")return;
    var dk=document.createElement("button");
    dk.type="button";dk.dataset.dockApp=a.id;dk.dataset.dockKind=a.kind||"window";
    dk.setAttribute("aria-label",a.title);
    dk.innerHTML=(a.icon?'<span class="dock-icon">'+esc(a.icon)+'</span>':'<span class="dock-icon">'+esc((a.short||a.title||a.id).slice(0,2))+'</span>');
    dk.addEventListener("click",function(){openApp(a.id)});
    dock.appendChild(dk);
  });
  /* Launcher: every registry app (deferred as catalog entries). */
  state.registry.forEach(function(a){
    if(!launcher)return;
    var deferred=a.kind==="deferred";
    var b=document.createElement("button");
    b.type="button";b.dataset.launchApp=a.id;b.dataset.launchKind=a.kind||"window";
    b.innerHTML='<span class="launcher-icon">'+(a.icon?esc(a.icon):esc((a.short||a.title||a.id).slice(0,2)))+'</span><span class="launcher-label"><strong>'+esc(a.title)+'</strong><small>'+(deferred?"Soon · planned":esc(a.id))+'</small></span>';
    if(deferred){b.disabled=true;b.setAttribute("aria-disabled","true")}
    else b.addEventListener("click",function(){openApp(a.id);var panel=q("[data-launcher]");if(panel)panel.hidden=true;persist()});
    launcher.appendChild(b);
  });
  if(mnav){
    state.registry.forEach(function(a){
      if(a.kind==="deferred")return;
      var m=document.createElement("button");
      m.type="button";m.dataset.app=a.id;m.textContent=a.short||a.title;
      m.addEventListener("click",function(){openApp(a.id)});
      mnav.appendChild(m);
    });
    var back=document.createElement("button");
    back.type="button";back.dataset.mobileBack="1";back.setAttribute("aria-label","Back to Work Console");back.textContent="\u2190";
    back.addEventListener("click",function(){openApp("work-console")});
    mnav.appendChild(back);
  }
  syncNavActive();
}
function syncNavActive(){
  var narrow=isNarrow();
  qa("[data-app]").forEach(function(x){
    var on=narrow?x.dataset.app===state.ui.mobileApp:!!state.ui.open[x.dataset.app];
    x.classList.toggle("active",on);
  });
  /* Dock active-app affordance + quiet running indicator: the dock entry of
     the active window is highlighted; a running dot marks any open app. */
  qa("[data-dock-app]").forEach(function(x){
    var id=x.dataset.dockApp,open=!!state.ui.open[id];
    x.classList.toggle("active",narrow?id===state.ui.mobileApp:id===activeWindowId());
    x.classList.toggle("running",open);
  });
}

/* ---- responsive rendering ----------------------------------------- */
function isNarrow(){return window.innerWidth<=NARROW}
function ensureStudio(id){if(id==="studio"){var f=q("[data-studio-frame]");if(f&&!f.getAttribute("src")&&f.dataset.src)f.src=f.dataset.src}}
function applyView(){
  var narrow=isNarrow();
  document.body.classList.toggle("is-mobile",narrow);
  if(narrow){
    if(isDeferred(state.ui.mobileApp))state.ui.mobileApp="work-console";
    var w=windowOf(state.ui.mobileApp);
    qa("[data-window]").forEach(function(x){x.hidden=x.dataset.window!==w;x.classList.remove("minimized");x.style.left=x.style.top=x.style.width=x.style.height=x.style.zIndex=""});
    ensureStudio(state.ui.mobileApp);
  }else{
    qa("[data-window]").forEach(function(x){
      var id=appIdForWindow(x.dataset.window),open=!!state.ui.open[id];
      x.hidden=!open;
      x.classList.toggle("minimized",open&&!!state.ui.min[id]);
      x.classList.toggle("maximized",open&&!state.ui.min[id]&&!!state.ui.max[id]);
      x.classList.toggle("focused",open&&!state.ui.min[id]&&id===activeWindowId());
      if(open&&state.ui.z[id])x.style.zIndex=String(state.ui.z[id]);
      if(open)ensureStudio(id);
    });
    q("[data-canvas]").classList.toggle("compose",!!state.ui.arranging);
    var arrange=q("[data-arrange]");if(arrange)arrange.setAttribute("aria-pressed",String(!!state.ui.arranging));
    applyGeom();
  }
  /* S3: empty desktop — when no window is open (desktop), show the launcher
     affordance instead of forcing Work Console open. First-run (no saved
     session) shows the Cortxt Home placeholder instead. */
  var anyOpen=Object.keys(state.ui.open).some(function(id){return !!state.ui.open[id]&&!state.ui.min[id]});
  var emptyDesktop=q("[data-empty-desktop]");
  var homeSurface=q("[data-home-surface]");
  if(emptyDesktop)emptyDesktop.hidden=!!anyOpen;
  if(homeSurface)homeSurface.hidden=!!anyOpen||state.hadSavedSession;
  /* S2: quiet workstream-binding indicator per window. */
  qa("[data-binding-indicator]").forEach(function(el){
    var id=appIdForWindow((el.closest("[data-window]")||{}).dataset? (el.closest("[data-window]")||{}).dataset.window:"");
    el.textContent=id?bindingLabel(id):"";
  });
  syncNavActive();
}

/* ---- desktop window lifecycle ----------------------------------- */
/* S1b: app navigation pushes the shell state onto the hash so browser
   back/refresh/deep-link have defined semantics. Guarded so the DOM-less
   Node test runtime (no location/history) is unaffected. */
function pushShellState(appId){
  if(typeof ShellCommands!=="undefined"&&ShellCommands.pushState&&typeof location!=="undefined"){
    ShellCommands.pushState(appId||null,activeContextId());
  }
}
function openApp(id){
  if(isDeferred(id))return;
  state.ui.mobileApp=id;  /* last-touched app: what a switch to mobile shows */
  if(!isNarrow()){state.ui.open[id]=true;delete state.ui.min[id];state.ui.z[id]=++state.ui.zTop}
  ensureStudio(id);
  persist();applyView();pushShellState(id);
}
function focusApp(id){
  if(isDeferred(id))return;
  state.ui.mobileApp=id;
  if(!isNarrow()){state.ui.open[id]=true;delete state.ui.min[id];state.ui.z[id]=++state.ui.zTop}
  persist();applyView();pushShellState(id);
}
function closeApp(id){
  /* S3: Work Console is closable like any other window — no app window is
     permanently open. Deferred apps still cannot be opened/closed. */
  if(isDeferred(id))return;
  delete state.ui.open[id];delete state.ui.min[id];delete state.ui.z[id];
  persist();applyView();
}
function setMin(id,on){
  if(isDeferred(id))return;
  if(on)state.ui.min[id]=true;else delete state.ui.min[id];
  persist();applyView();
}
function setMax(id,on){
  /* Maximize/restore (issue #432): the pinned console is always full-width and
     cannot be maximized further; other windows toggle a persisted max flag. */
  if(isDeferred(id)||isPinned(id))return;
  if(on)state.ui.max[id]=true;else delete state.ui.max[id];
  persist();applyView();
}
function toggleMax(id){setMax(id,!state.ui.max[id])}
function toggleArrange(){state.ui.arranging=!state.ui.arranging;persist();applyView()}

/* ---- selected Workstream context ------------------------------- */
function items(){return(state.model&&state.model.workstreams)||[]}
function currentItem(){
  var list=items(),wanted=state.context.workstreamId;
  var found=wanted?list.find(function(x){return x.id===wanted}):null;
  if(found)return found;
  if(!wanted&&list.length)return list[0];
  return null;
}
function selectWorkstream(id){state.context.workstreamId=id;persist();propagateContext()}
/* S2: the workstream switcher supports "all" as a distinct global context and
   routes through a before-switch guard when a mutation is pending. */
function activeContextId(){
  return state.context.activeWorkstreamId||state.context.workstreamId||null;
}
function hasPendingMutation(){
  /* A mutation is pending when the confirm dialog is open or an approval
     reference has been entered but not yet submitted. */
  var dialog=q("[data-confirm-dialog]");
  if(dialog&&dialog.open)return true;
  var ref=q("[data-approval-ref]");
  if(ref&&ref.value&&ref.value.trim())return true;
  return false;
}
function switchWorkstream(id){
  /* id: a workstream id, "all", or null (no selection). */
  if(id!==activeContextId()&&hasPendingMutation()&&!window.confirm("Switch Workstream? Any unsaved approval reference will be discarded."))return;
  state.context.activeWorkstreamId=(id==="all")?"all":id;
  if(id==="all"){state.context.workstreamId=null}
  else{state.context.workstreamId=id}
  persist();propagateContext();renderSwitcher();
  if(typeof ShellCommands!=="undefined"&&ShellCommands.pushState&&typeof location!=="undefined"){
    ShellCommands.pushState(state.ui.mobileApp||null,activeContextId());
  }
}
function recentWorkstreams(){
  /* Most-recently-used first; attention items float up. */
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
  /* All Work is a distinct global context. */
  html+='<button type="button" class="ws-item'+(active==="all"?" active":"")+'" data-ws-id="all"><span class="ws-icon">\u229e</span><span><strong>All Work</strong><small>every workstream</small></span></button>';
  /* Recent + attention. */
  recent.forEach(function(x){
    var on=active===x.id;
    html+='<button type="button" class="ws-item'+(on?" active":"")+'" data-ws-id="'+esc(x.id)+'"><span class="ws-icon">'+(x.attention?'<em class="ws-attention">'+esc(x.attention==="decision"?"D":"B")+'</em>':esc(x.id.slice(0,2)))+'</span><span><strong>'+esc(x.title)+'</strong><small>'+esc(x.id)+(x.attention?' · '+esc(x.attention):'')+'</small></span></button>';
  });
  /* Archived = accepted records (workflow done). */
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
    b.addEventListener("click",function(){switchWorkstream(b.dataset.wsId)});
  });
  var count=q("[data-ws-create]");
  if(count)count.addEventListener("click",function(){
    /* Creating a workstream is a platform action behind the authorized port;
       in this slice we surface the command affordance only. */
    OSRenderer.emit("command",{command:"create-workstream"});
  });
}
function propagateContext(){
  var x=currentItem();
  q("[data-active-context]").textContent=x?(x.id+" · "+x.title):"No Workstream selected";
  var ctx={workstream:x,state:state};
  /* Render window content through the shared registry as the single path
     (#431). The inline projections remain only as a guarded fallback when an
     app has no registered renderer, so behavior is preserved and no app is
     forced to register before the shell works. */
  var d=q("[data-decisions-body]");
  if(d&&!OSRenderer.render("decisions",d,ctx))d.innerHTML=x?'<span class="eyebrow">'+esc(x.id)+'</span><h3>'+esc(x.title)+'</h3><p>'+(x.decision?esc(x.decision.summary):"No authoritative decision is pending for this Workstream.")+'</p>':empty("Select a Workstream to project its decision.");
  var e=q("[data-evidence-body]");
  if(e&&!OSRenderer.render("evidence",e,ctx))e.innerHTML=x?'<span class="eyebrow">'+esc(x.id)+'</span><h3>Evidence</h3><div class="projection-list">'+(x.evidence.length?x.evidence.map(function(ev){return'<article><strong>'+esc(ev.title)+'</strong><p>'+esc(ev.detail)+'</p></article>'}).join(""):empty("No authoritative evidence is attached."))+'</div>':empty("Select a Workstream to project its evidence.");
  qa("[data-studio-frame]").forEach(function(frame){
    var src="maker.html"+(x?"?workstream="+encodeURIComponent(x.id):"");
    frame.dataset.src=src;if(frame.getAttribute("src"))frame.src=src;
  });
  OSRenderer.emit("context",ctx);
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

/* ---- Work Console app ---------------------------------------- */
function render(){
  var handled=OSRenderer.render("work-console",q("[data-window=console]"),{workstream:currentItem(),state:state});
  if(!handled)renderWorkConsole(q("[data-window=console]"),{workstream:currentItem(),state:state});
  qa("[data-open-review]").forEach(function(button){button.addEventListener("click",function(){openReview(Number(button.dataset.openReview))})});
  showConsole((state.apps["work-console"]&&state.apps["work-console"].panel)||"attention",true);
  renderSwitcher();
  propagateContext();
}
function renderWorkConsole(winEl,ctx){
  /* Registered OSRenderer for work-console (issue #426): renders the operator
     panels (Attention, Workstreams, Accepted records) from the shared shell
     context. When the registry is unavailable the shell calls this directly as
     its fallback, so behavior is preserved either way. */
  var s=(ctx&&ctx.state)||state,list=s.model&&s.model.workstreams? s.model.workstreams:[];
  var attention=list.filter(function(x){return x.attention}),done=list.filter(function(x){return x.workflow==="done"});
  q("[data-attention-count]").textContent=attention.length;q("[data-attention-title]").textContent=attention.length?(attention.length+(attention.length===1?" boundary is":" boundaries are")+" waiting."):"Nothing needs your decision.";
  q("[data-attention-list]").innerHTML=attention.length?attention.map(function(x){return '<article class="attention-card"><div><span class="state">'+esc(x.attention==="decision"?"Decision required":"Blocked")+'</span><h3>'+esc(x.title)+'</h3><p>'+esc(x.outcome)+'</p></div><button data-open-review="'+x.number+'">'+(x.decision?"Review and decide":"View Workstream")+' →</button></article>'}).join(""):empty("No Workstream currently requires operator attention.");
  q("[data-workstream-list]").innerHTML=list.length?list.map(row).join(""):empty("No authoritative Workstreams are available.");q("[data-record-list]").innerHTML=done.length?done.map(row).join(""):empty("No accepted records are available in this projection.");
}
function row(x){return '<button class="workstream-row" data-open-review="'+x.number+'"><span>'+esc(x.id)+'</span><span><strong>'+esc(x.title)+'</strong><small>'+esc(x.outcome)+'</small>'+(x.decision?'<em class="pending-decision">Decision pending</em>':'')+(x.evidence&&x.evidence.length?'<em class="evidence-count">'+x.evidence.length+' evidence</em>':'')+'</span><span class="workflow">'+esc(x.workflow.replace("-"," "))+'</span></button>'}
/* Register the Work Console app renderer with the shared registry so it is a
   first-class app like Decisions/Evidence (issue #426). Guarded for the
   DOM-less Node test runtime where OSRenderer is absent. */
if(typeof OSRenderer!=="undefined"){OSRenderer.register("work-console",renderWorkConsole)}
function openReview(number){
  var item=items().find(function(x){return x.number===number});if(!item)return;
  selectWorkstream(item.id);
  qa("[data-console-panel]").forEach(function(x){x.hidden=true});
  var review=q("[data-review]");review.hidden=false;
  var evidence=item.evidence.length?item.evidence.map(function(x){return '<article class="evidence-card"><span class="eyebrow">'+esc(x.status)+'</span><h3>'+esc(x.title)+'</h3><p>'+esc(x.detail)+'</p></article>'}).join(""):empty("No authoritative evidence is attached. Decision actions remain unavailable.");
  var canAct=!state.model.synthetic&&item.decision&&state.token&&state.capabilities.some(function(x){return x.id==="record-decision"});
  review.innerHTML='<button class="back-button" data-review-back>← Back to Work Console</button><div class="review-grid"><main class="review-main"><span class="eyebrow">'+esc(item.id)+' · human decision</span><h2>'+(item.decision?esc(item.decision.summary):esc(item.title))+'</h2><p>'+esc(item.outcome)+'</p>'+evidence+'</main><aside><section class="authority-card"><span class="eyebrow">Durable authority</span><dl><div><dt>Source</dt><dd>'+esc(item.authority.source)+'</dd></div><div><dt>Workflow</dt><dd>'+esc(item.authority.workflow_label||"ambiguous")+'</dd></div><div><dt>Approval recorded</dt><dd>'+(item.authority.approval_recorded?"Yes":"Not found")+'</dd></div></dl></section><section class="authority-card"><span class="eyebrow">What happens next</span><p><b>If accepted:</b> evidence becomes the durable accepted record and the Issue advances to done.</p><p><b>If returned:</b> the Workstream stays paused for a bounded follow-up Run.</p></section><div class="review-actions"><button data-open-app="evidence">Open Evidence</button><button data-open-app="decisions">Open Decisions</button>'+(item.decision?'<button data-return '+(state.model.synthetic?"":"disabled")+'>Return with note</button><button class="primary-action" data-accept '+(state.model.synthetic||canAct?"":"disabled")+'>'+(state.model.synthetic?"Preview acceptance":canAct?"Accept record":"Action boundary unavailable")+'</button>':"")+'<small>'+(state.model.synthetic?"Preview outcome stays in this browser.":"Mutation requires an approval reference and explicit confirmation. Return is unavailable until a reviewed return transition exists.")+'</small></div></aside></div>';
  q("[data-review-back]").onclick=function(){showConsole("attention")};
  qa("[data-open-app]",review).forEach(function(b){b.onclick=function(){openApp(b.dataset.openApp)}});
  var accept=q("[data-accept]",review),returned=q("[data-return]",review);
  if(accept)accept.onclick=function(){state.model.synthetic?recordDemo("accepted"):confirmDecision()};
  if(returned)returned.onclick=function(){recordDemo("returned")};
}
function recordDemo(outcome){
  var it=currentItem();if(!it)return;
  if(outcome==="accepted"){it.workflow="done";it.attention=null;it.decision=null;render();showConsole("records")}
  else{it.workflow="in-progress";it.attention=null;it.decision=null;render();showConsole("workstreams")}
}
function confirmDecision(){
  var it=currentItem();if(!it)return;
  var dialog=q("[data-confirm-dialog]");q("[data-dialog-error]").textContent="";q("[data-approval-ref]").value="";dialog.showModal();
  dialog.onclose=async function(){
    if(dialog.returnValue!=="confirm")return;
    var approval=q("[data-approval-ref]").value.trim();
    if(!approval){q("[data-dialog-error]").textContent="Approval reference is required.";dialog.showModal();return}
    try{
      var response=await fetch("api/action",{method:"POST",headers:{"Content-Type":"application/json","X-Cortxt-Token":state.token},body:JSON.stringify({action_id:"record-decision",issue_id:it.issue_id,approval_ref:approval,confirm:true})});
      var result=await response.json();
      if(!response.ok)throw new Error(result.error&&result.error.message||"Decision was denied");
      state.model=await load();render();showConsole("records");
    }catch(error){q("[data-dialog-error]").textContent=error.message;dialog.showModal()}
  };
}
function showConsole(name,silent){
  q("[data-review]").hidden=true;
  qa("[data-console-panel]").forEach(function(x){x.hidden=x.dataset.consolePanel!==name});
  qa("[data-console-view]").forEach(function(x){x.classList.toggle("active",x.dataset.consoleView===name)});
  if(!state.apps["work-console"])state.apps["work-console"]={};
  state.apps["work-console"].panel=name;
  if(!silent)persist();
}

/* ---- static wiring ----------------------------------------- */
/* Guarded so the pure geometry helpers (tileRects/geomFor) can be required
   in a DOM-less runtime for layout tests. */
if(typeof document!=="undefined"&&typeof window!=="undefined"){
  /* S1a recursion guard: a Cortxt OS shell must never mount inside another
     Cortxt OS window. If this page is embedded in a frame, refuse to render
     the desktop and show an affordance instead. `window.top` access is
     security-thrown in some contexts; treat that as embedded (fail safe). */
  var isRecursionMount = false;
  try {
    isRecursionMount = (typeof window.top !== "undefined") && (window.self !== window.top);
  } catch (_e) { isRecursionMount = true; }
  if (isRecursionMount) {
    var _banner = q("[data-mode-banner]");
    if (_banner) _banner.innerHTML = "<strong>Open in Cortxt OS</strong><span>This surface cannot be embedded inside the OS.</span>";
    var _canvas = q("[data-canvas]");
    if (_canvas) _canvas.innerHTML = '' +
      '<div style="max-width:520px;margin:4rem auto;text-align:center;">' +
        '<h2 style="margin:0 0 .5rem;">Open in Cortxt OS</h2>' +
        '<p style="color:var(--muted);line-height:1.5;margin:0 0 1rem;">A Cortxt OS window cannot be embedded inside itself. Use the launcher to open this app in the OS.</p>' +
      '</div>';
  } else if (typeof ShellIframeBridge !== "undefined" && ShellIframeBridge.listenFromIframe) {
    /* Origin-validated activation from an iframe-hosted app (S1a). The
       bridge validates origin, command, and payload; we only focus/open the
       requested app. No window.top navigation. */
    ShellIframeBridge.listenFromIframe(function(payload){
      var id = (payload && payload.appId) || null;
      if (id && state && state.registry) focusApp(id);
    });
  }
  /* S1b: typed shell command router — internal navigation goes through
     commands, never ordinary page navigation. open-home is typed and no-ops
     gracefully until Cortxt Home ships (S5); exit-workspace returns to the
     public landing; open-external opens a new tab. */
  if (typeof ShellCommands !== "undefined") {
    var commandHandlers = {
      "open-app": function(p){ if(p&&p.appId)openApp(p.appId); },
      "close-app": function(p){ if(p&&p.appId)closeApp(p.appId); },
      "focus-app": function(p){ if(p&&p.appId)focusApp(p.appId); },
      "switch-workstream": function(p){ if(p&&p.workstreamId)switchWorkstream(p.workstreamId); },
      "open-home": function(){ /* typed command; Cortxt Home ships in S5 */ },
      "exit-workspace": function(){ try{global.location.href="/"}catch(_e){} },
      "open-external": function(p){ if(p&&p.url)try{global.open(p.url,"_blank","noopener")}catch(_e){} },
    };
    window.ShellCommandHandlers = commandHandlers;
    window.addEventListener("hashchange", function(){
      if (typeof ShellCommands !== "undefined" && ShellCommands.applyDeepLink) {
        ShellCommands.applyDeepLink(location.hash, commandHandlers);
      }
    });
  }
  /* S4: launcher trigger/close replace the removed "Apps & canvas" drawer. */
  var launcherToggle=q("[data-launcher-toggle]"),launcherPanel=q("[data-launcher]");
  function openLauncher(){if(launcherPanel){launcherPanel.hidden=false;renderChrome()}}
  if(launcherToggle){launcherToggle.onclick=function(){var open=launcherPanel&&!launcherPanel.hidden;if(launcherPanel)launcherPanel.hidden=open;this.setAttribute("aria-expanded",String(!open));if(!open)openLauncher()}}
  var launcherClose=q("[data-launcher-close]");
  if(launcherClose)launcherClose.onclick=function(){if(launcherPanel)launcherPanel.hidden=true};
  var wsToggle=q("[data-ws-toggle]"),wsPanel=q("[data-workstream-switcher]");
  if(wsToggle&&wsPanel){wsToggle.onclick=function(){var open=wsPanel.hidden;wsPanel.hidden=!open;this.setAttribute("aria-expanded",String(open));if(open)renderSwitcher()}}
  var arrangeButton=q("[data-arrange]");if(arrangeButton)arrangeButton.onclick=toggleArrange;
  qa("[data-window-focus]").forEach(function(x){x.onclick=function(){focusApp(x.dataset.windowFocus)}});
  qa("[data-window-min]").forEach(function(x){x.onclick=function(){var id=x.dataset.windowMin;setMin(id,!state.ui.min[id])}});
  qa("[data-window-max]").forEach(function(x){x.onclick=function(){toggleMax(x.dataset.windowMax)}});
  qa("[data-close-window]").forEach(function(x){x.onclick=function(){closeApp(x.dataset.closeWindow)}});
  qa("[data-console-view]").forEach(function(x){x.onclick=function(){showConsole(x.dataset.consoleView)}});
  qa("[data-window] .window-bar").forEach(function(bar){bar.addEventListener("dblclick",function(ev){if(ev.target.closest("button,a,input"))return;var win=bar.closest("[data-window]"),id=appIdForWindow(win.dataset.window);if(state.ui.min[id])setMin(id,false)})});
  initCompose();
  /* Pointer-down on a window surface gives that window focus and raises it
     (desktop). Interactive controls keep their own behavior; the window
     chrome buttons already call focusApp/openApp themselves. */
  document.addEventListener("pointerdown",function(ev){
    if(isNarrow())return;
    var win=ev.target.closest("[data-window]");
    if(!win)return;
    if(ev.target.closest("button,a,input"))return;
    focusApp(appIdForWindow(win.dataset.window));
  });
  var resizeTimer;window.addEventListener("resize",function(){clearTimeout(resizeTimer);resizeTimer=setTimeout(applyView,120)});

  restore();
  loadTokens();
  loadRegistry().then(function(){
    renderChrome();applyView();
    return Promise.all([load(),loadBoundary()]);
  }).then(function(values){
    state.model=values[0];setMode();render();applyView();renderSwitcher();
    /* S1b: apply an initial deep link (#app=...&ws=...) once the registry and
       model are available. */
    if (typeof ShellCommands !== "undefined" && ShellCommands.applyDeepLink && typeof location !== "undefined") {
      ShellCommands.applyDeepLink(location.hash, window.ShellCommandHandlers);
    }
  }).catch(function(error){
    q("[data-mode-banner]").innerHTML="<strong>Data unavailable</strong><span>"+esc(error.message)+"</span>";
    q("[data-attention-title]").textContent="Work Console could not establish authoritative state.";
    q("[data-attention-list]").innerHTML=empty("The app failed closed. No evidence or decision action is exposed.");
  });
}
if(typeof module==="object"&&module.exports)module.exports={tileRects:tileRects,geomFor:geomFor,CONSOLE_W:CONSOLE_W,GUTTER:GUTTER};
})();
