"""The one versioned instruction a worker is given, and the grammar it answers in.

Part of W6. Before this module there were three prompt producers and none of
them was used by the path the OS takes: `cli_ports.py` handed the worker the
single sentence "Execute the approved dispatch request for <issue> per the
issue body", `work_launcher.generate_worker_prompt` built a fuller instruction
for `work new` and for `work resume --request-file`, and the daemon built a
third from an issue title plus body. A worker told none of the result contract
cannot be held to it, and `CORTXT-OUTCOME:` -- the attestation channel
`worker_outcome.read_attested_outcome` has parsed since #520 -- was stated to
no worker anywhere.

Two properties this module exists to hold, both asserted by test rather than
by comment:

- **One producer, one version.** `CONTRACT_VERSION` is written into the
  instruction the worker receives and is the same constant the classifier
  reports. A worker that answers under a version the platform does not
  implement is visible as a version, not as a parse failure.
- **The grammar is stated once.** `ATTESTATION_PREFIX` and `ATTESTABLE` are
  owned here and imported by both the producer (which tells the worker the
  form) and the parser (`worker_outcome`, which accepts it). The predecessor
  hazard is specific: an instruction that teaches `CORTXT-OUTCOME:` while the
  parser accepts `CORTXT_OUTCOME:` fails silently, in the direction of
  `unattested`, on every Run.

The daemon's own producer (`agent-platform/daemon/loop.py`) is deliberately
**not** migrated here. Daemon dispatch writes no Run and is invisible in the
OS; the corrected plan defers its adaptation to W15 and this module's scope is
the three launch paths inside the supported WorkLauncher/Dispatcher contract.

Design record: `lab/cortxt-os-implementation-plan-2026-09-08-corrected.md`
(W6, §3.4) and `lab/cortxt-execution-confirmation-design-2026-09-08-corrected.md`.
"""
from __future__ import annotations

from typing import Mapping, Sequence

#: The version of the worker result contract this platform states and reads.
#: Carried in the instruction handed to the worker and in the classifier's
#: report of what it applied, so the two can be asserted equal.
CONTRACT_VERSION = "worker.result.v1"

#: The attestation channel, owned here because two sides must agree on it.
#: `worker_outcome` imports these rather than restating them.
ATTESTATION_PREFIX = "CORTXT-OUTCOME:"

#: The only verbs a worker may attest. `no_result` and `unattested` are
#: conclusions the *platform* draws from transport and are deliberately absent:
#: a worker claiming "I produced no result" is still a worker claiming
#: something, which is not what those two states mean.
ATTESTABLE: tuple[str, ...] = ("completed", "declined")

# Diacritics are refused for the same reason `work_launcher.FORBIDDEN` refuses
# them: the instruction reaches a GitHub artifact surface whose language rule is
# English-only, and a scope that smuggles them in is a mandate defect, not a
# rendering problem.
_FORBIDDEN_CHARS = "åäöÅÄÖ"


class WorkerInstructionError(ValueError):
    """The mandate cannot be stated to a worker as a bounded instruction."""


def attestation_grammar() -> str:
    """The exact line a worker is told to write, as prose for the instruction.

    Derived from `ATTESTATION_PREFIX` and `ATTESTABLE` so that changing either
    changes what the worker is taught in the same edit. A test asserts that
    every verb named here is one the parser accepts.
    """
    verbs = " or ".join(f"`{ATTESTATION_PREFIX} {verb}`" for verb in ATTESTABLE)
    return (
        f"State your outcome on the LAST non-empty line of your output, exactly "
        f"{verbs}.\n"
        f"`{ATTESTATION_PREFIX} declined <reason>` may carry a short reason on the "
        f"same line;\n"
        f"`{ATTESTATION_PREFIX} completed` carries nothing else. Any other form, or "
        f"the line\n"
        f"appearing anywhere but last, is read as no claim at all -- not as the "
        f"outcome you\n"
        f"were reaching for."
    )


def _check_ascii(values: Sequence[str | None]) -> None:
    for value in values:
        if value and any(char in value for char in _FORBIDDEN_CHARS):
            raise WorkerInstructionError(
                "mandate content must contain only English ASCII letters")


def build_worker_instruction(
    *,
    scope: str,
    acceptance_criteria: Sequence[str],
    limits: Mapping[str, object],
    artifact_policy: str,
    issue_id: str | None = None,
    run_id: str | None = None,
    request_id: str | None = None,
) -> str:
    """Render the versioned instruction handed to a worker on any launch path.

    Every supported path resolves the same four mandate fields -- scope,
    acceptance criteria, limits, artifact policy -- from the approved dispatch
    request, so every path can state the same instruction. The identity block
    is written only from what the platform actually knows: a `None` is omitted
    rather than rendered, because telling a worker `run_id: None` and then
    requiring it to report `run_id` teaches it to invent one.

    Raises `WorkerInstructionError` when the mandate is not statable. A launch
    with no scope or no acceptance criteria is refused here rather than sent
    to a worker as an empty section, which is how a worker ends up guessing at
    the task -- the shape #520's Runs took.
    """
    scope = (scope or "").strip()
    criteria = [str(item).strip() for item in acceptance_criteria if str(item).strip()]
    artifact_policy = (artifact_policy or "").strip()
    _check_ascii([scope, artifact_policy, *criteria])
    if not scope:
        raise WorkerInstructionError("scope is required")
    if not criteria:
        raise WorkerInstructionError("acceptance criteria are required")
    if not artifact_policy:
        raise WorkerInstructionError("artifact policy is required")

    ac_lines = "\n".join(f"- {item}" for item in criteria)
    limit_lines = "\n".join(
        f"- {key}: {value}" for key, value in sorted(limits.items())
        if value is not None
    ) or "- none stated"

    identity = [
        (name, value) for name, value in
        (("run_id", run_id), ("issue_id", issue_id), ("request_id", request_id))
        if value
    ]
    identity_block = (
        "\n".join(f"- {name}: {value}" for name, value in identity)
        if identity else
        "- the platform did not supply an identity block for this Run"
    )
    identity_names = ", ".join(f"`{name}`" for name, _ in identity) or "the identifiers above"

    return (
        f"You are a bounded worker operating under contract {CONTRACT_VERSION}.\n"
        "\nScope\n-----\n" + scope +
        "\n\nAcceptance criteria\n-------------------\n" + ac_lines +
        "\n\nLimits\n------\n" + limit_lines +
        "\n\nArtifact policy\n---------------\n" + artifact_policy +
        "\n\nRun identity\n------------\n" + identity_block +
        "\nThese are supplied by the platform and are authoritative. Report them "
        "back verbatim;\ndo not invent, derive or correct them.\n"
        "\nIsolation\n---------\n"
        "You work inside this Run's own isolated git worktree, on its branch. Do "
        "not read or\nwrite outside it, do not push, do not merge, and do not "
        "close issues.\n"
        "\nResult contract\n---------------\n"
        f"Report your result as the structured result envelope, carrying "
        f"{identity_names}.\n"
        "If your scope changes the repository: commit your approved English "
        "artifacts inside\nthe artifact policy above, each commit carrying a DCO "
        "`Signed-off-by: Your Name <email>`\ntrailer, and report the full 40-hex "
        "`commit` SHA you landed. The platform verifies\nyour commit against this "
        "Run's own branch -- reachability, timestamp, DCO and artifact\npolicy -- "
        "so a commit you did not land cannot be claimed.\n"
        "Do not expose secrets, copy full prompts, or record model reasoning.\n"
        "\nOutcome attestation\n-------------------\n"
        + attestation_grammar() + "\n"
        "\nSaying you completed the task is a claim, not a verification. Where "
        "this route's\nruntime writes a machine-readable completion report, the "
        "platform reads that report\nfirst and your attestation cannot raise a "
        "verdict the report has already lowered.\n"
    )
