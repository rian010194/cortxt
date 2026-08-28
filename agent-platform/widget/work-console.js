(function(){"use strict";
/* Cortxt OS shell core.
   One authoritative app registry (apps.json) drives the app drawer, the mobile
   navigation bar and window resolution. Shell state is split into three parts:
     state.ui       global UI state (open/minimised windows, z-order, arrange
                    mode, drawer, the single active mobile app)
     state.context  the selected Workstream, propagated to every mounted app
     state.apps     app-local view state (e.g. the Work Console sub-view)
   state.ui + state.context + state.apps persist to one localStorage key so a
   reload restores the layout and the selected Workstream without defaulting
   back to the first item. The authority boundary (load/loadBoundary/
   confirmDecision) is unchanged and still fails closed. */
var SHELL_KEY="cortxt-os-shell",NARROW=720;
var state={
  model:null,token:null,capabilities:[],registry:[],
  ui:{open:{"work-console":true},min:{},z:{},geom:{},zTop:10,arranging:false,mobileApp:"work-console",drawer:false},
  context:{workstreamId:null},
  apps:{"work-console":{panel:"attention"}}
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

/* ---- persistence -------------------------------------------------------- */
function persist(){try{localStorage.setItem(SHELL_KEY,JSON.stringify({ui:state.ui,context:state.context,apps:state.apps}))}catch(_e){}}
function restore(){
  var saved;try{saved=JSON.parse(localStorage.getItem(SHELL_KEY)||"null")}catch(_e){saved=null}
  if(!saved||typeof saved!=="object")return;
  if(saved.ui&&typeof saved.ui==="object"){
    state.ui=Object.assign(state.ui,saved.ui);
    state.ui.open=Object.assign({},saved.ui.open);state.ui.open["work-console"]=true;
    state.ui.min=Object.assign({},saved.ui.min);state.ui.z=Object.assign({},saved.ui.z);
    state.ui.geom=(saved.ui.geom&&typeof saved.ui.geom==="object")?Object.assign({},saved.ui.geom):{};
  }
  if(saved.context&&typeof saved.context.workstreamId==="string")state.context.workstreamId=saved.context.workstreamId;
  if(saved.apps&&typeof saved.apps==="object")state.apps=Object.assign(state.apps,saved.apps);
  if(!state.apps["work-console"])state.apps["work-console"]={panel:"attention"};
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
     derive from state.ui.z. */
  var best="work-console",bz=-1;
  Object.keys(state.ui.open).forEach(function(id){
    if(!state.ui.open[id]||state.ui.min[id]||isDeferred(id))return;
    var z=state.ui.z[id]||0;
    if(z>=bz){bz=z;best=id}
  });
  return best;
}

/* ---- chrome built from the one registry ----------------------------- */
function renderChrome(){
  var drawer=q("[data-app-list]"),mnav=q("[data-mobile-nav]");
  if(drawer)drawer.innerHTML="";if(mnav)mnav.innerHTML="";
  state.registry.forEach(function(a){
    var deferred=a.kind==="deferred";
    if(drawer){
      var b=document.createElement("button");
      b.type="button";b.dataset.app=a.id;b.dataset.appKind=a.kind||"window";
      b.textContent=a.title+(deferred?" · soon":"");
      if(deferred){b.disabled=true;b.setAttribute("aria-disabled","true")}
      else b.addEventListener("click",function(){openApp(a.id);state.ui.drawer=false;q("[data-app-drawer]").hidden=true;persist()});
      drawer.appendChild(b);
    }
    if(mnav&&!deferred){
      var m=document.createElement("button");
      m.type="button";m.dataset.app=a.id;m.textContent=a.short||a.title;
      m.addEventListener("click",function(){openApp(a.id)});
      mnav.appendChild(m);
    }
  });
  if(mnav){
    /* Explicit back navigation on mobile: returns to the default app (Work
       Console) and preserves the selected Workstream context (openApp only
       changes the active mobile app, never the context). */
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
    state.ui.open["work-console"]=true;
    qa("[data-window]").forEach(function(x){
      var id=appIdForWindow(x.dataset.window),open=!!state.ui.open[id];
      x.hidden=!open;
      x.classList.toggle("minimized",open&&!!state.ui.min[id]);
      x.classList.toggle("focused",open&&!state.ui.min[id]&&id===activeWindowId());
      if(open&&state.ui.z[id])x.style.zIndex=String(state.ui.z[id]);
      if(open)ensureStudio(id);
    });
    q("[data-canvas]").classList.toggle("compose",!!state.ui.arranging);
    var arrange=q("[data-arrange]");if(arrange)arrange.setAttribute("aria-pressed",String(!!state.ui.arranging));
    applyGeom();
  }
  syncNavActive();
}

/* ---- desktop window lifecycle ----------------------------------- */
function openApp(id){
  if(isDeferred(id))return;
  state.ui.mobileApp=id;  /* last-touched app: what a switch to mobile shows */
  if(!isNarrow()){state.ui.open[id]=true;delete state.ui.min[id];state.ui.z[id]=++state.ui.zTop}
  ensureStudio(id);
  persist();applyView();
}
function focusApp(id){
  if(isDeferred(id))return;
  state.ui.mobileApp=id;
  if(!isNarrow()){state.ui.open[id]=true;delete state.ui.min[id];state.ui.z[id]=++state.ui.zTop}
  persist();applyView();
}
function closeApp(id){
  if(isPinned(id)||isDeferred(id))return;
  delete state.ui.open[id];delete state.ui.min[id];delete state.ui.z[id];
  persist();applyView();
}
function setMin(id,on){
  if(isDeferred(id))return;
  if(on)state.ui.min[id]=true;else delete state.ui.min[id];
  persist();applyView();
}
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
function propagateContext(){
  var x=currentItem();
  q("[data-active-context]").textContent=x?(x.id+" · "+x.title):"No Workstream selected";
  var d=q("[data-decisions-body]");
  if(d)d.innerHTML=x?'<span class="eyebrow">'+esc(x.id)+'</span><h3>'+esc(x.title)+'</h3><p>'+(x.decision?esc(x.decision.summary):"No authoritative decision is pending for this Workstream.")+'</p>':empty("Select a Workstream to project its decision.");
  var e=q("[data-evidence-body]");
  if(e)e.innerHTML=x?'<span class="eyebrow">'+esc(x.id)+'</span><h3>Evidence</h3><div class="projection-list">'+(x.evidence.length?x.evidence.map(function(ev){return'<article><strong>'+esc(ev.title)+'</strong><p>'+esc(ev.detail)+'</p></article>'}).join(""):empty("No authoritative evidence is attached."))+'</div>':empty("Select a Workstream to project its evidence.");
  qa("[data-studio-frame]").forEach(function(frame){
    var src="maker.html"+(x?"?workstream="+encodeURIComponent(x.id):"");
    frame.dataset.src=src;if(frame.getAttribute("src"))frame.src=src;
  });
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
  var list=items(),attention=list.filter(function(x){return x.attention}),done=list.filter(function(x){return x.workflow==="done"});
  q("[data-attention-count]").textContent=attention.length;q("[data-attention-title]").textContent=attention.length?(attention.length+(attention.length===1?" boundary is":" boundaries are")+" waiting."):"Nothing needs your decision.";
  q("[data-attention-list]").innerHTML=attention.length?attention.map(function(x){return '<article class="attention-card"><div><span class="state">'+esc(x.attention==="decision"?"Decision required":"Blocked")+'</span><h3>'+esc(x.title)+'</h3><p>'+esc(x.outcome)+'</p></div><button data-open-review="'+x.number+'">'+(x.decision?"Review and decide":"View Workstream")+' →</button></article>'}).join(""):empty("No Workstream currently requires operator attention.");
  q("[data-workstream-list]").innerHTML=list.length?list.map(row).join(""):empty("No authoritative Workstreams are available.");q("[data-record-list]").innerHTML=done.length?done.map(row).join(""):empty("No accepted records are available in this projection.");
  qa("[data-open-review]").forEach(function(button){button.addEventListener("click",function(){openReview(Number(button.dataset.openReview))})});
  showConsole((state.apps["work-console"]&&state.apps["work-console"].panel)||"attention",true);
  propagateContext();
}
function row(x){return '<button class="workstream-row" data-open-review="'+x.number+'"><span>'+esc(x.id)+'</span><span><strong>'+esc(x.title)+'</strong><small>'+esc(x.outcome)+'</small></span><span class="workflow">'+esc(x.workflow.replace("-"," "))+'</span></button>'}
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
  q("[data-reveal-apps]").onclick=function(){var drawer=q("[data-app-drawer]");state.ui.drawer=drawer.hidden;drawer.hidden=!drawer.hidden;this.setAttribute("aria-expanded",String(state.ui.drawer));persist()};
  var arrangeButton=q("[data-arrange]");if(arrangeButton)arrangeButton.onclick=toggleArrange;
  qa("[data-window-focus]").forEach(function(x){x.onclick=function(){focusApp(x.dataset.windowFocus)}});
  qa("[data-window-min]").forEach(function(x){x.onclick=function(){var id=x.dataset.windowMin;setMin(id,!state.ui.min[id])}});
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
    state.model=values[0];setMode();render();applyView();
  }).catch(function(error){
    q("[data-mode-banner]").innerHTML="<strong>Data unavailable</strong><span>"+esc(error.message)+"</span>";
    q("[data-attention-title]").textContent="Work Console could not establish authoritative state.";
    q("[data-attention-list]").innerHTML=empty("The app failed closed. No evidence or decision action is exposed.");
  });
}
if(typeof module==="object"&&module.exports)module.exports={tileRects:tileRects,geomFor:geomFor,CONSOLE_W:CONSOLE_W,GUTTER:GUTTER};
})();
