/* "Start a mission" — the entry step of the Work flow (#469 UX pass).

   Why this app exists
   -------------------
   Every "New Workstream" control in the shell emitted
   `OSRenderer.emit("command", {command:"create-workstream"})`, and nothing
   anywhere subscribed to the `command` event. Three data attributes across
   four call sites, on two surfaces, did nothing at all when clicked. The flow the operator is supposed to walk --
   start a mission, understand its terms, launch it, follow it, review it --
   had no first step.

   This app is that first step, and it is deliberately NOT a new mission
   store. A mission in Cortxt IS a GitHub Issue: the Issue holds the mandate,
   the approval, the limits and the artifact policy that the launcher and the
   Evidence Gate read. Inventing a browser-side "mission" object would create a
   second source of truth that no gate honours. So this app does these honest
   things:

     1. It projects the missions that actually exist -- the same
        `/api/workstreams` projection the shell already loads -- grouped by
        what the operator can do with each one now, in the operator's language.
     2. For a mission that does not exist yet, it can now COMPOSE one (#619):
        where the shell's action host has registered `issue-create` and the
        model is live, the operator writes the Issue here -- repo, title,
        body, labels -- and the app POSTs the confirmed form contents to
        `api/action` with the shell's action token. Where that authority is
        absent, it still says plainly that the record is an Issue and opens
        the tracker. Both are real, working actions; neither silently drops
        the click.
     3. For a mission that already exists, it can PREVIEW its terms (#619):
        the same authoritative `dispatch.request.v2` the launch app confirms
        against, fetched for the row's own Issue and rendered read-only --
        eligibility, what is missing, engine, routing reason, task tags and
        execution profile revision. The approval facts are NOT on that
        document (the v2 schema binds the approval_reference only); they are
        read from the `/api/workstreams` projection's authority block -- the
        same projection this app lists missions from -- so the rows show the
        actually recorded approval instead of a permanent "not recorded".
        The preview starts
        nothing: no confirm dialog, no action POST. Starting stays in the
        launch step behind its operator-gated confirmation.
     4. For a mission still at workflow:inbox (#619), it can perform the one
        label write this surface can reach -- marking the Issue ready --
        behind the same operator-gated confirmation the recovery action uses
        in the Work shell: an explained dialog, a required approval
        reference, explicit confirmation, and an honest rendering of any
        denial. Being ready is not dispatch approval: the mandate, limits
        and go decision are still confirmed in the launch step, and this
        starts no Run.

   The status vocabulary lives here (`MissionState`) because it is shared: Home
   and Work render the same words for the same state, so an operator never has
   to learn that "review" on one surface and "Ready for your review" on another
   are the same thing.
*/
(function (global) {
  "use strict";

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>\"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* Same grid row the launch renderer renders its dispatch request with, so
     the preview panel reads as the same document the launch step will
     confirm. */
  function row(key, value) {
    return '<div class="launch-row"><span class="launch-key">' + esc(key) +
      '</span><span class="launch-value">' + esc(value == null || value === "" ? "—" : value) + "</span></div>";
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

  /* ---- compose: the one real mutation this app owns (#619) ------------- */

  /* Compose is a REAL mutation: it is offered only where the shell's action
     host has registered `issue-create` and the model is live. The same
     fail-closed split as launchAvailable/recoveryAvailable in the Work shell:
     synthetic and preview data authorize nothing, and a host without the
     registered capability gets the tracker link instead -- never a control
     that can only fail. */
  function composeAvailable(s) {
    return !!s && !!s.model && !s.model.synthetic &&
      (s.capabilities || []).some(function (a) { return a && a.id === "issue-create"; });
  }

  /* Total by construction: the POSTed mandate is exactly the confirmed form
     contents -- trimmed, labels split on commas with empties dropped --
     wrapped as an issue-create action with explicit confirmation. Nothing
     browser-side widens it, and nothing else is sent. Exported so the
     payload shape is exercised, not grepped. */
  function composePayload(input) {
    var i = input || {};
    var labels = Array.isArray(i.labels)
      ? i.labels
      : String(i.labels == null ? "" : i.labels).split(",");
    return {
      action_id: "issue-create",
      mandate: {
        repo: String(i.repo == null ? "" : i.repo).trim(),
        title: String(i.title == null ? "" : i.title).trim(),
        body: String(i.body == null ? "" : i.body),
        labels: labels.map(function (l) { return String(l).trim(); })
                      .filter(function (l) { return !!l; }),
      },
      confirm: true,
    };
  }

  function composeForm(model) {
    var repo = (model && model.repo) || "";
    return '<form data-mission-compose-form>' +
      "<label>Repository" +
      '<input name="repo" data-mission-compose-repo value="' + esc(repo) +
      '" placeholder="owner/repo" required></label>' +
      "<label>Title" +
      '<input name="title" data-mission-compose-title placeholder="What this mission is, in one line" required></label>' +
      "<label>Body" +
      '<textarea name="body" data-mission-compose-body rows="5" ' +
      'placeholder="Outcome, scope, acceptance criteria — the mandate the OS will read."></textarea></label>' +
      "<label>Labels" +
      '<input name="labels" data-mission-compose-labels placeholder="comma,separated"></label>' +
      '<div data-mission-compose-error role="alert"></div>' +
      '<button type="submit" class="chrome-button" data-mission-compose-submit>Write the Issue →</button>' +
      "</form>";
  }

  function submitCompose(form, s) {
    var errEl = form.querySelector("[data-mission-compose-error]");
    var fail = function (message) { if (errEl) errEl.textContent = message; };
    var payload = composePayload({
      repo: (form.querySelector("[data-mission-compose-repo]") || {}).value,
      title: (form.querySelector("[data-mission-compose-title]") || {}).value,
      body: (form.querySelector("[data-mission-compose-body]") || {}).value,
      labels: (form.querySelector("[data-mission-compose-labels]") || {}).value,
    });
    if (!payload.mandate.repo || !payload.mandate.title) {
      fail("A repository and a title are required before anything is written.");
      return;
    }
    fail("");
    fetch("api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Cortxt-Token": s.token },
      body: JSON.stringify(payload),
    })
      .then(function (r) {
        return r.json().then(function (data) { return { ok: r.ok, data: data }; });
      })
      .then(function (res) {
        if (!res.ok) {
          var err = (res.data && res.data.error) || {};
          throw new Error((err.recovery || err.message) || "The Issue was not written.");
        }
        /* Show only what the host actually returned: a link when the result
           carries one, never an invented Issue number -- the Issue in the
           tracker is the record, not this panel. */
        var result = (res.data && res.data.result) || {};
        var link = result.issue_url || result.url || null;
        form.innerHTML = '<p class="mission-meaning" data-mission-compose-created>' +
          "The Issue was written to <code>" + esc(payload.mandate.repo) + "</code>. " +
          "Once it carries an approved mandate and its limits, it appears above " +
          "as ready to start." +
          (link ? ' <a href="' + esc(link) + '" target="_blank" rel="noopener">Open it →</a>' : "") +
          "</p>";
      })
      .catch(function (error) {
        fail(error && error.message ? error.message : "The Issue was not written.");
      });
  }

  /* ---- mark-ready: the one label write this surface can reach (#619) --- */

  /* A mission sitting at workflow:inbox has a captured Issue but no approved
     mandate yet, so the only real action the operator can perform on it
     from here is the promotion itself: `workflow:inbox` -> `workflow:ready`.
     That is the ONLY label write in the product, and `workflow:ready` is
     what the launch step reads before it will offer a start control at all
     -- so it crosses the same operator gate as the recovery action in the
     Work shell: an explained dialog, a required approval reference,
     explicit confirmation, and an honest rendering of any denial. The same
     fail-closed split as compose: offered only on a live host that has
     registered the `mark-ready` action, for a mission whose state the OS
     can actually read as inbox and which carries an Issue. A synthetic
     fixture may grant `view:prepare` -- navigation -- but preview data
     authorizes no mutation, so the control is never offered there. */
  function readyAvailable(s, x) {
    if (!s || !s.model || s.model.synthetic || !x || !x.issue_id) return false;
    return String(x.workflow || "").replace(/^workflow:/, "") === "inbox" &&
      (s.capabilities || []).some(function (a) { return a && a.id === "mark-ready"; });
  }

  /* Total by construction: exactly the operator's confirmed transition --
     the selected Issue, the typed approval reference, explicit
     confirmation. `approval_ref` is the field name the action host's
     request schema requires. Exported so the payload shape is exercised,
     not grepped. */
  function markReadyPayload(x, approval) {
    return {
      action_id: "mark-ready",
      issue_id: String((x && x.issue_id) == null ? "" : x.issue_id),
      approval_ref: String(approval == null ? "" : approval).trim(),
      confirm: true,
    };
  }

  /* The confirmation dialog, mirroring `beginRecovery` in
     app-renderer-decisions-evidence.js field for field: a modal <dialog>,
     the reviewed-action-boundary explanation, a REQUIRED approval reference
     (refused client-side when empty), and `confirm: true` on the POST. */
  function beginMarkReady(x, s) {
    var dlg = document.createElement("dialog");
    dlg.innerHTML =
      '<form method="dialog"><p class="eyebrow">Reviewed action boundary</p><h2>Mark this mission ready</h2>' +
      "<p>This moves the Issue from <b>workflow:inbox</b> to <b>workflow:ready</b> -- the only label write this surface can perform -- so the launch step will offer to start it. " +
      "Being ready is not dispatch approval: the mandate, the limits and the go decision are confirmed in the launch step, and this starts no Run.</p>" +
      '<label>Approval reference<input data-m-ready-approval required autocomplete="off" placeholder="Operator approval record"></label>' +
      '<div data-m-ready-error role="alert"></div><footer><button value="cancel">Cancel</button>' +
      '<button value="confirm" class="primary-action">Confirm ready</button></footer></form>';
    document.body.appendChild(dlg);
    dlg.showModal();
    dlg.addEventListener("close", function () {
      if (dlg.returnValue !== "confirm") { dlg.remove(); return; }
      var approval = dlg.querySelector("[data-m-ready-approval]").value.trim();
      if (!approval) { dlg.querySelector("[data-m-ready-error]").textContent = "Approval reference is required."; dlg.showModal(); return; }
      fetch("api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Cortxt-Token": s.token },
        body: JSON.stringify(markReadyPayload(x, approval)),
      })
        .then(function (r) {
          return r.json().then(function (data) { return { ok: r.ok, data: data }; });
        })
        .then(function (res) {
          if (!res.ok) {
            /* TransitionDenied and 409 land here: the port's own recovery
               text is shown, never softened into a success. */
            var err = (res.data && res.data.error) || {};
            throw new Error((err.recovery || err.message) || "The transition was denied.");
          }
          /* The dialog stays open with the outcome: the label write is the
             whole effect, and the next decision -- starting the mission --
             remains a separate, confirmed decision in the launch step. */
          dlg.querySelector("form").innerHTML =
            '<p class="mission-meaning" data-m-ready-done>The Issue is now <b>workflow:ready</b>. ' +
            "Starting it remains a separate, confirmed decision in the launch step.</p>";
        })
        .catch(function (error) {
          /* The refusal is shown, never hidden: whatever the host answered
             -- a denial, a 409, a network failure -- the operator sees it
             in the dialog they confirmed from. */
          dlg.querySelector("[data-m-ready-error]").textContent =
            (error && error.message) ? error.message : "The transition was denied.";
          dlg.showModal();
        });
    });
  }

  function readyButton(x, s) {
    if (!readyAvailable(s, x)) return "";
    return '<button type="button" class="chrome-button" data-mission-ready="' +
      esc(x.issue_id) + '">Mark ready for dispatch…</button>';
  }

  /* ---- preview: read-only terms for a mission that already exists (#619) */

  /* Offered for any mission carrying an Issue on a live host -- knowing what
     a mission is missing is most useful exactly when it is not yet startable.
     Never offered in synthetic mode: the static host has no api/ route, and a
     control that can only answer "unavailable" is a dead control. */
  function previewButton(x, synthetic) {
    if (!x || !x.issue_id || synthetic) return "";
    return '<button type="button" class="chrome-button" data-mission-preview="' +
      esc(x.issue_id) + '">Preview its terms →</button>';
  }

  /* The approval facts live on the `/api/workstreams` projection's
     authority block, not on the v2 dispatch-request document: that document
     binds the approval_reference only, so reading the two names from it is
     what always rendered "not recorded" for an approved mission (gate P2,
     #619). One extra read alongside the dispatch request; when the
     projection cannot be read, or this Issue is not on it (freshly
     composed, not yet listed), the rows fall back to the honest
     "not recorded" shape -- never an invented fact. */
  function authorityFor(projection, issue) {
    var list = (projection && projection.workstreams) || [];
    for (var i = 0; i < list.length; i++) {
      var x = list[i];
      if (x && x.issue_id === issue && x.authority) {
        return {
          approval_recorded: x.authority.approval_recorded,
          approval_source: x.authority.approval_source,
        };
      }
    }
    return null;
  }

  function loadPreview(winEl, issue) {
    var panel = winEl.querySelector("[data-mission-preview-panel]");
    if (!panel || !issue) return;
    panel.innerHTML = '<p class="mission-meaning">Reading the mission’s terms…</p>';
    fetch("api/dispatch-request?issue=" + encodeURIComponent(issue), { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("The mission’s dispatch request could not be read (" + r.status + ").");
        return r.json();
      })
      .then(function (req) {
        return fetch("api/workstreams", { cache: "no-store" })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (projection) { return { req: req, authority: authorityFor(projection, issue) }; })
          .catch(function () { return { req: req, authority: null }; });
      })
      .then(function (both) { renderPreview(panel, both.req, both.authority); })
      .catch(function (err) {
        panel.innerHTML = '<div class="empty-state">' +
          esc(err && err.message ? err.message : "The mission’s terms could not be read.") + "</div>";
      });
  }

  /* Field-for-field rendering of the server's dispatch request, the way
     renderRequest does in the launch app -- minus everything launch-shaped.
     The v2 payload carries no provider or model fields; the execution profile
     revision is the replaceable-execution fact it does carry, and nothing
     beyond it is invented here. The two approval rows are read from the
     workstream projection's authority block (see authorityFor), never from
     this document -- it carries neither field, and rendering them from it
     said "not recorded" even for an approved mission. With no authority
     available the rows render the honest absence shape: "not recorded" and
     no source. This panel starts nothing: no confirm dialog,
     no action POST -- starting stays in the launch step. */
  function renderPreview(panel, req, authority) {
    var r = req || {};
    var a = authority || {};
    var html = "<h3>Mission terms</h3>" +
      (r.eligible
        ? '<div class="launch-banner" data-preview-eligible>Eligible: the approved mandate is complete. Starting happens in the launch step, after your confirmation.</div>'
        : '<div class="launch-banner warn" data-preview-ineligible>Not startable yet: the approved mandate is incomplete.</div>') +
      '<div class="launch-grid">' +
      row("Issue", r.issue_id) +
      row("Engine", r.engine) +
      row("Routing reason", r.routing_reason) +
      row("Task tags", (r.routable_task_tags || []).join(", ")) +
      row("Execution profile", r.execution_profile_revision == null ? null : String(r.execution_profile_revision)) +
      row("Approval recorded", a.approval_recorded == null ? "not recorded" : (a.approval_recorded ? "yes" : "no")) +
      row("Approval source", a.approval_source) +
      "</div>";
    if (!r.eligible) {
      html += '<section class="launch-errors" data-preview-missing><h4>What is missing</h4>' +
        ((r.errors && r.errors.length)
          ? r.errors.map(function (e) {
              return '<article class="launch-error"><span class="eyebrow">' + esc(e.category || e.code) +
                "</span><strong>" + esc(e.code) + "</strong><p>" + esc(e.recovery || "") + "</p></article>";
            }).join("")
          : (r.missing || []).map(function (m) {
              return '<article class="launch-error"><strong>' + esc(m) + "</strong></article>";
            }).join("")) +
        "</section>";
    }
    panel.innerHTML = html;
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
    var synthetic = !!(s.model && s.model.synthetic);

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
        g.items.map(function (x) { return missionRow(x) + readyButton(x, s) + previewButton(x, synthetic); }).join("") +
        "</section>";
    });

    /* The read-only terms panel sits between the list and the compose form:
       the operator can read what a mission still needs without leaving the
       first step, and what they read is the same authoritative request the
       launch step will confirm against. Empty until a preview is asked for. */
    html += '<section class="mission-group" data-mission-preview-panel aria-live="polite"></section>';

    /* The honest ending, now with two real shapes (#619). Where the host has
       authorized issue-create, the mission is composed here and the POST
       writes the Issue to the tracker -- nowhere else. Where it has not, the
       record still lives in the tracker, so the control goes there -- and it
       goes there for real. Pretending either way is what the dead button
       did. */
    var url = newMissionUrl(s);
    html += '<section class="mission-group mission-new"><h3>Nothing here yet?</h3>' +
      '<p class="mission-meaning">A new mission starts as a new Issue. The OS reads it ' +
      "from there; it does not keep a separate list of its own. Once the Issue carries an " +
      "approved mandate and its limits, it appears above as ready to start.</p>" +
      (composeAvailable(s)
        ? '<p class="mission-meaning">This host has authorized writing Issues, so the mission ' +
          "can be composed here. The Issue is still the record: this writes it to the " +
          "tracker, nowhere else.</p>" + composeForm(s.model)
        : (url
          ? '<button type="button" class="chrome-button" data-mission-new="' + esc(url) + '">' +
            "Open the tracker to write one →</button>"
          : '<p class="mission-meaning">No repository is bound in this mode, so no tracker can be opened.</p>')) +
      "</section></div>";

    winEl.innerHTML = html;

    var qa = function (sel) { return Array.prototype.slice.call(winEl.querySelectorAll(sel)); };
    qa("[data-mission-open]").forEach(function (b) {
      b.addEventListener("click", function () {
        var handlers = global.ShellCommandHandlers;
        if (!handlers) return;
        /* Route through the shell's own typed command handlers rather than
           reaching into its state. `switch-workstream` validates the id and
           fails closed on one it does not know -- but it fails closed
           SILENTLY, and `open-app` would then land the operator in Work
           looking at whatever was selected before, believing this row opened.
           `s` is the shell's live state object, so re-reading it here is a
           check against the current projection, not the one this render saw.
           A row whose mission is gone re-renders the list instead of
           navigating to the wrong one. */
        var id = b.dataset.missionOpen;
        var current = (s.model && s.model.workstreams) || [];
        var known = current.some(function (w) { return w && w.id === id; });
        if (!known) { renderStart(winEl, ctx); return; }
        handlers["switch-workstream"]({ workstreamId: id });
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
    qa("[data-mission-preview]").forEach(function (b) {
      b.addEventListener("click", function () {
        loadPreview(winEl, b.dataset.missionPreview);
      });
    });
    qa("[data-mission-ready]").forEach(function (b) {
      b.addEventListener("click", function () {
        var id = b.dataset.missionReady;
        var x = ((s.model && s.model.workstreams) || []).filter(function (w) {
          return w && w.issue_id === id;
        })[0];
        if (!x) { renderStart(winEl, ctx); return; }
        beginMarkReady(x, s);
      });
    });
    qa("[data-mission-compose-form]").forEach(function (form) {
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        submitCompose(form, s);
      });
    });
  }

  var api = {
    missionState: missionState,
    groupMissions: groupMissions,
    STATES: STATES,
    UNKNOWN: UNKNOWN,
    DECISION: DECISION,
    composeAvailable: composeAvailable,
    composePayload: composePayload,
    readyAvailable: readyAvailable,
    markReadyPayload: markReadyPayload,
    loadPreview: loadPreview,
    renderPreview: renderPreview,
    render: renderStart,
  };
  if (typeof module === "object" && module.exports) module.exports = api;
  global.MissionState = api;
  if (typeof global.OSRenderer !== "undefined") {
    global.OSRenderer.register("start", renderStart);
  }
})(typeof window !== "undefined" ? window : globalThis);
