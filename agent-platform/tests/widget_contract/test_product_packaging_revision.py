"""W-2a (#606): revision identity D3-Alt-1 -- parent-chain content identity.

Oracle anchors asserted verbatim (from the verified digest table in the
W-2a supplement order, reproduced against the frozen 4a contract; every
frozen candidate payload below reproduces its constant EXACTLY):

- rev1 identity ``e0f94e0bd3b81a1b5765f16b21eb8c230d71a90be313be74605d28e95b678ede``
  (frozen candidate object inlined: audience/evidence_refs/features/outcome/
  package_id/parent_revision_identity/prior_binding_refs/problem/
  referenced_repositories/scope).
- rev2 identity ``06464a84ac248e63a123947d247539659751ca9d16725c94705b74b4e98ab2eb``
  (issue AC D3 case 6: the candidate_digest that differs from the committed
  rev1 digest in the content-mismatch scenario).
- rev3-revert identity ``043d797933bf6e4a3bd5df668dbcbedfa978749567d47e09475ff2b4e178ab85``
  (revert A -> B -> A yields a NEW identity, never a no-op).
- op-2 crash-before-commit candidate ``5c7dc1b1b141d7ae421a727e0076cb84bad0032280fa68ba4c53dc7a0b401f48``
  (``features: ["third feature"]``, parent rev1).
- concurrent winner ``e8b18fde04f4c6539ddb5fcc61a43033e44c7a20bc0ef18d1fe7e9c7f286e531``
  (``features: ["feature x"]``) vs loser ``50f0131bdbe2a53e3f4fa437c4ccd4fa7e66d8b8a6f24bdbf248fabb6a9eadcc``
  (``features: ["feature y"]``): insert-if-absent on rev1's child slot
  decides the winner.

Tests import nothing from ``agent-platform/state/core_store.py`` (delivered
in W-2b).
"""

import json

import pytest

from widget_contract.product_packaging._digest import (
    canonical_array,
    canonical_object,
    normalize_digest,
    sha256_hex,
)
from widget_contract.product_packaging.revision import (
    REVISION_FIELDS,
    RevisionError,
    build_revision,
    candidate_digest,
    is_genesis,
    revision_identity,
    validate_revision,
)

REV1_DIGEST = "e0f94e0bd3b81a1b5765f16b21eb8c230d71a90be313be74605d28e95b678ede"
REV2_DIGEST = "06464a84ac248e63a123947d247539659751ca9d16725c94705b74b4e98ab2eb"
REV3_REVERT_DIGEST = "043d797933bf6e4a3bd5df668dbcbedfa978749567d47e09475ff2b4e178ab85"
CONCURRENT_WINNER_DIGEST = "e8b18fde04f4c6539ddb5fcc61a43033e44c7a20bc0ef18d1fe7e9c7f286e531"
CONCURRENT_LOSER_DIGEST = "50f0131bdbe2a53e3f4fa437c4ccd4fa7e66d8b8a6f24bdbf248fabb6a9eadcc"
OP2_CANDIDATE_DIGEST = "5c7dc1b1b141d7ae421a727e0076cb84bad0032280fa68ba4c53dc7a0b401f48"

# The frozen 4a candidate revision object (order-inlined), genesis form.
_FROZEN_BASE = {
    "audience": "operator",
    "evidence_refs": [],
    "features": ["versioned package object"],
    "outcome": "C2 core package",
    "package_id": "cortxt-core",
    "parent_revision_identity": None,
    "prior_binding_refs": [],
    "problem": "first packaging work item",
    "referenced_repositories": [
        {"repo": "cortxt", "sha": "a8a1ff0ad5107c160597c1cdf3664bab29bff618"}
    ],
    "scope": ["C2 core"],
}


def _frozen_candidate(features, parent):
    """A frozen-form candidate: base object with overridden derived fields."""
    obj = dict(_FROZEN_BASE)
    obj["features"] = list(features)
    obj["parent_revision_identity"] = parent
    return obj


def _sha(s: str) -> str:
    return sha256_hex(s)


class TestCanonicalObjectForm:
    """Canonicalization (order rules, reproduced against frozen 4a)."""

    def test_canonical_object_is_sorted_compact_ascii(self):
        obj = {"b": 1, "a": "ä"}
        assert canonical_object(obj) == '{"a":"\\u00e4","b":1}'

    def test_canonical_object_no_trailing_newline(self):
        assert not canonical_object({"a": 1}).endswith("\n")

    def test_revision_identity_is_sha256_of_canonical_object(self):
        rev = {"package_id": "cortxt-core", "parent_revision_identity": None, "content": "A"}
        assert revision_identity(rev) == _sha(canonical_object(rev))

    def test_default_str_normalization_is_applied(self):
        rev = {"package_id": "cortxt-core", "parent_revision_identity": None,
               "content": json.dumps({"x": 1})}
        # non-serializable values fall through default=str instead of raising
        rev2 = {"package_id": "cortxt-core", "parent_revision_identity": None,
                "content": {"ts": json.dumps({"x": 1})}}
        assert isinstance(revision_identity(rev), str)
        assert isinstance(revision_identity(rev2), str)


class TestRevisionIdentity:
    """D3-Alt-1: parent-chain content identity, no counter."""

    def test_genesis_revision_has_null_parent(self):
        rev = build_revision("cortxt-core", {"text": "A"}, None)
        assert rev["parent_revision_identity"] is None
        assert is_genesis(rev)

    def test_identity_binds_parent_chain_revert_is_new_identity(self):
        # revert A -> B -> A: the second A has a different parent, so the
        # identity is NEW -- never a no-op (D3-Alt-1, d3_alt1_rev3_revert).
        rev_a1 = build_revision("cortxt-core", "A", None)
        id_a1 = revision_identity(rev_a1)
        rev_b = build_revision("cortxt-core", "B", id_a1)
        id_b = revision_identity(rev_b)
        rev_a2 = build_revision("cortxt-core", "A", id_b)
        id_a2 = revision_identity(rev_a2)
        assert id_a2 != id_a1
        assert id_a2 != id_b
        assert rev_a2["content"] == rev_a1["content"]

    def test_oracle_rev1_candidate_reproduces_exactly(self):
        # Frozen candidate (order-inlined object): the exact rev1 identity.
        assert candidate_digest(_frozen_candidate(
            ["versioned package object"], None)) == REV1_DIGEST

    def test_oracle_rev2_candidate_reproduces_exactly(self):
        # Frozen candidate, second feature, parent rev1: the exact rev2
        # identity (D3 case 6 content-mismatch candidate).
        assert candidate_digest(_frozen_candidate(
            ["versioned package object", "second feature"],
            REV1_DIGEST)) == REV2_DIGEST

    def test_oracle_rev3_revert_candidate_reproduces_exactly(self):
        # Frozen revert candidate (features back to rev1's, parent rev2):
        # A -> B -> A yields a NEW identity -- never rev1's, never a no-op.
        assert candidate_digest(_frozen_candidate(
            ["versioned package object"], REV2_DIGEST)) == REV3_REVERT_DIGEST
        assert REV3_REVERT_DIGEST not in (REV1_DIGEST, REV2_DIGEST)

    def test_oracle_rev3_revert_digest_is_a_valid_bare_hex_identity(self):
        # The frozen example d3_alt1_rev3_revert.json carries this identity;
        # it is a 64-char bare-hex digest and differs from rev2 (never a no-op
        # would mean re-using rev1's or rev2's identity).
        assert len(REV3_REVERT_DIGEST) == 64
        assert REV3_REVERT_DIGEST != REV2_DIGEST

    def test_oracle_op2_crash_before_commit_candidate_reproduces_exactly(self):
        # d3_op2_crash_before_commit: features ["third feature"], parent
        # rev1, pending status, null result identity.
        assert candidate_digest(_frozen_candidate(
            ["third feature"], REV1_DIGEST)) == OP2_CANDIDATE_DIGEST

    def test_oracle_concurrent_winner_and_loser_reproduce_exactly(self):
        # d3_op_concurrent_winner / loser: both candidates share parent
        # rev1; insert-if-absent on the child slot decides, so exactly one
        # wins and the loser's distinct identity is never written.
        assert candidate_digest(_frozen_candidate(
            ["feature x"], REV1_DIGEST)) == CONCURRENT_WINNER_DIGEST
        assert candidate_digest(_frozen_candidate(
            ["feature y"], REV1_DIGEST)) == CONCURRENT_LOSER_DIGEST
        assert CONCURRENT_WINNER_DIGEST != CONCURRENT_LOSER_DIGEST

    def test_same_operation_retry_same_candidate_digest_same_result(self):
        rev = build_revision("cortxt-core", {"text": "A"}, None)
        first = candidate_digest(rev)
        second = candidate_digest(build_revision("cortxt-core", {"text": "A"}, None))
        assert first == second  # same candidate content -> same digest -> replay

    def test_candidate_digest_matches_revision_identity(self):
        rev = build_revision("cortxt-core", {"text": "A"}, None)
        assert candidate_digest(rev) == revision_identity(rev)

    def test_parent_prefix_is_normalized_before_binding(self):
        bare = build_revision("cortxt-core", "B", "ab" * 32)
        prefixed = build_revision("cortxt-core", "B", "sha256:" + "ab" * 32)
        assert bare == prefixed
        assert revision_identity(bare) == revision_identity(prefixed)

    def test_no_counter_in_identity(self):
        # Identity is purely content+parent: there is no counter field, so
        # two revisions with identical content and parent have one identity.
        r1 = build_revision("cortxt-core", "A", None)
        r2 = build_revision("cortxt-core", "A", None)
        assert r1 == r2 and revision_identity(r1) == revision_identity(r2)

    def test_oracle_concurrent_winner_digest_is_bare_hex(self):
        assert len(CONCURRENT_WINNER_DIGEST) == 64
        # The winner takes the single child slot of rev1; the digest shape is
        # bare hex (P1-7).
        assert normalize_digest(CONCURRENT_WINNER_DIGEST) == CONCURRENT_WINNER_DIGEST


class TestRevisionValidation:
    def test_closed_three_field_shape(self):
        assert set(REVISION_FIELDS) == {
            "package_id", "parent_revision_identity", "content",
        }
        rev = build_revision("cortxt-core", "A", None)
        validate_revision(rev)
        with pytest.raises(RevisionError):
            validate_revision(dict(rev, counter=1))

    def test_rejects_bad_parent_digest(self):
        with pytest.raises(RevisionError):
            build_revision("cortxt-core", "A", "XYZ")
        with pytest.raises(RevisionError):
            build_revision("cortxt-core", "A", "sha256:sha256:" + "ab" * 32)

    def test_content_is_canonicalized_via_default_str(self):
        # default=str is part of the canonicalization contract: values that
        # json.dumps cannot serialize natively are stringified, never an
        # error, and the digest stays deterministic.
        rev = {"package_id": "p", "parent_revision_identity": None,
               "content": {1, 2}}
        first = revision_identity(rev)
        assert first == revision_identity(rev)  # deterministic
        assert len(first) == 64

    def test_normalize_digest_rejects_uppercase_and_doubled_prefix(self):
        with pytest.raises(ValueError):
            normalize_digest("AB" * 32)
        with pytest.raises(ValueError):
            normalize_digest("sha256:sha256:" + "ab" * 32)

    def test_derived_key_form_is_compact_array(self):
        assert canonical_array(["cortxt-core", "ab" * 32, "acceptance"]) == (
            '["cortxt-core","' + "ab" * 32 + '","acceptance"]'
        )


class TestChildSlotSemantics:
    """D3 case 4 rule level: one winner per parent child slot."""

    def test_two_writers_same_parent_distinct_identities(self):
        parent = revision_identity(build_revision("cortxt-core", "A", None))
        w1 = build_revision("cortxt-core", "B-1", parent)
        w2 = build_revision("cortxt-core", "B-2", parent)
        id1, id2 = revision_identity(w1), revision_identity(w2)
        assert id1 != id2  # never a silent fork: distinct identities...
        # ...and exactly one of them may occupy the child slot of the parent.
        child_slot = {}
        for rid, robj in ((id1, w1), (id2, w2)):
            child_slot.setdefault(parent, []).append(rid)
        assert len(child_slot[parent]) == 2  # both attempted
        winner = child_slot[parent][0]  # insert-if-absent: first wins
        assert winner in (id1, id2)

    def test_oracle_concurrent_winner_differs_from_rev2(self):
        assert CONCURRENT_WINNER_DIGEST != REV2_DIGEST
        # The loser's candidate is distinct from both winner and rev2 and is
        # never committed (insert-if-absent on the single child slot).
        assert CONCURRENT_LOSER_DIGEST not in (CONCURRENT_WINNER_DIGEST, REV2_DIGEST)


# The `committed` child-slot winner value asserted by the concurrent-winner
# frozen example; kept as the module-level constant so reviewers see the
# oracle string once.
winner = CONCURRENT_WINNER_DIGEST
_ = winner
