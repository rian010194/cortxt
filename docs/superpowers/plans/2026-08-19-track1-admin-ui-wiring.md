# Track 1: Admin-UI Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the widget visibility into `runtimes`, `credentials`, and `addons` — the three Fas 4/5 admin-surface CLI commands that exist as mechanism only today, with no UI.

**Architecture:** Reuse the existing single data source, not three new bespoke ones. `runtimes` and `credentials` extend `write_snapshot()`'s document with two new optional top-level arrays the widget polls, same pattern as `sessions`. `addons` reuses the *existing* sessions mechanism instead of inventing an addon registry (`learning/addon_review.py`'s own docstring explicitly defers that as "a separate, larger decision") — each `addons submit` call is recorded as a `session.terminal` event tagged `addon:<candidate_id>`, so it shows up in the widget's existing Sessions table for free, with zero new widget code.

**Tech Stack:** Python 3.11+, pytest, vanilla JS/HTML (no build step — `widget/index.html` is a single static file, per its own docstring's "no independent status logic" invariant).

**Spec:** `docs/superpowers/specs/2026-08-19-v02-swarm-orchestration-model-design.md`

## Global Constraints

- The widget never recomputes status/severity itself — it renders exactly what the snapshot says, per `widget/index.html`'s existing docstring invariant ("No independent status logic here"). New panels must follow the same rule.
- Credential values never appear in the snapshot or the widget — only `credential_id` and metadata derived from `CredentialBroker.audit_log()` (id, last action, last result, timestamp). No plaintext, ever.
- Tests run via `pytest agent-platform/tests/ -v` from the repo's `agent-platform/` directory.

---

### Task 1: Extend `write_snapshot()` with optional `runtimes` and `credentials`

**Files:**
- Modify: `agent-platform/cli/status.py`
- Test: `agent-platform/tests/cli/test_status.py` (create if it doesn't already exist — check first with `Test-Path agent-platform/tests/cli/test_status.py` or equivalent; if it exists, add to it)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `write_snapshot(sessions, snapshot_path, *, runtimes=None, credentials=None)` — Task 2 and Task 3 call this with their own data; Task 4 (widget) reads `doc.get("runtimes")` / `doc.get("credentials")`, both `None`/absent-safe.

- [ ] **Step 1: Write the failing test — snapshot omits runtimes/credentials keys when not given**

```python
def test_write_snapshot_omits_runtimes_and_credentials_by_default(tmp_path):
    from cli import status

    snapshot_path = tmp_path / "snapshot.json"
    status.write_snapshot([], snapshot_path)

    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert "runtimes" not in doc
    assert "credentials" not in doc
```

(Add `import json` at the top of the test file if not already present.)

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `pytest agent-platform/tests/cli/test_status.py::test_write_snapshot_omits_runtimes_and_credentials_by_default -v`
Expected: PASS already (current `write_snapshot` only ever writes `generated_at`/`sessions`) — this test locks in current behavior before Step 3 changes the signature, so a regression there is caught immediately.

- [ ] **Step 3: Write the failing test — snapshot includes runtimes/credentials when given**

```python
def test_write_snapshot_includes_runtimes_and_credentials_when_given(tmp_path):
    from cli import status

    snapshot_path = tmp_path / "snapshot.json"
    runtimes = [{"runtime_id": "hermes", "installed": True, "path": "/usr/bin/hermes"}]
    credentials = [{"credential_id": "openai-key", "last_action": "store", "last_result": "ok", "last_timestamp": "2026-08-19T10:00:00Z"}]

    status.write_snapshot([], snapshot_path, runtimes=runtimes, credentials=credentials)

    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert doc["runtimes"] == runtimes
    assert doc["credentials"] == credentials
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest agent-platform/tests/cli/test_status.py::test_write_snapshot_includes_runtimes_and_credentials_when_given -v`
Expected: FAIL with `TypeError: write_snapshot() got an unexpected keyword argument 'runtimes'`.

- [ ] **Step 5: Update `write_snapshot()`'s signature and body**

In `agent-platform/cli/status.py`, replace the existing `write_snapshot` function:

```python
def write_snapshot(
    sessions: list[dict[str, Any]],
    snapshot_path: Path,
    *,
    runtimes: list[dict[str, Any]] | None = None,
    credentials: list[dict[str, Any]] | None = None,
) -> None:
    """Atomically write the JSON snapshot the widget polls.

    `runtimes`/`credentials` are optional admin-surface data (Fas 4) the
    widget can render alongside sessions -- omitted from the document
    entirely when not given, so callers that only care about sessions
    (the existing `cortxt sessions`/`dispatch` call sites) don't need to
    change. Same write pattern as session_state._atomic_write: tempfile in
    the target directory + os.replace, so a reader never sees a
    half-written file.
    """
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {"generated_at": state.utc_now(), "sessions": sessions}
    if runtimes is not None:
        doc["runtimes"] = runtimes
    if credentials is not None:
        doc["credentials"] = credentials
    descriptor, tmp = tempfile.mkstemp(prefix=".snapshot-", suffix=".tmp", dir=snapshot_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, snapshot_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
```

- [ ] **Step 6: Run both new tests to verify they pass**

Run: `pytest agent-platform/tests/cli/test_status.py -v -k "snapshot_omits or snapshot_includes"`
Expected: both PASS.

- [ ] **Step 7: Run the full status.py test file and the full suite**

Run: `pytest agent-platform/tests/cli/test_status.py -v` then `pytest agent-platform/tests/ -v`
Expected: all PASS, no regressions (existing `_run_sessions`/`_run_dispatch` call sites pass no `runtimes`/`credentials` kwargs, so they're unaffected by the new optional params).

- [ ] **Step 8: Commit**

```bash
git add agent-platform/cli/status.py agent-platform/tests/cli/test_status.py
git commit -m "status: extend snapshot with optional runtimes/credentials for the widget"
```

---

### Task 2: Wire `cortxt runtimes` to refresh the snapshot

**Files:**
- Modify: `agent-platform/cli/unified_cli.py` (`_run_runtimes`, lines 401-423)
- Test: `agent-platform/tests/cli/test_unified_cli_widget.py` (existing file, per the prior session's Fas 6 work — add to it)

**Interfaces:**
- Consumes: `status.write_snapshot(sessions, snapshot_path, runtimes=..., credentials=...)` from Task 1.
- Produces: nothing new consumed elsewhere — this is a leaf CLI wiring task.

- [ ] **Step 1: Write the failing test — `cortxt runtimes` writes a snapshot with a `runtimes` key**

```python
def test_run_runtimes_writes_snapshot(tmp_path, monkeypatch):
    from cli import unified_cli

    snapshot_path = tmp_path / "snapshot.json"
    exit_code = unified_cli.main(["runtimes", "--snapshot", str(snapshot_path)])

    assert exit_code == 0
    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert "runtimes" in doc
    assert isinstance(doc["runtimes"], list)
```

(Match the exact `main()` return-code and argument-parsing conventions already used by the neighboring `test_run_dispatch_*` tests in this file — read a couple of them first if the exact assertion shape above doesn't match how `main()` is invoked elsewhere in this test file, and adjust to match, e.g. if `main()` returns `int` vs raises `SystemExit`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/cli/test_unified_cli_widget.py::test_run_runtimes_writes_snapshot -v`
Expected: FAIL — `--snapshot` isn't a recognized argument for the `runtimes` subparser yet, and `_run_runtimes` never calls `write_snapshot`.

- [ ] **Step 3: Add `--snapshot` argument to the `runtimes` subparser**

In `agent-platform/cli/unified_cli.py`, near line 573 (`runtimes_parser = sub.add_parser(...)`):

```python
    runtimes_parser = sub.add_parser("runtimes", help="List known agent runtimes and whether each is on PATH")
    runtimes_parser.add_argument("--snapshot", type=Path, help="Widget snapshot output path (default: agent-platform/widget/snapshot.json)")
```

- [ ] **Step 4: Update `_run_runtimes` to refresh the snapshot**

Replace `_run_runtimes` (lines 401-423) with:

```python
def _run_runtimes(args: argparse.Namespace) -> ResultEnvelope:
    """List known agent runtimes and whether each is on PATH (Fas 4 admin surface).

    Refreshes the widget snapshot's `runtimes` key on every call, same
    best-effort-but-visible pattern _run_dispatch uses for `sessions`: a
    snapshot write failure is logged, never masks this command's own
    result (Track 1, docs/superpowers/plans/2026-08-19-track1-admin-ui-wiring.md).
    """
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from routing.discovery import discover_installed_runtimes

        statuses = discover_installed_runtimes()
        print(f"{'RUNTIME':<14} {'INSTALLED':<10} PATH")
        print("-" * 60)
        for s in statuses:
            print(f"{s.runtime_id:<14} {'yes' if s.installed else 'no':<10} {s.path or ''}")

        runtimes_payload = [
            {"runtime_id": s.runtime_id, "installed": s.installed, "path": s.path} for s in statuses
        ]

        try:
            cli_dir = Path(__file__).parent
            if str(cli_dir) not in sys.path:
                sys.path.insert(0, str(cli_dir))
            import status as status_cli

            store = _get_agent_platform_path() / ".sessions"
            snapshot_path = args.snapshot or (ap_path / "widget" / "snapshot.json")
            status_cli.write_snapshot(
                status_cli.load_sessions(store), snapshot_path, runtimes=runtimes_payload,
            )
        except Exception as snapshot_error:
            logger.warning("runtimes: could not refresh widget snapshot: %s", snapshot_error)

        return ResultEnvelope(
            status="succeeded",
            evidence=[{"runtimes": runtimes_payload}],
        )
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})
```

(Check `logger` is already imported/defined at module level in `unified_cli.py` — `_run_dispatch`'s existing snapshot-refresh block uses `logger.warning` too, so it should already exist; if not, add `import logging` and `logger = logging.getLogger(__name__)` near the top, matching `status.py`'s own pattern.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest agent-platform/tests/cli/test_unified_cli_widget.py::test_run_runtimes_writes_snapshot -v`
Expected: PASS

- [ ] **Step 6: Run the full test suite**

Run: `pytest agent-platform/tests/ -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add agent-platform/cli/unified_cli.py agent-platform/tests/cli/test_unified_cli_widget.py
git commit -m "cli: cortxt runtimes refreshes the widget snapshot"
```

---

### Task 3: Wire `cortxt credentials` to refresh the snapshot (metadata only)

**Files:**
- Modify: `agent-platform/cli/unified_cli.py` (`_run_credentials`, lines 425-459)
- Test: `agent-platform/tests/cli/test_unified_cli_widget.py`

**Interfaces:**
- Consumes: `status.write_snapshot(..., credentials=...)` from Task 1; `CredentialBroker.audit_log() -> list[AuditRecord]` (existing, `security/credential_broker.py:140`).
- Produces: nothing new consumed elsewhere.

- [ ] **Step 1: Write the failing test — `store` refreshes the snapshot with metadata, no plaintext**

```python
def test_run_credentials_store_writes_snapshot_metadata_only(tmp_path, monkeypatch):
    from cli import unified_cli

    snapshot_path = tmp_path / "snapshot.json"
    store_dir = tmp_path / ".credentials"
    monkeypatch.setattr("sys.stdin", io.StringIO("super-secret-value\n"))

    exit_code = unified_cli.main([
        "credentials", "store", "--id", "test-cred", "--confirm",
        "--store-dir", str(store_dir), "--snapshot", str(snapshot_path),
    ])

    assert exit_code == 0
    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert "credentials" in doc
    ids = [c["credential_id"] for c in doc["credentials"]]
    assert "test-cred" in ids
    assert "super-secret-value" not in snapshot_path.read_text(encoding="utf-8")
```

(Add `import io` at the top of the test file if not already present. Match this test's exact CLI argument names — `--id`, `--confirm`, `--store-dir` — against what `credentials store`'s subparser actually defines; read the subparser definition around line 577-591 first and adjust flag names in this test if they differ from what's assumed here.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/cli/test_unified_cli_widget.py::test_run_credentials_store_writes_snapshot_metadata_only -v`
Expected: FAIL — no `--snapshot` argument on the `credentials store` subparser, and `_run_credentials` never calls `write_snapshot`.

- [ ] **Step 3: Add `--snapshot` argument to the `credentials` subparser**

Near line 577 (`credentials_parser = sub.add_parser("credentials", ...)`):

```python
    credentials_parser.add_argument("--snapshot", type=Path, help="Widget snapshot output path (default: agent-platform/widget/snapshot.json)")
```

(Add this once on the shared `credentials_parser`, not per-subcommand — both `store` and `inject` should refresh the snapshot, and `argparse` subparsers inherit arguments added to their parent only if added before `add_subparsers()` is called on it; if `credentials_sub = credentials_parser.add_subparsers(...)` already ran by this point in the file, add `--snapshot` to `credentials_parser` *before* that call, or add it identically to both `cred_store_parser` and `cred_inject_parser` instead — check the actual code order around lines 577-591 and pick whichever the existing structure supports without restructuring.)

- [ ] **Step 4: Update `_run_credentials` to refresh the snapshot on both `store` and `inject`**

Replace the body of `_run_credentials` (lines 425-459), keeping its existing docstring, adding a snapshot refresh after both the `store` and `inject` branches succeed:

```python
def _run_credentials(args: argparse.Namespace) -> ResultEnvelope:
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from security.credential_broker import CredentialBroker, NotOperatorConfirmedError

        store_dir = args.store_dir or (ap_path / ".credentials")
        broker = CredentialBroker.with_dpapi(store_dir)

        if args.credentials_command == "store":
            value = sys.stdin.read().rstrip("\n")
            broker.store(args.id, value, operator_confirmed=args.confirm)
            result = ResultEnvelope(status="succeeded", artifacts=[f"credential:{args.id}"])
        else:
            value = broker.inject(args.id, requesting_runtime=args.runtime, purpose=args.purpose)
            print(value)
            result = ResultEnvelope(status="succeeded", artifacts=[f"credential:{args.id}"])

        _refresh_credentials_snapshot(args, ap_path, broker)
        return result
    except NotOperatorConfirmedError as e:
        return ResultEnvelope(status="failed", error={"category": "not_confirmed", "message": str(e)})
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _refresh_credentials_snapshot(args: argparse.Namespace, ap_path: Path, broker) -> None:
    """Derive credential metadata (id, last action/result/timestamp) from
    the broker's own audit log -- never the plaintext value, which never
    leaves `inject`'s stdout. Best-effort, same pattern as _run_dispatch's
    snapshot refresh: a failure here is logged, never masks the
    store/inject result that already succeeded."""
    try:
        cli_dir = Path(__file__).parent
        if str(cli_dir) not in sys.path:
            sys.path.insert(0, str(cli_dir))
        import status as status_cli

        latest_by_id: dict[str, dict] = {}
        for record in broker.audit_log():
            if record.result != "ok":
                continue
            latest_by_id[record.credential_id] = {
                "credential_id": record.credential_id,
                "last_action": record.action,
                "last_result": record.result,
                "last_timestamp": record.timestamp,
            }

        store = _get_agent_platform_path() / ".sessions"
        snapshot_path = args.snapshot or (ap_path / "widget" / "snapshot.json")
        status_cli.write_snapshot(
            status_cli.load_sessions(store), snapshot_path,
            credentials=list(latest_by_id.values()),
        )
    except Exception as snapshot_error:
        logger.warning("credentials: could not refresh widget snapshot: %s", snapshot_error)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest agent-platform/tests/cli/test_unified_cli_widget.py::test_run_credentials_store_writes_snapshot_metadata_only -v`
Expected: PASS

- [ ] **Step 6: Run the full test suite**

Run: `pytest agent-platform/tests/ -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add agent-platform/cli/unified_cli.py agent-platform/tests/cli/test_unified_cli_widget.py
git commit -m "cli: cortxt credentials refreshes widget snapshot with metadata only, never plaintext"
```

---

### Task 4: Wire `cortxt addons submit` into session_state (no new registry)

**Files:**
- Modify: `agent-platform/cli/unified_cli.py` (`_run_addons`, lines 462-489)
- Test: `agent-platform/tests/cli/test_unified_cli_widget.py`

**Interfaces:**
- Consumes: `runtime.session_state.create`/`append` (existing, mirrors `_run_dispatch`'s usage at lines 312-318 and 353/361/370); `status.write_snapshot` from Task 1 (called with no new kwargs — addons ride the existing `sessions` array).
- Produces: nothing new consumed elsewhere.

- [ ] **Step 1: Write the failing test — `addons submit` creates a session visible in the snapshot**

```python
def test_run_addons_submit_creates_session(tmp_path):
    from cli import unified_cli

    snapshot_path = tmp_path / "snapshot.json"
    store = tmp_path / ".sessions"

    exit_code = unified_cli.main([
        "addons", "submit", "--candidate-id", "test-addon-1", "--codex-security-passed",
        "--store", str(store), "--snapshot", str(snapshot_path),
    ])

    assert exit_code == 0
    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    task_ids = [s["task_id"] for s in doc["sessions"]]
    assert "addon:test-addon-1" in task_ids
```

(Match `--candidate-id`/`--codex-security-passed`/`--incomplete` and any `--store` flag names against the actual `addons submit` subparser around lines 591-593 — read it first and adjust. If no `--store` flag exists yet on this subparser, add one identically to how `sessions_parser`/`dispatch_parser` already define theirs.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest agent-platform/tests/cli/test_unified_cli_widget.py::test_run_addons_submit_creates_session -v`
Expected: FAIL — `_run_addons` never touches `session_state` or the snapshot today.

- [ ] **Step 3: Add `--store`/`--snapshot` arguments to the `addons submit` subparser**

Near line 593 (`addons_submit_parser = addons_sub.add_parser(...)`):

```python
    addons_submit_parser.add_argument("--store", type=Path, help="Session store path (default: agent-platform/.sessions)")
    addons_submit_parser.add_argument("--snapshot", type=Path, help="Widget snapshot output path (default: agent-platform/widget/snapshot.json)")
```

- [ ] **Step 4: Update `_run_addons` to record a session per submission**

Replace `_run_addons` (lines 462-489):

```python
def _run_addons(args: argparse.Namespace) -> ResultEnvelope:
    """Admin surface over learning.addon_review.AddonReviewGate (Fas 5).

    Records each submission as a session_state entry tagged
    `addon:<candidate_id>` instead of a bespoke addon registry -- no addon
    history store exists yet, and inventing one is explicitly out of scope
    (see the module's own prior docstring note); reusing the sessions
    mechanism the widget already renders gives visibility for free
    (Track 1, docs/superpowers/plans/2026-08-19-track1-admin-ui-wiring.md).
    """
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from learning.addon_review import AddonReviewGate
        from learning.promotion_gate import PromotionGate
        from runtime import session_state as state

        matrix = {
            "complete": not args.incomplete,
            "codex_security_passed": args.codex_security_passed,
        }

        store = args.store or (ap_path / ".sessions")
        session = state.create(store, task_id=f"addon:{args.candidate_id}")
        session_id = session["session_id"]
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})

    try:
        verdict = AddonReviewGate(PromotionGate()).submit(matrix, args.candidate_id)
        print(verdict)
        status = "succeeded" if verdict != "REJECT" else "failed"
        state.append(store, session_id, 0, "session.terminal", {"status": status, "verdict": verdict})

        return ResultEnvelope(
            status=status,
            evidence=[{"candidate_id": args.candidate_id, "verdict": verdict, "matrix": matrix}],
        )
    except Exception as e:
        state.append(store, session_id, 0, "session.terminal", {"status": "failed", "reason": str(e)})
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})
    finally:
        try:
            cli_dir = Path(__file__).parent
            if str(cli_dir) not in sys.path:
                sys.path.insert(0, str(cli_dir))
            import status as status_cli

            snapshot_path = args.snapshot or (ap_path / "widget" / "snapshot.json")
            status_cli.write_snapshot(status_cli.load_sessions(store), snapshot_path)
        except Exception as snapshot_error:
            logger.warning("addons: could not refresh widget snapshot: %s", snapshot_error)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest agent-platform/tests/cli/test_unified_cli_widget.py::test_run_addons_submit_creates_session -v`
Expected: PASS

- [ ] **Step 6: Run the full test suite**

Run: `pytest agent-platform/tests/ -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add agent-platform/cli/unified_cli.py agent-platform/tests/cli/test_unified_cli_widget.py
git commit -m "cli: cortxt addons submit records a session, visible in the widget"
```

---

### Task 5: Runtimes and Credentials panels in the widget

**Files:**
- Modify: `agent-platform/widget/index.html`

**Interfaces:**
- Consumes: `doc.runtimes` (array of `{runtime_id, installed, path}`, absent-safe) and `doc.credentials` (array of `{credential_id, last_action, last_result, last_timestamp}`, absent-safe) from Task 1-3's extended snapshot.
- Produces: nothing (leaf UI task). Addons need no widget change — Task 4 already made them show up in the existing Sessions table via `task_id: "addon:<candidate_id>"`.

- [ ] **Step 1: Add two new panel containers to the HTML body**

In `agent-platform/widget/index.html`, after the existing `<div class="body">...</div>` block's closing tag (after line 102, before line 103's `</div>` that closes `.window`), insert:

```html
    <div class="body" id="runtimes-panel" style="display:none;">
      <div class="meta">Runtimes</div>
      <table>
        <thead><tr><th>Runtime</th><th>Installed</th><th>Path</th></tr></thead>
        <tbody id="runtimes-rows"></tbody>
      </table>
    </div>
    <div class="body" id="credentials-panel" style="display:none;">
      <div class="meta">Credentials</div>
      <table>
        <thead><tr><th>Credential</th><th>Last action</th><th>Result</th><th>Updated</th></tr></thead>
        <tbody id="credentials-rows"></tbody>
      </table>
    </div>
```

- [ ] **Step 2: Add render functions for both panels**

In the `<script>` block, after the existing `render(doc)` function (after line 139's closing `}`), add:

```javascript
function renderRuntimes(doc) {
  const panel = document.getElementById("runtimes-panel");
  if (!doc.runtimes) { panel.style.display = "none"; return; }
  panel.style.display = "";
  const rows = document.getElementById("runtimes-rows");
  rows.innerHTML = "";
  for (const r of doc.runtimes) {
    const tr = document.createElement("tr");
    const idCell = document.createElement("td");
    idCell.textContent = r.runtime_id;
    const installedCell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `badge ${r.installed ? "ok" : "warn"}`;
    badge.textContent = r.installed ? "yes" : "no";
    installedCell.appendChild(badge);
    const pathCell = document.createElement("td");
    pathCell.textContent = r.path || "";
    tr.append(idCell, installedCell, pathCell);
    rows.appendChild(tr);
  }
}

function renderCredentials(doc) {
  const panel = document.getElementById("credentials-panel");
  if (!doc.credentials) { panel.style.display = "none"; return; }
  panel.style.display = "";
  const rows = document.getElementById("credentials-rows");
  rows.innerHTML = "";
  for (const c of doc.credentials) {
    const tr = document.createElement("tr");
    const idCell = document.createElement("td");
    idCell.textContent = c.credential_id;
    const actionCell = document.createElement("td");
    actionCell.textContent = c.last_action;
    const resultCell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `badge ${c.last_result === "ok" ? "ok" : "error"}`;
    badge.textContent = c.last_result;
    resultCell.appendChild(badge);
    const updatedCell = document.createElement("td");
    updatedCell.textContent = c.last_timestamp;
    tr.append(idCell, actionCell, resultCell, updatedCell);
    rows.appendChild(tr);
  }
}
```

(Note: `c.credential_id`/`c.last_action`/`c.last_timestamp` are set via `textContent`, never `innerHTML` — same XSS-avoidance pattern the existing `render()` function already uses for `task_id`/`status`/`updated_at`, since these values ultimately come from operator-supplied credential ids and audit log entries, not a fixed enum.)

- [ ] **Step 3: Call the new render functions from `poll()`**

Replace the existing `poll()` function (lines 141-148):

```javascript
async function poll() {
  try {
    const res = await fetch("snapshot.json", { cache: "no-store" });
    const doc = await res.json();
    render(doc);
    renderRuntimes(doc);
    renderCredentials(doc);
  } catch (err) {
    document.getElementById("meta").textContent = "waiting for snapshot.json (run `cortxt sessions`)…";
  }
}
```

- [ ] **Step 4: Manual verification against a live snapshot**

Run (from `agent-platform/`): `python -m cli.unified_cli runtimes` then `python -m cli.unified_cli widget`, open the printed loopback URL in a browser, and confirm the Runtimes panel appears with real data (no "Installed" badges stuck on "no" for a runtime actually on PATH). Then run `python -m cli.unified_cli credentials store --id demo-cred --confirm` (typing a throwaway value at the stdin prompt) and confirm the Credentials panel appears with `demo-cred` and no plaintext visible anywhere in the page source.

This step has no pytest assertion — it is the UI verification the project's own guidance requires before calling a frontend change done ("start the dev server and use the feature in a browser before reporting the task as complete").

- [ ] **Step 5: Commit**

```bash
git add agent-platform/widget/index.html
git commit -m "widget: add Runtimes and Credentials panels"
```

---

## Self-review notes

- Spec coverage: all three admin-surface commands (runtimes, credentials, addons) get widget visibility. Addons deliberately gets no new panel — Task 4's design note explains why (no registry exists, reusing sessions avoids inventing one).
- Placeholder scan: every step has literal code; Task 5 Step 4 is explicitly a manual verification step, not a placeholder — it's the project's own required frontend-verification practice, called out as such.
- Type consistency: `write_snapshot`'s `runtimes`/`credentials` kwargs match across Task 1's implementation and Task 2/3's call sites; the widget's `doc.runtimes`/`doc.credentials` field names match Task 1's dict shapes exactly (`runtime_id`/`installed`/`path`, `credential_id`/`last_action`/`last_result`/`last_timestamp`).
- Ambiguity flagged inline: Task 3 Step 3 and several test steps note where the exact existing argparse structure (subparser argument placement, flag names) must be checked against the real file before finalizing, rather than assumed — the file was read only up to line 500 and around 573-593 during planning; an implementer should re-read the exact subparser blocks before writing code, per this plan's own instruction.
