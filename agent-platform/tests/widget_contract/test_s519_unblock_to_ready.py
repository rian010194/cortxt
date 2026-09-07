"""S7d (#519): a sanctioned `blocked -> ready` transition, separate from recovery.

Found by the dogfood itself. The negative arm is *required* to end at
`workflow:blocked` — that is its acceptance criterion — and `blocked` had no
registered way back. The arm could therefore be run exactly once, and every
re-run needed a manual `gh issue edit` outside the action ports, which is the
very thing these transitions exist to replace.

The two properties these tests exist to hold:

1. **Recovery stays restricted to `in-progress -> ready`.** The new action is a
   separate operation with a separate capability, not a widening of recovery:
   recovery returns an Issue whose Run stranded, while unblocking sets aside a
   refusal the platform made on evidence.
2. **Every refusal happens before any write.** A denied transition must leave
   the labels untouched and post no comment — asserted by counting writes, not
   by trusting the exception.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from widget_contract.action_ports import github_transition_adapter  # noqa: E402
from widget_contract.adapters.github_ports import (  # noqa: E402
    MIN_UNBLOCK_JUSTIFICATION, TransitionDenied, return_to_ready_transition,
    unblock_to_ready_transition)
from widget_contract.registry import ACTIONS  # noqa: E402

REASON = "Re-running the negative arm after #520 changed the refusal category."


class _Writer:
    """Records every write so a denial can be proven to have written nothing."""

    def __init__(self):
        self.calls = []

    def __call__(self, operation, request):
        self.calls.append((operation, dict(request)))
        return {"issue_id": request["issue_id"], "status": "ok"}


def _reader(*labels):
    def read(issue_id):
        return {"issue_id": issue_id, "labels": [{"name": x} for x in labels]}
    return read


def _unblock(labels=("workflow:blocked",), *, authority=lambda _id: False,
             justification=REASON, writer=None):
    writer = writer if writer is not None else _Writer()
    result = unblock_to_ready_transition(
        "workflow.unblock-to-ready.v1",
        {"issue_id": "owner/repo#519", "justification": justification},
        issue_reader=_reader(*labels), transition=writer, unblock_authority=authority)
    return result, writer


# --- the happy path -------------------------------------------------------

def test_blocked_issue_with_released_claim_and_a_reason_is_unblocked():
    result, writer = _unblock()

    assert result["status"] == "ok"
    assert len(writer.calls) == 1
    operation, request = writer.calls[0]
    assert operation == "workflow.unblock-to-ready.v1"
    assert request["issue_id"] == "owner/repo#519"
    # The stated reason reaches the writer, which is what makes it durable.
    assert request["justification"] == REASON


def test_justification_is_stripped_before_it_is_recorded():
    _result, writer = _unblock(justification="   " + REASON + "   ")
    assert writer.calls[0][1]["justification"] == REASON


# --- wrong source state: refused, no write --------------------------------

@pytest.mark.parametrize("labels", [
    ("workflow:in-progress",),   # recovery's state, not this one's
    ("workflow:ready",),
    ("workflow:inbox",),
    ("workflow:review",),
    ("workflow:done",),
    (),                          # no workflow label at all
    ("workflow:blocked", "workflow:ready"),   # ambiguous: not exactly blocked
])
def test_wrong_source_state_is_refused_without_mutation(labels):
    writer = _Writer()
    with pytest.raises(TransitionDenied) as raised:
        _unblock(labels=labels, writer=writer)

    assert "workflow:blocked" in str(raised.value)
    assert writer.calls == [], "a denied transition must not write"


# --- missing authority: refused, no write ---------------------------------

def test_missing_authority_is_refused_without_mutation():
    """An unwired host gets no unblock at all, never an unchecked one."""
    writer = _Writer()
    with pytest.raises(TransitionDenied) as raised:
        unblock_to_ready_transition(
            "workflow.unblock-to-ready.v1",
            {"issue_id": "owner/repo#519", "justification": REASON},
            issue_reader=_reader("workflow:blocked"), transition=writer)

    assert "run-liveness authority" in str(raised.value)
    assert writer.calls == []


@pytest.mark.parametrize("holds,label", [
    (True, "a Run still holds the Issue"),
    (None, "liveness not established"),
])
def test_only_an_explicit_false_permits_the_write(holds, label):
    """Returning to `ready` re-opens the dispatch gate, so absence of evidence
    must never permit it — the same tri-state discipline recovery uses."""
    writer = _Writer()
    with pytest.raises(TransitionDenied) as raised:
        _unblock(authority=lambda _id: holds, writer=writer)

    assert "lifting the block is refused" in str(raised.value)
    assert writer.calls == [], label


def test_an_authority_that_raises_denies_without_mutation():
    writer = _Writer()

    def boom(_id):
        raise RuntimeError("registry unreadable")

    with pytest.raises(TransitionDenied) as raised:
        _unblock(authority=boom, writer=writer)

    assert "could not be re-derived" in str(raised.value)
    assert writer.calls == []


# --- documented justification ---------------------------------------------

@pytest.mark.parametrize("justification", [
    None, "", "   ", "ok", "retry", "-", "x" * (MIN_UNBLOCK_JUSTIFICATION - 1),
])
def test_missing_or_token_justification_is_refused_without_mutation(justification):
    """A block is a recorded refusal; it is not set aside without a reason."""
    writer = _Writer()
    with pytest.raises(TransitionDenied) as raised:
        unblock_to_ready_transition(
            "workflow.unblock-to-ready.v1",
            {"issue_id": "owner/repo#519", "justification": justification},
            issue_reader=_reader("workflow:blocked"), transition=writer,
            unblock_authority=lambda _id: False)

    assert "justification" in str(raised.value)
    assert writer.calls == []


def test_justification_is_checked_before_the_issue_is_even_read():
    """The cheapest refusal happens first and touches nothing."""
    reads = []

    def counting_reader(issue_id):
        reads.append(issue_id)
        return {"issue_id": issue_id, "labels": [{"name": "workflow:blocked"}]}

    with pytest.raises(TransitionDenied):
        unblock_to_ready_transition(
            "workflow.unblock-to-ready.v1",
            {"issue_id": "owner/repo#519", "justification": "no"},
            issue_reader=counting_reader, transition=_Writer(),
            unblock_authority=lambda _id: False)

    assert reads == []


# --- the boundary against recovery ----------------------------------------

def test_recovery_still_refuses_a_blocked_issue():
    """`recover-to-ready` is NOT widened by this change."""
    writer = _Writer()
    with pytest.raises(TransitionDenied) as raised:
        return_to_ready_transition(
            "workflow.recover-to-ready.v1", {"issue_id": "owner/repo#519"},
            issue_reader=_reader("workflow:blocked"), transition=writer,
            recovery_authority=lambda _id: False)

    assert "workflow:in-progress" in str(raised.value)
    assert writer.calls == []


def test_unblock_refuses_an_in_progress_issue():
    """...and neither absorbs the other's state."""
    writer = _Writer()
    with pytest.raises(TransitionDenied):
        _unblock(labels=("workflow:in-progress",), writer=writer)
    assert writer.calls == []


def test_the_two_actions_carry_different_capabilities():
    """Holding one grants nothing about the other."""
    recover = ACTIONS["workflow.recover-to-ready.v1"]
    unblock = ACTIONS["workflow.unblock-to-ready.v1"]

    assert recover.capability == "act:recover-to-ready"
    assert unblock.capability == "act:unblock-to-ready"
    assert unblock.capability != recover.capability
    assert unblock.authorization_modes == frozenset({"operator"})
    assert unblock.effect_class == "workflow-transition"


def test_the_action_schema_requires_a_justification():
    schema = ACTIONS["workflow.unblock-to-ready.v1"].input_schema

    assert set(schema["required"]) == {"issue_id", "justification"}
    assert schema["additionalProperties"] is False
    assert schema["properties"]["justification"]["minLength"] == MIN_UNBLOCK_JUSTIFICATION
    # Recovery must not have gained the field.
    assert "justification" not in ACTIONS["workflow.recover-to-ready.v1"].input_schema["properties"]


# --- the adapter must not fall back to the wrong writer -------------------

def test_adapter_refuses_to_unblock_without_its_own_writer():
    """An unwired unblock writer raises rather than silently performing the
    inbox->ready edit — the same guard the review and recover writers have."""
    adapter = github_transition_adapter(
        lambda issue_id: ["workflow:blocked"], _Writer(),
        unblock_authority=lambda _id: False)

    with pytest.raises(ValueError) as raised:
        adapter("workflow.unblock-to-ready.v1",
                {"issue_id": "owner/repo#519", "justification": REASON})

    assert "unblock_transition_writer" in str(raised.value)


def test_adapter_routes_unblock_to_the_unblock_writer():
    written = []
    adapter = github_transition_adapter(
        lambda issue_id: ["workflow:blocked"], _Writer(),
        unblock_transition_writer=lambda issue_id, justification: written.append(
            (issue_id, justification)) or {"issue_id": issue_id, "status": "ok"},
        unblock_authority=lambda _id: False)

    result = adapter("workflow.unblock-to-ready.v1",
                     {"issue_id": "owner/repo#519", "justification": REASON})

    assert result["status"] == "ok"
    assert written == [("owner/repo#519", REASON)]


def test_wiring_recovery_alone_does_not_enable_unblocking():
    """The parameters are separate on purpose: a host that wired recovery must
    not find it has silently gained the power to lift blocks.

    It is refused as a missing *authority* rather than a missing writer,
    because the authority check runs before the writer is ever reached. That is
    the stronger refusal of the two — `recovery_authority` does not stand in
    for `unblock_authority`, so the block is denied on the check that matters
    rather than on the plumbing.
    """
    unblock_writer_calls = []
    adapter = github_transition_adapter(
        lambda issue_id: ["workflow:blocked"], _Writer(),
        recover_transition_writer=lambda issue_id: {"issue_id": issue_id, "status": "ok"},
        recovery_authority=lambda _id: False,
        unblock_transition_writer=lambda issue_id, justification: unblock_writer_calls.append(
            (issue_id, justification)))

    with pytest.raises(TransitionDenied) as raised:
        adapter("workflow.unblock-to-ready.v1",
                {"issue_id": "owner/repo#519", "justification": REASON})

    assert "run-liveness authority" in str(raised.value)
    assert unblock_writer_calls == []
