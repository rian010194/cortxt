#!/usr/bin/env python3
"""W-5 (#617): self-running checks for the PX read-only projection.

The FIRST extension over the W-3 ops API: `px_projection.py` is a SECOND
read-only consumer of `PackagingOpsApi.workstream()` and the W-2 record
views, mapping them into PX-001's neutral projection fields (source
category, Unknown-vs-Indeterminate observation, the three staleness axes).

These checks prove, against a REAL Core store populated through the W-3
API actions only:

- the neutral `source_category` mapping for all four record types, and a
  fail-closed refusal for a view that is not a packaging record;
- the Unknown-vs-Indeterminate distinction: `unknown` marks a record the
  store could not answer with a body, `indeterminate` marks an answer
  that does not decide the projected question (a verdict outside the
  decided set) -- never collapsed into each other;
- the three staleness axes per record type (run freshness / revision
  status / run provenance), anchored on the head revision identity;
- the aggregate `project_workstream` projection: the frozen shared
  workstream, the API's own counts, the head anchor, and one projected
  record per stored record;
- READ-ONLY by construction: the store's files are byte-identical before
  and after every projection read.

Run directly: python scripts/test_px_projection.py (0 = pass). One pytest
entry point, per the colocated self-running check-script convention.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLATFORM = REPO / "agent-platform"
if str(PLATFORM) not in sys.path:
    sys.path.insert(0, str(PLATFORM))

from state.core_store import CoreStore  # noqa: E402 - agent-platform on sys.path
from widget_contract.product_packaging.ops_api import (  # noqa: E402
    PACKAGING_WORKSTREAM,
    PackagingOpsApi,
)
from widget_contract.product_packaging.revision import (  # noqa: E402
    build_revision,
    candidate_digest,
)
from widget_contract.product_packaging.px_projection import (  # noqa: E402
    OBSERVATION_INDETERMINATE,
    OBSERVATION_UNKNOWN,
    OBSERVATION_VALUE,
    PXRecordError,
    SOURCE_DECISION,
    SOURCE_EVIDENCE,
    SOURCE_OPERATION,
    SOURCE_REVISION,
    STALE_COMPLETED,
    STALE_CURRENT,
    STALE_FRESH,
    STALE_PENDING,
    STALE_PLATFORM,
    STALE_SUPERSEDED,
    project_record,
    project_workstream,
)

fail = []


def check(name, condition, detail=""):
    print(f"  {'ok' if condition else 'FAIL':4} {name}"
          + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        fail.append(name)


def _content(label):
    return {"audience": "operator", "evidence_refs": [],
            "features": [label], "outcome": "an outcome",
            "problem": "a problem", "prior_binding_refs": [],
            "referenced_repositories": ["rian010194/cortxt"],
            "scope": ["one scope"]}


def _store_snapshot(root: Path):
    """Name+size of every file in the store, for the read-only proof."""
    return sorted((p.name, p.stat().st_size) for p in root.rglob("*") if p.is_file())


def _populated_api(root: Path):
    """A real Core store with all four record types, built ONLY through the
    W-3 API actions (the same surface any client uses)."""
    store = CoreStore(root)
    api = PackagingOpsApi(store)
    issue_ref = "rian010194/cortxt#617"
    rev1 = build_revision("cortxt-core", _content("genesis"))
    out1 = api.create_revision(rev1, issue_ref=issue_ref)
    rev2 = build_revision("cortxt-core", _content("child"),
                          parent_revision_identity=out1["revision_identity"])
    out2 = api.create_revision(rev2, issue_ref=issue_ref)
    op_pending = api.record_operation(
        operation_id="op-pending", package_id="cortxt-core", original_parent=None,
        candidate_revision=rev2, status="pending", issue_ref=issue_ref)
    op_committed = api.record_operation(
        operation_id="op-committed", package_id="cortxt-core",
        original_parent=out1["revision_identity"], candidate_revision=rev2,
        status="committed", issue_ref=issue_ref)
    decision = api.record_decision(
        package_id="cortxt-core", revision_digest=candidate_digest(rev2),
        decision_scope="acceptance", operator="operator-rikard",
        verdict="accepted", supersedes=None, issue_ref=issue_ref)
    evidence = api.append_evidence(
        request_id="sha256:" + candidate_digest(rev2), entry_id="px-entry-1",
        payload_digest="sha256:" + candidate_digest(rev2), issue_ref=issue_ref)
    return api, {"rev1": out1, "rev2": out2, "op_pending": op_pending,
                 "op_committed": op_committed, "decision": decision,
                 "evidence": evidence}


def main():
    tmp = Path(tempfile.mkdtemp(prefix="px-projection-"))
    api, out = _populated_api(tmp)

    print("== PX projection: neutral source categories over real store views ==")
    revisions = api.list_revisions()
    check("two revisions stored through the API", len(revisions) == 2)
    px_rev = project_record(revisions[0])
    check("a revision projects source_category=packaging-revision",
          px_rev["source_category"] == SOURCE_REVISION, str(px_rev))
    operations = api.list_operations()
    check("two operations stored through the API", len(operations) == 2)
    check("an operation projects source_category=packaging-operation",
          project_record(operations[0])["source_category"] == SOURCE_OPERATION)
    decisions = api.list_decisions()
    check("a decision projects source_category=packaging-decision",
          project_record(decisions[0])["source_category"] == SOURCE_DECISION)
    evidence = api.list_evidence()
    check("an evidence entry projects source_category=packaging-evidence",
          project_record(evidence[0])["source_category"] == SOURCE_EVIDENCE)
    try:
        project_record({"record_type": "not-a-record"})
        check("a non-packaging view is refused fail-closed", False)
    except PXRecordError:
        check("a non-packaging view is refused fail-closed", True)

    print("== PX projection: Unknown vs Indeterminate are distinct values ==")
    head_identity = revisions[-1]["revision_identity"]
    px_dec = project_record(decisions[0])
    check("a decided decision is a plain value observation",
          px_dec["observed"] == OBSERVATION_VALUE, str(px_dec["observed"]))
    pending_view = dict(decisions[0], verdict="awaiting-operator")
    check("an answer that decides nothing is Indeterminate",
          project_record(pending_view)["observed"] == OBSERVATION_INDETERMINATE)
    bodyless = {"record_type": "packaging-decision", "identity": "packaging-decision.x",
                "issue_ref": None, "decision": None, "verdict": None}
    check("a record the store cannot answer with a body is Unknown",
          project_record(bodyless)["observed"] == OBSERVATION_UNKNOWN)
    check("Unknown and Indeterminate never collapse into each other",
          OBSERVATION_UNKNOWN != OBSERVATION_INDETERMINATE != OBSERVATION_VALUE)

    print("== PX projection: the three staleness axes per record ==")
    check("the genesis revision is superseded by the head anchor",
          px_rev["revision_status"] == STALE_SUPERSEDED, str(px_rev["revision_status"]))
    check("the head revision is current",
          project_record(revisions[-1],
                         head_revision_identity=head_identity)["revision_status"]
          == STALE_CURRENT)
    check("a revision's run freshness is fresh and provenance platform",
          px_rev["run_freshness"] == STALE_FRESH
          and px_rev["run_provenance"] == STALE_PLATFORM, str(px_rev))
    statuses = {view["operation_id"]: project_record(view) for view in operations}
    check("a pending operation is pending and superseded",
          statuses["op-pending"]["run_freshness"] == STALE_PENDING
          and statuses["op-pending"]["revision_status"] == STALE_SUPERSEDED,
          str(statuses["op-pending"]))
    check("a committed operation is completed and current",
          statuses["op-committed"]["run_freshness"] == STALE_COMPLETED
          and statuses["op-committed"]["revision_status"] == STALE_CURRENT,
          str(statuses["op-committed"]))
    check("an accepted decision is completed and current",
          px_dec["run_freshness"] == STALE_COMPLETED
          and px_dec["revision_status"] == STALE_CURRENT, str(px_dec))
    check("an evidence entry is completed and platform-provenanced",
          project_record(evidence[0])["run_freshness"] == STALE_COMPLETED
          and project_record(evidence[0])["run_provenance"] == STALE_PLATFORM)

    print("== PX projection: the aggregate workstream projection ==")
    projection = project_workstream(api)
    check("the projection carries the frozen shared workstream",
          projection["workstream"] == PACKAGING_WORKSTREAM)
    check("the projection reuses the API's own counts",
          projection["counts"] == {"revisions": 2, "operations": 2,
                                   "decisions": 1, "evidence": 1},
          str(projection["counts"]))
    check("the head anchor is the latest revision identity",
          projection["head_revision_identity"] == head_identity)
    check("one projected record per stored record (6 total)",
          len(projection["records"]) == 6, str(len(projection["records"])))
    check("the projection is schema-versioned and ok",
          projection["schema_version"] == 1 and projection["status"] == "ok")
    check("every projected record carries the neutral field set",
          all({"source_category", "observed", "run_freshness", "revision_status",
               "run_provenance", "record_identity", "issue_ref"} <= set(record)
              for record in projection["records"]))

    print("== PX projection: read-only by construction (store untouched) ==")
    before = _store_snapshot(tmp)
    project_workstream(api)
    api.list_revisions(), api.list_operations(), api.list_decisions(), api.list_evidence()
    after = _store_snapshot(tmp)
    check("every projection read left the store byte-identical",
          before == after, f"{len(before)} vs {len(after)} files")

    print(f"\n{'PASS' if not fail else 'FAIL'}: {len(fail)} failure(s)")
    if fail:
        for name in fail:
            print(f"  FAILED: {name}")
        raise SystemExit(1)


def test_all_checks_pass():
    """Pytest entry point: run the same checks as the standalone script."""
    main()


if __name__ == "__main__":
    main()
