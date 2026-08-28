/* Shared OS app renderer registry (issue #425).
   Lets distinct apps (Work Console, Decisions, Evidence, ...) register their
   own window-content renderers so they can be built and extended in parallel
   without every app editing the shell's monolithic render logic. The shell
   delegates to a registered renderer first and falls back to its own inline
   rendering when none is registered, so the registry is strictly additive and
   behavior-preserving.

   API (window.OSRenderer):
     register(appId, renderFn)  - idempotent-per-app; renderFn(winEl, ctx) is
                                  called with the app's window element and the
                                  shared shell context ({workstream, state}).
     render(appId, winEl, ctx)  - dispatch to the registered renderer; returns
                                  true when handled, false when not registered.
     has(appId)                 - true when a renderer is registered.
   No private palette: renderers must use canonical CSS classes / tokens only.
*/
(function (global) {
  "use strict";
  var registry = {};

  function register(appId, renderFn) {
    if (!appId || typeof renderFn !== "function") return;
    registry[appId] = renderFn;
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

  var api = { register: register, render: render, has: has };
  if (typeof module === "object" && module.exports) module.exports = api;
  global.OSRenderer = api;
})(typeof window !== "undefined" ? window : globalThis);
