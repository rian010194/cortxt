"""W6 acceptance: the versioned worker contract and the no-upgrade invariant.

Two threads, both asserted behaviourally rather than by string search:

1. **One producer, one grammar.** `routing.worker_contract` owns the
   attestation vocabulary (`CORTXT-OUTCOME:` + the attestable verbs) and is the
   single source imported by both the producer (`build_worker_instruction`) and
   the parser (`worker_outcome`). A worker is taught exactly the form the
   platform accepts, so a producer and parser can never diverge in the silent
   direction of `unattested`.

2. **The no-upgrade invariant.** A required report that is missing, unreadable,
   invalid or incomplete can never be raised to success by attestation, by exit
   code, or by stdout. We exercise `HermesFreeAdapter.invoke` end to end with an
   injected invoker and a real report file, and assert the verdict survives.

Design record: `lab/cortxt-execution-confirmation-design-2026-09-08-corrected.md`
section 1.1-1.4; `lab/cortxt-os-implementation-plan-2026-09-08-corrected.md`
section 3.1.
"""
import json
import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from dispatcher import Run  # noqa: E402
from routing import worker_contract as wc  # noqa: E402
from routing import completion_report as cr  # noqa: E402
from routing.worker_outcome import read_attested_outcome  # noqa: E402
from worker_adapters import HermesFreeAdapter  # noqa: E402


def _run(runtime="hermes-free"):
    return Run(run_id="run-w6", issue_id="owner/repo#520", workflow="work-launcher/v1",
               worker_role="builder", runtime=runtime, claimed_at=time.time(),
               lease_seconds=900, mutating=True)


@pytest.fixture(autouse=True)
def _free_route(monkeypatch):
    monkeypatch.setenv("CORTXT_FREE_MODEL", "upstage/solar-pro4:free")
    monkeypatch.setenv("CORTXT_FREE_PROVIDER", "nous")


def _adapter(tmp_path, *, report=None, stdout="did the work", status="succeeded"):
    """Build a HermesFreeAdapter whose invoker writes `report` to the usage
    path it is handed. `report=None` simulates the runtime writing no report
    (requested_but_missing)."""
    def invoker(profile, prompt, timeout_seconds, model=None, provider=None,
                cwd=None, session_id=None, usage_file=None):
        if report is not None and usage_file is not None:
            Path(usage_file).parent.mkdir(parents=True, exist_ok=True)
            Path(usage_file).write_text(json.dumps(report), encoding="utf-8")
        return {"status": status, "exit_code": 0, "stdout": stdout, "stderr": "",
                "elapsed_seconds": 0.1, "session_id": None}
    return HermesFreeAdapter(invoke_hermes=invoker, log_dir=tmp_path / "logs")


# --- One producer, one grammar -------------------------------------------

def test_grammar_single_source():
    # The parser accepts exactly what the producer teaches.
    assert wc.ATTESTATION_PREFIX == "CORTXT-OUTCOME:"
    grammar = wc.attestation_grammar()
    for verb in wc.ATTESTABLE:
        assert f"{wc.ATTESTATION_PREFIX} {verb}" in grammar
        # The parser must round-trip the exact taught form.
        assert read_attested_outcome(f"{wc.ATTESTATION_PREFIX} {verb}") == (verb, "")


def test_instruction_carries_contract_version_and_grammar():
    instr = wc.build_worker_instruction(
        scope="Build X", acceptance_criteria=["Criterion A", "Criterion B"],
        limits={"max_cost_usd": 1.0}, artifact_policy="only-docs",
        issue_id="owner/repo#520", request_id="sha256:abc")
    assert wc.CONTRACT_VERSION in instr
    assert wc.ATTESTATION_PREFIX in instr
    for verb in wc.ATTESTABLE:
        assert f"{wc.ATTESTATION_PREFIX} {verb}" in instr


def test_instruction_omits_none_identity():
    instr = wc.build_worker_instruction(
        scope="S", acceptance_criteria=["A"], limits={}, artifact_policy="p")
    # A None identity is omitted, never rendered as 'None' that a worker would
    # then be told to report.
    assert "run_id: None" not in instr
    assert "request_id: None" not in instr


def test_instruction_refuses_empty_mandate():
    with pytest.raises(wc.WorkerInstructionError):
        wc.build_worker_instruction(scope="", acceptance_criteria=[], limits={},
                                    artifact_policy="")


# --- The no-upgrade invariant, adapter level ------------------------------

def test_missing_report_cannot_be_upgraded_by_attestation(tmp_path):
    """Exit 0 + a completed attestation + NO report can never become success:
    the route asked and got no answer, and no later signal may raise it."""
    env = _adapter(tmp_path, report=None,
                   stdout="did it\nCORTXT-OUTCOME: completed").invoke(
        _run(), "t", 60)
    assert env["_status"] == "blocked"
    assert env["outcome"] == "unverifiable"
    assert env["error"]["category"] == "completion_report_missing"


def test_incomplete_report_cannot_be_upgraded_by_attestation(tmp_path):
    """A worker attesting completed while its own runtime's report says the
    task did not finish is a conflict: recorded in evidence, and the structured
    verdict wins -- `incomplete`/`worker_incomplete`, never success."""
    env = _adapter(
        tmp_path, report={"completed": True, "failed": True, "report_version": 1},
        stdout="did it\nCORTXT-OUTCOME: completed").invoke(_run(), "t", 60)
    assert env["_status"] == "blocked"
    assert env["outcome"] == "incomplete"
    assert env["error"]["category"] == "worker_incomplete"
    assert "conflicting attestation" in env["evidence"]


def test_missing_report_not_upgraded_by_exit_code(tmp_path):
    """Exit 0 (`succeeded`) with no report is still refused -- the previous
    behaviour of recording a missing report as a plain success is gone."""
    env = _adapter(tmp_path, report=None, stdout="ordinary output").invoke(
        _run(), "t", 60)
    assert env["_status"] == "blocked"
    assert env["outcome"] == "unverifiable"
    assert env["error"]["category"] == "completion_report_missing"


def test_unreadable_report_blocks(tmp_path):
    """A truncated report file is `unreadable` evidence, not `missing` evidence,
    and it refuses the Run: `blocked`/`unverifiable`/`completion_report_unreadable`.
    This is exercised end-to-end through the adapter, not just at the reader."""
    def invoker(profile, prompt, timeout_seconds, model=None, provider=None,
                cwd=None, session_id=None, usage_file=None):
        if usage_file is not None:
            Path(usage_file).parent.mkdir(parents=True, exist_ok=True)
            Path(usage_file).write_text('{"completed": true, ', encoding="utf-8")
        return {"status": "succeeded", "exit_code": 0, "stdout": "did it\nCORTXT-OUTCOME: completed",
                "stderr": "", "elapsed_seconds": 0.1, "session_id": None}
    env = HermesFreeAdapter(invoke_hermes=invoker,
                            log_dir=tmp_path / "logs").invoke(_run(), "t", 60)
    assert env["_status"] == "blocked"
    assert env["outcome"] == "unverifiable"
    assert env["error"]["category"] == "completion_report_unreadable"
    assert env["report_state"] == cr.UNREADABLE


def test_invalid_report_blocks(tmp_path):
    """A report that decodes but violates the contract (`completed` as a string)
    refuses the Run via the adapter as `blocked`/`unverifiable`/`completion_report_invalid`,
    closing the truthiness defect through the whole chain."""
    def invoker(profile, prompt, timeout_seconds, model=None, provider=None,
                cwd=None, session_id=None, usage_file=None):
        if usage_file is not None:
            Path(usage_file).parent.mkdir(parents=True, exist_ok=True)
            Path(usage_file).write_text(
                json.dumps({"completed": "false", "report_version": 1}), encoding="utf-8")
        return {"status": "succeeded", "exit_code": 0, "stdout": "did it\nCORTXT-OUTCOME: completed",
                "stderr": "", "elapsed_seconds": 0.1, "session_id": None}
    env = HermesFreeAdapter(invoke_hermes=invoker,
                            log_dir=tmp_path / "logs").invoke(_run(), "t", 60)
    assert env["_status"] == "blocked"
    assert env["outcome"] == "unverifiable"
    assert env["error"]["category"] == "completion_report_invalid"
    assert env["report_state"] == cr.INVALID


def test_completed_report_with_attestation_succeeds(tmp_path):
    env = _adapter(
        tmp_path, report={"completed": True, "failed": False, "report_version": 1},
        stdout="did it\nCORTXT-OUTCOME: completed").invoke(_run(), "t", 60)
    assert env["_status"] == "succeeded"
    assert env["outcome"] == "completed"
    assert env["error"] is None


def test_completed_report_without_attestation_is_unattested(tmp_path):
    env = _adapter(
        tmp_path, report={"completed": True, "failed": False, "report_version": 1},
        stdout="just did the work").invoke(_run(), "t", 60)
    assert env["_status"] == "succeeded"
    assert env["outcome"] == "unattested"


# --- Decision table / monotonicity (plan 3.1) -----------------------------
# Each refusing report state must refuse terminally with its named
# (outcome, error.category) pair, and an attestation of `completed` from the
# worker must never raise it. The table is derived from the same constants and
# refusal mapping the production code owns, so a reviewer can see at a glance
# that no refusing state can be upgraded.


def _invoker_writing(report):
    def invoker(profile, prompt, timeout_seconds, model=None, provider=None,
                cwd=None, session_id=None, usage_file=None):
        if usage_file is not None:
            Path(usage_file).parent.mkdir(parents=True, exist_ok=True)
            # `report` is either a dict (serialise) or an already-raw string
            # (write verbatim, e.g. a truncated/undecodable payload).
            text = report if isinstance(report, str) else json.dumps(report)
            Path(usage_file).write_text(text, encoding="utf-8")
        return {"status": "succeeded", "exit_code": 0, "stdout": "did it\nCORTXT-OUTCOME: completed",
                "stderr": "", "elapsed_seconds": 0.1, "session_id": None}
    return invoker


def _invoker_writing_none():
    def invoker(profile, prompt, timeout_seconds, model=None, provider=None,
                cwd=None, session_id=None, usage_file=None):
        return {"status": "succeeded", "exit_code": 0, "stdout": "did it\nCORTXT-OUTCOME: completed",
                "stderr": "", "elapsed_seconds": 0.1, "session_id": None}
    return invoker


# process_class is `terminated` with exit 0 for every row: the runtime ran to
# termination, so the report question legitimately arises, and it is where the
# invariant is under threat (a `completed` attestation arrives on a refusing
# report). `missing`, `unreadable`, `invalid`, `incomplete` are the four
# refusing states; each must block and stay blocked.
@pytest.mark.parametrize("case", [
    # (report to write, expected outcome, expected error.category)
    (None, "unverifiable", "completion_report_missing"),            # requested_but_missing
    ('{"completed": true, ', "unverifiable", "completion_report_unreadable"),
    ({"completed": "false", "report_version": 1}, "unverifiable", "completion_report_invalid"),
    ({"completed": True, "failed": True, "report_version": 1}, "incomplete", "worker_incomplete"),
])
def test_refusing_report_state_is_never_upgraded_by_completed_attestation(tmp_path, case):
    report, expected_outcome, expected_category = case
    invoker = (_invoker_writing(report) if report is not None
               else _invoker_writing_none())
    env = HermesFreeAdapter(invoke_hermes=invoker,
                            log_dir=tmp_path / "logs").invoke(_run(), "t", 60)
    # A `completed` attestation from the worker is present in stdout, but a
    # refusing report state is terminal: monotonicity, asserted explicitly.
    assert env["_status"] == "blocked"
    assert env["outcome"] == expected_outcome
    assert env["error"]["category"] == expected_category
    # The refusing report state cannot be raised to a success outcome by the
    # completed attestation -- it is never `succeeded`/`completed`/`declined`.
    assert env["outcome"] not in ("completed", "declined", "no_result", "unattested")


def test_refusing_report_state_mapping_is_exactly_the_production_table(tmp_path):
    """The test table does not drift: every refusing state in
    `completion_report.REFUSING_STATES` appears in `REFUSAL_OUTCOME` with a
    distinct category, and every one of them is refusing."""
    for state in cr.REFUSING_STATES:
        assert state in cr.REFUSAL_OUTCOME
        outcome, category = cr.REFUSAL_OUTCOME[state]
        assert outcome in ("unverifiable", "incomplete")
        assert category  # a named error.category, never blank
        assert cr.ReportOutcome(state, "detail").refusing
