"""S7 (#520): the adapter envelope and the gate's refusal name what happened.

Covers the two halves of the fix that live outside `routing.worker_outcome`:
the `HermesFreeAdapter` envelope (`scripts/worker_adapters.py`) and the Evidence
Gate's refusal category (`scripts/dispatcher.py:_gate_commit`).

The property these tests exist to hold, from `lab/brief-520-worker-outcome.md`:
**no Run accepted today becomes refused, and no Run refused today becomes
accepted.** Only the stated cause changes, and two refusals move upstream of
the gate. `test_gate_accepts_unattested_with_correlated_commit` is the
regression guard for the first half of that promise.
"""
import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from commit_evidence import CorrelationFailure  # noqa: E402
from dispatcher import Dispatcher, Run, RunRegistry  # noqa: E402
from worker_adapters import HermesFreeAdapter  # noqa: E402

TRUNCATED_STDOUT = "Response truncated due to output length limit"


def _run(tmp_path, run_id="run-test", mutating=False, **extra):
    return Run(run_id=run_id, issue_id="owner/repo#520", workflow="work-launcher/v1",
               worker_role="builder", runtime="hermes-free", claimed_at=time.time(),
               lease_seconds=900, mutating=mutating, **extra)


def _adapter(tmp_path, *, status="succeeded", stdout="", stderr="", exit_code=0):
    return HermesFreeAdapter(
        invoke_hermes=lambda profile, prompt, timeout_seconds, model=None,
        provider=None, cwd=None, session_id=None: {
            "status": status, "exit_code": exit_code, "stdout": stdout,
            "stderr": stderr, "elapsed_seconds": 0.1, "session_id": None,
        },
        log_dir=tmp_path / "logs",
    )


@pytest.fixture(autouse=True)
def _free_route(monkeypatch):
    monkeypatch.setenv("CORTXT_FREE_MODEL", "upstage/solar-pro4:free")
    monkeypatch.setenv("CORTXT_FREE_PROVIDER", "nous")


# --- the adapter envelope -------------------------------------------------

def test_hermes_free_adapter_blocks_no_result(tmp_path):
    """The real 83-byte truncation is refused at the adapter, before the gate,
    and the run log is still written so the operator can see what arrived."""
    envelope = _adapter(tmp_path, stdout=TRUNCATED_STDOUT).invoke(
        _run(tmp_path), "do the task", timeout_seconds=60)

    assert envelope["_status"] == "blocked"
    assert envelope["outcome"] == "no_result"
    assert envelope["error"]["category"] == "provider_returned_no_result"
    # The log is written before classification, so a blocked Run keeps evidence.
    assert (tmp_path / "logs" / "run-test.log").is_file()
    assert envelope["artifacts"] == ["run-log:run-test"]
    # Never the raw output, never a filesystem path.
    assert TRUNCATED_STDOUT not in envelope["error"]["recovery"]
    assert str(tmp_path) not in str(envelope)


def test_hermes_free_adapter_blocks_attested_declination(tmp_path):
    envelope = _adapter(
        tmp_path,
        stdout="reasoning about the mandate\nCORTXT-OUTCOME: declined labels contradict the body",
    ).invoke(_run(tmp_path), "do the task", timeout_seconds=60)

    assert envelope["_status"] == "blocked"
    assert envelope["outcome"] == "declined"
    assert envelope["error"]["category"] == "worker_declined"
    assert "declined to act" in envelope["error"]["recovery"]


def test_declination_reason_never_reaches_the_envelope(tmp_path):
    """The worker's stated reason stays in the local run log.

    `error.recovery` reaches a GitHub issue comment, and CLAUDE.md rule 2
    forbids model output there -- the rule every other `recovery` in this
    adapter follows by pointing at the log instead (#58/#71). The category
    tells the operator this was a decision rather than a failure; the log
    tells them what the decision was.
    """
    reason = "the mandate contradicts itself in paragraph four"
    envelope = _adapter(
        tmp_path, stdout="long reasoning here\nCORTXT-OUTCOME: declined " + reason,
    ).invoke(_run(tmp_path), "do the task", timeout_seconds=60)

    assert envelope["outcome"] == "declined"
    assert reason not in str(envelope)
    assert "paragraph four" not in str(envelope)


def test_evidence_reports_the_runtime_verdict_not_the_adapter_conclusion(tmp_path):
    """`evidence` must never attribute this adapter's decision to hermes-free.

    The runtime reported `succeeded`; the adapter blocked it. Writing
    "hermes-free reported status=blocked" would be a false claim about the
    runtime in the one field that reaches GitHub -- the exact misreporting
    #520 exists to stop.
    """
    envelope = _adapter(tmp_path, stdout=TRUNCATED_STDOUT).invoke(
        _run(tmp_path), "do the task", timeout_seconds=60)

    assert envelope["_status"] == "blocked"
    assert "reported status=succeeded" in envelope["evidence"]
    assert "reported status=blocked" not in envelope["evidence"]
    assert "outcome=no_result" in envelope["evidence"]


def test_hermes_free_adapter_ordinary_success_is_unattested(tmp_path):
    """Real output with no declaration still succeeds -- and says it was never
    attested, rather than claiming the worker reported completion."""
    envelope = _adapter(tmp_path, stdout="I made the change and committed it.").invoke(
        _run(tmp_path), "do the task", timeout_seconds=60)

    assert envelope["_status"] == "succeeded"
    assert envelope["outcome"] == "unattested"
    assert envelope["error"] is None


def test_hermes_free_adapter_attested_completion(tmp_path):
    envelope = _adapter(tmp_path, stdout="did it\nCORTXT-OUTCOME: completed").invoke(
        _run(tmp_path), "do the task", timeout_seconds=60)

    assert envelope["_status"] == "succeeded"
    assert envelope["outcome"] == "completed"


def test_hermes_free_adapter_nonzero_exit_unchanged(tmp_path):
    """The pre-existing failure arm is untouched apart from `outcome: None`.

    A process that exited nonzero never reached a worker outcome, so there is
    none to have -- and this arm must not start being classified.
    """
    envelope = _adapter(tmp_path, status="failed", exit_code=3,
                        stderr="boom").invoke(
        _run(tmp_path), "do the task", timeout_seconds=60)

    assert envelope["_status"] == "failed"
    assert envelope["outcome"] is None
    assert envelope["error"]["category"] == "worker_nonzero_exit"
    assert "boom" not in str(envelope)


def test_hermes_free_adapter_timeout_unchanged(tmp_path):
    envelope = _adapter(tmp_path, status="timed_out", exit_code=None).invoke(
        _run(tmp_path), "do the task", timeout_seconds=60)

    assert envelope["_status"] == "timed_out"
    assert envelope["outcome"] is None
    assert envelope["error"]["category"] == "timed_out"


# --- the gate's refusal category ------------------------------------------

def _gate(tmp_path, gate_result, envelope, *, mutating=True):
    """Drive `_gate_commit` directly with an injected gate verdict.

    The gate itself is not under test here -- it refused all four real Runs
    correctly and `scripts/commit_evidence.py` is untouched. What is under test
    is how a refusal it already made gets named.
    """
    registry = RunRegistry(tmp_path / "runs.json")
    dispatcher = Dispatcher(registry=registry, gh=object(),
                            commit_gate=lambda run, env: gate_result)
    run = _run(tmp_path, run_id="run-gate", mutating=mutating)
    registry.add(run)
    return dispatcher._gate_commit(run, "succeeded", envelope)


def test_gate_renames_unattested_refusal(tmp_path):
    """`commit_predates_run` is the symptom; `no_attested_outcome` is the cause.

    The verdict is unchanged -- this Run was already being refused. Only the
    name changes, and the original correlation code survives in `detail`.
    """
    failure = CorrelationFailure(
        "commit_predates_run",
        "the commit is not strictly after the claim",
        "Start a fresh run.")
    status, envelope, evidence = _gate(
        tmp_path, failure, {"outcome": "unattested", "status": "succeeded"})

    assert status == "blocked"
    assert evidence is None
    assert envelope["evidence_gate"] == "commit_correlation_failed"
    assert envelope["error"]["category"] == "no_attested_outcome"
    assert envelope["error"]["detail"] == "the commit is not strictly after the claim"


def test_gate_keeps_other_failure_codes_unchanged(tmp_path):
    """Only the two codes that mean "nothing landed" are renamed."""
    failure = CorrelationFailure("commit_not_on_branch", "detail", "recovery")
    _status, envelope, _ = _gate(
        tmp_path, failure, {"outcome": "unattested", "status": "succeeded"})

    assert envelope["error"]["category"] == "commit_not_on_branch"


def test_gate_does_not_rename_an_attested_run(tmp_path):
    """A worker that attested completion and landed nothing is a different
    problem from one that attested nothing, and must not be relabelled."""
    failure = CorrelationFailure("commit_predates_run", "detail", "recovery")
    _status, envelope, _ = _gate(
        tmp_path, failure, {"outcome": "completed", "status": "succeeded"})

    assert envelope["error"]["category"] == "commit_predates_run"


def test_gate_accepts_unattested_with_correlated_commit(tmp_path):
    """The `run-14d3cb02` shape: unattested, but it committed.

    This is the regression guard for the brief's promise that nothing accepted
    today becomes refused. A correlated commit outranks a worker's word about
    itself, so an unattested Run that landed one still succeeds.
    """
    class _Evidence:
        def as_record(self):
            return {"commit": "90ba45d" + "0" * 33, "branch": "work/run-gate"}

    status, envelope, evidence = _gate(
        tmp_path, _Evidence(), {"outcome": "unattested", "status": "succeeded"})

    assert status == "succeeded"
    assert evidence is not None
    assert envelope["evidence_gate"] == "commit_correlated"


def test_non_mutating_unattested_is_not_blocked(tmp_path):
    """A research Run has no commit expectation and no attestation channel;
    blocking it would fail every research dispatch."""
    status, envelope, evidence = _gate(
        tmp_path, CorrelationFailure("commit_missing", "d", "r"),
        {"outcome": "unattested", "status": "succeeded"}, mutating=False)

    assert status == "succeeded"
    assert evidence is None
    assert "evidence_gate" not in envelope
