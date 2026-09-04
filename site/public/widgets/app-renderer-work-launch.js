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

   S7c (#472) live Run panel:
   - After a Run is started (or when a live host is attached), a panel polls
     GET /api/run-freshness?issue=owner/repo#N every 5s while the Run is
     fresh/stale/stranded and STOPS at terminal (bounded frequency, AC1/AC3).
   - On terminal it reads GET /api/run-terminal and GET /api/run-activity for
     the exact run_id; both are content-free server projections (no prompts,
     reasoning, secrets, raw logs, or artifact bodies -- AC4/AC5). Missing
     cost renders as "unknown", never $0.
   - Reload re-attaches and restores state from the server projections, not
     from browser cache (every fetch is cache:"no-store", AC9).
   - Browser-evidence hooks: [data-run-live], [data-run-freshness],
     [data-run-status], [data-run-terminal], [data-run-activity].
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
    /* Correlation before rendering: the request must belong to the selected
       Workstream's Issue. The eyebrow used to read `x.id || req.issue_id`,
       which relabelled a global fixture with whatever Workstream happened to
       be selected -- a WS-042 heading over a #471 request. A mismatch now
       fails closed instead. */
    if (!x.issue_id || !req.issue_id || x.issue_id !== req.issue_id) {
      winEl.innerHTML = empty(
        "This dispatch request does not belong to the selected Workstream (" +
        String(x.id || "unknown") + " expects " + String(x.issue_id || "no Issue") +
        ", request carries " + String(req.issue_id || "no Issue") +
        "). Nothing is rendered and no launch is offered.");
      return;
    }
    var html = '<span class="eyebrow">' + esc(x.id) + " · review and start Run</span><h3>Approved dispatch request</h3>";
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
      // Isolation is part of the mandate the operator confirms: it decides
      // whether the worker gets its own worktree and work/<run_id> branch or
      // works in the shared checkout. It is server-derived from the approved
      // artifact policy and covered by request_id, so it is displayed, never
      // chosen here (#473).
      row("Isolation", req.isolation === "shared-checkout"
        ? "shared checkout (waived by the approved artifact policy)"
        : "own worktree and work/<run_id> branch") +
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
      /* The preview is navigable and shows where the mutation boundary sits,
         but the control is inert: disabled, never wired to a handler, and the
         static host has no /api/action route to reach even if it were. */
      html += '<div class="review-actions"><button type="button" class="primary-action" data-launch-start-disabled disabled aria-disabled="true">Requires live action host</button></div>' +
        "<small>This preview is deterministic and non-mutating; the demo host has no action port. " +
        "Starting a Run requires a live action host with the registered claim-run capability.</small>";
    }
    winEl.innerHTML = html;
    var start = winEl.querySelector("[data-launch-start]");
    if (start) start.addEventListener("click", function () { beginLaunch(winEl, ctx, req); });
    // AC9: on reload during a running or terminal Run, restore live state from
    // the server projections (never browser cache). Harmless when no Run
    // exists yet: freshness simply reports "fresh" with nothing to show.
    if (live) attachLiveRun(winEl, ctx, req.issue_id, null);
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
        attachLiveRun(winEl, ctx, req.issue_id, run.run_id || null);
      } catch (error) {
        dlg.querySelector("[data-launch-error]").textContent = error.message;
        dlg.showModal();
        return;
      }
      dlg.remove();
    });
  }

  /* ---- S7c live Run panel: bounded poll, stop at terminal ----------- */
  function attachLiveRun(winEl, ctx, issue, runId) {
    if (!winEl || !issue) return;
    if (typeof winEl._cortxtStopLiveRun === "function") winEl._cortxtStopLiveRun();
    var prior = winEl.querySelector("[data-run-live]");
    if (prior) prior.remove();
    var panel = document.createElement("section");
    panel.className = "launch-block run-live";
    panel.setAttribute("data-run-live", issue);
    winEl.appendChild(panel);
    var timer = null, stopped = false, failures = 0;
    var MAX_POLL_FAILURES = 3;
    function stop() { stopped = true; if (timer) { clearTimeout(timer); timer = null; } }
    winEl._cortxtStopLiveRun = stop;
    function schedule() { if (!stopped) timer = setTimeout(tick, 5000); }
    function renderFreshness(fx) {
      panel.innerHTML = "<h4>Live Run</h4>" +
        '<div class="run-live-row" data-run-status="' + esc(fx.status) + '">' +
        '<span class="run-badge" data-run-freshness="' + esc(fx.status) + '">' + esc(fx.status) + "</span>" +
        '<span class="run-live-age">signal age ' + esc(fx.age_seconds) + "s</span></div>" +
        (fx.status === "stranded_running"
          ? '<p class="run-live-warn">This claim reports running but has produced no signal. It may be stranded.</p>'
          : "");
    }
    function tick() {
      fetch("api/run-freshness?issue=" + encodeURIComponent(issue), { cache: "no-store" })
        .then(function (r) { if (!r.ok) throw new Error("freshness unavailable (" + r.status + ")"); return r.json(); })
        .then(function (fx) {
          failures = 0;
          renderFreshness(fx);
          /* Stop on any complete reading, not only `terminal`: an issue with
             no correlated Runs is reported `fresh` + `complete` and would
             otherwise be polled forever (it never becomes terminal). */
          if (fx.status === "terminal") { stop(); loadTerminal(); }
          else if (fx.complete === true) stop();
          else schedule();
        })
        .catch(function (e) {
          /* A permanent failure (missing route, host gone) must not be retried
             forever; give up after MAX_POLL_FAILURES and say so. */
          failures += 1;
          var giveUp = failures >= MAX_POLL_FAILURES;
          panel.innerHTML = '<h4>Live Run</h4><div class="run-live-error" data-run-status="error">' +
            esc(e.message) + (giveUp ? " — stopped after " + failures + " attempts" : "") + "</div>";
          if (giveUp) stop(); else schedule();
        });
    }
    function loadTerminal() {
      if (runId) { terminalAndActivity(); return; }
      fetch("api/runs?issue=" + encodeURIComponent(issue), { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          var runs = (d && d.runs) || [];
          if (runs.length) {
            runs = runs.slice().sort(function (a, b) {
              var at = Date.parse(a.finished_at || a.heartbeat_at || a.started_at || 0) || 0;
              var bt = Date.parse(b.finished_at || b.heartbeat_at || b.started_at || 0) || 0;
              return bt - at;
            });
            runId = runs[0].run_id;
          }
          terminalAndActivity();
        })
        .catch(function () { terminalAndActivity(); });
    }
    function terminalAndActivity() {
      if (!runId) { panel.innerHTML = '<h4>Live Run · terminal</h4><div class="run-live-error">no correlated run</div>'; return; }
      var q = "issue=" + encodeURIComponent(issue) + "&run=" + encodeURIComponent(runId);
      Promise.all([
        fetch("api/run-terminal?" + q, { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }),
        fetch("api/run-activity?" + q, { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }),
      ]).then(function (res) { renderTerminal(res[0], res[1]); })
        .catch(function (e) {
          panel.innerHTML = '<h4>Live Run · terminal</h4><div class="run-live-error" data-run-status="error">' +
            esc(e && e.message ? e.message : "terminal projection unavailable") + "</div>";
        });
    }
    /* The Evidence Gate's verdict and the commit it correlated (#499). Absence
       of a verdict is rendered as "not recorded", never as a pass: a Run that
       never reached the gate must not look like one the gate accepted. */
    function gateRows(term) {
    var gate = term.evidence_gate, ev = term.commit_evidence;
    var html = row("Evidence gate", gate ? gate.replace(/_/g, " ") : "not recorded");
    if (!ev) return html;
    return html + row("Commit", ev.commit) + row("Base", ev.base_commit) +
        row("Branch", ev.branch) +
        row("Contributed commits", (ev.contributed_commits || []).length) +
        row("Contributed files", (ev.contributed_files || []).join(", "));
  }

    function renderTerminal(term, act) {
      var html = "<h4>Live Run · terminal</h4>";
      if (term) {
        var costText = term.cost_status === "unknown"
          ? "unknown"
          : money(term.cost) + " (" + esc(term.cost_status) + ")";
        html += '<div data-run-terminal="' + esc(term.run_id) + '" data-run-status="' + esc(term.status) + '">' +
          row("Status", term.status) + row("Engine", term.engine) +
          row("Provider", term.provider) + row("Model", term.model) +
          row("Cost", costText) +
          row("Artifacts", (term.artifacts || []).length) +
          row("Evidence", (term.evidence || []).length) +
          (term.incomplete ? '<p class="run-live-warn">Incomplete or unverified evidence.</p>' : "") +
          (term.conflicting ? '<p class="run-live-warn">Sources disagree on this run; not resolved.</p>' : "") +
          (term.error ? '<p class="run-live-warn">' + esc(term.error.category) + ": " + esc(term.error.message) + "</p>" : "") +
          gateRows(term) +
          "</div>";
      } else {
        html += '<div class="run-live-error">terminal result unavailable</div>';
      }
      if (act && act.items) {
        html += '<ol class="run-activity" data-run-activity="' + esc(act.run_id || "") + '">' +
          act.items.map(function (i) {
            var d = i.detail || {};
            return "<li>" + esc(i.event_type) + (d.status ? " · " + esc(d.status) : "") +
              (d.cost_status ? " · cost " + esc(d.cost_status) : "") + "</li>";
          }).join("") + "</ol>";
      }
      panel.innerHTML = html;
    }
    renderFreshness({ status: "fresh", age_seconds: 0 });
    tick();
  }

  /* ---- read-only follow of an already correlated Run (#472 AC9) -------
     A claim moves the Issue to workflow:in-progress, at which point the typed
     next action becomes `null` while the Run is alive (a running Run has no
     sanctioned next step: it is neither launchable nor recoverable). The
     launch view used to refuse outright on that, so a browser reload during a
     Run left the operator with no way back to the live panel -- the one
     surface that carries freshness, the terminal result and the Evidence Gate
     verdict. Restoring READ of an existing Run is all this does.

     The launch gate itself is untouched: no dispatch request is fetched, and
     neither the confirmation dialog nor the claim POST is reachable from
     here. Both still require `next_action.kind === "launch"` above. */
  function renderRunOnly(winEl, ctx, issue, typed) {
    fetch("api/runs?issue=" + encodeURIComponent(issue), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("run projection unavailable (" + r.status + ")"); return r.json(); })
      .then(function (d) {
        /* Fail closed on correlation exactly as the dispatch-request path
           does: only Runs the server reports against THIS Issue count. */
        var runs = ((d && d.runs) || []).filter(function (r) {
          return r && (!r.issue_ref || r.issue_ref === issue);
        });
        if (!runs.length) { winEl.innerHTML = noLaunchNotice(typed); return; }
        winEl.innerHTML = '<span class="eyebrow">' + esc(ctx.workstream.id) +
          " · run in progress</span><h3>Following this Workstream's Run</h3>" +
          "<p>This Workstream is claimed, so no launch is offered. Its correlated Run is followed read-only below.</p>";
        attachLiveRun(winEl, ctx, issue, null);
      })
      .catch(function () { winEl.innerHTML = noLaunchNotice(typed); });
  }

  /* A claim is what makes a Run exist to follow: the workflow label the
     dispatcher sets when it claims the Issue. Nothing else opens this path. */
  function claimed(x) {
    return !!x && String(x.workflow || "").replace(/^workflow:/, "") === "in-progress";
  }

  function noLaunchNotice(typed) {
    return empty(
      "This Workstream has no authorized launch. Its typed next action is " +
      String(typed || "none") + ", so no dispatch request is requested or rendered.");
  }

  function renderLaunch(winEl, ctx) {
    if (!winEl) return;
    var s = (ctx && ctx.state) || {}, x = (ctx && ctx.workstream) || null;
    if (!x) { winEl.innerHTML = empty("Select a Workstream to review and start a Run."); return; }
    /* An ineligible Workstream cannot reach the launch view even by deep
       link: without an Issue, a `launch` next action, or (in preview mode)
       its own view:launch grant, no dispatch request is fetched at all. */
    var syntheticMode = !!(s.model && s.model.synthetic);
    var typed = (x.next_action && x.next_action.kind) || null;
    if (!x.issue_id) { winEl.innerHTML = noLaunchNotice(typed); return; }
    if (typed !== "launch" ||
        (syntheticMode && ((x.view_capabilities || []).indexOf("view:launch") === -1))) {
      /* Preview mode never reaches a live host, so there is no Run to follow
         and nothing is fetched. */
      if (syntheticMode) { winEl.innerHTML = noLaunchNotice(typed); return; }
      /* Only a Workstream that actually holds a claim may follow a Run. Every
         other ineligible Workstream still causes no fetch at all -- the
         original deep-link invariant, narrowed rather than dropped. */
      if (!claimed(x)) { winEl.innerHTML = noLaunchNotice(typed); return; }
      renderRunOnly(winEl, ctx, x.issue_id, typed);
      return;
    }
    winEl.innerHTML = '<span class="eyebrow">' + esc(x.id) + '</span><h3>Loading the approved dispatch request…</h3>';
    var issue = x.issue_id;
    if (syntheticMode) {
      loadSynthetic(winEl, ctx, issue);
    } else {
      loadLive(winEl, ctx, issue);
    }
  }

  if (typeof OSRenderer !== "undefined") {
    OSRenderer.register("launch", renderLaunch);
  }
})();
