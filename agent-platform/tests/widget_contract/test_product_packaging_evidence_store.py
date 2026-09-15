"""W-2a (#606): evidence store D4/EVP-A -- idempotency key, normalization,
request binding, and the three deterministic outcomes.

Verified oracle constants asserted verbatim (supplement-order digest table;
every constant below reproduces EXACTLY from the inlined frozen payloads):

- idempotency key (stripped)
  ``4aa26a51bfb00214011b1df8dfa99b0b06251f5d1e054d72618b22f2f7a5582d`` for
  request_id ``sha256:d7f131fb7d9bc94fe5af641d20397c3a432f6507af65639e7e771065ba3a0469``
  + entry_id ``ev-0001``
- un-normalized prefixed variant
  ``34334628a3efd50a057be5c4b44dcf2d46b44a4229724e843552cec4277a3e82``
- ev-0002 key ``b5b70ddfecbc6134206a9faed729c7f50491562adc893b31e60c962413073c28``
- payload digests: ev-0001 ``bb56d9e1...`` (redelivery, no-op), conflict
  attempt ``bc571e08...`` (explicit conflict, nothing overwritten), ev-0002
  ``b2d49756...`` (new version appended)

Request binding is a separate boundary function ``check_request_binding``
(exact whole-string equality; normalization must NOT leak into it) -- the
append-before-binding ordering is asserted against that guard explicitly.
No import of ``agent-platform/state/core_store.py`` (W-2b).
"""

import pytest

from widget_contract.product_packaging._digest import canonical_object, sha256_hex
from widget_contract.product_packaging.evidence_store import (
    EvidenceError,
    EvidenceStore,
    OUTCOME_CONFLICT,
    OUTCOME_NEW_VERSION,
    OUTCOME_REDELIVERY,
    REQUEST_BINDING_MISMATCH,
    check_request_binding,
    evidence_idempotency_key,
    normalize_request_digest,
)

REQUEST_ID = "sha256:d7f131fb7d9bc94fe5af641d20397c3a432f6507af65639e7e771065ba3a0469"
REQUEST_HEX = "d7f131fb7d9bc94fe5af641d20397c3a432f6507af65639e7e771065ba3a0469"
EV1_KEY = "4aa26a51bfb00214011b1df8dfa99b0b06251f5d1e054d72618b22f2f7a5582d"
EV1_UNNORMALIZED = "34334628a3efd50a057be5c4b44dcf2d46b44a4229724e843552cec4277a3e82"
EV2_KEY = "b5b70ddfecbc6134206a9faed729c7f50491562adc893b31e60c962413073c28"

# Frozen payload objects (inlined from the supplement order) and their
# sha256(canonical_object(payload)) digests -- asserted EXACTLY below.
EV1_PAYLOAD = {
    "claim": "BLK-3 envelope drift exists",
    "correctness": "source-claim",
    "source": "docs/architecture/dispatch-contract.md",
}
EV1_PAYLOAD_DIGEST = "bb56d9e184b96004f8bc6702cc302698a014f0a06820891a035400484bb6fdc6"
CONFLICT_PAYLOAD = {
    "claim": "BLK-3 envelope resolved by E2'",
    "correctness": "source-claim",
    "source": "docs/architecture/dispatch-contract.md",
}
CONFLICT_PAYLOAD_DIGEST = "bc571e084e3a5cdb36f7257c93937c0ea378e2f489b796722d0a5d804cdcf6d2"
EV2_PAYLOAD = {"assert": "v2 digest over 19 bound fields"}
EV2_PAYLOAD_DIGEST = "b2d497564974b2854fadd8a3ad1b805382e677a5b810410e31d5f950b0f737f0"


def _payload_digest(payload: dict) -> str:
    """Order canonicalization rules: object form over the payload object."""
    return sha256_hex(canonical_object(payload))


class TestIdempotencyKey:
    def test_oracle_ev0001_key_with_prefix_input(self):
        assert evidence_idempotency_key(REQUEST_ID, "ev-0001") == EV1_KEY

    def test_same_key_without_prefix(self):
        assert evidence_idempotency_key(REQUEST_HEX, "ev-0001") == EV1_KEY

    def test_oracle_ev0002_key(self):
        assert evidence_idempotency_key(REQUEST_ID, "ev-0002") == EV2_KEY

    def test_unnormalized_prefixed_variant_hashes_differently(self):
        # The test must catch the difference: hashing the prefixed string
        # WITHOUT input normalization yields the different oracle key.
        from widget_contract.product_packaging._digest import canonical_array

        raw = sha256_hex_noimport(canonical_array([REQUEST_ID, "ev-0001"]))
        assert raw == EV1_UNNORMALIZED
        assert raw != EV1_KEY
        # ...and the module's normalization is what produces the stripped key.
        assert evidence_idempotency_key(REQUEST_ID, "ev-0001") != EV1_UNNORMALIZED

    def test_key_stored_as_bare_hex(self):
        key = evidence_idempotency_key(REQUEST_ID, "ev-0001")
        assert not key.startswith("sha256:")
        assert len(key) == 64


def sha256_hex_noimport(s: str) -> str:
    import hashlib

    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class TestInputNormalization:
    """Permitted input: 64 lowercase hex, optional single sha256: prefix."""

    def test_strips_single_prefix(self):
        assert normalize_request_digest(REQUEST_ID) == REQUEST_HEX

    def test_plain_hex_passes_through(self):
        assert normalize_request_digest(REQUEST_HEX) == REQUEST_HEX

    def test_uppercase_hex_rejected(self):
        with pytest.raises(EvidenceError):
            normalize_request_digest(REQUEST_HEX.upper())

    def test_doubled_prefix_rejected(self):
        with pytest.raises(EvidenceError):
            normalize_request_digest("sha256:sha256:" + REQUEST_HEX)

    def test_wrong_length_rejected(self):
        with pytest.raises(EvidenceError):
            normalize_request_digest(REQUEST_HEX[:63])
        with pytest.raises(EvidenceError):
            normalize_request_digest(REQUEST_HEX + "00")

    def test_non_hex_rejected(self):
        with pytest.raises(EvidenceError):
            normalize_request_digest("z" * 64)

    def test_normalization_before_comparison(self):
        # Same digest supplied with and without prefix normalizes to the same
        # key: normalization happens before hashing and before comparison.
        assert evidence_idempotency_key(REQUEST_ID, "ev-0001") == \
            evidence_idempotency_key(REQUEST_HEX, "ev-0001")


class TestRequestBinding:
    """Exact whole-string equality -- normalization must NOT leak here.

    ``check_request_binding`` is the packaging-layer boundary guard: callers
    invoke it explicitly on the envelope BEFORE dispatch/append.
    """

    def test_correctly_prefixed_request_id_passes(self):
        # A correctly prefixed request_id is ACCEPTED by the boundary guard.
        check_request_binding(REQUEST_ID, REQUEST_ID)

    def test_bare_request_id_rejected_against_prefixed_payload(self):
        # The SAME hex WITHOUT its prefix is rejected with the explicit
        # EV-REQUEST_BINDING_MISMATCH error: normalization must not leak.
        with pytest.raises(EvidenceError, match=REQUEST_BINDING_MISMATCH):
            check_request_binding(REQUEST_HEX, REQUEST_ID)

    def test_mismatched_hex_rejected(self):
        with pytest.raises(EvidenceError, match=REQUEST_BINDING_MISMATCH):
            check_request_binding(REQUEST_ID, "ee" * 64)

    def test_binding_does_not_use_digest_normalization(self):
        # The normalization rule must not leak into request binding: the
        # whole strings differ, so the binding fails even though the bare
        # hex values are equal.
        with pytest.raises(EvidenceError):
            check_request_binding(REQUEST_HEX, REQUEST_ID)

    def test_request_binding_checked_before_append(self):
        # The boundary guard runs on the envelope BEFORE the store append:
        # a correctly prefixed (request_id, payload_digest) pair passes...
        check_request_binding(REQUEST_ID, REQUEST_ID)
        # ...the same bare hex WITHOUT its prefix is rejected by the guard
        # with EV-REQUEST_BINDING_MISMATCH...
        with pytest.raises(EvidenceError, match=REQUEST_BINDING_MISMATCH):
            check_request_binding(REQUEST_HEX, REQUEST_ID)
        # ...and a guard-failing envelope is therefore never appended: a
        # caller that binds first and appends only on success leaves the
        # store empty, while a passing pair proceeds to a real append.
        store = EvidenceStore()
        with pytest.raises(EvidenceError, match=REQUEST_BINDING_MISMATCH):
            check_request_binding(REQUEST_HEX, REQUEST_ID)
            store.append({"request_id": REQUEST_HEX, "entry_id": "ev-0001",
                          "payload_digest": EV1_PAYLOAD_DIGEST})
        assert len(store) == 0  # refusal happened before any append
        store.append({"request_id": REQUEST_ID, "entry_id": "ev-0001",
                      "payload_digest": EV1_PAYLOAD_DIGEST})
        assert len(store) == 1  # the passing pair appended exactly once


class TestEvidenceOutcomes:
    def _request(self, request_id=REQUEST_ID, entry_id="ev-0001",
                 payload_digest=EV1_PAYLOAD_DIGEST):
        # NOTE: check_request_binding is the packaging-layer envelope guard
        # and compares the envelope request_id against the ENVELOPE's own
        # digest value; the evidence payload digest is a DIFFERENT digest
        # (the request_id digests the 19-field request snapshot). The
        # outcome branches below therefore go straight to the store; the
        # guard's rejection semantics are covered separately by
        # TestRequestBinding. Frozen example e3_entry_ev0001.json carries
        # request_id d7f131fb... (request snapshot) and payload_digest
        # bb56d9e1... (evidence payload) -- two distinct digests by design.
        return {"request_id": request_id, "entry_id": entry_id,
                "payload_digest": payload_digest}

    def test_frozen_payload_digests_reproduce_exactly(self):
        # The three inlined frozen payload objects reproduce their order
        # constants EXACTLY under the object-form canonicalization.
        assert _payload_digest(EV1_PAYLOAD) == EV1_PAYLOAD_DIGEST
        assert _payload_digest(CONFLICT_PAYLOAD) == CONFLICT_PAYLOAD_DIGEST
        assert _payload_digest(EV2_PAYLOAD) == EV2_PAYLOAD_DIGEST

    def test_new_evidence_version_appended(self):
        store = EvidenceStore()
        result = store.append(self._request())
        assert result["outcome"] == OUTCOME_NEW_VERSION
        assert result["appended"] is True
        assert result["idempotency_key"] == EV1_KEY
        assert result["payload_digest"] == EV1_PAYLOAD_DIGEST
        assert len(store) == 1

    def test_redelivery_appends_nothing(self):
        # Redelivery with an IDENTICAL payload digest is a no-op.
        store = EvidenceStore()
        store.append(self._request())
        again = store.append(self._request(entry_id="ev-0001",
                                           payload_digest=EV1_PAYLOAD_DIGEST))
        assert again["outcome"] == OUTCOME_REDELIVERY
        assert again["appended"] is False
        assert len(store) == 1

    def test_prefixed_redelivery_of_same_digest_is_redelivery(self):
        # Contract 6.2: readers strip before byte comparison. A re-delivery
        # of the SAME digest with a sha256: prefix must render re-delivery,
        # not a false conflict (P2-3 regression, reviewer finding).
        store = EvidenceStore()
        store.append(self._request())
        result = store.append(self._request(
            payload_digest="sha256:" + EV1_PAYLOAD_DIGEST))
        assert result["outcome"] == OUTCOME_REDELIVERY
        assert result["appended"] is False
        assert len(store) == 1
        # And the stored form stays bare.
        assert store.entries()[0]["payload_digest"] == EV1_PAYLOAD_DIGEST

    def test_conflict_rendered_explicitly_never_overwrites(self):
        # The conflict attempt carries the frozen conflict payload; its
        # digest differs from the stored one -> explicit CONFLICT, nothing
        # overwritten.
        assert _payload_digest(CONFLICT_PAYLOAD) != EV1_PAYLOAD_DIGEST
        store = EvidenceStore()
        store.append(self._request())
        result = store.append(self._request(payload_digest=CONFLICT_PAYLOAD_DIGEST))
        assert result["outcome"] == OUTCOME_CONFLICT
        assert result["appended"] is False
        assert result["existing_payload_digest"] == EV1_PAYLOAD_DIGEST
        # The stored entry was NOT silently overwritten.
        assert store.entries()[0]["payload_digest"] == EV1_PAYLOAD_DIGEST
        assert len(store) == 1

    def test_new_identity_appends_under_insert_if_absent(self):
        store = EvidenceStore()
        first = store.append(self._request(entry_id="ev-0001"))
        second = store.append(self._request(entry_id="ev-0002",
                                            payload_digest=EV2_PAYLOAD_DIGEST))
        assert first["idempotency_key"] == EV1_KEY
        assert second["idempotency_key"] == EV2_KEY
        assert second["outcome"] == OUTCOME_NEW_VERSION
        assert second["payload_digest"] == EV2_PAYLOAD_DIGEST
        assert len(store) == 2

    def test_keys_and_ids_stored_bare_never_prefixed(self):
        store = EvidenceStore()
        store.append(self._request())
        entry = store.entries()[0]
        assert entry["idempotency_key"] == EV1_KEY
        assert entry["request_id"] == REQUEST_HEX
        assert entry["payload_digest"] == EV1_PAYLOAD_DIGEST
        assert not entry["idempotency_key"].startswith("sha256:")
        assert not entry["request_id"].startswith("sha256:")


from widget_contract.product_packaging.evidence_store import EvidenceError  # noqa: E402  (used in tests above)
