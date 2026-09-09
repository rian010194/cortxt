"""What the platform managed to verify about a Run, as distinct from what the
worker said about itself.

Part of W6. `worker_outcome` answers "what did the worker do" from text the
worker wrote. This module answers a different and stronger question: did the
runtime itself state, in a machine-readable file the platform asked for and
whose creation the platform bounded, that it finished the task?

The two questions must not share a field. A route that never had a structured
channel and a route whose channel returned garbage are opposite situations, and
collapsing them into one `outcome` value destroys the difference -- which is
exactly how a truncated `usage.json` was recorded `succeeded` in the shape #520
exists to prevent.

Six states, one per Run, assigned by this module BEFORE attestation or stdout
is consulted at all. Four of them refuse terminally and cannot be raised by any
later signal; see `is_refusing` and the no-upgrade invariant below.

Why the strictness is not paranoia, in the words of the evidence:

- hermes writes its report best-effort and swallows every exception
  (`hermes_cli/oneshot.py:165-166`), so an absent file is a real and expected
  shape -- and it carries exactly zero information about whether the task
  finished. A route that asked a question and got no answer has not received a
  yes.
- The Run being classified may have died mid-stream, so a partial write is the
  most likely malformed shape. A partial write is *unreadable* evidence, never
  *absent* evidence, and the two may not share a constant.
- A type this reader does not understand is not a verdict. `completed: "false"`
  is `invalid`, not `completed` -- the truthiness defect that made the string
  `"false"` read as success in the unmerged predecessor
  (`completion_report.py:47`, branch `fix/hermes-completion-signal-520`).

**This is a re-derivation, not a cherry-pick.** The unmerged branch's module was
read and its four confirmed defects are each closed here by construction:
truthiness (fixed by `is True` / `is False` / else-invalid), every failure
collapsing into one non-refusing constant (fixed by six states of which four
refuse), no correlation to the invocation (fixed by `_correlated`), and the
vocabulary invented at a call site (fixed by exporting the constants that the
callers must use). None of its code is copied.

Design record: `lab/cortxt-execution-confirmation-design-2026-09-08-corrected.md` §1.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

#: The report contract version this reader implements. A report naming a
#: version this reader does not implement is `INVALID` and fails closed, which
#: is the required behaviour for an external contract on one host: a hermes
#: upgrade that changes the shape must stop the line, not be guessed at.
REPORT_VERSION = 1

# --- The six states -------------------------------------------------------
# Named constants, exported. The predecessor's fourth defect was a caller
# inventing the string "unverifiable" at the call site, in a module that owned
# the vocabulary; nothing here may be spelled at a call site.

#: The resolved route declares no structured channel, so none was offered and
#: none is owed. NOT a refusal, and must never be rendered as one.
NOT_REQUESTED = "not_requested"
#: The channel was requested, the runtime terminated, and no file exists.
REQUESTED_BUT_MISSING = "requested_but_missing"
#: A file exists but cannot be decoded -- OSError, decode error, bad JSON,
#: or a truncated write.
UNREADABLE = "unreadable"
#: The file decodes but violates the report contract, including a failed
#: correlation to this invocation.
INVALID = "invalid"
#: Valid, correlated, and states the task did not finish.
INCOMPLETE = "incomplete"
#: Valid, correlated, `failed` is not True, and `completed is True`.
COMPLETED = "completed"

REPORT_STATES: tuple[str, ...] = (
    NOT_REQUESTED, REQUESTED_BUT_MISSING, UNREADABLE, INVALID, INCOMPLETE, COMPLETED,
)

#: The states that terminally refuse. A Run in one of these can never be
#: raised to success by attestation, exit code, stdout, transport
#: classification, the Evidence Gate, or a downstream projection default.
REFUSING_STATES: tuple[str, ...] = (
    REQUESTED_BUT_MISSING, UNREADABLE, INVALID, INCOMPLETE,
)

#: The worker `outcome` and `error.category` each refusing state produces.
#: A single table so no call site can pick a different pair, and so the
#: mapping is readable in one place by a reviewer asking "can this be a
#: success?" -- the answer being visibly no for all four.
REFUSAL_OUTCOME: dict[str, tuple[str, str]] = {
    REQUESTED_BUT_MISSING: ("unverifiable", "completion_report_missing"),
    UNREADABLE: ("unverifiable", "completion_report_unreadable"),
    INVALID: ("unverifiable", "completion_report_invalid"),
    INCOMPLETE: ("incomplete", "worker_incomplete"),
}

# --- Which routes owe a report -------------------------------------------
# The design states this as a `report_channel` field on the execution profile.
# There are no execution profiles on `main`: `git grep execution_profile` over
# the ref returns nothing, and `routing/execution_model.py` exists only on the
# unmerged branch. The runtime id is what a Run actually carries
# (`dispatcher.Run.runtime`) and what `ADAPTER_REGISTRY` is keyed by, so the
# declaration lives here, keyed the same way, until profiles land and it moves
# onto them. Declaring a channel remains a reviewable property of a catalog in
# one place, which was the point of putting it on the profile.

CHANNEL_STRUCTURED = "structured"
CHANNEL_NONE = "none"

#: Every runtime that can be dispatched declares exactly one channel.
#:
#: `hermes` / `hermes-free`: the installed hermes 0.18.2 accepts `--usage-file`
#: (`hermes_cli/_parser.py:116`) and writes `completed` and `failed` alongside
#: cost and identity fields (`hermes_cli/oneshot.py:126-165`).
#:
#: `dsh`: declares none, citing its own adapter's terminal envelope, which
#: states the SDK result reports no usage (`worker_adapters.py`, the DSH
#: terminal branch). The SDK is not going to acquire a channel because a test
#: needs one.
REPORT_CHANNELS: dict[str, str] = {
    "hermes": CHANNEL_STRUCTURED,
    "hermes-free": CHANNEL_STRUCTURED,
    "hermes-researcher": CHANNEL_STRUCTURED,
    "hermes-coordinator": CHANNEL_STRUCTURED,
    "dsh": CHANNEL_NONE,
}


def report_channel(runtime: str) -> str:
    """The channel the named runtime declares.

    An unknown runtime declares `structured`, deliberately. The alternative --
    defaulting an unrecognised runtime to "owes nothing" -- means any adapter
    registered later is silently exempt from the contract on the day it is
    added, which is the failure mode this catalog exists to make impossible.
    Fail closed: a new runtime must state its channel to be exempt from one.
    """
    return REPORT_CHANNELS.get(runtime, CHANNEL_STRUCTURED)


# --- Process classes ------------------------------------------------------
# Requirement is a property of (channel, process class) and of nothing else --
# not of the launch path. All three supported paths resolve the same runtime
# and inherit the same requirement.

#: Carrier or configuration absent; the adapter refused before invoking.
NEVER_LAUNCHED = "never_launched"
#: The invocation raised before returning.
INVOCATION_RAISED = "invocation_raised"
#: The subprocess was killed by the lease.
TIMED_OUT = "timed_out"
#: The runtime ran to termination and returned a status.
TERMINATED = "terminated"

#: The classes that never reached a runtime, so no report is owed and -- for
#: `timed_out` -- none may be read. A file written by a process killed
#: mid-write is exactly the truncated artifact `UNREADABLE` exists to name; a
#: timeout is settled by the timeout, and reading its residue can only weaken
#: that verdict. W4's distinction is preserved here: a runtime that never
#: started is not a worker that failed, and neither is a report the platform
#: never asked for.
NO_RUNTIME_CLASSES: tuple[str, ...] = (NEVER_LAUNCHED, INVOCATION_RAISED, TIMED_OUT)


def report_required(runtime: str, process_class: str) -> bool:
    """Is a completion report required for this Run? Both conditions must hold."""
    if process_class in NO_RUNTIME_CLASSES:
        return False
    return report_channel(runtime) == CHANNEL_STRUCTURED


@dataclass(frozen=True)
class ReportOutcome:
    """The state assigned, plus what a reviewer needs to read it.

    `detail` names the violated rule and never the file's content: the report
    is written by a model-driven runtime and `error.recovery` reaches a GitHub
    issue comment, where CLAUDE.md forbids model output. `payload` carries the
    decoded report for an in-process consumer (W9 reads usage and cost from
    it) and is never projected.
    """

    state: str
    detail: str
    payload: dict | None = None

    @property
    def refusing(self) -> bool:
        return self.state in REFUSING_STATES


def _correlated(path: Path, *, invoked_after: float) -> bool:
    """Was this file created by the invocation that asked for it?

    The design specifies a per-invocation token written by the caller and
    checked by the reader. Hermes' report carries no field this platform can
    put a token in -- it writes a fixed key set and echoes nothing -- so the
    token form is not implementable against this external writer. The
    predecessor states the implementable minimum plainly: "at minimum assert
    the file was created by this call."

    That is what this is. The caller allocates a fresh per-invocation directory
    that did not exist before the call, and the file's modification time must
    fall inside the invocation window. A stale `usage.json` from a previous
    invocation is a worker choosing whether to be checked, which is precisely
    what the Evidence Gate's own wording refuses to allow
    (`commit_evidence.py:258-262`).

    The one-second slack absorbs filesystem timestamp granularity (FAT/exFAT
    resolve to two seconds; this is checked as a lower bound, so coarse
    granularity can only round a legitimate write *down* below the threshold).
    It cannot admit a stale file: the directory is created per invocation, so a
    file predating the call by more than the slack cannot be there at all.
    """
    try:
        return path.stat().st_mtime >= (invoked_after - 1.0)
    except OSError:
        return False


def read_completion_report(path: "str | os.PathLike[str]", *,
                           invoked_after: float) -> ReportOutcome:
    """Read a requested report and assign exactly one state.

    Never raises: every failure shape is a state. `invoked_after` is the
    monotonic-enough wall clock reading taken immediately before the runtime
    was invoked, and correlation is mandatory rather than opportunistic.
    """
    report_path = Path(path)
    try:
        raw = report_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ReportOutcome(
            REQUESTED_BUT_MISSING,
            "the route requested a completion report and the runtime wrote none")
    except (OSError, UnicodeDecodeError) as exc:
        return ReportOutcome(
            UNREADABLE,
            f"the completion report could not be read ({type(exc).__name__})")

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # A truncated write lands here, and it is unreadable evidence rather
        # than absent evidence. The two are separate constants on purpose.
        return ReportOutcome(
            UNREADABLE,
            "the completion report is not decodable JSON (a truncated write reads this way)")

    if not isinstance(payload, dict):
        return ReportOutcome(
            INVALID, "the completion report is not a JSON object")

    if not _correlated(report_path, invoked_after=invoked_after):
        # Checked after decoding so a stale file that is ALSO malformed is
        # reported as the correlation failure it is: the newer fact about a
        # file is which invocation wrote it.
        return ReportOutcome(
            INVALID,
            "the completion report does not correlate to this invocation")

    version = payload.get("report_version", REPORT_VERSION)
    if version != REPORT_VERSION:
        return ReportOutcome(
            INVALID,
            f"the completion report names version {version!r}, which this reader "
            f"does not implement")

    failed = payload.get("failed")
    if failed is not None and not isinstance(failed, bool):
        return ReportOutcome(
            INVALID, "the completion report's `failed` is not a boolean")
    completed = payload.get("completed")
    if completed is None:
        return ReportOutcome(
            INVALID, "the completion report omits the required `completed` key")
    if not isinstance(completed, bool):
        # The truthiness defect, closed. `"false"` is a string, and a type this
        # reader does not understand is not a verdict.
        return ReportOutcome(
            INVALID, "the completion report's `completed` is not a boolean")

    if failed is True:
        return ReportOutcome(
            INCOMPLETE, "the runtime reported the task failed", payload)
    if completed is False:
        return ReportOutcome(
            INCOMPLETE, "the runtime reported the task did not complete", payload)
    return ReportOutcome(
        COMPLETED, "the runtime reported the task completed", payload)


def not_requested(runtime: str) -> ReportOutcome:
    """The state for a route that declares no structured channel.

    Recorded on the Run rather than left blank, so a reviewer sees that the
    route never had a channel instead of inferring agreement from silence.
    """
    return ReportOutcome(
        NOT_REQUESTED,
        f"the {runtime} route declares no structured completion channel")
