/* shell-commands.js — typed shell command router, deep links, and browser
   history for Cortxt OS (issue #439, S1b).
   Internal app navigation must go through shell commands, never ordinary page
   navigation. Commands dispatch to the shell lifecycle functions; deep links
   (#app=<id>[&ws=<id>]) and browser history give back/refresh/deep-link
   defined semantics.

   Commands (typed):
     open-app{appId}            focus/open an app window
     close-app{appId}           close an app window
     focus-app{appId}           raise an app window
     switch-workstream{workstreamId}  select a workstream ("all" allowed)
     open-home{}                open Cortxt Home (typed; no-ops until S5)
     exit-workspace{}           return to the public landing experience
     open-external{url}         explicit external navigation (new tab)
     focus-record{appId, workstreamId, recordRef}  validated navigation to a
                              source record inside an app (S5.5c/ADR-044:
                              Activity Center validated navigation)

   Deep links (#app=<id>[&ws=<id>][&record=<ref>]) resolve the legacy
   `work-console` app id to the first principal app `work` through a
   one-release compatibility alias (ADR-044). Unknown commands, apps,
   workstreams, and record references fail closed: the router ignores them
   and never navigates.
*/
(function (global) {
  "use strict";
  var APP_COMMANDS = {
    "open-app": true,
    "close-app": true,
    "focus-app": true,
    "switch-workstream": true,
    "open-home": true,
    "exit-workspace": true,
    "open-external": true,
    "focus-record": true,
  };

  /* ADR-044: Work Console is retired. For one release cycle its app id
     resolves to the first principal app `work`; removing the alias is a
     separate operator decision. */
  var LEGACY_APP_ALIASES = { "work-console": "work" };

  function normalizeAppId(id) {
    return LEGACY_APP_ALIASES[id] || id;
  }

  function isPlainObject(x) {
    return !!x && typeof x === "object" && !Array.isArray(x);
  }

  /* ---- deep links ---------------------------------------------------- */
  function parseDeepLink(hash) {
    /* Accepts "#app=studio&ws=WS-042", "#app=work-console" (-> "#app=work"),
       "#ws=all", "#app=decisions&ws=WS-042&record=#445", or empty. Returns
       {appId, workstreamId, recordRef} (each may be null); the legacy
       work-console app id normalizes to `work`. */
    var out = { appId: null, workstreamId: null, recordRef: null };
    if (!hash || hash === "#" || hash === "#/") return out;
    var h = hash.charAt(0) === "#" ? hash.slice(1) : hash;
    if (h.charAt(0) === "/") h = h.slice(1);
    var pairs = h.split("&");
    for (var i = 0; i < pairs.length; i++) {
      var kv = pairs[i].split("=", 2);
      var k = decodeURIComponent(kv[0] || "").trim();
      var v = kv.length > 1 ? decodeURIComponent(kv[1] || "").trim() : "";
      if (k === "app" && v) out.appId = normalizeAppId(v);
      else if (k === "ws" && v) out.workstreamId = v;
      else if (k === "record" && v) out.recordRef = v;
    }
    return out;
  }

  /* ---- history ------------------------------------------------------- */
  function currentHash() {
    try { return (typeof location !== "undefined") ? location.hash : ""; } catch (_e) { return ""; }
  }

  var API = {
    APP_COMMANDS: APP_COMMANDS,
    LEGACY_APP_ALIASES: LEGACY_APP_ALIASES,
    normalizeAppId: normalizeAppId,
    parseDeepLink: parseDeepLink,

    /** Dispatch a typed command to the provided handlers. handlers is an
        object with optional functions for each command name; unknown commands
        or missing handlers are ignored (fail closed, no navigation). */
    dispatch: function (command, payload, handlers) {
      if (typeof command !== "string") return false;
      if (!APP_COMMANDS[command]) return false;
      if (!handlers || typeof handlers !== "object") return false;
      var fn = handlers[command];
      if (typeof fn !== "function") return false;
      fn(isPlainObject(payload) ? payload : {});
      return true;
    },

    /** Apply a deep link against the shell handlers. */
    applyDeepLink: function (hash, handlers) {
      var link = parseDeepLink(hash || currentHash());
      var applied = false;
      if (link.workstreamId && handlers && typeof handlers["switch-workstream"] === "function") {
        handlers["switch-workstream"]({ workstreamId: link.workstreamId });
        applied = true;
      }
      /* S5.5c: a deep link carrying a record reference navigates through the
         validated focus-record command (app/workstream/record all validated
         by the handler; unknown values fail closed). */
      if (link.appId && link.recordRef && handlers && typeof handlers["focus-record"] === "function") {
        handlers["focus-record"]({ appId: link.appId, workstreamId: link.workstreamId, recordRef: link.recordRef });
        applied = true;
      } else if (link.appId && handlers && typeof handlers["open-app"] === "function") {
        handlers["open-app"]({ appId: link.appId });
        applied = true;
      }
      return applied;
    },

    /** Push an app/workstream state onto the hash so back/refresh/deep-link
        have defined semantics. */
    pushState: function (appId, workstreamId) {
      var parts = [];
      if (appId) parts.push("app=" + encodeURIComponent(appId));
      if (workstreamId) parts.push("ws=" + encodeURIComponent(workstreamId));
      var next = parts.length ? "#" + parts.join("&") : "#";
      try {
        if (typeof history !== "undefined" && history.pushState) {
          history.pushState(null, "", next);
        } else {
          global.location.hash = next;
        }
      } catch (_e) { /* hash assignment may throw in sandboxed contexts */ }
    },

    /** Replace the current history entry without adding a new one. */
    replaceState: function (appId, workstreamId) {
      var parts = [];
      if (appId) parts.push("app=" + encodeURIComponent(appId));
      if (workstreamId) parts.push("ws=" + encodeURIComponent(workstreamId));
      var next = parts.length ? "#" + parts.join("&") : "#";
      try {
        if (typeof history !== "undefined" && history.replaceState) {
          history.replaceState(null, "", next);
        } else {
          global.location.hash = next;
        }
      } catch (_e) { /* ignore */ }
    },
  };

  global.ShellCommands = API;
  if (typeof module === "object" && module.exports) module.exports = API;
})(typeof window !== "undefined" ? window : globalThis);
