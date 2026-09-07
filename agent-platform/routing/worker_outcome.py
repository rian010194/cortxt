"""What a worker actually did, as distinct from how its process terminated.

Part of #520. `invoke_hermes` reports `succeeded` whenever the process exits 0,
and `docs/architecture/dispatch-contract.md` already states the principle that
contradicts: "Self-reported status is not evidence." Three of four real Runs on
`7534301` reported `succeeded` having accomplished nothing.

The split this module makes is epistemic, not cosmetic. Two shapes of "exited 0
without doing the work" were observed, and only one of them is knowable from
outside the worker:

- A provider that returned nothing usable. That is a property of the *response*,
  so the adapter can see it. `classify_transport_outcome` is that reading.
- A worker that understood the task and deliberately declined to act
  (`run-24c8421b68124e35b4663c3e808762ec`: 2804 bytes of correct reasoning about
  a contradiction between an Issue's labels and its body). That is *semantic*.
  Nothing outside the worker can distinguish it from a rambling failure without
  reading prose.

So this module never infers a semantic outcome from text. Guessing at intent by
matching phrases would be a heuristic whose failures are invisible in green
tests -- the same defect shape this work exists to remove. A worker that wants
to claim an outcome must say so through `read_attested_outcome`; everything
else is `unattested`, which is an honest answer and not a failure.

`unattested` is resolved elsewhere, not here: on a mutating Run the Evidence
Gate settles it, because a correlated commit is better attestation than a
worker's own word about itself.

Design record: `lab/brief-520-worker-outcome.md`.
"""
from __future__ import annotations

# Emitted by the hermes CLI or by the provider -- `grep -rn` over this
# repository finds it nowhere, so the string belongs to a contract we do not
# own. Matching is exact and case-sensitive for that reason: a loose match
# would be guessing at someone else's output format.
TRUNCATION_MARKERS: tuple[str, ...] = (
    "Response truncated due to output length limit",
)

#: The verb a worker may attest, and what each means. `completed` and
#: `declined` can only ever arrive by attestation; the other two are what the
#: adapter concludes when no attestation is available.
OUTCOMES: tuple[str, ...] = ("completed", "declined", "no_result", "unattested")

_ATTESTATION_PREFIX = "CORTXT-OUTCOME:"
_ATTESTABLE: tuple[str, ...] = ("completed", "declined")


def classify_transport_outcome(stdout: str, stderr: str) -> str:
    """Return "no_result" or "unattested" from transport evidence alone.

    Never returns "completed" or "declined": those are semantic and only a
    worker may attest to them (see the module docstring). `stderr` is part of
    the signature because a caller holds both and a future transport signal may
    live there; it is deliberately not consulted today, since a worker that
    wrote to stderr and still produced usable stdout has not failed.
    """
    if not (stdout or "").strip():
        return "no_result"
    if any(marker in stdout for marker in TRUNCATION_MARKERS):
        return "no_result"
    return "unattested"


def read_attested_outcome(stdout: str) -> tuple[str, str] | None:
    """Return `(outcome, reason)` if the worker declared one, else None.

    The declaration is the last non-empty line of stdout, of exactly the form
    `CORTXT-OUTCOME: completed` or `CORTXT-OUTCOME: declined <reason>`.

    Anything else -- absent, malformed, an unknown verb, or present but not on
    the last non-empty line -- returns None, and the caller falls through to
    `classify_transport_outcome`. An unparseable claim is not a claim: a worker
    that half-declares an outcome is in exactly the position of one that
    declared nothing, and must not be credited with the outcome it was reaching
    for.

    The channel is defined and tested before any worker profile emits it, so
    that it is not invented differently in three places later.
    """
    lines = [line for line in (stdout or "").splitlines() if line.strip()]
    if not lines:
        return None
    last = lines[-1].strip()
    if not last.startswith(_ATTESTATION_PREFIX):
        return None
    body = last[len(_ATTESTATION_PREFIX):].strip()
    if not body:
        return None
    verb, _, reason = body.partition(" ")
    if verb not in _ATTESTABLE:
        return None
    return verb, reason.strip()
