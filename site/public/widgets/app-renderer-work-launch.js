/* Review-and-start-Run renderer for the Work app (S7b, #471).
   Registered into the shared OSRenderer registry as app id "launch" and
   opened in context from the Work surface (data-launch-run) or from search.

   Authority contract (AC1/AC2/AC7):
   - The renderer renders ONLY the server-returned dispatch.request.v1
     (GET /api/dispatch-request?issue=owner/repo#N), never browser-entered
     scope or limits. The confirmation dialog binds to that immutable
     snapshot: approval_ref = request.approval_reference (server-derived,
     displayed read-only) and request_id = request.request_id (the digest
     the server re-validates at execution time). Browser-supplied values
     cannot widen scope or limits.
   - Synthetic/demo mode renders a deterministic, non-mutating preview from
     fixtures/dispatch-request.json: no confirm dialog, no action POST, and
     the static host has no /api/action route at all (AC7).
   - An ineligible request renders the server's structured errors with
     recovery guidance and no launch affordance (AC1/AC5).
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
    return (s && s.capabilities || []).some(function (a) { return a && a.id === id; });
  }
  function money(v) { return v == null ? "—" : "$" + String(v); }

  /* ---- byte-for-field rendering of the server dispatch request -------- */
  function renderRequest(winEl, ctx, req, live) {
    var s = (ctx && ctx.state) || {}, x = (ctx && ctx.workstream) || {};
    var synthetic = !!live === false;
    var html = '<span class="eyebrow">' + esc(x.id || req.issue_id) + " · review and start Run</span><h3>Approved dispatch request</h3>";
    if (synthetic) {
      html += '<div class="launch-banner">Preview · deterministic synthetic data · no action capability · nothing is dispatched</div>';
    } else if (!req.eligible) {
      html += '<div class="launch-banner warn">Not launchable: the approved mandate is incomplete.</div>';
    } else {
      html += '<div class="launch-banner">Eligible: authoritatively <b>workflow:ready</b> with a complete approved mandate.</div>';
    }
    html +=
      '<div class="launch-grid">' +
      row("Issue", req.issue_id) +
      row("Workflow", req.workflow + " · " + (req.workflow_labels || []).join(", ")) +
      row("Worker role", req.worker_role) +
      row("Workflow id", req.workflow_id) +
      row("Engine", req.engine) +
      row("Routing reason", req.routing_reason) +
      row("Engine policy", policyText(req.engine_policy)) +
      row("Max runtime", req.max_runtime_seconds == null ? "—" : String(req.max_runtime_seconds) + " seconds") +
      row("Max cost", money(req.max_cost_usd)) +
      row("Max parallel workers", req.max_parallel_workers == null ? "—" : String(req.max_parallel_workers)) +
      row("Delegation depth", req.delegation_depth == null ? "—" : String(req.delegation_depth)) +
      "</div>" +
      '<section class="launch-block"><h4>Scope</h4><p class="launch-scope">' + esc(req.scope) + "</p></section>" +
      '<section class="launch-block"><h4>Acceptance criteria</h4><ol class="launch-ac">' +
      (req.acceptance_criteria || []).map(function (ac) { return "<li>" + esc(ac) + "</li>"; }).join("") +
      "</ol></section>" +
      '<section class="launch-block"><h4>Artifact policy</h4><p class="launch-scope">' + esc(req.artifact_policy) + "</p></section>" +
      '<section class="launch-block"><h4>Approval and request snapshot</h4>' +
      '<p class="launch-ref">Approval reference: <code data-launch-approval>' + esc(req.approval_reference) + "</code></p>" +
      '<p class="launch-ref">Request snapshot: <code data-launch-request-id>' + esc(req.request_id) + "</code></p></section>";
    if (!synthetic && req.eligible) {
      html += '<div class="review-actions"><button type="button" class="primary-action" data-launch-start>Review and start Run →</button></div>' +
        "<small>Confirmation binds to the request snapshot and the server-derived approval reference above. Launching moves the Issue from workflow:ready to workflow:in-progress through the gated launcher.</small>";
    } else if (!synthetic && !req.eligible) {
      html += '<section class="launch-errors"><h4>What is missing</h4>' +
        (req.errors && req.errors.length
          ? req.errors.map(function (e) {
              return '<article class="launch-error"><span class="eyebrow">' + esc(e.category || e.code) + "</span><strong>" + esc(e.code) + "</strong><p>" + esc(e.recovery || "") + "</p></article>";
            }).join("")
          : (req.missing || []).map(function (m) { return '<article class="launch-error"><strong>' + esc(m) + "</strong></article>"; }).join("")) +
        "</section><small>Launch is not available until the authoritative Issue mandate is complete.</small>";
    } else if (synthetic) {
      html += "<small>This preview is deterministic and non-mutating; the demo host has no action port.</small>";
    }
    winEl.innerHTML = html;
    var start = winEl.querySelector("[data-launch-start]");
    if (start) start.addEventListener("click", function () { beginLaunch(winEl, ctx, req); });
  }

  function row(key, value) {
    return '<div class="launch-row"><span class="launch-key">' + esc(key) + "</span><span class=\"launch-value\">" + esc(value == null ? "—" : value) + "</span></div>";
  }

  function policyText(policy) {
    if (!policy) return "—";
    var bits = [];
    if (policy.approved_reliability) bits.push("reliability " + policy.approved_reliability);
    if (policy.approved_engine) bits.push("engine " + policy.approved_engine);
    return bits.join(" · ") || "—";
  }

  /* ---- data loading: live server request vs synthetic fixture -------- */
  function loadLive(winEl, ctx, issue) {
    fetch("api/dispatch-request?issue=" + encodeURIComponent(issue), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("dispatch request is unavailable (" + r.status + ")"); return r.json(); })
      .then(function (req) { renderRequest(winEl, ctx, req, true); })
      .catch(function (err) { winEl.innerHTML = empty(err.message); });
  }

  function loadSynthetic(winEl, ctx, issue) {
    fetch("fixtures/dispatch-request.json", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("synthetic dispatch request is unavailable"); return r.json(); })
      .then(function (req) { renderRequest(winEl, ctx, req, false); })
      .catch(function (err) { winEl.innerHTML = empty(err.message); });
  }

  /* ---- operator-gated confirmation dialog (AC2/AC8) ------------------ */
  function beginLaunch(winEl, ctx, req) {
    var s = (ctx && ctx.state) || {};
    /* Fail closed: the approval reference is server-derived and displayed
       read-only; the request snapshot id is bound verbatim; explicit
       confirmation is required before the action port is called. */
    var dlg = document.createElement("dialog");
    dlg.innerHTML =
      '<form method="dialog"><p class="eyebrow">Reviewed action boundary</p><h2>Confirm and start Run</h2>' +
      "<p>This claims the Issue through <b>workflow.claim-run.v1</b> and the execution-map-gated Work Launcher, and moves GitHub from <b>workflow:ready</b> to <b>workflow:in-progress</b>.</p>" +
      '<div class="launch-grid">' +
      row("Engine", req.engine) +
      row("Worker role", req.worker_role) +
      row("Max runtime", String(req.max_runtime_seconds) + " seconds") +
      row("Max cost", money(req.max_cost_usd)) +
      row("Max parallel workers", String(req.max_parallel_workers)) +
      row("Delegation depth", String(req.delegation_depth)) +
      "</div>" +
      '<p class="launch-ref">Approval reference: <code data-launch-approval>' + esc(req.approval_reference) + "</code></p>" +
      '<p class="launch-ref">Request snapshot: <code data-launch-request-id>' + esc(req.request_id) + "</code></p>" +
      '<label class="launch-check"><input type="checkbox" data-launch-confirm required> I confirm the exact dispatch request shown above and its approval reference.</label>' +
      '<div data-launch-error role="alert"></div><footer><button value="cancel">Cancel</button>' +
      '<button value="confirm" class="primary-action">Confirm and start Run</button></footer></form>';
    document.body.appendChild(dlg);
    dlg.showModal();
    dlg.addEventListener("close", async function () {
      if (dlg.returnValue !== "confirm") { dlg.remove(); return; }
      if (!dlg.querySelector("[data-launch-confirm]").checked) {
        dlg.querySelector("[data-launch-error]").textContent = "Explicit confirmation is required.";
        dlg.showModal(); return;
      }
      try {
        var response = await fetch("api/action", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Cortxt-Token": s.token },
          body: JSON.stringify({
            action_id: "claim-run",
            issue_id: req.issue_id,
            approval_ref: req.approval_reference,
            request_id: req.request_id,
            confirm: true,
          }),
        });
        var result = await response.json();
        if (!response.ok) {
          var err = (result && result.error) || {};
          throw new Error((err.recovery || err.message) || "Launch was denied");
        }
        var run = (result && result.result) || {};
        winEl.innerHTML = '<span class="eyebrow">Run started</span><h3>Claim and Run created</h3>' +
          '<p class="launch-ref">run_id: <code data-launch-run-id>' + esc(run.run_id) + "</code></p>" +
          '<p class="launch-ref">claim_id: <code>' + esc(run.claim_id) + "</code></p>" +
          '<p class="launch-ref">request snapshot: <code data-launch-request-id>' + esc(req.request_id) + "</code></p>" +
          "<small>The Issue moved to workflow:in-progress through the gated launcher.</small>";
      } catch (error) {
        dlg.querySelector("[data-launch-error]").textContent = error.message;
        dlg.showModal();
        return;
      }
      dlg.remove();
    });
  }

  function renderLaunch(winEl, ctx) {
    if (!winEl) return;
    var s = (ctx && ctx.state) || {}, x = (ctx && ctx.workstream) || null;
    if (!x) { winEl.innerHTML = empty("Select a Workstream to review and start a Run."); return; }
    winEl.innerHTML = '<span class="eyebrow">' + esc(x.id) + '</span><h3>Loading the approved dispatch request…</h3>';
    var issue = x.issue_id || ("owner/repo#" + (x.number || ""));
    if (s.model && s.model.synthetic) {
      loadSynthetic(winEl, ctx, issue);
    } else {
      loadLive(winEl, ctx, issue);
    }
  }

  if (typeof OSRenderer !== "undefined") {
    OSRenderer.register("launch", renderLaunch);
  }
})();
