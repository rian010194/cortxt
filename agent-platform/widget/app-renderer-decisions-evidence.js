/* Distinct Decisions and Evidence app renderers (issue #427).
   Registered into the shared OSRenderer registry so each app renders its own
   authority-aware surface instead of a generic projection.

   Decisions: pending decision for the selected Workstream plus its evidence
   context, with a fail-closed record-decision action. No mutation happens
   without a reviewed authority (approval reference) AND explicit
   confirmation; synthetic mode always previews and never calls the action
   port. The confirmation dialog is created locally per window so it never
   collides with the shell's own confirm dialog.

   Evidence: attributable evidence for the selected Workstream (statuses such
   as accepted/complete/passed are shown), read-only.

   Both read only from the shell-owned Workstream context (ctx.workstream) and
   shell state (ctx.state) — they never fork or mutate domain state.
*/
(function () {
  "use strict";
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function empty(m) { return '<div class="empty-state">' + esc(m) + "</div>"; }

  function hasAction(s, id) {
    return ((s && s.capabilities) || []).some(function (a) { return a && a.id === id; });
  }

  /* ---- Recovery: the one sanctioned way back from in-progress ---------
     S7d (#472 finding 2): a Run that failed or stranded left its Issue at
     workflow:in-progress with no actuator, so recovery meant a manual
     `gh issue edit` outside the action ports. This is the same fail-closed
     shape as the decision action (approval reference + explicit confirm
     before the port is called), bound to the exact selected Workstream. It
     approves, closes, and completes nothing, and it starts no Run: it
     re-opens the dispatch gate so a fresh Run is a separate decision. */
  /* Preview navigation authority is not mutation authority (S7d browser
     acceptance): a synthetic fixture may grant `view:recovery` so the
     explanation is reachable, but it never grants act:recover-to-ready, a
     token, or an endpoint. */
  function viewAuthorized(x, capability) {
    return !!x && ((x && x.view_capabilities) || []).indexOf(capability) !== -1;
  }
  function isSynthetic(s) { return !!(s && s.model && s.model.synthetic); }

  /* Every projection must belong to the selected Workstream: its Run and
     evidence references must carry the same Issue, or the surface fails
     closed rather than relabelling another Workstream's data. */
  function correlated(x) {
    if (!x || !x.issue_id) return false;
    var runs = x.runs || [], evidence = x.evidence || [];
    for (var i = 0; i < runs.length; i++) {
      if (runs[i] && runs[i].issue_id && runs[i].issue_id !== x.issue_id) return false;
    }
    for (var j = 0; j < evidence.length; j++) {
      if (evidence[j] && evidence[j].issue_id && evidence[j].issue_id !== x.issue_id) return false;
    }
    return true;
  }

  function recoveryVisible(s, x) {
    if (!s || !s.model || !x) return false;
    if (!correlated(x) || x.workflow !== "in-progress") return false;
    return isSynthetic(s) ? viewAuthorized(x, "view:recovery") : hasAction(s, "recover-to-ready");
  }
  function recoveryExecutable(s, x) {
    return recoveryVisible(s, x) && !isSynthetic(s) && hasAction(s, "recover-to-ready");
  }

  function beginRecovery(winEl, ctx) {
    var s = (ctx && ctx.state) || {}, x = (ctx && ctx.workstream) || {};
    var dlg = document.createElement("dialog");
    dlg.innerHTML =
      '<form method="dialog"><p class="eyebrow">Reviewed action boundary</p><h2>Return this Workstream to ready</h2>' +
      "<p>This moves the authoritative GitHub Issue from <b>workflow:in-progress</b> back to <b>workflow:ready</b> so a fresh Run can be approved. It does not approve, close, or complete any work, and it starts no Run.</p>" +
      '<label>Approval reference<input data-r-approval required autocomplete="off" placeholder="Operator approval record"></label>' +
      '<div data-r-error role="alert"></div><footer><button value="cancel">Cancel</button>' +
      '<button value="confirm" class="primary-action">Confirm recovery</button></footer></form>';
    document.body.appendChild(dlg);
    dlg.showModal();
    dlg.addEventListener("close", async function () {
      if (dlg.returnValue !== "confirm") { dlg.remove(); return; }
      var approval = dlg.querySelector("[data-r-approval]").value.trim();
      if (!approval) { dlg.querySelector("[data-r-error]").textContent = "Approval reference is required."; dlg.showModal(); return; }
      try {
        var response = await fetch("api/action", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Cortxt-Token": s.token },
          body: JSON.stringify({ action_id: "recover-to-ready", issue_id: x.issue_id, approval_ref: approval, confirm: true }),
        });
        var result = await response.json();
        if (!response.ok) throw new Error((result.error && (result.error.recovery || result.error.message)) || "Recovery was denied");
        winEl.innerHTML = '<span class="eyebrow">Recovered</span><h3>Returned to workflow:ready</h3><p>' + esc(approval) + "</p>";
        if (window.CortxtShell && window.CortxtShell.refreshAuthority) window.CortxtShell.refreshAuthority();
      } catch (error) {
        dlg.querySelector("[data-r-error]").textContent = error.message;
        dlg.showModal();
        return;
      }
      dlg.remove();
    });
  }

  function recoverySection(s, x) {
    if (!recoveryVisible(s, x)) return "";
    var intro = '<section class="review-actions" data-recover-section>' +
      "<p>This Workstream holds a <b>workflow:in-progress</b> claim. If its Run failed or stranded, return it to ready so a fresh Run can be approved. " +
      "Recovery re-opens the dispatch gate only: it approves, closes and completes nothing, and starts no Run.</p>";
    if (!recoveryExecutable(s, x)) {
      /* Reachable explanation, inert control: no handler is bound and the
         static host has no /api/action route to call. */
      return intro + '<button data-r-recover-disabled class="chrome-button" disabled aria-disabled="true">Requires live action host</button>' +
        "<small>This preview is non-mutating. Returning the Issue to ready requires a live action host with the registered recover-to-ready capability.</small></section>";
    }
    return intro + '<button data-r-recover class="chrome-button">Return to ready (recover)</button></section>';
  }

  /* ---- Decisions ----------------------------------------------------- */
  function renderDecisions(winEl, ctx) {
    if (!winEl) return;
    var s = (ctx && ctx.state) || {}, x = (ctx && ctx.workstream) || null;
    if (!x) { winEl.innerHTML = empty("Select a Workstream to project its pending decision."); return; }
    if (!correlated(x)) {
      winEl.innerHTML = empty(
        "This Workstream's Issue, Run, and evidence references do not correlate. " +
        "No decision candidate is rendered and no action is offered.");
      return;
    }
    var decision = x.decision;
    winEl.innerHTML =
      '<span class="eyebrow">' + esc(x.id) + " · human decision</span><h3>" + esc(x.title) + "</h3>" +
      "<p>" + (decision ? esc(decision.summary) : "No authoritative decision is pending for this Workstream.") + "</p>" +
      (x.evidence && x.evidence.length
        ? '<div class="projection-list">' + x.evidence.map(function (ev) {
            return '<article><span class="eyebrow">' + esc(ev.status) + "</span><strong>" + esc(ev.title) + "</strong><p>" + esc(ev.detail) + "</p></article>";
          }).join("") + "</div>"
        : "") +
      (decision
        ? '<div class="review-actions"><button data-d-accept class="primary-action">' +
            ((s.model && s.model.synthetic) ? "Preview acceptance" : "Accept record") +
          "</button></div><small>" +
          ((s.model && s.model.synthetic)
            ? "Preview outcome stays in this browser."
            : "Mutation requires an approval reference and explicit confirmation.") +
          "</small>"
        : "") +
      recoverySection(s, x);
    var accept = winEl.querySelector("[data-d-accept]");
    if (accept) accept.addEventListener("click", function () { beginDecision(winEl, ctx); });
    var recover = winEl.querySelector("[data-r-recover]");
    if (recover) recover.addEventListener("click", function () { beginRecovery(winEl, ctx); });
    /* #499: the decision is about a change the operator did not watch happen,
       so the change itself is rendered here, before the accept control. */
    if (!isSynthetic(s) && x.issue_id) attachRunDiff(winEl, x);
  }

  function beginDecision(winEl, ctx) {
    var s = (ctx && ctx.state) || {}, x = (ctx && ctx.workstream) || {};
    if (s.model && s.model.synthetic) { previewDecision(winEl, ctx); return; }
    /* Fail closed: local dialog requiring an approval reference and an
       explicit confirm before the action port is ever called. */
    var dlg = document.createElement("dialog");
    dlg.innerHTML =
      '<form method="dialog"><p class="eyebrow">Reviewed action boundary</p><h2>Confirm durable decision</h2>' +
      "<p>This moves the authoritative GitHub Issue from <b>workflow:review</b> to <b>workflow:done</b>. It does not authorize new scope.</p>" +
      '<label>Approval reference<input data-d-approval required autocomplete="off" placeholder="Operator approval record"></label>' +
      '<div data-d-error role="alert"></div><footer><button value="cancel">Cancel</button>' +
      '<button value="confirm" class="primary-action">Confirm and accept</button></footer></form>';
    document.body.appendChild(dlg);
    dlg.showModal();
    dlg.addEventListener("close", async function () {
      if (dlg.returnValue !== "confirm") { dlg.remove(); return; }
      var approval = dlg.querySelector("[data-d-approval]").value.trim();
      if (!approval) { dlg.querySelector("[data-d-error]").textContent = "Approval reference is required."; dlg.showModal(); return; }
      try {
        var response = await fetch("api/action", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Cortxt-Token": s.token },
          body: JSON.stringify({ action_id: "record-decision", issue_id: x.issue_id, approval_ref: approval, confirm: true }),
        });
        var result = await response.json();
        if (!response.ok) throw new Error((result.error && result.error.message) || "Decision was denied");
        winEl.innerHTML = '<span class="eyebrow">Recorded</span><h3>Decision accepted</h3><p>' + esc(approval) + "</p>";
      } catch (error) {
        dlg.querySelector("[data-d-error]").textContent = error.message;
        dlg.showModal();
        return;
      }
      dlg.remove();
    });
  }

  function previewDecision(winEl, ctx) {
    var x = (ctx && ctx.workstream) || {};
    winEl.innerHTML = '<span class="eyebrow">Preview outcome</span><h3>Accepted (preview)</h3><p>' + esc(x.title) + " — no external mutation was performed.</p>";
  }

  /* ---- The change itself (#499) --------------------------------------
     The closing step of S7 is a decision about work the operator did not
     watch happen. A SHA, a file list and a correlation receipt are not that
     work, so this panel renders the contributed diff read-only, from
     `GET /api/run-diff`.

     Nothing here can widen what is shown. The request carries only the Issue
     and the Run; the server resolves commit, branch and worktree from the
     durable evidence record the Evidence Gate wrote, and returns a patch only
     for a file that gate correlated inside the approved artifact policy. A
     withheld file is rendered as its reason with no content, and an
     unavailable diff renders its reason -- never as an empty change.

     WHICH Run is never guessed silently. The projection is bound to an exact
     issue+run pair, and a decision surface that showed a different Run's diff
     than the one being decided would be worse than showing none. So the Run
     is always named in the panel, and when the Workstream has more than one
     the operator picks it explicitly. Selection is local presentation state:
     it opens no port and changes no authority. */
  function runLabel(r) {
    var when = r.finished_at || r.started_at || r.heartbeat_at || null;
    return r.run_id + (r.status ? " · " + r.status : "") + (when ? " · " + when : "");
  }

  function orderRuns(runs) {
    /* `finished_at`/`started_at` are nullable, so an unparsable date must sort
       last deterministically rather than becoming NaN and reordering the list
       arbitrarily on every render. */
    return runs.slice().map(function (r, i) {
      var t = Date.parse(r.finished_at || r.started_at || "");
      return { run: r, key: isNaN(t) ? -1 : t, i: i };
    }).sort(function (a, b) { return b.key - a.key || a.i - b.i; })
      .map(function (e) { return e.run; });
  }

  function attachRunDiff(winEl, x) {
    var existing = winEl.querySelector("[data-run-diff]");
    if (existing) existing.remove();
    var panel = document.createElement("section");
    panel.className = "run-diff";
    panel.setAttribute("data-run-diff", "loading");
    panel.innerHTML = "<h4>Contributed change</h4><p>Loading the change this Run contributed…</p>";
    winEl.appendChild(panel);

    fetch("api/runs?issue=" + encodeURIComponent(x.issue_id), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("run projection unavailable"); return r.json(); })
      .then(function (d) {
        /* Fail closed on correlation: only Runs the server reports against
           THIS Issue are offered. */
        var runs = orderRuns(((d && d.runs) || []).filter(function (r) {
          return r && r.run_id && (!r.issue_ref || r.issue_ref === x.issue_id);
        }));
        if (!runs.length) throw new Error("no correlated run");
        loadDiff(panel, x, runs, runs[0].run_id);
      })
      .catch(function (e) { diffUnavailable(panel, e && e.message ? e.message : "unavailable"); });
  }

  function loadDiff(panel, x, runs, runId) {
    var q = "issue=" + encodeURIComponent(x.issue_id) + "&run=" + encodeURIComponent(runId);
    fetch("api/run-diff?" + q, { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("this Run has no readable change (" + r.status + ")");
        return r.json();
      })
      .then(function (diff) { renderRunDiff(panel, x, runs, runId, diff); })
      .catch(function (e) {
        diffUnavailable(panel, e && e.message ? e.message : "unavailable",
                        runPicker(runs, runId));
      });
  }

  function diffUnavailable(panel, message, picker) {
    panel.setAttribute("data-run-diff", "unavailable");
    panel.innerHTML = "<h4>Contributed change</h4>" + (picker || "") +
      '<p class="run-live-warn">' + esc(message) +
      " — nothing is shown. Deciding on metadata alone is your call, not this surface's.</p>";
  }

  function runPicker(runs, runId) {
    if (runs.length < 2) {
      return '<p class="run-diff-run">Run <b>' + esc(runId) + "</b></p>";
    }
    return '<label class="run-diff-run">Run <select data-run-diff-pick>' +
      runs.map(function (r) {
        return '<option value="' + esc(r.run_id) + '"' +
          (r.run_id === runId ? " selected" : "") + ">" + esc(runLabel(r)) + "</option>";
      }).join("") + "</select></label>";
  }

  function renderRunDiff(panel, x, runs, runId, diff) {
    var picker = runPicker(runs, runId);
    function bind() {
      var pick = panel.querySelector("[data-run-diff-pick]");
      if (pick) pick.addEventListener("change", function () { loadDiff(panel, x, runs, pick.value); });
    }
    if (!diff || diff.available !== true) {
      diffUnavailable(panel, "no readable change: " + ((diff && diff.reason) || "unknown"), picker);
      bind();
      return;
    }
    panel.setAttribute("data-run-diff", diff.run_id);
    var files = diff.files || [];
    var shown = files.filter(function (f) { return !f.withheld; });
    var held = files.filter(function (f) { return f.withheld; });
    var body;
    if (shown.length) {
      body = shown.map(function (f) {
        return "<article><strong>" + esc(f.path) + "</strong>" +
          '<pre class="run-diff-patch">' + esc(f.patch) + "</pre>" +
          (f.truncated ? '<p class="run-live-warn">Truncated — this file changed more than is shown.</p>' : "") +
          "</article>";
      }).join("");
    } else if (held.length) {
      body = '<p class="run-live-warn">Every changed file was withheld; there is nothing to read here.</p>';
    } else {
      /* Correlated, permitted, and empty: a real state that is neither a
         refusal nor a readable change, and must not be reported as either. */
      body = '<p class="run-live-warn">This Run recorded no changed file inside the approved artifact policy.</p>';
    }
    panel.innerHTML = "<h4>Contributed change</h4>" + picker +
      "<p>" + esc(diff.base_commit) + " … " + esc(diff.commit) +
      " on " + esc(diff.branch) + "</p>" + body +
      (held.length
        ? '<ul class="run-diff-withheld">' + held.map(function (f) {
            return "<li>" + esc(f.path) + " — withheld: " + esc(f.reason) + "</li>";
          }).join("") + "</ul>"
        : "");
    bind();
  }

  /* ---- Evidence ------------------------------------------------------ */
  function renderEvidence(winEl, ctx) {
    if (!winEl) return;
    var x = (ctx && ctx.workstream) || null;
    if (!x) { winEl.innerHTML = empty("Select a Workstream to project its evidence."); return; }
    if (!correlated(x)) {
      winEl.innerHTML = empty(
        "This Workstream's evidence references do not correlate with its Issue. Nothing is rendered.");
      return;
    }
    var items = x.evidence || [];
    winEl.innerHTML =
      '<span class="eyebrow">' + esc(x.id) + "</span><h3>Evidence</h3>" +
      (items.length ? "" : empty("No authoritative evidence is attached.")) +
      '<div class="projection-list">' + items.map(function (ev) {
        return '<article><span class="eyebrow">' + esc(ev.status) + "</span><strong>" + esc(ev.title) + "</strong><p>" + esc(ev.detail) + "</p></article>";
      }).join("") + "</div>";
    /* Synthetic mode reaches no host, so there is no Run whose change could
       be read; the metadata list above is all that exists there. */
    if (!isSynthetic(ctx && ctx.state) && x.issue_id) attachRunDiff(winEl, x);
  }

  if (typeof OSRenderer !== "undefined") {
    OSRenderer.register("decisions", renderDecisions);
    OSRenderer.register("evidence", renderEvidence);
  }
})();
