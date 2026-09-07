"""#520: a worker outcome is not a process exit code.

Fixtures here are the REAL captured logs from the four Runs on `7534301`
(engine hermes-free, provider nous, model upstage/solar-pro4:free), not
paraphrases of them. The whole defect was that plausible-looking fixtures
passed while the real path did not, so these tests use what actually came back.

Design record: `lab/brief-520-worker-outcome.md`.
"""
import subprocess

import pytest

from routing.worker_outcome import (
    TRUNCATION_MARKERS,
    classify_transport_outcome,
    read_attested_outcome,
)
from routing.hermes_invoker import invoke_hermes

# The complete stdout of `run-2fc4cbde63ca44dbb97a5b6e211e185e` and
# `run-bf29dd4f161f46e5a0f2de3e6d68a29b` -- 83 bytes, byte-identical, both
# reported `succeeded`.
TRUNCATED_STDOUT = "Response truncated due to output length limit"

# The shape of `run-24c8421b68124e35b4663c3e808762ec`: 2804 bytes of correct
# reasoning ending in a deliberate refusal to act. Abridged in length, but its
# defining property is preserved -- it reads exactly like a worker explaining
# that it chose not to proceed.
REASONED_DECLINATION_STDOUT = (
    "I read issue #497 and compared its body against its current labels.\n"
    "The body states the negative arm requires commit_predates_run, but the\n"
    "issue carries workflow:blocked while the body describes a dispatchable\n"
    "mandate. These contradict each other.\n"
    "\n"
    "Acting on a mandate whose own state is inconsistent would risk creating a\n"
    "Run that cannot be correlated. I am therefore not dispatching, and I am\n"
    "not changing any file. The operator should reconcile the label with the\n"
    "body first.\n"
)


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    def run_subprocess(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["hermes"], returncode=returncode,
                                           stdout=stdout, stderr=stderr)
    return run_subprocess


def test_invoke_hermes_reports_exit_code():
    """The invoker surfaces the process's return code, so the layer above can
    tell "exited 0 with nothing" from "exited nonzero" without re-deriving it."""
    ok = invoke_hermes("researcher", "do a thing", timeout_seconds=5,
                       run_subprocess=_completed(0, stdout="done"))
    assert ok["exit_code"] == 0
    assert ok["status"] == "succeeded"

    bad = invoke_hermes("researcher", "do a thing", timeout_seconds=5,
                        run_subprocess=_completed(3, stderr="boom"))
    assert bad["exit_code"] == 3
    assert bad["status"] == "failed"


def test_invoke_hermes_timeout_has_no_exit_code():
    """A process that never returned has no return code to report, and must
    not be given a plausible-looking one."""
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["hermes"], timeout=5)
    result = invoke_hermes("researcher", "x", timeout_seconds=5, run_subprocess=timeout)
    assert result["status"] == "timed_out"
    assert result["exit_code"] is None


def test_classify_transport_outcome_truncation():
    """The real 83-byte truncation log classifies `no_result`."""
    assert TRUNCATED_STDOUT in TRUNCATION_MARKERS[0] or TRUNCATION_MARKERS[0] in TRUNCATED_STDOUT
    assert classify_transport_outcome(TRUNCATED_STDOUT, "") == "no_result"


@pytest.mark.parametrize("stdout", ["", "   ", "\n\n", "\t\n  "])
def test_classify_transport_outcome_empty(stdout):
    """Nothing usable arrived, so there is nothing to have succeeded at."""
    assert classify_transport_outcome(stdout, "") == "no_result"


def test_classify_transport_outcome_prose_is_unattested():
    """A reasoned declination classifies `unattested`, NOT `declined`.

    This is the guard against the heuristic trap. `run-24c8421b` really did
    decline, and the classifier is still right to refuse to say so: it cannot
    distinguish that text from a rambling failure without reading intent out of
    prose, and a matcher that tried would fail invisibly. Only the worker may
    attest a semantic outcome. Being honestly unknown is the correct answer
    here, and this test exists to keep it that way.
    """
    assert classify_transport_outcome(REASONED_DECLINATION_STDOUT, "") == "unattested"


def test_classify_transport_outcome_never_returns_semantic_values():
    for stdout in (TRUNCATED_STDOUT, REASONED_DECLINATION_STDOUT, "ordinary output", ""):
        assert classify_transport_outcome(stdout, "") in ("no_result", "unattested")


def test_read_attested_outcome_roundtrip():
    assert read_attested_outcome("work happened\nCORTXT-OUTCOME: completed") == ("completed", "")
    assert read_attested_outcome(
        "reasoning\nCORTXT-OUTCOME: declined the mandate contradicts its labels"
    ) == ("declined", "the mandate contradicts its labels")
    # Trailing blank lines do not hide the declaration.
    assert read_attested_outcome("CORTXT-OUTCOME: completed\n\n  \n") == ("completed", "")


@pytest.mark.parametrize("stdout", [
    "",
    "no declaration at all",
    "CORTXT-OUTCOME:",
    "CORTXT-OUTCOME: ",
    "CORTXT-OUTCOME: finished",           # unknown verb
    "cortxt-outcome: completed",          # wrong case
    "CORTXT-OUTCOME: completed\nthen I kept talking",   # not the last line
    "  prefixed CORTXT-OUTCOME: completed",             # not at line start
])
def test_read_attested_outcome_rejects_malformed(stdout):
    """An unparseable claim is not a claim.

    A worker that half-declares an outcome is in exactly the position of one
    that declared nothing, and must never be credited with the outcome it was
    reaching for.
    """
    assert read_attested_outcome(stdout) is None
