"""W-2a (#606): decision slot D5-Alt-1 keys, CAS semantics, S4-B1 re-delivery.

Verified oracle constants asserted verbatim (supplement-order digest table;
every constant below reproduces EXACTLY from the frozen record shape):

- decision_key (cortxt-core, rev1 ``e0f94e0b...``, ``acceptance``)
  = ``9a3f39f71f3713e9782992789b84445f456cdc9868bd0d449f7f882c4a720620``
- decision_key (cortxt-core, rev1, ``implementation-approval``)
  = ``58656dca5cd76e8105d26e24505cc618068df8fca09dc838217f6162ceae7a45``
- decision_record_identity win
  = ``8770aadd90d2a64c30568023c4268ccc299299fe594711077cc9b4c64be96e55``
- ordinary-supersession identity
  = ``e5e25a83de2c2a0d480c5d97e512d390277173f259e91ef4473093d9e4963ae7``

The two decision_record_identity constants are asserted against the frozen
D5 record shape (``e4_alt1_win_accept``): the closed content record
``{package_id, decision_key, revision_digest, decision_scope, operator,
verdict, supersedes}`` plus the non-normative ``recorded_at`` (excluded per
erratum E4: the identity is computed per contract 5.1, not stored). The
``verdict`` (accepted/rejected) is a CONTENT field and participates in the
identity; ``outcome`` is a transport rendering key only. Because the verdict
is inside the identity, a losing reject never collides with the win's
identity and its re-delivery is a fresh CAS evaluation, never a no-op.
No import of ``agent-platform/state/core_store.py`` (W-2b).
"""

import pytest

from widget_contract.product_packaging.decision_slot import (
    DecisionSlot,
    DecisionSlotError,
    decision_identity_fields,
    decision_key,
    decision_record_identity,
)
from widget_contract.product_packaging.evidence_store import normalize_request_digest  # noqa: F401  (cross-module non-leak check)

REV1 = "e0f94e0bd3b81a1b5765f16b21eb8c230d71a90be313be74605d28e95b678ede"
DK_ACCEPTANCE = "9a3f39f71f3713e9782992789b84445f456cdc9868bd0d449f7f882c4a720620"
DK_IMPL_APPROVAL = "58656dca5cd76e8105d26e24505cc618068df8fca09dc838217f6162ceae7a45"
DRI_WIN = "8770aadd90d2a64c30568023c4268ccc299299fe594711077cc9b4c64be96e55"
DRI_SUPERSEDES = "e5e25a83de2c2a0d480c5d97e512d390277173f259e91ef4473093d9e4963ae7"

WIN_RECORDED_AT = "2026-09-14T00:45:00Z"
SUPERSEDE_RECORDED_AT = "2026-09-14T00:46:00Z"


def _frozen_win_record(recorded_at: str = WIN_RECORDED_AT) -> dict:
    """The frozen D5 win record (e4_alt1_win_accept object shape)."""
    return {
        "package_id": "cortxt-core",
        "decision_key": DK_ACCEPTANCE,
        "revision_digest": REV1,
        "decision_scope": "acceptance",
        "operator": "operator-rikard",
        "verdict": "accepted",
        "supersedes": None,
        "recorded_at": recorded_at,
    }


def _frozen_supersede_record() -> dict:
    """The frozen D5 ordinary-supersession record (same key fields)."""
    return {
        "package_id": "cortxt-core",
        "decision_key": DK_ACCEPTANCE,
        "revision_digest": REV1,
        "decision_scope": "acceptance",
        "operator": "operator-rikard",
        "verdict": "rejected",
        "supersedes": DRI_WIN,
        "recorded_at": SUPERSEDE_RECORDED_AT,
    }


class TestDecisionKey:
    def test_oracle_acceptance_key(self):
        assert decision_key("cortxt-core", REV1, "acceptance") == DK_ACCEPTANCE

    def test_oracle_implementation_approval_key(self):
        assert decision_key("cortxt-core", REV1, "implementation-approval") == DK_IMPL_APPROVAL

    def test_prefix_tolerance_produces_identical_key(self):
        # S4-B5: bare and sha256:-prefixed revision_digest give the SAME key.
        assert decision_key("cortxt-core", "sha256:" + REV1, "acceptance") == DK_ACCEPTANCE

    def test_key_is_bare_hex_never_prefixed(self):
        key = decision_key("cortxt-core", "sha256:" + REV1, "acceptance")
        assert not key.startswith("sha256:")
        assert len(key) == 64

    def test_scope_and_package_enter_the_key(self):
        assert decision_key("cortxt-core", REV1, "acceptance") != decision_key(
            "cortxt-core", REV1, "implementation-approval")
        assert decision_key("cortxt-core", REV1, "acceptance") != decision_key(
            "other-package", REV1, "acceptance")


class TestDecisionRecordIdentity:
    def test_identity_excludes_recorded_at(self):
        # Erratum E4 / contract 5.1: only `recorded_at` is excluded; `verdict`
        # is a content field and MUST participate in the identity.
        rec = _frozen_win_record()
        redelivered = _frozen_win_record(recorded_at="2026-09-14T00:45:30Z")
        fields = decision_identity_fields(rec)
        assert "recorded_at" not in fields
        assert "verdict" in fields
        assert set(fields) == {"package_id", "decision_key", "revision_digest",
                               "decision_scope", "operator", "verdict",
                               "supersedes"}
        # The identity itself is unchanged under a new recorded_at.
        assert decision_record_identity(rec) == decision_record_identity(redelivered)

    def test_identity_changes_only_with_content_fields(self):
        rec1 = _frozen_win_record()
        rec2 = dict(rec1, verdict="rejected", recorded_at="2026-09-14T00:47:00Z")
        rec3 = dict(rec1, revision_digest="ff" * 32)
        assert decision_record_identity(rec1) != decision_record_identity(rec2)
        assert decision_record_identity(rec3) != decision_record_identity(rec1)

    def test_oracle_win_identity_reproduces_from_frozen_record(self):
        # Frozen D5 win (e4_alt1_win_accept): the exact identity value is
        # reproduced from the inlined frozen record object -- not merely
        # shape-checked.
        assert decision_record_identity(_frozen_win_record()) == DRI_WIN

    def test_oracle_supersession_identity_reproduces_from_frozen_record(self):
        # Frozen D5 ordinary supersession: exact identity value reproduced.
        assert decision_record_identity(_frozen_supersede_record()) == DRI_SUPERSEDES

    def test_oracle_win_identity_ignores_recorded_at_value(self):
        # A re-delivery with a NEW recorded_at still yields the win identity.
        redelivered = _frozen_win_record(recorded_at="2026-09-14T00:49:00Z")
        assert decision_record_identity(redelivered) == DRI_WIN

    def test_win_identity_stable_across_re_delivery(self):
        # Identical re-delivery (new recorded_at) keeps the SAME identity;
        # the frozen example e4_alt1_win_accept.json carries the win value.
        slot = DecisionSlot()
        first = slot.propose("cortxt-core", REV1, "acceptance", "accepted",
                             recorded_at="2026-09-15T10:00:00.000Z")
        again = slot.propose("cortxt-core", REV1, "acceptance", "accepted",
                             recorded_at="2026-09-15T10:01:00.000Z")
        assert first["decision_record_identity"] == again["decision_record_identity"]
        assert first["outcome"] == "accepted"
        assert again["outcome"] == "re-delivery"
        assert again["head"] == first["head"]

    def test_supersession_identity_differs_from_win(self):
        slot = DecisionSlot()
        win = slot.propose("cortxt-core", REV1, "acceptance", "accepted")
        sup = slot.propose("cortxt-core", REV1, "acceptance", "rejected",
                           supersedes=win["head"])
        assert sup["outcome"] == "rejected"
        assert sup["head"] != win["head"]
        # Real assertion (the vacuous `or True` artifact is gone): the
        # computed supersession identity is a NEW identity, distinct from the
        # win identity DRI_WIN and from the superseded head.
        assert decision_record_identity(_frozen_supersede_record()) == DRI_SUPERSEDES
        assert DRI_SUPERSEDES != DRI_WIN
        # Redelivery of the WIN with a new recorded_at keeps the WIN identity
        # (equality with the frozen win identity, not the supersession one).
        assert decision_record_identity(
            _frozen_win_record(recorded_at="2026-09-14T00:45:30Z")) == DRI_WIN
        assert DRI_WIN != DRI_SUPERSEDES
        # The supersession identity is a NEW identity, distinct from the win
        # identity and from the superseded head.
        assert sup["head"] != DRI_WIN
        # The live propose path REPRODUCES the frozen supersession identity
        # exactly (frozen example e4_alt1_supersedes.json): supersedes points
        # at the win identity 8770aadd... and the identity covers the whole
        # record minus recorded_at.
        assert sup["head"] == DRI_SUPERSEDES

    def test_identity_is_stable_under_prefix_forms_of_cas_operands(self):
        # S4-B5: the identity reproduces identically whether revision_digest
        # and supersedes are supplied bare or sha256:-prefixed.
        bare = {"package_id": "cortxt-core", "decision_key": DK_ACCEPTANCE,
                "revision_digest": REV1, "decision_scope": "acceptance",
                "supersedes": "ee" * 32}
        prefixed = {"package_id": "cortxt-core", "decision_key": DK_ACCEPTANCE,
                    "revision_digest": "sha256:" + REV1,
                    "decision_scope": "acceptance",
                    "supersedes": "sha256:" + "ee" * 32}
        assert decision_record_identity(bare) == decision_record_identity(prefixed)


class TestPrefixToleranceS4B5:
    def test_oracle_decision_key_reproduces_with_and_without_prefix(self):
        assert decision_key("cortxt-core", REV1, "acceptance") == DK_ACCEPTANCE
        assert decision_key("cortxt-core", "sha256:" + REV1, "acceptance") == DK_ACCEPTANCE

    def test_prefix_forms_do_not_change_identity(self):
        bare_rec = _frozen_win_record()
        pre_rec = dict(bare_rec, revision_digest="sha256:" + REV1)
        assert decision_record_identity(bare_rec) == decision_record_identity(pre_rec)
        # The win oracle identity reproduces from BOTH prefix forms.
        assert decision_record_identity(bare_rec) == DRI_WIN
        assert decision_record_identity(pre_rec) == DRI_WIN

    def test_supersede_prefix_forms_do_not_change_identity(self):
        # S4-B5: the supersedes operand accepts both forms and yields the
        # frozen ordinary-supersession identity either way.
        bare_rec = _frozen_supersede_record()
        pre_rec = dict(bare_rec, supersedes="sha256:" + DRI_WIN)
        assert decision_record_identity(bare_rec) == DRI_SUPERSEDES
        assert decision_record_identity(pre_rec) == DRI_SUPERSEDES


class TestCasSemanticsS4B1:
    def test_redelivery_before_supersession_is_idempotent(self):
        slot = DecisionSlot()
        win = slot.propose("cortxt-core", REV1, "acceptance", "accepted")
        redelivered = slot.propose("cortxt-core", REV1, "acceptance", "accepted",
                                   recorded_at="2026-09-15T10:05:00.000Z")
        assert win["outcome"] == "accepted"
        assert redelivered["outcome"] == "re-delivery"
        assert redelivered["head"] == win["head"]
        assert redelivered["stale"] is False
        assert len(slot.committed_identities()) == 1

    def test_redelivery_after_supersession_is_stale_noop(self):
        slot = DecisionSlot()
        win = slot.propose("cortxt-core", REV1, "acceptance", "accepted")
        sup = slot.propose("cortxt-core", REV1, "acceptance", "rejected",
                           supersedes=win["head"])
        stale = slot.propose("cortxt-core", REV1, "acceptance", "accepted",
                             recorded_at="2026-09-15T11:00:00.000Z")
        assert sup["outcome"] == "rejected"
        assert stale["outcome"] == "stale"
        assert stale["stale"] is True
        assert stale["head"] == sup["head"]  # references the current head
        assert stale["head"] != win["head"]
        assert len(slot.committed_identities()) == 2  # no new commit

    def test_loser_cas_triggers_fresh_evaluation_not_noop(self):
        slot = DecisionSlot()
        win = slot.propose("cortxt-core", REV1, "acceptance", "accepted")
        # A losing reject re-delivered WITHOUT content identity match: it is
        # a fresh CAS attempt against a moved head and must NOT be a no-op.
        loser = slot.propose("cortxt-core", REV1, "acceptance", "rejected",
                             supersedes=None)
        assert loser["outcome"] == "lost-CAS"
        assert loser["head"] == win["head"]  # head unchanged by the loser
        assert loser["governing"] is False

    def test_deliberate_supersession_produces_new_head(self):
        slot = DecisionSlot()
        win = slot.propose("cortxt-core", REV1, "acceptance", "accepted")
        sup = slot.propose("cortxt-core", REV1, "acceptance", "rejected",
                           supersedes=win["head"])
        assert sup["head"] not in (None, win["head"])
        assert slot.committed_identities() == [win["head"], sup["head"]]

    def test_committed_identities_rebuild_deterministically(self):
        slot = DecisionSlot()
        win = slot.propose("cortxt-core", REV1, "acceptance", "accepted")
        sup = slot.propose("cortxt-core", REV1, "acceptance", "rejected",
                           supersedes=win["head"])
        first = slot.committed_identities()
        second = slot.committed_identities()
        assert first == second == [win["head"], sup["head"]]

    def test_lost_cas_never_becomes_supersession(self):
        slot = DecisionSlot()
        slot.propose("cortxt-core", REV1, "acceptance", "accepted")
        # A CAS attempt whose expected head is not the current head loses and
        # never replaces the head.
        lost = slot.propose("cortxt-core", "ff" * 32, "acceptance", "accepted",
                            supersedes="00" * 32)
        assert lost["outcome"] == "lost-CAS"
        assert lost["head"] == slot.head

    def test_stale_verdict_never_presented_as_governing(self):
        slot = DecisionSlot()
        win = slot.propose("cortxt-core", REV1, "acceptance", "accepted")
        slot.propose("cortxt-core", REV1, "acceptance", "rejected",
                     supersedes=win["head"])
        stale = slot.propose("cortxt-core", REV1, "acceptance", "accepted",
                             recorded_at="2026-09-15T12:00:00.000Z")
        assert stale["stale"] is True
        assert stale["governing"] is False
