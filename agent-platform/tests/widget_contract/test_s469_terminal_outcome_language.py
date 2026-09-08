"""W2 (#469/#520): the terminal panel must state the worker outcome, not only
the process status.

`run.terminal.v1` carries three separate facts -- how the PROCESS terminated
(`status`), what the WORKER reported it did (`outcome`, a required field since
#520), and whether the Evidence Gate ACCEPTED the result (`evidence_gate`). The
renderer read only the first, so a Run whose worker recorded `no_result` or
`unattested` was shown to the operator as `Status: succeeded` and nothing else.

Two kinds of check live here:

* **Behavioural.** The renderer exports its verdict function, so the decision
  is executed in node against fixtures for each status/outcome combination --
  the same `node -e` + `require` method `test_os_shell_core.py` already uses
  for `work-console.js`. These assert what the operator is actually told.
* **Source-level.** The presentation boundary and the mirror parity are
  properties of the file, not of one call, so they are asserted against the
  source in the style of the rest of the widget suite.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / "widget" / "app-renderer-work-launch.js"
MIRROR = ROOT.parent / "site" / "public" / "widgets" / "app-renderer-work-launch.js"
CSS = ROOT / "widget" / "os.css"
CSS_MIRROR = ROOT.parent / "site" / "public" / "widgets" / "os.css"

requires_node = pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")


@pytest.fixture(scope="module")
def source() -> str:
    return RENDERER.read_text(encoding="utf-8")


def verdict(term):
    """Run the shipped renderer's verdict function over one fixture, in node."""
    script = (
        "const m=require(%s);"
        "process.stdout.write(JSON.stringify(m.terminalVerdict(%s)));"
        % (json.dumps(str(RENDERER)), json.dumps(term))
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr or out.stdout
    return json.loads(out.stdout)


def block(term):
    """Render one fixture's verdict block to HTML, in node."""
    script = (
        "const m=require(%s);"
        "process.stdout.write(m.verdictBlock(%s));"
        % (json.dumps(str(RENDERER)), json.dumps(term))
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr or out.stdout
    return out.stdout


def run(status, outcome, gate=None, error=None, **rest):
    """A `run.terminal.v1` fixture carrying only the fields under test."""
    term = {"schema_version": 1, "issue_ref": "o/r#1", "run_id": "run-fixture",
            "status": status, "outcome": outcome, "evidence_gate": gate,
            "commit_evidence": None, "error": error, "engine": "hermes",
            "worker_role": "builder", "started_at": None, "finished_at": None,
            "provider": None, "model": None, "usage": {}, "cost": None,
            "cost_currency": "USD", "cost_status": "unknown", "artifacts": [],
            "evidence": [], "incomplete": True, "conflicting": False}
    term.update(rest)
    return term


# --- the combinations the operator must be able to tell apart ---------------

@requires_node
def test_succeeded_and_completed_states_both_facts_and_defers_acceptance():
    """A worker's own report is not the Evidence Gate's verdict."""
    v = verdict(run("succeeded", "completed", gate="commit_correlated"))
    assert v["statusLabel"] == "succeeded"
    assert v["outcomeRaw"] == "completed"
    assert v["outcomeLabel"] == "completed"
    assert v["gateLabel"] == "accepted"
    assert v["tone"] == "ok"
    assert "worker's own report" in v["plain"]


@requires_node
def test_completed_without_a_gate_verdict_is_not_presented_as_accepted():
    """`completed` is the worker's word; only the gate accepts anything."""
    v = verdict(run("succeeded", "completed"))
    assert v["tone"] == "warn"
    assert v["gateLabel"] == "not recorded"
    assert "not a" in v["plain"] and "pass" in v["plain"]


@requires_node
def test_succeeded_with_no_result_does_not_read_as_work_done():
    """The exact shape W2 exists for: a clean process over an empty result."""
    v = verdict(run("succeeded", "no_result"))
    assert v["tone"] == "warn"
    assert v["outcomeLabel"] == "no result"
    assert "Process succeeded" in v["headline"] and "no result" in v["headline"]
    assert "not evidence that work was done" in v["plain"]


@requires_node
def test_succeeded_with_no_result_stays_warn_even_if_a_gate_accepted_something():
    """No single field may raise a recorded absence of a result to a pass."""
    v = verdict(run("succeeded", "no_result", gate="commit_correlated"))
    assert v["tone"] == "warn"
    assert v["gateLabel"] == "accepted"


@requires_node
def test_succeeded_and_unattested_says_there_is_no_report_to_read():
    v = verdict(run("succeeded", "unattested"))
    assert v["tone"] == "warn"
    assert v["outcomeLabel"] == "unattested"
    assert "reported nothing" in v["plain"]


@requires_node
def test_declined_is_shown_as_a_refusal_to_work_not_as_a_failure_to_run():
    v = verdict(run("succeeded", "declined"))
    assert v["tone"] == "warn"
    assert v["outcomeLabel"] == "declined"
    assert "declined this task" in v["plain"]
    assert v["next"]


@requires_node
def test_an_error_status_keeps_its_existing_failure_information():
    """W2 adds the outcome; it removes nothing the panel already carried."""
    term = run("blocked", "unattested", gate="commit_correlation_failed",
               error={"category": "no_attested_outcome", "message": "nothing to verify"})
    v = verdict(term)
    assert v["tone"] == "warn"
    assert v["statusLabel"] == "blocked"
    assert v["gateLabel"] == "refused"
    assert "nothing to verify" in v["plain"] or "nothing to verify" in v["next"] \
        or "neither attested" in v["plain"]
    html = block(term)
    assert 'data-run-next-step' in html
    # The raw code itself is never dropped -- it is rendered by the detail view.
    assert "no_attested_outcome" in RENDERER.read_text(encoding="utf-8")


@requires_node
def test_an_older_run_without_an_outcome_fabricates_nothing():
    """`outcome: null` is every Run recorded before #520. It is not a pass."""
    v = verdict(run("succeeded", None))
    assert v["outcomeRaw"] is None
    assert v["outcomeLabel"] == "not recorded"
    assert v["tone"] == "warn"
    assert "No worker outcome was recorded" in v["plain"]


@requires_node
def test_an_older_accepted_run_is_still_accepted_on_the_gate_verdict():
    """The dogfood's one accepted Run has no outcome and reads
    `review_submitted`, not `succeeded` (#515). It must stay a pass."""
    v = verdict(run("review_submitted", None, gate="commit_correlated"))
    assert v["tone"] == "ok"
    assert v["gateLabel"] == "accepted"


@requires_node
def test_an_unknown_future_outcome_neither_crashes_nor_reads_as_approved():
    v = verdict(run("succeeded", "quantum_completed", gate="commit_correlated"))
    assert v["tone"] == "warn"
    assert v["outcomeLabel"] == "not recognised"
    assert v["outcomeRaw"] == "quantum_completed"
    assert "does not know how to read" in v["plain"]


@requires_node
def test_a_terminal_projection_missing_every_field_still_renders():
    """Totality: the verdict function must answer for any input it is given."""
    for term in ({}, {"status": None, "outcome": None}, {"status": "surprising"}):
        v = verdict(term)
        assert v["tone"] == "warn"
        assert v["headline"] and v["plain"] and v["next"]


# --- what the panel shows -------------------------------------------------

@requires_node
def test_the_panel_lists_status_and_outcome_as_separate_readable_facts():
    html = block(run("succeeded", "no_result"))
    assert "Process status" in html and "Worker outcome" in html and "Evidence gate" in html
    assert 'data-run-status-fact="succeeded"' in html
    assert 'data-run-worker-outcome="no_result"' in html
    assert 'data-run-gate-fact="not recorded"' in html


@requires_node
def test_an_unknown_outcome_is_escaped_when_shown_verbatim():
    html = block(run("succeeded", '<img src=x onerror=alert(1)>'))
    assert "<img" not in html
    assert "&lt;img" in html


@requires_node
def test_every_verdict_offers_a_next_step():
    """A stop the operator cannot act on is a dead end, not an explanation."""
    for outcome in (None, "completed", "declined", "no_result", "unattested", "unheard_of"):
        for status in ("succeeded", "blocked", "failed", "cancelled", None):
            v = verdict(run(status, outcome))
            assert v["next"], (status, outcome)


# --- source-level properties ----------------------------------------------

def test_a_gate_pass_is_never_presented_as_shipped(source):
    """The Gate verifies a commit on the run's own branch and nothing more."""
    assert "Nothing has been pushed, merged, published or deployed" in source


def test_acceptance_is_keyed_on_the_gate_verdict_not_the_status_word(source):
    assert 'gate === "commit_correlated"' in source
    assert 'gate === "commit_correlation_failed"' in source
    assert 'status === "succeeded"' not in source


def test_the_machine_vocabulary_survives_in_a_detail_view(source):
    """Debugging needs the raw code, run id and gate verdict -- one click away."""
    assert '<details class="run-detail">' in source
    assert "data-run-error-code" in source
    assert 'row("Run", term.run_id)' in source
    assert 'row("Worker outcome", term.outcome)' in source
    assert "gateRows(term)" in source


def test_the_evidence_hooks_the_acceptance_matrix_reads_are_unchanged(source):
    for hook in ("data-run-terminal", "data-run-status", "data-run-activity",
                 "data-run-freshness", "data-run-live"):
        assert hook in source


def test_the_presentation_boundary_holds(source):
    """W2 renders what the projection recorded and decides nothing itself.

    No outcome is derived from free text, no stored value is written back, and
    no workflow transition exists on this path.
    """
    terminal = source[source.index("function terminalVerdict("):source.index("function verdictBlock(")]
    for forbidden in ("fetch(", "POST", "workflow:", "localStorage", "outcome ="):
        assert forbidden not in terminal, forbidden


def test_the_narrow_layout_stacks_the_fact_list():
    """ADR-043: the panel must stay readable without sideways scrolling."""
    css = CSS.read_text(encoding="utf-8")
    assert "@media(max-width:720px){.run-verdict-facts{grid-template-columns:1fr" in css
    assert ".run-verdict-facts{display:grid;grid-template-columns:max-content 1fr" in css


def test_the_served_mirrors_are_byte_equal():
    """`site/public/widgets/*` is a byte-identical mirror of the widget source.

    W2, W3 and W7 all change both copies and nothing on main caught a one-sided
    edit; this is that parity check.
    """
    assert MIRROR.read_bytes() == RENDERER.read_bytes()
    assert CSS_MIRROR.read_bytes() == CSS.read_bytes()
