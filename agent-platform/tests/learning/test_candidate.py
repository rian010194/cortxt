"""Fas 8 Task 1 — Candidate datamodel: immutable, id ≡ type@name@version, hash over serialized payload."""
from __future__ import annotations

import pytest

from learning import Candidate


def test_candidate_id_equals_type_at_name_at_version():
    """P2.4 from Kimi spec-review #2: id is derived = f"{type}@{name}@{version}"."""
    c = Candidate(type="policy", name="geometric-path-scoring", version="v2",
                  payload={"w1": 0.15, "w2": 0.4})
    assert c.id == "policy@geometric-path-scoring@v2"


def test_manifest_hash_binds_to_serialized_payload():
    """P0.1: two candidates with equal payload dicts hash identically (deterministic over serialization)."""
    payload_a = {"w1": 0.15, "w2": 0.40, "w5": 0.5}
    payload_b = {"w5": 0.5, "w2": 0.40, "w1": 0.15}  # same content, different key order
    c1 = Candidate(type="policy", name="np", version="v1", payload=payload_a)
    c2 = Candidate(type="policy", name="np", version="v1", payload=payload_b)
    assert c1.manifest_hash == c2.manifest_hash


def test_payload_is_immutable_snapshot_not_mutable_ref():
    """P0.1: mutating the original payload dict after construction does NOT change the candidate's payload."""
    payload = {"w1": 0.15, "w2": 0.4, "w5": 0.5}
    c = Candidate(type="policy", name="np", version="v1", payload=payload)
    original_hash = c.manifest_hash
    payload["w1"] = 0.99  # mutate the caller's dict
    assert c.payload["w1"] != 0.99  # candidate holds a locked copy
    assert c.manifest_hash == original_hash


def test_candidate_is_frozen():
    """Candidate fields are immutable once constructed."""
    c = Candidate(type="policy", name="np", version="v1", payload={})
    with pytest.raises(Exception):
        c.version = "v9"
