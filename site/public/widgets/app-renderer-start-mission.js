/* "Start a mission" — the entry step of the Work flow (#469 UX pass).

   Why this app exists
   -------------------
   Every "New Workstream" control in the shell emitted
   `OSRenderer.emit("command", {command:"create-workstream"})`, and nothing
   anywhere subscribed to the `command` event. Three buttons on two surfaces
   did nothing at all when clicked. The flow the operator is supposed to walk --
   start a mission, understand its terms, launch it, follow it, review it --
   had no first step.

   This app is that first step, and it is deliberately NOT a new mission
   store. A mission in Cortxt IS a GitHub Issue: the Issue holds the mandate,
   the approval, the limits and the artifact policy that the launcher and the
   Evidence Gate read. Inventing a browser-side "mission" object would create a
   second source of truth that no gate honours. So this app does two honest
   things instead:

     1. It projects the missions that actually exist -- the same
        `/api/workstreams` projection the shell already loads -- grouped by
        what the operator can do with each one now, in the operator's language.
     2. For a mission that does not exist yet, it says plainly that the record
        is an Issue and opens the tracker. That is a real, working action, not
        a button that silently drops the click.

   The status vocabulary lives here (`MissionState`) because it is shared: Home
   and Work render the same words for the same state, so an operator never has
   to learn that "review" on one surface and "Ready for your review" on another
   are the same thing.

   Nothing here mutates. The app reads the projection the shell already holds,
   selects a Workstream, and navigates. Starting a Run stays entirely in the
   "launch" app behind its operator-gated confirmation.
*/
(function (global) {
  "use strict";

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ---- the shared plain-language mission state ------------------------

     One mapping, used by this app, by Home's resume card and by Work's
     header. The `workflow` label on the Issue is the authority; this only
     translates it. Two rules it must never break:

     - An unrecognised workflow becomes "State not recorded", never a guess
       and never a default of "ready". A mission whose state the OS cannot
       read must not look like one that is safe to start.
     - "Finished" is never said on the strength of a process ending. The only
       thing that closes a mission here is the Issue being `done`; a worker
       reporting that it exited says nothing about whether its result was
       accepted, which is the Evidence Gate's verdict and is rendered by the
       launch app's terminal panel, not by this vocabulary. */
  var STATES = {
    inbox: {
      key: "inbox", label: "Not started", tone: "idle",
      meaning: "Captured, but not yet shaped into an approved mandate.",
      next: "Open it to see what it still needs before it can run.",
    },
    ready: {
      key: "ready", label: "Ready to start", tone: "ready",
      meaning: "Approved, with its scope and limits recorded. It can be started.",
      next: "Review the run conditions, then start it.",
    },
    "in-progress": {
      key: "running", label: "Running", tone: "busy",
      meaning: "A worker holds this mission right now.",
      next: "Follow the run and wait for its result.",
    },
    review: {
      key: "review", label: "Ready for your review", tone: "attention",
      meaning: "The work finished and is waiting for a decision from you.",
      next: "Read what changed, then decide whether to take it further.",
    },
    blocked: {
      key: "blocked", label: "Blocked", tone: "bad",
      meaning: "Stopped. It cannot continue until something is resolved.",
      next: "Open it to see what stopped it and what the recovery is.",
    },
    done: {
      key: "done", label: "Closed", tone: "done",
      meaning: "Finished and closed.",
      next: "Nothing is pending.",
    },
  };

  var UNKNOWN = {
    key: "unknown", label: "State not recorded", tone: "idle",
    meaning: "No workflow state could be read for this mission.",
    next: "Open it to see the record the OS actually has.",
  };

  /* A mission awaiting an operator decision is called out separately from one
     merely in review: "needs you" and "you may look" are different demands on
     the operator's attention, and collapsing them is what makes an activity
     list unreadable. */
  var DECISION = {
    key: "decision", label: "Needs your decision", tone: "attention",
    meaning: "An authoritative decision is pending and only you can make it.",
    next: "Open Decisions and record the decision.",
  };

  function missionState(x) {
    if (!x) return UNKNOWN;
    if (x.decision) return DECISION;
    /* Strip the `workflow:` prefix exactly as `followable`, `claimed` and
       `runResultAvailable` do. Without it a producer sending the prefixed
       form would make one mission read "State not recorded" on Start, Home
       and Work while the launch panel correctly showed its run result --
       breaking the single shared vocabulary this module exists to provide. */
    var s = STATES[String(x.workflow || "").replace(/^workflow:/, "")];
    return s || UNKNOWN;
  }

  /* Display order is by demand on the operator, not alphabetical and not by
     Issue number: what is stopped or waiting on a decision comes before what
     is merely running, which comes before what has not started. */
  var ORDER = ["blocked", "decision", "review", "running", "ready", "inbox", "unknown", "done"];

  function groupMissions(list) {
    var groups = {};
    (list || []).forEach(function (x) {
      if (!x || x.id === "all") return;
      var st = missionState(x);
      (groups[st.key] = groups[st.key] || { state: st, items: [] }).items.push(x);
    });
    return ORDER.filter(function (k) { return groups[k] && groups[k].items.length; })
      .map(function (k) { return groups[k]; });
  }

  /* ---- rendering ------------------------------------------------------ */

  function missionRow(x) {
    var st = missionState(x);
    return '<button type="button" class="mission-row" data-mission-open="' + esc(x.id) + '"' +
      ' data-mission-state="' + esc(st.key) + '">' +
      '<span class="mission-dot ' + esc(st.tone) + '" aria-hidden="true"></span>' +
      '<span class="mission-main">' +
        '<span class="mission-title">' + esc(x.title || x.id) + "</span>" +
        '<span class="mission-sub">' + esc(x.id) + " · " + esc(st.label) + "</span>" +
      "</span>" +
      '<span class="mission-go" aria-hidden="true">Open →</span>' +
      "</button>";
  }

  function sourceLine(s) {
    var m = (s && s.model) || {};
    if (m.synthetic) {
      return '<p class="mission-source">Preview · deterministic sample data. ' +
        "No live record is being read and nothing can be started.</p>";
    }
    var repo = m.repo || "the configured repository";
    var status = m.status || "unknown";
    /* Freshness is stated, never assumed. An operator deciding what to work on
       deserves to know whether the list in front of them is current. */
    var when = status === "fresh"
      ? "read live"
      : (status === "unavailable"
        ? "could not be read — this list may be incomplete or empty"
        : "read with status " + status);
    return '<p class="mission-source">Missions are the open Issues in <code>' + esc(repo) +
      "</code>, " + esc(when) + ". The Issue is the record: its mandate, approval and limits " +
      "are what the launcher and the Evidence Gate read.</p>";
  }

  function newMissionUrl(s) {
    var m = (s && s.model) || {};
    if (m.synthetic || !m.repo) return null;
    return "https://github.com/" + String(m.repo) + "/issues/new";
  }

  function renderStart(winEl, ctx) {
    if (!winEl) return;
    var s = (ctx && ctx.state) || {};
    var list = ((s.model && s.model.workstreams) || []).filter(function (x) {
      return x && x.id && x.id !== "all";
    });
    var groups = groupMissions(list);

    var html = '<div class="mission-inner" data-start-mission>' +
      '<span class="eyebrow">Start</span>' +
      "<h1 class=\"mission-heading\">Start a mission</h1>" +
      '<p class="mission-lede">A mission is one piece of work the OS can carry from ' +
        "an approved mandate through an isolated run to a reviewable result. " +
        "Pick one to work on, or open a mission that already needs you.</p>" +
      sourceLine(s);

    if (!groups.length) {
      html += '<div class="empty-state">No missions could be read. Nothing is offered to start.</div>';
    }

    groups.forEach(function (g) {
      html += '<section class="mission-group" data-mission-group="' + esc(g.state.key) + '">' +
        '<h3><span class="mission-dot ' + esc(g.state.tone) + '" aria-hidden="true"></span>' +
        esc(g.state.label) + ' <small>' + esc(String(g.items.length)) + "</small></h3>" +
        '<p class="mission-meaning">' + esc(g.state.meaning) + " " + esc(g.state.next) + "</p>" +
        g.items.map(missionRow).join("") +
        "</section>";
    });

    /* The honest ending: there is no browser-side mission creation, and
       pretending otherwise is what the dead button did. The record lives in
       the tracker, so the control goes there -- and it goes there for real. */
    var url = newMissionUrl(s);
    html += '<section class="mission-group mission-new"><h3>Nothing here yet?</h3>' +
      '<p class="mission-meaning">A new mission starts as a new Issue. The OS reads it ' +
      "from there; it does not keep a separate list of its own. Once the Issue carries an " +
      "approved mandate and its limits, it appears above as ready to start.</p>" +
      (url
        ? '<button type="button" class="chrome-button" data-mission-new="' + esc(url) + '">' +
          "Open the tracker to write one →</button>"
        : '<p class="mission-meaning">No repository is bound in this mode, so no tracker can be opened.</p>') +
      "</section></div>";

    winEl.innerHTML = html;

    var qa = function (sel) { return Array.prototype.slice.call(winEl.querySelectorAll(sel)); };
    qa("[data-mission-open]").forEach(function (b) {
      b.addEventListener("click", function () {
        var handlers = global.ShellCommandHandlers;
        if (!handlers) return;
        /* Route through the shell's own typed command handlers rather than
           reaching into its state: `switch-workstream` already validates that
           the id is one the shell knows, so an id from a stale render cannot
           select something that no longer exists. */
        handlers["switch-workstream"]({ workstreamId: b.dataset.missionOpen });
        handlers["open-app"]({ appId: "work" });
      });
    });
    qa("[data-mission-new]").forEach(function (b) {
      b.addEventListener("click", function () {
        var handlers = global.ShellCommandHandlers;
        if (handlers && handlers["open-external"]) {
          handlers["open-external"]({ url: b.dataset.missionNew });
        }
      });
    });
  }

  var api = {
    missionState: missionState,
    groupMissions: groupMissions,
    STATES: STATES,
    UNKNOWN: UNKNOWN,
    DECISION: DECISION,
    render: renderStart,
  };
  if (typeof module === "object" && module.exports) module.exports = api;
  global.MissionState = api;
  if (typeof global.OSRenderer !== "undefined") {
    global.OSRenderer.register("start", renderStart);
  }
})(typeof window !== "undefined" ? window : globalThis);
