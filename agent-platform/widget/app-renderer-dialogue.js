/* Cortxt OS dialogue app renderer (B1.5d, dialogue-to-result series).

   Renders ONLY what the six frozen local dialogue routes of
   b15c-order.md section D2 return: the session list (R1), create (R2),
   open/reopen a transcript (R3), connect the agent (R4), send a turn (R5),
   cancel a turn (R6). Contract-first: every request and response shape
   comes from that frozen table; nothing is inferred.

   Authority boundary (ADR-044, ADR-038):
   - Rendering, reopening and polling issue GET only. Every mutation is
     issued by a click on a named control (create, connect, send, cancel).
   - No invented-data branch of any kind: without a live
     host token the app says it is unavailable and issues no request at all.
   - Every string from the server or the agent passes through esc().
   - History is marked (replay divider + load marker); replayed history is
     never shown as live; "started fresh" is read from the persisted
     dialogue.session.loaded event, never guessed (ADR-049 D3, DEC-8(a)).

   Browser-evidence hooks:
     data-dialogue-state         root state attribute (empty/ready/partial/
                                 unavailable/error)
     data-dialogue-turn-status   turn status element, role="status"
     data-dialogue-origin        "history" on pre-open items
     data-dialogue-divider       "history" | "replay" | "fresh"
     data-dialogue-permission    "denied" on denied permission items
     data-dialogue-store-error   store-error block
*/
(function () {
  "use strict";

  var ROUTES = { sessions: "api/dialogue/sessions", session: "api/dialogue/session",
                 connect: "api/dialogue/connect", turn: "api/dialogue/turn", cancel: "api/dialogue/cancel" };
  var POLL_MS = 1000;

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function empty(m) { return '<div class="empty-state">' + esc(m) + "</div>"; }

  /* ---- failure classification (b15c D7 kinds) ------------------------- */

  /* The 503 kinds answer state "unavailable" (no retry loop); every other
     failure answers state "error" (a Retry button re-issues the same GET). */
  var UNAVAILABLE_KINDS = { dialogue_unavailable: true, acp_unavailable: true,
                            agent_unavailable: true, agent_capacity: true };

  var KIND_SENTENCES = {
    not_found: "This dialogue path does not exist on this host.",
    method_not_allowed: "This host does not answer that method on the dialogue path.",
    authorization_denied: "This page's session token was rejected; reload the page.",
    validation_error: "The request was not valid for this host.",
    invalid_cursor: "The transcript cursor was not valid for this store.",
    rate_limited: "The host is limiting dialogue sends; wait a moment and retry.",
    dialogue_writer_busy: "Another Cortxt host owns dialogue writes for this data home.",
    session_not_found: "This session does not exist on this host.",
    session_unreadable: "This session's log could not be read.",
    cursor_ahead: "The transcript cursor is ahead of what the store has persisted.",
    acp_unavailable: "The ACP client package is not installed on this host.",
    agent_unavailable: "No agent command is configured or it was not found.",
    agent_capacity: "The host already runs its maximum number of agents.",
    already_connected: "An agent is already connected to this session.",
    not_connected: "No agent is connected to this session yet.",
    turn_in_progress: "A turn is already open in this session.",
    turn_not_open: "That turn is not the open turn of this session.",
    agent_connection_lost: "The agent connection was lost.",
    agent_protocol_error: "The agent answered in a way this host could not interpret.",
    sequence_conflict: "Another writer changed this session log concurrently.",
    store_refused: "The dialogue store refused a write.",
    dialogue_unavailable: "No data home is configured for this host.",
    dialogue_error: "The dialogue host hit an unexpected internal error."
  };

  function classifyFailure(httpStatus, body) {
    var kind = (body && body.error && body.error.kind) || "dialogue_error";
    var state = (httpStatus === 503 && UNAVAILABLE_KINDS[kind]) ? "unavailable" : "error";
    var message = body && body.error && body.error.message;
    var sentence;
    if (state === "unavailable") {
      sentence = (KIND_SENTENCES[kind] || "The dialogue host reported a failure.") +
                 " (" + kind + ")";
    } else {
      sentence = "The dialogue host answered with an error: " + kind +
                 (message ? " — " + message : "");
    }
    return { state: state, kind: kind, sentence: sentence };
  }

  /* ---- R1: the session list view --------------------------------------- */

  function listView(httpStatus, body) {
    if (httpStatus === 200 && body && (body.status === "ok" || body.status === "partial")) {
      var sessions = Array.isArray(body.sessions) ? body.sessions : [];
      var unreadable = Array.isArray(body.unreadable) ? body.unreadable : [];
      if (!sessions.length && !unreadable.length) {
        return { state: "empty", sessions: [], unreadable: [], kind: null, sentence: null,
                 storeKind: null };
      }
      return { state: unreadable.length ? "partial" : "ready",
               sessions: sessions, unreadable: unreadable, kind: null, sentence: null,
               storeKind: null };
    }
    var f = classifyFailure(httpStatus, body);
    return { state: f.state, sessions: [], unreadable: [],
             kind: f.kind, sentence: f.sentence,
             storeKind: (body && body.error && body.error.store_kind) || null };
  }

  /* ---- transcript folding ----------------------------------------------- */

  /* Folds the store's raw events into ordered items, in event-sequence order
     and, inside a dialogue.updates batch, in array order. The per-wire-event
     sequence number is never read: not for ordering, not for de-duplication,
     not as a cursor.

     Item types: prompt, reply, permission, update, outcome,
     history_divider, load_marker. Every item folded from an event with
     sequence <= openedAtSequence carries history: true. When the session has
     at least one turn started at or below the open boundary, one history
     divider follows the last history event: everything above it came from
     the store, never from agent replay (ADR-049 D3). */
  function foldTranscript(events, openedAtSequence) {
    var items = [];
    var replyByTurn = {};
    var pendingDivider = false;
    for (var i = 0; i < events.length; i++) {
      var ev = events[i];
      var seq = ev.sequence;
      var history = openedAtSequence != null && seq <= openedAtSequence;
      var kind = ev.event_type;
      var payload = ev.payload || {};
      if (kind === "dialogue.turn.started") {
        var prompt = { type: "prompt", turnId: payload.turn_id, text: payload.prompt_text };
        if (history) { prompt.history = true; pendingDivider = true; }
        items.push(prompt);
      } else if (kind === "dialogue.updates") {
        var batch = Array.isArray(payload.events) ? payload.events : [];
        for (var j = 0; j < batch.length; j++) {
          foldWire(items, batch[j], payload.turn_id, replyByTurn, history);
        }
      } else if (kind === "dialogue.turn.finished") {
        var outcomeText = payload.outcome === "interrupted"
          ? "failed (interrupted)" : String(payload.outcome);
        if (payload.outcome === "completed" && payload.stop_reason &&
            payload.stop_reason !== "end_turn") {
          outcomeText += " (" + payload.stop_reason + ")";
        }
        var outcome = { type: "outcome", turnId: payload.turn_id,
                        outcome: payload.outcome, text: outcomeText };
        if (history) outcome.history = true;
        items.push(outcome);
      } else if (kind === "dialogue.session.loaded") {
        var fresh = payload.replayed_update_count === 0;
        items.push({ type: "load_marker", turnId: null,
                     divider: fresh ? "fresh" : "replay",
                     text: fresh
                       ? "Agent started fresh — it replayed no earlier history."
                       : "Agent reconnected — it replayed " +
                         payload.replayed_update_count +
                         " earlier updates; they were not stored again." });
      }
      /* session.created and dialogue.acp.bound carry no renderable content. */

      /* The replay divider on reopen: exactly one, after the last history
         event, only when a turn started at or below the boundary. */
      if (history && pendingDivider) {
        var next = events[i + 1];
        if (!next || next.sequence > openedAtSequence) {
          items.push({ type: "history_divider", turnId: null, divider: "history",
                       text: "Earlier conversation (from the store)", history: true });
          pendingDivider = false;
        }
      }
    }
    return items;
  }

  function foldWire(items, wire, turnId, replyByTurn, history) {
    if (wire.kind === "session_update") {
      if (wire.update_type === "agent_message_chunk") {
        var update = wire.payload && wire.payload.update;
        var content = update && typeof update === "object" ? update.content : null;
        if (content && content.type === "text") {
          var reply = replyByTurn[turnId];
          if (!reply) {
            reply = { type: "reply", turnId: turnId, text: "" };
            if (history) reply.history = true;
            replyByTurn[turnId] = reply;
            items.push(reply);
          }
          reply.text += content.text == null ? "" : String(content.text);
          return;
        }
      }
      var updateItem = { type: "update", turnId: turnId,
                         text: wire.update_type || "update" };
      if (history) updateItem.history = true;
      items.push(updateItem);
      return;
    }
    if (wire.kind === "permission_request" && wire.decision === "denied") {
      var toolTitle = wire.payload && wire.payload.toolCall && wire.payload.toolCall.title;
      var permission = { type: "permission", turnId: turnId,
                         text: "The agent asked for permission (" +
                               (toolTitle ? toolTitle : "an action") +
                               ") — denied. Cortxt never grants agent permissions in this version." };
      if (history) permission.history = true;
      items.push(permission);
    }
    /* A permission request without a decision is an open question this
       version never answers: it renders nothing, never an allow control. */
  }

  /* ---- turn status ------------------------------------------------------- */

  /* localPhase: "posting" | "accepted" | null. Returns "sending" |
     "streaming" | "completed" | "failed" | "cancelled". A
     dialogue.turn.finished for THIS turn wins; interrupted is failed.
     Updates for another turn never advance this turn's status. */
  function turnStatus(events, turnId, localPhase) {
    var updates = 0;
    for (var i = 0; i < events.length; i++) {
      var ev = events[i];
      var payload = ev.payload || {};
      if (ev.event_type === "dialogue.turn.finished" && payload.turn_id === turnId) {
        return payload.outcome === "interrupted" ? "failed" : payload.outcome;
      }
      if (ev.event_type === "dialogue.updates" && payload.turn_id === turnId) {
        updates += 1;
      }
    }
    if (updates > 0) return "streaming";
    return "sending";
  }

  /* ---- pure HTML renderers ------------------------------------------------ */

  function renderList(view) {
    if (view.state === "empty") {
      return '<div data-dialogue-state="empty">' + empty("No dialogue sessions yet.") +
        '<div class="review-actions"><button type="button" class="primary-action" data-dialogue-create>Create session</button></div></div>';
    }
    if (view.state === "unavailable" || view.state === "error") {
      return '<div data-dialogue-state="' + view.state + '">' +
        '<div class="empty-state"><span class="eyebrow">' + esc(view.kind) + "</span>" +
        "<p>" + esc(view.sentence || "") + "</p>" +
        (view.storeKind ? "<p>" + esc(view.storeKind) + "</p>" : "") +
        (view.state === "error"
          ? '<button type="button" class="chrome-button" data-dialogue-retry>Retry</button>'
          : "") +
        "</div></div>";
    }
    var html = '<div data-dialogue-state="' + view.state + '"><span class="eyebrow">Dialogue sessions</span><div class="dialogue-list">';
    for (var i = 0; i < view.sessions.length; i++) {
      var s = view.sessions[i];
      html += '<article class="dialogue-session"><strong>' + esc(s.cortxt_session_id) + "</strong>" +
        "<p>" + esc(s.created_at || "") + " · " + esc(s.turn_count) +
        (s.turn_count === 1 ? " turn" : " turns") + " · " +
        (s.connected ? "connected" : "not connected") + "</p>" +
        '<div class="review-actions"><button type="button" class="chrome-button" data-dialogue-open="' +
        esc(s.cortxt_session_id) + '">Open</button></div></article>';
    }
    html += "</div>";
    if (view.unreadable.length) {
      html += '<section class="dialogue-unreadable"><span class="eyebrow">Unreadable sessions</span><ul>';
      for (var u = 0; u < view.unreadable.length; u++) {
        html += "<li><code>" + esc(view.unreadable[u].entry) + "</code> — " +
                esc(view.unreadable[u].kind) + "</li>";
      }
      html += "</ul></section>";
    }
    html += '<div class="review-actions"><button type="button" class="chrome-button" data-dialogue-create>Create session</button></div></div>';
    return html;
  }

  function renderTranscript(items) {
    var html = "";
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      if (it.type === "history_divider" || it.type === "load_marker") {
        html += '<div class="dialogue-divider" data-dialogue-divider="' + esc(it.divider) + '">' +
          esc(it.text) + "</div>";
        continue;
      }
      var extra = "";
      if (it.type === "permission") extra = ' data-dialogue-permission="denied"';
      html += '<div class="dialogue-item dialogue-' + esc(it.type) + '"' +
        (it.history ? ' data-dialogue-origin="history"' : "") + extra + ">" +
        '<span class="eyebrow">' + esc(it.type) + "</span><p>" + esc(it.text) + "</p></div>";
    }
    return '<div class="dialogue-transcript" data-dialogue-transcript>' + html + "</div>";
  }

  function renderStatus(status, detail) {
    return '<p class="dialogue-status" role="status" data-dialogue-turn-status="' + esc(status) + '">' +
      esc(status) + (detail ? " — " + esc(detail) : "") + "</p>";
  }

  /* ---- transport ----------------------------------------------------------- */

  /* deps = {fetch, token}; returns {httpStatus, body}; a thrown fetch ->
     {httpStatus: 0, body: null}. The token header rides on every request,
     reads included. A non-GET method carries a JSON body. */
  async function request(deps, method, route, opts) {
    var url = route + (opts && opts.query ? "?" + opts.query : "");
    var init = { method: method, cache: "no-store",
                 headers: { "X-Cortxt-Token": deps.token } };
    if (method !== "GET") {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify((opts && opts.body) || {});
    }
    try {
      var response = await deps.fetch(url, init);
      var body = null;
      try { body = await response.json(); } catch (_e) { body = null; }
      return { httpStatus: response.status, body: body };
    } catch (_e) {
      return { httpStatus: 0, body: null };
    }
  }

  function clientRequestId() {
    var bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    var hex = "";
    for (var i = 0; i < bytes.length; i++) {
      hex += (bytes[i] < 16 ? "0" : "") + bytes[i].toString(16);
    }
    return hex;
  }

  /* ---- DOM layer ----------------------------------------------------------- */

  function renderDialogue(winEl, ctx) {
    if (!winEl) return;
    var s = (ctx && ctx.state) || {};
    /* Fail closed before any DOM work beyond this one assignment: no token,
       no request, nothing fetched, nothing invented. */
    if (!s.token) {
      winEl.innerHTML = '<div data-dialogue-state="unavailable">' +
        '<div class="empty-state">Dialogue needs a live Cortxt host started with a data home.</div></div>';
      return;
    }

    var deps = { fetch: fetch.bind(globalThis), token: s.token };
    var view = { sessionId: null, connected: false, openTurnId: null,
                 cursorNext: -1, openedAtSequence: null, events: [],
                 turnId: null, localPhase: null, lastFailure: null,
                 finalReadDone: false, reopenDone: false,
                 timer: null, stopped: false, connectLine: null, connectError: null };

    function stop() {
      view.stopped = true;
      if (view.timer) { clearTimeout(view.timer); view.timer = null; }
    }
    winEl._cortxtStopDialogue = stop;

    function q(sel) { return winEl.querySelector(sel); }
    function qa(sel) { return Array.prototype.slice.call(winEl.querySelectorAll(sel)); }

    /* -- R1: list ---------------------------------------------------------- */
    async function loadList() {
      var r = await request(deps, "GET", ROUTES.sessions);
      var v = listView(r.httpStatus, r.body);
      winEl.innerHTML = renderList(v);
      var create = q("[data-dialogue-create]");
      if (create) create.addEventListener("click", onCreate);
      qa("[data-dialogue-open]").forEach(function (b) {
        b.addEventListener("click", function () { openSession(b.getAttribute("data-dialogue-open")); });
      });
      var retry = q("[data-dialogue-retry]");
      if (retry) retry.addEventListener("click", function () { loadList(); });
    }

    /* -- R3: open / reopen (GET only) -------------------------------------- */
    async function openSession(id) {
      stop();
      view.stopped = false;
      view.sessionId = id;
      view.cursorNext = -1;
      view.events = [];
      view.turnId = null;
      view.localPhase = null;
      view.lastFailure = null;
      view.finalReadDone = false;
      view.reopenDone = false;
      var opened = await readAll();
      if (!opened) return;
      renderSessionView();
      scheduleIfLive();
    }

    /* Reads pages with after=cursor.next until has_more is false. GET only.
       One consecutive cursor_ahead re-opens with after=-1; a second is a
       state error, never a loop. */
    async function readAll() {
      var guard = 0;
      for (;;) {
        var r = await request(deps, "GET", ROUTES.session,
                              { query: "id=" + encodeURIComponent(view.sessionId) +
                                       "&after=" + view.cursorNext });
        if (r.httpStatus === 409 && r.body && r.body.error &&
            r.body.error.kind === "cursor_ahead") {
          if (!view.reopenDone) {
            view.reopenDone = true;
            view.events = [];
            view.cursorNext = -1;
            continue;
          }
          view.events = [];
          view.cursorNext = -1;
          sessionFailed(r);
          return false;
        }
        if (r.httpStatus !== 200 || !r.body) { sessionFailed(r); return false; }
        view.events = view.events.concat(r.body.events || []);
        view.connected = !!r.body.connected;
        view.openTurnId = r.body.open_turn_id || null;
        view.openedAtSequence = r.body.last_persisted_sequence;
        view.cursorNext = r.body.cursor ? r.body.cursor.next : view.cursorNext;
        if (r.body.store_error) { showStoreError(r.body.store_error); return false; }
        if (!r.body.cursor || !r.body.cursor.has_more) return true;
        if (++guard > 100) {
          showState("error", '<div class="empty-state"><span class="eyebrow">dialogue_error</span>' +
            "<p>The session log is paging without end.</p></div>");
          return false;
        }
      }
    }

    function showState(state, html) {
      winEl.innerHTML = '<div data-dialogue-state="' + esc(state) + '">' + html + "</div>";
    }

    function renderSessionView() {
      var items = foldTranscript(view.events, view.openedAtSequence);
      var textarea = q("[data-dialogue-text]");
      var kept = textarea ? textarea.value : "";
      var html = '<span class="eyebrow">' + esc(view.sessionId) + "</span><h3>Dialogue</h3>";
      if (view.connectLine) {
        html += '<p class="dialogue-status" role="status" data-dialogue-connect-line>' +
          esc(view.connectLine) + "</p>";
        view.connectLine = null;
      }
      html += renderTranscript(items);
      if (!view.connected) {
        html += '<div class="review-actions"><button type="button" class="primary-action" data-dialogue-connect>Connect agent</button></div>';
        html += '<div data-dialogue-connect-slot></div>';
      } else {
        html += composerHtml();
      }
      showState("ready", html);
      if (view.connected) {
        var send = q("[data-dialogue-send]");
        if (send) send.addEventListener("click", onSend);
        var cancel = q("[data-dialogue-cancel]");
        if (cancel) cancel.addEventListener("click", onCancel);
        var restore = q("[data-dialogue-text]");
        if (restore && kept) restore.value = kept;
        updateComposer();
      } else {
        var connect = q("[data-dialogue-connect]");
        if (connect) connect.addEventListener("click", onConnect);
        if (view.connectError) {
          var slot = q("[data-dialogue-connect-slot]");
          if (slot) slot.innerHTML = renderStatus("failed", view.connectError);
        }
      }
    }

    function composerHtml() {
      return '<div class="dialogue-composer">' +
        '<textarea class="dialogue-input" data-dialogue-text rows="3" aria-label="Message text"></textarea>' +
        '<div class="review-actions">' +
        '<button type="button" class="primary-action" data-dialogue-send>Send</button>' +
        '<button type="button" class="chrome-button" data-dialogue-cancel hidden>Cancel</button>' +
        "</div>" +
        '<div data-dialogue-status-slot></div>' +
        "</div>";
    }

    /* Recompute the status line and the composer's disabled/cancel state
       from the latest transcript events. Text-only: status is never
       communicated by colour alone (ADR-043). The raw finished outcome of
       the current turn drives the status detail: the word "interrupted" is
       reserved for turns whose outcome is interrupted (order section 4);
       a plain failed turn renders without it. */
    function rawOutcome(events, turnId) {
      for (var i = 0; i < events.length; i++) {
        var ev = events[i];
        if (ev.event_type === "dialogue.turn.finished" && ev.payload &&
            ev.payload.turn_id === turnId) {
          return ev.payload.outcome || null;
        }
      }
      return null;
    }

    function updateComposer() {
      var slot = q("[data-dialogue-status-slot]");
      var send = q("[data-dialogue-send]");
      var cancel = q("[data-dialogue-cancel]");
      var outcome = view.turnId ? rawOutcome(view.events || [], view.turnId) : null;
      var status = view.turnId
        ? turnStatus(view.events || [], view.turnId, view.localPhase)
        : (view.localPhase ? "sending" : null);
      var shown = status || (view.lastFailure ? "failed" : null);
      var detail = view.lastFailure
        ? view.lastFailure.kind + " — " + view.lastFailure.sentence
        : (status === "failed" && outcome === "interrupted" ? "interrupted" : null);
      if (slot) slot.innerHTML = (status || view.lastFailure) ? renderStatus(shown, detail) : "";
      if (send) send.disabled = !(view.connected && !view.openTurnId && !view.localPhase);
      if (cancel) cancel.hidden = !(status === "sending" || status === "streaming");
    }

    function sessionFailed(r) {
      var f = classifyFailure(r.httpStatus, r.body);
      /* The Retry button belongs to state "error" only; "unavailable" has
         no retry loop (order state table). */
      showState(f.state, '<div class="empty-state"><span class="eyebrow">' + esc(f.kind) + "</span><p>" +
        esc(f.sentence) + "</p>" +
        (f.state === "error"
          ? '<button type="button" class="chrome-button" data-dialogue-retry>Retry</button>'
          : "") +
        "</div>");
      qa("[data-dialogue-retry]").forEach(function (b) {
        b.addEventListener("click", function () {
          view.events = [];
          view.cursorNext = -1;
          readAll().then(function (ok) { if (ok) { renderSessionView(); scheduleIfLive(); } });
        });
      });
    }

    function showStoreError(storeError) {
      showState("ready", '<div class="empty-state" data-dialogue-store-error>' +
        '<span class="eyebrow">' + esc(storeError.kind) + "</span>" +
        "<p>The dialogue store refused a write: " + esc(storeError.kind) + "</p></div>");
      /* The caller does not schedule a next read: polling stops. */
    }

    /* -- RD-1: one bounded poll chain per mounted window ------------------- */
    function scheduleIfLive() {
      if (view.stopped) return;
      if (!(view.connected && (view.openTurnId || view.localPhase))) return;
      if (view.timer) return;
      view.timer = setTimeout(tick, POLL_MS);
    }

    async function tick() {
      view.timer = null;
      if (view.stopped) return;
      var ok = await readAll();
      if (!ok || view.stopped) return;
      /* A terminal outcome for the current turn ends the send phase: the
         localPhase latch clears BEFORE the re-render, so the composer
         re-enables (connected && open_turn_id == null) and the
         one-final-poll rule below is reachable (RD-1). */
      var status = view.turnId
        ? turnStatus(view.events, view.turnId, view.localPhase)
        : null;
      var terminal = status === "completed" || status === "failed" || status === "cancelled";
      if (view.turnId && terminal) view.localPhase = null;
      renderSessionView();
      if (view.openTurnId || view.localPhase) { scheduleIfLive(); return; }
      if (view.turnId && terminal && !view.finalReadDone) {
        /* The open turn has a terminal outcome; one further poll completes
           the stream, then polling stops (idle: no polling). Scheduled
           explicitly: scheduleIfLive's gateway refuses to re-arm once
           localPhase has cleared, which is exactly the idle state. */
        view.finalReadDone = true;
        if (!view.timer && !view.stopped) view.timer = setTimeout(tick, POLL_MS);
      }
    }

    /* -- R2: create (click handler) ---------------------------------------- */
    async function onCreate() {
      var r = await request(deps, "POST", ROUTES.sessions, { body: {} });
      if (r.httpStatus === 201 && r.body && r.body.session) {
        await loadList();
        openSession(r.body.session.cortxt_session_id);
        return;
      }
      var f = classifyFailure(r.httpStatus, r.body);
      showState(f.state, '<div class="empty-state"><span class="eyebrow">' + esc(f.kind) +
        "</span><p>" + esc(f.sentence) + "</p></div>");
    }

    /* -- R4: connect (click handler) --------------------------------------- */
    async function onConnect() {
      var r = await request(deps, "POST", ROUTES.connect,
                            { body: { session_id: view.sessionId } });
      if (r.httpStatus === 200 && r.body) {
        var info = r.body.agent_info || {};
        view.connectLine = r.body.mode === "new"
          ? "Connected to " + (info.agent_name || "agent") + " " +
            (info.agent_version || "") + " — new agent session"
          : "Reconnected";
        /* The single post-connect read: the persisted load marker renders. */
        view.connectError = null;
        await openSession(view.sessionId);
        return;
      }
      var f = classifyFailure(r.httpStatus, r.body);
      view.connectError = f.sentence;
      renderSessionView();
    }

    async function onSend() {
      var textarea = q("[data-dialogue-text]");
      if (!textarea || !view.connected || view.openTurnId || view.localPhase) return;
      var text = textarea.value;
      if (!text || !text.trim()) return;
      view.localPhase = "posting";
      view.turnId = null;
      view.lastFailure = null;
      updateComposer();
      var r = await request(deps, "POST", ROUTES.turn,
                            { body: { session_id: view.sessionId, text: text,
                                      client_request_id: clientRequestId() } });
      if (r.httpStatus === 202 && r.body && r.body.turn_id) {
        view.turnId = r.body.turn_id;
        view.localPhase = "accepted";
        updateComposer();
        scheduleIfLive();
        return;
      }
      view.localPhase = null;
      view.lastFailure = classifyFailure(r.httpStatus, r.body);
      updateComposer(); /* the textarea content is kept */
    }

    async function onCancel() {
      if (!view.turnId) return;
      await request(deps, "POST", ROUTES.cancel,
                    { body: { session_id: view.sessionId, turn_id: view.turnId } });
      /* The cancelled outcome arrives through the poll. */
    }

    loadList();
  }

  if (typeof OSRenderer !== "undefined") {
    OSRenderer.register("dialogue", renderDialogue, { capabilities: ["read:dialogue-session", "act:dialogue-turn"] });
  }

  if (typeof module === "object" && module.exports) {
    module.exports = { ROUTES: ROUTES, POLL_MS: POLL_MS,
                       classifyFailure: classifyFailure, listView: listView,
                       foldTranscript: foldTranscript, turnStatus: turnStatus,
                       renderList: renderList, renderTranscript: renderTranscript,
                       renderStatus: renderStatus, request: request,
                       renderDialogue: renderDialogue };
  }
})();
