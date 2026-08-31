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
  function recoveryAvailable(s, x) {
    return !!s && !!s.model && !s.model.synthetic && hasAction(s, "recover-to-ready") &&
      !!x && x.workflow === "in-progress";
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
    if (!recoveryAvailable(s, x)) return "";
    return '<section class="review-actions" data-recover-section>' +
      "<p>This Workstream holds a <b>workflow:in-progress</b> claim. If its Run failed or stranded, return it to ready so a fresh Run can be approved.</p>" +
      '<button data-r-recover class="chrome-button">Return to ready (recover)</button></section>';
  }

  /* ---- Decisions ----------------------------------------------------- */
  function renderDecisions(winEl, ctx) {
    if (!winEl) return;
    var s = (ctx && ctx.state) || {}, x = (ctx && ctx.workstream) || null;
    if (!x) { winEl.innerHTML = empty("Select a Workstream to project its pending decision."); return; }
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

  /* ---- Evidence ------------------------------------------------------ */
  function renderEvidence(winEl, ctx) {
    if (!winEl) return;
    var x = (ctx && ctx.workstream) || null;
    if (!x) { winEl.innerHTML = empty("Select a Workstream to project its evidence."); return; }
    if (!x.evidence || !x.evidence.length) { winEl.innerHTML = empty("No authoritative evidence is attached."); return; }
    winEl.innerHTML =
      '<span class="eyebrow">' + esc(x.id) + "</span><h3>Evidence</h3>" +
      '<div class="projection-list">' + x.evidence.map(function (ev) {
        return '<article><span class="eyebrow">' + esc(ev.status) + "</span><strong>" + esc(ev.title) + "</strong><p>" + esc(ev.detail) + "</p></article>";
      }).join("") + "</div>";
  }

  if (typeof OSRenderer !== "undefined") {
    OSRenderer.register("decisions", renderDecisions);
    OSRenderer.register("evidence", renderEvidence);
  }
})();
