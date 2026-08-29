/* Shared OS app renderer registry (issues #425, #431).
   Lets distinct apps (Work Console, Decisions, Evidence, Execution Inspector,
   Policies, Atlas, Connections, Studio, ...) register their own window-content
   renderers so they can be built and extended in parallel without every app
   editing the shell's monolithic render logic. The shell delegates to a
   registered renderer first and falls back to its own inline rendering when
   none is registered, so the registry is strictly additive and
   behavior-preserving.

   API (window.OSRenderer):
     register(appId, renderFn, opts?) - idempotent-per-app; renderFn(winEl, ctx)
       is called with the app's window element and the shared shell context
       ({workstream, state}). opts may carry {capabilities:[...]}.
     render(appId, winEl, ctx)        - dispatch to the registered renderer;
       returns true when handled, false when not registered.
     has(appId)                       - true when a renderer is registered.
     mount(appId, winEl, ctx)         - lifecycle hook: called when an app's
       window is opened/shown; returns true when handled.
     unmount(appId)                   - lifecycle hook: called when an app's
       window is closed/hidden; returns true when handled.
     on(event, fn) / emit(event, payload) - lightweight shell<->app event
       channel; fn receives (payload). No hidden coupling: events are named and
       payloads are plain data.
     capabilities(appId)              - array of declared capabilities from
       register() opts, or [] when none.
   No private palette: renderers must use canonical CSS classes / tokens only.
*/
(function (global) {
  "use strict";
  var registry = {};
  var capabilities = {};
  var events = {};

  function register(appId, renderFn, opts) {
    if (!appId || typeof renderFn !== "function") return;
    registry[appId] = renderFn;
    capabilities[appId] = (opts && Array.isArray(opts.capabilities))
      ? opts.capabilities.slice()
      : [];
  }

  function has(appId) {
    return Object.prototype.hasOwnProperty.call(registry, appId);
  }

  function render(appId, winEl, ctx) {
    var fn = registry[appId];
    if (typeof fn !== "function") return false;
    fn(winEl || null, ctx || {});
    return true;
  }

  function mount(appId, winEl, ctx) {
    var fn = registry[appId];
    if (typeof fn !== "function") return false;
    // mount is render + lifecycle notification; renderers may override by
    // registering a function with a .mount property later — for now the
    // render function is the mount body (behavior-preserving).
    fn(winEl || null, ctx || {});
    return true;
  }

  function unmount(appId) {
    return Object.prototype.hasOwnProperty.call(registry, appId);
  }

  function on(event, fn) {
    if (!event || typeof fn !== "function") return;
    (events[event] = events[event] || []).push(fn);
  }

  function emit(event, payload) {
    var list = events[event] || [];
    for (var i = 0; i < list.length; i++) {
      try { list[i](payload); } catch (_e) { /* one bad listener must not break the bus */ }
    }
    return list.length > 0;
  }

  function appCapabilities(appId) {
    var c = capabilities[appId];
    return Array.isArray(c) ? c.slice() : [];
  }

  var api = {
    register: register, render: render, has: has,
    mount: mount, unmount: unmount,
    on: on, emit: emit,
    capabilities: appCapabilities,
  };
  if (typeof module === "object" && module.exports) module.exports = api;
  global.OSRenderer = api;
})(typeof window !== "undefined" ? window : globalThis);
