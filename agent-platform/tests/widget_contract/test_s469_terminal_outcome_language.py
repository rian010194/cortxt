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


def verdicts(terms, tmp_path):
    """The same, for a list of fixtures, in one node process.

    The fixtures go through a file rather than the command line: a sweep of a
    few hundred is past the Windows argument-length limit.
    """
    fixtures = tmp_path / "terms.json"
    fixtures.write_text(json.dumps(terms), encoding="utf-8")
    script = (
        "const m=require(%s);"
        "const t=require(%s);"
        "process.stdout.write(JSON.stringify(t.map(function(x){return m.terminalVerdict(x);})));"
        % (json.dumps(str(RENDERER)), json.dumps(str(fixtures)))
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
    assert "neither attested an outcome nor landed a commit" in v["plain"]
    assert "start a fresh run" in v["next"]
    assert 'data-run-next-step' in block(term)


@requires_node
def test_a_failure_before_the_gate_still_states_its_recorded_reason():
    """A run that never reached the gate is not a run with nothing to say.

    Reporting only "no Evidence Gate verdict was recorded" would read as an
    absence when the run actually recorded a reason.
    """
    v = verdict(run("failed", None,
                    error={"category": "worker_nonzero_exit", "message": "exit 1"}))
    assert "The worker stopped before finishing its task." in v["plain"]
    assert "No Evidence Gate verdict was recorded" in v["plain"]
    assert v["next"] == "Open the run log for what it reported, then re-run."


@requires_node
def test_a_recorded_outcome_is_never_contradicted_by_the_failure_code():
    """Both sentences narrate the worker, so only one of them may speak.

    A recorded outcome is the worker's own attestation and wins; pairing it
    with a code-derived sentence produced paragraphs that argued with
    themselves. The code is not lost -- it stays in the next step and in the
    technical detail.
    """
    contradictions = {
        "completed": "The worker stopped before finishing its task.",
        "declined": "The worker stopped before finishing its task.",
        "no_result": "The worker stopped before finishing its task.",
        "unattested": "The worker stopped before finishing its task.",
    }
    for outcome, sentence in contradictions.items():
        for status in ("succeeded", "failed", "cancelled", "blocked"):
            v = verdict(run(status, outcome,
                            error={"category": "worker_nonzero_exit", "message": "exit 1"}))
            assert sentence not in v["plain"], (status, outcome)
            assert v["next"] == "Open the run log for what it reported, then re-run."


@requires_node
def test_no_verdict_pairs_two_sentences_that_argue_with_each_other(tmp_path):
    """Sweep the whole cross-product rather than trusting the branches read.

    Each of the four recorded outcomes has a claim that no other outcome's
    sentence may appear beside.
    """
    exclusive = {
        "completed": ["ran to the end and recorded no result", "declined this task",
                      "reported nothing at all"],
        "declined": ["reported that it finished the task", "ran to the end and recorded no result"],
        "no_result": ["reported that it finished the task", "declined this task"],
        "unattested": ["reported that it finished the task", "declined this task"],
    }
    codes = [None, "worker_nonzero_exit", "commit_predates_run", "no_attested_outcome",
             "commit_missing", "artifact_policy_missing", "not_a_known_code"]
    gates = [None, "commit_correlated", "commit_correlation_failed", "skipped"]
    statuses = ("succeeded", "failed", "cancelled", "blocked", "review_submitted")
    cases = [run(status, outcome, gate=gate,
                 error=None if code is None else {"category": code, "message": "m"})
             for outcome in exclusive
             for status in statuses
             for code in codes
             for gate in gates]
    # One node process for the whole cross-product: 560 fixtures is a sweep,
    # not 560 separate interpreter starts.
    for term, v in zip(cases, verdicts(cases, tmp_path)):
        for phrase in exclusive[term["outcome"]]:
            assert phrase not in v["plain"], (term["status"], term["outcome"],
                                              term["error"], term["evidence_gate"], phrase)


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
    """Debugging needs the raw code, run id and gate verdict -- one click away.

    Asserted against the panel's own markup expression rather than the whole
    file: `"gateRows(term)"` alone would also match the function's definition
    line, so removing the call would not fail this test.
    """
    panel = source[source.index("function renderTerminal("):]
    assert '<details class="run-detail">' in panel
    assert "data-run-error-code" in panel
    assert 'row("Run", term.run_id)' in panel
    assert 'row("Worker outcome", term.outcome)' in panel
    assert "gateRows(term) +" in panel


def test_the_two_top_level_warnings_are_not_collapsed_behind_the_summary(source):
    """A statement about how far the panel can be trusted must stay visible.

    `conflicting` and `incomplete` say the panel's own content may be wrong.
    Collapsing either behind the detail summary would downgrade it silently,
    which is the failure mode this whole change exists to remove.
    """
    panel = source[source.index("function renderTerminal("):]
    detail_at = panel.index('<details class="run-detail">')
    for warning in ("Sources disagree on this run", "Incomplete or unverified evidence"):
        assert panel.index(warning) < detail_at, warning


def test_the_evidence_hooks_the_acceptance_matrix_reads_are_unchanged(source):
    for hook in ("data-run-terminal", "data-run-status", "data-run-activity",
                 "data-run-freshness", "data-run-live"):
        assert hook in source


def test_the_presentation_boundary_holds(source):
    """W2 renders what the projection recorded and decides nothing itself.

    A source guard, not a proof: it pins that the verdict is computed from the
    projection's own fields against fixed keys, with no I/O, no persistence and
    no transition on this path. The stronger evidence is the behavioural tests
    above, which show the verdict is a pure function of its input.
    """
    terminal = source[source.index("function terminalVerdict("):source.index("function verdictBlock(")]
    reader = source[source.index("function workerOutcome("):source.index("var PROCESS_PHRASES")]
    for forbidden in ("fetch(", "XMLHttpRequest", "POST", "workflow:", "localStorage",
                      "innerHTML", "OSRenderer", "outcome ="):
        assert forbidden not in terminal, forbidden
        assert forbidden not in reader, forbidden
    # The projection's own fields, read against fixed key sets and nothing else.
    # Scoped to the two functions that do the reading -- asserted against the
    # whole file, `term.outcome` would also be satisfied by this file's header
    # comment and by the detail view's row.
    assert "term.outcome" in reader
    assert "has(WORKER_OUTCOME_TERMS" in reader
    for field in ("t.status", "t.error", "t.evidence_gate"):
        assert field in terminal, field
    assert "has(ERROR_GUIDANCE" in terminal and "ERROR_GUIDANCE[" in terminal


@requires_node
def test_an_outcome_colliding_with_an_object_prototype_key_is_not_interpreted():
    """`WORKER_OUTCOME_TERMS` is a plain object, so a bare property lookup
    would resolve inherited keys and dress `constructor` up as a known outcome.
    """
    for hostile in ("constructor", "toString", "hasOwnProperty", "__proto__"):
        v = verdict(run("succeeded", hostile))
        assert v["outcomeLabel"] == "not recognised", hostile
        assert v["tone"] == "warn", hostile


def test_the_narrow_layout_stacks_the_fact_list():
    """The narrow rule exists and uses the house breakpoint.

    That the panel does not scroll sideways at 380px was checked by rendering
    it, not by this test; this only pins the rule against a silent removal.
    """
    css = CSS.read_text(encoding="utf-8")
    assert "@media(max-width:720px){.run-verdict-facts{grid-template-columns:1fr" in css
    assert ".run-verdict-facts{display:grid;grid-template-columns:max-content 1fr" in css


def test_the_gloss_is_styled_apart_from_the_monospace_value():
    """The outcome's plain-language gloss reads as prose, not as an identifier."""
    css = CSS.read_text(encoding="utf-8")
    assert ".run-verdict-gloss{" in css
    assert "font-family:var(--sans)" in css[css.index(".run-verdict-gloss{"):][:120]


def test_the_served_mirrors_are_byte_equal():
    """`site/public/widgets/*` is a byte-identical mirror of the widget source.

    W2, W3 and W7 all change both copies and nothing on main caught a one-sided
    edit; this is that parity check.
    """
    assert MIRROR.read_bytes() == RENDERER.read_bytes()
    assert CSS_MIRROR.read_bytes() == CSS.read_bytes()
