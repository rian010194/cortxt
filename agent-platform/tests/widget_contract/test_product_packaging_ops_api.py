"""Tests for the shared packaging ops-API (W-3, #612).

The ops-API is the composition boundary between the pure W-2a modules and the
W-2b Core store: read paths are pure reads, every mutation returns the store's
insert-if-absent outcome envelope, no digest logic is duplicated and there is
no GitHub/network access. Store fixtures are temporary directories ONLY.
"""
import json
import tempfile
import unittest
from pathlib import Path

from state.core_store import CoreStore, CoreError
from widget_contract.product_packaging.ops_api import (
    DECISION_TYPE,
    EVIDENCE_TYPE,
    OPERATION_TYPE,
    PACKAGING_WORKSTREAM,
    REVISION_TYPE,
    OpsApiError,
    PackagingOpsApi,
)
from widget_contract.product_packaging.revision import build_revision, revision_identity

REQUEST_ID = "sha256:d7f131fb7d9bc94fe5af641d20397c3a432f6507af65639e7e771065ba3a0469"


def _content() -> dict:
    return {"audience": "operator", "evidence_refs": [], "features": ["unit"],
            "outcome": "an outcome", "problem": "a problem",
            "prior_binding_refs": [], "referenced_repositories": ["rian010194/cortxt"],
            "scope": ["one scope"]}


class PackagingOpsApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = CoreStore(Path(self._tmp.name))
        self.api = PackagingOpsApi(self.store)

    def _genesis(self, package_id: str = "cortxt-core"):
        revision = build_revision(package_id, _content())
        outcome = self.api.create_revision(revision)
        assert outcome["outcome"] == "appended", outcome
        return outcome


class TestReadPaths(PackagingOpsApiTestCase):
    def test_empty_store_lists_are_empty(self):
        assert self.api.list_revisions() == []
        assert self.api.list_operations() == []
        assert self.api.list_decisions() == []
        assert self.api.list_evidence() == []

    def test_list_and_get_revision_roundtrip(self):
        outcome = self._genesis()
        revisions = self.api.list_revisions()
        assert len(revisions) == 1
        view = revisions[0]
        assert view["record_type"] == REVISION_TYPE
        assert view["revision_identity"] == outcome["revision_identity"]
        assert view["package_id"] == "cortxt-core"
        assert view["parent_revision_identity"] is None  # genesis
        fetched = self.api.get_revision(outcome["revision_identity"])
        assert fetched is not None
        assert fetched["revision_identity"] == outcome["revision_identity"]
        assert fetched["revision"]["content"] == _content()
        # sha256:-prefixed lookup works too (P1-7 normalization).
        assert self.api.get_revision("sha256:" + outcome["revision_identity"]) is not None
        assert self.api.get_revision("0" * 64) is None

    def test_list_revisions_filters_by_package(self):
        self._genesis("pkg-a")
        self._genesis("pkg-b")
        assert [v["package_id"] for v in self.api.list_revisions("pkg-a")] == ["pkg-a"]
        assert len(self.api.list_revisions()) == 2

    def test_head_revision_is_latest_appended(self):
        first = self._genesis()
        parent = first["revision_identity"]
        second = self.api.create_revision(
            build_revision("cortxt-core", _content(), parent_revision_identity=parent))
        assert second["outcome"] == "appended"
        head = self.api.head_revision("cortxt-core")
        assert head["revision_identity"] == second["revision_identity"]

    def test_get_operation_and_decision_reads(self):
        self._genesis()
        digest = self.api.head_revision("cortxt-core")["revision_identity"]
        op = self.api.record_operation(
            operation_id="op-0001", package_id="cortxt-core",
            original_parent=None, candidate_revision=build_revision("cortxt-core", _content()),
            status="pending")
        view = self.api.get_operation("op-0001")
        assert view is not None
        assert view["operation_id"] == "op-0001"
        assert view["status"] == "pending"
        assert view["result_revision_identity"] is None
        decision = self.api.record_decision(
            package_id="cortxt-core", revision_digest=digest,
            decision_scope="acceptance", operator="operator-rikard", verdict="accepted")
        decisions = self.api.list_decisions()
        assert len(decisions) == 1
        assert decisions[0]["verdict"] == "accepted"
        assert decisions[0]["decision_record_identity"] == decision["decision_record_identity"]
        got = self.api.get_decision(decision["decision_record_identity"])
        assert got is not None and got["verdict"] == "accepted"

    def test_workstream_projection_is_stable_and_complete(self):
        projection = self.api.workstream()
        workstream = projection["workstream"]
        for field in ("id", "issue_id", "number", "title", "outcome", "url",
                      "mandate", "objective", "scope", "non_goals", "repo_refs"):
            assert field in workstream, field
        assert workstream["mandate"] and workstream["objective"]
        assert workstream["scope"] and workstream["non_goals"] and workstream["repo_refs"]
        assert projection["status"] == "ok"
        assert projection["store_backup_status"] == "declared-unfulfilled"  # P2-9


class TestActionPaths(PackagingOpsApiTestCase):
    def test_create_revision_returns_appended_envelope_then_re_delivery(self):
        outcome = self.api.create_revision(build_revision("cortxt-core", _content()))
        assert outcome["outcome"] == "appended"
        assert outcome["appended"] is True
        assert outcome["record_type"] == REVISION_TYPE
        assert outcome["revision_identity"] == revision_identity(
            build_revision("cortxt-core", _content()))
        retry = self.api.create_revision(build_revision("cortxt-core", _content()))
        assert retry["outcome"] == "re-delivery"
        assert retry["appended"] is False
        # The loser rendering's existing_appended_at must equal the durable
        # stored envelope's canonical appended_at seen through the read view.
        stored = self.api.get_revision(outcome["revision_identity"])
        assert retry["existing_appended_at"] == stored["appended_at"]
        assert len(self.api.list_revisions()) == 1  # nothing appended twice

    def test_conflicting_content_same_package_differs_not_overwritten(self):
        # Distinct content => distinct content identities => both appended;
        # the store never silently overwrites (append-only, CAS on identity).
        first = self.api.create_revision(build_revision("cortxt-core", _content()))
        changed = dict(_content())
        changed["outcome"] = "a different outcome"
        second = self.api.create_revision(build_revision("cortxt-core", changed))
        assert first["outcome"] == "appended" and second["outcome"] == "appended"
        assert first["identity"] != second["identity"]
        assert len(self.api.list_revisions()) == 2

    def test_record_operation_committed_and_replay_is_re_delivery(self):
        self._genesis()
        parent = self.api.head_revision("cortxt-core")["revision_identity"]
        candidate = build_revision("cortxt-core", _content(),
                                   parent_revision_identity=parent)
        appended = self.api.record_operation(
            operation_id="op-1", package_id="cortxt-core", original_parent=parent,
            candidate_revision=candidate, status="committed")
        assert appended["outcome"] == "appended"
        assert appended["operation_id"] == "op-1"
        assert appended["record_type"] == OPERATION_TYPE
        # Same operation + same candidate content => deterministic re-delivery.
        replay = self.api.record_operation(
            operation_id="op-1", package_id="cortxt-core", original_parent=parent,
            candidate_revision=candidate, status="committed")
        assert replay["outcome"] == "re-delivery"
        assert replay["appended"] is False
        # Same operation_id + DIFFERENT candidate content => explicit conflict.
        conflicting = build_revision("cortxt-core", {"different": True},
                                     parent_revision_identity=parent)
        conflict = self.api.record_operation(
            operation_id="op-1", package_id="cortxt-core", original_parent=parent,
            candidate_revision=conflicting, status="pending")
        assert conflict["outcome"] == "conflict"
        assert conflict["appended"] is False
        assert conflict["conflict"]["field"] == "payload_digest"
        assert conflict["conflict"]["values"][0] != conflict["conflict"]["values"][1]
        assert len(self.api.list_operations()) == 1

    def test_record_operation_rejects_bad_status_fail_closed(self):
        try:
            self.api.record_operation(
                operation_id="op-bad", package_id="cortxt-core",
                original_parent=None,
                candidate_revision=build_revision("cortxt-core", _content()),
                status="not-a-status")
        except OpsApiError as exc:
            assert exc.kind == "invalid_input"
        else:
            self.fail("expected OpsApiError for an invalid status")

    def test_record_decision_builds_identity_and_replay(self):
        revision = self._genesis()
        digest = revision["revision_identity"]
        first = self.api.record_decision(
            package_id="cortxt-core", revision_digest=digest,
            decision_scope="acceptance", operator="operator-rikard", verdict="accepted")
        assert first["outcome"] == "appended"
        # Identical content re-delivered renders re-delivery (idempotent).
        again = self.api.record_decision(
            package_id="cortxt-core", revision_digest=digest,
            decision_scope="acceptance", operator="operator-rikard", verdict="accepted")
        assert again["outcome"] == "re-delivery"
        # A different verdict has its own content identity (never a silent no-op).
        rejected = self.api.record_decision(
            package_id="cortxt-core", revision_digest=digest,
            decision_scope="acceptance", operator="operator-rikard", verdict="rejected")
        assert rejected["outcome"] == "appended"
        assert rejected["decision_record_identity"] != first["decision_record_identity"]

    def test_append_evidence_binding_guard_and_outcomes(self):
        self._genesis()
        revision = self.api.list_revisions()[0]
        bare = revision["record_digest"]
        prefixed = "sha256:" + bare
        # Request binding: exact whole-string equality between the envelope
        # request_id and the payload digest; a correctly prefixed request_id
        # is accepted (D4).
        ok = self.api.append_evidence(request_id=prefixed, entry_id="ev-0001",
                                      payload_digest=prefixed)
        assert ok["outcome"] == "appended"
        assert ok["record_type"] == EVIDENCE_TYPE
        # Same identity + same payload => re-delivery, nothing appended.
        again = self.api.append_evidence(request_id=prefixed, entry_id="ev-0001",
                                         payload_digest=prefixed)
        assert again["outcome"] == "re-delivery"
        assert again["appended"] is False
        # A new entry id is a new identity => a new evidence version appends.
        second = self.api.append_evidence(request_id=prefixed, entry_id="ev-0002",
                                          payload_digest=prefixed)
        assert second["outcome"] == "appended"
        # Binding mismatch: the request_id WITHOUT its prefix against a
        # prefixed payload is rejected fail-closed BEFORE any store write
        # (the normalization rule never leaks into request binding).
        with self.assertRaises(OpsApiError):
            self.api.append_evidence(request_id=bare, entry_id="ev-0003",
                                     payload_digest=prefixed)
        assert len(self.api.list_evidence()) == 2

    def test_invalid_revision_is_rejected_fail_closed(self):
        try:
            self.api.create_revision({"package_id": "x", "content": {}, "extra": 1})
        except OpsApiError as exc:
            assert exc.kind == "invalid_input"
        else:
            self.fail("expected OpsApiError for an invalid revision")

    def test_store_integrity_error_maps_to_503(self):
        def explode(_payload, **_kwargs):
            raise CoreError("integrity_error", "tampered record", 6)

        self.store.append = explode  # type: ignore[method-assign]
        try:
            self.api.create_revision(build_revision("cortxt-core", _content()))
        except OpsApiError as exc:
            assert exc.kind == "integrity_error"
            assert exc.http_status == 503
        else:
            self.fail("expected OpsApiError")

    def test_issue_ref_validation_fails_closed(self):
        with self.assertRaises(OpsApiError):
            self.api.create_revision(build_revision("cortxt-core", _content()),
                                     issue_ref="../traversal")


class TestPackagingWorkstreamOracle(PackagingOpsApiTestCase):
    def test_workstream_carries_mandate_objective_scope_non_goals_repo_refs(self):
        workstream = self.api.workstream()["workstream"]
        assert workstream == PACKAGING_WORKSTREAM
        assert workstream["id"] == "WS-606"
        assert workstream["mandate"] and workstream["objective"]
        assert isinstance(workstream["scope"], list) and workstream["scope"]
        assert isinstance(workstream["non_goals"], list) and workstream["non_goals"]
        assert all(ref.startswith("rian010194/cortxt#")
                   for ref in workstream["repo_refs"])

    def test_counts_reflect_store_state(self):
        assert self.api.workstream()["counts"] == {
            "revisions": 0, "operations": 0, "decisions": 0, "evidence": 0}
        self._genesis()
        assert self.api.workstream()["counts"]["revisions"] == 1


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
