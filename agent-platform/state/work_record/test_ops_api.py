"""Work-record ops-API tests over the append-only Core store (ADR-050).

These pin the ADR's rules at the operations boundary: a record is created
without an issue and without a repository (rule 1); a revision leaves the
earlier version stored and byte-identical and the relation visible (rule 2);
nothing in the API closes or completes a record (rule 3). The store's own
guarantees -- insert-if-absent, re-delivery, conflict-not-merge, the
supersedes existence check -- are tested in ``state/test_core_store.py``;
here they are only checked to be surfaced, never softened.
"""

from __future__ import annotations

import json

import pytest

from state.core_store import CoreStore
from state.work_record.ops_api import WorkRecordOpsApi
from state.work_record.record import (
    STATE_SETTLED,
    WorkRecordError,
    build_work_record,
)


@pytest.fixture()
def api(tmp_path):
    return WorkRecordOpsApi(tmp_path / "core")


def record(**overrides):
    fields = {"work_id": "w-1", "title": "Decide the store shape"}
    fields.update(overrides)
    return build_work_record(**fields)


def test_accepts_a_store_root_path_or_a_store(tmp_path):
    from_path = WorkRecordOpsApi(str(tmp_path / "a"))
    assert isinstance(from_path.store, CoreStore)
    store = CoreStore(tmp_path / "b")
    assert WorkRecordOpsApi(store).store is store
    with pytest.raises(WorkRecordError):
        WorkRecordOpsApi(object())


def test_create_without_issue_or_repository_then_read_back(api):
    """ADR-050 rule 1: no issue_ref, no repository, still durable."""
    outcome = api.create(record())
    assert outcome["outcome"] == "appended"
    assert outcome["appended"] is True
    view = api.get(outcome["identity"])
    assert view is not None
    assert view["issue_ref"] is None
    assert view["supersedes"] is None
    assert view["record"]["possibly_affected_repositories"] == []
    assert view["record"]["title"] == "Decide the store shape"


def test_identity_is_the_payload_digest(api):
    outcome = api.create(record())
    assert outcome["identity"] == outcome["record_digest"]


def test_view_never_exposes_the_store_internal_hash(api):
    outcome = api.create(record())
    view = api.get(outcome["identity"])
    assert "record_hash" not in view
    assert set(view) == {"identity", "record_digest", "appended_at",
                         "issue_ref", "supersedes", "record"}


def test_create_carries_an_optional_issue_ref(api):
    outcome = api.create(record(title="With a reference"),
                         issue_ref="rian010194/cortxt#1")
    assert api.get(outcome["identity"])["issue_ref"] == "rian010194/cortxt#1"


def test_settled_record_is_a_delivery(api):
    """ADR-050 rule 3: no issue, no repository, no Run -- still a result."""
    outcome = api.create(record(title="Analysis", state=STATE_SETTLED))
    view = api.get(outcome["identity"])
    assert view["record"]["state"] == STATE_SETTLED
    assert view["issue_ref"] is None


def test_revise_keeps_the_earlier_version_byte_identical(api):
    """ADR-050 rule 2: revision is supersession, never mutation."""
    first = api.create(record(observations=["the store already exists"]))
    before = json.dumps(api.get(first["identity"]), sort_keys=True)

    second = api.revise(record(observations=["the store already exists",
                                             "and needs no change"]),
                        supersedes=first["record_digest"])
    assert second["outcome"] == "appended"
    assert second["identity"] != first["identity"]

    after = json.dumps(api.get(first["identity"]), sort_keys=True)
    assert after == before
    assert len(api.list_records("w-1")) == 2


def test_history_shows_the_relation_oldest_first(api):
    first = api.create(record(title="v1"))
    second = api.revise(record(title="v2"), supersedes=first["record_digest"])
    third = api.revise(record(title="v3"), supersedes=second["record_digest"])

    chain = api.history("w-1")
    assert [view["record"]["title"] for view in chain] == ["v1", "v2", "v3"]
    assert [view["supersedes"] for view in chain] == [
        None, first["record_digest"], second["record_digest"]]
    assert [view["record_digest"] for view in chain] == [
        first["record_digest"], second["record_digest"], third["record_digest"]]


def test_head_is_the_unsuperseded_record(api):
    first = api.create(record(title="v1"))
    second = api.revise(record(title="v2"), supersedes=first["record_digest"])
    assert api.head("w-1")["record_digest"] == second["record_digest"]
    assert api.head("no-such-work") is None


def test_head_refuses_to_pick_a_side_on_a_forked_chain(api):
    """A fork is a fact the operator must see, not one the API resolves."""
    first = api.create(record(title="v1"))
    left = api.revise(record(title="left"), supersedes=first["record_digest"])
    right = api.revise(record(title="right"), supersedes=first["record_digest"])

    with pytest.raises(WorkRecordError) as caught:
        api.head("w-1")
    assert caught.value.kind == "forked_chain"
    assert left["record_digest"] in str(caught.value)
    assert right["record_digest"] in str(caught.value)
    # Both branches stay readable; nothing was resolved away.
    assert len(api.history("w-1")) == 3


def test_revise_against_an_unknown_digest_is_refused(api):
    api.create(record())
    with pytest.raises(WorkRecordError) as caught:
        api.revise(record(title="v2"), supersedes="0" * 64)
    assert caught.value.kind == "invalid_input"
    assert "supersedes" in str(caught.value)
    assert len(api.list_records("w-1")) == 1


def test_revise_requires_a_supersedes_digest(api):
    with pytest.raises(WorkRecordError):
        api.revise(record(), supersedes="")


def test_same_payload_twice_is_a_re_delivery(api):
    first = api.create(record())
    again = api.create(record())
    assert again["outcome"] == "re-delivery"
    assert again["appended"] is False
    assert again["identity"] == first["identity"]
    assert len(api.list_records()) == 1


def test_different_payload_under_one_identity_is_an_explicit_conflict(api):
    """The ops API is content-addressed, so a collision needs an explicit
    identity. The store's conflict-not-merge stance is checked here to be
    intact and unsoftened -- it is not re-implemented above it."""
    first = api.create(record(title="v1"))
    outcome = api.store.append(record(title="v2"), identity=first["identity"])
    assert outcome["outcome"] == "conflict"
    assert outcome["appended"] is False
    assert api.get(first["identity"])["record"]["title"] == "v1"


def test_invalid_record_is_rejected_before_any_append(api):
    with pytest.raises(WorkRecordError):
        api.create({"record_kind": "work_record", "work_id": "w-1"})
    assert api.list_records() == []


def test_list_filters_by_kind_and_work_id(api):
    api.create(record(work_id="w-1", title="a"))
    api.create(record(work_id="w-2", title="b"))
    api.store.append({"record_type": "packaging-revision", "package_id": "p"},
                     identity="packaging-revision.other")

    assert len(api.list_records()) == 2
    assert [view["record"]["title"] for view in api.list_records("w-1")] == ["a"]
    assert api.list_records("w-3") == []


def test_get_ignores_a_foreign_record(api):
    api.store.append({"record_type": "packaging-revision", "package_id": "p"},
                     identity="packaging-revision.other")
    assert api.get("packaging-revision.other") is None
    assert api.get("0" * 64) is None
