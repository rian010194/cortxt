/* shell-iframe-bridge.js — origin-validated parent/child shell command
   channel for iframe-hosted apps (issue #435, S1a).
   Protects the Cortxt OS shell boundary: an app served inside a Studio-style
   iframe must never navigate to the OS shell URLs (which would mount a second
   OS and recurse). Instead it requests the parent shell to activate an app via
   a typed postMessage command; the parent validates origin, command, and
   payload, then acts.

   Contract (both sides must agree):
     message = {
       source: "cortxt-os-iframe",
       v: 1,
       command: "activate-app",
       payload: { appId: string }
     }

   No window.top navigation. The parent shell owns app activation.
*/
(function (global) {
  "use strict";
  var SOURCE = "cortxt-os-iframe";
  var V = 1;
  var ALLOWED_COMMANDS = { "activate-app": true };
  var ALLOWED_APP_IDS = { "work-console": true, "decisions": true, "evidence": true, "studio": true };

  function isPlainObject(x) {
    return !!x && typeof x === "object" && !Array.isArray(x);
  }

  function normalizeOrigin(origin) {
    // Convert a postMessage origin (scheme://host[:port]) to a comparable key.
    try { return new URL(origin).origin; } catch (_e) { return null; }
  }

  function defaultAllowedOrigins() {
    // Same-origin by default: the shell and its iframe are served together,
    // so the iframe posts to the shell with the shell's own origin.
    if (typeof location !== "undefined") return normalizeOrigin(location.origin);
    return null;
  }

  var API = {
    SOURCE: SOURCE,
    V: V,

    /** Validate an incoming message event against the allowed origin set.
        Returns the normalized payload when valid, null otherwise. */
    validateMessage: function (ev, allowedOrigins) {
      if (!ev || !isPlainObject(ev.data)) return null;
      var data = ev.data;
      if (data.source !== SOURCE) return null;
      if (data.v !== V) return null;
      if (!ALLOWED_COMMANDS[data.command]) return null;
      var origins = allowedOrigins;
      if (origins === undefined || origins === null) {
        var def = defaultAllowedOrigins();
        origins = def ? [def] : [];
      }
      if (!Array.isArray(origins)) origins = [origins];
      var incoming = normalizeOrigin(ev.origin);
      if (!incoming || origins.indexOf(incoming) === -1) return null;
      var payload = data.payload;
      if (!isPlainObject(payload) || typeof payload.appId !== "string") return null;
      if (!ALLOWED_APP_IDS[payload.appId]) return null;
      return payload;
    },

    /** Parent-side: listen for a valid activation command and forward it.
        handler(payload) is called with { appId }. Returns a teardown fn. */
    listenFromIframe: function (handler, allowedOrigins) {
      if (typeof handler !== "function") return function () {};
      var listener = function (ev) {
        var payload = API.validateMessage(ev, allowedOrigins);
        if (!payload) return;
        handler(payload);
      };
      (global.addEventListener || global.attachEvent)("message", listener, false);
      return function () {
        (global.removeEventListener || global.detachEvent)("message", listener, false);
      };
    },

    /** Child-side: request the parent shell to activate an app. */
    requestActivateApp: function (appId) {
      if (typeof global.parent === "undefined") return false;
      if (!ALLOWED_APP_IDS[appId]) return false;
      try {
        global.parent.postMessage({ source: SOURCE, v: V, command: "activate-app", payload: { appId: appId } }, "*");
        return true;
      } catch (_e) {
        return false;
      }
    },
  };

  global.ShellIframeBridge = API;
  if (typeof module === "object" && module.exports) module.exports = API;
})(typeof window !== "undefined" ? window : globalThis);
